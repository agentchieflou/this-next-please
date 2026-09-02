# PBIP layout (PBIR report + TMDL model) — what is where, what never to touch

```
<Name>.pbip                           shortcut: {"version":"1.0","artifacts":[{"report":{"path":"<Name>.Report"}}]}
<Name>.Report/
  .platform                           Fabric metadata: type, displayName, logicalId  -> NEVER edit or regenerate logicalId
  definition.pbir                     {"version":"4.0","datasetReference":{"byPath":{"path":"../<Name>.SemanticModel"}}}
  definition/version.json             {"version":"2.0.0"}  (constant for PBIR)
  definition/report.json              report-level filterConfig, themes, settings
  definition/pages/pages.json         {"pageOrder":[...],"activePageName":...}  -> order is meaningful
  definition/pages/<pageId>/page.json displayName, filterConfig, visualInteractions
  definition/pages/<pageId>/visuals/<visualId>/visual.json
  definition/bookmarks/*.json         explorationState.sections.<page>.visualContainers.<visualId>
  definition/reportExtension.json     report-level measures (entities[].measures[])
  localSettings.json                  user-local; never commit
<Name>.SemanticModel/
  .platform, definition.pbism         {"version":"4.2"} — do not edit
  definition/database.tmdl            must start with `database` (compatibilityLevel)
  definition/model.tmdl               model properties + `ref table X` / `ref culture en-US` lines (every table needs a ref)
  definition/relationships.tmdl       `relationship <guid>` blocks: fromColumn (many side) / toColumn (one side)
  definition/expressions.tmdl         shared M expressions and parameters
  definition/tables/<Table>.tmdl      columns, measures, hierarchies, partitions, annotations
  definition/roles/, cultures/, perspectives/
  diagramLayout.json                  Desktop diagram positions — noise
```

## Field references in visual.json (what the validator resolves)
Every reference is one object with exactly one key: `Column`, `Measure`, `Aggregation` (wraps a Column; `Function` 0 Sum, 1 Avg,
2 DistinctCount, 3 Min, 4 Max, 5 Count, 6 Median, 7 StdDev, 8 Var), `Hierarchy`, `HierarchyLevel`, `PropertyVariationSource`.
- `field`/projection positions: `{"Column":{"Expression":{"SourceRef":{"Entity":"Sales"}},"Property":"Margin"}}` — **Entity**.
- inside `filter.Where` / `prototypeQuery`: `{"SourceRef":{"Source":"s"}}` — **Source** is an alias of the sibling `From[]`
  entry `{"Name":"s","Entity":"Sales","Type":0}` (Type 0 = model table; 1 = presentation object; 2 = expression table).
- Anchors: `visual.query.queryState.<Role>.projections[].field`, `sortDefinition.sort[].field`, `filterConfig.filters[].field`
  (visual, page, report), conditional formatting under `objects.*[].properties.*.expr` (untyped → recursive walk).
- `queryRef` is `Entity.Property` (or `Sum(Entity.Property)`); roles live under `query.queryState`, never directly under `query`.

## Names and versions
- Visual `name`: 20 lowercase hex chars, unique per page — keep Desktop's; bookmarks, sync groups and interactions point at it.
- Page `name`: unique per report (`ReportSection…` or 20 hex). Filter `name`: `Filter` + 24 hex, unique across the whole report.
- `$schema` URLs carry a version Desktop bumps with releases: preserve them, never invent or bump one; copy from a sibling file.
- `definition.pbir` `version` "4.0" and `version.json` "2.0.0" are constants.

## Volatile (do not diff, do not "fix") vs load-bearing
Volatile: `position` floats, `expansionStates`, `annotations`, `howCreated`, theme name GUIDs, `$schema` minor versions, `diagramLayout.json`.
Load-bearing: object names, `pageOrder`, filter names, `.platform` `logicalId`, `lineageTag`s already present.

## Reading Desktop into the workflow
Desktop does **not** hot-reload TMDL or report JSON: after any edit, close and reopen the `.pbip` to see it. Saving from Desktop
rewrites files in its own canonical order — commit before opening Desktop so its rewrite is a separate, reviewable diff.
