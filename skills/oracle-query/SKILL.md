---
name: oracle-query
description: "Use for any read-only SQL against Oracle. Never connect directly; ad-ora lints the SQL for Oracle syntax first, runs it, and returns TOON."
---
# oracle query (read-only)

0. Before writing SQL read `references/oracle-sql.md` §Row limiting and §Dates. No `LIMIT`/`TOP` (use `FETCH FIRST n ROWS ONLY`), no `AS` on table aliases, `FROM DUAL` for scalar selects, `''` is NULL, `ROWNUM` before `ORDER BY` returns wrong rows.
1. Write the SQL to `.agent/sql/<ticket>-<purpose>.sql`. One SELECT. Add `FETCH FIRST 100 ROWS ONLY` while exploring; remove only for the final run.
2. Run `ad-ora --env <env> --sql-file <that file> --name <purpose>` (`--env` defaults to the `oracle_env` fact in AGENTS.md; the env name IS the connection name, e.g. `OIMPROD1_ROSVC`).
   `no oracle connection configured` or `no service name or SID` → Oracle needs hostname + port + service name (there is no ODBC DSN): print the hint, tell the user to run `ad-setup --patch`, STOP.
3. `ok: false` with `source: ad-sql-check` → apply the `fix` from `findings`, rerun. Other `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`.
4. `meta.warnings` present → apply each fix before the final run (string-vs-DATE compares, `= ''`, `ROWNUM` ordering).
5. `rule: 6` → do not read rows. Use `stats` or script over `path` (see `data-adapter`).
6. Invoke `state-update` with the `path` and `run_id`.
7. Return to the calling skill (or `router`).
