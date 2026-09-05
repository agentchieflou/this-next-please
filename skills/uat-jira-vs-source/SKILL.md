---
name: uat-jira-vs-source
description: "Use for UAT/remediation of Jira-tracking dashboards — when numbers look wrong, when validating a fix, or when asked to compare live Jira against the Jira history held in a warehouse (Teradata, Hive/Hadoop, Impala, Oracle). One command generates the SQL, runs both sides and writes the findings."
---
# UAT: live Jira vs the Jira history in a warehouse

Prereq: `jira-triage` done; acceptance criteria include an explicit **date window** and **JQL scope**. Missing either → `friction-log`. STOP. Sprint or story-point questions → run `jira-changelog` first (its `sprint-replay` rows are the live side).

The SQL is **generated per engine**, not written by hand: Teradata and Oracle get `QUALIFY`, Hive and Impala get the windowed subquery, and the `key` alias is quoted the way each engine quotes identifiers. Every generated query is linted by `ad-sql-check` before it is sent.

1. Which engine holds the history? The user's words usually say ("Teradata", "Hadoop/Hive", "Impala"). If they do not, ask — do not guess, the two warehouses rarely hold the same rows.
2. First pass, no query spent:

```
ad-uat jira-vs-source --source <teradata|hive|impala|oracle> --ticket <KEY> --jql "<scope>" --window <start>,<end> --plan-only
```

   Read the generated `.agent/sql/<KEY>-uat.sql`. The column names come from `AGENTS.md` facts (`jira_hist_table`, and `jira_hist_key_column` / `_ts_column` / `_project_column`, each with a `_<engine>` override). Wrong names → fix the **facts**, not the file; a hand-edited file is regenerated on the next run.
3. Run it for real: the same command without `--plan-only`. It pulls live Jira, runs the history query, diffs on `key`, and writes `.agent/out/<KEY>-uat-findings.md`.
4. Read `meta`. A `warning` about truncation or a size gap > 2% → narrow the window and run once more; every class below is meaningless while one side is cut short.
5. The three classes are unchanged: `only_live` = missing from the warehouse; `only_history` = stale in it; `changed` = load lag or a mapping bug.
6. `changed` > 0 → open the findings file's examples, fetch those keys on both sides, and decide: lag (timestamps inside the load window) or bug.
7. Invoke `state-update`: `phase=documenting`, artifacts. Hand off → `confluence-publish`.
8. Never edit Jira or the warehouse. The generated SQL is read-only and `ad-sql-check` enforces it — never bypass it with a hand-written query.
9. Never restate rows in chat; cite the `findings` path.
