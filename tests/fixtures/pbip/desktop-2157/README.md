# A project shaped like Power BI Desktop 2.157 saves it

Hand-written, not saved by Desktop: a minimal PBIP whose every report file declares the `$schema` version Power BI
Desktop 2.157 (August 2026, 2.157.1354.0) writes, as `agentdata/pbip/pbir.py` `DESKTOP_SCHEMAS` lists them, and
validates against that schema as vendored under `agentdata/pbip/schema/fabric/` (`tests/test_pbir_2157.py` checks
both). Do not bump a version here by hand; a later Desktop gets its own fixture.

| File | Schema | What it holds |
|---|---|---|
| `definition.pbir` | definitionProperties 2.0.0, `"version": "4.0"` | `byPath` to the semantic model |
| `definition/version.json` | versionMetadata 1.0.0 | `"version": "2.0.0"` |
| `definition/report.json` | report 3.3.0 | base theme `CY24SU10`: a report keeps the base theme it was created with until someone updates it, and the name Desktop gives the Fluent 2 base theme is not published, so it is not guessed here |
| `definition/reportExtensions.json` | reportExtension 1.0.0 | one report-level measure, under the file name Microsoft's PBIR folder table gives (the plural) |
| `definition/pages/pages.json` | pagesMetadata 1.1.0 | one page |
| `definition/pages/<page>/page.json` | page 2.1.0 | 1920x1080, the Fluent 2 default canvas |
| `.../visuals/<visual>/visual.json` | visualContainer 2.12.0 | a `listSlicer` on `Sales[Region]` and a `cardVisual` on `[Total Sales]` |
| `definition/bookmarks/bookmarks.json` | bookmarksMetadata 1.0.0 | the bookmark index: Desktop lists only the bookmarks it names |
| `definition/bookmarks/<name>.bookmark.json` | bookmark 2.1.0 | one bookmark over both visuals |
