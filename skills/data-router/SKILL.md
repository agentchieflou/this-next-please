---
name: data-router
description: "Domain sub-router for warehouse reads and UAT: Teradata, Hive, Impala, Oracle queries, Jira-vs-warehouse reconciliation, dataset diffs. Does no work itself."
---
# Data router

1. Match the request to ONE row. First match wins. Reconciliation rows come before plain query rows on purpose: "compare Jira to Teradata" names a warehouse, and a query skill would answer the wrong question.

| Request mentions | Invoke |
|---|---|
| UAT across **two** warehouses at once, migration or cutover parity ("do Teradata and Hadoop agree") | `uat-jira-vs-warehouses` |
| UAT, remediation, "compare Jira to Teradata / Hadoop / Hive / Impala / Oracle" (status / assignee lists, counts that look wrong) | `uat-jira-vs-source` |
| query, count, rows, table, SQL, Teradata, "Jira history" | `teradata-query` |
| Hive, Hadoop, Impala, Spark table | `hive-query` |
| Oracle | `oracle-query` |
| compare two datasets, diff two extracts, "did the numbers change between runs", two TOON or TSV files | `data-adapter` |
| a query that exceeds the laptop (hours, hundreds of millions of rows), "run it on the cluster" | `slurm-submit` |

2. Preconditions, each a command: the engine's `ad-doctor` row is not `fail` (`sources/teradata`, `sources/hive`, `sources/impala`, `sources/oracle`); failing → print its hint, `friction-log` type `tool-error`, STOP. The engine is unnamed and more than one is configured → `ad-state ask "Which warehouse holds this — <the configured ones>?" --want value`, `friction-log` type `missing-info`, STOP. Exactly one configured → say so in one line and continue.
3. Read-only only (AGENTS.md rule 7). A request to write, load, create or drop anything in a warehouse is not routed: say so in one line, `friction-log` type `contract`, STOP.
4. Output one line: `→ <skill>: <reason in ≤ 12 words>`. Then invoke it.
5. No match after reading the table twice → invoke `research-spike`. STOP.
