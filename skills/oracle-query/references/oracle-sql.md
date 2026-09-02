# Oracle SQL (19c / 21c) — write it right the first time

Tags: **(verified)** = Oracle docs / sqlglot Oracle generator; **(verify on your instance)** where version matters.

## Row limiting
- 12c+: `SELECT ... ORDER BY d DESC FETCH FIRST 10 ROWS ONLY;` and `OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY`. (verified)
- Legacy `ROWNUM`: assigned **before** `ORDER BY` runs. `WHERE ROWNUM <= 10 ORDER BY d` returns 10 arbitrary rows then sorts them — wrong rows, no error. Correct legacy form: `SELECT * FROM (SELECT * FROM t ORDER BY d DESC) WHERE ROWNUM <= 10`. (verified)
- No `LIMIT` (ORA-00933), no `TOP`, no `SAMPLE n` in that form (`SAMPLE(10)` percent exists).

## QUALIFY
Not available in 19c/21c (it arrived only in 26ai). Use a subquery: `SELECT * FROM (SELECT t.*, ROW_NUMBER() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM t) WHERE rn = 1`. (verified)

## Dates
- Now: `SYSDATE` (DATE with time), `SYSTIMESTAMP`, `CURRENT_DATE`, `TRUNC(SYSDATE)` = today at midnight. No parentheses on `CURRENT_DATE`.
- Literals: `DATE '2025-01-31'`, `TIMESTAMP '2025-01-31 10:00:00'`, `TO_DATE('2025-01-31', 'YYYY-MM-DD')`. **Never compare a DATE column to a bare string** — implicit conversion depends on NLS settings (ORA-01861). (verified)
- Arithmetic: `d + 7` adds days; `d1 - d2` is a **NUMBER of days that can be fractional** (`3.5`); `ADD_MONTHS(d, n)`; `MONTHS_BETWEEN(a, b)`; `TRUNC(d, 'MM')` first of month; `TRUNC(d)` strips time.
- Format: `TO_CHAR(d, 'YYYY-MM-DD HH24:MI:SS')` — `MI` is minutes, `MM` is months. `EXTRACT(YEAR FROM d)`.
- Hive functions (`date_add`, `datediff`, `date_format`) do not exist.

## NULLs
- `NVL(a, b)`, `NVL2(a, if_not_null, if_null)`, `COALESCE`, `NULLIF`, `DECODE(x, v1, r1, default)`. No `IFNULL`/`ISNULL`/`ZEROIFNULL`.
- **`''` is NULL** in VARCHAR2: `WHERE col = ''` never matches; use `IS NULL`. Porting from Teradata/Hive changes row counts here. (verified)

## Strings
- Concatenate with `||` (or 2-argument `CONCAT`). `SUBSTR(s, 1, 3)`, `INSTR(s, 'x')` (1-based, 0 when absent), `TRIM`, `REPLACE`, `REGEXP_SUBSTR`, `REGEXP_REPLACE`, `REGEXP_LIKE(s, pattern)`.
- Comparisons are case-sensitive by default. `LIKE` is case-sensitive; use `UPPER()` on both sides.

## Types and division
- `VARCHAR2(n)` (not `VARCHAR`/`STRING` in DDL/casts), `NUMBER(p,s)`, `DATE` (always has a time part), `TIMESTAMP`.
- `NUMBER / NUMBER` is exact (no integer truncation). Integer result: `TRUNC(a / b)` or `FLOOR`.
- Modulo: `MOD(a, b)`.

## Identifiers
- Unquoted identifiers are **folded to UPPERCASE**; `"quoted"` identifiers are case-sensitive forever. Never quote unless you must. (verified)
- Table aliases take **no `AS`**: `FROM jira_hist h` — `FROM jira_hist AS h` is ORA-00933. Column aliases may use `AS`. (verified)
- Backticks are a syntax error.

## Aggregation
- `LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)`; `MEDIAN`, `PERCENTILE_CONT`; window functions supported.
- `GROUP BY 1` is **not** an ordinal — it groups by the literal 1 and raises ORA-00979 for the other columns. Repeat the expressions. (verified)
- Set ops: `UNION [ALL]`, `INTERSECT`, `MINUS` (`EXCEPT` only 21c+, verify).

## Joins
- ANSI joins. Legacy `(+)` outer-join operator exists in old code — read it, never write it.
- CTEs `WITH x AS (...)`; recursive `WITH` supported. Temp tables need DDL (rejected by the adapter) — use CTEs.

## Scalar select
`SELECT 1 FROM DUAL;` — a FROM-less `SELECT` is a syntax error in 19c/21c. (verified)

## Metadata
`ALL_TABLES`, `ALL_TAB_COLUMNS` (`WHERE OWNER = 'SCHEMA' AND TABLE_NAME = 'T'`), `USER_TABLES`, `ALL_VIEWS`. Names are stored upper-case.

## Gotchas
1. `LIMIT n` / `TOP n` → ORA-00933; use `FETCH FIRST n ROWS ONLY`.
2. `FROM t AS x` → ORA-00933; drop `AS` on table aliases.
3. `ROWNUM` with `ORDER BY` in one block → silently wrong rows.
4. `WHERE col = ''` matches nothing (`''` is NULL).
5. String vs DATE compare → ORA-01861; use `TO_DATE`/`DATE '...'`.
6. `GROUP BY 1` → ORA-00979.
7. ORA-00904 invalid identifier: quoted-name case mismatch, or a SELECT alias used in WHERE.
8. ORA-01722 invalid number: implicit string→number on one bad row.
9. `d1 - d2` is fractional; wrap in `TRUNC()` for whole days.
10. Missing `FROM DUAL` on a scalar select.
