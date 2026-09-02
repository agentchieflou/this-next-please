# Data format policy (the determinant)

Every connector normalizes into an `AgentTable` (columns + typed rows + provenance).
The policy engine then decides, deterministically, what goes to **context** and what
goes to **disk**. Agents never choose; the adapter does.

## Inputs to the decision
| Signal | How measured |
|---|---|
| `shape` | `scalar` \| `record` (1 row) \| `table` (uniform rows) \| `nested` (non-uniform / depth>1) |
| `rows` | row count after normalization |
| `est_tokens` | `len(toon_text) / 3.5` (conservative) |
| `mode` | `--raw` flag (debugging) or default |

## Rules (first match wins)
| # | Condition | Context gets | Disk gets |
|---|---|---|---|
| 1 | `--raw` and payload ≤ 300 tokens | JSON | `.json` |
| 2 | `--raw` and payload > 300 tokens | JSON header (top-level keys, counts) + path | `.json` |
| 3 | `scalar` or `record` with ≤ 20 fields | TOON inline (full) | none |
| 4 | `table`, rows ≤ 50 and est_tokens ≤ 1500 | TOON tabular (full) | `.tsv` |
| 5 | `table`, rows ≤ 500 | TOON header + first 20 rows + `stats` block + path | `.tsv` |
| 6 | `table`, rows > 500 | TOON schema + 10 sample rows + `stats` + path. Agent MUST script over the file. | `.tsv` |
| 7 | `nested`, flatten succeeds (≥ 80% keys shared after dot-path flatten) | re-enter as `table` | `.tsv` + `.json` |
| 8 | `nested`, flatten fails | TOON summary: top-level keys, list lengths, 1 sample record | `.json` |

`stats` block = per column: `nulls`, `distinct`, and `min`/`max` for numeric/date columns.

## Connector notes
- **pncli** always emits JSON. `ad-pncli` runs the pncli command, extracts the result array
  (`issues`, `results`, `values`, or root list), flattens Jira `fields.*` one level, then applies rules 4–8.
  Default Jira projection: `key,status,assignee,priority,updated,summary`. Pass `--fields` to change.
- **Teradata / Oracle / Hive** already return tabular. Rows are capped server-side at `--max-rows`
  (default 5000) with a statement timeout (default 120 s). Rules 4–6 apply.
- **pandas** in-process: `agentdata.from_df(df)` → same policy. Use in scripts so script output is TOON too.
- **Comparisons** (`ad-diff`): joins two TSVs on `--key`, emits TOON: `only_left[n]`, `only_right[n]`,
  `changed[n]{key,col,left,right}` (first 20 each) + counts. Never diff in context.

## Why
- TOON is ~40–60% fewer tokens than JSON for uniform tables and stays readable for a small model.
- Fixed thresholds remove a decision the worker model would otherwise deliberate over.
- Full data on disk keeps context stable across turns and lets scripts do the arithmetic.

## New commands and the rules their output hits
- `ad-sql-check` / lint inside `ad-td|ad-ora|ad-hive|ad-impala`: `findings` table (rule 4/5 by size); errors end the command with `ok: false` before any query runs; warnings ride in `meta.warnings`.
- `ad-jira changelog|sprint-replay`: change rows / per-issue rows through rules 4–6 (TSV on disk); `summary` is a small TOON record.
- `ad-pbip project`: files under `.agent/pbip/<name>/` (committed, hash-skipped); `check|lint`: `findings` table; `refs`, `visual-query`: rules 4–6.
- `ad-uat expect|reconcile`: TSVs through rules 4–6; `<KEY>-uat-findings.md` (≤ 40 lines) is the document of record.
- `ad-doctor|ad-setup`: `checks` table, rows sorted fail → warn → ok.
Rule 7 note: `render_nested` writes `.tsv` only (the `.json` copy is kept only when flattening fails, rule 8).

## Changelog
- 2026-09-01 v1: initial thresholds (50/1500, 500). Revisit after 2 weeks of friction logs.
- 2026-09-02 v1.1: no threshold change; documented the outputs of ad-sql-check, ad-jira, ad-pbip, ad-uat, ad-doctor and the rule-7 disk behaviour.
