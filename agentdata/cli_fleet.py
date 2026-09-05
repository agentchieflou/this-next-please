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
from .fleet import (agentstate, approval, board as B, events as E, launch, notify as N,
                    serve as S, supervisor)
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
    cfg = C.load()
    # The board is consulted only if it is already cached. Being unable to reach Jira must never
    # stop an operator starting an agent -- the guard rails it feeds are a courtesy, not a gate.
    rows = (B.read_cache() or {}).get("rows") or []
    try:
        lock = supervisor.start(a.repo, key=a.ticket, prompt=a.prompt, force=a.force, cfg=cfg,
                                cross_project=a.cross_project, board_rows=rows)
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError) as e:
        return _refuse("ad-fleet start", e)
    return _emit("ad-fleet start", {"repo": a.repo, "ticket": lock.get("ticket", ""),
                                    "summary": lock.get("summary", ""),
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
                                "fleet_dir": fleet_dir(), "toast": N.toast_status(C.load())}}))
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

    try:
        E.refresh(a.repo, repo.path, repo_state=repo.state())
    except E.Busy:
        # Another writer holds the stream. Read what is already normalized rather than fail: the
        # next reader picks up whatever this one could not merge.
        pass
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


def cmd_board(a) -> int:
    """The operator's own tickets, and where each one probably belongs.

    Read-only, always: only agents write to Jira, and only through the approval gate (#95).
    """
    try:
        data = B.board(cfg=C.load(), force=a.refresh)
    except B.BoardError as e:
        return _refuse("ad-fleet board", e)
    rows = B.with_suggestions(data["rows"])
    if a.project:
        rows = [r for r in rows if r["project"] == a.project.upper()]
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet board", "tickets": len(rows),
                                "jql": data["jql"],
                                "from": f"cache, {data['age_s']}s old" if data["cached"] else "jira"}}))
    print(toon.table("board", ["key", "status", "type", "summary", "repo", "why"],
                     [[r["key"], r["status"], r["type"], r["summary"][:70],
                       r["suggested"]["repo"] or "-",
                       r["suggested"]["hint"] or r["suggested"]["why"]] for r in rows]))
    return EXIT_OK


def cmd_history(a) -> int:
    rows = B.history(since=B.since_seconds(a.since))
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet history", "runs": len(rows),
                                "since": a.since,
                                "premium_requests": round(sum(r["premium_requests"] for r in rows), 2)}}))
    print(toon.table("history", ["started", "repo", "ticket", "summary", "state", "phase",
                                 "turns", "premium_requests"],
                     [[str(r["started"])[:16], r["repo"], r["ticket"] or "-", r["summary"][:50],
                       r["state"], r["phase"] or "-", r["turns"], r["premium_requests"]]
                      for r in rows]))
    return EXIT_OK


def cmd_notify(a) -> int:
    """`test` fires one of each severity; `tail` prints what *would* fire, changing nothing.

    `tail` is the point of this verb. A rule can be tuned against a real captured stream instead of
    by starting four agents and waiting for one of them to get stuck.
    """
    cfg = C.load()
    if a.what == "test":
        items = N.deliver(N.samples(), cfg=cfg, url=_serve_url())
        print(toon.encode({"meta": {"ok": True, "source": "ad-fleet notify test",
                                    "toast": N.toast_status(cfg),
                                    "quiet_hours": N.settings(cfg)["quiet_hours"] or "off",
                                    "sent": len(items)}}))
        print(toon.table("notifications", ["severity", "title", "toasted"],
                         [[i["severity"], i["title"], i["toasted"]] for i in items]))
        return EXIT_OK

    if a.what == "tail":
        would = N.sweep(cfg=cfg, dry_run=True)
        s = N.settings(cfg)
        print(toon.encode({"meta": {"ok": True, "source": "ad-fleet notify tail",
                                    "would_fire": len(would), "cooldown_s": s["cooldown"],
                                    "idle_minutes": s["idle_minutes"],
                                    "quiet_hours": s["quiet_hours"] or "off",
                                    "note": "a dry run: nothing was sent and no cooldown was spent"}}))
        print(toon.table("would_fire", ["seq", "repo", "severity", "title", "why"],
                         [[i["seq"], i["repo"], i["severity"], i["title"],
                           i["body"].replace("\n", " ")[:80]] for i in would]))
        return EXIT_OK

    recent = N.read_log(a.limit)
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet notify list",
                                "notifications": len(recent), "toast": N.toast_status(cfg)}}))
    print(toon.table("notifications", ["at", "repo", "severity", "title", "toasted"],
                     [[str(i.get("at", ""))[11:19], i.get("repo"), i.get("severity"),
                       i.get("title"), i.get("toasted")] for i in recent]))
    return EXIT_OK


def _serve_url() -> str:
    """Where the dashboard is, if one is running. A toast that cannot deep-link still notifies."""
    try:
        import json

        return str(json.loads(open(S.serve_file(), encoding="utf-8").read()).get("url") or "")
    except (OSError, ValueError):
        return ""


def cmd_serve(a) -> int:
    """The multi-viewer. Blocks until Ctrl-C; everything it shows comes from #94's stream."""
    try:
        server, token = S.build(a.port)
    except S.ServeError as e:
        return _refuse("ad-fleet serve", e)
    url = S.url_for(server, token)
    S.record(server, token)
    _emit("ad-fleet serve", {"url": url, "port": server.server_address[1],
                             "bound": "127.0.0.1 only",
                             "note": "the token in the URL is required on every request; "
                                     "stop with Ctrl-C"})
    sys.stdout.flush()
    if a.open:
        import webbrowser

        webbrowser.open(url)
    S.run(server)
    return EXIT_OK


def cmd_approvals(a) -> int:
    waiting = approval.pending()
    if a.raw:
        import json

        for record in waiting:
            print(json.dumps(record, ensure_ascii=False))
        return EXIT_OK
    rows = [[r.get("id"), r.get("repo"), r.get("ticket") or "", r.get("kind"),
             _mins(r.get("waiting_s", 0)), str(r.get("summary") or "")[:90]] for r in waiting]
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet approvals",
                                "pending": len(waiting),
                                "note": "each one is an agent blocked at a write, waiting for you"
                                        if waiting else "nothing is waiting"}}))
    print(toon.table("approvals", ["id", "repo", "ticket", "kind", "waiting", "summary"], rows))
    return EXIT_OK


def cmd_approval_show(a) -> int:
    record = approval.read_request(a.id)
    if not record:
        return _refuse("ad-fleet approval", approval.ApprovalError(
            f"no approval called {a.id!r}", "`ad-fleet approvals` lists what is waiting"))
    decided = approval.read_decision(a.id)
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet approval", "id": a.id,
                                "repo": record.get("repo"), "ticket": record.get("ticket") or "",
                                "kind": record.get("kind"), "summary": record.get("summary"),
                                "created": record.get("created"),
                                "decision": decided.get("decision") or "waiting"},
                       "payload": record.get("payload") or {}}))
    return EXIT_OK


def _decide(a, state: str, reason: str = "") -> int:
    source = "ad-fleet approve" if state == approval.APPROVED else "ad-fleet deny"
    try:
        done = approval.decide(a.id, state, reason=reason)
    except approval.ApprovalError as e:
        return _refuse(source, e)
    return _emit(source,
                 {"id": done["id"], "repo": done.get("repo"), "kind": done.get("kind"),
                  "decision": done["decision"], "by": done["by"],
                  "note": "the agent is released and will run the command it showed you"
                          if state == approval.APPROVED else
                          "the agent will log friction with your reason and stop"})


def cmd_approve(a) -> int:
    return _decide(a, approval.APPROVED, a.comment or "")


def cmd_deny(a) -> int:
    return _decide(a, approval.DENIED, a.reason or "")


def _mins(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds < 90:
        return f"{seconds}s"
    return f"{seconds // 60}m" if seconds < 5400 else f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


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
    start.add_argument("--cross-project", action="store_true", dest="cross_project",
                       help="start a ticket whose project is not this repo's jira_project")
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

    ap = sub.add_parser("approvals", help="writes waiting for a click, oldest first")
    ap.add_argument("--raw", action="store_true", help="one JSON object per pending approval")
    ap.set_defaults(fn=cmd_approvals)

    show = sub.add_parser("approval", help="one approval in full, including the dry-run payload")
    show.add_argument("id")
    show.set_defaults(fn=cmd_approval_show)

    ok = sub.add_parser("approve", help="release a waiting write")
    ok.add_argument("id")
    ok.add_argument("--comment", help="a note the agent can quote")
    ok.set_defaults(fn=cmd_approve)

    no = sub.add_parser("deny", help="refuse a waiting write; the agent logs friction and stops")
    no.add_argument("id")
    no.add_argument("--reason", required=True, help="why. The agent quotes this, so write it for whoever picks the ticket up")
    no.set_defaults(fn=cmd_deny)

    brd = sub.add_parser("board", help="your Jira tickets, and which repo each one belongs to")
    brd.add_argument("--refresh", action="store_true", help="ask Jira now instead of using the cache")
    brd.add_argument("--project", help="only this Jira project")
    brd.set_defaults(fn=cmd_board)

    hist = sub.add_parser("history", help="what was dispatched, how it ended, what it cost")
    hist.add_argument("--since", default="7d", help="7d | 12h | 90m (default 7d)")
    hist.set_defaults(fn=cmd_history)

    note = sub.add_parser("notify", help="what the fleet would tell you, and what it has")
    note.add_argument("what", nargs="?", default="list", choices=["list", "test", "tail"],
                      help="list: recent; test: one of each severity; tail: what would fire now")
    note.add_argument("--limit", type=int, default=50, help="how many to list")
    note.set_defaults(fn=cmd_notify)

    srv = sub.add_parser("serve", help="the multi-viewer: one local page, one tile per agent")
    srv.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (0 picks a free one)")
    srv.add_argument("--open", action="store_true", help="open it in the default browser")
    srv.set_defaults(fn=cmd_serve)

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
