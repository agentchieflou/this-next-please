# UAT method — tiers, classes, grain

## Source-of-truth order
1. **Live Jira** (`ad-pncli jira search`, `ad-jira changelog`, `ad-jira sprint-replay`) — what the system of record says now, or said at an instant (replay).
2. **Jira history in Teradata** (`jira_hist_table`) — the warehouse copy the report is built on. Can lag, can miss rows, can mis-map.
3. **Power BI** (`ad-pbip visual-query`, `dax-studio-export`) — what the report shows: model logic over the warehouse copy.
The **expected document** is the requester's claim. It is compared, never trusted; when every tier agrees against it, the class is `expectation-wrong`.

## Classes (one per key × metric; first match wins)
| class | condition | meaning |
|---|---|---|
| `missing` | key present in only one tier | scope or join-key mismatch |
| `expectation-wrong` | all present tiers agree, expected differs | the document is wrong |
| `report-bug` | pbi ≠ hist and (no jira or hist = jira) | model/report logic |
| `history-gap` | hist ≠ jira and coverage shows no rows in window, `n_rows` 0, or null points | **the warehouse cannot reproduce Jira** — the case where committed+completed points equal a value the history table cannot produce because data is missing |
| `lag` | hist ≠ jira and last history change < window end | load lag |
| `mapping-bug` | hist ≠ jira with full coverage | load transformation defect |
| `unexplained` | tiers disagree, no coverage / no history tier | supply `--hist-coverage` or the missing tier |
`--tol` sets a numeric tolerance (rounding). Truth reported per row is the highest tier that has a value.

## Grain matching (do this before reconcile)
- The visual's grain is its group-by columns (`ad-uat plan` → `group_by`, `key_guess`); measures are the metrics.
- Live Jira rows are per issue; a sprint chart is per sprint. Aggregate the finer side with a ≤10-line script: read the TSV with `AgentTable.read_tsv`, sum per key, write a TSV, `ad-view` it. Never compare different grains.
- Normalize key formatting on every side (same case, no whitespace; dates as `YYYY-MM-DD`).
- `sprint-replay` already emits per-issue `committed`/`completed` flags and per-sprint sums (`summary`); use the summary for a per-sprint chart, the rows for a per-issue table.

## Coverage file
`--hist-coverage cov.tsv` with `key, first_ts, last_ts, n_rows, points_null` — produced by the coverage template. Without it the
`history-gap` / `lag` / `mapping-bug` split is impossible and rows come back `unexplained`.

## Windows and instants
Sprint numbers are instants: committed at `startDate`, completed at `completeDate` (or `endDate`). The history table must be
read *as of* those instants (`CHANGED_TS <= TIMESTAMP '...'` + `QUALIFY ROW_NUMBER() ... = 1`), not as its current row.

## What the findings file must contain (≤ 40 lines, written by `ad-uat reconcile`)
counts per class · definition of each class present · up to 3 example rows per class (key, col, expected, jira, hist, pbi, note) ·
one recommendation per class · for `history-gap` the fixed sentence that the warehouse cannot reproduce live Jira. Do not restate rows in chat; cite the path.
