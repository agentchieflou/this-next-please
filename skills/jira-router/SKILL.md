---
name: jira-router
description: "Domain sub-router for Jira work: triage a key, create a ticket, field history and sprint replay, move an issue. Does no work itself."
---
# Jira router

1. Match the request to ONE row. First match wins. A ticket key with nothing else said is a triage.

| Request mentions | Invoke |
|---|---|
| a ticket key, "triage", "what's next", acceptance criteria, plan the work on a ticket | `jira-triage` |
| "new ticket", "open a ticket", "file this as a Jira", "create a story / task" (no key named) | `jira-create` |
| sprint report, committed / completed points, changelog, field history, "when did … change", "who moved it", sprint replay | `jira-changelog` |
| move / transition / close / reopen a ticket, "mark it done", "put it in review", "start progress" | `jira-transition` |
| a UAT of numbers on a sprint chart or dashboard (a Power BI visual is named) | `uat-report-visual` |
| comment on a ticket, reply to the reporter, "add a note to", post the findings on the ticket | `jira-comment` |
| "what did people say on", read the thread, the reporter's answer | `jira-triage` |

2. Preconditions, each a command and never a judgement: `ad-doctor` row `pncli / jira auth` is not `fail`; failing → print its hint, `friction-log` type `tool-error`, STOP. A transition or a new ticket runs with `--dry-run` first (AGENTS.md rule 8) -- the leaf skill does that; never skip it here.
3. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
4. No match after reading the table twice → invoke `research-spike`. STOP.
