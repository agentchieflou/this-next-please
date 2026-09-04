---
name: pbi-router
description: "Domain sub-router for Power BI tasks: reports, models, TMDL, DAX, visuals, deploy, and refresh. Does no work itself."
---
# Power BI Router

1. Match the Power BI request to ONE row. First match wins.

| Request mentions | Invoke |
|---|---|
| numbers on a chart/visual are wrong, expected values in a document or CSV, UAT of a report | `uat-report-visual` |
| new report, dashboard from scratch, which pages, what should it look like | `pbi-report-plan` |
| layout, chart choice, colours, theme, looks wrong | `pbi-report-design` |
| add visual, edit visual, add page, remove visual, report authoring | `pbi-report-author` |
| PBIP, report, visual, page, "what feeds this chart", model overview | `pbip-projection` |
| add / fix a measure, column, format string, relationship, TMDL edit | `tmdl-edit` |
| audit the model, best practices, prepare for Copilot, slow measure, optimize DAX | `pbi-model-audit` |
| validate the report, broken visual, "does the report still work", before deploy | `pbi-validate` |
| deploy model, publish, XMLA, workspace | `pbi-deploy-te2` |
| refresh model / dataset | `pbi-refresh-xmla` |
| DAX result, vpax, export measures | `dax-studio-export` |

2. Output one line: `→ <skill>: <reason in ≤ 12 words>`. If `.agent/desktop.json` is stale, ask the human to press *External Tools → agentdata* in the window they mean. Then invoke it.
3. No match after reading the table twice → invoke `friction-log` with type `ambiguity`. STOP.
