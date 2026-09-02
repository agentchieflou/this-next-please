---
name: jira-triage
description: "Use when given a Jira ticket key, asked \"what's next\", or asked to plan work. Reads the ticket via ad-pncli, extracts acceptance criteria, sets the plan and branch name. Use before any query, code, or PR work on a ticket."
---
# Jira triage

1. Run `ad-pncli jira search --jql "key = <KEY>" --fields key,status,assignee,priority,updated,summary`.
2. Run `ad-pncli raw jira <get-issue verb> <KEY>` for description + acceptance criteria. Pinned verb: `TODO(HANDOFF: pin after pncli jira --help)`. If unpinned, run `pncli jira --help` once, use the listed verb. Do not guess twice.
3. Extract acceptance criteria into ≤ 6 numbered lines. Each must be testable (has a number, date window, or exact field).
4. Any criterion untestable → `friction-log` type `ambiguity`, quote the line. STOP.
5. Decide type: `data-fix | model-change | report | investigation`. Branch: `feature/<KEY>-<slug≤4 words>`.
6. Invoke `state-update`: `active_ticket=<KEY>`, `branch`, `phase=triaged`.
7. Print the ≤6 lines + branch. Hand off: investigation/UAT → `uat-jira-vs-teradata`; model-change → `pbi-deploy-te2` after edits; otherwise → `router`.
