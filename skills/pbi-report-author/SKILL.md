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
     (fields fill the type's roles in `catalog describe` order; name every measure's table: `'Sales'[Total Sales]`,
     never a bare `[Total Sales]`, which writes a field the visual schema rejects)
   - Formatting: `ad-pbip visual set <pbip> --visual <id> --property <object.property>=<value>`
   - One series' data label: add `--series <measure>`; a label that shows another field: `--property labels.dynamicLabelValue=[Measure]`
   - Filters: `ad-pbip filter set <pbip> --scope report|page|visual [--page <p>] [--visual <id>] --field <ref> --values a,b`
   - Bookmarks: `ad-pbip bookmark add <pbip> --name "<name>" --page <p> [--visuals <id1,id2>]`
   - Themes: `ad-pbip theme set <pbip> --file <theme.json>`
   - Any other property: `ad-pbip pbir patch <pbip> (--file <definition/...> | --page <p> [--visual <id>]) --set <json-pointer>=<json-value> [--unset <pointer>] [--dry-run]`
     (RFC 6901 pointers: `/position/x=300`, `/visual/visualContainerObjects/title/-={...}` appends; a missing object is created)
3. **Validate**: Run pre-flight lint:
   - `ad-pbip check <pbip>`: Must pass with 0 errors. Checks schema rules, field references, and anti-patterns.
4. **Reload & Verify**:
   - `ad-pbip desktop reload --pid <pid> --report-only`: Reload the running Desktop after PBIR-only edits (Desktop Bridge `file.reload`; without `--report-only` it re-applies the model too — use that, then `tmdl-edit` step 4b, only when TMDL changed). It refuses while Desktop has unsaved changes: ask the human to save; never pass `--discard` on your own.
   - `ad-pbip screenshot --pid <pid> --page <p> [--visual <id>]`: Visually inspect rendered result.
   - `ad-pbip screenshot --compare <before.png> <after.png>`: Confirm intentional visual diff.
5. **Commit**: Format Conventional Commit (`feat:`, `fix:`).

## Power BI Desktop 2.157 (PBIR)
- **Schema versions**: a new page, visual or bookmark copies the `$schema` of a file of its kind already in the
  project, Desktop's choice; a kind the project has none of gets what Desktop 2.157 writes (page 2.1.0,
  visualContainer 2.12.0, bookmark 2.1.0, pagesMetadata 1.1.0, bookmarksMetadata 1.0.0). The command's `schema`
  field says which version and why (`copied from <file>` or `2.157 default`). Never edit a `$schema` by hand.
- **Slicers**: `slicer` (classic: dropdown, list, between, date picker are its `data.mode`, which only Desktop sets
  today), `listSlicer` (a list; several fields make a hierarchy; then tooltip measures), `advancedSlicerVisual`
  (the button slicer: one column, then an optional measure on each tile), `textSlicer` (one text column searched by
  typing). A date picker or a mode other than Desktop's default: `pbir patch` the `data.mode` Desktop saves, copying
  the shape from a slicer Desktop saved; friction-log `type: contract` only when the schema refuses it.
- **Desktop only**: `textbox`, `image`, `shape`, `actionButton` and `shapeMap` are in the catalog, but `visual add`
  refuses them: their content (text, source, shape, action, role names) is nothing `visual add` can fill. Add them in
  Desktop. Once present, their text, source, shape and action are `pbir patch` edits: `--dry-run` first, with the
  property path read off the file Desktop saved.
- **Bookmarks** land where Desktop reads them: `bookmarks/<name>.bookmark.json`, listed in `bookmarks/bookmarks.json`.

## Cardinal Rule: Verbs first, `pbir patch` second, never raw
- **Never** create or edit `visual.json` (or any PBIR file) by hand or from memory.
- A property no verb covers is set with `ad-pbip pbir patch`. It validates the result against the file's own
  `$schema` (Desktop 2.157's, vendored) and refuses what would not open: `fail: schema_invalid` names the property
  and its JSON path, and the file is untouched. It also refuses the `$schema` and `name` pointers, `.platform`,
  `definition.pbir`, `version.json`, `localSettings.json` and anything outside `definition/`.
- Only a patch the schema refuses is a missing verb: invoke `friction-log` with `type: contract` naming the property
  and the `errors` line. A property the schema accepts is a `pbir patch`, never a friction log.
- Never use legacy or deprecated visual types; `visual add` refuses them and `ad-pbip check` warns on each one
  already there: `card`/`multiRowCard` → `cardVisual`, `table` → `tableEx`, `matrix` → `pivotTable`,
  `map`/`filledMap` (Bing Maps, being retired) → `azureMap` (or `shapeMap` for custom regions), `qnaVisual` (Q&A,
  deprecated December 2026) → no visual: Power BI Copilot answers questions instead.
- Ensure all visual positions remain inside page canvas bounds (`width`x`height`).
- In filters, conditions must reference the table alias via `SourceRef.Source`, never `SourceRef.Entity`.
