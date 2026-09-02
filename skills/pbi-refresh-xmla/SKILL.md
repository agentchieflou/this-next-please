---
name: pbi-refresh-xmla
description: "Use to refresh a deployed Power BI semantic model (full, table, or partition) through the XMLA endpoint using a TE2 C# script (TOM RequestRefresh + SaveChanges). Use after deploy or when asked to refresh a model/dataset."
---
# Refresh via TE2 script

1. Scope: `full` | `table:<name>` | `partition:<table>/<partition>`. User did not say → `full`.
2. `$env:TE_REFRESH_SCOPE = "<scope>"` then
   `& "<te2_exe>" "powerbi://api.powerbi.com/v1.0/myorg/<pbi_workspace>" "<pbi_model>" -S "<skills_dir>/pbi-refresh-xmla/scripts/refresh.csx" -E -W`
3. Exit non-zero → `az account show`. Fails → `az login --allow-no-subscriptions`, retry once. Second failure → `friction-log`.
4. Verify: `az rest --method get --url "https://api.powerbi.com/v1.0/myorg/groups/<ws_id>/datasets/<ds_id>/refreshes?`$top=1" --resource https://analysis.windows.net/powerbi/api`. Read `status`. `Failed` → `friction-log` with `serviceExceptionJson`.
5. `state-update` `phase=validating`. Hand off → `dax-studio-export` if the ticket needs value checks, else `router`.
