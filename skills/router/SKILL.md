---
name: router
description: Use at the start of every task after session-bootstrap, and whenever you are unsure which skill applies. Reads .agent/state.json and picks exactly ONE next skill. Does no work itself.
---
# Router

1. Read `.agent/state.json`. Note `phase`, `active_ticket`, `open_questions`.
2. If `open_questions` is non-empty → invoke `friction-log`. STOP.
3. Match the user's request to ONE row. First match wins.

| Request mentions | Invoke |
|---|---|
| a ticket key, "triage", "what's next", acceptance criteria | `jira-triage` |
| numbers on a chart/visual are wrong, expected values in a document or CSV, UAT of a report | `uat-report-visual` |
| UAT, remediation, "compare Jira to Teradata" (status/assignee lists) | `uat-jira-vs-teradata` |
| sprint report, committed / completed points, changelog, field history, "when did … change" | `jira-changelog` |
| query, count, rows, table, SQL (Teradata) | `teradata-query` |
| Hive, Hadoop, Impala, Spark table | `hive-query` |
| Oracle | `oracle-query` |
| PBIP, report, visual, page, "what feeds this chart", model overview | `pbip-projection` |
| add / fix a measure, column, format string, relationship, TMDL edit | `tmdl-edit` |
| validate the report, broken visual, "does the report still work", before deploy | `pbi-validate` |
| deploy model, publish, XMLA, workspace | `pbi-deploy-te2` |
| refresh model / dataset | `pbi-refresh-xmla` |
| DAX result, vpax, export measures | `dax-studio-export` |
| sbatch, cluster job, schedule | `slurm-submit` |
| PR, branch, push, commit | `bitbucket-pr` |
| Confluence, document, write-up, page | `confluence-publish` |
| progress saved?, "where was I" | `state-update` |

4. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
5. No match after reading the table twice → invoke `friction-log` with type `ambiguity`. STOP.
