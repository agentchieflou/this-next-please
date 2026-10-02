---
name: pbi-report-design
description: "Design Power BI report page archetypes, visual hierarchy, layout contracts, and space audits without direct PBIR authoring."
---

# pbi-report-design: Report Design System & Layout Contracts

Designs visual hierarchy, archetypes, and layout contracts for report pages.
This skill produces only the `design_brief:` block and never runs an `ad-pbip` write verb.

## Design Protocol
1. **Tone & Signature**:
   - Establish emotional tone: confident, neutral, analytical.
   - Pick 1 primary brand color and 1 accent; use neutrals for structural lines and containers.
   - Reference `references/theme-base.json` for baseline token defaults and per-type safeguards. It is a theme file, not prose: it has no sections, and you load it whole or not at all.
   - It is a custom theme, layered on the report's base theme. Reports new in Desktop 2.157 start on the Fluent 2 base
     theme (titles on, rounded padding, 1920x1080 pages), which no longer overrides fonts: the theme's text settings
     reach every visual. Lay out new pages for the canvas the report's existing pages use.
2. **Page Archetype Selection**:
   - Match each page to one of the 5 canonical archetypes, then read only the one you picked — `references/archetypes.md` §<that archetype>:
     - **Executive Summary**: 5-second scan, headline KPI strip, primary trend, high-level breakdown.
     - **Operational Monitor**: Real-time / intraday state, threshold alerts, status grids.
     - **Analytical Canvas**: Multi-dimensional exploration, slicers, cross-filtering matrices.
     - **Narrative Story**: Stepped progression from context to detail to action.
     - **Comparative Benchmark**: Side-by-side variance, budget vs actual, ranked percentiles.
3. **Chart Selection & Encoding**:
   - Follow `references/chart-selection.md` §Question → Visual Type Mapping to pick the type, then §Encoding Hierarchy to encode it.
   - Slicers: pick the type from `references/chart-selection.md` §Slicer Selection (dropdown, list, buttons, text, date picker).
   - Never place a deprecated type (`map`, `filledMap`, `multiRowCard`, `qnaVisual`, ...): `ad-pbip catalog list` marks them `legacy`.
   - Always sample data grain and cardinality before choosing chart types.
   - Sort rules, labels and axes for the type you picked: `references/visual-cookbook.md` §<that visual type> — one section per type, not the whole book.
4. **Layout Contract & Space Audit**:
   - Build 12-column grid regions: header, KPI strip, primary, secondary.
   - Assign exact non-overlapping pixel bounding boxes (`x, y, width, height`).
   - Run space audit: verify all regions + white space sum to $\le 100\%$.
   - Prohibit bare single-value cards in dominant regions (> 30% area).
5. **Output**:
   - Provide the completed `design_brief:` YAML structure to update `.agent/brief/<KEY>-report-spec.md`.
