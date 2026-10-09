"""The column names a Jira read answers with.

`ad-view` gives a saved `pncli jira search` / `pncli jira get-issue` answer these columns, and so do the in-process
reads in `connectors/pncli.py` (the fleet's pre-flight, the UAT live side), so a skill and the code read the same
header. The names were pncli's first (`docs/pncli-parts.md`): a flattened issue reads `fields.status.name`, and that
is too long for a TSV header an agent has to type back into a JQL. Nothing here touches the network.
"""
from __future__ import annotations

JIRA_DEFAULT_FIELDS = ["key", "fields.status.name", "fields.assignee.displayName", "fields.priority.name",
                       "fields.updated", "fields.summary"]
JIRA_RENAME = {"fields.status.name": "status", "fields.assignee.displayName": "assignee",
               "fields.priority.name": "priority", "fields.updated": "updated", "fields.summary": "summary"}
ISSUE_RENAME = dict(JIRA_RENAME, **{"fields.description": "description", "fields.issuetype.name": "issuetype",
                                    "fields.resolution.name": "resolution", "fields.labels": "labels"})
ISSUE_RENAME_BACK = {v: k for k, v in ISSUE_RENAME.items()}
