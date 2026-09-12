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
10. Acceptance criteria ambiguous. **Two readings that lead to different work** → `ad-state ask` with the two
    readings as `--choice`, then `friction-log`, then STOP. **A missing detail a safe, reversible default
    settles** (a date window nobody will dispute, an obvious unit) → `ad-state ask "<assumption>" --assume
    "<the default>"`, say so in one line, and CONTINUE. Never assume something you cannot undo.
11. You issued the same tool call twice with the same args.
12. You are about to write anything outside the current branch or `.agent/`.
13. A tool returned `"ok": false` twice in a row.
14. You are about to edit a source file whose `ad-graph guard` verdict is not `ok` -- or you have not run it.

## Style
15. Short answers. No preamble. State the next skill you will invoke and why (one line).

## Branches
16. **Before `git checkout -b`, look.** `git for-each-ref refs/heads --format=%(refname:short)` lists every local
    branch; `git branch --no-merged <default>` the ones whose work never reached `main`/`master`. A branch that
    already carries this ticket's key is this ticket's: continue on it when it is checked out, and when it is not,
    `ad-state ask` the operator to check it out (the allow-list has no `git checkout <branch>`) -- a second branch
    per ticket is how work gets stranded. At `fleet.branches.warn` (default 6) or more local branches, name the
    unmerged ones in one line and `ad-state ask --assume` whether to continue on the existing branch or which of
    the stale ones the operator will delete -- never you: a branch is the operator's to delete. Cautious, not
    stopped: a repository that legitimately holds nine branches still gets its PR, on the branch that exists.
