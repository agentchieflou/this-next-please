# Delivery routes for a custom chart

**Why this file exists.** A custom visual the tenant blocked reached production, and every viewer got an error
where the chart belonged. Days later an assistant asked about the same Average/Recent chart concluded that
without the custom visual "the bar-end variance-label requirement remains unmet". That was wrong twice over: a
native data label carries it (§Bar-end variance labels), and so does Deneb, a Microsoft-certified visual. The
research behind every route below had been done before and never written into the routing.

The rules that follow from it:
1. **Native first, then Microsoft-certified.** Certified visuals may be customized without limit.
2. **Never build a non-certified visual to deliver a report.** A need that survives every native and certified
   route is logged with `ad-pbiviz candidate`, a proposal to build it and publish it to AppSource for
   certification (§Candidates).
3. **"Can't" needs proof.** The candidate command refuses without a reason for every route below, id for id.
4. **Nothing ships that viewers may not see.** `ad-pbip check` and `ad-pbi publish report` fail closed (§The gate).

## The tenant decides who sees a .pbiviz

Fabric admin portal → **Tenant settings** → **Power BI visuals**. These settings are "*not* available in the Power
Platform admin center" [1].

| Setting (exact name) | What Microsoft says it governs [1][2] | Organizational store? |
|---|---|---|
| Allow visuals created using the Power BI SDK | "Users in the organization can add, view, share, and interact with visuals imported from AppSource or from a file." Disabled by default. Scope: the entire organization, specific security groups, or all except specific security groups. | "Visuals allowed in the *Organizational visuals* page aren't affected by this setting." |
| Add and use certified visuals only (block uncertified) | "only certified Power BI visuals render in your organization's reports and dashboards. Power BI visuals from AppSource or files that aren't certified return an error message." | "aren't affected by this setting, regardless of certification." |
| Allow downloads from custom visuals | a visual exporting data to a file | applies to every visual |
| AppSource Custom Visuals SSO | Entra access tokens for AppSource visuals | applies to AppSource visuals, store ones included |
| Allow access to the browser's local storage | a visual's local storage | applies to every visual |

What follows from it:
- **Viewers, not authors.** The SDK setting covers who may *view* such a visual. An exception scoped to a security
  group renders the visual for members only. Record `pbi_custom_visuals` for the report's audience.
- **The service, not Desktop.** "The UI tenant settings only affect the Power BI service." Desktop follows Group
  Policy under `HKLM\Software\Policies\Microsoft\Power BI Desktop\`: `EnableCustomVisuals` and
  `EnableUncertifiedVisuals`, 0 disable, 1 enable (the default) [2]. A visual that works in Desktop can still fail
  for every viewer in the service. That is how the blocked visual got through.
- **Who can change it.** "To manage Power BI visuals, you must be a Fabric administrator" [2]; a Power Platform
  administrator has the same access to Fabric management, and so does a Global administrator [3].
- **The organizational store** accepts "any type of visual including uncertified visuals and *.pbiviz* visuals,
  even if they contradict the tenant settings of your organization", and "Organizational visuals settings
  automatically deploy to Power BI Desktop". Power BI Report Server does not support them [2].
- **R and Python visuals** have their own setting, "Interact with and share R and Python visuals", which "applies
  to the entire organization and can't be limited to specific groups" [4].
- **Microsoft's own AppSource visuals** (Bullet Chart, Tornado, Power KPI and the rest) are custom visuals too [15]:
  the certified ones are C2 like any other, and an `org-only` tenant blocks them all.

### How a report records where a visual comes from
PBIR `definition/report.json` has three registries [5]: `publicCustomVisuals` ("Names of the custom visuals used in
this report from AppSource"), `organizationCustomVisuals` ("Names and metadata of the organization approved custom
visuals", each `name`, `path`, `disabled`), and `resourcePackages` entries of type `CustomVisual` for a private
visual imported from a file. Only a private visual travels inside the report; Power BI loads AppSource and store
visuals itself [6]. `ad-pbip check` reads all three (§The gate).

## Choosing a route

Take the first route that meets the requirement, in this order. Every one needs nobody's permission except C1 or C2
on an `org-only` tenant, where the certified visual has to be in the organizational store first.

| # | Route | Renders for viewers | Interaction | Reach for it when |
|---|---|---|---|---|
| N1 | data-label fields on the native chart | always | full: cross-filter, tooltips, drill | a label or annotation on a bar, column, point |
| N2 | format strings: three sections, or dynamic | always | full | the label must be the bar's own number plus text |
| N3 | SVG measure in a table, matrix, card or slicer | always | a row click cross-filters; no per-mark hover | the drawing itself is custom: shapes, micro-charts |
| N4 | analytics and conditional formatting | always | full | targets, thresholds, bands, colour or icon by rule |
| N5 | composition: combo, small multiples, field parameters, visual calculations, tooltip pages, the new card | always | full | two measures on two axes, panels, switchable measures, rich hovers |
| N6 | paginated report visual | always: a native visual | driven by the report's filters | pixel-exact or printable output; labels are expressions |
| N7 | R or Python visual | while the tenant-wide setting is on; viewers need Pro or PPU | a static image: filtered by others, filters nothing | statistical drawings |
| C1 | Deneb, a Vega or Vega-Lite specification | from the store on any tenant; from AppSource on `allowed` and `certified-only` | cross-filter, cross-highlight, tooltips, context menu | anything the natives above cannot draw |
| C2 | another Microsoft-certified visual | as C1 | as built | a certified visual already draws exactly this |
| — | `ad-pbiviz candidate` | never ships | — | every row above lacks something the requirement needs |

## Native routes (no admin, every tenant)

### N1 Data-label fields on the native chart
A bar, column, line or ribbon chart's data label can show a different field from the one the bar is drawn from, a
text measure included, and a second line from another [8][9]. Format pane → **Data labels**: **Apply settings to**
picks the series, **Options → Position** puts the label at **Outside end**, **Value** carries the field the label
shows, and **Detail** adds a second line. The chart keeps cross-filtering, tooltips and drill. The custom label field
arrived in May 2023 (then a *Custom label* toggle under Values); the Title, Value and Detail cards in December 2023.
- **Outside end** exists on clustered charts, not stacked ones [10]. The Average/Recent chart is clustered.
- The longest bar's label can be cut off: give the value axis a fixed maximum with room for it.
- One Desktop gesture per visual: `ad-pbip visual set` writes literal properties, and this is a field reference.
  Save, and `ad-pbip check` validates the field like any other reference.

### N2 Format strings on the series
A three-section format string (positive;negative;zero) prints arrows and signs, e.g. `"▲ "0.0%;"▼ "0.0%;"– "0.0%`.
A dynamic format string (a DAX expression, generally available since October 2024 [11]) prints any text: a quoted
literal inside a format string prints as itself, written as four double-quote characters in DAX [12]. A copy of the
series measure then keeps its value, sorts and plots as a number, and reads `138  ▲ +15.0%`.
- Tooltips show the formatted text; the value axis does not follow a per-point format. If the number looks wrong,
  set the label's display units to None.
- Model measures only: a report measure in a live-connected report cannot have one.

### N3 SVG measure in a table, matrix, card or slicer
A measure returns an SVG as a `data:` URL; its data category is **Image URL** (measures can carry one since
August 2018), and a table or matrix draws it per row. It is Power BI's own image rendering, not a visual, so no
visuals setting applies to it, and the tenant settings index has none for images. The drawing is anything SVG can
express. A slicer, a multi-row card and the new Card visual (image, with **fx** on Image URL) draw it too [13].
- `#` ends a URL: write colours as `%23RRGGBB`. A `%` in any text is `%25` (`SUBSTITUTE ( …, "%", "%25" )`).
- Coordinates must carry no decimal separator, which in some locales is a comma: `ROUND ( …, 0 )` them.
- Scale every row against the largest value in the visual (`MAXX ( ALLSELECTED ( … ), … )`).
- Size the image in the format pane (image height and width) to the SVG's `width` and `height`.
- Tooltips show the SVG's source text; give the visual a report-page tooltip or turn its tooltips off.
- Blank in the service but not in Desktop: percent-encode `<`, `>` and `'` too (`%3C`, `%3E`, `%27`). Either way,
  the route is done when it renders in the service.

### N4 Analytics and conditional formatting
The Analytics pane adds constant, average, median, percentile, min and max lines, trend and forecast lines,
error bars (generally available since June 2022; no labels of their own) and shaded areas; a constant line's value
can come from a measure, so a target moves with the filters. Conditional formatting (**fx**) colours bars, columns
and labels by rules or by a measure returning a colour, and gives table and matrix cells background, font colour,
data bars and icons. Reach for it for targets, thresholds, ranges, and good-or-bad colouring.

### N5 Composition
- **Combo chart** (line and clustered or stacked column): two measures on two axes; the line carries its own labels.
- **Small multiples**: one panel per category on bar, column, line, area and combo charts.
- **Field parameters**: a slicer that swaps the measure or the axis.
- **Visual calculations** (generally available since May 2026): running totals, moving averages and percentages
  over the visual's own rows. They cannot carry a data category, so no SVG from them.
- **Tooltip pages**: a whole report page as the hover.
- **The new Card visual** (generally available since November 2025): a card per category, with images and reference
  labels.
- Buttons, bookmarks and drillthrough for guided interaction.

### N6 Paginated report visual
A native visual (since June 2021) that renders a paginated report inside the Power BI report. Its chart data labels
are expressions (`=Format(Fields!Var.Value, "+0.0%")`, or keywords such as `#VALY{N2}`), and bar labels sit Outside,
Left, Center or Right [16]. It needs the paginated report published to a workspace, which a Pro or PPU licence
allows since November 2022. The report's filters drive it; it does not cross-filter, and Publish to web does not
show it.

### N7 R or Python visual
A native visual governed by its own tenant-wide setting (above). It draws anything matplotlib or seaborn can, as a
static image: filtered by the report, never filtering it. In the service: 150,000 rows, a one-minute timeout,
viewers with Pro or PPU; Desktop needs a local Python. Last among the native routes for that reason.

## Certified visuals (customized to the limit)

A Microsoft-certified visual is not a custom visual of ours: the agent may configure one as far as it goes. It
renders from the organizational store on any tenant, or from AppSource on an `allowed` tenant and, once its badge is
confirmed (`pbi_certified_visuals`), on a `certified-only` one. On `org-only`, only its store copy renders: send the
§Admin request. Certification does not get a visual past a disabled "Allow visuals created using the Power BI SDK".

### C1 Deneb
Deneb draws a Vega or Vega-Lite specification over the fields in its Values well: marks, layers, text, custom axes,
transforms and interaction. That is most of what a visual of our own would have drawn. It is free, open source and
Microsoft-certified [14], and Deneb itself recommends the organizational store for enterprises, pinned to an
approved version [14].

From Deneb's PBIR guide [17] and its source [18]:
- **Visual type** `deneb7E15AEF80B9E4D4F8E12924291ECE89A`, the certified AppSource edition; Power BI fetches its code
  from AppSource, so it is not stored in the report. The Standalone, Alpha and Beta editions
  (`STANDALONEdeneb…`, `ALPHA…`, `BETA…`) are **not** certified and ship inside the report; never use them.
- **Data**: one role, `dataset`, taking columns and measures. The specification reads them as the data set named
  `dataset`, each field under its display name in the well (`datum["Avg Sales"]` for a name with a space).
- **Specification**: `visual.objects.vega[0].properties.jsonSpec`, the JSON stringified inside single quotes;
  `provider` is `vegaLite` (the default) or `vega`. Interactivity: `enableTooltips` (on by default),
  `enableSelection` with `selectionMode` `simple` (clicking a mark cross-filters), `enableHighlight`
  (cross-highlight from other visuals), `enableContextMenu`.

The verb writes exactly that, so no one hand-writes visual JSON:
`ad-pbip visual deneb <pbip> --page Overview --spec visuals/deneb/average-recent.vl.json --fields 'Dates'[Category] [Average] [Recent] --cross-filter`
adds one; `--visual <id>` with `--spec` replaces a visual's specification and keeps what Deneb manages. It refuses a
specification that is not JSON or that never names `dataset`. An apostrophe is fine: the verb doubles it, which is
how Power BI escapes one in every PBIR text literal (`Men's` is stored as `Men''s`). It refuses to add an AppSource
Deneb on an `org-only` tenant: add it from *My organization* in Desktop once, then set its specification.

Writing a specification: start from `references/deneb-average-recent.vl.json`. Render it before it goes near a
report: Deneb 2.0 bundles Vega 6.4.0 and Vega-Lite 6.4.3, and a Node script with those versions renders a
specification to SVG with the `dataset` filled in. Keep to standard Vega expressions (`format`, `max`) so it
renders both there and in Deneb.

### C2 Another Microsoft-certified visual
Any AppSource visual whose listing carries the certified badge. Check the badge, then add its GUID to
`pbi_certified_visuals`, or `ad-pbip check` refuses it on a `certified-only` tenant. Author it in Desktop: this
repository has a verb for Deneb only. An uncertified AppSource visual is never a route.

## Admin request
For an `org-only` tenant, where only store visuals render. It asks for a **certified** visual; never for one of ours.

> **Request: add one Microsoft-certified visual to the organizational store.** Please add **Deneb: Declarative
> Visualization in Power BI** (AppSource, certified; GUID `deneb7E15AEF80B9E4D4F8E12924291ECE89A`) under Fabric
> admin portal → Organizational visuals → Add visual → From AppSource. `[report]` needs it for `[the requirement,
> e.g. the Average/Recent comparison with a variance label at each bar end]`, which native visuals cannot draw.
> Our tenant settings stay as they are: Microsoft documents that organizational-store visuals are not affected by
> "Allow visuals created using the Power BI SDK" or "Add and use certified visuals only". AppSource visuals in the
> store update themselves. Optional: **Enable for Visualization Pane**. Deneb's enterprise FAQ, written for IT:
> deneb-viz.github.io/enterprise.

## Candidates
`ad-pbiviz candidate` writes `.agent/pbiviz/candidates/<yyyymmdd>-<slug>.md`: the requirement, the tenant, the
ticket, and one row per route with what it lacks. `ad-pbiviz candidates` lists them. It is the only way the routing
says "can't", and it refuses a missing route or a reason that names nothing ("n/a", "can't", "doesn't work").

A candidate is a proposal to the team, never a visual in a report. What the team may do with one:
- **Build it for AppSource**: the skill's Loop, on the operator's explicit word; then a Partner Center submission
  and Microsoft's certification review. Once certified, it is C2 on every `certified-only` tenant.
- **Decline it**: set `status: declined` and ship the closest route.
- The organizational store could carry it uncertified. That is a non-certified custom visual in production: the
  team's decision after review, never the agent's.

## Bar-end variance labels

The case this file was written for: a clustered bar chart of `[Average]` and `[Recent]` per category, with the
variance of Recent against Average at the end of each bar. Two routes meet it; neither is a custom visual.

**Native (N1).** `[Average]` and `[Recent]` stand for the model's own measures; add the others with `tmdl-edit`.
```dax
Variance % = DIVIDE ( [Recent] - [Average], [Average] )          -- format string: +0.0%;-0.0%;0.0%

Variance Label =
VAR v = [Variance %]
RETURN
    IF (
        NOT ISBLANK ( v ),
        IF ( v > 0, "▲ ", IF ( v < 0, "▼ ", "– " ) ) & FORMAT ( v, "+0.0%;-0.0%;0.0%" )
    )

Variance Color =                        -- hex text for a colour's "Field value" format style
SWITCH ( TRUE (), [Variance %] > 0, "#1A7F37", [Variance %] < 0, "#CF222E", "#6E7781" )
```
Swap the two colours for a measure where lower is better. Then in Desktop, once:
1. Data labels on. Apply settings to the **Average** series: labels off.
2. Apply settings to the **Recent** series: Position **Outside end**; **Value** field `Variance Label`. The bar end
   now reads `▲ +15.0%`. To keep the number as well, leave Value as it is and put `Variance Label` in **Detail**.
3. Optional, where the label colour offers **fx**: Format style **Field value** → `Variance Color`.
4. Save, then `ad-pbip check`: no `field-unresolved`.

N2 on the same chart, where N1's fields are missing: a copy of `[Recent]` as the Recent series, with this format
string expression. It returns `#,0"  ▲ +15.0%"`: the number, then the quoted text, its `%` taken literally.
```dax
VAR v = [Variance %]
RETURN
    "#,0"
        & IF (
            NOT ISBLANK ( v ),
            """  " & IF ( v > 0, "▲ ", IF ( v < 0, "▼ ", "– " ) ) & FORMAT ( v, "+0.0%;-0.0%;0.0%" ) & """"
        )
```

**Certified (C1).** `references/deneb-average-recent.vl.json` draws the same chart in Deneb: Average and Recent as a
clustered pair per category, the variance at the end of the longer bar, green ▲, red ▼, gray at zero, and nothing
where there is no Average to compare against. Rename `Category`, `Average` and `Recent` in it to the display names
in the well, then `ad-pbip visual deneb` as in §C1. It was rendered with Vega 6.4.0 and Vega-Lite 6.4.3, the
versions Deneb 2.0 bundles, over five sample rows (▲ +15.0%, ▼ −14.7%, – 0.0%, ▲ +14.0%, blank). It has not yet
run inside Power BI Desktop: a Desktop screenshot is the proof.

**A drawing of our own, still native (N3)**: two bars per row and the variance at the end of the longer one, in a
table next to the category column. Data category **Image URL** (TMDL: `dataCategory: ImageUrl`); image size
250 × 28. `'Dim'[Category]` stands for the table's category column.
```dax
Average vs Recent (SVG) =
VAR _avg = COALESCE ( [Average], 0 )
VAR _rec = COALESCE ( [Recent], 0 )
VAR _var = [Variance %]
VAR _max = MAXX ( ALLSELECTED ( 'Dim'[Category] ), MAX ( [Average], [Recent] ) )
VAR _plot = 170                        -- px for the longest bar; the other 80 hold the label
VAR _avgW = IF ( _max > 0, ROUND ( _avg / _max * _plot, 0 ), 0 )
VAR _recW = IF ( _max > 0, ROUND ( _rec / _max * _plot, 0 ), 0 )
VAR _x = MAX ( _avgW, _recW ) + 6
VAR _color = SWITCH ( TRUE (), _var > 0, "%231A7F37", _var < 0, "%23CF222E", "%236E7781" )
VAR _mark =
    SWITCH (
        TRUE (),
        _var > 0, "<path d='M" & _x & " 24 l4 -8 l4 8 z' fill='" & _color & "'/>",
        _var < 0, "<path d='M" & _x & " 16 l4 8 l4 -8 z' fill='" & _color & "'/>",
        "<rect x='" & _x & "' y='19' width='8' height='2' fill='" & _color & "'/>"
    )
VAR _label =
    IF (
        NOT ISBLANK ( _var ),
        _mark & "<text x='" & ( _x + 11 ) & "' y='24' font-family='Segoe UI, sans-serif' font-size='11' fill='"
            & _color & "'>" & SUBSTITUTE ( FORMAT ( _var, "+0.0%;-0.0%;0.0%" ), "%", "%25" ) & "</text>"
    )
RETURN
    IF (
        NOT ( ISBLANK ( [Average] ) && ISBLANK ( [Recent] ) ),
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='250' height='28'>"
            & "<rect x='0' y='2' width='" & _avgW & "' height='9' fill='%23C8CDD2'/>"
            & "<rect x='0' y='13' width='" & _recW & "' height='12' fill='%23336699'/>"
            & _label & "</svg>"
    )
```
Its output, emulated line by line and rendered in Chromium for the same five rows, draws what the certified
version does. Not yet run in Power BI Desktop.

## The gate
`ad-pbip check` (from the project root, where AGENTS.md holds the facts) and `ad-pbi publish report` run the same
rules. Publish refuses on any error before it calls the service, and has no flag to force it.

| Rule | Severity | When |
|---|---|---|
| `custom-visual-tenant-unknown` | error | a file or AppSource visual, and `pbi_custom_visuals` is not recorded: fail closed |
| `custom-visual-tenant-blocked` | error | a file or AppSource visual on `org-only`; a file visual on `certified-only` |
| `custom-visual-certification-unconfirmed` | error | an AppSource visual on `certified-only` whose GUID is not in `pbi_certified_visuals` |
| `custom-visual-store-disabled` | error | a store visual the admin switched off; viewers read "This custom visual is no longer available. Contact your administrator for details." [2] |
| `custom-visual-package-missing` | error | the report says it ships a private visual and the package is not on disk |
| `custom-visual-guid-unregistered` | error | the visual is in none of the three registries |
| `custom-visual-uncertified` | warning | a file visual on `allowed`: it renders until the tenant turns `certified-only` |
| `custom-visual-tenant-fact-invalid` | warning | `pbi_custom_visuals` is none of the three values; treated as unrecorded |

## Sources
1. Microsoft Fabric docs, *Power BI visuals tenant settings*, `docs/admin/service-admin-portal-power-bi-visuals.md`
   in MicrosoftDocs/fabric-docs, dated 2026-04-08.
2. Microsoft Fabric docs, *Manage Power BI visuals admin settings*, `docs/admin/organizational-visuals.md`, dated
   2025-10-23.
3. Microsoft Fabric docs, *Understand Microsoft Fabric admin roles*, `docs/admin/roles.md`.
4. Microsoft Fabric docs, *R and Python visuals tenant settings*, `docs/admin/service-admin-portal-r-python-visuals.md`.
5. Microsoft JSON schema, `fabric/item/report/definition/report/3.1.0/schema.json` in microsoft/json-schemas.
6. Power BI docs, *Power BI Desktop project report folder* (learn.microsoft.com/power-bi/developer/projects/projects-report):
   only private custom visuals are stored in the report's `CustomVisuals` folder; Power BI Desktop loads AppSource and
   organizational visuals itself.
7. OKVIZ, *Power BI Organizational Visuals Store* (docs.okviz.com/visuals/get-started/org-store), paraphrased: import
   the visual from the store and each new release is a single update there, not one per report.
8. Power BI May 2023 Feature Summary, "Measure driven data labels"; Kerry Kolosko, *Measure driven data labels*
   (kerrykolosko.com), a text measure as the custom label.
9. Power BI December 2023 Feature Summary: data label Title, Value and Detail cards, "available across Columns,
   Bars, Lines, and Ribbon charts".
10. Erik Svensen, 2024-04-09 (eriksvensen.wordpress.com): stacked charts offer Auto, Inside end, Inside center,
    Inside base; clustered bar and column charts add Outside end.
11. Power BI October 2024 Feature Summary: dynamic format strings for measures generally available.
12. SQLBI, *Improving data labels with format strings* (Kurt Buhler, 2025-03-21).
13. Power BI docs, *Display images in a table, matrix, or slicer* (power-bi-images-tables); Kerry Kolosko, *Adding
    sparklines to the new card visual*.
14. Deneb, *Enterprise and Security FAQ* (deneb-viz.github.io/enterprise, 2026-09-14): certified, free, MIT; the
    organizational store "the recommended path where continuity guarantees are required".
15. DataChant's daily AppSource export (github.com/DataChant/PowerBI-Visuals-AppSource), 2026-09: Microsoft's visuals
    listed as AppSource custom visuals, and Deneb 2.0.0.0 as certified.
16. Microsoft SQL docs, *Formatting data points on a chart (Report Builder and SSRS)*, dated 2024-09-25.
17. Deneb, *PBIR Implementation Guide* (deneb-viz.github.io/pbir-guide, source dated 2026-09-18).
18. Deneb source (github.com/deneb-viz/deneb): `apps/deneb/pbiviz.json` (GUID, version 2.0.0.0),
    `apps/deneb/capabilities.json` (the `dataset` role and the `vega` properties), `package.json` (Vega 6.4.0,
    Vega-Lite 6.4.3).

Sources 8 to 13 were read as search excerpts: those sites are not reachable from where this file was written.
