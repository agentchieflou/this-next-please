---
name: teradata-query
description: Use for any read-only SQL against Teradata (Jira history lives here: PROJECT_KEY, ISSUE_KEY, STATUS, CHANGED_TS). Use when the task needs counts, rows, history, or validation from this source. Never call the database directly; use ad-td.
---
# teradata query (read-only)

1. Write the SQL to `.agent/sql/<ticket>-<purpose>.sql`. One SELECT. Add `SAMPLE 100` / `FETCH FIRST` / `LIMIT` while exploring; remove only for the final run.
2. Run `ad-td --env <env from AGENTS.md> --sql-file <that file> --name <purpose>`.
3. Read `meta`. `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`.
4. `rule: 6` → do not read rows. Use `stats` or script over `path` (see `data-adapter`).
5. Invoke `state-update` with the `path` and `run_id`.
6. Return to the calling skill (or `router`).
