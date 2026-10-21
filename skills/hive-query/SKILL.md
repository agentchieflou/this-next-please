---
name: hive-query
description: "Use for read-only SQL against Hive (HiveServer2), Impala or Spark SQL (the Spark Thrift Server) on Hadoop. Never connect directly; ad-hive / ad-impala / ad-spark lint the SQL for the engine's syntax first, run it, and return TOON. The engines differ — `||` is OR in Impala."
---
# hive / impala / spark query (read-only)

0. Before writing SQL read `references/hive-impala-sql.md` §The five differences, §Row limiting and §Dates. Hive 3 has no QUALIFY (Hive 4 does), Impala has none; `||` concatenates in Hive but is LOGICAL OR in Impala — use `concat()`; Hive `trunc()` knows only MONTH/QUARTER/YEAR.
1. Pick the engine from the request: Impala → `ad-impala` (env fact `impala_env`); Spark, Spark SQL, a Delta table → `ad-spark` (env fact `spark_env`; read §Spark SQL first); Hive/Hadoop table → `ad-hive` (env fact `hive_env`). A Spark table with no `spark_env` fact → `ad-hive` reads the same metastore.
2. Write the SQL to `.agent/sql/<ticket>-<purpose>.sql`. One SELECT. Add `LIMIT 100` while exploring; remove only for the final run.
3. Run `ad-hive --sql-file <that file> --name <purpose>`, `ad-impala ...` or `ad-spark ...` (`--env` overrides the fact).
4. `ok: false` with `source: ad-sql-check` → apply the `fix` from `findings`, rerun. Other `ok: false` → fix once from `hint` (`klist` shows whether a Kerberos ticket exists); second failure → `friction-log` type `tool-error`.
   The request said Hadoop (not Hive by name) and Hive refused for capacity — a YARN queue, a timeout, `Error while processing statement` with no SQL line → run the same query once on the other engine (`ad-impala`, after re-reading §The five differences: `||` → `concat()`). Its failure too → `friction-log` type `tool-error` quoting both. A missing Kerberos ticket is an environment error (router step 8), not a reason to switch engines.
5. `meta.warnings` present → apply each fix before the final run.
6. `rule: 6` → do not read rows. Use `stats` or script over `path` (see `data-adapter`).
7. Invoke `state-update` with the `path` and `run_id`.
8. Return to the calling skill (or `router`).
