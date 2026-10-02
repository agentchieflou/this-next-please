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

### §3b. Model Authoring, Audit & Optimization (`tmdl-edit` & `pbi-model-audit`)
- **Tier 1 (Live TOM)**: `ad-pbip model apply --server <host:port>|--pid <pid> --ops <ops.json> [--save]` modifies the live model over port via Tabular Editor 2 `-S apply.csx`. Exact TOM errors are returned per op. When `--save`, session save triggers via UIA (`Ctrl+S`) and waits for Desktop-serialised TMDL to settle.
- **Tier 2 (TMDL Writer)**: `ad-pbip model apply --model <definition> --ops <ops.json>` applies the same declarative op list directly to TMDL files with mechanical formatting and automatic lint validation.
- **`lineageTag` Policy**: We never emit `lineageTag` or `annotation PBI_*` on newly created objects; Desktop generates lineageTags on save.
- **Best-Practice Audit**: `ad-pbip model audit` evaluates 8+ canonical rules, emitting TOON rows with actionable `fix` snippets.
- **Copilot AI Readiness**: `ad-pbip model audit --copilot` scores the model (0-100%) on descriptions, technical key hiding hygiene, and synonyms.
- **DAX Optimization**: `ad-pbip model optimize --measure <M> --pid <pid>` benchmarks before/after trace evidence, applies provable rewrites (variables, `KEEPFILTERS`, `CALCULATE`, `DIVIDE`), and strictly rolls back if evaluation results differ.

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

### §5. Publish (`pbi-publish`, `pbi-deploy-te2` & `pbi-refresh-xmla`)
- Deploy report and model definitions to Microsoft Fabric / Power BI Premium workspace via `ad-pbi` (REST item definitions) or `pbi-deploy-te2` (XMLA endpoint).
- Trigger model refresh and monitor completion.
- Reconcile live DMV dependencies against PBIP files.

#### Fabric Item-Definition Traps Table
The Fabric REST item-definition API (`/v1/workspaces/{ws}/reports`, `/getDefinition`, `/updateDefinition`) contains traps that make it agent-hostile without mechanical CLI protection. `ad-pbi` enforces these rules automatically:

| Trap / Hazard | Failure Mode | Mechanical Rule Enforced by `ad-pbi` |
|---|---|---|
| Missing `?format=PBIR` on `getDefinition` | Service returns `PBIR-Legacy` (monolithic `report.json`), breaking folder-based tooling. | `getDefinition` always appends `?format=PBIR` (reports) or `?format=TMDL` (models); refuses legacy formats with an actionable hint. |
| Incomplete parts on `updateDefinition` | `updateDefinition` replaces the entire definition. Any part not sent is permanently deleted on the service. | `ad-pbi publish` enumerates and transmits **all** parts from the `.Report` folder, warning if any part from a previous definition vanished. |
| Retrying `POST` after HTTP 202 | Service creates duplicate reports/models if create `POST` is repeated. | Never retry a create after 202. The operation ID is recorded to `.agent/out/pbi-ops/<op-id>.json` *before* polling begins so a crash never re-POSTs; `ad-pbi ops` resumes safely. |
| Backslash path separators | API rejects payloads with backslashes with `MissingDefinitionParts`. | Every part path is normalized to forward slashes (`/`) regardless of local OS conventions. |
| Local `byPath` semantic model reference | Service reports cannot use local relative paths (`byPath`); visual rendering fails. | `definition.pbir` is dynamically rewritten in memory to `byConnection` referencing the cloud model ID; the file on disk stays `byPath`. |
| Out-of-sync model entities | If a table or column was renamed in the target model, visual fields break silently upon publish. | Binding verification diff: `ad-pbi` fetches the target model TMDL and diffs PBIR field references against `ModelIndex` before publishing. Unbound references halt publish unless `--allow-unbound`. |
| A custom visual the tenant will not render | Desktop follows Group Policy and the service follows the tenant settings, so the visual works locally and every viewer gets an error in its place. | `ad-pbi publish report` reads where each custom visual comes from and refuses (`custom_visual_blocked`) before any call, when the visual is not certified (the enterprise floor: its GUID not in `pbi_certified_visuals`, or a private `.pbiviz` while `pbi_sdk_visuals` is blocked), when the `pbi_custom_visuals` fact says the tenant blocks it, or when nobody recorded the tenant. There is no override flag. |
| Credential leakage in logs/traces | Bearer tokens exposed in CLI output, logs, or error traces. | Tokens obtained through `az account get-access-token` are held in memory only, never printed to stdout/stderr, and scrubbed from error output. The token Tabular Editor is handed rides in its argv; `auth.redact` runs on the deploy log, every error tail, every result's `source` line and the doctor rows. |
| `az login` that signs nothing in | The Azure CLI has a token cache; Tabular Editor 2 and DAX Studio (AMO / ADOMD.NET) have another, filled only by their own sign-in window. REST works, `TabularEditor.exe powerbi://…` stalls until a person opens the GUI and connects. | `powerbi.auth.mode: token` (default): every Tabular Editor launch gets a connection string carrying a token az just minted for the Power BI audience (`Password=<token>`, empty `User ID`), so no cache is consulted. Service DAX goes through Tabular Editor (`ad-pbi dax`); dscmd keeps Desktop and `.vpax`. A signed-out CLI is signed in by the command (`az login --allow-no-subscriptions`, once). `ad-pbi auth --probe` proves it; `interactive` is the way back. |

---

## 2. Version-Drift Policy

We track Power BI Desktop and the Desktop Bridge through **capability probes** and **manifest-driven transcripts**, never by pinning fragile version numbers.

### Desktop Capability Probes (`ad-pbip capabilities`)
Power BI Desktop capabilities (Analysis Services port, local XMLA tooling, external tools directory, UIAutomation, user32!PrintWindow, Bridge named pipe, Bridge manifest) are probed dynamically on every session. We never assume an environment capability based on a Windows build number or Power BI Desktop version string.

### Bridge Manifest + Recorded Transcripts
The Bridge is an optional JSON-RPC 2.0 transport operating over `\\.\pipe\pbi-desktop-bridge-<pid>`. We negotiate capabilities at runtime via the `manifest` call:
- Operations are only invoked if explicitly declared in the advertised manifest (`manifest.operations`).
- Baseline transcripts (`tests/fixtures/bridge/<desktop-version>/*.jsonl`) capture golden request/response frames from live sessions.
- When Power BI Desktop updates on its monthly release train:
  1. `ad-pbip bridge probe --pid <pid>` checks for added or removed operations (`drift`).
  2. `ad-pbip bridge record --pid <pid>` records a new golden transcript under `tests/fixtures/bridge/<new-version>/transcript.jsonl`.
  3. Adding support for newly declared operations is a simple method mapping without code breaks or version bumps.

### Graceful Degrade to Native
Every Bridge-backed verb MUST gracefully fall back to its native equivalent if:
- The named pipe is absent (`pipe_present: false`)
- The requested operation is not declared in the manifest
- A frame is malformed, times out, or returns a transport error

In all fallback scenarios, the operation succeeds with `via: native` (or `reloaded_via: native`) and logs an informative warning. **Skills never see a Bridge error.**

| Verb | Bridge Path (`via: bridge`) | Native Degrade Path (`via: native` / `via: printwindow`) | Degrade Trigger |
|---|---|---|---|
| `ad-pbip desktop reload` | In-place JSON-RPC `reload` preserving AS port and live instance | Native `close` + `open_and_wait` with PBIP path | No pipe, undeclared `reload`, timeout, error |
| `ad-pbip screenshot` | Desktop internal renderer screenshot via JSON-RPC `screenshot` | Native `user32!PrintWindow` / UIAutomation window capture | No pipe, undeclared `screenshot`, timeout, error |

---

## 3. Custom Visuals (`pbiviz`)

The enterprise blocks every custom visual that is not Microsoft-certified, and does not approve the packaging an
SDK visual needs: the tools this package may ask a machine for are Tabular Editor 2, dscmd and the Azure CLI. So
the routing never builds a visual of its own to deliver a report, and the custom TypeScript/D3 loop is **blocked
until workspace approval**. The evidence and every route are in
`skills/pbi-custom-visual/references/delivery-routes.md`.

### The enterprise floor
- **Certified means listed.** A visual is certified when its GUID is in `pbi_certified_visuals` (the project stub
  presets Deneb's). `ad-pbip check` and `ad-pbi publish report` refuse any other custom visual on every tenant:
  `pbi_custom_visuals: allowed` no longer downgrades it to a warning, and a caller passing no facts gets the floor.
- **Organizational store**: registered as a `resourcePackages` entry of type `OrganizationalStoreCustomVisual`
  named `<GUID>_OrgStore` (the `visualType` too); a root `organizationCustomVisuals` entry registers nothing and is
  a warning. A store visual passes when its GUID is certified, or when `pbi_org_visuals` lists it on a tenant
  recorded as `org-only`.
- **Native first, then certified.** N1–N6 need no admin (data-label fields, format strings, SVG measures,
  analytics, composition, the paginated report visual); N7, an R or Python visual, is unavailable because its
  runtime and packages are external packaging. Deneb draws any Vega or Vega-Lite specification, and
  `ad-pbip visual deneb` writes it exactly as Deneb's PBIR guide describes, refusing while Deneb's GUID is not
  listed. A specification is proved in Desktop with `ad-pbip screenshot`, never with a Node renderer.
- **"Can't" costs a reason per route.** A need no route meets is logged with `ad-pbiviz candidate`: a proposal to
  build it for AppSource and certification, never a visual in a report.

### SDK visuals: `pbi_sdk_visuals`
`blocked` (the default, also when absent or misspelt): `ad-pbiviz new`, `dev`, `stop`, `package` and `import`
refuse with `sdk_visuals_blocked`, `ad-pbiviz doctor` reports the gate and probes no toolchain, and
`ad-pbip capabilities` reports its `pbiviz` row `via: blocked`. `roles`, `bind`, `candidate` and `candidates` need
no Node and keep working. `approved` is the operator's to write once the enterprise grants workspace approval,
with `pbi_sdk_workspace` naming the workspace; it approves Node.js, npm and `powerbi-visuals-tools` too. Then
the loop (`skills/pbi-custom-visual/references/delivery-routes.md` §The SDK loop) runs for a logged candidate, a
private visual is held to the tenant facts, and `ad-pbi publish report` resolves the target workspace and refuses
any but `pbi_sdk_workspace` (`ad-pbip check` compares it with the project's `pbi_workspace` / `ws_id`).

The rule ids, severities and conditions: `skills/pbi-custom-visual/references/delivery-routes.md` §The gate.

---

## 4. Handoff under policy

The Desktop handoff — the human indicates the window they mean, and `.agent/desktop.json` appears
with `server`, `database`, `pid`, `file` — has to work for a user who **cannot elevate**. Epic #112
measured that machine over three discovery rounds (#113) instead of guessing at it: Python is
enterprise-approved and on every user's `PATH`; Tabular Editor 2 and dscmd run fully functional from
`C:\Enforce`; and the single wall is one privileged file write, `<name>.pbitool.json` into
`%CommonProgramFiles%\Microsoft Shared\Power BI Desktop\External Tools`, Administrators only.

So the ribbon is not the handoff. It is one of four transports, and `ad-pbip capabilities` row
`external_tools` is the single source of truth for which one is live:

| Transport | Mechanism | Privileged write | `%database%` | Human gesture |
|---|---|---|---|---|
| `zorder` | highest `PBIDesktop.exe` window in Z-order, via `ctypes`/`user32` | none | DMV | click the window, then `ad-pbip handoff --active` |
| `file` | the instance matching the project's `pbip_path`, or a named document | none | DMV | none |
| `te2:local` | a per-user Tabular Editor custom action, *Hand off to agentdata* | none | verbatim | pick the instance, one click |
| `ribbon:machine` | one user-agnostic `agentdata.pbitool.json` placed once by IT | one, **by IT** | verbatim | the ribbon button |

`zorder` and `file` are the floor and need nothing from anyone. `ribbon:machine` is the honest front
door: `ad-pbip register-tool --package` writes the file and the request, and we never place it
ourselves. Its `path` is the resolved `%SystemRoot%\System32\cmd.exe`, so `cmd` resolves `python`
from the clicking user's own `PATH` — no interpreter path, no project path, no user name, no `%VAR%`
beyond Desktop's two substitutes. That is what makes the ticket worth filing exactly once, for
everyone, forever, instead of again after every Python upgrade.

### Withdrawn for good, and why

Three routes were considered during #112 and **withdrawn**. They are recorded here with their
reasons because each is the obvious idea — each will be re-proposed by somebody reading the same
error message in six months, and the reason it was dropped is not visible from that error message.
**No code may reintroduce them.** A pull request that does is rejected on this section, not on
taste.

**Environment-variable redirection of `CommonProgramFiles` / `CommonProgramFiles(x86)`.** Launch
Power BI Desktop with those variables pointed at a folder this user *can* write, and Desktop reads
its External Tools from there. It works. It is also a **policy bypass**: the folder is
Administrators-only precisely so that code launched by every user of the machine is code an
administrator approved, and redirecting the variable defeats that control while leaving it looking
enforced. Nobody would sign off on this if it were named honestly in the change request, and the
right response to "this control blocks me" is a ticket, not a workaround that survives until the
first audit. Withdrawn permanently: not because it is fragile, but because it is the thing the
control exists to prevent. What does the job instead: `zorder` and `file` need no ribbon at all,
and `ribbon:machine` asks for the write in the open.

**A resident `RegisterHotKey` listener.** A small background process holding a system-wide hotkey,
so the human presses a key over the Desktop window they mean and the handoff fires. This is a
**global hook by another name**: a process that outlives the command, sees keystrokes aimed at every
other application, and is indistinguishable to an endpoint agent from the thing those agents are
deployed to catch. It also breaks the epic's own rule that there is **no resident process** — every
verb starts, does one thing, and exits, which is what makes the tool auditable and what keeps a
crashed agent from leaving something running on a locked-down laptop. What does the job instead: the
gesture the human already made. They clicked the window; `ad-pbip handoff --active` reads the
Z-order, which is a read, needs no hook, and holds nothing after it returns.

**`Add-Type`-compiled PowerShell for the window enumeration.** Compiling a C# `P/Invoke` shim at
runtime to call `EnumWindows` and friends. `ctypes` on `user32.dll` does exactly the same job from
the approved Python, with no compiler on the path, no temporary assembly written to disk, no
`csc.exe` invocation for an endpoint agent to flag, and it stays inside the "stdlib only, zero new
dependencies" rule. `Add-Type` costs a compile per call and buys nothing. PowerShell is still used
through the existing `Runner` seam, for what it already does; it is not the way to reach `user32`.

### The standing rules these three leave behind

- **Measure, don't assume; never bypass.** A transport ships only after a read-only probe
  (`ad-pbip probe`) or a vendor-documented feature shows it is expected behaviour. Every claim in
  this section cites #113 output recorded in `docs/windows-verification.md` §Handoff without
  elevation.
- Anything needing a write outside `%LOCALAPPDATA%`, `%APPDATA%` or `.agent/` is an **IT package,
  not code**. We never write the machine file ourselves, and we never say "run elevated" unless an
  elevation avenue was actually detected — telling a user who cannot elevate to elevate is worse
  than saying nothing, and it is the reported failure this epic started from.
- **No resident process, no hotkeys, no hooks, no UI Automation clicks** as a transport.
- Every verb probes a **capability**, never a **version** — the same rule §2 states for the Bridge,
  applied to the handoff. `ribbon` is reported as a state (`registered`, `needs-it-file`,
  `disabled-by-policy`) with its evidence, never as an instruction to elevate.
