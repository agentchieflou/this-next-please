# Implementation brief: epics #162 and #170

_For the agent that builds them — Antigravity, or any other. Written 2026-09-11 against commit `81b6f9c` on branch
`claude/adoring-gauss-bf40fr` (PR #161, unmerged). Every code line cited below was read at v0.9.0 (`c8ec7aa`, the
tip of `main` on that date) and may have drifted by a few lines; the symbol names will not have. This brief tells
you how to work in this repository and what each slice must do; the two plans tell you why._

## 0. Before the first line of code

Read these, in this order. They are short and every one of them will refuse a change that ignores it.

1. `AGENTS.md` — the canonical rules for the *agents this repository runs* (Luna, headless Copilot). You are a
   developer, not Luna, but rules 4, 7, 8 and 9 shape what you are building, and rule 10 is one of the things
   #165 changes.
2. `HANDOFF.md` — read "Windows facts learned on the laptop (do not regress)" and "Rules for you" twice.
3. `docs/testing-this-repo.md` — how the suite is run, what every guard refuses, and the regression-file convention.
4. `docs/plan-handoff.md` (epic #162) and `docs/plan-sessions.md` (epic #170) — the designs. Every slice card below
   names the plan section it comes from; the card is the contract, the plan is the reasoning.
5. The fleet's own documentation, which the slices extend: `docs/fleet.md`, `fleet-events.md`, `fleet-dashboard.md`,
   `fleet-intake.md`, `fleet-approvals.md`, `fleet-notifications.md`, `fleet-ide.md`, `fleet-lifecycle.md`,
   `fleet-layouts.md`, and `plan-desk-refactor.md` (the previous epic on the same page, and the style every plan
   here follows).

**Environment.** Python 3.12 or newer is required (`pyproject.toml` refuses older). Then:

```bash
pip install -e ".[dev]"
playwright install chromium          # or point AGENTDATA_CHROMIUM at a Chromium you already have
python -m pytest -q -m "not slow"    # the whole suite; about two minutes on Linux
python -m pytest -q -m browser       # only the rendered-page tests
python -m pytest -q --shuffle-seed 1 # order dependence; CI runs two seeds
```

**Known noise.** Three benchmark-timing tests compare millisecond medians and fail in a slow sandbox with no code
change: `tests/test_perf_loop.py::test_the_full_loop_on_a_covered_node` and two in `tests/test_testing_bench.py`.
If those three are the only failures, and they fail with the tree stashed too, they are the machine's. Everything
else is yours.

**Branches.** Until #161 merges, the two plans and this brief exist only on `claude/adoring-gauss-bf40fr`. Branch
each slice from it (or from `main` after the merge). One branch and one draft pull request per slice, titled with
the issue number, body saying what changed and how it was verified, `Closes #<n>` in the body. Never merge; the
operator merges. Do not bump `version` in `pyproject.toml` or add a version heading to `CHANGELOG.md` in a slice
PR — the release PR does both, and a test keeps the two in step.

## 1. The non-negotiables

These are the rules a test, a CI job, or a documented decision will enforce. Each names where it lives so you can
read the reasoning before you fight it.

| Rule | Enforced by |
|---|---|
| A new `ad-*` verb needs a `[project.scripts]` entry, a row in `agentdata/__main__.COMMANDS` pointing at the same function, an `int` return (never a bare `sys.exit`), and a case in `tests/contract_cases.py` | `tests/test_entrypoints.py`, `tests/test_contract.py` |
| A doc or skill may name only an `ad-*` command that is installed; a plan doc whose status line begins `_Status: PLANNED` is exempt until it says IMPLEMENTED | `tests/test_entrypoints.py::test_docs_only_mention_commands_that_exist` |
| Every `SKILL.md` stays under 120 lines, imperative, numbered, with an explicit STOP or handoff at the end | `tests/test_skills.py` |
| `textio.norm_path()` is the only path canonicaliser; never hand-write `.replace("\\", "/")` | `tests/test_props_paths.py::test_no_hand_written_path_canonicaliser` |
| Every subprocess goes through `agentdata/proc.py`; every external file is read through `agentdata/textio.py` | `HANDOFF.md`, `tests/test_proc.py` |
| A refusal is exit 2 with `ok: false` and a `hint`; every refusal has a row in `docs/refusals.md` naming its test, and the count of refusal call sites is pinned | `tests/test_refusals.py` |
| Agent-facing stdout is TOON with a `meta.ok`; no ANSI when piped; byte-identical under `NO_COLOR=1` | `tests/test_contract.py` |
| Coverage floors are per module, per platform, and ratchet up only | `.github/scripts/coverage_floors.py` |
| A failure seen on a real machine becomes `tests/regressions/test_<yyyymmdd>_<host>_<short>.py`, docstring quoting what the machine printed and linking the issue | `tests/regressions/test_convention.py` |
| Browser tests assert on the rendered page — computed styles, hit-testing, the text a person reads — never on the source text of `app.js`; they skip with a named reason without a browser and never fail for its absence | `docs/testing-this-repo.md` §The browser tests, `tests/test_fleet_desk_regressions.py` |
| The page globals the browser tests call — `toggleTileSize`, `toggleTilePin`, `moveTile`, `choose`, `getEffectiveOrder`, `getLayoutArrangement`, `desk`, `LAYOUT` — are a public API; do not rename them | `tests/test_fleet_desk_regressions.py` |
| The fleet writes only under `~/.agentdata/fleet/` (or `$AGENTDATA_FLEET_DIR`). The single exception is `<repo>/.agent/in/<KEY>/`, on a click or a start, always an event; `ad-state` is the only writer of `.agent/state.json` and the fleet *asks* it (`inbox._ask_ad_state` is the pattern) | `tests/test_fleet_e2e.py` walks four repositories after a run |
| `events.norm.jsonl` is additive at schema `1`: kinds may be added, fields may be added, nothing is removed or renamed; unknown kinds never raise; `redact()` runs on every payload | `docs/fleet-events.md`, `tests/test_fleet_events.py` |
| There is no `needs_human` event and there will not be one; states are derived by `agentstate.classify` in a fixed order | `docs/fleet-events.md` §What is deliberately not here |
| The IDE shells host the page and relay; they contain no rule logic, name no state but four, and act on no SSE event but `notify` | `tests/test_fleet_shells.py`, `docs/fleet-ide.md` §What a shell must do |
| `agentdata/fleet/static/` has no framework, no build step, no CDN, no CSS framework; the server sends `Content-Security-Policy: default-src 'self'` | `tests/test_fleet_serve.py` |
| An agent is launched with an enumerated allow-list, `--disable-builtin-mcps` and `--no-ask-user`; never `--allow-all*` or `--yolo` | `agentdata/fleet/launch.py`, `docs/fleet-spike.md` |
| A layout decision is the operator's, made on the real screens and recorded in `docs/fleet-layouts.md` first; no code concludes what the sitting has not | `docs/fleet-layouts.md` |
| Commit messages are Conventional Commits in this repo's voice — `feat: the thing, said as a sentence` | `AGENTS.md` rule 9, `git log` |

**Decisions already made.** Do not re-open these; the plans say why.

- AGENTS.md rule 10 is refined in #165 — two readings that lead to different work block; a safe, reversible default
  is assumed and stated — **approved by the operator on 2026-09-11**, landing in the same commit as `ad-state ask`
  and never before it.
- The prompt the fleet gives an agent stays one line and never carries ticket text; `{handoff}` names a directory
  and counts.
- A dropped file is identified by its git blob hash, never by a path from the browser; nothing but a hash leaves
  the page until the operator clicks *attach a copy*.
- Shells post paths; the server decides which checkout owns them.
- `hidden` ships per layout (shared across windows); the sitting may move it per window later.
- The fleet never creates a git worktree; it registers what the scan finds.
- Copilot's `~/.copilot/session-store.db` is read, never written, behind a doctor row; `--continue` and
  `--session-id` stay unused.
- One live agent per registered working tree, still. Every *resume* onto a live checkout is a refusal first and a
  deliberate second press.

**Laptop measurements.** Each plan ends with open questions that can only be answered on the operator's Windows
laptop in Edge, PyCharm's JCEF tool window and VS Code's Simple Browser. You cannot measure those. When a slice
depends on one, build the branch the plan names as the default, add the row to `docs/windows-verification.md`
marked *not yet measured*, and say so in the PR. Never guess a measurement into a doc — this repository reverted a
fabricated sitting once (`docs/fleet-layouts.md`, the boxed note) and the rule exists because of it.

## 2. Order of work

```
#163 contract ─┬─ #164 pick-up ──────────────┐
               ├─ #165 the ask ──┬───────────┤
               └─ #166 scope/page ┴─ #167 IDE ┤─ #168 agent honours scope ─ #169 proof
                                              │
#171 sessions ─┬───────────── #174 switcher ──┴─ #175 checkouts ─ #176 proof
#172 desk back ── #173 hide/reopen ─┘
```

**First session.** Take #171 and #163 in that order. #171 is entirely server-side, fixes a real defect (a `send`
after a dead start resumes the previous conversation), and needs no page work. #163 is the contract every other
handoff slice lands on. Then #172, which is one split function and one test of the shutdown path. After those
three, #164, #165, #166 and #173 can proceed in parallel.

## 3. Working an issue

1. Read the issue and the plan section it names. The issue's **Build this** list is the scope; its **Acceptance
   criteria** are the tests you will write; its **Out of scope** is where you stop.
2. Open every seam in the slice card below and read the surrounding function before touching it. The line numbers
   are from `c8ec7aa`; the names are stable.
3. Write the failing test first, named after the acceptance criterion in this repository's style
   (`test_a_reply_after_a_dead_start_refuses_instead_of_resuming_yesterday`). A browser criterion is a
   rendered-page test in `tests/test_fleet_desk_regressions.py` or a sibling file.
4. Implement the smallest change that passes. Reuse the pattern the plan's *What is reused* section points at
   before writing a new one.
5. Run `python -m pytest -q -m "not slow"`, then `-m browser`, then one shuffled seed.
6. Update the documents the slice touches: the `docs/fleet-*.md` page that describes the feature, `docs/refusals.md`
   for a new refusal, `docs/fleet-events.md` for a grown event, `docs/fleet-ide.md` for a shell step. A feature that
   is not in the docs is not done.
7. Open the draft PR. In the epic's checklist the box is ticked on merge, by the operator.

## 4. Slice cards — the handoff (#162)

Plan: `docs/plan-handoff.md`. Ground rules: `docs/plan-handoff.md` §Ground rules.

### #163 — A: the contract

Plan section: §Where everything is written down. Depends on nothing; everything else in #162 depends on it.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/static/app.js` | 1022–1036 | `dispatch()`; the cross-project override is offered by `/jira_project/.test(r.error)` — a regex over prose |
| `agentdata/fleet/serve.py` | 1189–1190, 1385–1388 | `_refuse()` builds `{ok:false, error, hint}`; the one funnel every `ServeError`, `SupervisorError`, `ApprovalError`, `InboxError`, `CatalogueError` passes through |
| `agentdata/fleet/supervisor.py` | 336–368, 371–418 | `check_ticket` and `start`: the refusals whose prose the page matches today |
| `agentdata/fleet/static/app.js` | 1013–1017, 181–186 | the board row sets `text/plain`; the tile-reorder drag sets `application/x-agentdata-tile` — mirror the latter |
| `agentdata/fleet/static/app.js` | 1211–1213 | reads `r.attached`, `r.dir`, `r.why` flat |
| `agentdata/fleet/events.py` | 129–132 | `event()` nests those under `data` — so a successful attach renders *already there* |
| `agentdata/fleet/agentstate.py` | 24 | `TERMINAL_PHASES = ("pr_open", "done", "closed", "merged")` |
| `agentdata/fleet/supervisor.py` | 25 | `TERMINAL_PHASES = ("", "idle", "done", "closed", "merged")` — disagrees |
| `agentdata/state.py` | 11 | `PHASES` has `optimizing`, lacks `closed` and `merged` |
| `skills/state-update/SKILL.md` | 10 | the phase list lacks `optimizing` |
| `agentdata/fleet/events.py` | 37–57 | `KINDS` — reserve the new kinds here |
| `agentdata/cli.py` | 81 | `ad-pncli jira` accepts `choices=["search", "get"]`; `("jira","comments")` is already in `connectors/pncli.READ_VERBS` |

**Build.** A `code` on every 409 body and `dispatch()` switching on it; `application/x-agentdata-ticket` with
`text/plain` kept as the fallback; the kinds and fields the plan reserves (`question_opened` grows `id, choices,
default, want, blocking`; new `question_answered`, `handoff.brief`, `scope.added`; `started` grows `answers,
scope`; `friction` grows `severity`), documented in `docs/fleet-events.md`; `docs/fleet-handoff.md` for the
`.agent/in/<KEY>/` layout and its five inherited rules; the attach response fixed; one `TERMINAL_PHASES` imported by
the supervisor; `closed`/`merged` settled one way for `state.PHASES`; `optimizing` in the skill; `ad-pncli jira
comments`; Playwright helpers that build a `DataTransfer` with files in page context and dispatch `drop` on a tile.

**Tests to write.** Rendered-page: the override still appears after the refusal text is reworded; a successful
attach reads *attached → …* (must fail on the previous commit). Unit: the two terminal-phase tuples are one object
and `ad-state` accepts every phase either names; every new kind is redacted and resumable by `seq` and an older
fold ignores it; a `docs/refusals.md` row per new `code`.

**Out of scope.** Any card, any file drop, any skill change beyond the phase list.

### #164 — B: pick-up

Plan section: §Pick-up. After #163.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/launch.py` | 105, 176–190 | `DEFAULT_PROMPT = "Ticket {key}{summary}. Invoke skill session-bootstrap, then router."`; `prompt_for()` with `_Blanks` making unknown fields empty — add `{handoff}` the same way |
| `agentdata/fleet/supervisor.py` | 371–418, 413–415 | `start()` and the lock it writes; the brief is written before the spawn and refuses the start if it cannot be |
| `agentdata/fleet/board.py` | 148–178, 203–248 | `suggest()` (repo match) and `history()` (earlier dispatches of this key) |
| `agentdata/fleet/inbox.py` | 395–453, 478–499 | `attach()` — the destination rule, `safe_name`, the containment check — and `_ask_ad_state()`; the brief's write follows both |
| `agentdata/fleet/catalogue.py` | 755 | `where()` — the lookup for names the ticket mentions |
| `agentdata/fleet/serve.py` | 951–960, 1240–1252 | `/api/start` and `/api/board`; the Done check reads the board cache only |
| `agentdata/connectors/pncli.py` | 16–21, 116–124 | `JIRA_DEFAULT_FIELDS`, `ISSUE_RENAME`, `get-issue` — the one fetch the pre-flight makes |
| `agentdata/fleet/static/index.html` | 169–194 | the tile's why line, approval card, and bottom row — the dispatch card sits beside the approval card |

**Build.** `fleet/preflight.py` with the rows and the `ready | thin | blocked | unknown` rule in one table;
`GET /api/preflight?key=&repo=` and `ad-fleet preflight <KEY> [--repo]`; the dispatch card (rows, verdict, brief
box, drop zone wired later by #166, *Start* / *Start anyway*, `Enter`/`Esc`, the repo segment for *pick one*);
`fleet.preflight: false` skips the card; `start --brief` / `--brief-file` writing `brief.md`, emitting
`handoff.brief`, asking `ad-state set --input`, then spawning; `{handoff}` in the prompt; the catalogue lookup
saying when a match is in another repo.

**Tests to write.** Thin / ready / Done verdicts by example; `preflight` on an unreachable Jira prints `unknown`
rows, exit 0, and `start` still launches; a start with a brief produces the four artefacts in order, proven from the
event stream; the Jira request budget from #98's test plus one `get` per dropped key; a rendered-page drop reads the
verdict text.

**Out of scope.** Jira attachments; changing what `jira-triage` reads; auto-start on *ready*.

### #165 — C: the ask

Plan section: §The ask. After #163. Carries the approved AGENTS.md rule 10 change.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/state.py` | 11–14, 48–91 | `PHASES`, `apply()`; `open_questions` merge at 70–71 (append-only strings); "open questions persist until `--clear-questions`" at 89 |
| `agentdata/cli_state.py` | 87–93 | `--question`, `--clear-questions`, `--input` |
| `agentdata/fleet/events.py` | 200–218, 221–238 | `from_state()` emits `question_opened` when `open_questions` grows; `friction_event()` lifts only the unblock sentence — `severity` is never read |
| `agentdata/fleet/agentstate.py` | 22, 27–95, 98–138 | `_ASK_ENDINGS = ("?",)`; the `Fold`; `classify()` — the precedence table; questions outlive the turn (64–68) |
| `agentdata/fleet/supervisor.py` | 421–463 | `send()` — spawns `copilot --resume <session> -p <message>`; `stdin` is `DEVNULL` (309) so a reply is always a respawn |
| `agentdata/fleet/lifecycle.py` | 42–44 | `RESUME_PROMPT` — put the answer prompt beside it |
| `agentdata/fleet/static/index.html` | 171–187 | the approval card (the pattern for the question card) and `.say` |
| `agentdata/fleet/static/app.js` | 286–295, 391 | Send/Start wiring; the why line |
| `skills/jira-triage/SKILL.md` | 7–13 | step 8 (`jira get`), step 10 (untestable criterion → friction-log, STOP) |
| `skills/session-bootstrap/SKILL.md` | 11 | phase `blocked` → print the unblock sentence, STOP |
| `skills/router/SKILL.md` | 8 | `open_questions` non-empty → friction-log, STOP |
| `skills/friction-log/SKILL.md` | 16, 30–31 | `severity: blocker \| friction \| nit`; `ad-state set phase=blocked --question`; STOP |
| `AGENTS.md` | 20–25 | stop conditions; rule 10 |

**Build.** `ad-state ask` and `ad-state answer` (records with `id, q, choices, default, want, about, blocking,
asked`; strings normalised; `blocked_from` kept and restored); `question_opened` grown and `question_answered`
emitted from the state diff; the fold (blocking → `needs_human`, non-blocking → an *assumed* row, `friction.severity`
read, `nit` not folded as blocked); the question card with one *Send*, `POST /api/answer` and `ad-fleet answer`,
one resume for N answers; the skill steps; the AGENTS.md rule 10 rewording in the same commit as the verb, with
`HANDOFF.md` and every skill citing rule 10 saying the same thing.

**Tests to write.** A fake-copilot round trip (ask with choices → stop → answered from the tile → resume records
the answer → `phase=triaged`); three questions, one card, one Send, one `started` with three ids; an `--assume`
question leaves the tile `running` and can be overturned; a `nit` does not turn the tile red; skills under 120
lines and none ends a turn on an unanswered question without printing it; AGENTS.md rule 10 and `jira-triage`
step 10 name the same two outcomes.

**Out of scope.** Questions the fleet asks the agent; free-text "other" beyond the box; toast content.

### #166 — D: scope in the page

Plan section: §The scope, first channel. After #163.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/static/app.js` | 199–242 | the tile's `dragover` (unconditional `copy` + `drop-target` for non-tile drags) and `drop` (reads `text/plain` only at 240) — branch on `dataTransfer.files` *before* the ticket branch |
| `agentdata/fleet/static/app.css` | 389 | `.drop-target` — the outline that already promises a copy |
| `agentdata/fleet/serve.py` | 70, 1365–1393 | `MAX_BODY = 64 * 1024`; the POST funnel requires a JSON object — `attach-bytes` is the one route with its own cap |
| `agentdata/fleet/serve.py` | 930–945, 996–1001 | `_offer()` re-looks the file at click time; `/api/attach` — the pattern for *attach a copy* |
| `agentdata/fleet/inbox.py` | 19–40, 71–72, 395–453 | the constitution, `OFFER_TYPES`, `SIZE_CAP`, `attach()` — the destination rule and event to reuse with `source: "drop"` |
| `agentdata/fleet/catalogue.py` | 89 | `allows()` — the refused-name patterns a scope must also refuse |
| `agentdata/proc.py` | — | every `git` call goes through it |

**Build.** The page hashes each dropped file (SHA-1 over `blob <size>\0` + bytes, `crypto.subtle` with a plain-JS
fallback; `fleet.scope.max_hash_mb` default 64; folders via `webkitGetAsEntry`, capped at 200);
`POST /api/scope/resolve` (candidates by basename from `git ls-files` and `git ls-files --others
--exclude-standard`, hashed on the server, `resolved | ambiguous | unmatched`); `POST /api/scope {repo, paths, why,
how}` appending `scope.toon`, emitting `scope.added`, asking `ad-state set --input`, queued when `running`; the
scope card (rows with `how`, *tell it now*, the pick, the *attach a copy* offer); `POST /api/attach-bytes` under
`fleet.attach.max_mb` (default 10) with the inbox's rules.

**Tests to write.** Rendered-page: bytes equal to a tracked file resolve to its path; the same bytes under another
name still resolve; unrelated bytes read *not a file of <repo>*. A git-ignored file never resolves. Only the hash
request leaves the page until *attach a copy* (count requests). A drop on a running tile is queued and named in
the next `started` prompt. `scope.toon` only under `.agent/in/<KEY>/`, every write an event, the four-repo walk
clean.

**Out of scope.** IDE paths (#167); what the agent does with the scope (#168); moving a file.

### #167 — E: scope from the IDE

Plan section: §The scope, second channel. After #166.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `ide/vscode/src/extension.ts` | 132, 153–162, 219 | `enableScripts` only; the page as an `<iframe>` inside the webview; the workspace root matched against registered paths |
| `ide/vscode/src/fleet.ts` | 240 | `startAgent()` — the shape of a POST from the shell |
| `ide/vscode/package.json` | — | three commands, one view, three settings today |
| `ide/jetbrains/src/main/kotlin/com/agentdata/fleet/FleetToolWindow.kt` | 56, 82, 114 | `JBCefBrowser().loadURL`; the `#tile=` anchor |
| `ide/jetbrains/src/main/kotlin/com/agentdata/fleet/Fleet.kt` | 142 | the POST to `/api/start` |
| `tests/test_fleet_shells.py` | 61–82, 93–101, 104–111, 264–270 | what a shell may not name; the one SSE event; refusals in the server's words; the doc must carry the contract |
| `docs/fleet-ide.md` | §What a shell must do | steps 1–7; add step 8 |

**Build.** PyCharm: a Swing drop target on the tool-window panel, `FileCopyPasteUtil.getFileList()`, then
`POST /api/scope {paths}` with the token from `serve.json`. VS Code: an `explorer/context` and
`editor/title/context` command with the selected URIs; Shift-drop into the webview and a `text/uri-list` drop on
the Fleet view are laptop measurements — build them behind the measured branch and mark the rows. Server:
`POST /api/scope` without `repo` maps each path to the containing registered checkout (`norm_path`, real path,
prefix), refuses one in no checkout, refuses `.agent/out/` and the catalogue's refused names, answers
`scope_wrong_repo` with the owning repo when the selected tile is another. `docs/fleet-ide.md` step 8;
`test_fleet_shells.py` asserts a shell posts paths and nothing else.

**Tests to write.** Both shells build on CI; a path outside every checkout is refused with its `code`; a path in
repo A while tile B is selected is refused naming A; `test_fleet_shells.py` fails on a shell that names `.tmdl`,
`25 MB` or a repo name.

**Out of scope.** A second view in a shell; a host↔page JS bridge (the server is the bridge); macOS/Linux IDE paths.

### #168 — F: the agent honours the scope

Plan section: §The scope, *What the agent receives*. After #165 and #166.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `skills/session-bootstrap/SKILL.md` | 7–12 | the steps; nothing reads `inputs` |
| `agentdata/cli_state.py` | 39–40 | `ad-state show` prints `inputs (attached under .agent/in/)` |
| `agentdata/state.py` | 16–23, 74–82 | the `inputs` list, capped at 200, "so the agent finds them on its next turn without being told" |
| `agentdata/graph/query.py` | 241, 269 | `get_node_details`, `get_refs` — the widening preview |
| `agentdata/fleet/events.py` | `exited` / `error` | `files_modified` on both — the scope report compares against `scope.toon` |
| `agentdata/fleet/board.py` | 203–257 | `history()` — grows the scope column |

**Build.** `session-bootstrap` reads `.agent/in/<ticket>/` via `ad-state show` and prints one line; `jira-triage`
treats the scope as *where to start*, widens with `ad-graph refs`, announces an edit outside it; the scope report
on the tile and in `history`; the widening preview on the card, greyed with the `codebase-map` hint when no graph;
`fleet.prompt_at_refs` only if the `@path` measurement says yes.

**Tests to write.** A fake-copilot transcript whose first tool call after bootstrap reads `scope.toon` and whose
first edit is in it; a run editing outside the scope ends with `1 outside the scope you gave it` from events alone;
`history` for a scripted day agrees with the store; every touched skill under 120 lines.

**Out of scope.** Enforcing the scope; a ticket→file edge in the graph; `ad-jira attachments`.

### #169 — G: proof

Plan section: slice G. After everything. The fake `copilot` (`tests/fakes/copilot/`) learns a question round trip and
a scoped edit; runbook rows for every measurement A–F named; the CI demo (thin ticket → card says thin → brief and
two files → one blocking question with two choices and one assumption → answered in one Send → works → `edited 2 ·
0 outside`). The plan's status line moves to IMPLEMENTED in this slice, which turns the doc guard on for every
command it names.

## 5. Slice cards — sessions (#170)

Plan: `docs/plan-sessions.md`. Ground rules: `docs/plan-sessions.md` §Ground rules.

### #171 — A: a session is a record

Plan section: §A session is a thing. Depends on nothing. **Start here.**

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/supervisor.py` | 186–197 | `session_id()` reads the live raw `events.jsonl` only, for the last `result.sessionId` |
| `agentdata/fleet/supervisor.py` | 413–415, 458–460, 511–514 | the three lock shapes; `start` writes no `session` |
| `agentdata/fleet/supervisor.py` | 315–333 | `_emit_started()` — `started.data` gets `new: true` |
| `agentdata/fleet/lifecycle.py` | 170–178, 250 | `slept()` — one caller, a test; `rotate_all` renames the raw log |
| `agentdata/fleet/events.py` | 182 | the `session_id` kind — the normalized stream already carries every id |
| `agentdata/fleet/serve.py` | 170–220 | `split_runs()` — a run at every `started`; `earlier[]` at 195–201 carries no session |
| `agentdata/fleet/board.py` | 228, 251–257 | `history()` — a run only at a non-`resumed` `started`; `_close` returns no session |
| `agentdata/cli_fleet.py` | 218–219, 908, 1067–1249 | `status` columns; `history` columns; the verb list (no `sessions`) |
| `agentdata/fleet/adopt.py` | 269–277 | the adopted lock's `session` is the fleet's own last id, not the foreign one |
| `agentdata/fleet/launch.py` | 224–225 | `--resume` is the only session flag emitted |
| `agentdata/fleet/static/app.js` | 436–453 | the run line; `session` sliced to 8 characters at 443 |
| `agentdata/setup/steps/fleet.py` | 290–341 | the fleet doctor rows — add `fleet/session store` |

**Build.** `fleet/sessions.py` folding `events.norm.jsonl` into `agents/<name>/sessions.json` (`id, title, ticket,
first_seen, last_seen, runs, ended, cost, source`; `title` the one non-derived field); `ad-fleet sessions <repo>
[--rebuild] [rename <id> "<title>"]`, `GET /api/sessions?repo=`; `session_id()` from the normalized stream; a fresh
start's lock with `session: ""` and `started.new`; `fleet/runs.py` naming *run* and *dispatch*, read by both
`split_runs` and `history`; `earlier[].session`; the `session` column in `status` and `history`; the run line's
title and copy button; `start --resume <id>` and `--new` through `supervisor.start`, `launch_command` and the CLI;
the store reader (read-only, copy-on-read when locked, schema measured first, `source: store`, the doctor row);
adoption's lock and `started` gaining `session` from the store; `slept()` wired into the poller with the `exited`
`why`.

**Tests to write.** Three sessions fold into three rows with the right `ended` and `cost` (high-water mark); a
rebuild is byte-identical; a rotated raw log no longer makes `send` refuse; a start that dies before its first
`result` followed by a `send` refuses instead of resuming the old one (**the regression this slice exists for**);
tile and `history` say which word they count; no store → every test passes and the doctor row says `skip`; a fixture
store → a console session appears with `source: store`; a three-minute clock jump with a dead pid produces one
`exited` naming sleep and no `error`.

**Out of scope.** Page changes beyond the run line; writing to the store; `/session prune`.

### #172 — B: the desk comes back

Plan section: §The desk comes back. Depends on nothing.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/serve.py` | 445–469 | `reset()` — blanks `_selection` and every layout's arrangement and calls `_save_desk()`; docstring says it is for "the fleet moving under a live process" |
| `agentdata/fleet/serve.py` | 1473–1483 | `run()`'s `finally`: `forget()` then `reset()` — the clean-shutdown wipe |
| `agentdata/fleet/serve.py` | 364–374, 384–427 | `_selection`, `_ensure_desk_loaded`, `_save_desk` — `windows[name]` goes beside `arrangement` |
| `agentdata/fleet/serve.py` | 600–613, 689–729, 1123–1129 | `desk_state()`, `select()`, `arrange()`, the `desk` SSE frame |
| `agentdata/fleet/serve.py` | 1204–1210, 1437, 1459–1466 | `/open`; the per-run token; `serve.json` written then deleted by `forget()` |
| `agentdata/fleet/static/app.js` | 24–29, 1807–1814 | the URL parse (`layout`, `view`, `screen`) — add `w` |
| `agentdata/fleet/static/app.js` | 41, 596–621, 814, 890, 1872, 1881, 948, 952 | `held`, `focus()`/`unfocus()`/`followHash()`, `unread`, `lastSection`, the two `localStorage` keys — all move into the window record but the chime |
| `agentdata/fleet/static/app.js` | 151–152 | the transcript cap and the force-scroll on every append |
| `agentdata/fleet/static/app.js` | 544–592 | the SSE handler; on disconnect the page reloads `/api/fleet` — the `403` re-homing goes here |
| `agentdata/fleet/notify.py` | 121, 164–190 | `notify.state.json`; `scan()` over transitions — *since you were away* reads the same |
| `agentdata/cli_fleet.py` | `open` | `ad-fleet open --in …` — add `--window` and `--all` |
| `tests/test_fleet_desk.py` | 79–102 | persistence tests for `select`/`arrange`; nothing tests the shutdown path |

**Build.** Split `reset()` into `drop_handles()` (shutdown) and `forget_desk()` (fleet dir moved); `?w=` and
`windows[name]`; `POST /api/window`; the `desk` event carrying windows; `/open?w=`; `open --window` / `--all`; the
page re-homing itself through `/open` on the first `403` after a dead stream; *since you were away* from
`agentstate.transitions` and `notifications.jsonl` since `seen`; the transcript pane keeping its scroll position.

**Tests to write.** Serve → arrange, select, hide → `Ctrl-C` → serve: a rendered-page test reads the same
arrangement, selection and zoomed tile in the same named window; two windows keep different focus states across a
restart on a new port; a tab open across a restart draws the new run's tiles unaided; two changed tiles → two
strip lines, four quiet agents → none; `test_fleet_shells.py` passes with `?w=` as a pass-through.

**Out of scope.** Window placement on monitors; a per-window token.

### #173 — C: hide and reopen

Plan section: §Hide and reopen. After #172.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/static/app.css` | 184, 491, 525, 529 | the four `display:none` rules: zoom, focus mode, solo, laptop view |
| `agentdata/fleet/static/app.js` | 507–512, 498–504 | a repo leaving the registry → `el.remove()`; a new one appended at the end |
| `agentdata/fleet/static/app.js` | 631–637 | `1`–`9` read `getEffectiveOrder()` — unfiltered, so a digit can zoom a hidden tile |
| `agentdata/fleet/static/app.js` | 618–621 | `followHash()` — silent when the repo has no tile |
| `agentdata/fleet/static/app.js` | 1483–1499, 1505–1550 | `getLayoutArrangement`, `getEffectiveOrder`, `reorderDomTiles` — `hidden` filters here |
| `agentdata/fleet/static/app.js` | 1869–1877, 1709–1710 | `focusMode()` clears `held` on exit; the *Nothing needs you* line fires only on an empty grid |
| `agentdata/fleet/static/index.html` | 146–162 | the tile header — pin and width are the only buttons; add hide |
| `agentdata/fleet/serve.py` | 709–729 | `arrange()` — accepts `hidden` |
| `agentdata/fleet/notify.py` | 244 | the toast launches `#tile=<repo>` |
| `agentdata/fleet/agentstate.py` | 165–167 | `needs_the_human()` — the one predicate the dock rule uses |

**Build.** `hidden` per layout in `arrangement`, `arrange` accepting it, `ad-fleet hide`/`show`, the header
button and `h`; the dock (chips with state, age, badge; click reopens in place; *show all*; the zoomed case; registry
departures kept a day with the restoring command; arrivals announced); the never-hide table (red chip and chime;
shown in focus mode with a note; anchors reopen or say *no tile*); digits and `Alt+←/→` over the visible order;
leaving focus mode keeps `held`; the tile-number question measured, not decided.

**Tests to write.** Hide → reload → dock chip → reopen → old slot; a hidden tile turning `needs_human` shows a red
chip and appears in focus mode with the note; a digit for a tile focus mode hides no longer blanks the grid;
`#tile=` reopens a hidden tile and says *no tile* for an unregistered name; removing a repo while the page is open
leaves a chip naming the command; every existing rendered-page regression still passes.

**Out of scope.** Moving a tile between windows; the per-window `hidden` question.

### #174 — D: the switcher

Plan section: §The switcher. After #171 and #173.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/static/app.js` | 455–473 | the earlier-runs `<details>` — text rows, no handler, no id |
| `agentdata/fleet/static/index.html` | 164, 182–194 | the run line; `<details class="earlier">`; the bottom row |
| `agentdata/fleet/static/app.js` | 286–319, 428–433 | Send/Start/Stop/Reset wiring; the two-press *Reset anyway*; controls disabled for an external session |
| `agentdata/fleet/serve.py` | 290–342, 947–1005 | `fleet_snapshot()`'s per-repo row (`recent` is the last 40 events of the current run); `act()` — add `transcript`, `resume`, `new` |
| `agentdata/fleet/supervisor.py` | 380–394, 557–594 | the live-agent refusal and `--force` replacing; `reset()` — the pattern for *Stop and resume* |
| `agentdata/fleet/adopt.py` | 22–27, 248–251, 295–297 | "adoption supersedes, it does not supervise"; the refusals a `store` resume inherits |

**Build.** The tab strip under the run line (main tab; sibling checkouts from #175, one tab before then; *earlier
(n)*; *+ new*; every tab a button with the session title as its name); `GET /api/transcript?repo=&session=`, paged,
read-only, with the one sentence and *Resume here*; *Resume here* → `start --resume <id>`, the refusal and the
two-press *Stop and resume* when live, the console sentence and refusal for a `store` session; *+ new* →
`start --new`, with a ticket opening #164's card; `Alt+[`, `Alt+]`, `Alt+N`.

**Tests to write.** The fake-copilot sequence (session 1 blocked → *+ new* → *earlier* shows 1 → *Resume here*
refuses while 2 is live → *Stop and resume* launches `--resume <session 1>`); choosing an earlier session spawns
nothing (count `started`); the strip operable without a mouse; the page globals unchanged; a one-session tile looks
as today but for two buttons.

**Out of scope.** Editing a transcript; deleting a session; the sibling checkouts themselves.

### #175 — E: checkouts of one project

Plan section: §Checkouts. After #171 and #174.

**Seams.**

| File | Line | What is there |
|---|---|---|
| `agentdata/fleet/registry.py` | 44–71, 102–108, 127–159, 161–165 | `Repo` (`extra` splatted on save); `load()` drops unknown keys; `add()` — name from basename, uniqueness on name only, `norm_path` only; `remove()` leaves the agent dir |
| `agentdata/fleet/scan.py` | 53–54, 188–211, 222–228, 282–298, 322, 369, 383, 392–402 | `MARKERS`; a `.git` file counts; the deliberate refusal to follow `gitdir:`; `_unique`; registered-by-path; the blank branch and age; `_why` |
| `tests/test_fleet_scan.py` | 209–219 | the existing worktree test (blank branch, by design) — keep it passing |
| `agentdata/fleet/catalogue.py` | 73–74, 110–114, 118–134, 352–353, 411–441 | `GIT_HEAD`/`GIT_REFS`; the allow-list; `_inside` (the wall — do not touch); the `git` doc never built for a worktree |
| `agentdata/fleet/poll.py` | 613–637 | `read_git` — `git status --porcelain=v2 --branch` in the checkout; worktree-correct |
| `agentdata/fleet/serve.py` | 833–872, 875–898 | `show_for()` (`branch` from the catalogue at 866), `desk_snapshot()` |
| `agentdata/fleet/supervisor.py` | 595–605 | `status()` — add `project` |
| `agentdata/theme_project.py` | 43–52, 153, 173, 267, 271, 319, 331 | the colour lookup (name, then abspath); the three hooks' path-prefix rules, first match wins, emitted in name order |
| `agentdata/fleet/inbox.py` | 351–391 | `_match()` — the two ties that make everything `unsorted` |
| `agentdata/cli_fleet.py` | 55–77, 328–329 | `repo add`/`rm`; `SCAN_COLUMNS` |
| `docs/fleet.md` | 122 | "One agent per repository" |

**Build.** `extra` read back; `project` defaulting to `name`; `extra.worktree_of`; `repo add` following the
`gitdir:` line once at the human's add, `--project`, the scan's `worktree_of` column and *why*; `show_for` taking
the branch from the poll's cell; `project` in `desk_snapshot` and `status`; the page grouping a project's checkouts
as sibling tabs, pinned/hidden/ordered as one; `theme.projects.<project>` first and longest-path-first hooks;
`_match` resolving an intra-project tie by `active_ticket` then the primary; `repo rm` naming the orphan dir; the
`docs/fleet.md` wording.

**Tests to write.** A previous-release registry loads with `project == name` and saves back byte-identical; a
fixture worktree registers as `proj-<basename>` with `project: proj` and the scan line says so; `/api/show` carries
its own branch; two checkouts share a colour, a nested one gets its own; a Downloads file goes to the checkout whose
`active_ticket` matches; two agents at once with two locks and the four-repo walk clean.

**Out of scope.** Creating worktrees; a project spanning two repositories; per-project approval or budget; the
tracked-`state.json` shared-history hazard (a finding for the project stub, recorded in the plan).

### #176 — F: proof

Plan section: slice F. After everything. The fake `copilot` answers `--resume <id>` and `--new`; a fixture
`session-store.db` in the measured schema; runbook rows for every measurement; the CI demo (two checkouts of one
project, one hidden, `Ctrl-C` and reopen by name, the hidden tile turning red in the dock and reopening from a toast
anchor, an earlier session resumed by *Stop and resume*, the *since you were away* strip naming every change and
nothing else). The plan's status line moves to IMPLEMENTED here.

## 6. Glossary

| Term | Means here |
|---|---|
| **project** | the git repository; a name, a colour, a `jira_project` (#175 adds it to the registry) |
| **checkout** | a working tree the fleet registered — a registry entry with a `name` and a `path`; one lock, at most one live agent |
| **session** | a Copilot conversation id, resumable with `--resume <id>`; many per checkout; one is *current* |
| **run** | what one `started` event begins — a launch, a `send`, a `restart`; the tile's transcript boundary |
| **dispatch** | a run whose `started` is not `resumed`; what `ad-fleet history` counts |
| **the fold** | `agentstate.derive()` — the event stream reduced to one state and one *why* sentence, in a fixed order |
| **the lock** | `~/.agentdata/fleet/agents/<name>/agent.json`; a live pid means a live agent; `lifecycle.reap` clears it when the pid is gone |
| **tile** | one checkout's current session on the page; the sidebar is the project |
| **the dock** | (#173) the strip of every tile that is not on the glass |
| **the brief** | (#164) the operator's own words at dispatch, `.agent/in/<KEY>/brief.md` |
| **the scope** | (#166) the files handed to the agent, `.agent/in/<KEY>/scope.toon` |
| **the ask** | (#165) a question as a record — id, choices, default, want, blocking — via `ad-state ask` |
| **adopted** | a session the fleet did not start, taken on as a checkout's current run; supervised by nobody, resumable once its console is gone (#171) |
| **the store** | `~/.copilot/session-store.db`, Copilot's own; read, never written (#171) |
| **the sitting** | the operator's afternoon on the real screens that decides layout questions; `docs/fleet-layouts.md` |
| **TOON** | the agent-facing table format every `ad-*` command prints; `docs/data-format-policy.md` |
