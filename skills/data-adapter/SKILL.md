---
name: data-adapter
description: How to read and produce data in this workspace. Use whenever you need rows from Jira, Teradata, Oracle, Hive or Impala, or need to compare two datasets. Never call pncli/DB drivers directly; every ad-* command lints, runs, and returns TOON.
---
# Data adapter (ad-* commands)

| Need | Command |
|---|---|
| Jira rows | `ad-pncli jira search --jql "<JQL>" [--fields key,status,assignee,updated]` |
| Any other pncli read | `ad-pncli raw <pncli args…>` |
| Teradata | `ad-td --sql "<SELECT…>"` or `--sql-file q.sql` (`--env` defaults to the AGENTS.md fact `env`) |
| Oracle / Hive / Impala | `ad-ora …` / `ad-hive …` / `ad-impala …` (same flags; facts `oracle_env`, `hive_env`, `impala_env`) |
| Lint SQL before running | `ad-sql-check --dialect teradata|hive|impala|oracle q.sql` (ad-td/ad-ora/ad-hive/ad-impala run it for you) |
| Re-read a TSV | `ad-view <path>` |
| Compare two results | `ad-diff <left.tsv> <right.tsv> --key <col> [--cols a,b]` |
| Toolchain health | `ad-doctor` (offline) · `ad-doctor --online` (Jira, SELECT 1, XMLA) · fix with `ad-setup --only <step>` |

## Reading TOON
- Check `meta.ok: true`. `meta.rule` tells you how much you got: `3/4` → complete data is in context; `5` → 20 of `rows` shown + `stats`, full data at `path`; `6` → 10 shown, you MUST script over `path`; never open it in the editor.
- `meta.warnings[n]` → dialect traps the linter could not prove fatal (case-insensitive `=`, integer division, `ROWNUM` ordering, NULL-propagating `concat`). Apply each fix before the final run.
- `ok: false` with `source: ad-sql-check` → the query never ran; `findings` rows carry `line`, `rule`, `message`, `fix`, `doc` (a section of the dialect reference). Apply the fix and rerun.

## Rules
1. Never `--raw` except when debugging a pncli payload shape.
2. Never compute totals/diffs by reading rows. Write a ≤10-line Python script using `agentdata.AgentTable.read_tsv` and print via `agentdata.render`.
3. Read-only SQL only; the adapter rejects DML/DDL and there is no bypass for the linter.
4. Write SQL for the engine you are on: `references/sql-dialects.md` is the side-by-side; each query skill's `references/` has the full dialect guide.
5. `ok: false` → fix once from `hint`; second failure → `friction-log` type `tool-error`.
6. Record every `path` via `state-update` so the next session can `ad-view` it.
