"""The fleet as one graph: projects, the checkouts that hang from them, and each checkout's agent (#401).

`GET /api/map` answers this. It is a pure fold over `serve.fleet_snapshot()`'s answer: no git call,
no registry read, no `.agent/` read. Everything it says is already on the snapshot's rows; what it adds
is how they relate -- which checkout is a worktree of which, and who started each agent -- so a page
draws the structure instead of reassembling it from tiles. Schema and sentences: docs/fleet-map.md.

It never carries a path (the operator's disk layout is not the map's business) and never carries
event text (the transcript belongs to the desk).
"""
from __future__ import annotations

import os

from .. import textio
from . import poll as P
from .agentstate import STATE_ROLES

SCHEMA = 1

#: Who an agent is, in the order `kind` is decided and tested. `headless` is a run the fleet started
#: (`copilot -p`), alive or finished; `none` is a checkout that has never had a run.
KINDS = ("console", "adopted", "headless", "adoptable", "none")

_KIND_WORDS = {
    "console": "console agent",
    "adopted": "adopted session",
    "headless": "background agent (headless)",
    "adoptable": "a session the fleet could adopt",
    "none": "no session",
}

# The notifier's words where it has them (notify.RULES), so the map and a notification agree.
_STATE_WORDS = {
    "running": "running",
    "waiting_approval": "needs approval",
    "needs_human": "needs you",
    "blocked": "blocked",
    "error": "fell over",
    "done": "done",
    "starting": "starting",
    "idle": "idle",
}

_ORIGIN_KIND = {"fleet": "headless", "console": "console", "adopted": "adopted", "": "none"}


def _key(path: str) -> str:
    return os.path.normcase(textio.norm_path(path or ""))


def _count(n: int, one: str, many: str) -> str:
    return f"1 {one}" if n == 1 else f"{n} {many}"


def kind_of(row: dict) -> str:
    """The first of `KINDS` that applies to a snapshot row."""
    if row.get("console"):
        return "console"
    if row.get("external"):
        return "adopted"
    if row.get("adoptable"):
        return "adoptable"
    origin = (row.get("run") or {}).get("origin", "")
    return _ORIGIN_KIND.get(origin, "none")


def agent_says(agent: dict, *, ran: bool) -> str:
    """`<kind words> · [finished · ]<state words>[ · ticket]`, and what else is true."""
    bits = [_KIND_WORDS[agent["kind"]]]
    if ran and not agent["live"] and agent["kind"] != "none":
        bits.append("finished")
    bits.append(_STATE_WORDS.get(agent["state"], agent["state"] or "idle"))
    if agent["ticket"]:
        bits.append(agent["ticket"])
    n = agent["subagents"]
    if n > 0:
        bits.append(_count(n, "sub-agent", "sub-agents") + " (not yet measured)")
    if agent["stale"]:
        bits.append("began on an older install")
    if agent["renew_queued"]:
        bits.append("renew queued")
    return " · ".join(bits)


def _agent(row: dict) -> dict:
    run = row.get("run") or {}
    state = row.get("state") or "idle"
    agent = {
        "id": f"a:{row['repo']}",
        "kind": kind_of(row),
        "live": bool(row.get("supervised")),
        "state": state,
        "role": STATE_ROLES.get(state, "idle"),
        "needs_human": bool(row.get("needs_human")),
        "stale": bool((row.get("stale") or {}).get("stale")),
        "renew_queued": bool(row.get("renew_queued")),
        "ticket": row.get("ticket") or "",
        "phase": row.get("phase") or "",
        "model": row.get("model") or "",
        "age_s": row.get("last_event_age_s", -1),
        "turns": int(row.get("turns") or 0),
        "sessions_n": int(row.get("sessions_n") or 0),
        "subagents": int(row.get("subagents") or 0),
    }
    agent["says"] = agent_says(agent, ran=bool(run.get("origin")))
    return agent


def _git(row: dict) -> dict:
    value = ((row.get("polls") or {}).get("git") or {}).get("value") or {}
    if not isinstance(value, dict):
        value = {}
    return {"branch": value.get("branch") or "", "dirty": bool(value.get("dirty")),
            "ahead": int(value.get("ahead") or 0), "behind": int(value.get("behind") or 0)}


def checkout_says(c: dict, main_repo: str) -> str:
    """*worktree luna-velocity on feature/RDSD-101-velocity, of luna*, and what git says of it."""
    what = "main checkout" if c["main"] else ("worktree" if c["worktree_of"] or
                                              c["worktree_of_unregistered"] else "checkout")
    out = f"{what} {c['repo']}"
    if c["branch"]:
        out += f" on {c['branch']}"
    if c["worktree_of"]:
        out += f", of {main_repo}"
    elif c["worktree_of_unregistered"]:
        out += ", of a checkout the fleet does not know"
    if c["dirty"]:
        out += ", uncommitted changes"
    if c["ahead"]:
        out += f", {c['ahead']} ahead"
    if c["behind"]:
        out += f", {c['behind']} behind"
    return out


def graph_says(n_projects: int, n_checkouts: int, working: int, needs: int) -> str:
    """*3 projects, 5 checkouts, 4 agents working, 1 needs you*."""
    projects = "no projects" if not n_projects else _count(n_projects, "project", "projects")
    checkouts = "no checkouts" if not n_checkouts else _count(n_checkouts, "checkout", "checkouts")
    agents = ("no agents working" if not working
              else _count(working, "agent working", "agents working"))
    need = "nobody needs you" if not needs else ("1 needs you" if needs == 1 else f"{needs} need you")
    return f"{projects}, {checkouts}, {agents}, {need}"


def project_says(name: str, checkouts: list[dict]) -> str:
    out = f"project {name}, " + _count(len(checkouts), "checkout", "checkouts")
    needs = sum(1 for c in checkouts if c["agent"]["needs_human"])
    if needs:
        out += ", " + ("1 needs you" if needs == 1 else f"{needs} need you")
    return out


def branches_says(n: int, unmerged: int, default: str, *, more: bool = False) -> str:
    """*12 branches, 4 never reached main*; `40+` when the list was capped."""
    plus = "+" if more else ""
    head = f"1{plus} branch" if n == 1 else f"{n}{plus} branches"
    reach = default or "main"
    if not unmerged:
        return f"{head}, all reached {reach}"
    return f"{head}, {unmerged}{plus if unmerged == n else ''} never reached {reach}"


def branch_says(b: dict, repos: list[str]) -> str:
    """*feature/RDSD-101-velocity · never reached main · current in luna-velocity · carries RDSD-101*."""
    bits = [b["name"]]
    if b["unmerged"]:
        bits.append(f"never reached {b['_default'] or 'main'}")
    if repos:
        bits.append("current in " + ", ".join(repos))
    if b["carrying"] and b["ticket"]:
        bits.append(f"carries {b['ticket']}")
    return " · ".join(bits)


def _cached(branch_rows, repo: str) -> dict | None:
    if branch_rows is None:
        return None
    try:
        got = branch_rows(repo)
    except Exception:                         # noqa: BLE001 - a map without lanes, not no map
        return None
    return got if isinstance(got, dict) and isinstance(got.get("rows"), list) else None


def _lanes(mine: list[dict], root: dict | None, cache: dict) -> dict:
    """One project's branch list (#403): the root checkout's rows, else the union over its
    checkouts. Worktrees of one repository share `refs/heads`, so every checkout lists the same
    branches; the union only matters when the main is unregistered or not read yet."""
    read = [c for c in mine if cache.get(c["repo"]) is not None]
    if not read:
        return {"default": "", "more": False, "rows": [], "read": False}
    first = root if root is not None and cache.get(root["repo"]) is not None else read[0]
    if first is root:
        entry = cache[root["repo"]]
        rows, more, default = list(entry["rows"]), bool(entry.get("more")), entry.get("default") or ""
    else:
        seen: dict[str, dict] = {}
        more = False
        for c in read:
            entry = cache[c["repo"]]
            more = more or bool(entry.get("more"))
            for r in entry["rows"]:
                seen.setdefault(r.get("name", ""), r)
        seen.pop("", None)
        rows = sorted(seen.values(), key=lambda r: (not r.get("unmerged"), -float(r.get("at") or 0),
                                                    r.get("name", "")))
        if len(rows) > P.MAP_BRANCH_ROWS:
            rows, more = rows[:P.MAP_BRANCH_ROWS], True
        default = cache[read[0]["repo"]].get("default") or ""
    return {"default": str(default), "more": more, "rows": rows, "read": True,
            "at": float(cache[first["repo"]].get("at") or 0.0)}


def _project(name: str, mine: list[dict], root: dict | None, cache: dict,
             now: float | None) -> dict:
    """A project node with its branch lanes, and each of its checkouts (and agents) put on its lane."""
    lanes = _lanes(mine, root, cache)
    default = lanes["default"]
    carrying = {n for c in mine if cache.get(c["repo"]) for n in cache[c["repo"]].get("carrying") or []}
    current = {c["repo"]: (cache.get(c["repo"]) or {}).get("current") or c["branch"] for c in mine}
    ref = lanes.get("at", 0.0) if now is None else float(now)

    branches: list[dict] = []
    for r in lanes["rows"]:
        bname = str(r.get("name") or "")
        at = float(r.get("at") or 0.0)
        on = [c for c in mine if current[c["repo"]] == bname]
        b = {"id": f"b:{name}:{bname}", "name": bname, "unmerged": bool(r.get("unmerged")),
             "ticket": str(r.get("ticket") or ""),
             "age_s": round(max(0.0, ref - at), 1) if at else 0.0,
             "carrying": bname in carrying, "current_in": [c["id"] for c in on], "_default": default}
        b["says"] = branch_says(b, [c["repo"] for c in on])
        del b["_default"]
        branches.append(b)

    by_name = {b["name"]: b for b in branches}
    for c in mine:
        b = by_name.get(current[c["repo"]])
        c["on"] = b["id"] if b else ""
        agent = c["agent"]
        agent["on"], agent["branch"] = c["on"], (b["name"] if b else "")
        if b:
            agent["says"] += f" · on {b['name']}"
            if b["carrying"] and b["ticket"]:
                agent["says"] += f" · carries {b['ticket']}"

    if lanes["read"]:
        said = branches_says(len(branches), sum(1 for b in branches if b["unmerged"]), default,
                             more=lanes["more"])
    else:
        said = f"branches not read yet (the git poll runs every {P.DEFAULT_INTERVALS['git']} s)"
    lines: list[str] = []
    for c in mine:
        line = P.carry_line(cache[c["repo"]]) if cache.get(c["repo"]) else ""
        if line and line not in lines:
            lines.append(line)
    return {"id": f"p:{name}", "name": name, "root": root["id"] if root is not None else "",
            "default": default, "says": f"{project_says(name, mine)}; {said}",
            "branches_says": said, "carry_lines": lines, "branches": branches}


def graph(snapshot: dict, *, now: float | None = None, branch_rows=None) -> dict:
    """The map's schema-1 graph of one `fleet_snapshot()` answer. Pure: the same snapshot (and the
    same `branch_rows` answers) gives an equal graph.

    `branch_rows` is `Poller.branch_rows`, a name -> dict callable over the git poll's side cache
    (#403), or None when nothing polls. `now` is what a branch's `age_s` is measured against;
    without it, against the moment the poll read the rows."""
    rows = [r for r in (snapshot.get("repos") or []) if r.get("repo")]
    by_path = {_key(r.get("path", "")): r["repo"] for r in rows if r.get("path")}

    checkouts: list[dict] = []
    for row in rows:
        raw_of = row.get("worktree_of") or ""
        of = by_path.get(_key(raw_of), "") if raw_of else ""
        if of == row["repo"]:
            of = ""
        checkouts.append({
            "id": f"c:{row['repo']}", "repo": row["repo"],
            "project": row.get("project") or row["repo"],
            "main": False,
            "worktree_of": f"c:{of}" if of else "",
            "worktree_of_unregistered": bool(raw_of) and not of,
            "_raw_of": bool(raw_of),
            **_git(row),
            "agent": _agent(row),
        })

    cache = {c["repo"]: _cached(branch_rows, c["repo"]) for c in checkouts}
    projects: list[dict] = []
    for name in sorted({c["project"] for c in checkouts}):
        mine = sorted((c for c in checkouts if c["project"] == name), key=lambda c: c["repo"])
        roots = [c for c in mine if not c["_raw_of"]]
        root = roots[0] if roots else None
        if root is not None:
            root["main"] = True
        projects.append(_project(name, mine, root, cache, now))

    repo_of = {c["id"]: c["repo"] for c in checkouts}
    for c in checkouts:
        del c["_raw_of"]
        c["says"] = checkout_says(c, repo_of.get(c["worktree_of"], ""))
        # `says` after the facts it is made of, and the agent last, as the schema lists them.
        c["agent"] = c.pop("agent")
    checkouts.sort(key=lambda c: (c["project"], not c["main"], c["repo"]))

    working = sum(1 for c in checkouts if c["agent"]["state"] == "running")
    needs = sum(1 for c in checkouts if c["agent"]["needs_human"])
    seqs = {r["repo"]: int(r.get("last_seq") or 0) for r in rows}
    return {
        "schema": SCHEMA,
        "as_of": rows[0].get("as_of") if rows else None,
        "cursor": ",".join(f"{repo}:{seqs[repo]}" for repo in sorted(seqs)),
        "says": graph_says(len(projects), len(checkouts), working, needs),
        "projects": projects,
        "checkouts": checkouts,
    }
