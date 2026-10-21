---
name: data-adapter
description: "How to read and produce data in this workspace. Use whenever you need rows from Jira, Confluence, Bitbucket, Teradata, Oracle, Hive or Impala, or need to compare two datasets. Warehouses through ad-* only; Jira, Confluence and Bitbucket reads through toil, saved to .agent/out/ and read with ad-view. Everything reaches you as TOON."
---
# Data adapter (ad-* commands, and toil for what it reads)

| Need | Command |
|---|---|
| Jira rows | `toil jira issue search --jql "<JQL>" --limit 500 > .agent/out/<name>.json`, then `ad-view .agent/out/<name>.json` (`--fields key,status,assignee,updated` narrows the columns) |
| One Jira issue (description, acceptance criteria) | `toil jira issue get <KEY> > .agent/out/<KEY>.json`, then `ad-view .agent/out/<KEY>.json` |
| Its comment thread | `toil jira issue comments <KEY> > .agent/out/<KEY>-comments.json`, then `ad-view .agent/out/<KEY>-comments.json` |
| Confluence or Bitbucket read | `toil confluence page get <id> > .agent/out/<name>.json`, `toil bitbucket pr get <id> > .agent/out/<name>.json` (any read: `toil <area> <resource> <action> <ids> --<flag> <value>`), then `ad-view` it |
| toil's own usage, the commands an area has | `toil <area> --help` · `toil <area> <resource> --help` |
| A write to Jira, Confluence or Bitbucket | never toil: `ad-jira comment`, `transition` or `create`, `ad-confluence publish`, `ad-git pr` (each `--dry-run` first, each gated). Never pass `--allow-write` yourself |
| Teradata | `ad-td --sql "<SELECT…>"` or `--sql-file q.sql` (`--env` defaults to the AGENTS.md fact `env`) |
| Oracle / Hive / Impala | `ad-ora …` / `ad-hive …` / `ad-impala …` (same flags; facts `oracle_env`, `hive_env`, `impala_env`) |
| Lint SQL before running | `ad-sql-check --dialect teradata|hive|impala|oracle q.sql` (ad-td/ad-ora/ad-hive/ad-impala run it for you) |
| Re-read a TSV, a dscmd `.csv`, or a saved toil `.json` | `ad-view <path>` |
| Compare two results | `ad-diff <left.tsv> <right.tsv> --key <col> [--cols a,b]` |
| Toolchain health | `ad-doctor` (offline) · `ad-doctor --online` (Jira, SELECT 1, XMLA) · fix with `ad-setup --only <step>` |
| Jira refuses the token | `ad-jira whoami` (flavor, `token_source`); fix with `ad-doctor --only toil` (its hint names the connection) |
| toil will not start | `ad-doctor --only toil` (resolved path, npm shim, node entry, toil and Node versions) |

## Reading TOON
- Check `meta.ok: true`. `meta.rule` tells you how much you got: `3/4` → complete data is in context; `5` → 20 of `rows` shown + `stats`, full data at `path`; `6` → 10 shown, you MUST script over `path`; never open it in the editor.
- `meta.warnings[n]` → dialect traps the linter could not prove fatal (case-insensitive `=`, integer division, `ROWNUM` ordering, NULL-propagating `concat`). Apply each fix before the final run.
- `ok: false` with `source: ad-sql-check` → the query never ran; `findings` rows carry `line`, `rule`, `message`, `fix`, `doc` (a section of the dialect reference). Apply the fix and rerun.

## Rules
1. Never `--raw` except when debugging a payload shape.
2. Never compute totals/diffs by reading rows. Sums and counts by a key: `ad-uat rollup <file> --by <cols> --sum <cols>`; two results: `ad-diff`. Only what neither does gets a ≤10-line Python script (`agentdata.AgentTable.read_tsv`, print via `agentdata.render`) — in a fleet that needs the `write` and `shell(python)` grants the tile offers, so ask before reaching for it.
3. Read-only SQL only; the adapter rejects DML/DDL and there is no bypass for the linter.
4. Write SQL for the engine you are on: `references/sql-dialects.md` §The side-by-side is the one-row-per-operation comparison; each query skill's `references/` has the full dialect guide.
5. `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`. What a lint row means before you act on it: `references/sql-dialects.md` §Lint outcomes you will see.
6. toil prints one JSON envelope, `{ok, data, error, meta}`. `ad-view` of a failed one prints toil's `error.code: message` and its `fix` → apply the fix once. `meta.warnings` (a truncated history, a summary that left rows in a file) and `next_cursor` stay on what `ad-view` prints: a page with a cursor is not the whole answer. Unknown command → run `toil <area> --help` ONCE, use a listed command, and report the working one. Never guess a second time.
7. `refused: toil_write_in_fleet` → you ran a toil write (`--allow-write`, or a `connections` / `dossiers` / `skill` change); run the extension its `hint` names. `WRITE_DISABLED` is toil saying a person has not turned writes on: report it, never work around it. toil not found (an npm package needing Node 24.14+: `toil.cmd`, never `toil.exe`) or `UNSUPPORTED_NODE` → `ad-doctor --only toil`, print its row and hint verbatim, `friction-log` type `tool-error`, STOP. Never install software, change PATH, or substitute another client.
8. Record every `path` via `state-update` so the next session can `ad-view` it.
