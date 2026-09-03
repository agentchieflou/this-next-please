"""Which transitions this issue actually has, and which one "move it to review" means.

A Jira workflow belongs to the ISSUE TYPE, not the project: a Story may go `In Progress -> In Review -> Done`
while a Task in the same project goes `In Progress -> Done` and has no review state at all. Hard-coding
`"In Review"` therefore works on Stories and fails on Tasks, which is exactly what happened. Nothing here
guesses a status name: the only source of truth is the transition list Jira returns for that one issue, and an
intent that the issue's own workflow cannot satisfy is refused with the list of what it can do.

Resolution order, most specific first: a name pinned for this issue type -> the transition's own name -> the
target status name -> a known name for the intent -> the only transition into the intent's status category ->
a unique substring. Ambiguity is never broken by guessing; it is reported with the candidates.
"""
from __future__ import annotations

import re
from typing import Any

# Intent -> the status category it must land in, and the names workflows actually use for it, best first.
# `by_category` says whether the status category IS the intent. It is for todo/in-progress/done, so a workflow
# that spells them differently still resolves. It is not for review or blocked: those are particular states, and
# "the only other in-progress transition" is not a review -- silently sending a ticket there is the failure this
# module exists to prevent. Cover those on a workflow that names them oddly with --pin.
INTENTS: dict[str, dict] = {
    "todo": {"category": "new", "by_category": True,
             "names": ["to do", "todo", "open", "backlog", "new", "reopen", "reopen issue", "stop progress"]},
    "in-progress": {"category": "indeterminate", "by_category": True,
                    "names": ["in progress", "start progress", "start work", "start", "in development", "in dev",
                              "doing", "implementing"]},
    "review": {"category": "indeterminate", "by_category": False,
               "names": ["in review", "ready for review", "code review", "peer review", "review", "submit for review",
                         "ready for qa", "in qa", "in test", "testing"]},
    "blocked": {"category": "indeterminate", "by_category": False,
                "names": ["blocked", "on hold", "impediment", "waiting"]},
    "done": {"category": "done", "by_category": True,
             "names": ["done", "closed", "close issue", "close", "complete", "completed", "resolve issue", "resolved",
                       "resolve", "finish", "finished"]},
}
INTENT_ALIASES = {
    "in_progress": "in-progress", "inprogress": "in-progress", "progress": "in-progress", "start": "in-progress",
    "in-review": "review", "in_review": "review", "inreview": "review", "code-review": "review", "qa": "review",
    "to-do": "todo", "to_do": "todo", "open": "todo", "backlog": "todo", "reopen": "todo",
    "close": "done", "closed": "done", "complete": "done", "completed": "done", "resolved": "done", "finish": "done",
    "block": "blocked", "on-hold": "blocked",
}


class WorkflowError(Exception):
    def __init__(self, msg: str, hint: str = "", available: list[dict] | None = None):
        super().__init__(msg)
        self.hint, self.available = hint, available or []


def intent_of(want: str) -> str:
    """`"In Review"`, `in_review` and `review` are the same intent; a status name nothing knows is not one."""
    key = re.sub(r"\s+", "-", (want or "").strip().lower())
    key = INTENT_ALIASES.get(key, key)
    if key in INTENTS:
        return key
    for name, spec in INTENTS.items():
        if key.replace("-", " ") in spec["names"]:
            return name
    return ""


def type_key(issue_type: str) -> str:
    """`Sub-task` and `sub task` pin to the same config key; `.` would split a config dot-path."""
    return re.sub(r"[^a-z0-9]+", "-", (issue_type or "").strip().lower()).strip("-") or "unknown"


def normalize(transitions: list[dict]) -> list[dict]:
    """Jira's transition JSON -> flat rows. `requires` names the fields a transition screen will demand, which is
    the difference between a clean POST and a 400 nobody can read."""
    rows = []
    for t in transitions or []:
        to = t.get("to") or {}
        req = [f.get("name") or fid for fid, f in (t.get("fields") or {}).items()
               if f.get("required") and not f.get("hasDefaultValue")]
        rows.append({"id": str(t.get("id") or ""), "name": t.get("name") or "",
                     "to_id": str(to.get("id") or ""), "to_status": to.get("name") or "",
                     "to_category": ((to.get("statusCategory") or {}).get("key") or "").lower(),
                     "requires": sorted(req), "looped": bool(t.get("isLooped") or t.get("looped"))})
    return rows


def _hit(rows: list[dict], pred) -> list[dict]:
    return [r for r in rows if pred(r)]


def resolve(rows: list[dict], want: str, issue_type: str = "", pinned: str = "") -> tuple[dict, str]:
    """-> (the transition to run, why it was chosen). Raises WorkflowError carrying every candidate."""
    if not rows:
        raise WorkflowError("this issue has no available transitions",
                            hint="the workflow offers nothing from its current status to this account: check the "
                                 "issue is not closed and that you have the Transition Issues permission")
    want_l = (want or "").strip().lower()
    if not want_l:
        raise WorkflowError("no target given", hint='pass --to "<status or transition name>" or an intent: '
                                                   + ", ".join(INTENTS), available=rows)
    if pinned:
        p = pinned.strip().lower()
        hit = _hit(rows, lambda r: r["name"].lower() == p or r["to_status"].lower() == p)
        if hit:
            return hit[0], f"pinned for {issue_type or 'this type'}"
        raise WorkflowError(f"pinned target {pinned!r} is not available on this issue",
                            hint=f"the pin for {type_key(issue_type)} is stale: re-pin with "
                                 f'ad-jira transition <KEY> --to "<name>" --pin, or clear jira.workflow.'
                                 f"{type_key(issue_type)}", available=rows)
    for pred, why in ((lambda r: r["name"].lower() == want_l, "transition name"),
                      (lambda r: r["to_status"].lower() == want_l, "status name")):
        hit = _hit(rows, pred)
        if len(hit) == 1:
            return hit[0], why
        if hit:
            raise WorkflowError(f"{want!r} matches {len(hit)} transitions by {why}",
                                hint="use the transition id: " + ", ".join(f"{r['id']}={r['name']}" for r in hit),
                                available=rows)
    intent = intent_of(want)
    if intent:
        spec = INTENTS[intent]
        for name in spec["names"]:
            hit = _hit(rows, lambda r, n=name: r["name"].lower() == n or r["to_status"].lower() == n)
            if hit:
                return hit[0], f"intent {intent}"
        hit = _hit(rows, lambda r: r["to_category"] == spec["category"] and not r["looped"]) if spec["by_category"] else []
        if len(hit) == 1:
            return hit[0], f"intent {intent} (only transition to a {spec['category']} status)"
        if hit:
            raise WorkflowError(f"{issue_type or 'this issue'} has {len(hit)} transitions into a "
                                f"{spec['category']} status, so {want!r} is ambiguous",
                                hint='name the one you mean: --to "' + '" or --to "'.join(r["to_status"] for r in hit) + '"',
                                available=rows)
        raise WorkflowError(f"no {intent} transition on this {issue_type or 'issue'}",
                            hint=f"a {issue_type or 'issue'} workflow need not have one -- Stories and Tasks differ; "
                                 f'run it with --to "<one of the names below>", or skip the step',
                            available=rows)
    hit = _hit(rows, lambda r: want_l in r["name"].lower() or want_l in r["to_status"].lower())
    if len(hit) == 1:
        return hit[0], "substring"
    raise WorkflowError(f"{want!r} matches {len(hit)} of this issue's transitions",
                        hint="use an exact name from the list, or an intent: " + ", ".join(INTENTS), available=rows)


def already_there(status: str, want: str) -> bool:
    """Re-running a skill must not fail because the ticket is already where it belongs."""
    s, w = (status or "").strip().lower(), (want or "").strip().lower()
    if s and s == w:
        return True
    intent = intent_of(want)
    return bool(intent and s in INTENTS[intent]["names"])


def adf(text: str) -> dict:
    """Cloud's REST v3 rejects a plain string comment body; Data Center's v2 rejects this. Flavor decides."""
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def field_value(raw: str) -> Any:
    """`resolution={"name":"Done"}` when it parses as JSON, else the plain string Jira wants for a text field."""
    import json
    try:
        return json.loads(raw)
    except ValueError:
        return raw
