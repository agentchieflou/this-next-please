# TMDL syntax — how Power BI Desktop writes it, how to edit it by hand

Verified on Microsoft's sample PBIP (round-tripped through Desktop) and Microsoft's TMDL guidelines. `ad-pbip lint` enforces
the rules marked ⚑; `ad-pbip check --te2` (Tabular Editor 2) is the authoritative parse + DAX check.

## Structure
- `<type> <Name>` declares an object; `<type> <Name> = <expression>` for objects whose default property is an expression:
  `measure`, `partition`, `expression`, `function`, calculated `column`, `calculationItem`, `tablePermission`, `annotation X = value`,
  `changedProperty = IsHidden`, `extendedProperty X =` (JSON block).
- Properties are `key: value` one level under the object. Booleans are **bare keywords when true** (`isHidden`, `isKey`,
  `discourageImplicitMeasures`); `false` is written `isAvailableInMdx: false`.
- ⚑ Indentation: **one TAB per level**. Spaces are legal only if the whole file uses them consistently; never mix.
- ⚑ Names containing a space or `. = : '` are single-quoted: `measure 'Sales Amount (LY)'`, `column 'Order Date'`,
  `table 'Smart Calcs'`. The same applies to references: `sortByColumn: 'Week Day (#)'`, `fromColumn: Sales.'Order Date'`,
  `level Country` … `column: 'Country Name'`, `ref table 'Smart Calcs'`.
- Descriptions: `///` lines directly above the object (several lines = several `///`). ⚑ `//` comments do not exist in TMDL
  (only inside DAX/M bodies).
- Keywords are lowercase. Property order is convention, not grammar: declaration, `dataType`, `isHidden`, `formatString`,
  `isAvailableInMdx`, `lineageTag`, `summarizeBy`, `sourceColumn`, `sortByColumn`, blank line, `changedProperty` lines,
  blank-line-separated `annotation` lines. Measures come before columns in a table file.

## Multi-line expressions (the part that goes wrong)
Two valid forms. Continuation lines sit **two levels under the declaration** (properties sit one level under); ⚑ a
continuation indented only one level parses as a property and silently corrupts the object.
```tmdl
	measure Margin = ```
			SUMX (
			    Sales,
			    Sales[Quantity] * ( Sales[Net Price] - Sales[Unit Cost] )
			)
			```
		formatString: $ #,##0

	measure 'Sales Amount (% Δ LY)' =
			var ly = [Sales Amount (LY)]
			return
			DIVIDE ( [Sales Amount] - ly, ly )
		formatString: #,##0.00 %
```
Use the fenced form when writing by hand (it is Microsoft's recommendation and tolerates blank lines and `key: value`-looking
lines inside DAX/M). `ad-pbip measure set` always writes the fenced form. Property-valued expressions (`source =`,
`extendedProperty X =`) follow the same rule: body two levels under the object.

## Objects Desktop writes

### Columns and calculated columns
```tmdl
	column CustomerKey
		dataType: int64
		isHidden
		formatString: 0
		isAvailableInMdx: false
		lineageTag: 4de77f33-318d-4006-85db-580cb119fc6a
		summarizeBy: none
		sourceColumn: CustomerKey

		changedProperty = IsHidden

		annotation SummarizationSetBy = Automatic

	column 'Story Points Rounded' = ROUND ( Sales[Quantity], 0 )     -- calculated column: no sourceColumn
		dataType: int64
		summarizeBy: sum
```

### Hierarchies
```tmdl
	hierarchy 'Geography Hierarchy'
		level Continent
			column: Continent
		level Country
			column: Country
```

### Partitions
```tmdl
	partition Customer = m                     -- import from M
		mode: import
		source =
				let
				    Source = Sql.Database(#"Server", #"Database"),
				    Customer = Source{[Schema="dbo", Item="Customer"]}[Data]
				in
				    Customer

	partition 'Parameter - Dimension' = calculated     -- calculated table
		mode: import
		source =
				{ ("Customer", NAMEOF('Customer'[Customer]), 0) }
```

### Relationships
`relationships.tmdl` (top level, ids are GUIDs; `fromColumn` = many side, `toColumn` = one side):
```tmdl
relationship d4e6dc5a-6f46-443d-ab94-4cc0e10323c6
	fromColumn: Sales.CustomerKey
	toColumn: Customer.CustomerKey

relationship 21bd108e-527d-4566-be7d-9e474c858ee0
	isActive: false
	fromColumn: Sales.'Delivery Date'
	toColumn: Calendar.Date
```
### model.tmdl and refs
`model.tmdl` ends with `ref table Sales`, `ref culture en-US` (Desktop) / `ref cultureInfo en-US` (docs) … — ⚑ a new table
file needs its `ref table` line, and `database.tmdl` must start with `database`.

## lineageTag, annotations, files
- Do **not** write `lineageTag` on objects you create (Desktop assigns GUIDs on first save). ⚑ Never copy one: two objects
  with the same tag corrupt lineage. Existing tags stay as they are.
- Never add `annotation PBI_*` lines by hand; new roles never get `PBI_Id`.
- Files are UTF-8, LF, no BOM, trailing newline. Keep whatever the file already uses (the writer does); a BOM/CRLF flip turns a
  one-line change into a whole-file diff.
- Desktop rewrites files in its canonical order on save: commit before you open the PBIP so the rewrite is its own diff.

## Worked examples
1. **Add a measure**: `ad-pbip measure set --table Sales --name "Margin %" --expr-file margin_pct.dax --format-string "0.0%" --display-folder KPIs --description "Margin over sales"`.
2. **Change a format string**: edit the `formatString:` line only (keep the leading two tabs). `formatString: #,##0.00`.
3. **Add a calculated column**: under the table, after the last column: `\tcolumn 'Points Rounded' = ROUND ( Sales[Quantity], 0 )` then `\t\tdataType: int64`, `\t\tsummarizeBy: sum`. Then `ad-pbip lint`, `ad-pbip check --te2`.
4. **Add a relationship**: append to `relationships.tmdl` a `relationship <new GUID>` block with `fromColumn: Fact.'Key Col'` / `toColumn: Dim.Key`; `crossFilteringBehavior: bothDirections` only when asked; `isActive: false` for a second path.
5. **Add a hierarchy**: `\thierarchy 'Date Hierarchy'` then `\t\tlevel Year` / `\t\t\tcolumn: Year` — level columns must exist in the same table.
6. **Edit partition M**: change only lines inside the `source =` body, keep the 4-tab indentation of the body, use `Item="TABLE"` / `Schema="DB"` navigation or `Value.NativeQuery(Source, "SELECT ...")` for SQL (write the SQL with the dialect reference).
7. **Add a table**: new `tables/<Name>.tmdl` (`table <Name>` + columns + one partition) **and** `ref table <Name>` in `model.tmdl`.

## Pitfalls checklist (each is a lint rule or a TE2 error)
mixed tabs/spaces · continuation indented one level · unterminated ``` · unquoted name with space/dot · unquoted reference in
`sortByColumn`/`fromColumn`/`column:` · duplicate `lineageTag` · `//` comment · new table without `ref table` ·
`database.tmdl` without `database` · BOM or CRLF flip · measure referencing a column that does not exist (TE2 catches it).
