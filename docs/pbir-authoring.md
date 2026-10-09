# PBIR Authoring Parity Reference

This document outlines the mechanical authoring commands, the PBIR anti-pattern lint rules, and the schema update procedure for Power BI reports (`.pbip`).

## 1. Authoring Verbs

| Command | Arguments / Flags | Description |
| :--- | :--- | :--- |
| `ad-pbip schema update` | `[--pretty]` | Validates vendored schemas against `VERSION` metadata and reports visual types and properties. |
| `ad-pbip catalog list` | `[--pretty]` | Lists all available visual types, required roles, and legacy deprecation status. |
| `ad-pbip catalog describe` | `<visualType> [--pretty]` | Describes roles, min/max cardinality, and allowed data kinds (`Grouping`, `Measure`). |
| `ad-pbip catalog formatting` | `[<visualType>] [--object <o>] [--property <p>] [--search <s>]` | Lists formatting properties, types (`string`, `bool`, `color`, `number`, `enum`), valid values, and the `location` each object is written to. |
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
| `ad-pbip visual set` | `<pbip> --visual <id> --property <obj.prop>=<val> [--series <field>]` | Updates a position (`position.x`, `position.width`) or formatting property, where and as Desktop saves it: chart objects (`labels`, `legend`, `categoryAxis`, `valueAxis`) in `visual.objects`, container objects (`title`, `subTitle`, `background`, `border`, `dropShadow`, `padding`, `visualHeader`) in `visual.visualContainerObjects`. Values are Desktop literals (`true`, `12D`, `'center'`, `'#118DFF'` in `solid.color`). `labels.dynamicLabelTitle`, `dynamicLabelValue` and `dynamicLabelDetail` take a field (`[Measure]`, `'Table'[Measure]` or `Min('Table'[Column])`), checked against the model. `--series` (a labels setting only) applies it to one of the visual's fields, by queryRef, display name or measure name. |
| `ad-pbip visual set` (a bar-end label) | on a `clusteredBarChart` or `clusteredColumnChart`: `labels.show=true`; `--series Average labels.show=false`; `--series Recent labels.labelPosition=OutsideEnd`; `--series Recent labels.dynamicLabelValue=[Variance Label]` | Desktop's data-label *Apply settings to* a series, *Position: Outside end*, and *Value* carrying another measure. For a second line instead: `enableDetailDataLabel=true`, `detailContentType=Custom`, `dynamicLabelDetail=[Variance Label]`. |
| `ad-pbip visual remove` | `<pbip> --visual <id>` | Removes visual directory from page. |
| `ad-pbip filter set` | `<pbip> --scope report\|page\|visual [--page <p>] [--visual <id>] --field <ref> (--values\|--between\|--top)` | Creates canonical filter using `SourceRef.Source` alias in `Where` condition. |
| `ad-pbip bookmark add` | `<pbip> --name "<name>" --page <p> [--visuals <id1,id2>]` | Creates bookmark capture in `definition/bookmarks/`. |
| `ad-pbip pbir patch` | `<pbip> (--file <definition/...> \| --page <p> [--visual <id>]) --set <json-pointer>=<json-value> [--set ...] [--unset <pointer> ...] [--dry-run]` | Sets or removes any property of one PBIR file, written only when the result validates against the file's own `$schema` (section 4). |

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
3. The `formatting` section of `visuals.json` names objects and properties as Power BI Desktop saves them, and each object's `location` says which of `visual.objects` and `visual.visualContainerObjects` holds it. `tests/test_pbir_visual_set.py` checks both against visuals Desktop saved, in `tests/fixtures/pbip/desktop-saved/`: an object added to the catalog is pinned there, from a Desktop-saved file that carries it.

## 4. `pbir patch`: any property, checked instead of banned

`ad-pbip pbir patch` is the verb for a property no other verb covers. It takes one file (`--file`, relative to the
`.Report` folder; `--page` for its `page.json`; `--page --visual` or `--visual` for a `visual.json`, found the way
`visual set` finds it), applies each `--set <json-pointer>=<json-value>` (RFC 6901; the value is JSON when it parses,
text otherwise; a missing intermediate object is created; `-` appends to an array) and `--unset <pointer>` in memory,
validates the result against the `$schema` the file names, vendored under `agentdata/pbip/schema/fabric/`, and writes
only when it passes. `--dry-run` reports the same with `written: false`.

What it refuses (exit 2, `ok: false`, `fail: <code>`, the file untouched):

| `fail` | What | Why |
| :--- | :--- | :--- |
| `protected_pointer` | a pointer whose first segment is `$schema` or `name` | `name` is what `pages.json`, bookmarks and cross-highlighting bind to; `$schema` is the version the operator's Desktop reads, chosen by the verb that adds a file. |
| `protected_file` | `.platform`, `definition.pbir`, `localSettings.json`, `version.json`, anything outside `definition/` | the project's identity and Desktop's own stamps, none of which names a vendored schema to check an edit against. |
| `schema_invalid` | the patched document violates its schema; `errors` lists `<json path>: <message>` | the file would not open in Desktop 2.157. Fix the property named, or set it in Desktop and read the file it saves. |
| `schema_unvendored` | the file has no `$schema`, or one that is not vendored | nothing to check against; `ad-pbip schema update` vendors Desktop's set. |
| `schema_checker_missing` | jsonschema is not installed | the patch is allowed only because it validates; `pip install "agentdata[pbi]"`. |

`ad-pbip check` runs the same validation on every file under `definition/` naming a vendored `$schema` and reports
each violation as `schema-invalid` (up to 20 per file); without jsonschema it says so once (`schema-check-skipped`).
