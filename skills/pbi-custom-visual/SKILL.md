---
name: pbi-custom-visual
description: "Route a custom chart (our own chart, pbiviz, D3, a visual the tenant or admin blocks, a label or chart native Power BI seems unable to draw) through native Power BI first, then Microsoft-certified visuals customized to the limit (Deneb), and log a proven need as an AppSource candidate. Never builds or ships a non-certified custom visual."
---

# `pbi-custom-visual`

A custom visual the tenant blocked reached production once, and every viewer got an error where the chart
belonged. So this skill never builds a non-certified visual to deliver a report. It exhausts native Power BI,
then the Microsoft-certified visuals, which it may customize without limit; a need that survives both is
logged as a candidate for AppSource, not built. Who controls what, in Microsoft's words:
`references/delivery-routes.md` §The tenant decides.

## Prove it before you say "can't"
1. Read the `pbi_custom_visuals` fact (AGENTS.md): what the tenant renders for this report's **viewers**, one of
   `allowed`, `certified-only`, `org-only`. Absent: run `ad-state ask "What does the production tenant render for this report's viewers?" --choice allowed --choice certified-only --choice org-only --assume "org-only: native and organizational-store visuals only"`,
   say so in one line, CONTINUE. Once answered, add `- pbi_custom_visuals: <answer>` to AGENTS.md and commit it.
2. Write the requirement as what a viewer sees (`variance label at each bar end`), never as "a custom visual".
3. **Native**, in order: N1 to N7 in `references/delivery-routes.md` §Native routes. The first that meets it is
   the route: hand off → `pbip-projection` (it leads to `tmdl-edit` for the measures, then `pbi-validate`).
   STOP here. For each route that falls short, note one line: what the requirement needs that the route lacks.
4. **Certified, to the limit**: `references/delivery-routes.md` §Certified visuals. Deneb (C1) draws any Vega or
   Vega-Lite specification, so it answers nearly every "native can't". Write the specification, then
   `ad-pbip visual deneb <pbip> --page <p> --spec <file> --fields <f1> <f2>`; commit; hand off → `pbi-validate`.
   It renders where the organizational store carries it (`pbi_org_visuals`), on any tenant; or from AppSource on
   an `allowed` or `certified-only` tenant, once its GUID is in `pbi_certified_visuals`. On an `org-only` tenant
   without it in the store: `ad-state ask "Ask the Fabric admin to add Deneb to the organizational store?" --want decision`,
   with the text in `references/delivery-routes.md` §Admin request. STOP until it is there.
   C2 is any other Microsoft-certified visual: check its badge, record its GUID in `pbi_certified_visuals`.
5. **Nothing meets it: a candidate, never a build.** `ad-pbiviz candidate "<requirement>" --tried N1="<what N1 lacks>"`,
   with one `--tried` for every route N1 to N7 and C1 to C2, each naming what that route lacks. It refuses a
   missing or empty reason. Then `ad-state ask "<requirement> is logged as an AppSource candidate: ship the closest route meanwhile, or wait?" --choice closest --choice wait`.
   STOP. What happens to a candidate: `references/delivery-routes.md` §Candidates.
6. Never say or write "can't", "not possible natively" or "needs a custom visual" without the path that step 5
   printed. The case that started this, done both ways: `references/delivery-routes.md` §Bar-end variance labels.

## Loop: only for a candidate the operator chose to build for AppSource
7. The operator's own words (this prompt or the brief) name a logged candidate and AppSource. Anything else: STOP,
   back to step 5. The package goes to AppSource and its certification review, never into a report to ship.
8. `ad-pbiviz doctor` checks Node.js, `pbiviz` and the HTTPS certificate.
   - **Stop condition**: certificate missing (`check: certificate, status: fail`) → STOP:
     `hint: run pbiviz --install-cert in your terminal, then re-invoke pbi-custom-visual`.
9. **Scaffold visual** (if new):
   ```bash
   ad-pbiviz new <name> [--template default|circlecard]
   ```
10. **Inspect roles**:
   ```bash
   ad-pbiviz roles <name>
   ```
11. **Bind data roles to model fields**:
   ```bash
   ad-pbiviz bind <name> --pbip <dir> --role category='Sales'[Product] --role measure=[Total Sales]
   ```
   - **Stop condition**: If `bind` returns kind mismatch error (`Grouping` vs `Measure`), STOP:
     adjust role bindings to match field kinds.
12. **Serve locally**:
   ```bash
   ad-pbiviz dev <name> --pbip <dir>
   ```
   - In Desktop: *Format -> Report settings -> Develop a visual: ON*.
   - Add Developer Visual to the canvas.
13. **Iterate & Verify**:
   - Edit TypeScript code under `visuals/<name>/src/`.
   - Reload running Desktop: `ad-pbip desktop reload --pid <pid>`.
   - Capture screenshot & verify crop: `ad-pbip screenshot --pid <pid> --visual <name>`.
14. **Package** for the AppSource submission:
   ```bash
   ad-pbiviz package <name> [--bump patch|minor]
   ```
   `ad-pbiviz import` puts it in a report for a Desktop test only: `ad-pbip check` and `ad-pbi publish report`
   refuse a file visual wherever the tenant does not render one.
15. Finish, invoke `state-update`, return to `router`.
