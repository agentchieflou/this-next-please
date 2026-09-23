---
name: pbi-custom-visual
description: "Route a custom chart (our own chart, pbiviz, D3, a visual the tenant or admin blocks, an organizational visual) to a delivery the tenant renders: native data labels, an SVG measure, or the organizational store. Then develop, bind, test, package, and import a pbiviz when one is the route."
---

# `pbi-custom-visual`

A `.pbiviz` renders for a report's viewers only where the tenant lets it, and most "custom" charts are a native
chart plus one technique. Route the delivery first; build a visual only when that is the route. Who controls
what, in Microsoft's words: `references/delivery-routes.md` §The tenant decides.

## Route the delivery (always, before any build)
1. Read the `pbi_custom_visuals` fact (AGENTS.md): what the tenant renders for this report's **viewers**, one of
   `allowed`, `certified-only`, `org-only`. Absent: run `ad-state ask "What does the production tenant render for this report's viewers?" --choice allowed --choice certified-only --choice org-only --assume "org-only: native routes first"`,
   say so in one line, CONTINUE. Once answered, add `- pbi_custom_visuals: <answer>` to AGENTS.md and commit it.
2. Write the requirement as what a viewer sees (`variance label at each bar end`), never as "a custom visual".
3. Take the first route that meets it; the order and why: `references/delivery-routes.md` §Choosing a route.
   - **Native**: no admin, renders on every tenant. N1 data-label fields, N2 a dynamic format string, N3 an SVG
     measure in a table: `references/delivery-routes.md` §Native routes. Hand off → `pbip-projection` (it leads
     to `tmdl-edit` for the measures, then `pbi-validate`). The label field is one Desktop gesture per visual,
     spelled out in the recipe. STOP here.
   - **A store visual the tenant already has** (the `pbi_org_visuals` fact, e.g. Deneb):
     `references/delivery-routes.md` §Organizational store.
   - **Our own `.pbiviz`, `allowed`**: the Loop.
   - **Our own `.pbiviz`, `certified-only` or `org-only`**: the Loop in Desktop (tenant settings govern the
     service, not Desktop), then the organizational store: `ad-state ask "Send the organizational-store request to the Fabric admin?" --want decision --about <name>`,
     its text from `references/delivery-routes.md` §Admin request. STOP until the store lists the visual.
4. Never tell anyone "there is no native alternative" without naming what the requirement needs that every
   route in `references/delivery-routes.md` §Native routes lacks. A worked case: §Bar-end variance labels.

## Loop (a .pbiviz is the route)
5. `ad-pbiviz doctor` checks Node.js, `pbiviz` and the HTTPS certificate.
   - **Stop condition**: certificate missing (`check: certificate, status: fail`) → STOP:
     `hint: run pbiviz --install-cert in your terminal, then re-invoke pbi-custom-visual`.
6. **Scaffold visual** (if new):
   ```bash
   ad-pbiviz new <name> [--template default|circlecard]
   ```
7. **Inspect roles**:
   ```bash
   ad-pbiviz roles <name>
   ```
8. **Bind data roles to model fields**:
   Map each declared role to projected model fields:
   ```bash
   ad-pbiviz bind <name> --pbip <dir> --role category='Sales'[Product] --role measure=[Total Sales]
   ```
   - **Stop condition**: If `bind` returns kind mismatch error (`Grouping` vs `Measure`), STOP:
     adjust role bindings to match field kinds.
9. **Serve locally**:
   ```bash
   ad-pbiviz dev <name> --pbip <dir>
   ```
   - In Desktop: *Format -> Report settings -> Develop a visual: ON*.
   - Add Developer Visual to the canvas.
10. **Iterate & Verify**:
   - Edit TypeScript code under `visuals/<name>/src/`.
   - Reload running Desktop: `ad-pbip desktop reload --pid <pid>`.
   - Capture screenshot & verify crop: `ad-pbip screenshot --pid <pid> --visual <name>`.
11. **Package & Import**:
   ```bash
   ad-pbiviz package <name> [--bump patch|minor]
   ad-pbiviz import <name> --pbip <dir> --page <page_name>
   ```
   - Organizational store: the admin uploads `visuals/<name>/dist/*.pbiviz`; then in Desktop replace the
     instance with the *My organization* copy, so the report stops carrying the file.
12. **Validate**: `ad-pbip check <pbip>` must show zero custom-visual errors; `custom-visual-tenant-blocked` means
    viewers would get an error in the visual's place: back to step 3.
13. Finish, invoke `state-update`, return to `router`.
