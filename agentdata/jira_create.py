"""`ad-jira create`: a ticket the agent opens itself, with the project's own defaults filled in.

Until now the agent would not start without a ticket somebody else had written, and could not write
one: `jira-triage` reads a key, `bitbucket-pr` refuses without `active_ticket`, and nothing in
between could say "make one". This is that verb. What a right ticket looks like for a project --
the issue type, its components, the *Primary Domain* select, the labels, the epic it hangs under --
is the project's knowledge, so it lives in the project's `AGENTS.md` as facts, beside `jira_project`:

    - jira_project: RDSD
    - jira_issue_type: Task
    - jira_components: Data Platform, Reporting
    - jira_labels: agent
    - jira_fields: Primary Domain=Data; Team=BI Platform
    - jira_parent: RDSD-100
    - jira_assignee: me

Field *names* are what a person knows; Jira wants ids and typed values. Both are resolved at run
time against `GET /field`: `Primary Domain=Data` becomes `{"customfield_10123": {"value": "Data"}}`
for a select list, a labels-shaped field gets a list, a user field gets an accountId. A name that
does not exist is refused with the nearest matches, before anything is sent.

The write is gated the way every write here is: `--dry-run` prints the exact payload, and inside a
fleet `approval.require("jira-create", ...)` holds the POST for one click. The POST itself is never
retried -- a create that timed out may well have created.
"""
from __future__ import annotations
import json
import re
from typing import Any

from . import jira_workflow as W

FACT_KEYS = ("jira_project", "jira_issue_type", "jira_components", "jira_labels", "jira_fields", "jira_parent",
             "jira_assignee")
DEFAULT_ISSUE_TYPE = "Task"
# Field types whose value Jira wants as {"name": ...}.
_NAMED = ("priority", "component", "version", "resolution", "issuetype", "project", "securitylevel")
_WORDS = re.compile(r"[a-z0-9]+")


class CreateError(Exception):
    def __init__(self, msg: str, hint: str = "", available: list[str] | None = None):
        super().__init__(msg)
        self.hint, self.available = hint, available or []


def split_list(raw: Any) -> list[str]:
    """`a, b, c` -> `["a", "b", "c"]`; a list comes back stripped; empty is empty."""
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    return [str(x).strip() for x in items if str(x).strip()]


def parse_pairs(items: Any) -> dict[str, str]:
    """`Primary Domain=Data; Team=BI` (a fact) or `["Primary Domain=Data", "Team=BI"]` (--field) -> {name: raw}.

    A `;` separates pairs in the one-line fact form, so a value in that form cannot contain one;
    `--field` takes each pair whole and can. An item without `=` is refused by name, not dropped.
    """
    if items is None:
        return {}
    parts = [p for p in str(items).split(";")] if isinstance(items, str) else list(items)
    out: dict[str, str] = {}
    for item in parts:
        item = str(item).strip()
        if not item:
            continue
        if "=" not in item:
            raise CreateError(f"a field is NAME=VALUE, got {item!r}", 'example: --field "Primary Domain=Data"')
        name, value = item.split("=", 1)
        if name.strip():
            out[name.strip()] = value.strip()
    return out


def defaults(facts: dict) -> dict:
    """The project's ticket shape, from its AGENTS.md facts. Every key present, empty when unset."""
    f = facts or {}
    return {"project": (f.get("jira_project") or "").strip() or None,
            "issue_type": (f.get("jira_issue_type") or "").strip() or DEFAULT_ISSUE_TYPE,
            "components": split_list(f.get("jira_components")),
            "labels": split_list(f.get("jira_labels")),
            "fields": parse_pairs(f.get("jira_fields")),
            "parent": (f.get("jira_parent") or "").strip() or None,
            "assignee": (f.get("jira_assignee") or "").strip() or None}


def user_ref(value: str, cloud: bool) -> dict:
    return {"accountId": value} if cloud else {"name": value}


def coerce(meta: dict, value: Any, cloud: bool = True) -> Any:
    """`value` in the shape this field's schema wants. A value that already parsed as JSON is trusted."""
    if not isinstance(value, str):
        return value
    sch = meta.get("schema") or {}
    t, items = sch.get("type"), sch.get("items")
    if t in ("option", "option-with-child"):
        return {"value": value}
    if t == "array":
        parts = split_list(value)
        if items == "option":
            return [{"value": p} for p in parts]
        if items == "user":
            return [user_ref(p, cloud) for p in parts]
        if items in _NAMED:
            return [{"name": p} for p in parts]
        return parts
    if t == "number":
        try:
            return float(value) if "." in value else int(value)
        except ValueError:
            raise CreateError(f"{meta.get('name')} wants a number, got {value!r}") from None
    if t == "user":
        return user_ref(value, cloud)
    if t in _NAMED:
        return {"name": value}
    return value                       # string, date, datetime, any


def nearest(name: str, fields_json: list[dict], limit: int = 8) -> list[str]:
    """Field names sharing a word with `name`, for the refusal that says what exists instead."""
    words = set(_WORDS.findall(name.lower()))
    hits = []
    for f in fields_json:
        n = str(f.get("name") or "")
        if words & set(_WORDS.findall(n.lower())):
            hits.append(n)
    return sorted(set(hits))[:limit]


def payload(fields_json: list[dict], *, project: str | None, issue_type: str | None, summary: str | None,
            description: str | None = None, components: list[str] | None = None, labels: list[str] | None = None,
            fields: dict[str, Any] | None = None, parent: str | None = None, assignee: str | None = None,
            me: dict | None = None, cloud: bool = True, api3: bool = True) -> tuple[dict, list[dict]]:
    """The `POST /issue` body, and one row per named field saying what it resolved to.

    Refused before anything is sent: no project, no summary, a field name Jira does not have, a
    value the field's type cannot take, `me` with nobody signed in.
    """
    if not project:
        raise CreateError("no Jira project", "pass --project <KEY>, or set `jira_project` in AGENTS.md")
    if not (summary or "").strip():
        raise CreateError("no summary", 'pass --summary "<one line: what, and why>"')
    by_id = {str(f.get("id")): f for f in fields_json}
    by_name = {str(f.get("name") or "").lower(): f for f in fields_json}
    body: dict[str, Any] = {"project": {"key": project}, "issuetype": {"name": issue_type or DEFAULT_ISSUE_TYPE},
                            "summary": str(summary).strip()}
    if description:
        body["description"] = W.adf(description) if api3 else description
    if components:
        body["components"] = [{"name": c} for c in components]
    if labels:
        body["labels"] = list(labels)
    if parent:
        body["parent"] = {"key": parent}
    if assignee:
        who = assignee
        if assignee.strip().lower() == "me":
            who = (me or {}).get("accountId") if cloud else (me or {}).get("name")
            if not who:
                raise CreateError("assignee `me` needs a signed-in user", "ad-jira whoami")
        body["assignee"] = user_ref(str(who), cloud)
    resolved: list[dict] = []
    for name, raw in (fields or {}).items():
        meta = by_id.get(name) or by_name.get(name.lower())
        if not meta:
            raise CreateError(f"no Jira field named {name!r}",
                              "`ad-jira fields --like <part of the name>` lists them; the name is matched whole, case-insensitively",
                              available=nearest(name, fields_json))
        value = W.field_value(raw) if isinstance(raw, str) else raw
        fid = str(meta["id"])
        body[fid] = coerce(meta, value, cloud)
        sch = meta.get("schema") or {}
        resolved.append({"field": meta.get("name"), "id": fid,
                         "type": sch.get("type", "") + (f"<{sch['items']}>" if sch.get("items") else ""),
                         "value": json.dumps(body[fid], ensure_ascii=False)})
    return {"fields": body}, resolved


def create(j, body: dict) -> dict:
    """`POST /issue`, never replayed. `{id, key, self}` -- and a refusal if Jira answered without a key."""
    res = j.post(f"{j.api}/issue", body, idempotent=False)
    if not isinstance(res, dict) or not res.get("key"):
        raise CreateError("Jira accepted the create but answered without a key",
                          "search the project for the summary before creating again")
    return res


def browse_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/browse/{key}"
