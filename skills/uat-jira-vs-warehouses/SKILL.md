---
name: uat-jira-vs-warehouses
description: "Use when a UAT or migration question involves TWO warehouses at once — comparing live Jira against both Teradata and Hadoop/Hive/Impala history, and asking whether the two platforms agree with each other. For a single warehouse use uat-jira-vs-source."
---
# UAT: live Jira vs two warehouse histories

Use this when the question is **parity between platforms** — a migration, a dual-write, a cutover — not just "does the warehouse match Jira". One warehouse → `uat-jira-vs-source`.

Prereq: `jira-triage` done; acceptance criteria include an explicit **date window** and **JQL scope**. Missing either → `friction-log`. STOP.

1. Which two engines? The ticket usually names them ("Teradata and Hadoop"). If it names one, this is the wrong skill.
2. First pass, no query spent:

```
ad-uat jira-vs-warehouses --sources teradata,hive --ticket <KEY> --jql "<scope>" --window <start>,<end> --plan-only
```

   Two files are written, one per engine, because the two warehouses rarely use the same column names. Check both. Wrong names → fix the `AGENTS.md` facts (`jira_hist_table`, plus a `_<engine>` override where they differ), not the files.
3. Run it: the same command without `--plan-only`.
4. Read `## Do <a> and <b> agree?` first — it is the question that was asked, and it is at the top of the findings file for that reason.
   - **They disagree** → `warehouse-drift`. That is a *migration* defect: whatever either platform says about Jira, they do not say the same thing as each other. Raise it against the platform that disagrees with Jira; if both do, the load is common to them and Jira is still the truth.
   - **They agree but both differ from Jira** → not a migration problem. The classes underneath (`lag`, `mapping-bug`, `history-gap`) name which.
5. A `warning` about truncation on either side → narrow the window and run once more. Every count is meaningless while a side is cut short.
6. Invoke `state-update`: `phase=documenting`, artifacts. Hand off → `confluence-publish`.
7. Never edit Jira or either warehouse. The generated SQL is read-only and `ad-sql-check` enforces it — never bypass it with a hand-written query.
8. Never restate rows in chat; cite the `findings` path.
