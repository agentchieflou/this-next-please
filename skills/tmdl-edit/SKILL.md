---
name: tmdl-edit
description: Use for any change to a Power BI semantic model stored as TMDL — add or fix a measure, calculated column, format string, relationship, hierarchy, partition M. Mechanizes the layout rules Luna gets wrong (tabs, expression blocks, quoting) and always ends by validating the report against the model.
---
# TMDL edit (backend change with a mandatory frontend check)

Inputs: `pbip_path` / `tmdl_path` facts. Prereq: `pbip-projection` ran this session (you know table, object names and where they are used).

1. Impact first: `ad-pbip refs --table <T> --column <C>` (or `--measure <M>`). Every visual, filter, measure, relationship, sort-by and hierarchy listed there breaks if you rename or remove the object. Renames: change the TMDL **and** every listed `visual.json`/filter, or stop and `friction-log` type `ambiguity`.
2. Measures → never hand-write the block. `ad-pbip measure set --table <T> --name "<Measure>" --expr-file .agent/dax/<KEY>-<measure>.dax [--format-string "#,##0"] [--display-folder KPIs] [--description "..."]`. It inserts/replaces with Desktop layout (fenced ``` body, properties one level under, no lineageTag — Desktop assigns one on save) and refuses edits that would leave the file invalid.
3. Other edits (columns, relationships, hierarchies, partitions): follow `references/tmdl-syntax.md` exactly — one TAB per level, `key: value` properties, bare keywords for true booleans, single quotes around names with spaces or `. = : '` (also in `sortByColumn: 'Week Day (#)'`, `fromColumn: Sales.'Order Date'`), multi-line expressions in a ``` block indented two levels under the declaration, `///` descriptions above the object, no `//` comments, new tables need `ref table` in `model.tmdl`. Then `ad-pbip lint <definition folder>`; fix every `error` row.
4. `ad-pbip check` (structure) — must be `ok: true`. Then `ad-pbip project --force` so the projection matches the edit.
5. Commit the TMDL change on the ticket branch (`bitbucket-pr` step 3 style commit message: `feat: <KEY> <what>`). Do not open Desktop before committing; its save rewrites files.
6. Hand off → `pbi-validate` (mandatory; it runs Tabular Editor for real DAX errors and evaluates the affected visuals). Never skip it, never deploy from here.

Reference: `references/tmdl-syntax.md` (syntax rules, Desktop conventions, worked examples for each edit type, pitfalls).
