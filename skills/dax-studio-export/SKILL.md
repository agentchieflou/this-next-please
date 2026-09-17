---
name: dax-studio-export
description: "Use to evaluate a DAX query against a deployed model or a running Desktop and get results as TOON, or to export a .vpax model-metrics file. Service queries go through ad-pbi dax (Tabular Editor with an az token, no DAX Studio sign-in); Desktop queries and .vpax use DAX Studio's dscmd.exe. Use for measure value checks, regression diffs, and model size analysis."
---
# DAX export

1. Write the query to `.agent/dax/<KEY>-<purpose>.dax`. Must start with `EVALUATE`. Wrap in `TOPN(500, …)` while exploring.
2. **Deployed model (the service):** `ad-pbi dax --workspace "<pbi_workspace>" --model "<pbi_model>" --file .agent/dax/<KEY>-<purpose>.dax --out .agent/out/<KEY>-<purpose>.tsv`
   It renders TOON and keeps the file. Sign-in is the command's: Tabular Editor gets an az access token per launch, and a signed-out Azure CLI is signed in by the command (`az login --allow-no-subscriptions`, a browser window — say so in one line). Never open DAX Studio or Tabular Editor by hand to seed a sign-in. `not_signed_in` after that → `ad-pbi auth --probe` once, then `friction-log` type `tool-error`.
3. **Running Desktop (`localhost:<port>` from `ad-pbip desktop`, no sign-in):** run dscmd. pwsh: `& "<dscmd_exe>" csv ".agent/out/<KEY>-<purpose>.csv" -s "localhost:<port>" -f ".agent/dax/<KEY>-<purpose>.dax"`
   bash: `"<dscmd_exe>" csv ".agent/out/<KEY>-<purpose>.csv" -s "localhost:<port>" -f ".agent/dax/<KEY>-<purpose>.dax"`. Then view as TOON: `python -m agentdata.csv2toon ".agent/out/<KEY>-<purpose>.csv"`.
4. Regression: export the same query before and after a change (`--out …-before.tsv` / `…-after.tsv`) → `ad-diff before.tsv after.tsv --key <row key>`.
5. Model metrics — pwsh: `& "<dscmd_exe>" vpax ".agent/out/<KEY>.vpax" -s "<server>" -d "<pbi_model>"`
   bash: `"<dscmd_exe>" vpax ".agent/out/<KEY>.vpax" -s "<server>" -d "<pbi_model>"`. Report file size only; do not open. Against the service, `vpax` uses DAX Studio's own sign-in (open DAX Studio once and connect to the workspace, then re-run); against Desktop `localhost:<port>` it needs none.
6. `state-update` with paths. Return to caller.
