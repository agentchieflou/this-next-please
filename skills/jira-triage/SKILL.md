---
name: jira-triage
description: "Use when given a Jira ticket key, asked \"what's next\", or asked to plan work. Reads the ticket via ad-jira, extracts acceptance criteria, sets the plan and branch name. Use before any query, code, or PR work on a ticket."
---
# Jira triage

1. Run `ad-jira search --jql "key = <KEY>" --fields key,status,assignee,priority,updated,summary`. `ok: false` → print its `hint` (it names `ad-setup --only jira`), `friction-log` type `tool-error`, STOP (never edit credentials or PATH yourself).
2. Run `ad-jira get <KEY>` for description + acceptance criteria (`--fields key,status,summary,description` narrows it; the description is plain text, comments and attachments are counts).
3. Extract acceptance criteria into ≤ 6 numbered lines. Each must be testable (has a number, date window, or exact field).
4. Any criterion untestable: run `ad-jira comments <KEY>` first — a human has usually already answered
   there. Still untestable, and **two readings lead to different work** → `ad-state ask "<the question>"
   --choice "<reading A>" --choice "<reading B>"`, then `friction-log` type `ambiguity` quoting the line,
   STOP. **A safe, reversible default settles it** → `ad-state ask "<assumption>" --assume "<default>"`,
   print it in one line, CONTINUE (AGENTS.md rule 10).
5. If `.agent/in/<KEY>/scope.toon` exists, those files are **where to start**: read them first, and widen with
   `ad-graph refs <symbol>` rather than by browsing. Announce in one line before you edit anything outside it.
   The scope is advice, not a fence — going outside it is allowed and is reported, never refused.
6. Decide type: `data-fix | model-change | report | investigation`. Branch: `feature/<KEY>-<slug≤4 words>`.
7. Invoke `state-update`: `active_ticket=<KEY>`, `branch`, `phase=triaged`.
8. Print the ≤6 lines + branch. Hand off: investigation/UAT → `uat-jira-vs-source`; model-change → `pbip-projection` (which leads to `tmdl-edit` → `pbi-validate` → `pbi-deploy-te2`; never deploy without validating); otherwise → `router`.
