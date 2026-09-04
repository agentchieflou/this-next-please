---
name: pbi-custom-visual
description: "Develop, bind, test, package, and import custom Power BI visual (pbiviz)."
---

# `pbi-custom-visual`

Mechanical development loop for Power BI custom visual packages using `ad-pbiviz`.

## Prerequisites & Doctor
1. Run `ad-pbiviz doctor` to verify Node.js, `pbiviz`, and HTTPS certificate.
   - **Stop condition**: If certificate missing (`check: certificate, status: fail`), STOP:
     `hint: run pbiviz --install-cert in your terminal, then re-invoke pbi-custom-visual`.

## Loop
2. **Scaffold visual** (if new):
   ```bash
   ad-pbiviz new <name> [--template default|circlecard]
   ```
3. **Inspect roles**:
   ```bash
   ad-pbiviz roles <name>
   ```
4. **Bind data roles to model fields**:
   Map each declared role to projected model fields:
   ```bash
   ad-pbiviz bind <name> --pbip <dir> --role category='Sales'[Product] --role measure=[Total Sales]
   ```
   - **Stop condition**: If `bind` returns kind mismatch error (`Grouping` vs `Measure`), STOP:
     adjust role bindings to match field kinds.
5. **Serve locally**:
   ```bash
   ad-pbiviz dev <name> --pbip <dir>
   ```
   - In Desktop: *Format -> Report settings -> Develop a visual: ON*.
   - Add Developer Visual to the canvas.
6. **Iterate & Verify**:
   - Edit TypeScript code under `visuals/<name>/src/`.
   - Reload running Desktop: `ad-pbip desktop reload --pid <pid>`.
   - Capture screenshot & verify crop: `ad-pbip screenshot --pid <pid> --visual <name>`.
7. **Package & Import**:
   ```bash
   ad-pbiviz package <name> [--bump patch|minor]
   ad-pbiviz import <name> --pbip <dir> --page <page_name>
   ```
8. **Validate**:
   Run `ad-pbip check <pbip>` to ensure zero custom-visual errors.
9. Finish, invoke `state-update`, return to `router`.
