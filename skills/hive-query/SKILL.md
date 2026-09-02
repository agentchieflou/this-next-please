---
name: hive-query
description: "Use for read-only SQL against Hive (HiveServer2) or Impala on Hadoop. Never connect directly; ad-hive / ad-impala lint the SQL for the engine's syntax first, run it, and return TOON. Hive and Impala differ — `||` is OR in Impala."
---
# hive / impala query (read-only)

0. Before writing SQL read `references/hive-impala-sql.md` §The five differences, §Row limiting and §Dates. Hive 3 has no QUALIFY (Hive 4 does), Impala has none; `||` concatenates in Hive but is LOGICAL OR in Impala — use `concat()`; Hive `trunc()` knows only MONTH/QUARTER/YEAR.
1. Pick the engine from the request: Impala → `ad-impala` (env fact `impala_env`); Hive/Hadoop/Spark table → `ad-hive` (env fact `hive_env`).
2. Write the SQL to `.agent/sql/<ticket>-<purpose>.sql`. One SELECT. Add `LIMIT 100` while exploring; remove only for the final run.
3. Run `ad-hive --sql-file <that file> --name <purpose>` or `ad-impala ...` (`--env` overrides the fact).
4. `ok: false` with `source: ad-sql-check` → apply the `fix` from `findings`, rerun. Other `ok: false` → fix once from `hint` (`klist` shows whether a Kerberos ticket exists); second failure → `friction-log` type `tool-error`.
5. `meta.warnings` present → apply each fix before the final run.
6. `rule: 6` → do not read rows. Use `stats` or script over `path` (see `data-adapter`).
7. Invoke `state-update` with the `path` and `run_id`.
8. Return to the calling skill (or `router`).
