---
name: jira-create
description: "Use when the user asks for a new ticket — \"open a ticket\", \"file this\", \"create a Jira for it\" — or when the router decides this request needs one and none exists. Writes the ticket with the project's own defaults (issue type, components, primary domain, labels, parent) through ad-jira create, records it as active_ticket, then continues the work."
---
# Create a Jira ticket (then keep going)

The shape of a right ticket is the project's, not yours: `AGENTS.md` facts `jira_project`, `jira_issue_type`, `jira_components`, `jira_labels`, `jira_fields` (`Primary Domain=Data; Team=BI`), `jira_parent`, `jira_assignee`. `ad-jira create` reads them and resolves every field name against Jira. Never hand-write a field id or guess a component name.

1. From the user's words write the **summary** — one line, ≤ 80 characters: what, and why — and a **description** of ≤ 6 lines: the ask, the acceptance criteria you can test (a number, a date window, an exact field), the files or objects it touches. Write the description to `.agent/out/new-ticket.md`. `jira_project` empty in `AGENTS.md` and no key given → `ad-state ask "Which Jira project?" --want value`, then `friction-log` type `missing-info`. STOP.
2. Dry run — it resolves everything and sends nothing:

```
ad-jira create --summary "<summary>" --description-file .agent/out/new-ticket.md --dry-run
```

   Add `--type`, `--component`, `--label`, `--field "Name=value"`, `--parent`, `--assignee` only when the user named one; otherwise the facts fill them. Read the `resolved` rows: every field name became an id and a typed value.
   `ok: false` naming a field → the `available` rows are the real names: fix the fact or the flag, re-run once. Still refused → `friction-log` type `tool-error`. STOP.
3. Re-run without `--dry-run`. Read `key` and `url`.
   `refused: approval_timeout` or `approval_denied` → an operator gate, not a bug: `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
4. `state-update`: `active_ticket=<KEY>`, `branch=feature/<KEY>-<slug≤4 words>`, `phase=triaged`. Print one line: `<KEY> · <url>`.
5. Hand off → `router` with the user's original request. You wrote the acceptance criteria, so `jira-triage` has nothing to add; the next skill is the one the request names.
