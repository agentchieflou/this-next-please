# PYTHON_ARGCOMPLETE_OK
"""ad-fleet: run several headless Copilot agents, one per repository, from one place.

Epic #91's spine (#93). A plain `ad-*` command, so a fleet can be driven from any shell long before
there is a dashboard -- and the dashboard, when it comes, is another client of the same module
rather than a second source of truth.

    ad-fleet repo add C:/repos/rdsd-pbi-reporting
    ad-fleet start rdsd-pbi-reporting RDSD-101
    ad-fleet status
    ad-fleet send rdsd-pbi-reporting "approved, continue"
    ad-fleet logs rdsd-pbi-reporting
    ad-fleet stop rdsd-pbi-reporting

What the agent is allowed to do is configuration, not a flag buried in the code:
`ad-fleet status --show-launch` prints the exact command line, allow-list and all.
"""
from __future__ import annotations
import argparse
import sys

from . import completion
from . import config as C
from . import toon
from . import ui
from .console import utf8_stdout
from .fleet import agentstate, events as E, launch, supervisor
from .fleet.registry import Registry, RegistryError, fleet_dir
from .version import add_version, version_string

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2


def _refuse(source: str, err) -> int:
    print(toon.encode({"meta": {"ok": False, "source": source, "error": err.msg,
                                "hint": getattr(err, "hint", "")}}))
    return EXIT_REFUSED


def _emit(source: str, meta: dict, tables: dict | None = None) -> int:
    payload = {"meta": {"ok": True, "source": source, **meta}}
    payload.update(tables or {})
    print(toon.encode(payload))
    return EXIT_OK


# ----------------------------------------------------------------------------------- the verbs


def cmd_repo_add(a) -> int:
    try:
        repo = Registry().add(a.path, a.name)
    except RegistryError as e:
        return _refuse("ad-fleet repo add", e)
    return _emit("ad-fleet repo add", {"repo": repo.name, "path": repo.path,
                                       "jira_project": repo.jira_project or "",
                                       "fleet_dir": fleet_dir()})


def cmd_repo_rm(a) -> int:
    try:
        repo = Registry().remove(a.name)
    except RegistryError as e:
        return _refuse("ad-fleet repo rm", e)
    return _emit("ad-fleet repo rm", {"repo": repo.name, "path": repo.path})


def cmd_repo_list(a) -> int:
    reg = Registry()
    rows = [[r.name, r.path, r.jira_project or "", r.added or ""] for r in reg.sorted()]
    if ui.on():
        ui.table(["repo", "path", "jira", "added"], rows, title="fleet repositories")
        return EXIT_OK
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet repo list",
                                "repos": len(rows), "fleet_dir": fleet_dir()}}))
    print(toon.table("repos", ["repo", "path", "jira", "added"], rows))
    return EXIT_OK


def cmd_start(a) -> int:
    try:
        lock = supervisor.start(a.repo, key=a.ticket, prompt=a.prompt, force=a.force, cfg=C.load())
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError) as e:
        return _refuse("ad-fleet start", e)
    return _emit("ad-fleet start", {"repo": a.repo, "ticket": lock.get("ticket", ""),
                                    "pid": lock["pid"], "prompt": lock["prompt"],
                                    "next": f"ad-fleet status --repo {a.repo}"})


def cmd_send(a) -> int:
    try:
        lock = supervisor.send(a.repo, a.message, cfg=C.load())
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError) as e:
        return _refuse("ad-fleet send", e)
    return _emit("ad-fleet send", {"repo": a.repo, "pid": lock["pid"],
                                   "session": lock.get("session", "")})


def cmd_stop(a) -> int:
    reg = Registry()
    names = [r.name for r in reg.sorted()] if a.all else [a.repo]
    if not a.all and not a.repo:
        print(toon.encode({"meta": {"ok": False, "source": "ad-fleet stop",
                                    "error": "name a repo, or pass --all",
                                    "hint": "ad-fleet stop <repo>   |   ad-fleet stop --all"}}))
        return EXIT_REFUSED
    results = []
    for name in names:
        try:
            results.append(supervisor.stop(name))
        except (RegistryError, supervisor.SupervisorError) as e:
            results.append({"repo": name, "stopped": False, "detail": e.msg})
    stopped = sum(1 for r in results if r.get("stopped"))
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet stop", "stopped": stopped,
                                "asked": len(results)}}))
    print(toon.table("agents", ["repo", "stopped", "detail"],
                     [[r["repo"], r.get("stopped", False), r.get("detail", "")] for r in results]))
    return EXIT_OK


COLUMNS = ["repo", "agent", "ticket", "phase", "turns", "premium_requests", "denied_tools",
           "last_event", "pid"]


def cmd_status(a) -> int:
    try:
        rows = supervisor.status()
    except RegistryError as e:
        return _refuse("ad-fleet status", e)
    if a.repo:
        rows = [r for r in rows if r["repo"] == a.repo]

    if a.show_launch:
        cfg = C.load()
        try:
            allow, deny = launch.allow_tools(cfg), launch.deny_tools(cfg)
            launch.check_no_blanket_permission(allow + deny)
        except launch.LaunchError as e:
            return _refuse("ad-fleet status", e)
        print(toon.encode({"meta": {"ok": True, "source": "ad-fleet status --show-launch",
                                    "agents": len(rows), "fleet_dir": fleet_dir()}}))
        print(toon.table("allow_tools", ["pattern"], [[p] for p in allow]))
        print(toon.table("deny_tools", ["pattern"], [[p] for p in deny]))
        for row in rows:
            lock = supervisor.read_lock(row["repo"])
            if lock.get("launch"):
                print(toon.table(f"launch_{row['repo']}", ["arg"], [[x] for x in lock["launch"]]))
        return EXIT_OK

    table = [[r.get(c, "") for c in COLUMNS] for r in rows]
    if ui.on():
        ui.table(COLUMNS, table, title="fleet")
        return EXIT_OK
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet status", "agents": len(rows),
                                "fleet_dir": fleet_dir()}}))
    print(toon.table("agents", COLUMNS, table))
    return EXIT_OK


def cmd_logs(a) -> int:
    try:
        Registry().get(a.repo)
    except RegistryError as e:
        return _refuse("ad-fleet logs", e)
    events = supervisor.read_events(a.repo, raw=a.raw, limit=a.limit)
    if a.raw:
        import json

        for event in events:
            print(json.dumps(event))
        return EXIT_OK
    rows = []
    for event in events:
        data = event.get("data") or {}
        detail = (data.get("content") or data.get("toolName") or
                  ((data.get("error") or {}).get("code") if isinstance(data.get("error"), dict) else "")
                  or "")
        rows.append([str(event.get("timestamp", ""))[11:19], event.get("type", ""),
                     str(detail).replace("\n", " ")[:120]])
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet logs", "repo": a.repo,
                                "events": len(rows)}}))
    print(toon.table("events", ["at", "event", "detail"], rows))
    return EXIT_OK


# ------------------------------------------------------------------------------------- parser


def cmd_events(a) -> int:
    reg = Registry()
    try:
        repo = reg.get(a.repo)
    except RegistryError as e:
        return _refuse("ad-fleet events", e)

    E.refresh(a.repo, repo.path, repo_state=repo.state())
    kinds = tuple(a.kind) if a.kind else None
    stream = E.read(a.repo, since=a.since, kinds=kinds, limit=a.limit)

    if a.raw:
        import json

        for ev in stream:
            print(json.dumps(ev, ensure_ascii=False))
        return EXIT_OK

    derived = agentstate.derive(E.read(a.repo), live=bool(supervisor.live(a.repo)))
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet events", "repo": a.repo,
                                "events": len(stream), "state": derived["state"],
                                "why": derived["why"],
                                "needs_human": agentstate.needs_the_human(derived["state"])}}))
    rows = [[e.get("seq"), str(e.get("ts", ""))[11:19], e.get("kind"),
             _summarize(e).replace("\n", " ")[:120]] for e in stream]
    print(toon.table("events", ["seq", "at", "kind", "detail"], rows))
    return EXIT_OK


def _summarize(ev: dict) -> str:
    """One line a person can read. The full payload is always there under --raw."""
    data = ev.get("data") or {}
    for key in ("text", "unblock", "question", "message", "tool", "to", "url", "artifact",
                "session", "premium_requests", "exit_code", "type"):
        if data.get(key) not in (None, ""):
            return f"{key}={data[key]}"
    return ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ad-fleet",
        description="Run several headless Copilot agents, one per repository, from one place.")
    add_version(p)
    p.add_argument("--pretty", action="store_true", help="force human-facing table format")
    sub = p.add_subparsers(dest="subcommand", metavar="COMMAND")

    repo = sub.add_parser("repo", help="register the repositories the fleet may run agents in")
    repo_sub = repo.add_subparsers(dest="repo_command", metavar="COMMAND")
    add = repo_sub.add_parser("add", help="register a repository (needs AGENTS.md and .agent/state.json)")
    add.add_argument("path")
    add.add_argument("--name", help="what the fleet calls it (default: the folder name)")
    add.set_defaults(fn=cmd_repo_add)
    rm = repo_sub.add_parser("rm", help="forget a repository (its files are untouched)")
    rm.add_argument("name")
    rm.set_defaults(fn=cmd_repo_rm)
    repo_sub.add_parser("list", help="the registered repositories").set_defaults(fn=cmd_repo_list)
    repo.set_defaults(fn=cmd_repo_list)

    start = sub.add_parser("start", help="start an agent in a repository")
    start.add_argument("repo")
    start.add_argument("ticket", nargs="?", help="the ticket key the agent should work")
    start.add_argument("--prompt", help="an explicit prompt instead of the ticket template")
    start.add_argument("--force", action="store_true",
                       help="start even if the repo is mid-ticket or holds a stale lock")
    start.set_defaults(fn=cmd_start)

    send = sub.add_parser("send", help="continue an agent's session with another message")
    send.add_argument("repo")
    send.add_argument("message")
    send.set_defaults(fn=cmd_send)

    stop = sub.add_parser("stop", help="stop an agent and everything it started")
    stop.add_argument("repo", nargs="?")
    stop.add_argument("--all", action="store_true", help="stop every agent")
    stop.set_defaults(fn=cmd_stop)

    status = sub.add_parser("status", help="one row per registered repository")
    status.add_argument("--repo", help="just this one")
    status.add_argument("--show-launch", action="store_true", dest="show_launch",
                        help="print the exact command line and tool allow-list instead")
    status.set_defaults(fn=cmd_status)

    ev = sub.add_parser("events", help="the normalized event stream, and the agent's derived state")
    ev.add_argument("repo")
    ev.add_argument("--since", type=int, default=0, help="only events after this seq")
    ev.add_argument("--kind", action="append", help="only these kinds (repeatable)")
    ev.add_argument("--limit", type=int, default=60, help="how many events (0 = all)")
    ev.add_argument("--raw", action="store_true", help="the normalized JSON, one object per line")
    ev.set_defaults(fn=cmd_events)

    logs = sub.add_parser("logs", help="the raw Copilot event stream, unnormalized")
    logs.add_argument("repo")
    logs.add_argument("--raw", action="store_true", help="the untouched JSONL, ephemeral events included")
    logs.add_argument("--limit", type=int, default=60, help="how many events (0 = all)")
    logs.set_defaults(fn=cmd_logs)

    return p


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = build_parser()
    completion.autocomplete(parser)
    a = parser.parse_args(argv)

    if not getattr(a, "fn", None):
        parser.print_help()
        return EXIT_OK

    import os

    old = os.environ.get("AGENTDATA_UI")
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.fn(a)
    finally:
        if getattr(a, "pretty", False):
            if old is None:
                os.environ.pop("AGENTDATA_UI", None)
            else:
                os.environ["AGENTDATA_UI"] = old
            ui.reset_cache()


if __name__ == "__main__":
    sys.exit(main())
