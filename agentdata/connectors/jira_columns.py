"""The column names a Jira read answers with, whichever backend produced the rows.

`ad-jira search|get|comments` (REST) and `ad-pncli jira search|get|comments` (the optional pncli backend)
print the same columns, so a skill written against one keeps working against the other. The names were
pncli's first (`docs/pncli-parts.md`): a flattened issue reads `fields.status.name`, and that is too long for
a TSV header an agent has to type back into a JQL. Nothing here touches the network.
"""
from __future__ import annotations

JIRA_DEFAULT_FIELDS = ["key", "fields.status.name", "fields.assignee.displayName", "fields.priority.name",
                       "fields.updated", "fields.summary"]
JIRA_RENAME = {"fields.status.name": "status", "fields.assignee.displayName": "assignee",
               "fields.priority.name": "priority", "fields.updated": "updated", "fields.summary": "summary"}
ISSUE_RENAME = dict(JIRA_RENAME, **{"fields.description": "description", "fields.issuetype.name": "issuetype",
                                    "fields.resolution.name": "resolution", "fields.labels": "labels"})
ISSUE_RENAME_BACK = {v: k for k, v in ISSUE_RENAME.items()}


def rename(columns: list[str], table: dict[str, str] | None = None) -> list[str]:
    """`fields.status.name` -> `status`; anything unnamed just loses its `fields.` prefix."""
    table = ISSUE_RENAME if table is None else table
    return [table.get(c, c.replace("fields.", "")) for c in columns]


def paths(fields: list[str]) -> list[str]:
    """Short names (`status`) or flattened paths, as flattened paths; `key` stays `key`."""
    return [ISSUE_RENAME_BACK.get(f, f) for f in fields]


def field_ids(fields: list[str]) -> list[str]:
    """The Jira field ids a REST request must ask for to answer these columns: `status` and
    `fields.status.name` both mean the `status` field; `key` is not a field and is always answered."""
    out: list[str] = []
    for f in paths(fields):
        if f == "key":
            continue
        fid = f.split(".")[1] if f.startswith("fields.") else f
        if fid and fid not in out:
            out.append(fid)
    return out
