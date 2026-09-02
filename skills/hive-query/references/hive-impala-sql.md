# Hive (3 / 4) and Impala (4) SQL — write it right the first time

Both run on Hadoop, share the metastore, and look alike. They are **not** the same dialect. Tags: **(verified)** =
confirmed from the Hive grammar / Impala docs source; **(verify on your instance)** = version-dependent
(`ad-setup --only sources` records `capabilities.major` for Hive; `ad-sql-check` gates on it).

## The five differences that bite first (all verified)
1. **`||` is LOGICAL OR in Impala** (a BOOLEAN, or a type error). In Hive `||` concatenates. Use `concat(a, b)` on both.
2. **`QUALIFY`**: Hive 4 yes, Hive 3 no, Impala no. Portable: subquery with `row_number()`.
3. `LIMIT n` takes a **literal** number only (no expressions, no parameters) in Hive.
4. Hive `trunc(date, unit)` supports only `MONTH`/`MON`/`MM`, `QUARTER`/`Q`, `YEAR`/`YYYY`/`YY` — no day/week truncation.
5. Impala `TRUNC(ts, 'MM')` vs `DATE_TRUNC('MONTH', ts)`: **opposite argument order**.

## Row limiting
- `LIMIT n`; Hive also `LIMIT offset, n` and `LIMIT n OFFSET m`; Impala `LIMIT n OFFSET m` (use with `ORDER BY`). (verified)
- No `TOP`, no `FETCH FIRST`, no `SAMPLE n` (Hive: `TABLESAMPLE`), no `ROWNUM` (use `row_number() OVER (...)`).
```sql
SELECT * FROM (
  SELECT issue_key, status, changed_ts,
         row_number() OVER (PARTITION BY issue_key ORDER BY changed_ts DESC) AS rn
  FROM   db.jira_issue_history WHERE project_key = 'RDSD'
) x WHERE rn = 1 LIMIT 100;
```

## QUALIFY
Hive 4+: `... QUALIFY row_number() OVER (...) = 1` after `WHERE`/`GROUP BY`. Hive 3 and Impala: use the subquery above. (verified)

## Dates
- Hive: `current_date()`, `current_timestamp()` (constant for the query); `date_add(d, 7)`, `date_sub`, `datediff(d1, d2)` (INT days, negative if d1 < d2), `add_months(d, n)`, `months_between(a, b)`, `trunc(d, 'MM')`, `date_format(d, 'yyyy-MM-dd')`, `to_date(ts)` (**one argument**), `year(d)`, `month(d)`, `unix_timestamp(s, 'yyyy-MM-dd')`, `from_unixtime(n, 'yyyy-MM-dd')`. Pattern letters are **Java style and case-sensitive**: `MM` month, `mm` minute, `dd` day, `HH` hour. `date_format`'s accepted letters depend on `hive.datetime.formatter`. (verified)
- Impala: `now()`, `current_timestamp()`, `current_date()`; `days_add(ts, 7)`, `date_add(ts, 7)`, `ts + interval 7 days`, `datediff(a, b)`, `add_months`, `months_between` (DOUBLE); `trunc(ts, 'MM')`, `date_trunc('MONTH', ts)`, `extract(year from ts)`; `from_timestamp(ts, 'yyyy-MM-dd')` to format, `to_timestamp(s, 'yyyy-MM-dd')` to parse, `from_unixtime`, `unix_timestamp`. (verified)
- `to_date(s, 'fmt')` with two arguments does not exist in either → Hive `from_unixtime(unix_timestamp(s,'yyyy-MM-dd'))`, Impala `to_timestamp(s,'yyyy-MM-dd')`.
- No `SYSDATE`, no `TO_CHAR`, no `TO_DATE(s, fmt)`, no `ADD_MONTHS` capitalisation issues (functions are case-insensitive).
- String→timestamp implicit casts return NULL rather than erroring in Impala — cast explicitly (verify).

## NULLs
- `coalesce`, `nullif`, `if(cond, a, b)`. Hive `nvl` **is** `coalesce` (any arity — non-portable). Impala: `nvl(a, b)` (2 args), `nvl2`, `ifnull`, `isnull`, `zeroifnull`, `nullifzero`, `nonnullvalue`. (verified)
- `''` and `NULL` are distinct (unlike Oracle). Impala `concat()` returns NULL if any argument is NULL → `concat_ws` or `nvl`.

## Strings
- `concat(a, b, ...)`, `concat_ws(sep, ...)`, `substr(s, 1, 3)` (1-based), `length`, `upper`/`lower`, `trim`, `regexp_replace(s, pat, rep)`, Hive `regexp_extract(s, pat, idx)` / Impala `regexp_extract`, `regexp_like` (Impala), `rlike`/`regexp` operators.
- **`instr(str, substr)` vs `locate(substr, str)` take arguments in opposite orders**; both 1-based, 0 when absent. (verified)
- Comparisons are **case-sensitive**; Impala has `ilike` / `iregexp` for case-insensitive matches.
- Hive `translate`, `replace` (Hive 1.3+/2.1+), Impala `replace`.

## Types and division
- Text type is `STRING` (`VARCHAR(n)` exists but rarely useful). `CAST(x AS STRING)`, `CAST(x AS DECIMAL(18,2))`, `CAST(x AS BIGINT)`.
- `/` always returns DOUBLE (Impala verified; Hive same). Integer division: `a DIV b`. Modulo `%` (Impala: integer operands only) or `pmod`. (verified)
- Hive `COUNT(DISTINCT a, b)` is allowed; multiple distinct aggregates can force one reducer (slow).

## Identifiers
- Backticks `` `my col` ``; identifiers are case-insensitive and stored lower-case. **Double quotes are string literals** in Hive/Impala, not identifiers. (verified)
- Impala's reserved-word list grows every release — backtick anything that could be a keyword (`date`, `year`, `data`, `comment`), also inside qualified names: `` db.`data` ``. (verified)

## Aggregation
- Window functions on both. Hive string aggregation `concat_ws(',', collect_list(x))` (`collect_set` dedupes; order undefined). Impala `group_concat(x, ',')`. No `LISTAGG`. (verified)
- Percentiles: Hive `percentile`, `percentile_approx`; Impala `appx_median` (verify).
- Set ops: `UNION [ALL|DISTINCT]`, `INTERSECT`, `EXCEPT`/`MINUS` on Hive 3+/Impala. (verified)
- `GROUP BY` ordinals are config-dependent — repeat expressions.

## Joins
- ANSI joins; Hive `LEFT SEMI JOIN` acts like EXISTS. Impala restricts correlated subqueries (one per block, none in OR/SELECT list) — prefer `LEFT JOIN ... IS NULL` or a de-duplicated CTE. Hive `LATERAL VIEW explode(arr)` is Hive-only; Impala unnests with `FROM t, t.arr`.
- Partition pruning needs **literal** predicates on partition columns (`WHERE dt = '2025-01-31'`); functions or join-derived values on the partition column mean a full scan. (verify)
- CTEs `WITH x AS (...)` on both.

## Scalar select
`SELECT 1` works without FROM on both. Do not write `FROM DUAL`.

## Metadata
`SHOW TABLES [IN db]`, `DESCRIBE FORMATTED db.t`, `SHOW PARTITIONS db.t`, `SHOW CREATE TABLE db.t`. Impala only sees external writes after `REFRESH db.t` (data) or `INVALIDATE METADATA db.t` (schema/new tables) — those are not read-only statements, so ask the data owner. (verified)

## Gotchas
1. Impala `a || b` is OR — silent wrong answer on booleans, type error on strings.
2. `QUALIFY` on Hive 3 / Impala → parse error.
3. `LIMIT <expression>` in Hive → parse error.
4. Hive `trunc(d, 'DD')` → error; use `date_format`.
5. `MM` vs `mm` in patterns — month vs minute, silently wrong.
6. `TO_DATE(s, 'fmt')` does not exist.
7. `"quoted identifier"` is a string literal.
8. Hive n-ary `nvl` does not port to Impala/Oracle.
9. Impala `concat` with a NULL argument returns NULL.
10. Stale Impala metadata after Hive/Spark writes → ask for `REFRESH`.
11. `SYSDATE`, `ROWNUM`, `TO_CHAR`, `LISTAGG` are Oracle — none exist here.
