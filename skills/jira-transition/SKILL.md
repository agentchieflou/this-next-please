---
name: jira-transition
description: "Use to move a Jira issue to another status — in review, done, in progress, blocked. Use after opening a PR, after publishing to Confluence, or when the user says to move / close / reopen a ticket. Never guesses a status name."
---
# Move a Jira issue

A workflow belongs to the **issue type**, not the project: a Story may go `In Progress → In Review → Done`, while a Task in the same project has no review state at all. Never write a status name from memory — `ad-jira` asks Jira what *this* issue can do.

1. `state.active_ticket` (or a key given by the user) is required. Missing → `session-bootstrap`. STOP.
2. Dry run first — it resolves the target and prints the transition without moving anything:

```
ad-jira transition <KEY> --to review --dry-run
```

   `--to` takes an **intent** — `todo`, `in-progress`, `review`, `blocked`, `done` — or an exact transition or status name. Read `issue_type`, `transition`, `to` and `matched`.
3. `already: true` → the issue is already there. Nothing to do; go to step 8.
4. `ok: false`, error `no <intent> transition on this <type>` → this issue type's workflow has no such state. Read the `available` rows:
   - one of them is plainly the same thing under another name → re-run with `--to "<that exact name>" --pin`. `--pin` remembers it for this issue type (`jira.workflow.<type>.<intent>`), so the next ticket of that type resolves without asking.
   - none is → the step does not apply to this type. Say so in one line and continue the task. Do **not** substitute a different status.
5. `ok: false`, error `... is ambiguous` → the hint lists the candidates. Pick the one the user's words name, or ask. Never pick by position.
6. `ok: false`, error `has a screen requiring <fields>` → re-run with those fields, e.g. `--resolution Done` or `--field "Fix Version=2026.09"`. Values that look like JSON are sent as JSON.
7. Re-run without `--dry-run`, adding `--comment "<one line>"` when there is a URL to record (PR, Confluence page). `ok: false` with `still '<status>'` → a workflow post-function undid it: `friction-log` type `tool-error`. STOP.
   `refused: approval_timeout` or `approval_denied` → an operator gate, not a bug: `friction-log` type `missing-info` quoting the `approval` id and the `hint`. Do not retry.
8. `state-update`: `phase` matching the new status. Hand off → `router`.

`ad-jira transitions <KEY>` lists the whole picture — id, name, target status, category, and the screen fields each one demands — when a decision needs it.
