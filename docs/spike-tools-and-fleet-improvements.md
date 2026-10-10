# Spike: tools we could lean on, and where the fleet could be faster, clearer and kinder

_Status: PLANNED (spike opened 2026-10-10 at the operator's request: "figure out what tools are out there that we
could also be leveraging … additional open source tools to make us better at what we use the most + additional
design improvement ideas for our fleet (focused on engineering performance improvements first, then UI
improvements, then UX improvements)"). Research only; nothing here is built. Every number about **this** repository
comes from its own docs and CI records and is cited by path. Every claim about an outside tool comes from a page
read on 2026-10-10 (§10) and is marked **verify** where the page was a vendor's or a blog's rather than the
project's own._

## 1. The answer, first

Ranked by what each one moves against a number this repository already measures. "Cost" is the routing plan's
scale: *cheap* is an afternoon with no new dependency; *medium* is a day and a test; *dear* is a new dependency,
a new process on the laptop, or a sitting.

| # | Pick | What it moves | Cost | Section |
|---|---|---|---|---|
| 1 | **coverage.py's `sysmon` core** (the default on Python 3.14 since coverage 7.9.2) | the coverage step, last green at **9m38s** of a 15-minute cap | cheap: pin the version, measure | 3a |
| 2 | **Copilot CLI's own OpenTelemetry exporter**, file mode, tailed like `events.jsonl` | token counts and cost per turn, which `events.norm.jsonl` cannot carry today ("no cost increments, session totals only", [fleet-events.md](fleet-events.md) §What is deliberately not here) | medium, **verify** the variables on the laptop | 3d |
| 3 | **ruff**, lint and format in one binary, ratcheted like `tests/hygiene_baseline.json` | the repository has no Python linter or formatter at all; CI lints shell and PowerShell but not Python | cheap to add, medium to ratchet | 3e |
| 4 | **pytest-testmon** for the developer's loop and the Windows shards | the inner loop is ~116 s locally; a Windows shard is ~9.4 min serial, and #227 keeps it serial | medium; never the CI gate | 3a |
| 5 | **Playwright tracing on failure** for the browser tier | the one flaky test this week (`test_the_agents_work_in_an_office…`, PR #659) failed with a bare timeout and no trace to read | cheap | 3a |
| 6 | **PBI Inspector's rule model** (JsonLogic over PBIR JSON) as the shape of `ad-pbip check` rules | report checks are code today; a rules file is a DataTable-style seam | medium | 4b |
| 7 | **mark**'s metadata-header contract for Confluence pages | `ad-confluence publish` needs a page address; mark's `Space`/`Title`/`Parent` front matter is a proven one | cheap to borrow, nothing to install | 4a |
| 8 | **Risk-tiered approvals with an undo lane** | the gate asks the same click for `git-push` to the agent's own branch as for `jira-transition`; the 2026 HITL literature calls that approval fatigue | medium | 6 |
| 9 | **Agent profiles as data** and **worktree auto-isolation**, two patterns from agent-dashboard | the registry and launch flags are code; a second agent on one project is refused by a lock rather than offered a worktree | medium | 5, 6 |
| 10 | **TypeScript 7 strict** for the desk, and the two unchecked files | `tsconfig.json` pins 7.0.2 with `strict: false`; `settings.js` and `probe.js` are not checked | cheap | 5 |

Two things this spike recommends **against**, with the reasons in §7: adopting a tmux-based agent manager (the
laptop is Windows and the policy forbids what they assume), and the free-threaded 3.14 build (two C extensions in
the runtime dependencies decide it, not us).

## 2. What we use most, by the numbers

| Surface | Fact | Where it is written |
|---|---|---|
| The CLI | 29 `ad-*` console scripts; Python ≥ 3.14; runtime deps `rich`, `keyring`, `pyodbc`, `pyyaml` | `pyproject.toml` |
| The suite | 272 test files; inner loop ~4,200–4,900 tests in ~100–116 s on four cores; browser tier 349 tests, ~25 min of test time, sharded; `measured`+`scale` 19 tests run serially; everything serial ~34 min | [testing-this-repo.md](testing-this-repo.md); `tests/durations.json` |
| CI | one workflow, ~1,050 lines, 16 jobs; step caps ≈ 1.5× last green, job caps ≤ 20 min (#309); Windows runs four **serial** shards at ~9.4 min each because `-n auto` failed three of four tries (#227); coverage step 9m38s | `.github/workflows/tests.yml`; `tests/test_hygiene_ci_budgets.py` |
| The fleet server | stdlib `ThreadingHTTPServer`, SSE at `/api/events` (`TICK_S = 0.4`), plus a 15 s `loadDesk` poll in the page; 154 KB gzipped static against a 200 KB budget; 50 ms gesture budget, ~6 ms measured | `agentdata/fleet/serve.py`; [desk-instant.md](desk-instant.md) |
| Agents | `copilot -p … --output-format json --no-ask-user`, one per repo, stdout to `events.jsonl`, folded to `events.norm.jsonl` by byte offset; `--usage-output-file` read by `spend.py` for session totals | `agentdata/fleet/launch.py`, `supervisor.py`, `events.py`, `spend.py` |
| Atlassian | pncli directly; `ad-confluence publish` and `ad-git pr` as gated extensions; `confluence.py` is our own Markdown → storage-format converter | [pncli-parts.md](pncli-parts.md) |
| Power BI | PBIP/TMDL projection and validator (`ad-pbip`), Desktop bridge (`ad-pbi`), TE2 deploy; pbi-tools credited | [pbir-authoring.md](pbir-authoring.md); [pbi-tools-parts.md](pbi-tools-parts.md) |
| Skills | 51 under `skills/`; the ledger counts uses from the fleet's stream and Copilot's session files; sync from `fleet.skills.source` | [fleet-skills.md](fleet-skills.md) |
| Lint and types | shellcheck, PSScriptAnalyzer and `tsc --noEmit` in CI; **no** ruff, black, flake8, mypy or pyright | `.github/workflows/tests.yml`; `tsconfig.json` |
| Node and npm on the laptop | Node.js is installed; `npm install` works only through the route Playwright's install uses (the one npm path the proxy allows); **every npm package must be vetted** before install. A laptop rule, not a CI rule | [windows-verification.md](windows-verification.md) §0a (recorded 2026-10-10) |

The ledger does not yet say which skills run most, and this checkout has no `.agent/friction/`, so "what we use
most" above is what CI and the laptop spend their minutes on, not what the operator types most. That is a gap the
marketplace page will close on its own as the ledger fills (and a reason to add Claude Code's transcripts as a
second source, [plan-m365-bridge.md](plan-m365-bridge.md) §8).

## 3. Engineering performance

### 3a. The suite and CI

| Tool | What it is | Where it would land | Evidence and caveats |
|---|---|---|---|
| **coverage.py `sysmon` core** | the `sys.monitoring` measurement core from Python 3.12; coverage 7.7.0 added branch coverage on it for 3.14, and **7.9.2 made it the default on 3.14+** where supported. It disables an event after its first hit, so re-executed lines cost nothing | the `coverage` job (serial, `-m "not browser"`, last green 9m38s of 15). First check which coverage version CI installs and whether the run is already on `sysmon`; if not, `COVERAGE_CORE=sysmon` is the whole change | Ned Batchelder's note and the 7.9.2 changelog (§10). Plugins and dynamic contexts are unsupported on `sysmon`; we use neither. **Measure** before and after: no source gave 2026 numbers |
| **pytest-testmon** | selects the tests affected by changed files from a dependency database (v2.2.0, Dec 2025) | the developer's inner loop, and a candidate for the **Windows** shards where #227 forces serial runs: fewer tests per shard beats parallel shards we cannot have. Never the gate: `ci-ok` keeps running everything | A "flat waits / skips only go down" repository should treat testmon as a *speed* tool, not a *selection* of what counts as green |
| **xdist `--dist worksteal`** | idle workers steal from busy ones; built for suites with uneven durations | the Linux `pytest` leg; the browser shards already use `-n 2` | the workflow's own comment (line 449) says `--dist load` interleaves per-module autouse fixtures on Windows; `worksteal` does not fix that, so Windows stays serial |
| **pytest-split** | durations-balanced sharding | **not needed**: `tests/shard.py` already balances whole files by `tests/durations.json`, and `.github/scripts/durations.py` already refreshes it. Named here so nobody adds it twice | — |
| **Playwright tracing** | `--tracing retain-on-failure` in pytest-playwright writes a trace zip per failing test; upload it as a job artefact beside `junit/` | the browser jobs. This week's flake (a `page.click("#wtake")` that completed, then a navigation that never came) would have come with a timeline instead of a 30 s timeout | the pytest-playwright reference; our `tests/desk_harness.py` launches Chromium itself, so the flag may need to become a harness option |
| **pytest-flakefinder** | runs each test N times in one session to surface order- and timing-sensitivity | the nightly `order-independence-nightly` job already shuffles seeds; flakefinder on the browser tier once a week would find the next `#wtake` before a PR does | it finds flakes; the rule that no test is skipped or quarantined to get green stands |
| **TypeScript 7** | the Go compiler shipped as `tsc` in July 2026; 8–12× faster full builds reported | already pinned (`typescript@7.0.2`). Two follow-ups: `strict` is reported to default to `true` in 7.0 (our `tsconfig.json` sets `false` explicitly, so nothing changed under us); and `settings.js`/`probe.js` are still outside the check | release coverage (§10); the "strict by default" claim is from one blog, **verify** against the 7.0 notes |
| **Typing the three.js files** | `probe.js`, `ink/layer.js` and `map/scene.js` import the vendored `three.module.min.js`; a program that includes them makes tsc infer types from 656 KB of minified code, slowly and uselessly | a **hand-written `three.d.ts`** declaring only what the desk uses, under `declare module "*/three.module.min.js"`; the world stays out (parked, moved to play-sports). `@types/three` would be more complete but is an npm package to vet on the laptop and a version to keep matched to the vendored release; CI could fetch it, the laptop should not have to | the npm facts in §2; `tsconfig.json`'s own comment on why `probe.js` is not in the program yet |

### 3b. The CLI's start-up

Twenty-nine entry points share one package. Two measurements nobody has taken: `python -X importtime -c "import
agentdata.cli"` on the laptop, and the same for `ad-view`, the command every skill now runs after a pncli read.
`rich` is imported for `--pretty` only, and `keyring`, `pyodbc` and `pyyaml` are needed by a minority of commands.

- **Now:** function-level imports where `-X importtime` shows a cost. `slowimports` (PyPI) reads the importtime
  output and names the candidates. No dependency: it runs once, on a developer's machine.
- **Python 3.15:** PEP 810's explicit `lazy import` keeps the declaration at module level. Our floor is 3.14, so
  this is a note for the next floor bump, not a change now.
- **Not this:** PyOxidizer or a frozen binary. The laptop installs from a wheel through `ad-update`, and that path
  is tested on three shells; a second packaging would double the Windows matrix.

### 3c. The server

The server is already the shape the research recommends: SSE for push, a threaded stdlib server, `no-store` on
API answers, weak ETags and gzip on static files. Two things could still move:

- **The 15 s `loadDesk` poll** (`static/app.js:1845`) runs beside the SSE stream. If every change the poll can
  see is also an event on the stream, the poll can become a fallback that runs only when `EventSource` is closed.
  That is a measurement first ([desk-instant.md](desk-instant.md)'s "one round trip per action"), then a removal.
- **Browsers cap HTTP/1.1 connections at about six per origin.** Each desk tab holds one SSE connection; the
  multi-viewer page ([fleet-dashboard.md](fleet-dashboard.md)) and an IDE pane ([fleet-ide.md](fleet-ide.md))
  open more. Worth a row in `ad-fleet engines`: how many tabs before the seventh request queues.

**Not this:** the free-threaded build (§7), and `concurrent.interpreters` (PEP 734): the poller and the fold are
I/O-bound and already on threads with no contention measured.

### 3d. Telemetry: let the Copilot CLI say what it cost

Today the fleet learns a session's cost from `--usage-output-file` after the fact (`spend.py`), and the event
contract says plainly that per-turn cost is not in the stream. The Copilot CLI ships an OpenTelemetry exporter
(vendor guides for OpenObserve, Last9, LangWatch, Opik and Grafana all document the same variables, and GitHub
announced enterprise-managed export on 2026-07-08):

- `COPILOT_OTEL_ENABLED=true`, `COPILOT_OTEL_EXPORTER_TYPE=otlp-http|file`, the standard `OTEL_EXPORTER_OTLP_*`
  variables; metrics include token-usage histograms, operation durations and tool-call counts; prompt text is not
  exported unless content capture is turned on. **verify**: every one of these pages is a vendor's.
- **The `file` exporter is the one for us.** It writes OTLP JSON to a path, which the supervisor can set per agent
  under `~/.agentdata/fleet/<repo>/` and `events.py` can tail by byte offset exactly as it tails `events.jsonl`.
  No socket opens on the laptop; the policy that forbids MCP is not touched; the contract gains additive kinds
  (`tokens`, `tool_duration`) and `spend.py` gets per-turn numbers for the meter ([plan-meter.md](plan-meter.md)
  M1–M4, "whether premiumRequests is per turn or per session" — the exporter may simply answer it).
- If the file exporter does not exist or is not what the guides say, the fallback is a 40-line OTLP/HTTP receiver
  on the loopback server we already run (`/api/otlp`, POST only, token on the URL like every other route).
  agent-dashboard does exactly this per host (an OTLP receiver on 4318) to show cost per agent.
- **DuckDB's `otlp` community extension** reads OTLP JSON and JSONL with SQL, including in the browser through
  DuckDB-WASM. Not a dependency: a developer's tool for the day someone asks "what did Tuesday cost per tool".

### 3e. Lint and types

The repository checks its shell, its PowerShell and its JavaScript in CI, and its Python with tests alone.

- **ruff** does lint and format in one binary and is fast enough to run on every file on every push. Adopt it the
  way `tests/hygiene_baseline.json` was adopted: a baseline of today's findings, a test that the count only goes
  down, `ruff format --check` on new files only until the one big reformat is agreed. Rule set: `E, F, I, UP, B`
  to start; `UP` targets 3.14 syntax, which the floor already guarantees.
- **Type checking:** `ty` is still beta (0.0.x, breaking changes between versions, ~15% typing-spec conformance
  per one comparison). Not yet. If a checker is wanted, `pyright` in basic mode on `agentdata/fleet/` first, with
  the same ratchet. Astral's ownership changed in 2026 per two secondary sources; **verify** before depending on
  the roadmap.

### 3f. Data

- **`events.norm.jsonl`, `skills.json`, `spend.json`** are the fleet's history. Two tools make them queryable
  without a schema change: `sqlite-utils insert --nl` into a scratch database (then `datasette` to browse), or
  DuckDB's `read_json` straight over the files. Both are developer tools, neither a dependency. The catalogue's
  FTS5 table is the right production index and stays.
- **The hygiene ratchet** (`tests/hygiene_baseline.json`) already is the pattern for every "only goes down" rule
  above (ruff findings, testmon-skipped shards never gating). One mechanism, more rows.

## 4. Tools for what we use most

### 4a. Atlassian: pncli first, these as references

| Tool | What it does | What we would take |
|---|---|---|
| **mark** (kovetskiy, Go, Apache-2.0, ~1.6k stars) | syncs Markdown to Confluence: page addressed by `Space`/`Title`/`Parent`/`Label`/`Attachment` headers (HTML comments or YAML front matter), creates missing parents, uploads referenced images, renders Mermaid/D2/PlantUML through macros, `--dry-run`, link check, Cloud and Server | **the header contract.** `ad-confluence publish <file.md>` needs an address; mark's is proven and a Markdown file carrying it is portable. Nothing to install: `confluence.py` already converts, and pncli already posts |
| **atlassian-skills** (`atls`, PyPI) | Jira, Confluence, Bitbucket and Bamboo for Server/Data Center; uses **cfxmark** for lossless Confluence XHTML ↔ Markdown | **cfxmark** is the reference for the round-trip `confluence.py` does one way. The mis-routed `confluence-read` needs the other way (storage format → Markdown an agent can read); compare before writing it |
| **coji** (Go), **confluence-cli**, **bitbucket-cli `bkt`**, **jira-cli** | Cloud-first CLIs | nothing: pncli covers them, and 0.20.0 settled that we use it directly |

### 4b. Power BI: the rules seam

| Tool | What it does | What we would take |
|---|---|---|
| **PBI Inspector v2** | rules-based checks over a report's PBIR JSON; rules are JsonLogic with JsonPath/JsonPointer selectors; runs on a desktop or in CI | **the rule format.** `ad-pbip check` validates against the vendored schemas (0.19.0) and carries its other checks in code. A `rules.json` of JsonLogic rows is a DataTable for report lint: the operator adds "no visual wider than it is tall on a mobile page" without a release. The base rules file is a starting list |
| **Tabular Editor 2** (free) | TMDL import/export, BPA rules, C# scripting; 2.29.0 adds DAX UDFs and matches Desktop's TMDL serialisation | already the deploy path (`pbi-deploy-te2`). Its **Best Practice Analyzer rules** are JSON too, and `pbi-model-audit` could run them headless instead of re-deriving them |
| **pbi-tools** | TMDL extract/convert/compile/deploy | already credited ([pbi-tools-parts.md](pbi-tools-parts.md)); the TMDL verbs are the ones to re-read now that PBIP is GA (Sept 2026) and PBIR is Desktop's default (March 2026) |
| **pbip-documenter**, **pbip-studio** | browser documentation from TMDL; a Windows PBIP toolkit (MIT) | reference only. `ad-pbip` projects the model already; documenter's output is a shape to compare against for `pbi-report-plan` |
| A **PBIR reference-integrity** check (a community validator) | dangling bookmarks → deleted pages or visuals | a rule `ad-pbip check` does not have and the schemas cannot express. One function |

### 4c. The Copilot CLI we drive

- **Official programmatic page** (GitHub Docs): `-p`, `-s`, `--allow-tool`, `--allow-url`, `--no-ask-user`,
  `--model`, `--share=<path>` (the full transcript as Markdown), `--share-gist`. JSON output, hooks and resume are
  **not** on that page; `--output-format json`, which the fleet uses, is documented by third parties and by two
  open issues this month asking for its event shape. The fleet's `raw` kind and "unknown kinds never raise" rule is
  the right defence; `fleet-spike.md`'s method (measure on a machine) is how to re-pin it after each CLI release.
- **`--share=<path>`** is new to us: a Markdown transcript per session, written by the CLI. For the OneNote worklog
  ([plan-onenote-worklog.md](plan-onenote-worklog.md), W-D3 "facts only or the agent's prose?") it is the
  agent's prose without a model turn of ours. Worth one sitting to see what it contains and whether it redacts.
- **Hooks** (`preToolUse`, `postToolUse`) appear on one unofficial reference only. If they exist, the approval
  gate could sit *in front of* a write instead of reading `denied` after it. **verify** on the laptop.

### 4d. Skills and the marketplace

- The SKILL.md format is an open standard (agentskills.io, Dec 2025) and runs in Claude Code, Codex CLI, Cursor
  and Gemini CLI as of mid-2026; the standard defines no marketplace, so registries differ.
- **skills.sh** (Vercel): `npx skills add owner/repo`, ranking by install telemetry, ~670k listings by June 2026,
  anyone may publish, and Trail of Bits bypassed its malicious-skill detector. **A curated registry** of ~80
  skills with static analysis and Snyk scans takes the opposite stance; Chainguard sells org-scoped registries.
- For us: `fleet.skills.source` already takes any git URL or folder. Two cheap additions: accept a skills.sh
  `owner/repo` as a source spelling (it is a git repository underneath), and show on the marketplace page what
  the *source* says about a skill (its install count, when it was last changed) next to what *our ledger* says
  (uses, success rate, repositories). The ledger is the trust signal the registries lack; keep it first.

### 4e. Fleets like ours

| Project | Shape | Worth borrowing | Not for us because |
|---|---|---|---|
| **agent-of-empires** (Rust, MIT, ~2–3k stars) | TUI + web; one tmux session per agent; a worktree per agent, created and cleaned automatically; supports Copilot CLI among six CLIs; optional Docker sandbox | the **worktree lifecycle** as a first-class object (ours is `worktree-tidy`, a skill); a session list that is also a lane list | tmux; the laptop is Windows and runs agents through `proc.py` and ConPTY consoles |
| **agent-dashboard** (Python FastAPI + React, Apache-2.0) | hub + per-host daemons; agents in PTYs relayed over Socket.IO to xterm.js, output coalesced per animation frame; a local **OTLP receiver per host** for tokens and cost; **agent profiles as YAML**; "isolate in worktree" **auto-on when a second agent targets the same project and host**; status *working / idle / permission-waiting* derived from OTLP activity and terminal patterns | the three bold items: §3d, §5, §6 | multi-host and containers; we are one laptop and a policy |
| **amux** (one Python file, MIT) | dozens of Claude Code sessions, a web dashboard, a **self-healing watchdog**, a kanban | the watchdog's posture: restart on a known-bad state, never on a quiet one; compare with `renew.py` | tmux |
| **Multica**, **Pane**, **emdash**, **flowmux**, **Crystal**, **cmux** | issue workspaces and parallel runners | the vocabulary: every one of them has settled on "one worktree per task" and "a lane per agent", which is the fleet map's model too | tmux or macOS |

The fleet's distinguishing facts hold up well against this list: nothing here has an approval gate with digests,
a normalised event contract with a ratchet, or a phone lane through OneDrive. What they have and we do not is
**per-turn cost in the UI** (§3d) and **worktrees offered rather than refused** (§6).

## 5. UI ideas, in the desk's own terms

The desk's rules are written down and this spike does not argue with them: no framework, no bundler, one flat
script, "a picture must say something the DOM cannot" ([desk-rendering.md](desk-rendering.md)), a 50 ms gesture
budget. Inside those rules:

| Idea | What | Why now | Cost |
|---|---|---|---|
| **Strict types for the whole desk** | `strict: true` in `tsconfig.json`; add `settings.js` and `probe.js` to the checked set | TS 7 makes the check cheap enough to run on every push; two served files are unchecked | cheap, then a day of fixes |
| **Container queries for the tiers** | the pane tiers switch on widths set as `fleet.tiers.*` ([desk-window.md](desk-window.md)) in JS; CSS `@container` lets each pane answer to *its own* width | fewer resize listeners on the gesture budget; a pane dropped into the IDE at an odd width lays itself out | medium; measure the swap frame time (16.7 ms median today) |
| **A live terminal pane** | xterm.js (MIT, no bundler needed) rendering a ConPTY-backed console inside the desk, the agent-dashboard pattern | the console is a separate window today (`ad-fleet console`); a pane keeps the operator on the desk | dear: ConPTY from Python needs `pywinpty` or `ctypes`; a vendored xterm.js is ~300 KB against a 200 KB static budget, and one more npm package to vet on the laptop. A sitting first |
| **uPlot for the activity trace** | canvas charts, zero dependencies, ~50 kB, script-tag build, cursor sync across charts | **not yet**: the trace is "an hour in sixty numbers" drawn in a few lines, and the rendering rule says a library earns its bytes only when charts multiply. Named so the day cost per tool (§3d) has a candidate | — |
| **Lit, htmx, VanJS** | small component or hypermedia libraries | **no**: [desk-components.md](desk-components.md) §not here is explicit, and `patchList` is 30 lines | — |

## 6. UX ideas

- **Risk-tiered approvals.** Every 2026 HITL guide read for this spike (§10) says the same thing in different
  words: a binary approve/deny on every action becomes a rubber stamp; tier by reversibility and blast radius; let
  the operator approve a *plan within invariants*; batch the low tier; offer **undo instead of approve** where
  undo is real. Mapped onto our kinds: `git-push` to the agent's own branch is reversible (force-with-lease back),
  `bitbucket-pr` as a draft is reversible (close), `jira-comment` and `jira-transition` are not, and
  `confluence-publish` is a version. A tier column on the gate, a "do it, I can undo" lane for the first two, and a
  batch for a sweep's dozen `git-push` rows would cut clicks without cutting the record: every undo is an approval
  record with `via: undo`.
- **Worktrees offered, not refused.** The one-agent-per-repo lock is right; the response to a second ticket on
  the same project is a refusal today. agent-dashboard's answer is a toggle that turns itself on: *this project
  already has an agent; start this one in a worktree?* The fleet map already draws worktrees as lanes, and
  `worktree-tidy` already cleans them.
- **Agent profiles as data.** Launch flags, tier, allow-lists and `AGENTS.md` facts per project live in code and
  in the registry's `extra`. A profile file per project (YAML, in the fleet directory) that the launch reads is
  what lets the operator say "this project runs `efficiency` with no shell" without a release.
- **Tell the screen reader what the toast says.** The notifier's rules (state transitions only, a 300 s cooldown
  per state, quiet hours) are better than the ARIA guidance asks for; the page should mirror them in one
  `role="status"` region for `done`/`needs-you` and one `role="log"` for the event feed, debounced to the same
  cooldown, empty at load. [desk-motion.md](desk-motion.md) already honours `prefers-reduced-motion`; pairing it
  with the live region (text updates on, transitions off) is the one combination no source covered.
- **Per-turn cost where the eye already is.** Once §3d lands, the tile's `says` line gains *· 12k tokens this
  turn*; the meter's reserve step-down becomes visible as it happens rather than at `ad-fleet spend`.
- **A worklog someone else can read** is [plan-onenote-worklog.md](plan-onenote-worklog.md); `--share` (§4c)
  may hand it the agent's own account for free.

## 7. What not to adopt, and why

| Candidate | Why not |
|---|---|
| tmux-based managers (agent-of-empires, amux, flowmux, workmux) | the laptop is Windows; agents run through `proc.py` with `taskkill /T` trees and ConPTY consoles; the lesson transfers, the binary does not |
| Free-threaded Python 3.14t | `keyring` and `pyodbc` are C-extension paths; packages that are not free-threading-ready silently re-enable the GIL on import; nothing in the fleet is CPU-bound enough to measure a gain |
| `ty` | beta, breaking between versions, low spec conformance; revisit at 1.0 |
| pytest-split, a second sharder | `tests/shard.py` already does it from measured durations |
| A JS framework or chart library on the desk | the rendering rule; 154 of 200 KB already spent |
| DuckDB or Datasette as runtime dependencies | the catalogue's SQLite FTS5 is the production index; both tools are for a developer's afternoon over JSONL |
| A hosted skills registry as the source of trust | the ledger knows what *we* ran and whether it worked; a registry knows installs |
| A new npm package on the laptop where a vendored file or a hand-written stub does the job | every npm package is vetted before install and reaches the registry only through Playwright's route ([windows-verification.md](windows-verification.md) §0a); CI may `npx` what it likes, the laptop pays for each one |

## 8. Measurements this spike proposes

Each row joins [windows-verification.md](windows-verification.md)'s format: a date and a host before anyone builds
on the answer.

| Id | Question | How |
|---|---|---|
| T1 | Coverage step time with the `tracing` core vs `sysmon`, and whether the installed coverage already defaults to `sysmon` | two CI runs, same commit, `COVERAGE_CORE` set each way |
| T2 | Import time of `agentdata.cli` and of `ad-view`'s path on the laptop | `python -X importtime`, top 20 lines kept |
| T3 | Does `COPILOT_OTEL_EXPORTER_TYPE=file` exist, what does it write, and does it redact? | one `copilot -p` run with the variables set; read the file |
| T4 | Does `--share=<path>` redact, and what does the transcript hold per turn? | one run; compare with `events.jsonl` |
| T5 | Do `preToolUse`/`postToolUse` hooks exist in the installed CLI? | `copilot --help` and the config directory |
| T6 | How many desk tabs before the seventh SSE request queues, per engine | `ad-fleet engines` row |
| T7 | testmon on one Windows shard: tests selected and minutes saved on a docs-only and a one-module change | two runs of the same shard |

## 9. Decisions for the operator

| | Question | Default until answered |
|---|---|---|
| TOOLS-D1 | ruff: add with a ratchet, add with one big reformat, or not at all? | ratchet; no reformat |
| TOOLS-D2 | Telemetry from the Copilot CLI: file exporter tailed by the fold, a loopback receiver, or neither? | file exporter if T3 says it exists; else none |
| TOOLS-D3 | testmon on the Windows shards? | the developer's loop only until T7 shows the saving |
| TOOLS-D4 | A `rules.json` seam for `ad-pbip check` in PBI Inspector's JsonLogic shape? | yes, empty by default |
| TOOLS-D5 | Risk tiers on the approval gate with an undo lane for `git-push` and draft `bitbucket-pr`? | tiers shown, undo lane off until the approval-integrity seams of #537 cover `via: undo` |
| TOOLS-D6 | Worktree offered on a second ticket for a busy project? | ask, default no |
| TOOLS-D7 | A terminal pane in the desk (xterm.js + ConPTY)? | no; a sitting to measure the bytes and the PTY first |
| TOOLS-D8 | Type the three.js-importing desk files with a hand-written `three.d.ts` stub, or vet `@types/three`? | the stub; `@types/three` only if the stub grows past the surface a person can keep honest |

## 10. Sources (read 2026-10-10)

- pytest: [awesome-pytest-speedup](https://github.com/zupo/awesome-pytest-speedup); [exante, 8.5× faster suites](https://exante.eu/press/blog/2925-how-we-made-python-pytest-suites-8-5x-faster/); [pytest-testmon](https://dev.co/testing/open-source/pytest-testmon); [pytest-xdist docs](https://pytest-xdist.readthedocs.io/en/latest/_sources/index.rst.txt); [Playwright pytest plugin reference](https://playwright.dev/python/docs/test-runners).
- coverage: [Faster branch coverage measurement](https://nedbatchelder.com/blog/202503/faster_branch_coverage_measurement); [coverage 7.7.0 release](https://newreleases.io/project/pypi/coverage/release/7.7.0).
- Python start-up and builds: [Python 3.15 lazy imports](https://www.c-sharpcorner.com/article/python-3-15-lazy-imports-measuring-startup-time-in-large-applications); [slowimports](https://pypi.org/project/slowimports/); [python lazy imports](https://www.danilchenko.dev/posts/python-lazy-imports/); [PEP 779 explained](https://pydevtools.com/handbook/explanation/what-is-pep-779/); [free-threaded 3.14 in practice](https://www.buildmvpfast.com/blog/free-threaded-python-3-14-should-you-switch-2026).
- Types: [ty beta](https://pydevtools.com/blog/ty-beta/); [ty complete guide](https://pydevtools.com/handbook/explanation/ty-complete-guide/); [pyrefly vs ty 2026](https://www.pkgpulse.com/guides/pyrefly-vs-ty-python-type-checkers-2026); [TypeScript 7 released (InfoQ)](https://infoq.com/news/2026/08/typescript-7-released/); [Microsoft bets on a native compiler](https://adtmag.com/articles/2026/07/10/microsoft-bets-typescript-future-on-a-native-compiler.aspx).
- Telemetry: [OpenObserve, GitHub Copilot tracing](https://openobserve.ai/docs/integration/ai/github-copilot-tracing/); [hve-core, Copilot OTel metrics](https://microsoft.github.io/hve-core/docs/customization/copilot-otel-metrics); [LangWatch, Copilot CLI](https://langwatch.ai/docs/coding-agents/github-copilot-cli); [Opik, GitHub Copilot](https://www.comet.com/docs/opik/integrations/github-copilot.md); [DuckDB otlp extension](https://duckdb.org/community_extensions/extensions/otlp); [otelq](https://pypi.org/project/otelq/); [local-first OTel for agent debugging](https://oneuptime.com/blog/post/2026-02-06-local-otel-ai-coding-agent-debugging/view).
- Copilot CLI: [Running Copilot CLI programmatically (GitHub Docs)](https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically); [Copilot CLI flags in late 2026](https://dev.to/selinorlov/copilot-cli-in-late-2026-the-flags-i-actually-use-in-scripts-4b0g); [JSON event stream issue (orb #33)](https://github.com/antshc/orb/issues/33); [unofficial reference](https://htekdev.github.io/copilot-cli-reference/).
- Fleets: [agent-dashboard](https://github.com/dustinblack/agent-dashboard); [agent-of-empires guide](https://betterstack.com/community/guides/ai/agent-of-empires/); [awesome-cli-coding-agents](https://github.com/bradagi/awesome-cli-coding-agents); [ai-agent-session-center](https://github.com/coding-by-feng/ai-agent-session-center); [pi-agent-dashboard](https://github.com/BlackBeltTechnology/pi-agent-dashboard); [workmux](https://github.com/mic92/workmux).
- Atlassian: [mark](https://github.com/kovetskiy/mark); [atlassian-skills](https://pypi.org/project/atlassian-skills/0.3.3/); [coji](https://pkg.go.dev/github.com/mgilbir/coji); [markdown-confluence action](https://github.com/marketplace/actions/markdown-confluence).
- Power BI: [VisOps with PBI Inspector](https://blog.crossjoin.co.uk/2023/10/01/visops-for-power-bi-with-pbi-inspector/); [Tabular Editor (SQLBI)](https://www.sqlbi.com/tools/tabular-editor/); [pbi-tools TMDL](https://pbi.tools/tmdl/); [PBIP GA guide (Red Gate)](https://www.red-gate.com/simple-talk/data-analytics/powerbi/power-bi-project-pbip-format-guide/); [pbip-studio](https://github.com/mohammedadnant/pbip-studio); [pbip-documenter](https://github.com/JonathanJihwanKim/pbip-documenter); [TMDL for report design](https://draftbi.com/blog/tmdl-for-report-design); [FabricTools.Items.Report](https://www-0.nuget.org/packages/FabricTools.Items.Report).
- Skills: [What is an agent skills registry (Atlan)](https://atlan.com/know/ai-agent/ai-agent-skills/agent-skills-registry/); [skills.sh research](https://rywalker.com/research/skills-sh); [what are agent skills (parallel.ai)](https://parallel.ai/articles/what-are-agent-skills); [agent skills (pinggy)](https://pinggy.io/blog/ai_agent_skills/).
- UI: [uPlot](https://openapps.pro/packages/uplot); [unsuckjs](https://scriptagc.wasmer.app/https_unsuckjs_com); [Lit](https://feedbagel.com/post/lit-a-lightweight-javascript-library-for-simplified-web-components-development); [htmx](https://feedbagel.com/post/htmx-lightweight-javascript-library-for-modern-html-development); [SSE: streaming from server to browser](https://flaviocopes.com/server-sent-events.md); [larzsse](https://pypi.org/project/larzsse/).
- UX: [10 HITL tool approval patterns](https://www.kunalganglani.com/blog/tool-approval-patterns-ai-agents); [approval fatigue](https://www.buildmvpfast.com/blog/approval-fatigue-agent-permission-ux-2026); [HITL patterns 2026](https://myengineeringpath.dev/genai-engineer/human-in-the-loop/); [agent UX checklist](https://www.agenticwire.news/article/agent-ux-design-patterns); [HITL design course outline](https://codemia.io/courses/introduction_to_agentic_ai/human_in_the_loop_design); [W3C live region best practices](https://www.w3.org/wiki/PF/ARIA/BestPractices/LiveRegion); [aria-live (a11y-collective)](https://www.a11y-collective.com/blog/aria-live/); [live regions for dynamic content (UXPin)](https://www.uxpin.com/studio/blog/aria-live-regions-for-dynamic-content/).
