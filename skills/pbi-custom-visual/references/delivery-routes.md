# Delivery routes for a custom chart

**Why this file exists.** On 2026-09-23 a production tenant would not render our Average/Recent `.pbiviz`, and an
assistant concluded that the only fallback without an admin "keeps the current Average/Recent chart, but the
bar-end variance-label requirement remains unmet". That was wrong: the label is a native data label
(§Bar-end variance labels). The routes below had been researched before and never written into the routing, so
the next person to hit the wall started from nothing. This file is where they live now, and every claim names its
source (§Sources).

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
  group renders the visual for members only, so every viewer of the report must be in the group, not just its
  author. Record `pbi_custom_visuals` for the audience.
- **The service, not Desktop.** "The UI tenant settings only affect the Power BI service." Desktop follows Group
  Policy under `HKLM\Software\Policies\Microsoft\Power BI Desktop\`: `EnableCustomVisuals` and
  `EnableUncertifiedVisuals`, 0 disable, 1 enable (the default) [2]. A visual that works in Desktop can still fail
  for every viewer in the service, so a route is done when it renders in the service.
- **Who can change it.** "To manage Power BI visuals, you must be a Fabric administrator" [2]; a Power Platform
  administrator has the same access to Fabric management, and so does a Global administrator [3].
- **The organizational store** accepts "any type of visual including uncertified visuals and *.pbiviz* visuals,
  even if they contradict the tenant settings of your organization", and "Organizational visuals settings
  automatically deploy to Power BI Desktop". Power BI Report Server does not support them [2].
- **R and Python visuals** have their own setting, "Interact with and share R and Python visuals", which "applies
  to the entire organization and can't be limited to specific groups" [4].

### How a report records where a visual comes from
PBIR `definition/report.json` has three registries [5]: `publicCustomVisuals` ("Names of the custom visuals used in
this report from AppSource"), `organizationCustomVisuals` ("Names and metadata of the organization approved custom
visuals", each `name`, `path`, `disabled`), and `resourcePackages` entries of type `CustomVisual` for a private
visual imported from a file. Only a private visual travels inside the report; Power BI loads AppSource and store
visuals itself [6]. `ad-pbip check` reads all three (§The gate).

## Choosing a route

Take the first row that meets the requirement. The native rows come first because they need nobody's permission
and cannot be blocked later; a store visual can be disabled or deleted by an admin, and deleting one "immediately
stops rendering in existing reports" [2].

| # | Route | Admin | Renders for viewers | Interaction | Use when |
|---|---|---|---|---|---|
| N1 | native chart, data-label fields | no | always | full: cross-filter, tooltips, drill | a label or annotation on a bar, column or point |
| N2 | native chart, dynamic format string | no | always | full | N1's fields are not there, or the label must be the bar's own value plus text |
| N3 | SVG measure in a table or matrix | no | always | a row click cross-filters; no per-mark hover | the drawing itself is custom: shapes, layout, micro-charts |
| S1 | a store visual the tenant already has (`pbi_org_visuals`, e.g. Deneb); on a `certified-only` tenant also a certified AppSource visual (Deneb is certified) | no | always | depends on the visual | a spec-driven visual can draw it |
| S2 | our own `.pbiviz` in the organizational store | one upload | always | as built | nothing above meets it |
| X1 | the SDK setting scoped to a security group | yes | members only | as built | a closed audience, and the admin prefers it to S2 |
| X2 | R or Python visual | only if its setting is off | while the tenant-wide setting is on; viewers need Pro or PPU | a static image: filtered by others, filters nothing | statistical drawings; last resort |
| X3 | paginated report visual | no (a paginated report in a Pro or PPU workspace) | always: a native visual | driven by the report's filters; no per-mark interaction | printable, pixel-exact output; chart labels are expressions |

Never a route: the Developer visual (Desktop only, for building); Microsoft's own AppSource visuals (Bullet Chart,
Tornado, Power KPI and the rest are custom visuals, blocked by the same setting); a report moved to another tenant to
get round the policy; or certifying our own visual to satisfy `certified-only` (an AppSource submission and
Microsoft's review, weeks at best, for a visual that then becomes public).

## Native routes (no admin, every tenant)

### N1 Data-label fields on the native chart
A bar, column, line or ribbon chart's data label can show a different field from the one the bar is drawn from, a
text measure included, and a second line from another [8][9]. Format pane → **Data labels**: **Apply settings to**
picks the series, **Options → Position** puts the label at **Outside end**, **Value** carries the field the label
shows, and **Detail** adds a second line. The variance is a measure, so the bar end shows it, and the chart keeps
cross-filtering, tooltips and drill. The custom label field arrived in May 2023 (then a *Custom label* toggle under
Values); the Title, Value and Detail cards in December 2023.
- **Outside end** exists on clustered charts, not stacked ones [10]. The Average/Recent chart is clustered.
- The longest bar's label can be cut off: give the value axis a fixed maximum with room for it.
- It is one Desktop gesture per visual: `ad-pbip visual set` writes literal properties, and this is a field
  reference. Save, and `ad-pbip check` validates the field like any other reference.

### N2 Dynamic format string on the series
A measure's format string can be a DAX expression (generally available since October 2024 [11]), and text in double
quotes inside a format string prints as itself: the suffix is wrapped in quotes written as four double-quote
characters in DAX [12]. A copy of the series measure therefore keeps its value, sorts and plots as a number, and
prints the variance after it: `138  ▲ +15.0%`. Use it where N1's fields are missing, or where the label must stay the
bar's own number.
- Tooltips show the formatted text; the value axis does not follow a per-point format. If the number looks wrong,
  set the label's display units to None.
- Model measures only: a report measure in a live-connected report cannot have one.

### N3 SVG measure in a table or matrix
A measure returns an SVG as a `data:` URL; its data category is **Image URL** (measures can carry one since
August 2018), and a table or matrix draws it per row. It is Power BI's own image rendering, not a visual, so no
visuals setting applies to it. The drawing is
anything SVG can express. The trade-off is interaction: a row click cross-filters the page, but there is no hover
on an individual mark.

Rules that break it when forgotten:
- `#` ends a URL: write colours as `%23RRGGBB`. A `%` in any text is `%25` (`SUBSTITUTE ( …, "%", "%25" )`).
- Numbers concatenated into coordinates must carry no decimal separator, which in some locales is a comma:
  `ROUND ( …, 0 )` them.
- Scale every row against the largest value in the visual (`MAXX ( ALLSELECTED ( … ), … )`), or each row's bar is
  full width.
- Size the image in the table's format pane (image height and width), matching the SVG's `width` and `height`.
- Tooltips show the SVG's source text; give the visual a report-page tooltip or turn its tooltips off.
- If it renders in Desktop and is blank in the service, percent-encode `<`, `>` and `'` as well (`%3C`, `%3E`,
  `%27`). Either way, the route is done when it renders in the service.

Besides a table or matrix, an Image URL measure also draws in a slicer, a multi-row card and the new Card visual
(image, with the **fx** on Image URL) [13]. No tenant setting governs any of it: the tenant settings index has none
for images.

The worked measure is in §Bar-end variance labels. Its output was rendered in Chromium from a line-by-line emulation
of the DAX, for five sample rows, and all five decoded. It has not yet run in Power BI Desktop: `ad-pbip check --te2`
parses it, and a Desktop screenshot is the proof.

## Organizational store

### A general-purpose store visual (Deneb)
Deneb draws a Vega or Vega-Lite specification over the fields you give it, so one visual covers most custom
charts, bar-end labels included. It is free, open source, and Microsoft-certified [14]. When the `pbi_org_visuals`
fact lists it (Desktop: Visualizations pane → … → Get more visuals → My organization), build the chart as a
specification in it: no admin, no upload.
- Certification does not get it past a disabled "Allow visuals created using the Power BI SDK": on an `org-only`
  tenant only the store copy renders. On a `certified-only` tenant, its AppSource edition renders as well.
- Deneb's own guidance for enterprises is the organizational store, which pins the approved version [14]. Its
  enterprise FAQ is written to be handed to IT.

### Our own .pbiviz
Build and test it in Desktop with the skill's Loop. Then:
1. The admin uploads `visuals/<name>/dist/*.pbiviz` in *Organizational visuals* → **Add visual** → **From a file**,
   and can pick **Enable for Visualization Pane** so it appears for everyone [2].
2. In Desktop, add the *My organization* copy and swap the report's instance to it. The report then lists the visual
   in `organizationCustomVisuals` and stops carrying the file.
3. A new version is an admin **Update** of the same entry (Settings → Browse → Update) [2]. Reports that use the
   store copy get it from there, so a release is one update in the store, not one per report [7].
4. `ad-pbip check` → no `custom-visual-tenant-blocked`, no `custom-visual-store-disabled`.

## Admin request
Paste-ready text for the operator to send. Fill the brackets; keep the rest.

> **Request: add one Power BI visual to the organizational store.** Please add `[visual display name]`
> (`[GUID from pbiviz.json]`, version `[x.y.z.w]`, attached) under Fabric admin portal → Organizational visuals →
> Add visual → From a file. It draws `[the requirement, e.g. the Average/Recent comparison with a variance label
> at each bar end]` in `[report]` for `[audience]`. Our tenant's "Allow visuals created using the Power BI SDK"
> setting stays as it is: Microsoft documents that organizational-store visuals are not affected by it or by
> "Add and use certified visuals only". The source is in `[repository]` for review. Optional: **Enable for
> Visualization Pane**.

If the admin prefers a security-group exception (X1), the group must contain **every viewer** of the report, not
only its authors.

## Bar-end variance labels

The case this file was written for: a clustered bar chart of `[Average]` and `[Recent]` per category, with the
variance of Recent against Average at the end of each bar. `[Average]` and `[Recent]` stand for the model's own
measures; add the others with `tmdl-edit`.

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
Swap the two colours for a measure where lower is better.

**N1, on the chart that exists** (Desktop, once):
1. Data labels on. Apply settings to the **Average** series: labels off.
2. Apply settings to the **Recent** series: Position **Outside end**; **Value** field `Variance Label`. The bar end
   now reads `▲ +15.0%`. To keep the number as well, leave Value as it is and put `Variance Label` in **Detail**.
3. Optional, where the label colour offers **fx**: Format style **Field value** → `Variance Color`.
4. Save, then `ad-pbip check`: no `field-unresolved`.

**N2, the same chart where N1's fields are missing**: a copy of `[Recent]` as the Recent series, with this format
string expression:
```dax
VAR v = [Variance %]
RETURN
    "#,0"
        & IF (
            NOT ISBLANK ( v ),
            """  " & IF ( v > 0, "▲ ", IF ( v < 0, "▼ ", "– " ) ) & FORMAT ( v, "+0.0%;-0.0%;0.0%" ) & """"
        )
```
It returns `#,0"  ▲ +15.0%"`: the number, then the quoted text, with its `%` taken literally.

**N3, a drawing of our own, still native**: two bars per row and the variance at the end of the longer one, in a
table next to the category column. Data category **Image URL** (TMDL: `dataCategory: ImageUrl`); the table's image
size 250 × 28. `'Dim'[Category]` stands for the table's category column.
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
Its output, emulated line by line and rendered in Chromium for five rows (up, down, zero, the widest bar, a row
without an Average): a gray Average bar, a blue Recent bar, a green or red arrow and the variance at the bar end, a
gray dash at zero, and no label where there is no Average to compare against. Not yet run in Power BI Desktop.

## The gate
`ad-pbip check` (from the project root, where AGENTS.md holds the facts):

| Rule | Severity | When |
|---|---|---|
| `custom-visual-tenant-blocked` | error | a file or AppSource visual on an `org-only` tenant; a file visual on a `certified-only` one |
| `custom-visual-store-disabled` | error | a store visual the admin switched off; viewers read "This custom visual is no longer available. Contact your administrator for details." [2] |
| `custom-visual-tenant-certified` | info | an AppSource visual on a `certified-only` tenant: renders only if certified |
| `custom-visual-tenant-unknown` | info | a file or AppSource visual, and `pbi_custom_visuals` is not recorded |
| `custom-visual-tenant-fact-invalid` | warning | `pbi_custom_visuals` is none of `allowed`, `certified-only`, `org-only` |
| `custom-visual-package-missing` | error | the report says it ships a private visual and the package is not on disk |
| `custom-visual-guid-unregistered` | error | the visual is in none of the three registries |

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
14. Deneb, *Enterprise and Security FAQ* (deneb-viz.github.io/enterprise, 2026-09-14).

Sources 8–13 were read as search excerpts: those sites are not reachable from where this file was written.
