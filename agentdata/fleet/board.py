"""The operator's own Jira tickets, and which repository each one probably belongs to.

Delegating specific tickets to specific agents should not mean copying keys out of a browser. This
is the intake side of the fleet: a JQL the operator sets, the tickets it returns, and — because
every registered repository already declares its `jira_project` in `AGENTS.md` — a suggestion of
where each one goes.

**No new credential.** `jira_api` runs on the token pncli already stores, exactly as `ad-jira
changelog` does. A fleet that asked for a second login would not be used.

**Cached, because four tiles and a panel must not hammer Jira.** The board is a *view of a queue*,
not a live feed: a ticket that appeared thirty seconds ago is not urgent, and a search per tile per
tick is how a shared Jira instance starts rate-limiting the whole team.

**Read-only, always.** Only agents write to Jira, and only through the approval gate (#95). Nothing
in this module can transition, comment or assign.
"""
from __future__ import annotations
import json
import os
import re
import time

from .. import config as C
from .. import textio
from .registry import Registry, RegistryError, fleet_dir

CACHE = "board.json"
DEFAULT_JQL = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC"
DEFAULT_FIELDS = "key,summary,status,priority,issuetype,updated"
DEFAULT_TTL_S = 120

# A Jira key is <PROJECT>-<number>, and the project is what matches a repository.
KEY = re.compile(r"^([A-Z][A-Z0-9_]+)-(\d+)$")

DONE_CATEGORIES = ("done",)


class BoardError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def project_of(key: str) -> str:
    m = KEY.match((key or "").strip().upper())
    return m.group(1) if m else ""


def settings(cfg: dict | None = None) -> dict:
    cfg = C.load() if cfg is None else cfg
    ttl = C.get(cfg, "fleet.board_ttl")
    try:
        ttl = max(0, int(ttl))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_S
    return {"jql": str(C.get(cfg, "fleet.jql") or DEFAULT_JQL),
            "fields": str(C.get(cfg, "fleet.jql_fields") or DEFAULT_FIELDS),
            "ttl": ttl}


# ------------------------------------------------------------------------------- the cache


def cache_path() -> str:
    return os.path.join(fleet_dir(), CACHE)


def read_cache() -> dict:
    try:
        return json.loads(textio.read_text(cache_path()))
    except (OSError, ValueError):
        return {}


def write_cache(payload: dict) -> None:
    os.makedirs(fleet_dir(), exist_ok=True)
    textio.write_text(cache_path(), json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def fresh(cached: dict, jql: str, ttl: int, now: float | None = None) -> bool:
    """Is the cache still worth serving? A different JQL is never fresh, whatever its age."""
    if not cached or cached.get("jql") != jql:
        return False
    try:
        return (now or time.time()) - float(cached.get("fetched_at") or 0) < ttl
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------------------------- the fetch


def normalize(issues: list[dict]) -> list[dict]:
    """Jira's nested shape flattened to what a tile row needs, and nothing else."""
    out = []
    for issue in issues or []:
        f = issue.get("fields") or {}
        status = f.get("status") or {}
        out.append({"key": issue.get("key", ""),
                    "summary": str(f.get("summary") or "").strip(),
                    "status": str(status.get("name") or ""),
                    "category": str(((status.get("statusCategory") or {}).get("key")) or ""),
                    "type": str((f.get("issuetype") or {}).get("name") or ""),
                    "priority": str((f.get("priority") or {}).get("name") or ""),
                    "updated": str(f.get("updated") or "")[:19],
                    "project": project_of(issue.get("key", ""))})
    return out


def fetch(*, cfg: dict | None = None, client=None) -> list[dict]:
    """Ask Jira. `client` is injectable so the tests never need a network or a token."""
    s = settings(cfg)
    if client is None:
        from .. import cli_jira

        try:
            _cfg, client, _me = cli_jira._client()
        except Exception as e:                    # noqa: BLE001 - any credential or flavor failure
            raise BoardError(f"Jira is not reachable: {str(e)[:200]}",
                             "`ad-jira whoami` checks the token and the flavour; the fleet uses the "
                             "same one pncli stores and asks for no second login") from None
    try:
        issues = client.search(s["jql"], [f.strip() for f in s["fields"].split(",") if f.strip()])
    except Exception as e:                        # noqa: BLE001 - Jira's own error text is the hint
        raise BoardError("the board query failed", str(e)[:300]) from None
    return normalize(issues)


def board(*, cfg: dict | None = None, client=None, force: bool = False,
          now: float | None = None) -> dict:
    """The board, from cache when it is fresh enough. Returns rows plus how they were obtained."""
    s = settings(cfg)
    cached = read_cache()
    if not force and fresh(cached, s["jql"], s["ttl"], now):
        age = int((now or time.time()) - float(cached.get("fetched_at") or 0))
        return {"rows": cached.get("rows") or [], "cached": True, "age_s": age, "jql": s["jql"]}

    rows = fetch(cfg=cfg, client=client)
    write_cache({"jql": s["jql"], "fetched_at": now or time.time(), "rows": rows})
    return {"rows": rows, "cached": False, "age_s": 0, "jql": s["jql"]}


# ---------------------------------------------------------------- which repo does this belong to


def suggest(key: str, registry: Registry | None = None) -> dict:
    """Where a ticket probably goes, and honestly when that is not knowable.

    Three answers, because the operator needs a different thing in each case: one repo means the
    drag has an obvious target; several means *pick*, and guessing would eventually start the wrong
    checkout; none means the repository is not registered yet, which is a one-line fix worth naming.
    """
    project = project_of(key)
    if not project:
        return {"key": key, "project": "", "repo": "", "candidates": [],
                "why": f"{key!r} is not a Jira key", "hint": "keys look like RDSD-101"}
    try:
        repos = [r for r in (registry or Registry()).sorted()
                 if (r.jira_project or "").upper() == project]
    except RegistryError:
        repos = []
    names = [r.name for r in repos]
    if len(names) == 1:
        return {"key": key, "project": project, "repo": names[0], "candidates": names,
                "why": f"{names[0]} declares jira_project {project}", "hint": ""}
    if names:
        return {"key": key, "project": project, "repo": "", "candidates": names,
                "why": f"{len(names)} repositories declare {project}", "hint": "pick one"}
    return {"key": key, "project": project, "repo": "", "candidates": [],
            "why": f"no registered repository declares jira_project {project}",
            "hint": f"`ad-fleet repo add <path>` for the {project} checkout"}


def with_suggestions(rows: list[dict], registry: Registry | None = None) -> list[dict]:
    reg = registry or Registry()
    return [{**row, "suggested": suggest(row.get("key", ""), reg)} for row in rows]


def find(rows: list[dict], key: str) -> dict:
    key = (key or "").strip().upper()
    for row in rows:
        if (row.get("key") or "").upper() == key:
            return row
    return {}


# ------------------------------------------------------------------ what was dispatched, and how

SINCE = re.compile(r"^(\d+)\s*([dhm])$", re.I)


def since_seconds(spec: str, default: int = 7 * 86400) -> int:
    """`7d`, `12h`, `90m`. Anything else is the default rather than an error: this is a report."""
    m = SINCE.match((spec or "").strip())
    if not m:
        return default
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"d": 86400, "h": 3600, "m": 60}[unit]


def history(*, since: int = 7 * 86400, registry: Registry | None = None,
            now: float | None = None) -> list[dict]:
    """One row per dispatch: what was started, where, how it ended, what it cost.

    Read from the event store and nothing else, so it agrees with the tiles by construction rather
    than by a second bookkeeping file somebody has to remember to write.
    """
    import calendar

    from . import agentstate, events as E

    cutoff = (now or time.time()) - since
    out: list[dict] = []
    try:
        names = [r.name for r in (registry or Registry()).sorted()]
    except RegistryError:
        names = []

    for name in names:
        stream = E.read(name)
        run: dict = {}
        fold = agentstate.Fold()
        for ev in stream:
            fold.add(ev)
            kind = ev.get("kind")
            if kind == "started" and not (ev.get("data") or {}).get("resumed"):
                # A new dispatch closes the previous one, however it ended -- a run with no `exited`
                # is a run that was killed, and hiding it would hide exactly the interesting case.
                if run:
                    out.append(_close(run, fold))
                run = {"repo": name, "ticket": ev.get("ticket", ""),
                       "summary": (ev.get("data") or {}).get("summary", ""),
                       "started": ev.get("ts", ""), "ended": "", "seq": ev.get("seq", 0)}
                fold = agentstate.Fold().add(ev)
            elif run and kind in ("exited", "error"):
                run["ended"] = ev.get("ts", "")
        if run:
            out.append(_close(run, fold))

    def when(row):
        try:
            return calendar.timegm(time.strptime(str(row.get("started"))[:19], "%Y-%m-%dT%H:%M:%S"))
        except (TypeError, ValueError):
            return 0.0

    return sorted([r for r in out if when(r) >= cutoff], key=when)


def _close(run: dict, fold) -> dict:
    from . import agentstate

    final = agentstate.classify(fold)
    return {**run, "state": final["state"], "phase": final["phase"],
            "premium_requests": final["premium_requests"], "turns": final["turns"],
            "pr_url": run.get("pr_url", "")}
