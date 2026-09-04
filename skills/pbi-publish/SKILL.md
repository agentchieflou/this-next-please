---
name: pbi-publish
description: "Use to publish, deploy, and rebind Power BI report and semantic model definitions to Fabric workspaces without Desktop."
---
# Power BI service publishing and binding transport

Deploy report and semantic model definitions directly to Fabric workspaces using the Fabric REST item-definition transport.

Inputs: `pbip_path` fact or report directory, target workspace (`--workspace <name|id>`), target semantic model (`--model <name|id>`).

## Workflow

1. **Binding diff and dry-run** (`AGENTS.md` rule 8):
   Always run with `--dry-run` first to test entity bindings and inspect payload parts:
   `ad-pbi publish report <pbip> --workspace <workspace> --model <model> --dry-run`
   - Verifies all report visual fields, filters, and extension measures against target model's TMDL.
   - Converts `definition.pbir` to `byConnection` in memory only (disk stays `byPath`).
   - Read the TOON output and verify `ok: true`.

2. **Stop condition**:
   If binding verification reports any unresolved entity or column/measure reference:
   - STOP immediately and invoke skill `friction-log`.
   - Never publish a broken visual binding unless explicitly instructed with `--allow-unbound`.

3. **Publish report**:
   Once `--dry-run` outputs `ok: true`, execute the publish:
   `ad-pbi publish report <pbip> --workspace <workspace> --model <model> [--name <name>]`
   - Automatically detects whether to create or update definition.
   - Warns if any part present in a previous service definition is missing from the local folder.
   - Records the 202 operation ID to `.agent/out/pbi-ops/<op-id>.json` before polling.
   - If publish fails or operation reports `Failed`, record error details and invoke `friction-log`.

4. **Verify deployment**:
   Verify the published report appears in the workspace:
   `ad-pbi ls --workspace <workspace> --kind report`
   If XMLA is configured on the workspace, verify live model queries using:
   `ad-pbip dax "EVALUATE TOPN(5, 'TableName')" --server <xmla_endpoint> --database <model>`

5. **Publish semantic model (Desktop-less alternative)**:
   For workspaces without XMLA Read/Write, deploy TMDL models directly:
   `ad-pbi publish model <definition_folder> --workspace <workspace> [--name <name>]`

6. **Resume interrupted operations**:
   If an operation was interrupted after 202:
   `ad-pbi ops <op-id>`
