---
name: data-adapter
description: How to read and produce data in this workspace. Use whenever any command returns rows, whenever you need Jira/Teradata/Oracle/Hive/pandas data, or when tempted to call pncli, SQL, or pandas directly. All data flows through ad-* commands and arrives as TOON.
---
# Data adapter (TOON in, files on disk)

## Commands (only these touch data)
| Need | Command |
|---|---|
| Jira rows | `ad-pncli jira search --jql "<JQL>" [--fields key,status,assignee,updated]` |
| Any other pncli read | `ad-pncli raw <pncli args…>` |
| Teradata | `ad-td --env <env> --sql "<SELECT…>"` or `--sql-file q.sql` |
| Oracle / Hive | `ad-ora …` / `ad-hive …` (same flags) |
| Re-read a TSV | `ad-view <path>` |
| Compare two results | `ad-diff <left.tsv> <right.tsv> --key <col> [--cols a,b]` |

## Reading TOON
- `meta:` block first. Check `ok: true`. `rule:` tells you how much you were shown:
  - 3/4 → complete data is in context.
  - 5 → 20 of `rows` shown + `stats`. Full data at `path`.
  - 6 → 10 shown. You MUST script over `path`; never open it in the editor.
- Table line `name[N]{cols}:` then one row per line, comma-separated, quoted when needed.
- `stats:` gives `nulls`, `distinct`, `min`, `max` per column. Use these instead of scanning rows.

## Rules
1. Never pass `--raw` unless a command failed and you are debugging the payload.
2. Never compute totals/diffs by reading rows. Write a ≤10-line Python script using `agentdata.AgentTable.read_tsv` and print via `agentdata.render`.
3. Never write SQL with INSERT/UPDATE/DELETE/DDL. The adapter rejects it; do not work around.
4. If `ok: false` → read `hint`, fix once. Second failure → `friction-log`.
5. Record every `path` via `state-update` so the next session can `ad-view` it.
