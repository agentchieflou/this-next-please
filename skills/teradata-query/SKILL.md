---
name: teradata-query
description: Use for any read-only SQL against Teradata (Jira history lives here: PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS). Never connect directly; ad-td lints the SQL for Teradata syntax first, runs it, and returns TOON.
---
# teradata query (read-only)

0. Before writing SQL read `references/teradata-sql.md` §Row limiting and §Dates. No `LIMIT`, no `%`, `TOP` cannot combine with `QUALIFY`, integer division truncates, `=` on strings may be case-insensitive.
1. Write the SQL to `.agent/sql/<ticket>-<purpose>.sql`. One SELECT. Add `SAMPLE 100` (or `TOP 100`, never with QUALIFY) while exploring; remove only for the final run.
2. Run `ad-td --env <env> --sql-file <that file> --name <purpose>` (`--env` defaults to the `env` fact in AGENTS.md).
3. `ok: false` with `source: ad-sql-check` → the `findings` rows give line, rule and `fix`; apply the fix, rerun. This is the linter, not the database. Other `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`.
4. `meta.warnings` present → apply each fix before the final run; they are silent-wrong-answer traps.
5. `rule: 6` → do not read rows. Use `stats` or script over `path` (see `data-adapter`).
6. Invoke `state-update` with the `path` and `run_id`.
7. Return to the calling skill (or `router`).
