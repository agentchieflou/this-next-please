# PBIR Authoring Parity Reference

This document outlines the mechanical authoring commands, the PBIR anti-pattern lint rules, and the schema update procedure for Power BI reports (`.pbip`).

## 1. Authoring Verbs

| Command | Arguments / Flags | Description |
| :--- | :--- | :--- |
| `ad-pbip schema update` | `[--pretty]` | Validates vendored schemas against `VERSION` metadata and reports visual types and properties. |
| `ad-pbip catalog list` | `[--pretty]` | Lists all available visual types, required roles, and legacy deprecation status. |
| `ad-pbip catalog describe` | `<visualType> [--pretty]` | Describes roles, min/max cardinality, and allowed data kinds (`Grouping`, `Measure`). |
| `ad-pbip catalog formatting` | `[<visualType>] [--object <o>] [--property <p>] [--search <s>]` | Lists formatting properties, types (`string`, `bool`, `color`, `number`, `enum`), and valid values. |
| `ad-pbip expr encode` | `<fieldRef>` | Converts readable field references (e.g. `'Sales'[Amount]`, `Sum('Sales'[Qty])`) into JSON `QueryExpressionContainer`. |
| `ad-pbip expr decode` | `<json>` | Decodes JSON `QueryExpressionContainer` into readable field reference. |
| `ad-pbip theme shade` | `--color <hex> --pct <float>` | Shades (darkens, negative %) or tints (lightens, positive %) a hex color. |
| `ad-pbip theme set` | `<pbip> --file <theme.json>` | Registers a custom theme in `report.json` and copies it to `StaticResources/RegisteredResources/`. |
| `ad-pbip preview pages` | `[<pbip>]` | Lists all pages with dimensions and visual counts. |
| `ad-pbip preview visuals` | `[<pbip>]` | Lists all visuals with coordinates, dimensions, types, and field counts. |
| `ad-pbip preview filters` | `[<pbip>]` | Lists all filters across report, page, and visual scopes. |
| `ad-pbip preview themes` | `[<pbip>]` | Lists base and custom theme registrations. |
| `ad-pbip page add` | `<pbip> --name "<name>" [--after <p>] [--width <w>] [--height <h>]` | Adds page folder, `page.json`, and updates `pages.json` `pageOrder`. |
| `ad-pbip page remove` | `<pbip> --page <page>` | Deletes page directory and cleans up `pages.json`. |
| `ad-pbip page move` | `<pbip> --page <page> [--after <p2>]` | Reorders page in `pages.json` `pageOrder`. |
| `ad-pbip visual add` | `<pbip> --page <p> --type <type> [--title <t>] [--fields ...] [--position x,y,w,h]` | Adds visual with fresh 20-hex ID, schema-ordered roles, and canvas boundary checks. |
| `ad-pbip visual set` | `<pbip> --visual <id> --property <obj.prop>=<val>` | Updates formatting or position (`position.x`, `position.width`) property. |
| `ad-pbip visual remove` | `<pbip> --visual <id>` | Removes visual directory from page. |
| `ad-pbip filter set` | `<pbip> --scope report\|page\|visual [--page <p>] [--visual <id>] --field <ref> (--values\|--between\|--top)` | Creates canonical filter using `SourceRef.Source` alias in `Where` condition. |
| `ad-pbip bookmark add` | `<pbip> --name "<name>" --page <p> [--visuals <id1,id2>]` | Creates bookmark capture in `definition/bookmarks/`. |

---

## 2. Anti-Pattern Lint Reference

The `ad-pbip check` command inspects both TMDL models and PBIR report definitions. It flags the following anti-patterns:

| Lint Kind | Severity | Why It Breaks / Rationale |
| :--- | :--- | :--- |
| `filter-entity-vs-source` | Error | Power BI Desktop's internal query processor expects filter `Where` conditions to bind to an alias defined in `From[]` via `{"SourceRef": {"Source": "<alias>"}}`. Using `{"SourceRef": {"Entity": "<table-name>"}}` silently causes the filter to be ignored or crashes visual evaluation. |
| `page-not-in-pages-json` | Error | If a page folder exists under `definition/pages/` but is not in `pages.json` `pageOrder`, Power BI Desktop will fail to load the page tab or throw a deserialization error. Conversely, dangling entries in `pages.json` cause missing section crashes. |
| `duplicate-visual-id` | Error | Visual IDs must be globally unique 20-hex strings across the entire report. Duplicated IDs corrupt bookmark bindings and cross-highlighting states. |
| `duplicate-filter-id` | Error | Filter IDs must be unique (24-hex formatted `Filter...`). Duplicates cause filter state overwrites. |
| `visualcalc-missing-nativequeryref` | Warning | Visual calculations require `nativeQueryRef` alongside `queryRef` in projection dictionaries; missing this breaks DAX visual calculation evaluation. |
| `legacy-visual-type` | Warning | Visual types `card`, `table`, `matrix`, and `map` are deprecated legacy visuals that miss modern formatting controls and container styling. Use `cardVisual`, `tableEx`, `pivotTable`, and `azureMap`. |
| `position-off-canvas` | Warning | Visual coordinates extending beyond canvas boundaries (`x + width > page.width` or `y + height > page.height`) render clipped or completely invisible on view mode. |
| `overlap` | Warning | Overlapping non-hidden visuals cause z-order conflicts and unintended obstruction of data points. |

---

## 3. Schema Update Procedure

The PBIR schemas and visual catalogs are vendored as static data under `agentdata/pbip/schema/`:
- `LICENSE`: Microsoft MIT License.
- `VERSION`: Upstream commit SHA and format versions (`pbir_format_version: 2.0.0`, `pbir_definition_version: 4.0`).
- Schema files: `report.json`, `page.json`, `pagesMetadata.json`, `visualContainer.json`, `filterConfig.json`, `bookmark.json`, `visuals.json`.

To verify or update:
1. Run `ad-pbip schema update`.
2. To update upstream definitions, update the schema JSON files in `agentdata/pbip/schema/`, update `VERSION` with the new commit SHA, and run `pytest tests/test_pbir_author.py`.
