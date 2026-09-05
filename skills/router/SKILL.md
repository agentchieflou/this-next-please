---
name: router
description: "Use at the start of every task after session-bootstrap, and whenever you are unsure which skill applies. Reads .agent/state.json and picks exactly ONE next skill. Does no work itself."
---
# Router

1. Use the `phase`, `active_ticket` and `open_questions` `session-bootstrap` handed you **if it invoked you in this same turn**. Otherwise read `.agent/state.json` — on every later task in the session you must, because a skill has run since and state changes.
2. If `open_questions` is non-empty → invoke `friction-log`. STOP.
3. Match the user's request to ONE row. First match wins.

| Request mentions | Invoke |
|---|---|
| a ticket key, "triage", "what's next", acceptance criteria | `jira-triage` |
| UAT, remediation, "compare Jira to Teradata" (status/assignee lists) | `uat-jira-vs-teradata` |
| sprint report, committed / completed points, changelog, field history, "when did … change" | `jira-changelog` |
| query, count, rows, table, SQL (Teradata) | `teradata-query` |
| Hive, Hadoop, Impala, Spark table | `hive-query` |
| Oracle | `oracle-query` |
| DPM run, hand back / handoff, orchestrator.db, selection manifest, text_analysis, job manifest, OCR routing, native text | `dpm-consumer-integration` |
| Power BI, PBIP, report, visual, model, DAX, measure, TMDL | `pbi-router` |
| sbatch, cluster job, schedule | `slurm-submit` |
| map the codebase, how does this repo work, what calls what, unfamiliar code | `codebase-map` |
| write tests for, cover, characterization test, no tests for | `test-cover` |
| did I break anything, is it faster, before and after, regression | `test-regress` |
| slow, make it faster, performance, optimize, hot path, N+1 | `perf-optimize` |
| PR, branch, push, commit | `bitbucket-pr` |
| Confluence, document, write-up, page | `confluence-publish` |
| move / transition / close / reopen a ticket, "mark it done", "put it in review" | `jira-transition` |
| progress saved?, "where was I" | `state-update` |

4. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
5. No match after reading the table twice → invoke `friction-log` with type `ambiguity`. STOP.

When this table outgrows itself — about 24 rows, checked by `tests/test_skills.py` — **split it, do not shorten the rows.** Add a domain sub-router and give this table one row pointing at it, the way `pbi-router` already holds the seven report skills behind a single Power BI row. The rows here are already terse; squeezing them further trades a legible table for a cryptic one while the growth continues, and first-match-wins turns a near-miss into the wrong skill.
