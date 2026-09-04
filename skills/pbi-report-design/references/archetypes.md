# Report Page Archetypes

Each report page must align to one of the five canonical archetypes.

## 1. Executive Summary
- **Audience**: C-Suite, VP, GM.
- **Target Scan Time**: 5–10 seconds.
- **Core Pattern**:
  - Top: 3–5 multi-metric KPI cards (`cardVisual`) with sparklines or period-over-period variance.
  - Middle: Primary driver trend (`lineChart` or `columnChart`) showing trajectory against target.
  - Bottom: High-level categorical breakdown (`barChart` or `waterfallChart`).
- **Layout Variants**:
  - Variant A (Standard): Top KPI ribbon (h:120px), Middle Trend (w:800px), Side Breakdown (w:420px).
  - Variant B (Dual-Pillar): Top KPI ribbon, Left Revenue stream, Right Cost/Margin stream.
  - Variant C (Scorecard): Grid of 6 KPI cards with embedded progress bars and variance banners.

## 2. Operational Monitor
- **Audience**: Operations Managers, Supervisors, Dispatchers.
- **Target Scan Time**: 30–60 seconds, refreshed frequently.
- **Core Pattern**:
  - Top: Exception alerts and queue counts.
  - Middle: Real-time work-in-progress status grid (`tableEx`).
  - Side: SLA status distribution (`barChart` or `donutChart`).
- **Layout Variants**:
  - Variant A: Left alert panel (w:320px), Center active items table (w:920px).
  - Variant B: Top alert cards, Center split active vs completed tables.

## 3. Analytical Canvas
- **Audience**: Business Analysts, Financial Controllers.
- **Target Scan Time**: 5–15 minutes (deep exploratory dive).
- **Core Pattern**:
  - Top/Side: Multi-select interactive slicers (`slicer`).
  - Center: Cross-filtering matrix / pivot grid (`pivotTable`).
  - Supporting: Scatter correlation (`scatterChart`) or decomposition tree.
- **Layout Variants**:
  - Variant A (Left Slicer Rail): Slicers w:240px, Main pivot grid w:680px, Detail chart w:320px.
  - Variant B (Top Filter Bar): Horizontal filter bar, Dual interactive charts, Bottom detail table.

## 4. Narrative Story
- **Audience**: Stakeholders, Board Members, External Clients.
- **Target Scan Time**: 2–5 minutes guided reading.
- **Core Pattern**:
  - Left-to-right or top-to-bottom step progression: "What happened?" → "Why?" → "Recommended action".
  - Annotations and callout banners accompanying charts.

## 5. Comparative Benchmark
- **Audience**: Product Managers, Sales Directors, Regional Heads.
- **Target Scan Time**: 1–3 minutes.
- **Core Pattern**:
  - Side-by-side performance comparisons across entities (Regions, Products, Teams).
  - Ranked bar charts (`barChart`), variance waterfalls, and quartile distribution bands.
