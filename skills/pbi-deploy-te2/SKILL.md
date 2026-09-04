---
name: pbi-deploy-te2
description: "Use to deploy a TMDL semantic model folder to a Power BI Premium workspace over XMLA. Use when the user says deploy, publish model, push TMDL, or after model edits are committed."
---
# Deploy TMDL with Tabular Editor 2

Inputs: `tmdl_path` (the semantic model definition folder containing `model.tmdl`), `workspace` (name or ID), `model`. Missing → `friction-log`. Prereq: `pbi-validate` passed on this commit.

1. **Dry-run preview** (`AGENTS.md` rule 8):
   `ad-pbi deploy <tmdl_path> --workspace <workspace> --model <model> --dry-run`
   - Enforces clean working tree (`git status --porcelain`).
   - Generates deploy script to `.agent/out/deploy-<ts>.xmla`.
   - Exit non-zero → `friction-log`. STOP.

2. **Deploy**:
   `ad-pbi deploy <tmdl_path> --workspace <workspace> --model <model>`
   - Add `--roles` only when configuration specifies `deploy_roles: true`.
   - Checks deploy stamp in `.agent/out/deploy-<ts>.json` to prevent duplicate re-deployments.
   - Logs output to `.agent/out/deploy-<ts>.log`.

3. **Hand off**:
   - Exit 0 → `state-update` `phase=validating`. Hand off → `pbi-refresh-xmla`.
   - Exit non-zero → `friction-log`. Never retry a deploy automatically.
