---
name: tmdl-edit
description: "Use for any change to a Power BI semantic model stored as TMDL — add or fix a measure, calculated column, format string, relationship, hierarchy, partition M. Mechanizes the layout rules Luna gets wrong (tabs, expression blocks, quoting) and always ends by validating the report against the model."
---
# TMDL edit (backend change with a mandatory frontend check)

Inputs: `pbip_path` / `tmdl_path` facts. Prereq: `pbip-projection` ran this session (you know table, object names and where they are used).

Tool tiers:
- **Tier 1 (Live TOM)**: `ad-pbip model apply --pid <pid>|--server <host:port> --ops <ops.json> [--save]` writes changes directly into the running Desktop model through TOM; `--save` triggers session save and waits for TMDL to settle.
- **Tier 2 (TMDL writer)**: `ad-pbip model apply --model <definition> --ops <ops.json>` applies the same declarative op list directly to TMDL files with mechanical indentation and runs `ad-pbip lint`.
- No third tier: if both fail, log `friction-log` type `contract`.

1. Impact first: `ad-pbip refs --table <T> --column <C>` (or `--measure <M>`). Every visual, filter, measure, relationship, sort-by and hierarchy listed there breaks if you rename or remove the object. Renames: change the model **and** every listed `visual.json`/filter, or stop and `friction-log` type `ambiguity`.
2. Measures: `ad-pbip measure set --table <T> --name "<Measure>" --expr-file .agent/dax/<KEY>-<measure>.dax [--format-string "#,##0"] [--display-folder KPIs] [--description "..."]` (thin alias of `model apply`). Never hand-write the block. It inserts/replaces with Desktop layout (fenced ``` body, properties one level under, no lineageTag — Desktop assigns one on save) and refuses edits that would leave the file invalid. `references/tmdl-syntax.md` §Multi-line expressions is why hand-writing one goes wrong.
3. Model edits (columns, relationships, hierarchies, calc groups, partitions, roles): run `ad-pbip model apply --ops <ops.json>` using supported op types:
   - `measure.set`: `{op: "measure.set", table, name, expression, formatString, displayFolder, description, isHidden}`
   - `column.calc.set`: `{op: "column.calc.set", table, name, expression, dataType, formatString, isHidden, description}`
   - `relationship.set`: `{op: "relationship.set", fromTable, fromColumn, toTable, toColumn, cardinality, crossFilteringBehavior, isActive}`
   - `hierarchy.set`: `{op: "hierarchy.set", table, name, levels: [{name, column}], isHidden, description}`
   - `calcgroup.set`: `{op: "calcgroup.set", table, name, precedence, items: [{name, expression, formatStringExpression, ordinal}]}`
   - `fieldparam.set`: `{op: "fieldparam.set", table, name, fields: [ref1, ref2, ...]}`
   - `role.set`: `{op: "role.set", name, modelPermission, tablePermissions: [{table, filterExpression}]}`
   - `partition.set`: `{op: "partition.set", table, name, mode, source: {type, query}}`
   - `perspective.set`: `{op: "perspective.set", name, tables: [...]}`
   - `object.describe`: `{op: "object.describe", table, objectType, name, description}`
   - `object.hide`: `{op: "object.hide", table, objectType, name, isHidden}`
   - `object.delete`: `{op: "object.delete", table, objectType, name}`
   For review and verification — not manual authoring — read only the part that matches the edit: `references/tmdl-syntax.md` §Columns and calculated columns for `column.calc.set`, §Relationships for `relationship.set`, §Hierarchies for `hierarchy.set`, §Partitions for `partition.set`, §Multi-line expressions for any DAX or M body.
4. `ad-pbip check` (structure) — must be `ok: true`. Then `ad-pbip project --force` so the projection matches the edit.
5. Commit the TMDL change on the ticket branch (`bitbucket-pr` step 3 style commit message: `feat: <KEY> <what>`). Do not open Desktop before committing; its save rewrites files.
6. Hand off → `pbi-validate` (mandatory; it runs Tabular Editor for real DAX errors and evaluates the affected visuals). Never skip it, never deploy from here.

§ When a lint error or a TE2 error is not obvious: `references/tmdl-syntax.md` §Pitfalls checklist — every item there is one of those errors. §Worked examples has one of each edit type.

