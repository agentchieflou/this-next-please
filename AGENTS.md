# Canonical rules (this-next-please)

Scope: every project that installs these skills. Do not restate these in project files.

## Session
1. First action every session: invoke skill `session-bootstrap`. Then invoke `router`.
2. Do one skill at a time. Finish it, run `state-update`, return to `router`.
3. Never read a second project's `.agent/` directory.

## Data
4. Never call Teradata/Oracle/Hive/Spark/pncli directly for data. Use `ad-*` commands (skill `data-adapter`).
5. Data arrives as TOON. Full rows live on disk under `.agent/out/`. Do not open files > 500 rows; script over them.
6. Never compare datasets in your head. Use `ad-diff`.
7. Read-only SQL only. The adapter rejects DML/DDL; do not work around it.

## Writes to systems of record
8. Jira transitions, Confluence writes, PR creation: run with `--dry-run` first, read `"ok"`, then execute. Never merge a PR. Never close a ticket.
9. Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`).

## Stop conditions (invoke `friction-log`, then STOP)
10. Acceptance criteria ambiguous (missing date window, undefined term, two plausible readings).
11. You issued the same tool call twice with the same args.
12. You are about to write anything outside the current branch or `.agent/`.
13. A tool returned `"ok": false` twice in a row.
14. You are about to edit a source file whose `ad-graph guard` verdict is not `ok` -- or you have not run it.

## Style
14. Short answers. No preamble. State the next skill you will invoke and why (one line).
