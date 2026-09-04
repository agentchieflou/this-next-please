# Visual Cookbook

Formatting rules and properties per visual type.

## §1. columnChart & barChart
- **Sorting**:
  - Time dimensions: Always sort chronologically ascending.
  - Categorical rankings: Always sort by metric descending. Never leave sorted alphabetically by default.
- **Labels**: Enable data labels only when data density is low (< 12 bars). For dense charts, rely on axis scales and tooltips.
- **Axes**: Start value axis at zero. Never truncate baseline unless showing variance index.

## §2. lineChart & areaChart
- **Markers**: Enable small circle markers if points represent discrete months or sparse observations.
- **Stepped lines**: Use stepped lines for interest rates, price tiers, or inventory levels.
- **Forecast bands**: Use lighter shade with 50% transparency for confidence intervals.

## §3. cardVisual (Modern KPI Card)
- **Callout Value**: 32–40pt bold. Limit precision to 1 decimal place (e.g. `$4.2M` not `$4,218,941.22`).
- **Variance Label**: Include direction icon (▲ / ▼) with semantic color (green/red or neutral).
- **Spacing**: Maintain at least 16px inner padding between card containers.

## §4. tableEx & pivotTable
- **Row Alternation**: Subtle 3–5% tint on alternating rows for scan readability.
- **Alignment**:
  - Text columns: Left-aligned.
  - Numeric columns & dates: Right-aligned.
- **Conditional Formatting**: Use data bars or background heatmaps on 1 primary metric only. Avoid color visual noise.

## §5. slicer
- **Orientation**: Prefer dropdown or tile button layout over long scrolling lists.
- **Header**: Clear, concise title indicating what filter is active.
