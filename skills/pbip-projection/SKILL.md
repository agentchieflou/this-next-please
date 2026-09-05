---
name: pbip-projection
description: "Use whenever a task touches a Power BI project (PBIP) — report pages, visuals, measures, columns, TMDL, \"what feeds this chart\". Builds the LLM projection of the PBIP (normalized JSON, TSVs, MODEL.md / REPORT.md / LINEAGE.md) with ad-pbip and tells you what to read. Never open visual.json or .tmdl files raw to answer questions."
---
# PBIP projection (read the model and report without reading the PBIP)

Inputs: `pbip_path` fact in `AGENTS.md` (or pass the folder holding the `.pbip`). The PBIP is the source of truth; the projection under `.agent/pbip/<name>/` is generated next to it and committed. Never edit projection files.

1. `ad-pbip project` (add `--force` after you edited TMDL or report JSON by hand; otherwise it skips when `meta.json` hashes match). Read `meta.path`. Which files under the PBIP are generated, and which must never be hand-edited: `references/pbip-layout.md` §Volatile (do not diff, do not "fix") vs load-bearing.
2. Read in this order, only what the task needs: `MODEL.md` (tables, measures with dependencies, columns, hierarchies, partitions and source tables), `REPORT.md` (pages → visuals → fields and filters), `LINEAGE.md` (field → visuals, column/measure → measures using it, table → warehouse objects).
3. Precise questions → `ad-pbip refs`: `--visual "<title or id>"` (what feeds a chart, down to source tables), `--page "<name>"`, `--table T --column C` or `--table T --measure M` (where used: visuals, measures, relationships, sort-by, hierarchies). How a visual names a field, which is what `refs` resolves: `references/pbip-layout.md` §Field references in visual.json.
4. Bulk questions ("all measures without a format string") → script over the TSVs (`measures.tsv`, `columns.tsv`, `visual_fields.tsv`, `filters.tsv`) with `AgentTable.read_tsv`; never read `normalized.json` into context.
5. `lint_errors > 0` in the `project` output → the TMDL has syntax problems; hand off → `tmdl-edit` step 3 (`ad-pbip lint`).
6. `state-update` with the projection path. Hand off → `tmdl-edit` (change the model), `pbi-validate` (verify), `uat-report-visual` (numbers wrong), else return to the caller.

§ When the folder is not shaped the way the commands expect: `references/pbip-layout.md` §Names and versions, and §Reading Desktop into the workflow when the PBIP is open in Desktop. Each step above points at the one section it needs.
