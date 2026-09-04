# Chart Selection & Encoding Hierarchy

## Rule 0: Sample the Data First
Before picking a visual type, always verify:
1. **Cardinality**: How many distinct values exist in the category column?
   - < 7 items: `columnChart`, `barChart`, `donutChart`.
   - 7–30 items: horizontal `barChart` (vertical column labels truncate).
   - > 30 items: searchable `tableEx` or `pivotTable`.
2. **Data Grain**: Is it discrete periods (months, quarters) or continuous timestamps?
   - Discrete periods: `columnChart` or `lineChart`.
   - Continuous high-density time: `lineChart` or `areaChart`.
3. **Number of Measures**:
   - 1 metric: bar, column, line, or card.
   - 2 metrics: dual-axis or scatter.
   - 3+ metrics: multi-metric `cardVisual` or `tableEx`.

## Question → Visual Type Mapping

| Analytical Question | Recommended Visual Type | Avoid / Anti-Pattern |
| :--- | :--- | :--- |
| How did metric trend over time? | `lineChart` or `columnChart` | `pieChart`, `tableEx` |
| Which categories rank highest? | horizontal `barChart` (sorted desc) | vertical column chart (truncated text) |
| How do parts contribute to whole? | `waterfallChart`, 100% stacked bar | `pieChart` with > 5 slices |
| How do two metrics correlate? | `scatterChart` | separate unlinked bar charts |
| Are we meeting KPI target? | `gauge` or `cardVisual` with variance | bare single number with no context |
| What is the granular row data? | `tableEx` or `pivotTable` | crowded card visuals |
| What is geographic distribution? | `azureMap` (with lat/long) | legacy `map` (deprecated) |

## Encoding Hierarchy (Most to Least Accurate Perception)
1. **Position along a common scale** (bar lengths, scatter coordinates) — Most accurate.
2. **Length** (unaligned bars) — High accuracy.
3. **Slope / Direction** (line trend angle) — Medium accuracy.
4. **Area / Angle** (pie slice, treemap rectangle) — Low accuracy.
5. **Color saturation / Shading** (heatmap intensity) — Qualitative only.
