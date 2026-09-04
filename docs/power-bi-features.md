# Native Power BI Features Matrix

Hardened native Power BI features matrix: each row specifies the test fixture path exercising the feature, the validator rule IDs catching breakages, the live verification check (Desktop port or XMLA), and the last verification date.

> [!NOTE]
> `ad-doctor --online` validates that `verified_on` dates for features used by the project have not decayed beyond `powerbi.feature_recheck_days` (default 30 days).

| Feature | Fixture Path | Rule IDs | Live Check | Verified On |
|---|---|---|---|---|
| `bookmarks` | `tests/fixtures/pbip/native/Native.Report/definition/bookmarks/b1.json` | `bookmark-visual-missing`, `bookmark-page-missing` | Screenshot diff / UIA state interaction | 2026-09-04 |
| `drillthrough` | `tests/fixtures/pbip/native/Native.Report/definition/pages/drillthrough_page/page.json` | `drillthrough-field-missing` | Interaction navigation + target filter verification | 2026-09-04 |
| `tooltip` | `tests/fixtures/pbip/native/Native.Report/definition/pages/tooltip_page/page.json` | `tooltip-page-not-tooltip` | Hover state screenshot capture | 2026-09-04 |
| `sync_slicers` | `tests/fixtures/pbip/native/Native.Report/definition/pages/overview/visuals/11111111111111111111/visual.json` | `sync-slicer-group-field-mismatch` | Cross-page slicer state sync verification | 2026-09-04 |
| `field_parameters` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/FieldParam.tmdl` | `fieldparam-nameof-mismatch` | `EVALUATE TOPN(5, 'FieldParam')` over XMLA/port | 2026-09-04 |
| `calculation_groups` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/TimeIntelligence.tmdl` | `calcgroup-precedence-clash` | `EVALUATE ROW("YTD", CALCULATE([Total Sales], 'TimeIntelligence'[Calculation Item] = "YTD"))` | 2026-09-04 |
| `visual_calculations` | `tests/fixtures/pbip/native/Native.Report/definition/pages/overview/visuals/22222222222222222222/visual.json` | `visualcalc-missing-nativequeryref` | Visual query execution over XMLA/port | 2026-09-04 |
| `conditional_formatting` | `tests/fixtures/pbip/native/Native.Report/definition/pages/overview/visuals/22222222222222222222/visual.json` | `cf-rule-field-missing` | Visual rendering & property inspection | 2026-09-04 |
| `rls_ols` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/roles/SalesManager.tmdl` | `rls-table-missing`, `rls-filter-invalid-dax` | `EVALUATE Customers` under effective role via TE2/XMLA | 2026-09-04 |
| `incremental_refresh` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/Sales.tmdl` | `refresh-policy-parameters-missing` | DMV `$SYSTEM.DISCOVER_STORAGE_TABLE_PARTITIONS` check | 2026-09-04 |
| `hierarchies` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/Dates.tmdl` | `level-column-missing`, `hierarchy-level-column-missing` | `EVALUATE TOPN(5, SUMMARIZE(Dates, Dates[Year], Dates[Quarter]))` | 2026-09-04 |
| `sort_by` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/Dates.tmdl` | `sort-by-missing` | `EVALUATE TOPN(5, Dates, [MonthNumber])` | 2026-09-04 |
| `format_strings` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/Sales.tmdl` | `format-string-invalid` | `EVALUATE ROW("Format", FORMAT([Total Sales], "$#,##0"))` | 2026-09-04 |
| `page_navigation` | `tests/fixtures/pbip/native/Native.Report/definition/pages/overview/visuals/33333333333333333333/visual.json` | `nav-action-page-missing` | Button click page navigation verification | 2026-09-04 |
| `mobile_layout` | `tests/fixtures/pbip/native/Native.Report/definition/pages/overview/page.json` | `mobile-visual-not-on-page` | Mobile layout layout container inspection | 2026-09-04 |
| `visual_interactions` | `tests/fixtures/pbip/native/Native.Report/definition/report.json` | `interaction-visual-missing` | Slicer selection cross-filter screenshot diff | 2026-09-04 |
| `relationships` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/relationships.tmdl` | `userelationship-inactive-missing` | `EVALUATE ROW("DeliveryDate", [Sales Delivery Date])` | 2026-09-04 |
| `report_level_measures` | `tests/fixtures/pbip/native/Native.Report/definition/reportExtension.json` | `extension-entity-missing`, `report-measure-entity-missing` | Report measure evaluation against model | 2026-09-04 |
| `themes` | `tests/fixtures/pbip/native/Native.Report/definition/report.json` | `theme-resource-missing` | Palette color evaluation & visual style inspection | 2026-09-04 |
| `agg_tables` | `tests/fixtures/pbip/native/Native.SemanticModel/definition/tables/SalesAgg.tmdl` | `agg-table-hidden` | `EVALUATE TOPN(5, SalesAgg)` query direct execution | 2026-09-04 |
