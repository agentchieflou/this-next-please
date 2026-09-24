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


def graph(snapshot: dict, *, now: float | None = None) -> dict:
    """The map's schema-1 graph of one `fleet_snapshot()` answer. Pure: the same snapshot gives an
    equal graph. `now` is reserved for age-relative words and unused by schema 1."""
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

    projects: list[dict] = []
    for name in sorted({c["project"] for c in checkouts}):
        mine = sorted((c for c in checkouts if c["project"] == name), key=lambda c: c["repo"])
        roots = [c for c in mine if not c["_raw_of"]]
        root = roots[0] if roots else None
        if root is not None:
            root["main"] = True
        projects.append({"id": f"p:{name}", "name": name,
                         "root": root["id"] if root is not None else "",
                         "says": project_says(name, mine)})

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
