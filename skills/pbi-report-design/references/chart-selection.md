# Chart Selection & Encoding Hierarchy

## Rule 0: Sample the Data First
Before picking a visual type, always verify:
1. **Cardinality**: How many distinct values exist in the category column?
   - < 7 items: `clusteredColumnChart`, `clusteredBarChart`, `donutChart`.
   - 7–30 items: horizontal `clusteredBarChart` (vertical column labels truncate).
   - > 30 items: searchable `tableEx` or `pivotTable`.
2. **Data Grain**: Is it discrete periods (months, quarters) or continuous timestamps?
   - Discrete periods: `clusteredColumnChart` or `lineChart`.
   - Continuous high-density time: `lineChart` or `areaChart`.
3. **Number of Measures**:
   - 1 metric: bar, column, line, or card.
   - 2 metrics: dual-axis or scatter.
   - 3+ metrics: multi-metric `cardVisual` or `tableEx`.
   - Several series per category: `clusteredColumnChart` / `clusteredBarChart` side by side; the stacked `columnChart` / `barChart` only when the series are parts of the category's total.

## Question → Visual Type Mapping

| Analytical Question | Recommended Visual Type | Avoid / Anti-Pattern |
| :--- | :--- | :--- |
| How did metric trend over time? | `lineChart` or `clusteredColumnChart` | `pieChart`, `tableEx` |
| Which categories rank highest? | horizontal `clusteredBarChart` (sorted desc) | vertical column chart (truncated text) |
| How do parts contribute to whole? | `waterfallChart`, 100% stacked bar | `pieChart` with > 5 slices |
| How do two metrics correlate? | `scatterChart` | separate unlinked bar charts |
| Are we meeting KPI target? | `gauge` or `cardVisual` with variance | bare single number with no context |
| What is the granular row data? | `tableEx` or `pivotTable` | crowded card visuals |
| What is geographic distribution? | `azureMap` (location, or lat/long) | `map` / `filledMap` (Bing Maps, being retired) |
| How do custom regions compare (territories, floor plan)? | `shapeMap` (added in Desktop) | `filledMap` |
| What does a plain-language question return? | Power BI Copilot (outside the page) | `qnaVisual` (Q&A, deprecated December 2026) |

## Slicer Selection

| The viewer needs to... | Visual type | Note |
| :--- | :--- | :--- |
| pick a few values from a long list, compactly | `slicer` (dropdown) | Desktop's default form |
| scan and tick values, maybe down a hierarchy | `listSlicer` | several fields make a hierarchy; tooltip measures allowed |
| choose among about 10 or fewer values at a glance | `advancedSlicerVisual` (button slicer) | one field; an optional measure on each tile |
| find a value by typing part of it | `textSlicer` | one text column |
| pick dates on a calendar, or a rolling period | `slicer` as a date picker | a Desktop setting today: say so in the brief |

Executive pages keep a year or period dropdown or tiles; a date picker earns its space on exploratory pages.

## Encoding Hierarchy (Most to Least Accurate Perception)
1. **Position along a common scale** (bar lengths, scatter coordinates) — Most accurate.
2. **Length** (unaligned bars) — High accuracy.
3. **Slope / Direction** (line trend angle) — Medium accuracy.
4. **Area / Angle** (pie slice, treemap rectangle) — Low accuracy.
5. **Color saturation / Shading** (heatmap intensity) — Qualitative only.
