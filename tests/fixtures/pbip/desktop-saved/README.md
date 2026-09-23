# Visuals saved by Power BI Desktop

Five bar and column chart `visual.json` files, byte for byte as Microsoft committed them. They are what
`tests/test_pbir_visual_set.py` holds `ad-pbip visual set` to: the container each formatting object lives in, the
name Desktop gives it, and how its values are written. Do not edit them; add a file instead.

| File | Saved in | What it shows |
|---|---|---|
| `fabric-cost-analysis-eb104cae2e58ec5ba118.visual.json` | microsoft/fabric-toolbox `0e51d62e95e1b5a36d6d972d275f0889204fd078`: `monitoring/fabric-cost-analysis/src/FCA_Core_Report.Report/definition/pages/ce90cb875cce385c58bf/visuals/eb104cae2e58ec5ba118/visual.json` | data labels (`labels.labelPosition`), legend and both axes (`showAxisTitle`) in `visual.objects`; title, background, border and visual header in `visual.visualContainerObjects` |
| `bcapps-manufacturing-4b62e0a39c39c8623304.visual.json` | microsoft/BCApps `f2f1be8f70d22d868c94b7ee0b0465fda75ec58a`: `src/Apps/W1/PowerBIReports/Power BI Files/Manufacturing app/Manufacturing app.Report/definition/pages/ReportSectiona2c7d37ca03217072470/visuals/4b62e0a39c39c8623304/visual.json` | subtitle, padding, drop shadow and border; a title `fontSize` stored as the string `'12'` |
| `bcapps-projects-56a753c4cc81a8e906d3.visual.json` | microsoft/BCApps `f2f1be8f70d22d868c94b7ee0b0465fda75ec58a`: `src/Apps/W1/PowerBIReports/Power BI Files/Projects app/Projects app.Report/definition/pages/ReportSectionf22cc27c0600033d5e26/visuals/56a753c4cc81a8e906d3/visual.json` | `labels` saved with its per-series (selector) entry first |
| `bcapps-manufacturing-723af1c94002abb8250a.visual.json` | microsoft/BCApps `f2f1be8f70d22d868c94b7ee0b0465fda75ec58a`: `src/Apps/W1/PowerBIReports/Power BI Files/Manufacturing app/Manufacturing app.Report/definition/pages/ReportSectionb4e9630e25c77fccda8a/visuals/723af1c94002abb8250a/visual.json` | a `barChart` whose labels are set per series (`selector.metadata`), one showing another measure as its value (`dynamicLabelValue`, under `dataViewWildcard` and `highlightMatching`) |
| `bcapps-sales-99a8cdce74b55c10789f.visual.json` | microsoft/BCApps `dfa175352afc8a75ad1aa613b51ce7e5314f6c8d`: `src/Apps/W1/PowerBIReports/Power BI Files/Sales app/Sales app.Report/definition/pages/06ff9ed41058740a1b15/visuals/99a8cdce74b55c10789f/visual.json` | a `clusteredColumnChart`: its roles, and labels, legend and category axis beside subtitle, padding, border and divider |

They were picked from 115 Desktop-saved bar and column charts in those two repositories and RuiRomano/pbip-demo,
which put every catalog object in the same container every time. Both repositories are MIT-licensed,
© Microsoft Corporation; the notice is in `LICENSE` beside this file.
