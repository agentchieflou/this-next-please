# Teradata SQL (Vantage 20.0) — write it right the first time

Tags: **(verified)** = confirmed from Teradata docs or the sqlglot Teradata dialect; **(verify on your instance)** =
depends on version/settings — `ad-setup --only sources` probes these and `ad-sql-check` uses the results
(`capabilities`: `tmode`, `trunc_date`, `to_char`, `listagg`).

## Row limiting
- No `LIMIT`, no `FETCH FIRST`, no `OFFSET`. Error 3706 "Syntax error" is what `LIMIT` produces. (verified)
- `SELECT TOP 100 ...` returns the first n rows (add `ORDER BY` for determinism). `TOP n PERCENT` exists.
- `SELECT ... FROM t SAMPLE 100` returns a random sample — use while exploring.
- Top-n per group / deterministic paging: `QUALIFY ROW_NUMBER() OVER (PARTITION BY k ORDER BY ts DESC) = 1`.
- **`TOP` cannot be combined with `QUALIFY`** in the same query; pick one. `TOP` also cannot be combined with `DISTINCT` + `WITH TIES` combos — keep it simple. (verified / verify)
```sql
SELECT ISSUE_KEY, STATUS, CHANGED_TS
FROM   DB.JIRA_ISSUE_HISTORY
WHERE  PROJECT_KEY = 'RDSD'
QUALIFY ROW_NUMBER() OVER (PARTITION BY ISSUE_KEY ORDER BY CHANGED_TS DESC) = 1;
```

## QUALIFY
Supported (verified). It filters on window-function results after `WHERE`/`GROUP BY`/`HAVING`. Equivalent portable
form is a subquery with `ROW_NUMBER()` — use that when the same SQL must also run on Impala/Oracle.

## Dates
- Now: `CURRENT_DATE`, `CURRENT_TIMESTAMP`, `DATE`, `TIME` — **no parentheses**. (verified)
- Literal: `DATE '2025-01-31'`, `TIMESTAMP '2025-01-31 10:00:00'`.
- Arithmetic: `d + 7` adds days; `d1 - d2` is an **INTEGER** number of days (Oracle gives a fraction); `ADD_MONTHS(d, n)`.
- Parts: `EXTRACT(YEAR FROM d)`, `EXTRACT(MONTH FROM d)`.
- Format/parse the portable way: `CAST(CAST(d AS FORMAT 'YYYY-MM-DD') AS VARCHAR(10))`, `CAST(s AS DATE FORMAT 'YYYY-MM-DD')`. (verified)
- Format letters: `YYYY` year, `MM` month, `DD` day, `HH` hour, **`MI` minute** (not `mm`), `SS` second, `MMM` month abbreviation. (verified)
- `TRUNC(d, 'MM')` and `TO_CHAR(d, 'YYYY-MM-DD')` exist on 16.x+ **(verify on your instance)** — the linter blocks them when the probe says they are missing and offers the CAST/FORMAT form.
- Never use Hive functions here: `date_add`, `datediff`, `date_format`, `from_unixtime` do not exist.
- Month bucket without TRUNC: `CAST(CAST(d AS FORMAT 'YYYY-MM') AS VARCHAR(7))` or `EXTRACT(YEAR FROM d) * 100 + EXTRACT(MONTH FROM d)`.
- Compare timestamps to timestamps: `CHANGED_TS <= TIMESTAMP '2025-01-31 23:59:59'`; comparing a TIMESTAMP column to a DATE literal needs `CAST(CHANGED_TS AS DATE)`.

## NULLs
- `COALESCE(a, b)`, `NULLIF(a, b)`, `ZEROIFNULL(x)`, `NULLIFZERO(x)`; `NVL` exists on 16.x+ (verify). `IFNULL`/`ISNULL` do not exist.
- `''` and `NULL` are **different** (unlike Oracle): `WHERE col = ''` can match. (verified)
- `COUNT(col)` ignores NULLs; `SUM` of an all-NULL set is NULL, not 0 → `ZEROIFNULL(SUM(x))`.

## Strings
- Concatenate with `||`. `SUBSTR(s, 1, 3)`, `INDEX(s, 'x')` or `POSITION('x' IN s)` (1-based, 0 when absent), `TRIM(s)`, `OREPLACE(s, 'a', 'b')` (not `REPLACE`), `REGEXP_SUBSTR`, `REGEXP_REPLACE`, `UPPER`/`LOWER`.
- **Case sensitivity depends on the session mode** (verify on your instance): in Teradata mode (`tmode=TERA`) comparisons are NOT CASESPECIFIC — `'Done' = 'done'` is TRUE; in ANSI mode they are case-sensitive. Force it: `WHERE (STATUS (CASESPECIFIC)) = 'Done'` or `UPPER(STATUS) = 'DONE'`. `ad-setup` records `tmode`; the linter warns on `=` against literals in TERA mode.
- `LIKE '%x%'` — `%` inside a literal is fine; `%` as a **modulo operator does not exist**, use `MOD(a, b)`. (verified)

## Types and division
- Text type is `VARCHAR(n)` (also `CHAR`, `CLOB`); no `STRING`. Numbers: `INTEGER`, `BIGINT`, `DECIMAL(18,2)`, `FLOAT`.
- **Integer / integer truncates**: `5/2 = 2`. `SUM(points)/COUNT(*)` is a truncated average. Write `CAST(SUM(points) AS DECIMAL(18,4)) / COUNT(*)`. (verified)
- `SUM` over an `INTEGER` column stays INTEGER and can overflow (error 2616) → `SUM(CAST(x AS BIGINT))`.
- Casts: `CAST(x AS VARCHAR(20))`, `CAST(x AS DECIMAL(18,2))`, `CAST(x AS DATE FORMAT 'YYYY-MM-DD')`.

## Identifiers
- Quote with double quotes `"My Col"`; names are case-insensitive. Backticks are a syntax error.
- Fully qualify: `DB.TABLE`. Abbreviations `SEL`, `DEL`, `INS`, `UPD` exist — never emit them.

## Aggregation
- Window functions and `ROWS BETWEEN` supported. Every non-aggregated SELECT column must be in `GROUP BY` (error 3504). Avoid `GROUP BY 1` ordinals.
- String aggregation: **no `LISTAGG`** (verify on your instance; the probe records it) — use
  `TRIM(TRAILING ',' FROM (XMLAGG(TRIM(col) || ',' ORDER BY col) (VARCHAR(4000))))`.
- `MEDIAN`, `PERCENTILE_CONT` exist; `COUNT(DISTINCT x)` fine.

## Joins
- ANSI joins. Read-only dirty reads: prefix `LOCKING ROW FOR ACCESS SELECT ...` when the table is being loaded (verified as a statement prefix).
- Set ops: `UNION [ALL]`, `INTERSECT`, `MINUS`/`EXCEPT`.
- CTEs: `WITH x AS (...) SELECT ...` (the WITH clause must precede the SELECT); `WITH RECURSIVE` exists.
- Temp objects need DDL, which the adapter rejects — use a CTE instead of `CREATE VOLATILE TABLE`.

## Scalar select
`SELECT 1` works with no FROM. Do not write `FROM DUAL`.

## Metadata
`DBC.TablesV`, `DBC.ColumnsV` (`WHERE DatabaseName = 'DB' AND TableName = 'T'`), `HELP TABLE DB.T;`, `SHOW TABLE DB.T;`
(verify HELP/SHOW pass the adapter's read-only filter: they do, as they start with HELP/SHOW → currently only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN pass; use `DBC.ColumnsV`).

## Gotchas
1. `LIMIT` → 3706. Use `TOP`/`SAMPLE`/`QUALIFY`.
2. `TOP` + `QUALIFY` together → syntax error; use `QUALIFY` alone.
3. Integer division truncates silently; averages come out as integers.
4. 2616 numeric overflow on `SUM(int)` → cast to BIGINT.
5. 3504 non-aggregate not in GROUP BY.
6. `%` is not modulo.
7. `=` on strings may be case-insensitive (session mode) — silently different row counts.
8. `''` is not NULL (Oracle habits break here).
9. No `/*+ hints */`.
10. `CURRENT_DATE()` with parentheses is a syntax error.
