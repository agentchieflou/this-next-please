---
name: jira-triage
description: "Use when given a Jira ticket key, asked \"what's next\", or asked to plan work. Reads the ticket via ad-pncli, extracts acceptance criteria, sets the plan and branch name. Use before any query, code, or PR work on a ticket."
---
# Jira triage

1. Run `ad-pncli jira search --jql "key = <KEY>" --fields key,status,assignee,priority,updated,summary`. `refused: not_found` → `ad-pncli where`, print its `hint` and `tried` rows, `friction-log` type `tool-error`, STOP (never install pncli or edit PATH yourself).
2. Run `ad-pncli jira get <KEY>` for description + acceptance criteria (`--fields key,status,summary,description` narrows it). It issues pncli's confirmed read verb `jira get-issue --key <KEY>`: never assemble that command by hand.
3. Extract acceptance criteria into ≤ 6 numbered lines. Each must be testable (has a number, date window, or exact field).
4. Any criterion untestable → `friction-log` type `ambiguity`, quote the line. STOP.
5. Decide type: `data-fix | model-change | report | investigation`. Branch: `feature/<KEY>-<slug≤4 words>`.
6. Invoke `state-update`: `active_ticket=<KEY>`, `branch`, `phase=triaged`.
7. Print the ≤6 lines + branch. Hand off: investigation/UAT → `uat-jira-vs-teradata`; model-change → `pbi-deploy-te2` after edits; otherwise → `router`.
