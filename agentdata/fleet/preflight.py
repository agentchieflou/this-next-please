"""Is this ticket ready to hand to an agent? (#164)

A drop used to be a launch. It is now a **card**, and this module is what fills it in: the rows a
person would have checked themselves before delegating, gathered from what the fleet already holds
and at most one Jira read, and folded into one of four words.

**It spends no premium request.** Nothing here starts a model, and that is the whole point: the
cheapest moment to notice that a ticket says *"UAT refresh is slow"* and nothing else is *before*
an agent has read it, made a plan and stopped on it.

**It is a courtesy, not a gate.** Being unable to reach Jira never blocks a start -- exactly as the
Done check never has ([fleet-intake.md](../../docs/fleet-intake.md)). A source that cannot be read
goes grey with its error, the verdict reads `unknown`, and *Start* stays enabled. The two things
that genuinely refuse are the guard rails that already refused in `supervisor.check_ticket`, and
they refuse here with the same words and the same `code` the CLI would print.
"""
from __future__ import annotations
import json
import os
import re
import time
from typing import Any

from .. import config as C
from .. import textio
from . import board as B
from . import events as E
from .registry import Registry, RegistryError, fleet_dir

# The four words a card can end in. `blocked` is one of `supervisor.check_ticket`'s refusals and
# means the start would be refused; `unknown` means a source could not be read and says so rather
# than guessing; `thin` is the judgement this module exists to make.
READY, THIN, BLOCKED, UNKNOWN = "ready", "thin", "blocked", "unknown"

# What "thin" means, in one place so the rule is arguable rather than scattered. A description
# shorter than this many words, with no criteria found, is not something an agent can act on -- it
# is a title with a full stop.
THIN_WORDS = 25

# Acceptance criteria, as five shapes a real Jira description uses. This is a *heuristic over the
# description*, and it says so on the card: "none found" is not "none exist", which is why the
# verdict is `thin` (a nudge to write a brief) and never `blocked` (a refusal to start).
_AC_HEADING = re.compile(r"^\s*#*\s*(acceptance criteria|ac)\b[:\s]*$", re.I | re.M)
_AC_NUMBERED = re.compile(r"^\s*\d+[.)]\s+\S", re.M)
_AC_CHECKBOX = re.compile(r"^\s*[-*]\s*\[[ xX]?\]\s*\S", re.M)
_AC_BULLET = re.compile(r"^\s*[-*•]\s+\S", re.M)
_AC_GHERKIN = re.compile(r"^\s*given\b.*$\n(?:.*\n)*?^\s*then\b", re.I | re.M)

# Capitalised or quoted names a description mentions, looked up in the catalogue so the card can
# say *which project already knows about this*. Two letters minimum, because "A" and "I" are words.
_NAME = re.compile(r'"([^"]{2,40})"|\b([A-Z][a-zA-Z0-9]{2,})\b')
# Words that are capitalised because they start a sentence or are Jira furniture, not because they
# name anything. Looking each of these up would put a row on every card that says nothing.
_NOT_A_NAME = frozenset({
    "The", "This", "That", "These", "Those", "There", "Then", "They", "When", "Where", "Which",
    "What", "While", "With", "Without", "And", "But", "For", "Not", "All", "Any", "Are", "Was",
    "Given", "Should", "Would", "Could", "Must", "Jira", "Story", "Task", "Bug", "Epic", "Done",
    "Todo", "Note", "See", "Add", "Fix", "Use", "Run", "Make", "Set", "Get", "Per", "Via", "Now",
    # the furniture of a well-written ticket, which is exactly the ticket whose names matter
    "Acceptance", "Criteria", "Steps", "Reproduce", "Expected", "Actual", "Context", "Scope",
    "Background", "Definition", "Details", "Summary", "Description", "Impact", "Risk", "Notes",
    "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
})


class PreflightError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


# --------------------------------------------------------------------------------- the issue cache


def cache_path() -> str:
    """Beside every other thing the fleet remembers, and outside every repository."""
    return textio.norm_path(os.path.join(fleet_dir(), "preflight.json"))


def read_cache() -> dict:
    try:
        return json.loads(textio.read_text(cache_path()) or "{}")
    except (OSError, ValueError):
        return {}


def write_cache(payload: dict) -> None:
    try:
        textio.write_text(cache_path(), json.dumps(payload, indent=1, sort_keys=True))
    except OSError:
        pass          # a cache that cannot be written costs one more Jira read, and nothing else


def _cached_issue(key: str, ttl: int, now: float | None = None) -> dict | None:
    """The issue this key was last fetched as, if it is still inside the TTL.

    The TTL is `fleet.board_ttl`, shared with the board, for the reason the board has one: a ticket
    that changed thirty seconds ago is not urgent, and a fetch per drop per tile is how a shared
    Jira instance starts rate-limiting a team.
    """
    row = (read_cache().get("issues") or {}).get(key.upper())
    if not isinstance(row, dict):
        return None
    age = (now if now is not None else time.time()) - float(row.get("at") or 0)
    return row if 0 <= age <= ttl else None


def _remember(key: str, issue: dict, now: float | None = None) -> None:
    payload = read_cache()
    issues = payload.setdefault("issues", {})
    issues[key.upper()] = dict(issue, at=now if now is not None else time.time())
    # Bounded: one entry per ticket ever dropped would grow without end, and the only rows worth
    # keeping are the ones inside a TTL measured in minutes.
    if len(issues) > 200:
        for stale in sorted(issues, key=lambda k: issues[k].get("at") or 0)[:len(issues) - 200]:
            del issues[stale]
    write_cache(payload)


def fetch_issue(key: str, *, cfg: dict | None = None, client=None,
                now: float | None = None) -> dict:
    """The one Jira read a drop makes. Never raises: a failure is a row, not an exception.

    Returns `{description, issuetype, comments, attachments, error}` -- `error` set means every
    field is empty and the card says why rather than showing a confident blank.
    """
    ttl = int(B.settings(cfg).get("ttl") or 0)
    hit = _cached_issue(key, ttl, now=now)
    if hit is not None:
        return dict(hit, cached=True)

    issue: dict[str, Any] = {"description": "", "issuetype": "", "comments": 0,
                             "attachments": 0, "error": "", "cached": False}
    try:
        if client is not None:
            table = client.get_issue(key)
        else:
            from ..connectors import pncli

            table = pncli.get_issue(key)
        rows = getattr(table, "rows", None) or []
        cols = list(getattr(table, "columns", None) or [])
        if rows:
            row = dict(zip(cols, rows[0])) if cols else dict(rows[0])
            issue["description"] = str(row.get("description") or "")
            issue["issuetype"] = str(row.get("issuetype") or "")
            for name, field in (("comments", "comments"), ("attachments", "attachment")):
                value = row.get(field)
                issue[name] = len(value) if isinstance(value, list) else int(value or 0)
    except Exception as e:               # noqa: BLE001 - every failure is the same row to a person
        issue["error"] = str(e) or e.__class__.__name__
        return issue
    _remember(key, issue, now=now)
    return issue


# ---------------------------------------------------------------------------------------- the rows


def _row(name: str, value: str, *, verdict: str = READY, why: str = "", age: str = "") -> dict:
    return {"row": name, "value": value, "verdict": verdict, "why": why, "age": age}


def criteria_found(description: str) -> int:
    """How many acceptance criteria the description appears to carry.

    Deliberately a count and not a list: the card says *four found*, and the agent still reads them
    itself through `ad-pncli`, because a fleet that pasted criteria into a card would be showing the
    operator a second, staler copy of the ticket.
    """
    if not description.strip():
        return 0
    body = description
    heading = _AC_HEADING.search(body)
    if heading:
        body = body[heading.end():]
    for pattern in (_AC_CHECKBOX, _AC_NUMBERED, _AC_BULLET):
        found = pattern.findall(body)
        if len(found) >= 2 or (found and heading):
            return len(found)
    if _AC_GHERKIN.search(body):
        return len(re.findall(r"^\s*given\b", body, re.I | re.M))
    return 0


def names_mentioned(text: str, limit: int = 6) -> list[str]:
    """Capitalised or quoted names worth asking the catalogue about."""
    out: list[str] = []
    for quoted, bare in _NAME.findall(text or ""):
        name = (quoted or bare).strip()
        if not name or name in _NOT_A_NAME or name.upper() == name and len(name) <= 3:
            continue
        if name not in out:
            out.append(name)
        if len(out) >= limit:
            break
    return out


def _inputs_row(repo, key: str) -> dict:
    """What is already under `.agent/in/<KEY>/`, and whether a branch from a previous attempt exists."""
    bits: list[str] = []
    folder = os.path.join(repo.path, ".agent", "in", textio.safe_name(key))
    try:
        files = [f for f in os.listdir(textio.longpath(folder))
                 if os.path.isfile(os.path.join(folder, f))]
    except OSError:
        files = []
    if files:
        bits.append(f"{len(files)} file{'s' if len(files) != 1 else ''} already attached")
    branch = _branch_for(repo, key)
    if branch:
        bits.append(f"a branch exists from a previous attempt ({branch})")
    if not bits:
        return _row("here", "nothing yet")
    return _row("here", "; ".join(bits), why="an earlier attempt left something behind")


def _branch_for(repo, key: str) -> str:
    """A `feature/<KEY>-*` branch in this checkout, read from git's own refs and nothing else."""
    head = os.path.join(repo.path, ".git", "refs", "heads", "feature")
    try:
        for name in os.listdir(textio.longpath(head)):
            if name.upper().startswith(key.upper() + "-"):
                return f"feature/{name}"
    except OSError:
        pass
    return ""


def _history_row(key: str, registry: Registry | None = None) -> dict:
    """How earlier dispatches of this key ended -- the row that makes a repeat honest."""
    try:
        runs = [r for r in (B.history(registry=registry) or [])
                if str(r.get("ticket") or "").upper() == key.upper()]
    except Exception:                    # noqa: BLE001 - the event store is a courtesy here too
        return _row("history", "unknown", verdict=UNKNOWN, why="the event store could not be read")
    if not runs:
        return _row("history", "not dispatched before")
    endings = [str(r.get("state") or "") for r in runs]
    worst = "blocked" if "blocked" in endings else (endings[-1] or "unknown")
    value = f"dispatched {len(runs)} time{'s' if len(runs) != 1 else ''}"
    if worst in ("blocked", "error", "needs_human"):
        return _row("history", f"{value}; ended {worst}", verdict=THIN,
                    why="it stopped needing a person last time; a brief is what changes that")
    return _row("history", f"{value}; ended {endings[-1] or 'unknown'}")


def _catalogue_row(names: list[str], repo_name: str) -> dict:
    if not names:
        return _row("mentions", "nothing the catalogue knows")
    try:
        from .catalogue import Catalogue

        cat = Catalogue()
        try:
            for name in names:
                hits = cat.where(name, limit=3) or []
                for hit in hits:
                    where = str(hit.get("project") or "")
                    if not where:
                        continue
                    if where != repo_name:
                        return _row("mentions", f"{name} — {where} declares it", verdict=THIN,
                                    why=f"the match is in {where}, not {repo_name}")
                    return _row("mentions", f"{name} — {where} declares it")
        finally:
            cat.close()
    except Exception as e:               # noqa: BLE001 - no catalogue is a grey row, never an error
        return _row("mentions", "unknown", verdict=UNKNOWN, why=f"the catalogue could not be read: {e}")
    return _row("mentions", ", ".join(names[:3]) + " — none of them indexed")


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


# -------------------------------------------------------------------------------------- the verdict


def verdict_for(rows: list[dict]) -> str:
    """One table, one function. The first rule that matches wins.

    Ordering is the point: a refusal outranks everything because the start will not happen; an
    unreadable source outranks a judgement because a card that says `thin` on evidence it could not
    read is worse than one that admits it does not know.
    """
    kinds = {r.get("verdict") for r in rows}
    if BLOCKED in kinds:
        return BLOCKED
    if UNKNOWN in kinds:
        return UNKNOWN
    if THIN in kinds:
        return THIN
    return READY


def preflight(key: str, repo_name: str = "", *, cfg: dict | None = None, client=None,
              registry: Registry | None = None, now: float | None = None) -> dict:
    """The card, as data. Never raises for a reason a person can act on -- those are rows."""
    key = (key or "").strip().upper()
    cfg = cfg if cfg is not None else C.load()
    reg = registry or Registry()
    rows: list[dict] = []

    suggestion = B.suggest(key, registry=reg)
    if not suggestion.get("project"):
        rows.append(_row("ticket", key or "(none)", verdict=BLOCKED,
                         why=suggestion.get("why", ""), age=""))
        return {"ok": True, "key": key, "repo": repo_name, "verdict": BLOCKED, "rows": rows,
                "suggestion": suggestion, "at": E.stamp()}

    repo_name = repo_name or suggestion.get("repo") or ""
    rows.append(_row("ticket", key))

    # The guard rails, asked here exactly as `ad-fleet start` will ask them, so the card cannot
    # promise a start the CLI would refuse.
    repo = None
    if repo_name:
        try:
            repo = reg.get(repo_name)
        except (RegistryError, KeyError):
            repo = None
    if repo is None:
        rows.append(_row("repo", repo_name or "none", verdict=BLOCKED,
                         why=suggestion.get("why") or f"{repo_name!r} is not registered"))
    else:
        from . import supervisor

        try:
            summary = supervisor.check_ticket(
                repo, key, board_rows=(B.read_cache() or {}).get("rows") or [])
            rows.append(_row("repo", repo.name, why=suggestion.get("why", "")))
            if summary:
                rows.append(_row("summary", summary))
        except supervisor.SupervisorError as e:
            rows.append(_row("repo", repo.name, verdict=BLOCKED, why=e.msg))
            rows[-1]["code"] = e.code
            rows[-1]["hint"] = e.hint

    issue = fetch_issue(key, cfg=cfg, client=client, now=now)
    if issue.get("error"):
        rows.append(_row("description", "unknown", verdict=UNKNOWN,
                         why=f"Jira could not be read: {issue['error']}"))
        rows.append(_row("criteria", "unknown", verdict=UNKNOWN, why="no description to read"))
    else:
        words = _words(issue.get("description") or "")
        age = "cached" if issue.get("cached") else "now"
        if words == 0:
            rows.append(_row("description", "empty", verdict=THIN, age=age,
                             why="there is nothing for the agent to read"))
        elif words < THIN_WORDS:
            rows.append(_row("description", f"{words} words", verdict=THIN, age=age,
                             why="a title with a full stop is not a specification"))
        else:
            rows.append(_row("description", f"{words} words", age=age))
        found = criteria_found(issue.get("description") or "")
        if found:
            rows.append(_row("criteria", f"{found} found", age=age))
        else:
            rows.append(_row("criteria", "none found", verdict=THIN, age=age,
                             why="the agent will have to infer what done means"))
        if issue.get("comments"):
            rows.append(_row("comments", f"{issue['comments']}", age=age,
                             why="a human may already have answered there"))
        if issue.get("attachments"):
            rows.append(_row("attachments", f"{issue['attachments']}", age=age,
                             why="the fleet cannot fetch these; attach what matters"))
        rows.append(_catalogue_row(names_mentioned(issue.get("description") or ""), repo_name))

    rows.append(_history_row(key, registry=reg))
    if repo is not None:
        rows.append(_inputs_row(repo, key))

    return {"ok": True, "key": key, "repo": repo_name, "verdict": verdict_for(rows), "rows": rows,
            "suggestion": suggestion, "at": E.stamp()}
