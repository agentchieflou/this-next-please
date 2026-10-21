---
name: jira-triage
description: "Use when given a Jira ticket key, asked \"what's next\", or asked to plan work. Reads the ticket with toil (saved, then read with ad-view), extracts acceptance criteria, sets the plan and branch name. Use before any query, code, or PR work on a ticket."
---
# Jira triage

1. Run `toil jira issue get <KEY> > .agent/out/<KEY>.json`, then `ad-view .agent/out/<KEY>.json --fields key,status,assignee,priority,updated,summary,description`. `ok: false` with `NOT_FOUND` → the key is wrong: say so and STOP. Any other `ok: false`, or toil exits non-zero → run `ad-doctor --only toil`, print its hint, `friction-log` type `tool-error`, STOP (never edit credentials, connections or PATH yourself).
2. The `description` column carries the acceptance criteria.
3. Extract acceptance criteria into ≤ 6 numbered lines. Each must be testable (has a number, date window, or exact field).
4. Any criterion untestable: run `toil jira issue comments <KEY> > .agent/out/<KEY>-comments.json`, then `ad-view .agent/out/<KEY>-comments.json` first — a human has usually already answered
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
