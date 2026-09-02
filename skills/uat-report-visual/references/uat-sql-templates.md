# Teradata SQL templates for Jira-history UAT

Assumed columns of `jira_hist_table`: `PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS, STORY_POINTS, SPRINT_ID` (adapt names once;
`ad-uat plan` writes these into `.agent/sql/<KEY>-uat-*.sql`). Teradata rules apply (`teradata-query/references/teradata-sql.md`):
`QUALIFY`, no `LIMIT`, `TIMESTAMP '...'` literals, `CAST(... AS DECIMAL)` before dividing.

## State as of an instant (one row per issue)
```sql
SELECT h.ISSUE_KEY AS "key", h.STATUS AS status, h.STORY_POINTS AS points, h.SPRINT_ID AS sprint_id
FROM   DB.JIRA_ISSUE_HISTORY h
WHERE  h.PROJECT_KEY = 'RDSD'
  AND  h.CHANGED_TS <= TIMESTAMP '2026-08-18 09:00:00'
QUALIFY ROW_NUMBER() OVER (PARTITION BY h.ISSUE_KEY ORDER BY h.CHANGED_TS DESC) = 1;
```

## Coverage per key (feeds `ad-uat reconcile --hist-coverage`)
```sql
SELECT h.ISSUE_KEY AS "key", MIN(h.CHANGED_TS) AS first_ts, MAX(h.CHANGED_TS) AS last_ts, COUNT(*) AS n_rows,
       SUM(CASE WHEN h.STORY_POINTS IS NULL THEN 1 ELSE 0 END) AS points_null
FROM   DB.JIRA_ISSUE_HISTORY h
WHERE  h.PROJECT_KEY = 'RDSD' AND h.CHANGED_TS <= TIMESTAMP '2026-08-18 09:00:00'
GROUP BY h.ISSUE_KEY;
```

## Committed vs completed points per sprint from history (compare with `ad-jira sprint-replay`)
```sql
WITH at_start AS (
  SELECT h.ISSUE_KEY, h.STORY_POINTS AS pts, h.SPRINT_ID
  FROM   DB.JIRA_ISSUE_HISTORY h
  WHERE  h.PROJECT_KEY = 'RDSD' AND h.CHANGED_TS <= TIMESTAMP '2026-08-04 09:00:00'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY h.ISSUE_KEY ORDER BY h.CHANGED_TS DESC) = 1
), at_close AS (
  SELECT h.ISSUE_KEY, h.STORY_POINTS AS pts, h.SPRINT_ID, h.STATUS
  FROM   DB.JIRA_ISSUE_HISTORY h
  WHERE  h.PROJECT_KEY = 'RDSD' AND h.CHANGED_TS <= TIMESTAMP '2026-08-18 11:00:00'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY h.ISSUE_KEY ORDER BY h.CHANGED_TS DESC) = 1
)
SELECT 41 AS sprint_id,
       ZEROIFNULL(SUM(CASE WHEN s.SPRINT_ID = 41 THEN s.pts END))                                   AS committed_points,
       ZEROIFNULL(SUM(CASE WHEN c.SPRINT_ID = 41 AND c.STATUS IN ('Done','Closed') THEN c.pts END)) AS completed_points
FROM   at_start s
FULL OUTER JOIN at_close c ON c.ISSUE_KEY = s.ISSUE_KEY;
```
Status names in the warehouse are strings: map them to the `done` category with `ad-jira statuses` before trusting `IN (...)`.
A `committed_points`/`completed_points` here that differs from `sprint-replay` while coverage shows missing rows is the `history-gap` class.

## Average without integer truncation
```sql
SELECT CAST(SUM(h.STORY_POINTS) AS DECIMAL(18,4)) / COUNT(DISTINCT h.ISSUE_KEY) AS avg_points FROM DB.JIRA_ISSUE_HISTORY h WHERE ...;
```
