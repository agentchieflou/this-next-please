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
import os
import sqlite3
import sys

from . import completion
from . import config as C
from . import textio
from . import toon
from . import ui
from .console import prompt as ask_line, utf8_stdout
from .fleet import (agentstate, approval, board as B, catalogue as CAT, events as E, handoff,
                    inbox as IN, launch, lifecycle as L, links as LK, notify as N, opener as O,
                    poll as P, preflight as PF, scan as SC, serve as S, supervisor)
from .fleet.registry import Registry, RegistryError, fleet_dir
from .version import add_version, version_string

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2


def _refuse(source: str, err) -> int:
    code = getattr(err, "code", "") or "refused"
    meta = {"ok": False, "source": source, "error": err.msg,
            "hint": getattr(err, "hint", ""), "refused": code, "code": code}
    print(toon.encode({"meta": meta}))
    return EXIT_REFUSED


def _emit(source: str, meta: dict, tables: dict | None = None) -> int:
    payload = {"meta": {"ok": True, "source": source, **meta}}
    payload.update(tables or {})
    print(toon.encode(payload))
    return EXIT_OK


# ----------------------------------------------------------------------------------- the verbs


def cmd_repo_add(a) -> int:
    if getattr(a, "scan", ""):
        return _repo_add_scan(a)
    if not a.path:
        return _refuse("ad-fleet repo add", RegistryError(
            "name the repository to register",
            "`ad-fleet repo add <path>`, or `ad-fleet repo add --scan <parent folder>` to be "
            "shown every project under one folder"))
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
    brief = getattr(a, "brief", None)
    brief_file = getattr(a, "brief_file", None)
    try:
        if brief_file:
            if brief:
                raise handoff.HandoffError(
                    "pass --brief or --brief-file, not both",
                    "one brief per dispatch; the file wins nothing over the flag, so choose",
                    code="brief_ambiguous")
            brief = handoff.read_brief_file(brief_file)
        lock = supervisor.start(a.repo, key=a.ticket, prompt=a.prompt, force=a.force, cfg=cfg,
                                cross_project=a.cross_project, board_rows=rows,
                                resume=getattr(a, "resume", None), new=getattr(a, "new", False),
                                brief=brief)
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError,
            handoff.HandoffError) as e:
        return _refuse("ad-fleet start", e)
    return _emit("ad-fleet start", {"repo": a.repo, "ticket": lock.get("ticket", ""),
                                    "summary": lock.get("summary", ""),
                                    "session": lock.get("session", ""),
                                    "pid": lock["pid"], "prompt": lock["prompt"],
                                    "next": f"ad-fleet status --repo {a.repo}"})


def cmd_preflight(a) -> int:
    """Is this ticket ready to hand over? The dispatch card, as TOON.

    Exit 0 whatever the verdict, `blocked` included: a verdict is an answer, not a refusal. The
    refusal happens at `ad-fleet start`, in the same words, and this verb exists so the operator can
    read them before spending a turn rather than after.
    """
    card = PF.preflight(a.ticket, getattr(a, "repo", "") or "")
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet preflight",
                                "ticket": card["key"], "repo": card["repo"] or "-",
                                "verdict": card["verdict"], "rows": len(card["rows"]),
                                "cost": "no premium request"}}))
    print(toon.table("preflight", ["row", "value", "verdict", "why"],
                     [[r["row"], r["value"], r["verdict"], r.get("why") or "-"]
                      for r in card["rows"]]))
    return EXIT_OK


def cmd_restart(a) -> int:
    """Bring an agent back on the session it was already having, not on a fresh reading of the
    ticket -- it has a plan and possibly edits, and starting over repeats both at full price."""
    try:
        lock = supervisor.restart(a.repo, cfg=C.load(), force=a.force)
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError) as e:
        return _refuse("ad-fleet restart", e)
    return _emit("ad-fleet restart", {"repo": a.repo, "pid": lock["pid"],
                                      "session": lock.get("session", ""),
                                      "ticket": lock.get("ticket", ""),
                                      "restarts": lock.get("restarts", 1)})


def cmd_reset(a) -> int:
    """Stop and resume in one verb, because "it is stuck, make it go again" is one intention.

    The dashboard's Reset button calls the same function, so the two cannot drift.
    """
    try:
        out = supervisor.reset(a.repo, cfg=C.load(), force=a.force)
    except (RegistryError, supervisor.SupervisorError, launch.LaunchError) as e:
        return _refuse("ad-fleet reset", e)
    return _emit("ad-fleet reset", {"repo": a.repo, "stopped": out["stopped"], "pid": out["pid"],
                                    "session": out.get("session", ""),
                                    "ticket": out.get("ticket", ""),
                                    "restarts": out.get("restarts", 1),
                                    "next": f"ad-fleet status --repo {a.repo}"})


def cmd_adopt(a) -> int:
    """Take on a session the fleet did not start, so the tile stops showing an older one."""
    from .fleet import adopt as A

    if a.list:
        rows = A.candidates()
        return _emit("ad-fleet adopt", {"found": len(rows), "sessions": rows,
                                        "next": "ad-fleet adopt <repo>" if rows else ""})
    try:
        out = A.adopt(a.repo, pid=a.pid)
    except (RegistryError, A.AdoptError) as e:
        return _refuse("ad-fleet adopt", e)
    return _emit("ad-fleet adopt", {**out, "next": f"ad-fleet status --repo {a.repo}"})


def cmd_release(a) -> int:
    """Hand an adopted session back. Never touches a lock the supervisor wrote."""
    from .fleet import adopt as A

    try:
        out = A.release(a.repo)
    except (RegistryError, A.AdoptError) as e:
        return _refuse("ad-fleet release", e)
    return _emit("ad-fleet release", out)


def cmd_gc(a) -> int:
    result = L.gc(a.days)
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet gc", "days": a.days,
                                "removed": len(result["removed"]),
                                "left_alone": ", ".join(result["kept_running"]) or "none",
                                "note": "rotated logs and answered approvals only; a live "
                                        "`events.norm.jsonl` is what `ad-fleet history` reads"}}))
    print(toon.table("removed", ["path"], [[p] for p in result["removed"]]))
    return EXIT_OK


def cmd_doctor(a) -> int:
    """`ad-fleet doctor` is `ad-doctor --only fleet`, so an operator who lives in `ad-fleet` does
    not have to know that the checks live somewhere else."""
    from .setup.wizard import run_doctor

    if a.pretty:
        import os

        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    return run_doctor(["--only", "fleet"])


def cmd_send(a) -> int:
    try:
        lock = supervisor.send(a.repo, a.message, cfg=C.load(), force=a.force)
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


COLUMNS = ["repo", "agent", "ticket", "session", "phase", "turns", "premium_requests", "budget",
           "denied_tools", "last_event", "pid", "accent"]


def cmd_status(a) -> int:
    if getattr(a, "polls", False):
        return _status_polls(a)
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

    from . import theme
    cfg = C.load()
    budget = L.settings(cfg)["budget_per_agent"] if cfg else 0.0
    for row in rows:
        row["budget"] = f"{budget:g}" if budget else "-"
        t_name = C.get(cfg, f"theme.projects.{row['repo']}") or C.get(cfg, "theme.default") or "none"
        try:
            t = theme.get(t_name, seed=row["repo"])
            row["accent"] = t.accent or ""
        except Exception:
            row["accent"] = ""
    table = [[r.get(c, "") for c in COLUMNS] for r in rows]
    if ui.on():
        ui.table(COLUMNS, table, title="fleet")
        return EXIT_OK
    spent_today = round(sum(float(r.get("premium_requests") or 0) for r in rows), 2)
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet status", "agents": len(rows),
                                "fleet_dir": fleet_dir(), "toast": N.toast_status(cfg),
                                "premium_requests": spent_today,
                                "skills": _skills_warning()}}))
    print(toon.table("agents", COLUMNS, table))
    return EXIT_OK


def _skills_warning() -> str:
    """Skills load at session start, so an agent that was running when `ad-update` ran is still
    holding last week's instructions -- and nothing about its behaviour would say so."""
    try:
        from . import update as U

        skills = U.skills_state()
        if not U.stale(skills):
            return ""
        live = [r["repo"] for r in supervisor.status() if r.get("pid")]
        if not live:
            return ""
        return (f"the installed skills are older than the CLI, and {', '.join(live)} loaded them "
                f"at session start: `ad-update --skills`, then `ad-fleet restart <repo>`")
    except Exception:                        # noqa: BLE001 - a status row must never fail the command
        return ""


def cmd_sessions(a) -> int:
    from .fleet import sessions as S

    reg = Registry()
    try:
        repo = reg.get(a.repo)
    except RegistryError as e:
        return _refuse("ad-fleet sessions", e)

    if getattr(a, "rename_verb", None) == "rename" and getattr(a, "rename_id", None) and getattr(a, "rename_title", None):
        try:
            renamed = S.rename_session(a.repo, a.rename_id, a.rename_title)
        except KeyError as e:
            return _refuse("ad-fleet sessions", e)
        return _emit("ad-fleet sessions rename", {"repo": a.repo, "session": renamed})

    if getattr(a, "rebuild", False):
        rows = S.rebuild_sessions(a.repo, repo_path=repo.path)
    else:
        rows = S.load_sessions(a.repo)
        if not rows:
            rows = S.rebuild_sessions(a.repo, repo_path=repo.path)

    cols = ["id", "title", "ticket", "first_seen", "last_seen", "runs", "ended", "cost", "source"]
    table_rows = [[r.get("id", ""), r.get("title", ""), r.get("ticket", "") or "-",
                   str(r.get("first_seen", ""))[:16], str(r.get("last_seen", ""))[:16],
                   r.get("runs", 1), r.get("ended", "") or "-", r.get("cost", 0.0),
                   r.get("source", "fleet")] for r in rows]
    if ui.on():
        ui.table(cols, table_rows, title=f"fleet sessions: {a.repo}")
        return EXIT_OK
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet sessions",
                                "repo": a.repo, "sessions": len(rows)}}))
    print(toon.table("sessions", cols, table_rows))
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


# ------------------------------------------------------------------------------- the desk (#122)
#
# Five verbs that turn a folder full of checkouts into a desk: `repo add --scan` proposes what to
# register, `index`/`where`/`show` answer "which project owns this" without opening a tab, `inbox`
# routes what the browser dropped in Downloads, and `quickstart` runs the lot in one command. Every
# one of them is a thin wrapper: the reading, the allow-lists and the refusals live in
# `fleet/scan.py`, `catalogue.py`, `links.py`, `poll.py` and `inbox.py`, and this file only decides
# what a person is asked and what gets printed.

# The proposal's columns, in the order #129 fixes them. `why` is last because it is the only one
# that is a sentence: everything left of it is a fact the operator can scan down.
SCAN_COLUMNS = ["path", "name", "branch", "has_agents_md", "has_state", "jira_project", "pbip",
                "last_commit_age_days", "already_registered", "why"]

# `ad-fleet serve --layout roles` is `?layout=roles` on the page. The flag is this file's and the
# rendering is the dashboard's, so the query parameter's name is written down once, here, rather
# than spelled twice and drifting the first time one side is renamed.
LAYOUT_PARAM = "layout"
LAYOUTS = ("grid", "roles", "screens")


def _catalogue(source: str):
    """Open `~/.agentdata/fleet/catalogue.sqlite`, or refuse in the house shape.

    Returns `(catalogue, exit_code)`; the catalogue is None when it could not be opened, and the
    refusal has already been printed. A half-written sqlite file is a real laptop failure -- OneDrive
    syncing the folder mid-write is enough -- and the honest answer is that the file is a cache,
    deleting it costs an index run and nothing else.
    """
    try:
        return CAT.Catalogue.open(), EXIT_OK
    except (sqlite3.Error, CAT.CatalogueError, OSError) as e:
        path = os.path.join(fleet_dir(), CAT.CATALOGUE)
        return None, _refuse(source, CAT.CatalogueError(
            f"the catalogue could not be opened: {path} ({e})",
            "delete that file and run `ad-fleet index --rebuild`; it is a cache of what the repos "
            "already say, so nothing in it is irreplaceable"))


# ---------------------------------------------------------------- repo add --scan (#129)


def _pick(candidates: list, only: str) -> tuple[list, list[str]]:
    """`--only a,b` against the proposal's names, plus the names that matched nothing.

    An unmatched name is reported rather than ignored: the operator typed it, and a
    `--yes --only rdsd` that quietly registers nothing looks exactly like a run that worked.
    """
    if not only:
        return list(candidates), []
    by_name = {c.name.lower(): c for c in candidates}
    picked, unknown = [], []
    for name in [n.strip() for n in str(only).split(",") if n.strip()]:
        found = by_name.get(name.lower())
        if found is None:
            unknown.append(name)
        elif found not in picked:
            picked.append(found)
    return picked, unknown


def _ask_each(candidates: list) -> tuple[list, str]:
    """One `y/n/a/q` per candidate on stderr. Returns what was accepted and how it ended.

    `a` and `q` are what make a folder of twenty checkouts bearable: the operator reads the first
    few rows, decides the scan got it right, and takes the rest with one keystroke. A closed stdin
    -- a scan run from a script, or from an IDE terminal that attaches none -- is neither an error
    nor a silent yes: it stops with nothing registered and names `--yes`.
    """
    accepted: list = []
    rest = False
    for i, c in enumerate(candidates):
        if rest:
            accepted.append(c)
            continue
        try:
            answer = ask_line(f"register {c.name}?  {c.path}  [y/n/a/q]", "n").strip().lower()[:1]
        except EOFError:
            return accepted, ("nothing on stdin, so nothing more was asked; `--yes` registers "
                              "every proposal without asking")
        if answer == "q":
            return accepted, f"quit at {c.name}; {len(candidates) - i} were not asked about"
        if answer == "a":
            rest = True
            accepted.append(c)
        elif answer == "y":
            accepted.append(c)
    return accepted, "asked one at a time"


def _scan_and_register(source: str, folder, depth: int, yes: bool, only: str, reg: Registry) -> dict:
    """The whole of `repo add --scan`, printed as it goes. Also step one of `quickstart`.

    Prints the proposal *before* asking anything, because the answer to "should this folder be
    registered" is the row: the branch, whether it has an `AGENTS.md`, when it last moved. Then it
    calls `Registry.add` -- unchanged, once per accepted row -- so a repository registered by the
    scan is indistinguishable from one registered by hand, which is what keeps #93's registry
    format, its refusals and the doctor's rows where they are.
    """
    skipped: list[list] = []
    try:
        found = SC.scan(folder, depth=depth, registry=reg,
                        on_skip=lambda path, why: skipped.append([path, why]))
    except SC.ScanError as e:
        return {"error": e, "added": [], "candidates": []}

    moved = SC.drift(reg)
    fresh = [c for c in found if not c.already_registered]
    print(toon.encode({"meta": {
        "ok": True, "source": source, "folder": textio.norm_path(os.path.abspath(C.expand(
            textio.from_msys(str(folder))))), "depth": depth,
        "candidates": len(found), "new": len(fresh),
        "already_registered": len(found) - len(fresh), "drift": len(moved),
        "skipped": len(skipped),
        "note": "nothing is registered yet: the scan proposes and you decide"}}))
    print(toon.table("candidates", SCAN_COLUMNS,
                     [[c.to_json()[col] for col in SCAN_COLUMNS] for c in found]))
    if moved:
        print(toon.table("drift", ["repo", "path", "reason", "detail", "hint"],
                         [[d["name"], d["path"], d["reason"], d["detail"], d["hint"]] for d in moved]))
    if skipped:
        print(toon.table("skipped", ["path", "why"], skipped))
    sys.stdout.flush()

    picked, unknown = _pick(fresh, only)
    if unknown:
        known = ", ".join(c.name for c in fresh) or "nothing new was proposed"
        return {"error": SC.ScanError(
            f"--only names {', '.join(unknown)}, which the scan did not propose",
            f"proposed: {known}"), "added": [], "candidates": found}

    ready = [c for c in picked if c.ready]
    not_ready = [c for c in picked if not c.ready]
    if yes:
        accepted, how = ready, "--yes"
    else:
        accepted, how = _ask_each(ready)

    rows, added, failed = [], [], 0
    for c in accepted:
        try:
            repo = reg.add(c.path, name=c.name)
        except RegistryError as e:
            failed += 1
            rows.append([c.name, c.path, "", False, e.msg])
            continue
        added.append(repo)
        rows.append([repo.name, repo.path, repo.jira_project, True, ""])
    for c in not_ready:
        rows.append([c.name, c.path, "", False, c.why])

    print(toon.encode({"meta": {"ok": True, "source": source, "registered": len(added),
                                "refused": failed + len(not_ready), "how": how,
                                "fleet_dir": fleet_dir(),
                                "next": "ad-fleet index" if added else "ad-fleet repo list"}}))
    print(toon.table("registered", ["repo", "path", "jira", "added", "detail"], rows))
    return {"error": None, "added": added, "candidates": found, "drift": moved,
            "failed": failed, "how": how}


def _repo_add_scan(a) -> int:
    result = _scan_and_register("ad-fleet repo add --scan", a.scan, a.depth, a.yes, a.only or "",
                                Registry())
    if result["error"]:
        return _refuse("ad-fleet repo add --scan", result["error"])
    return EXIT_FAILED if result["failed"] else EXIT_OK


# ------------------------------------------------------------- index / where / show (#130)


def cmd_index(a) -> int:
    """Re-read the allow-listed files of every registered repo into the catalogue.

    Incremental: a second run after one edit reads one file, which is what makes `quickstart`'s
    refresh cheap enough to run whenever the operator sits down. `--rebuild` is for when the *shape*
    of a doc changed here rather than the file changing there.
    """
    reg = Registry()
    try:
        repos = [reg.get(a.repo)] if a.repo else reg.sorted()
    except RegistryError as e:
        return _refuse("ad-fleet index", e)

    cat, code = _catalogue("ad-fleet index")
    if cat is None:
        return code
    try:
        got = cat.index(repos, rebuild=a.rebuild)
        stats = cat.stats()
    finally:
        cat.close()

    print(toon.encode({"meta": {
        "ok": True, "source": "ad-fleet index", "projects": got["projects"],
        "read": got["docs"], "unchanged": got["unchanged"], "removed": got["removed"],
        "docs": stats["docs"], "elapsed_s": got["elapsed"],
        "search": "fts5" if got["fts"] else "like (this Python's sqlite3 has no FTS5)",
        "catalogue": stats["path"],
        "note": "nothing outside AGENTS.md, .agent/ and the git branch was opened",
        "next": ("ad-fleet where <a word from one of your reports>" if stats["docs"] else
                 "register a repository first: ad-fleet repo add --scan <folder>")}}))
    if got["refused"]:
        print(toon.table("refused", ["project", "path", "pattern", "hint"],
                         [[r["project"], r["path"], r["pattern"], r["hint"]] for r in got["refused"]]))
    if got["problems"]:
        print(toon.table("problems", ["project", "path", "reason", "hint"],
                         [[p["project"], p["path"], p["reason"], p["hint"]] for p in got["problems"]]))
    if got["skipped_repos"]:
        print(toon.table("skipped", ["project", "path", "reason", "hint"],
                         [[s["project"], s["path"], s["reason"], s["hint"]]
                          for s in got["skipped_repos"]]))
    return EXIT_OK


def cmd_where(a) -> int:
    """Which project owns this word. The one question that used to cost four tabs."""
    cat, code = _catalogue("ad-fleet where")
    if cat is None:
        return code
    try:
        rows = cat.where(a.query, limit=a.limit)
        stats = cat.stats()
    except CAT.CatalogueError as e:
        return _refuse("ad-fleet where", e)
    finally:
        cat.close()

    hint = ""
    if not stats["projects"]:
        hint = "nothing is indexed yet: `ad-fleet index`"
    elif not rows:
        hint = "no project mentions that; try a word from a report title or a ticket key"
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet where", "query": a.query,
                                "matches": len(rows), "indexed_projects": stats["projects"],
                                "search": "fts5" if stats["fts"] else "like",
                                "hint": hint}}))
    print(toon.table("matches", ["project", "kind", "title", "snippet", "score"],
                     [[r["project"], r["kind"], r["title"], r["snippet"], r["score"]] for r in rows]))
    return EXIT_OK


def cmd_show(a) -> int:
    """One project in full: its facts, its state, its open friction, and its links.

    The links come from `links.links_for`, the same rail the tile renders, so what this prints and
    what the dashboard shows cannot disagree -- and the keys a missing link needs are named here
    too, because the operator reading this at 5pm is the person who can add them.
    """
    cat, code = _catalogue("ad-fleet show")
    if cat is None:
        return code
    try:
        data = cat.show(a.project)
    except CAT.CatalogueError as e:
        return _refuse("ad-fleet show", e)
    finally:
        cat.close()

    facts, state = data["facts"], data["state"]
    rail = LK.links_for(data, facts, state)
    missing = LK.missing_keys(rail)
    print(toon.encode({"meta": {
        "ok": True, "source": "ad-fleet show", "project": data["project"], "path": data["path"],
        "branch": data["branch"], "jira_project": data["jira_project"],
        "phase": state.get("phase", ""), "ticket": state.get("active_ticket") or "",
        "friction": len(data["friction"]), "docs": data["docs"],
        "last_indexed": data["last_indexed"],
        "missing_keys": ", ".join(missing) or "none",
        "hint": (f"add {', '.join(missing)} to that repo's AGENTS.md and the missing links appear"
                 if missing else "")}}))
    print(toon.table("facts", ["key", "value"], [[k, facts[k]] for k in sorted(facts)]))
    print(toon.table("links", ["name", "url", "kind", "why_missing"],
                     [[r["name"], r["url"], r["kind"], r["why_missing"]] for r in rail]))
    print(toon.table("friction", ["date", "type", "title", "unblock"],
                     [[f["date"], f["type"], f["title"], f["unblock"]] for f in data["friction"]]))
    print(toon.table("pbip", ["name", "model", "report", "lineage"],
                     [[p["name"], p["model"], p["report"], p["lineage"]] for p in data["pbip"]]))
    return EXIT_OK


# --------------------------------------------------------------------------- inbox (#132)


def _offer(offers: list, wanted: str):
    """The offer an `--attach`/`--dismiss` id names, by id, id prefix, or exact file name."""
    wanted = str(wanted or "").strip()
    for o in offers:
        if o.id == wanted or o.name == wanted:
            return o
    prefixed = [o for o in offers if o.id.startswith(wanted.lower())] if wanted else []
    return prefixed[0] if len(prefixed) == 1 else None


def _size(n) -> str:
    """A size a person reads, because the decision is "is that the export or the installer"."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def cmd_inbox(a) -> int:
    """What the browser saved, and which tile it belongs to. Never opens a file.

    Matching is on the name alone (#132): Downloads holds bank statements and installers next to the
    Jira exports, and a watcher that read a file to decide where it belongs would be reading all of
    them. `--attach` is the one write the fleet makes inside a repository, and it happens only here,
    only on this flag, and only into `.agent/in/<KEY>/`.
    """
    if a.attach and a.dismiss:
        return _refuse("ad-fleet inbox", IN.InboxError(
            "--attach and --dismiss ask for opposite things",
            "run them one at a time: `ad-fleet inbox --attach <id> --repo <repo>`"))
    reg = Registry()
    box = IN.Inbox(folders=list(a.folder) if a.folder else None, registry=reg)
    offers = box.look()

    if a.attach or a.dismiss:
        offer = _offer(offers, a.attach or a.dismiss)
        if offer is None:
            ids = ", ".join(f"{o.id} ({o.name})" for o in offers[:10]) or "the tray is empty"
            return _refuse("ad-fleet inbox", IN.InboxError(
                f"no file with id {a.attach or a.dismiss!r} in the tray",
                f"`ad-fleet inbox` lists what is there: {ids}"))
        if a.dismiss:
            box.dismiss(offer)
            return _emit("ad-fleet inbox --dismiss",
                         {"file": offer.name, "id": offer.id,
                          "note": "hidden until a newer file arrives with that name"})
        if not a.repo:
            return _refuse("ad-fleet inbox", IN.InboxError(
                "--attach needs the repository to attach it to",
                f"`ad-fleet inbox --attach {offer.id} --repo "
                f"{offer.project or '<repo>'}`; `ad-fleet repo list` names them"))
        try:
            event = box.attach(offer, a.repo)
        except (IN.InboxError, RegistryError) as e:
            return _refuse("ad-fleet inbox --attach", e)
        data = event["data"]
        return _emit("ad-fleet inbox --attach",
                     {"file": data["name"], "repo": data["project"], "to": data["file"],
                      "attached": data["attached"], "recorded": data["recorded"],
                      "why": data.get("why", ""),
                      "note": "the original is still in Downloads; nothing was moved"})

    offered = [o for o in offers if o.offered]
    print(toon.encode({"meta": {
        "ok": True, "source": "ad-fleet inbox", "folders": ", ".join(box.folders) or "none found",
        "files": len(offers), "offered": len(offered),
        "unsorted": sum(1 for o in offered if not o.project),
        "dismissed": len(box.dismissed()), "still_being_written": len(box.retry),
        "note": "matched on the file name; no file here was opened",
        "hint": ("`ad-fleet inbox --attach <id> --repo <repo>` copies one into "
                 ".agent/in/<KEY>/" if offered else
                 "" if box.folders else
                 "no Downloads folder was found: pass `--folder <path>`")}}))
    print(toon.table("inbox", ["id", "name", "size", "age", "project", "ticket", "offered", "reason"],
                     [[o.id, o.name, _size(o.size), _mins(o.age_s), o.project, o.ticket,
                       o.offered, o.reason] for o in offers]))
    if box.retry:
        print(toon.table("still_being_written", ["name", "reason"],
                         [[r["name"], r["reason"]] for r in box.retry]))
    return EXIT_OK


# ------------------------------------------------------------------- status --polls (#131)


def _status_polls(a) -> int:
    """What the polling cost today, per source.

    Printed because it is the number nobody thinks about until a shared Jira tenant starts rate-
    limiting a team: four tiles times a poll a minute is a figure the operator should be able to see
    before somebody else does. `jira` counts *searches*, not tickets -- one JQL covers every tile.
    """
    cfg = C.load()
    try:
        poller = P.Poller(Registry(), cfg=cfg)
    except RegistryError as e:
        return _refuse("ad-fleet status --polls", e)
    counts, conf = poller.counts(), P.settings(cfg)
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet status --polls",
                                "day": counts["day"], "requests": counts["total"],
                                "note": "one JQL covers every tile, so `jira` counts searches, "
                                        "not tickets; `fleet.poll.<source>: false` turns one off"}}))
    print(toon.table("polls", ["source", "on", "interval_s", "requests", "errors", "stood_down"],
                     [[s, conf[s]["on"], conf[s]["interval"], counts["requests"][s],
                       counts["errors"][s], counts["stood_down"][s]] for s in P.SOURCES]))
    return EXIT_OK


# ---------------------------------------------------------------------- quickstart (#134)


def _layout_url(url: str, layout: str) -> str:
    """The dashboard's URL with the layout on it. Both halves agree on `LAYOUT_PARAM`."""
    return f"{url}{'&' if '?' in url else '?'}{LAYOUT_PARAM}={layout}"


def _open_browser(url: str) -> str:
    """Windows first: `os.startfile` is the shell's own "open this", and it needs no dependency.

    `webbrowser` is the fallback everywhere else. Either way the URL has already been printed, so a
    machine where neither works loses a click and not the address.
    """
    if os.name == "nt":
        try:
            os.startfile(url)                    # noqa: S606 - our own 127.0.0.1 address
            return "os.startfile"
        except OSError as e:
            return f"could not open a browser ({e}); the URL is above"
    import webbrowser

    return "the default browser" if webbrowser.open(url) else "no browser answered; the URL is above"


def cmd_quickstart(a) -> int:
    """From a folder of checkouts to a dashboard that already answers questions, in one command.

    Nothing here is new machinery: it is `repo add --scan`, `index`, one poll of every tile, the
    inbox's first look and `serve`, in that order, with the clock running. The operator's condition
    for this whole epic was not spending an evening on setup, and the summary at the end is what
    that condition is measured against -- `elapsed`, and how much of the desk actually answered.

    A second run is a refresh, not a re-setup: the scan proposes only what is new, the index reads
    only what changed, and `refresh: true` says so.
    """
    import time

    started = time.time()
    reg = Registry()
    cat, code = _catalogue("ad-fleet quickstart")
    if cat is None:
        return code
    refresh = bool(reg.repos) and bool(cat.stats()["projects"])

    scanned = _scan_and_register("ad-fleet quickstart", a.folder, a.depth, a.yes, "", reg)
    if scanned["error"]:
        cat.close()
        return _refuse("ad-fleet quickstart", scanned["error"])

    reg.load()
    repos = reg.sorted()
    try:
        cat.index(repos)
        docs = cat.stats()["docs"]
        facts = {}
        for repo in repos:
            try:
                facts[repo.name] = cat.show(repo.name)
            except CAT.CatalogueError:
                facts[repo.name] = {"facts": {}, "state": {}}
    finally:
        cat.close()

    cfg = C.load()
    poller = P.Poller(reg, cfg=cfg)
    events = poller.tick()

    with_ticket = missing_facts = 0
    for repo in repos:
        shown = facts.get(repo.name) or {}
        state = shown.get("state") or repo.state()
        if state.get("active_ticket"):
            with_ticket += 1
        if LK.missing_keys(LK.links_for(repo, shown.get("facts") or {}, state)):
            missing_facts += 1

    watch = list(a.folder_watch) if getattr(a, "folder_watch", None) else None
    box = IN.Inbox(folders=watch, registry=reg)
    offered = sum(1 for o in box.look() if o.offered)

    server = url = ""
    if not a.no_serve:
        try:
            server, token = S.build(a.port)
        except S.ServeError as e:
            return _refuse("ad-fleet quickstart", e)
        url = _layout_url(S.url_for(server, token), a.layout)
        S.record(server, token)

    _emit("ad-fleet quickstart",
          {"refresh": refresh, "repos": len(repos), "indexed_docs": docs,
           "tiles_with_ticket": with_ticket, "tiles_missing_facts": missing_facts,
           "inbox_offered": offered, "elapsed": round(time.time() - started, 2),
           "events": len(events), "url": url,
           "next": ("open the page; `ad-fleet show <project>` answers the same questions in a "
                    "shell" if url else "ad-fleet serve --open")})
    sys.stdout.flush()
    if server:
        _emit("ad-fleet quickstart", {"opened": _open_browser(url), "url": url,
                                      "bound": "127.0.0.1 only", "note": "stop with Ctrl-C"})
        sys.stdout.flush()
        S.run(server)
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


def _remembered_windows() -> list[str]:
    try:
        from .registry import fleet_dir
        from .serve import DESK_FILE
        desk_path = os.path.join(fleet_dir(), DESK_FILE)
        if os.path.isfile(desk_path):
            with open(desk_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            wins = data.get("windows")
            if isinstance(wins, dict) and wins:
                return list(wins.keys())
    except Exception:
        pass
    return ["main"]


def cmd_open(a) -> int:
    """Put the dashboard in front of the operator, starting one if none is up.

    Every branch prints what it actually did, including the ones that could only put the URL on the
    clipboard -- an embedding story that quietly does nothing is worse than one that says so.
    """
    record = O.running()
    started = False
    if not record:
        try:
            record = O.start_server(a.port)
            started = True
        except O.OpenError as e:
            return _refuse("ad-fleet open", e)

    try:
        if getattr(a, "all", False):
            wins = _remembered_windows()
            dids = [O.open_in(a.where, record, launcher_dir=a.write_launcher or "", window=w) for w in wins]
            return _emit("ad-fleet open", {"where": a.where, "server": "started" if started else "already up",
                                           "port": record.get("port"), "windows": wins,
                                           "opened": [d.get("opened") for d in dids]})
        w = getattr(a, "window", "") or ""
        did = O.open_in(a.where, record, launcher_dir=a.write_launcher or "", window=w)
    except O.OpenError as e:
        return _refuse("ad-fleet open", e)

    return _emit("ad-fleet open", {"where": a.where, "server": "started" if started else "already up",
                                   "port": record.get("port"), **did})


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
    print(toon.encode({"meta": {"ok": True, "source": "ad-fleet history", "dispatches": len(rows),
                                "runs": len(rows),
                                "since": a.since,
                                "premium_requests": round(sum(r["premium_requests"] for r in rows), 2)}}))
    print(toon.table("history", ["started", "repo", "ticket", "session", "summary", "state", "phase",
                                 "turns", "premium_requests"],
                     [[str(r["started"])[:16], r["repo"], r["ticket"] or "-", r.get("session") or "-",
                       r["summary"][:50], r["state"], r["phase"] or "-", r["turns"], r["premium_requests"]]
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
    url = _layout_url(S.url_for(server, token), a.layout)
    S.record(server, token)
    _emit("ad-fleet serve", {"url": url, "port": server.server_address[1],
                             "bound": "127.0.0.1 only", "layout": a.layout,
                             "note": "the token in the URL is required on every request; "
                                     "stop with Ctrl-C"})
    sys.stdout.flush()
    if a.open:
        _open_browser(url)
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
    add.add_argument("path", nargs="?")
    add.add_argument("--name", help="what the fleet calls it (default: the folder name)")
    add.add_argument("--scan", metavar="FOLDER",
                     help="propose every project under FOLDER instead, and ask about each")
    add.add_argument("--depth", type=int, default=2,
                     help="how many levels under FOLDER to look (default 2)")
    add.add_argument("--yes", action="store_true",
                     help="register every proposal without asking (a folder ad-setup has not "
                          "touched is reported, not registered)")
    add.add_argument("--only", metavar="A,B", help="register just these proposed names")
    add.set_defaults(fn=cmd_repo_add)
    rm = repo_sub.add_parser("rm", aliases=["remove"],
                             help="forget a repository (its files are untouched)")
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
    start.add_argument("--resume", help="resume a specific session by id")
    start.add_argument("--new", action="store_true", help="start a clean session beside the previous one")
    start.add_argument("--brief", help="what the agent should know, in your own words; written to "
                                       ".agent/in/<KEY>/brief.md before the agent starts")
    start.add_argument("--brief-file", dest="brief_file", metavar="PATH",
                       help="the same, read from a file")
    start.set_defaults(fn=cmd_start)

    pf = sub.add_parser("preflight", help="is this ticket ready to hand over? (spends no premium request)")
    pf.add_argument("ticket")
    pf.add_argument("--repo", help="the checkout it would start on (default: the one that declares its project)")
    pf.set_defaults(fn=cmd_preflight)

    send = sub.add_parser("send", help="continue an agent's session with another message")
    send.add_argument("repo")
    send.add_argument("message")
    send.add_argument("--force", action="store_true", help="send even if the agent is over budget")
    send.set_defaults(fn=cmd_send)

    again = sub.add_parser("restart", help="resume a stopped agent on its own session")
    again.add_argument("repo")
    again.add_argument("--force", action="store_true",
                       help="restart past `fleet.max_restarts`")
    again.set_defaults(fn=cmd_restart)

    take = sub.add_parser("adopt", help="take on a session running outside the fleet")
    take.add_argument("repo", nargs="?", default="")
    take.add_argument("--list", action="store_true", help="show what could be adopted, and change nothing")
    take.add_argument("--pid", type=int, default=0,
                      help="the process to record, where this machine will not say which it is")
    take.set_defaults(fn=cmd_adopt)

    give = sub.add_parser("release", help="hand an adopted session back to whoever started it")
    give.add_argument("repo")
    give.set_defaults(fn=cmd_release)

    unblock = sub.add_parser("reset", help="unblock a stuck agent: stop it, then resume its session")
    unblock.add_argument("repo")
    unblock.add_argument("--force", action="store_true",
                         help="resume past `fleet.max_restarts`")
    unblock.set_defaults(fn=cmd_reset)

    collect = sub.add_parser("gc", help="prune rotated logs and answered approvals")
    collect.add_argument("--days", type=int, default=L.DEFAULT_GC_DAYS,
                         help=f"keep anything newer than this (default {L.DEFAULT_GC_DAYS})")
    collect.set_defaults(fn=cmd_gc)

    doc = sub.add_parser("doctor", help="the fleet's rows from ad-doctor")
    doc.add_argument("--pretty", action="store_true", help="draw it for a person to read")
    doc.set_defaults(fn=cmd_doctor)

    stop = sub.add_parser("stop", help="stop an agent and everything it started")
    stop.add_argument("repo", nargs="?")
    stop.add_argument("--all", action="store_true", help="stop every agent")
    stop.set_defaults(fn=cmd_stop)

    status = sub.add_parser("status", help="one row per registered repository")
    status.add_argument("--repo", help="just this one")
    status.add_argument("--show-launch", action="store_true", dest="show_launch",
                        help="print the exact command line and tool allow-list instead")
    status.add_argument("--polls", action="store_true",
                        help="what today's tile polling has cost, per source, instead")
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

    opn = sub.add_parser("open", help="show the dashboard, starting one if none is running")
    opn.add_argument("--in", dest="where", default="browser", choices=list(O.WHERE),
                     help="where to show it (default: the default browser)")
    opn.add_argument("--port", type=int, default=8765, help="port to start a server on if none is up")
    opn.add_argument("--write-launcher", dest="write_launcher", metavar="DIR",
                     help="write fleet.html into DIR, for an IDE that only opens files")
    opn.add_argument("--window", "-w", help="which named window to open (e.g. main, left)")
    opn.add_argument("--all", action="store_true", help="open every window the desk remembers")
    opn.set_defaults(fn=cmd_open)

    brd = sub.add_parser("board", help="your Jira tickets, and which repo each one belongs to")
    brd.add_argument("--refresh", action="store_true", help="ask Jira now instead of using the cache")
    brd.add_argument("--project", help="only this Jira project")
    brd.set_defaults(fn=cmd_board)

    hist = sub.add_parser("history", help="what was dispatched, how it ended, what it cost")
    hist.add_argument("--since", default="7d", help="7d | 12h | 90m (default 7d)")
    hist.set_defaults(fn=cmd_history)

    sess = sub.add_parser("sessions", help="list or rebuild sessions for a repository")
    sess.add_argument("repo")
    sess.add_argument("--rebuild", action="store_true", help="rebuild sessions.json from events.norm.jsonl")
    sess.add_argument("rename_verb", nargs="?", choices=["rename"], help=argparse.SUPPRESS)
    sess.add_argument("rename_id", nargs="?", help=argparse.SUPPRESS)
    sess.add_argument("rename_title", nargs="?", help=argparse.SUPPRESS)
    sess.set_defaults(fn=cmd_sessions)

    note = sub.add_parser("notify", help="what the fleet would tell you, and what it has")
    note.add_argument("what", nargs="?", default="list", choices=["list", "test", "tail"],
                      help="list: recent; test: one of each severity; tail: what would fire now")
    note.add_argument("--limit", type=int, default=50, help="how many to list")
    note.set_defaults(fn=cmd_notify)

    srv = sub.add_parser("serve", help="the multi-viewer: one local page, one tile per agent")
    srv.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (0 picks a free one)")
    srv.add_argument("--open", action="store_true", help="open it in the default browser")
    srv.add_argument("--layout", default=LAYOUTS[0], choices=list(LAYOUTS),
                     help="how the tiles are arranged: grid | roles | screens (default grid)")
    srv.set_defaults(fn=cmd_serve)

    idx = sub.add_parser("index", help="read what each repo publishes into the local catalogue")
    idx.add_argument("--repo", help="just this one")
    idx.add_argument("--rebuild", action="store_true",
                     help="re-read every file instead of only what changed")
    idx.set_defaults(fn=cmd_index)

    whr = sub.add_parser("where", help="which project mentions this, and in what")
    whr.add_argument("query", help="plain words, or a ticket key")
    whr.add_argument("--limit", type=int, default=20, help="how many projects (default 20)")
    whr.set_defaults(fn=cmd_where)

    shw = sub.add_parser("show", help="one project: its facts, state, friction and links")
    shw.add_argument("project")
    shw.set_defaults(fn=cmd_show)

    inb = sub.add_parser("inbox", help="files the browser saved that belong to a project")
    inb.add_argument("--folder", action="append", metavar="PATH",
                     help="watch this folder instead of Downloads (repeatable)")
    inb.add_argument("--attach", metavar="ID", help="copy one into <repo>/.agent/in/<KEY>/")
    inb.add_argument("--repo", help="the repository to attach it to")
    inb.add_argument("--dismiss", metavar="ID", help="stop offering one until it is downloaded again")
    inb.set_defaults(fn=cmd_inbox)

    quick = sub.add_parser("quickstart", help="scan, index, poll and serve one folder of projects")
    quick.add_argument("folder", help="the parent folder your projects live under")
    quick.add_argument("--depth", type=int, default=2,
                       help="how many levels under it to look (default 2)")
    quick.add_argument("--yes", action="store_true", help="register every proposal without asking")
    quick.add_argument("--no-serve", action="store_true", dest="no_serve",
                       help="print the summary and stop, instead of starting the dashboard")
    quick.add_argument("--folder-watch", action="append", dest="folder_watch", metavar="PATH",
                       help="an inbox folder to look in besides Downloads (repeatable)")
    quick.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (0 picks a free one)")
    quick.add_argument("--layout", default=LAYOUTS[0], choices=list(LAYOUTS),
                       help="how the tiles are arranged: grid | roles | screens (default grid)")
    quick.set_defaults(fn=cmd_quickstart)

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
