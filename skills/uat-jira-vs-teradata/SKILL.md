---
name: uat-jira-vs-teradata
description: Use for UAT/remediation of Jira-tracking dashboards — when numbers look wrong, when validating a fix, or when asked to compare live Jira against the Jira history in Teradata. Pulls both sides through ad-* and diffs on disk.
---
# UAT: live Jira vs Teradata history

Prereq: `jira-triage` done; acceptance criteria include an explicit **date window** and **JQL scope**. Missing either → `friction-log`. STOP.

1. Live side: `ad-pncli jira search --jql "<scope JQL> AND updated >= '<start>' AND updated <= '<end>'" --fields key,status,assignee,updated --max-results 2000`. Note `path` → LEFT.
2. History side: write `.agent/sql/<ticket>-uat.sql` selecting the same grain (one row per issue key, latest status ≤ `<end>`). Run `ad-td --env <env> --sql-file … --name hist`. Note `path` → RIGHT.
3. Row counts differ by > 2% → check `truncated: true` on either side. If truncated, narrow the window and repeat once.
4. `ad-diff <LEFT> <RIGHT> --key key --cols status,assignee`.
5. Read `meta` counts. Classify: `only_left` = missing from warehouse; `only_right` = stale in warehouse; `changed` = lag or mapping bug.
6. `changed` > 0 → pick 3 keys, fetch each side for those 3 keys only. Decide: lag (timestamps within load window) vs bug.
7. Write findings to `.agent/out/<ticket>-uat-findings.md`: counts, classification, 3 examples, recommendation (≤ 25 lines).
8. Invoke `state-update`: `phase=documenting`, artifacts. Hand off → `confluence-publish`.
9. Never edit Jira or Teradata. Never restate rows in chat; cite `path`.
