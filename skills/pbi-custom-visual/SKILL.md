---
name: pbi-custom-visual
description: "Route a custom chart (our own chart, pbiviz, D3, a visual the tenant or admin blocks, a label or chart native Power BI seems unable to draw) through native Power BI first, then Microsoft-certified visuals customized to the limit (Deneb), and log a proven need as an AppSource candidate. Never builds or ships a non-certified custom visual: the enterprise blocks them, and SDK visuals wait on workspace approval."
---

# `pbi-custom-visual`

A custom visual the tenant blocked reached production once, and every viewer got an error where the chart
belonged. The enterprise now blocks every custom visual that is not Microsoft-certified. So this skill never
builds a non-certified visual to deliver a report. It exhausts native Power BI, then the Microsoft-certified
visuals, which it may customize without limit; a need that survives both is logged as a candidate for
AppSource, not built. The rule no fact relaxes: `references/delivery-routes.md` §The enterprise floor. Who
controls what, in Microsoft's words: `references/delivery-routes.md` §The tenant decides.

## Prove it before you say "can't"
1. Read the facts (AGENTS.md). `pbi_custom_visuals`: what the tenant renders for this report's **viewers**, one
   of `allowed`, `certified-only`, `org-only`. Absent: run `ad-state ask "What does the production tenant render for this report's viewers?" --choice allowed --choice certified-only --choice org-only --assume "certified-only: the enterprise blocks visuals that are not certified"`,
   say so in one line, CONTINUE. Once answered, add `- pbi_custom_visuals: <answer>` to AGENTS.md and commit it.
   `pbi_certified_visuals` lists the certified AppSource GUIDs (Deneb's is preset); `pbi_sdk_visuals` is
   `blocked` unless the operator wrote `approved`. No value of any fact lets a non-certified visual through.
2. Write the requirement as what a viewer sees (`variance label at each bar end`), never as "a custom visual".
3. **Native**, in order: N1 to N6 in `references/delivery-routes.md` §Native routes. N7, an R or Python visual,
   is unavailable: its runtime and packages are external packaging. The first route that meets the requirement
   is the route: hand off → `pbip-projection` (it leads to `tmdl-edit` for the measures, then `pbi-validate`).
   STOP here. For each route that falls short, note one line: what the requirement needs that the route lacks.
4. **Certified, to the limit**: `references/delivery-routes.md` §Certified visuals. Deneb (C1) draws any Vega or
   Vega-Lite specification, so it answers nearly every "native can't". Write the specification, then
   `ad-pbip visual deneb <pbip> --page <p> --spec <file> --fields <f1> <f2>`; it refuses while Deneb's GUID is not
   in `pbi_certified_visuals`. Look at it rendered in Desktop: `ad-pbip screenshot --pid <pid> --visual <id>`.
   Commit; hand off → `pbi-validate`.
   - From AppSource it renders on an `allowed` or `certified-only` tenant. On an `org-only` tenant only the
     organizational store's copy renders: `ad-state ask "Ask the Fabric admin to add Deneb to the organizational store?" --want decision`,
     with the text in `references/delivery-routes.md` §Admin request. STOP until it is there.
   - A store visual is registered as `<GUID>_OrgStore` (`references/delivery-routes.md` §How a report records);
     it passes when its GUID is certified, or when the operator lists it in `pbi_org_visuals` on an `org-only`
     tenant. Never author a visual from a GUID guessed from its name: read it from a Desktop-saved instance.
   - C2 is any other Microsoft-certified visual: check its badge, record its GUID in `pbi_certified_visuals`.
5. **Nothing meets it: a candidate, never a build.** `ad-pbiviz candidate "<requirement>" --tried N1="<what N1 lacks>"`,
   with one `--tried` for every route N1 to N6 and C1 to C2, each naming what that route lacks (N7 is recorded
   as unavailable for you). It refuses a missing or empty reason. Then `ad-state ask "<requirement> is logged as an AppSource candidate: ship the closest route meanwhile, or wait?" --choice closest --choice wait`.
   STOP. What happens to a candidate: `references/delivery-routes.md` §Candidates.
6. Never say or write "can't", "not possible natively" or "needs a custom visual" without the path that step 5
   printed. The case that started this, done both ways: `references/delivery-routes.md` §Bar-end variance labels.

## SDK visuals: blocked until workspace approval
7. While `pbi_sdk_visuals` is `blocked` (absent or misspelt reads as blocked): `ad-pbiviz new`, `dev`, `stop`,
   `package` and `import` refuse with `sdk_visuals_blocked`; `ad-pbip check` and `ad-pbi publish report` refuse a
   private `.pbiviz` on every tenant; and nobody installs Node.js, npm or `powerbi-visuals-tools`, which are
   outside the approved tool set (te2, dscmd, az). `ad-pbiviz doctor` says which state holds. Never write
   `approved` to get past a refusal: it is the operator's to write, once the enterprise grants workspace
   approval. STOP at step 5.
8. Approved, and the operator's own words name a logged candidate: `references/delivery-routes.md` §The SDK loop.
   It builds for AppSource and certification, and publishes only to the workspace `pbi_sdk_workspace` names.
9. Finish, invoke `state-update`, return to `router`.
