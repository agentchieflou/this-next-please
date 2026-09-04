# Agentic Power BI Lifecycle

This document describes the end-to-end development loop for Power BI projects with Antigravity agent skills and mechanical tools:

$$\text{Plan} \longrightarrow \text{Design} \xrightarrow{\text{Gate 1: Brief Approval}} \text{Author} \longrightarrow \text{Validate} \xrightarrow{\text{Gate 2: Pre-Deploy Validation}} \text{Publish}$$

---

## 1. The Five Stages

### §1. Plan (`pbi-report-plan`)
- **Step 0**: Model projection via `ad-pbip project`. Inspect `MODEL.md` (tables, measures, dependencies). Never plan against an unprojected model.
- **Inquiry Rounds**: Up to 5 rounds. Ask exactly one question per round, then stop. Prioritize `.agent/state.json` and Jira context to avoid re-asking known facts.
- **Output**: Drafts `.agent/brief/<KEY>-report-spec.md` with ticket metadata, audience, model SHA, and page targets.

### §2. Design (`pbi-report-design`)
- **Archetypes**: Map pages to canonical archetypes (Executive Summary, Operational Monitor, Analytical Canvas, Narrative Story, Comparative Benchmark).
- **Encoding**: Choose visual types using data cardinality, grain, and encoding hierarchies.
- **Contract**: Generate the `design_brief:` YAML block with canvas dimensions, 12-column grid regions, visual placements, and `space_audit`.
- **Constraint**: Design produces only layout specs and *never runs an `ad-pbip` write verb*.

### 🔒 Human Gate 1: Brief Approval (`ad-pbip brief approve`)
- **Automated Pre-flight**: Run `ad-pbip brief check <spec.md>` to assert zero overlapping placements, canvas boundary compliance, space audit $\le 100\%$, and model field resolution.
- **Interactive Terminal Gate**: `ad-pbip brief approve <spec.md>` must be executed interactively in a terminal TTY (`isatty`).
- **Stamp**: Writes `.agent/brief/<KEY>.approval.json` recording spec SHA256 and model SHA.
- **Author Gate**: Authoring verbs (`visual add`, `page add`) verify that `ad-pbip brief status` is `current` before writing PBIR.

### §3. Author (`pbi-report-author`)
- **Zero Handwriting**: Never hand-write or guess visual JSON.
- **Mechanical Verbs**: Authoring is driven strictly through `ad-pbip` verbs:
  - `ad-pbip page add`, `page move`, `page remove`
  - `ad-pbip visual add --brief <spec.md>`, `visual set`, `visual remove`
  - `ad-pbip filter set`
  - `ad-pbip bookmark add`
  - `ad-pbip theme set`
- **Verification Loop**: After edits, reload running Desktop (`ad-pbip desktop reload --pid <pid>`) and verify via screenshot (`ad-pbip screenshot --pid <pid> --page <p>`).

### §4. Validate (`pbi-validate`)
- Cross-validate PBIR reports and TMDL models (`ad-pbip check <pbip>`).
- Run anti-pattern linting:
  - `filter-entity-vs-source`
  - `page-not-in-pages-json`
  - `duplicate-visual-id`
  - `duplicate-filter-id`
  - `legacy-visual-type`
  - `position-off-canvas`
  - `overlap`
- Run DAX/TMDL syntax validation via Tabular Editor 2 (`ad-pbip check --te2`).

### 🔒 Human Gate 2: Pre-Deploy Validation
- Ensure all CI tests pass across runners.
- Live DAX measure probe against Analysis Services server or XMLA endpoint.
- Human signs off on diffs before publishing.

### §5. Publish (`pbi-deploy-te2` & `pbi-refresh-xmla`)
- Deploy model to Microsoft Fabric / Power BI Premium workspace via XMLA endpoint.
- Trigger model refresh and monitor completion.
- Reconcile live DMV dependencies against PBIP files.
