---
name: pbi-report-author
description: "Author PBIR report pages, visuals, filters, bookmarks, and themes with schema validation and anti-pattern linting."
---

# pbi-report-author: Schema-Driven PBIR Authoring

Author Power BI reports mechanically via `ad-pbip` verbs without handwriting visual JSON.

## The Authoring Loop
1. **Catalog**: Query visual roles and formatting properties before editing:
   - `ad-pbip catalog list`: Inspect supported visual types and modern replacements.
   - `ad-pbip catalog describe <visualType>`: View role requirements and cardinality.
   - `ad-pbip catalog formatting <visualType> [--object <obj>] [--search <text>]`: View property paths.
2. **Mechanical Edit**: Apply changes via schema-validated CLI commands:
   - Pages: `ad-pbip page add <pbip> --name "<name>" [--after <p>]`
   - Visuals: `ad-pbip visual add <pbip> --page <p> --type <type> --title "<t>" --fields <f1> <f2> ... --position x,y,w,h`
   - Formatting: `ad-pbip visual set <pbip> --visual <id> --property <object.property>=<value>`
   - Filters: `ad-pbip filter set <pbip> --scope report|page|visual [--page <p>] [--visual <id>] --field <ref> --values a,b`
   - Bookmarks: `ad-pbip bookmark add <pbip> --name "<name>" --page <p> [--visuals <id1,id2>]`
   - Themes: `ad-pbip theme set <pbip> --file <theme.json>`
3. **Validate**: Run pre-flight lint:
   - `ad-pbip check <pbip>`: Must pass with 0 errors. Checks schema rules, field references, and anti-patterns.
4. **Reload & Verify**:
   - `ad-pbip desktop reload --pid <pid>`: Trigger live refresh in running Desktop.
   - `ad-pbip screenshot --pid <pid> --page <p> [--visual <id>]`: Visually inspect rendered result.
   - `ad-pbip screenshot --compare <before.png> <after.png>`: Confirm intentional visual diff.
5. **Commit**: Format Conventional Commit (`feat:`, `fix:`).

## Cardinal Rule: Never Hand-Write Visual JSON
- **Never** manually create or edit `visual.json` files from memory.
- If an authoring verb is missing or cannot express the requested layout/property:
  Invoke `friction-log` with `type: contract` naming the missing verb or schema property, then stop.
- Never use legacy visual types (`card`, `table`, `matrix`, `map`); use `cardVisual`, `tableEx`, `pivotTable`, `azureMap`.
- Ensure all visual positions remain inside page canvas bounds (`width`x`height`).
- In filters, conditions must reference the table alias via `SourceRef.Source`, never `SourceRef.Entity`.
