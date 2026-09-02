---
name: dax-studio-export
description: Use to evaluate a DAX query against a deployed model and get results as TOON, or to export a .vpax model-metrics file, using DAX Studio's dscmd.exe. Use for measure value checks, regression diffs, and model size analysis.
---
# DAX Studio export

1. Write the query to `.agent/dax/<KEY>-<purpose>.dax`. Must start with `EVALUATE`. Wrap in `TOPN(500, …)` while exploring.
2. `& "<dscmd_exe>" csv ".agent/out/<KEY>-<purpose>.csv" -s "powerbi://api.powerbi.com/v1.0/myorg/<pbi_workspace>" -d "<pbi_model>" -f ".agent/dax/<KEY>-<purpose>.dax"`
3. View as TOON: `python -m agentdata.csv2toon ".agent/out/<KEY>-<purpose>.csv"`.
4. Regression: export the same query before and after a change → `ad-diff before.tsv after.tsv --key <row key>`.
5. Model metrics: `& "<dscmd_exe>" vpax ".agent/out/<KEY>.vpax" -s "<server>" -d "<pbi_model>"`. Report file size only; do not open.
6. `state-update` with paths. Return to caller.
