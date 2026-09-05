---
name: router
description: "Use at the start of every task after session-bootstrap, and whenever you are unsure which skill applies. Reads .agent/state.json and picks exactly ONE next skill. Does no work itself."
---
# Router

1. Read `.agent/state.json`. Note `phase`, `active_ticket`, `open_questions`.
2. If `open_questions` is non-empty → invoke `friction-log`. STOP.
3. Match the user's request to ONE row. First match wins.

| Request mentions | Invoke |
|---|---|
| a ticket key, "triage", "what's next", acceptance criteria | `jira-triage` |
| UAT, remediation, "compare Jira to Teradata / Hadoop / Hive / Impala" (status/assignee lists) | `uat-jira-vs-source` |
| UAT across **two** warehouses at once, migration or cutover parity ("do Teradata and Hadoop agree") | `uat-jira-vs-warehouses` |
| sprint report, committed / completed points, changelog, field history, "when did … change" | `jira-changelog` |
| query, count, rows, table, SQL (Teradata) | `teradata-query` |
| Hive, Hadoop, Impala, Spark table | `hive-query` |
| Oracle | `oracle-query` |
| DPM run, hand back / handoff, orchestrator.db, selection manifest, text_analysis, job manifest, OCR routing, native text | `dpm-consumer-integration` |
| extract named fields from DPM documents ("pull the borrower and amount out of these"), per-job field list | `dpm-field-extraction` |
| Content Understanding, Foundry analyzer, "use the AI model to read these documents", field extraction that label matching could not do | `content-understanding-extract` |
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
