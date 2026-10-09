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
  definition/bookmarks/bookmarks.json the bookmark index: Desktop lists only the bookmarks named here
  definition/bookmarks/<name>.bookmark.json  explorationState.sections.<page>.visualContainers.<visualId>
  definition/reportExtensions.json    report-level measures (entities[].measures[]); older projects may hold
                                      reportExtension.json (singular): both are read
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
  `ad-pbip page|visual|bookmark add` do exactly that (the highest version a file of that kind declares), and say so in
  their `schema` field: `copied from <file>`.
- A kind the project has no file of gets what Power BI Desktop 2.157 (August 2026) writes, the one table in
  `agentdata/pbip/pbir.py` (`DESKTOP_SCHEMAS`), reported as `2.157 default`: report 3.3.0, page 2.1.0,
  pagesMetadata 1.1.0, visualContainer 2.12.0, visualContainerMobileState 2.7.0, bookmark 2.1.0,
  bookmarksMetadata 1.0.0, versionMetadata 1.0.0, reportExtension 1.0.0; `definition.pbir` is definitionProperties
  2.0.0. A Desktop older than 2.157 may refuse such a file: open the project with 2.157 or later.
- Desktop converts a PBIR-Legacy report (`report.json` at the report root) to PBIR when it saves: PBIR is the default.
- `definition.pbir` `version` "4.0" and `version.json` "2.0.0" are constants.

## Volatile (do not diff, do not "fix") vs load-bearing
Volatile: `position` floats, `expansionStates`, `annotations`, `howCreated`, theme name GUIDs, `$schema` minor versions, `diagramLayout.json`.
Load-bearing: object names, `pageOrder`, filter names, `.platform` `logicalId`, `lineageTag`s already present.

## Reading Desktop into the workflow
A running Desktop re-reads the files on `ad-pbip desktop reload --pid <pid> [--report-only]` (the Desktop Bridge's `file.reload`,
documented for Desktop 2.155+, verified on 2.157): `--report-only` after PBIR-only edits, without it the model is re-applied too.
It refuses while Desktop has unsaved changes — ask the human to save, never pass `--discard` on your own. Close and reopen the
`.pbip` only where there is no bridge (`ad-pbip capabilities` says so). Saving from Desktop rewrites files in its own canonical
order — commit before opening Desktop so its rewrite is a separate, reviewable diff.
