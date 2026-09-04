# Native Power BI Features Mapping (native fixture)

| # | Feature | Fixture Path | Objects / Properties |
|---|---|---|---|
| 1 | `bookmarks` | `Native.Report/definition/bookmarks/b1.json` | `BookmarkOverview` targeting visual `22222222222222222222` |
| 2 | `drillthrough` | `Native.Report/definition/pages/drillthrough_page/page.json` | `drillthrough.target` on `Sales[Product]` |
| 3 | `tooltip` | `Native.Report/definition/pages/tooltip_page/page.json` | `pageType: Tooltip`, bound to visual `22222222222222222222` |
| 4 | `sync_slicers` | `Native.Report/definition/pages/overview/visuals/11111111111111111111/visual.json` | `syncSlicers` with `YearSyncGroup` |
| 5 | `field_parameters` | `Native.SemanticModel/definition/tables/FieldParam.tmdl` | `FieldParam` partition with `NAMEOF` |
| 6 | `calculation_groups` | `Native.SemanticModel/definition/tables/TimeIntelligence.tmdl` | `calculationGroup` precedence 1, items `YTD`, `Prior Year` |
| 7 | `visual_calculations` | `Native.Report/definition/pages/overview/visuals/22222222222222222222/visual.json` | `visualCalculation` with `nativeQueryRef: Profit` |
| 8 | `conditional_formatting` | `Native.Report/definition/pages/overview/visuals/22222222222222222222/visual.json` | `backColor.conditionalFormatting` on `Sales[Margin]` |
| 9 | `rls_ols` | `Native.SemanticModel/definition/roles/SalesManager.tmdl` | Role `SalesManager` with `tablePermission Customers` |
| 10 | `incremental_refresh` | `Native.SemanticModel/definition/tables/Sales.tmdl` | `refreshPolicy` with `RangeStart` & `RangeEnd` |
| 11 | `hierarchies` | `Native.SemanticModel/definition/tables/Dates.tmdl` | `hierarchy CalendarHierarchy` (Year -> Quarter -> Month) |
| 12 | `sort_by` | `Native.SemanticModel/definition/tables/Dates.tmdl` | `column MonthName` with `sortByColumn: MonthNumber` |
| 13 | `format_strings` | `Native.SemanticModel/definition/tables/Sales.tmdl` | Format strings and dynamic format string on measures |
| 14 | `page_navigation` | `Native.Report/definition/pages/overview/visuals/33333333333333333333/visual.json` | Button action with `PageNavigation` to `drillthrough_page` |
| 15 | `mobile_layout` | `Native.Report/definition/pages/overview/page.json` | `mobileState` with visual container positions |
| 16 | `visual_interactions` | `Native.Report/definition/report.json` | `visualInteractions` from `11111111111111111111` to `22222222222222222222` |
| 17 | `relationships` | `Native.SemanticModel/definition/relationships.tmdl` | `isActive: false` relationship and `USERELATIONSHIP` measure |
| 18 | `report_level_measures` | `Native.Report/definition/reportExtension.json` | Extension measure `Report Level KPI` on `Sales` |
| 19 | `themes` | `Native.Report/definition/report.json` | Custom theme `CY24SU02` with theme file |
| 20 | `agg_tables` | `Native.SemanticModel/definition/tables/SalesAgg.tmdl` | Aggregation table with `isHidden` |
