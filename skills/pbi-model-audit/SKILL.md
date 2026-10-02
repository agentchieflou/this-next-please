---
name: pbi-model-audit
description: "Use to audit a Power BI semantic model for performance, DAX anti-patterns, Copilot AI readiness, and slow measure optimization with evidence."
---
# Semantic model audit and DAX optimization

Inputs: `pbip_path` / `tmdl_path` facts, or live Desktop connection via `--pid` / `--server`.

1. Run model best-practice audit:
   `ad-pbip model audit [<definition>|--server <host:port>] [--bpa]`
   Evaluates 8+ canonical rules:
   - `columns-not-hidden-used-in-measures`: visible columns that only feed measures
   - `summarize-by-numeric-key`: numeric ID / key columns with default summarization
   - `missing-format-string`: measures lacking explicit format strings
   - `bi-directional-relationship`: bi-directional cross-filtering relationships
   - `unused-columns`: columns not referenced in measures, DAX user-defined function bodies, hierarchies, relationships, or visuals
   - `dax-anti-pattern-filter-all`: `FILTER(ALL(Table))` scans across entire tables
   - `implicit-measures-used`: report visuals using implicit aggregations instead of explicit measures
   - `missing-description-used-measure`: report-used measures without descriptions
   - `udf-missing-description`: functions without the `///` description (and `@param` / `@returns` lines) IntelliSense shows at every call
   - `unused-function`: functions no measure, column, calculation item or other function calls (fix: `function.delete`)
   Every row includes an op-list `fix` snippet that `ad-pbip model apply` accepts directly. A function's signature, argument count, recursion and the compatibility level it needs are `ad-pbip check` rules (`udf-*`), not audit rows.

2. Run Copilot AI readiness audit:
   `ad-pbip model audit [<definition>|--server <host:port>] --copilot`
   Produces a scored checklist (0 to 100%) evaluating table/measure/column descriptions, technical key hiding hygiene, and synonyms for Q&A and Copilot semantic search.

3. Optimize slow DAX measures with trace evidence:
   `ad-pbip model optimize --measure <MeasureName> --pid <pid>|--server <host:port>`
   - Captures baseline execution time and query result
   - Proposes provable DAX transform (variables, `KEEPFILTERS`, `CALCULATE`, `DIVIDE`)
   - Applies rewrite to live model and measures performance after
   - Regression guard: automatically verifies results match and rolls back if numbers differ
