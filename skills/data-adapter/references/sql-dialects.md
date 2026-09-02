# SQL dialects side by side — Teradata 20 · Hive 3/4 · Impala 4 · Oracle 19c/21c

Per-dialect detail lives next to each query skill: `teradata-query/references/teradata-sql.md`,
`hive-query/references/hive-impala-sql.md`, `oracle-query/references/oracle-sql.md`. `ad-sql-check` enforces the
blocking rows below before any query runs; **V** = verified from grammar/docs, **?** = verify on your instance.

| Operation | Teradata 20 | Hive 3/4 | Impala 4 | Oracle 19c/21c |
|---|---|---|---|---|
| Limit rows | `SELECT TOP n` / `SAMPLE n` (V) | `LIMIT n` (V) | `LIMIT n` (V) | `FETCH FIRST n ROWS ONLY` (V) |
| Limit + offset | `QUALIFY ROW_NUMBER() ...` | `LIMIT n OFFSET m` (V) | `LIMIT n OFFSET m` + ORDER BY (V) | `OFFSET m ROWS FETCH NEXT n ROWS ONLY` (V) |
| QUALIFY | yes (V) | **3: no · 4: yes** (V) | **no** (V) | **no** (26ai only) (V) |
| Current date | `CURRENT_DATE` (no parens) | `current_date()` | `current_date()` / `now()` | `SYSDATE`, `TRUNC(SYSDATE)` |
| Date literal | `DATE '2025-01-31'` | `DATE '2025-01-31'` | `CAST('2025-01-31' AS DATE)` | `DATE '2025-01-31'` |
| Add days | `d + 7` | `date_add(d, 7)` | `days_add(d, 7)` / `d + interval 7 days` | `d + 7` |
| Add months | `ADD_MONTHS(d, n)` | `add_months(d, n)` | `add_months(d, n)` | `ADD_MONTHS(d, n)` |
| Day difference | `d1 - d2` → **INTEGER** | `datediff(d1, d2)` → INT | `datediff(d1, d2)` → INT | `d1 - d2` → **fractional NUMBER** |
| Truncate to month | `TRUNC(d,'MM')` (?) else `CAST(... AS FORMAT 'YYYY-MM')` | `trunc(d,'MM')` (V, MONTH/QUARTER/YEAR only) | `TRUNC(ts,'MM')` / `DATE_TRUNC('MONTH', ts)` (V) | `TRUNC(d,'MM')` |
| Format date | `CAST(CAST(d AS FORMAT 'YYYY-MM-DD') AS VARCHAR(10))` | `date_format(d,'yyyy-MM-dd')` | `from_timestamp(ts,'yyyy-MM-dd')` | `TO_CHAR(d,'YYYY-MM-DD')` |
| Parse date | `CAST(s AS DATE FORMAT 'YYYY-MM-DD')` | `from_unixtime(unix_timestamp(s,'yyyy-MM-dd'))` | `to_timestamp(s,'yyyy-MM-dd')` | `TO_DATE(s,'YYYY-MM-DD')` |
| Null default | `COALESCE`, `ZEROIFNULL` | `coalesce`, `nvl` (= coalesce, n-ary) | `nvl` (2 args), `ifnull`, `zeroifnull` | `NVL`, `NVL2`, `COALESCE`, `DECODE` |
| Empty string | `''` ≠ NULL | `''` ≠ NULL | `''` ≠ NULL | **`''` IS NULL** |
| Concatenate | `a \|\| b` | `a \|\| b` or `concat()` (V) | **`concat(a,b)` only — `\|\|` is OR** (V) | `a \|\| b` |
| Find substring | `INDEX(s, sub)` / `POSITION(sub IN s)` | `instr(s, sub)` / `locate(sub, s)` (V) | `instr(s, sub)` / `locate(sub, s)` (V) | `INSTR(s, sub)` |
| Replace literal | `OREPLACE(s, a, b)` | `regexp_replace` / `replace` | `replace` | `REPLACE(s, a, b)` |
| Text type | `VARCHAR(n)` | `STRING` | `STRING` | `VARCHAR2(n)` |
| `int / int` | **truncates** (V) | DOUBLE | DOUBLE (V) | exact NUMBER |
| Integer division | default `/` | `a DIV b` | `a DIV b` (V) | `TRUNC(a / b)` |
| Modulo | `MOD(a, b)` — no `%` (V) | `a % b` | `a % b` (ints) (V) | `MOD(a, b)` |
| Quote identifier | `"My Col"` | `` `My Col` `` (`"` = string) | `` `My Col` `` (`"` = string) | `"My Col"` — forces case |
| Table alias | `FROM t x` | `FROM t x` | `FROM t x` | `FROM t x` — **no AS** (V) |
| String aggregation | XMLAGG idiom (no LISTAGG ?) | `concat_ws(',', collect_list(x))` | `group_concat(x, ',')` | `LISTAGG(x, ',') WITHIN GROUP (ORDER BY x)` |
| Set difference | `MINUS` / `EXCEPT` | `EXCEPT` / `MINUS` (V) | `EXCEPT` / `MINUS` (V) | `MINUS` |
| Scalar select | `SELECT 1` | `SELECT 1` | `SELECT 1` | **`SELECT 1 FROM DUAL`** (V) |
| GROUP BY ordinal | avoid | avoid (config) | avoid | **no** — groups by the literal (V) |
| Case of `=` on strings | session mode (`tmode`) (?) | case-sensitive | case-sensitive | case-sensitive |

## Lint outcomes you will see
- `ok: false` + `source: ad-sql-check`: an **error** row would make the query fail (or silently misbehave in a way with an exact fix). Apply `fix`, rerun.
- `meta.warnings` on a successful query: silent-wrong-answer traps (Teradata case-insensitive `=`, integer division, Oracle `ROWNUM` with `ORDER BY`, Impala `concat` NULL). Fix before the final run.
- Capability-gated rules (Teradata `TRUNC`/`TO_CHAR`/`LISTAGG`, Hive `QUALIFY`) block only when `ad-setup --only sources` probed the feature as missing; unknown → warning. Run `ad-doctor --online` to record probes.
