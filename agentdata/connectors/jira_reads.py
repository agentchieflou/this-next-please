"""The three Jira reads that used to be pncli-only -- search, one issue, its comments -- over REST, as
`AgentTable`s with the columns pncli taught us (`jira_columns.py`, `docs/pncli-parts.md`).

`backend()` is the one switch every caller uses: the REST path whenever credentials exist (env, keyring or
pncli's own config file -- `jira_api.load_credentials`), pncli's launcher only when they do not. Both
answer `jira_search` / `get_issue` / `get_comments` with the same signatures, so a caller holds a module and
never knows which one.
"""
from __future__ import annotations

from typing import Any

from .. import config as C
from ..model import AgentTable
from . import jira_api as J
from . import jira_columns as COLS

# What `get_issue` answers without `--fields`: the issue columns pncli printed, plus the counts a pre-flight
# reads (`fleet/preflight.py`) and the two names that say who and when.
ISSUE_FIELD_IDS = ["summary", "status", "assignee", "reporter", "priority", "issuetype", "resolution", "labels",
                   "created", "updated", "description", "comment", "attachment", "parent"]
ISSUE_COLUMNS = ["key", "status", "assignee", "priority", "updated", "summary", "description", "issuetype",
                 "resolution", "labels", "reporter", "created", "parent", "comments", "attachment"]
COMMENT_COLUMNS = ["id", "author", "created", "updated", "body"]


def client(cfg: dict | None = None) -> J.Jira:
    """A REST client from the stored flavor (one `/myself` call proves the token before any read)."""
    cfg = cfg if cfg is not None else C.load()
    j, _me = J.detect_flavor(J.load_credentials(cfg), cfg)
    return j


def backend(cfg: dict | None = None):
    """This module when REST credentials exist, else the pncli connector (the optional backend)."""
    import sys
    if J.has_credentials(cfg):
        return sys.modules[__name__]
    from . import pncli
    return pncli


def text(value: Any) -> str:
    """A rich-text field as plain text: Cloud answers ADF (a dict), Data Center a string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        from ..fleet.command import adf_text
        return adf_text(value)
    return str(value)


def _name(d: Any) -> str:
    return str((d or {}).get("displayName") or (d or {}).get("name") or "") if isinstance(d, dict) else ""


def issue_record(issue: dict) -> dict:
    """One issue as the flat row `ad-jira get` prints; `comments` and `attachment` are counts."""
    f = issue.get("fields") or {}
    comment = f.get("comment") or {}
    n_comments = comment.get("total") if isinstance(comment, dict) else None
    if n_comments is None:
        n_comments = len(comment.get("comments") or []) if isinstance(comment, dict) else 0
    parent = f.get("parent") or {}
    return {"key": issue.get("key"), "status": _name(f.get("status")), "assignee": _name(f.get("assignee")),
            "priority": _name(f.get("priority")), "updated": f.get("updated"), "summary": f.get("summary"),
            "description": text(f.get("description")), "issuetype": _name(f.get("issuetype")),
            "resolution": _name(f.get("resolution")), "labels": ";".join(str(x) for x in f.get("labels") or []),
            "reporter": _name(f.get("reporter")), "created": f.get("created"),
            "parent": parent.get("key") if isinstance(parent, dict) else "",
            "comments": int(n_comments), "attachment": len(f.get("attachment") or [])}


def jira_search(jql: str, fields: list[str] | None = None, max_results: int = 500, j: J.Jira | None = None,
                cfg: dict | None = None) -> AgentTable:
    """`ad-jira search`: the issues a JQL matches, the columns pncli's search printed. A JQL wider than
    `max_results` is answered as the first `max_results` rows with `truncated` set, as pncli's was."""
    j = j or client(cfg)
    want = COLS.paths(fields or COLS.JIRA_DEFAULT_FIELDS)
    issues = j.search(jql, COLS.field_ids(want), max_results=max_results, truncate=True)
    truncated = len(issues) > max_results
    recs = issues[:max_results]
    t = AgentTable.from_records(recs, name="jira", source=f"ad-jira search --jql {jql!r}", fields=want, raw=recs)
    t.columns = COLS.rename(t.columns, COLS.JIRA_RENAME)
    t.elapsed_s = float(getattr(j.stats, "elapsed_seconds", 0.0) or 0.0)
    t.truncated = truncated
    return t


def get_issue(key: str, fields: list[str] | None = None, j: J.Jira | None = None,
              cfg: dict | None = None) -> AgentTable:
    """`ad-jira get`: one issue as one row. `fields` narrows to those columns (short names as the TSV prints
    them); a name that is not one of them is read from the issue's `fields` by id."""
    j = j or client(cfg)
    short = [c for c in COLS.rename(COLS.paths(fields)) if c] if fields else ISSUE_COLUMNS
    extra = [c for c in short if c not in ISSUE_COLUMNS]
    issue = j.issue(key, ISSUE_FIELD_IDS + extra) or {}
    rec = issue_record(issue)
    for c in extra:
        rec[c] = (issue.get("fields") or {}).get(c)
    t = AgentTable.from_records([rec], name="issue", source=f"ad-jira get {key}", fields=short, raw=issue)
    return t


def get_comments(key: str, j: J.Jira | None = None, cfg: dict | None = None) -> AgentTable:
    """`ad-jira comments`: one row a comment, oldest first, the body as plain text."""
    j = j or client(cfg)
    rows = [{"id": c.get("id"), "author": _name(c.get("author")), "created": c.get("created"),
             "updated": c.get("updated"), "body": text(c.get("body"))} for c in j.comments(key)]
    return AgentTable.from_records(rows, name="comments", source=f"ad-jira comments {key}", fields=COMMENT_COLUMNS,
                                   raw=rows)
