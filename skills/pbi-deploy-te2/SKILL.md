---
name: pbi-deploy-te2
description: Use to deploy a TMDL semantic model folder to a Power BI Premium workspace over XMLA with TabularEditor 2 (TabularEditor.exe). Use when the user says deploy, publish model, push TMDL, or after model edits are committed.
---
# Deploy TMDL with Tabular Editor 2

Inputs from `AGENTS.md`: `te2_exe`, `tmdl_path`, `pbi_workspace`, `pbi_model`. Missing → `friction-log`.

1. Branch clean: `git status --porcelain` empty. Not empty → commit via `bitbucket-pr` step 3 first.
2. Preview (no deploy): `& "<te2_exe>" "<tmdl_path>" -X ".agent/out/<KEY>-deploy.xmla" -S -C -O -E -W`
   Exit non-zero → paste last 10 lines, `friction-log` type `tool-error`. STOP.
3. Deploy: `& "<te2_exe>" "<tmdl_path>" -D "powerbi://api.powerbi.com/v1.0/myorg/<pbi_workspace>" "<pbi_model>" -S -C -O -E -W -P -Y`
   - `-S` shared expressions (required since TE2 2.27.0). `-P -Y` keep incremental-refresh partitions. Add `-R -M` only when AGENTS.md says `deploy_roles: true`.
   - Do not add or remove flags.
4. Exit 0 → `state-update` `phase=validating`. Hand off → `pbi-refresh-xmla`.
5. Exit non-zero → `friction-log`. Never retry a deploy automatically.
