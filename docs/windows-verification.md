# Windows verification runbook (post PR #2)

Everything that could be proven on Linux CI was proven (parsers, lint rules, replay algorithm, validators, wizard with
fake drivers). What remains is every integration seam that only exists on the laptop: pncli's real config, the real Jira
instance, ODBC/native drivers, keyring, `az`, Tabular Editor 2, DAX Studio's `dscmd` flags, Power BI Desktop discovery,
and PBIR/TMDL files as the current Desktop writes them. Run this top to bottom; paste results back as described and
each failure becomes a fix with a reproducing test.

Conventions: run in PowerShell inside the project checkout; every `ad-*` command prints TOON; **paste the whole TOON block** (it never contains a token or password) plus any Python traceback. Where a step says "paste", paste even on success for the first run so expectations can be calibrated. Stop at the first failing step inside a section and continue with the next section (sections are independent).

## 0. Baseline
```powershell
ad-update --check                                                      # version + commit you are on now
git pull origin main
pip install "agentdata[pbi,uat,teradata,impala,oracle] @ git+https://github.com/agentchieflou/this-next-please.git"
#   drop extras you do not use; impyla on Windows also needs: pip install winkerberos
#   developing the repo instead? clone it and `pip install -e ".[dev]"` THERE, never in a report repo
ad-doctor    # if "not recognized": the Scripts dir is not on PATH -> use `python -m agentdata doctor` everywhere below
gh skill install agentchieflou/this-next-please --all --scope user   # --all avoids the picker; --scope user applies to every repo
python -m pytest -q     # only in a clone of this-next-please; expect: 96 passed
chcp 65001 | Out-Null                                                  # UTF-8 console so → · ≤ render (cosmetic)
```
Pass: `96 passed`. Paste: any failing test names and their assertion text (likely candidates: CRLF fixture if `core.autocrlf=true`, path separators).

## 1. Doctor before setup
```powershell
ad-doctor
```
Pass: exit 1 with `fail`/`warn` rows that each carry a hint naming `ad-setup --only <step>`; no traceback. Paste: the output.

## 2. pncli import and Jira flavor
```powershell
ad-setup --only pncli            # accept the proposed keys if they point at url / email / token; note if the proposal is wrong
ad-jira whoami
ad-jira whoami --redetect        # only if the first call failed
ad-pncli where                   # resolved launcher: path, kind (npm shim), node entry, version
ad-pncli jira search --jql "key = <any issue>"
ad-pncli jira get <any issue key>   # pncli's confirmed read verb, built for you (jira get-issue --key <KEY>)
```
Pass: `whoami` returns `flavor` (`cloud` or `dc`), `auth`, `api`, `display_name`, `token_source: pncli:<key path>`; `ad-doctor --only pncli` is all `ok`. Paste: the key list the wizard printed (values are masked), the answers you gave, and the `whoami` TOON. If `~/.pncli/config.json` is not JSON or the token is stored indirectly (env var, keychain), say so — that changes `steps/pncli_import.py` and `jira_api.load_credentials`.

## 3. Jira changelog and sprint replay
```powershell
ad-jira fields --like sprint
ad-jira fields --like point
ad-jira fields --pin
ad-jira statuses
ad-jira sprints --board <jira_board_id> --state closed
ad-jira changelog <one issue key> --fields status,Sprint,"Story Points"
ad-jira sprint-replay --sprint <closed sprint id> --board <jira_board_id> --jql "project = <KEY> AND updated >= '<sprint start minus 1 day>'" --compare-sprintreport
```
Pass: `--pin` reports `pinned_sprint` and at least one `pinned_story_points` id; changelog rows show `from_id`/`to_id` for Sprint and status; `sprint-replay` prints `summary` with `committed_points`/`completed_points` and `sprintreport_delta` with small or explained deltas. Paste: the `summary` and `sprintreport_delta` blocks, and Jira's own Sprint Report numbers for the same sprint (committed, completed). A delta means either a replay convention (`--points-at commit` vs `close`) or a bug in `uat/sprint.py`; the per-issue rows in `path` tell which keys differ.

## 4. Data sources
```powershell
ad-setup --only sources          # answer for the sources you have; passwords go to keyring
ad-doctor --online               # SELECT 1 + capability probes per env
ad-td --sql "SELECT 1"           # env from AGENTS.md `env` fact, or add --env
ad-sql-check --dialect teradata .agent\sql\<any real query>.sql
type $env:USERPROFILE\.agentdata\config.json   # safe to paste: no secrets by design; check `capabilities` under each env
```
Pass: doctor rows `ok` with `verified` dates; `capabilities` show `tmode`, `trunc_date`, `to_char`, `listagg` for Teradata (`major` for Hive/Impala); a real query passes the lint with at most warnings you agree with. Paste: doctor output, the config file, and any lint `findings` you consider false positives (rule id + the SQL line) — those become rule fixes in `sqlcheck/rules.py`. Note which mode you chose per source (native vs ODBC) and the driver names `pyodbc.drivers()` listed if ODBC failed.

## 5. Power BI tools and workspaces
```powershell
ad-setup --only powerbi          # tool paths (incl. az), az login, workspace list, TE2 ping per workspace/model
ad-setup --patch                 # after any fail row: re-asks ONLY the settings behind it
ad-doctor --only powerbi
```
Pass: `te2_exe`, `dscmd_exe`, `pbi_desktop_exe` rows `ok`; workspaces listed with `xmla` percent-encoded; `verified.powerbi:xmla:<ws>` present after the ping. Paste: the wizard's summary TOON and the `az rest` error text if listing failed. If the TE2 ping fails, also paste the last 10 lines Tabular Editor printed (the wizard shows them in `detail`).

## 6. PBIP projection and validator (no Desktop needed)
```powershell
cd <report repo>                 # folder holding <Name>.pbip, or set pbip_path in AGENTS.md
ad-pbip project
ad-pbip check                    # structure only
ad-pbip check --te2              # Tabular Editor build of the TMDL folder
ad-pbip lint <Name>.SemanticModel\definition
ad-pbip refs --visual "<a visual title from REPORT.md>"
ad-pbip refs --table <Table> --column <Column>
```
Pass: `project` writes `.agent\pbip\<name>\` and `MODEL.md` / `REPORT.md` read correctly (spot-check 3 measures and 2 visuals against Desktop); `check` has `errors: 0` on a report that opens fine in Desktop; `check --te2` shows `te2: ran` with `errors: 0`; `lint` has no `error` rows on Desktop-written files. Paste: the `meta` blocks and **every** `error`/`warning` row from `check`, `check --te2` and `lint` — on Desktop-written files these are parser gaps, not your report's fault (candidates: TMDL constructs the parser has not seen, PBIR expression kinds the walker does not decode, name-shape rules that are too strict).

## 7. Desktop discovery and live evaluation
```powershell
# open the .pbip in Power BI Desktop first (File > Open)
ad-pbip desktop
ad-pbip check --server localhost:<port>
ad-pbip visual-query --visual "<visual title>" --server localhost:<port>
ad-pbip visual-query --visual "<visual title>" --dry-run      # prints the DAX only
```
Pass: `desktop` lists the instance with `port`, `title` and `matched` file; `check --server` shows `measures_probed > 0`, `measures_failed: 0`, no `live-stale` rows; `visual-query` returns rows that match the visual in Desktop for a simple chart. Paste: the `desktop` rows, the `check --server` meta, and for `visual-query` the DAX file at `dax_path` plus the error text if dscmd failed — that tells whether dscmd needs `-q` instead of `-f`, whether `-d` is required for a Desktop workspace, or whether the SUMMARIZECOLUMNS builder mis-translated a filter.

## 8. Mechanical measure edit round trip (on a scratch copy of the PBIP)
```powershell
Copy-Item -Recurse <report repo> <scratch dir>; cd <scratch dir>
[IO.File]::WriteAllText("$PWD\margin.dax", "DIVIDE ( [Margin], [Total Sales] )")   # UTF-8 without BOM; Set-Content -Encoding utf8 would add one (tolerated, but do not teach Luna that)
ad-pbip measure set --table <Table> --name "Verify Pct" --expr-file margin.dax --format-string "0.0%" --display-folder Verify
ad-pbip lint <Name>.SemanticModel\definition
ad-pbip check --te2
git diff --stat; git diff                                        # expect only the inserted block
# then open the scratch .pbip in Desktop: the measure must appear under the table
```
Pass: lint clean, TE2 clean, diff is exactly the block (no CRLF/BOM churn), Desktop shows the measure and can save without complaint. Paste: the diff and any Desktop error dialog text.

## 9. UAT end to end on one small chart
```powershell
ad-uat plan --visual "<chart title>" --ticket <KEY> --expected .agent\in\<file.csv> --window <start>,<end>
ad-uat expect .agent\in\<file.csv>
# run the tier commands the plan printed (tier 3 with the Desktop port, tier 2 after fixing column names in .agent\sql\<KEY>-uat-*.sql, tier 1 jira)
ad-uat reconcile --expected <e.tsv> --jira <j.tsv> --hist <h.tsv> --pbi <p.tsv> --key <key> --cols <metrics> --window <start>,<end> --hist-coverage <cov.tsv> --ticket <KEY>
```
Pass: `plan` names the right measures and warehouse objects; `expect` infers the right `grain`; `reconcile` produces classes you agree with and `.agent\out\<KEY>-uat-findings.md` is ≤ 40 lines. Paste: the `plan` meta, the `grain`, and the `counts` block; if a class looks wrong, paste the offending finding row and the four tier values.

## 10. Project stub
```powershell
ad-setup --project <fresh project folder>
ad-setup --only project --non-interactive --offline --project <another fresh folder> --set project.jira_project=RDSD   # the form Luna runs (no stdin)
ad-state --file <folder>\.agent\state.json set phase=triaged active_ticket=RDSD-1
```
Pass: `AGENTS.md` facts filled (env names, tool paths, workspace, model, `pbi_xmla`, `pbip_path`), `.agent\state.json` present, `.gitignore` extended. Paste: the generated `AGENTS.md`.

## 11. Luna dry run (optional but the real test)
In PyCharm with the skills installed (`gh skill install agentchieflou/this-next-please --all --scope user` — `--all` skips the interactive picker, whose search row swallows Enter), ask Luna: "add a measure `<X>` to `<Table>` that does `<Y>` and make sure the report still works". Pass: it runs `pbip-projection` → `tmdl-edit` (`ad-pbip measure set`) → `pbi-validate` (`check --te2`, `desktop`, `visual-query`) without hand-editing TMDL. Paste: the friction log if it stops (`.agent\friction\*.md`).

## 12. Desktop session control and capabilities (#50)
```powershell
ad-pbip capabilities                                                   # probe 8 capabilities (as_port, xmla_local, uia, etc.)
ad-pbip desktop status                                                 # lists instances with pid, port, pages, unsaved, desktop_version, install
ad-pbip desktop open <path-to.pbip> --wait 180                         # launches and polls until Analysis Services and UI are ready
ad-pbip desktop reload --pid <pid>                                     # cleanly closes and reopens, restoring active page
ad-pbip desktop close --pid <pid> --discard                            # closes via WM_CLOSE, discarding unsaved changes
```
Pass: `capabilities` outputs 8 rows with available state and evidence; `status` reports `pages`, `unsaved`, `loaded`, `desktop_version`, `install`; `open --wait` returns instance row once loaded; `reload` returns `reloaded_via: native`; `close` cleanly exits.

## 13. Desktop screenshots and visual regression (#51)
```powershell
ad-pbip screenshot --pid <pid> --page "Page 1" --out page1.png
ad-pbip screenshot --pid <pid> --visual "Visual Title" --out visual.png
ad-pbip screenshot --pid <pid> --page "Page 1" --out after.png --compare before.png --threshold 0.005 --mask "10,10,100,50"
```
Pass: `screenshot` captures full window or crops to canvas/visual without black screen (using `PrintWindow` with `PW_RENDERFULLCONTENT`); visual regression diff returns `diff_ratio` and generates visual diff image when differences exceed threshold; masked areas are ignored in comparison.

## 14. Desktop External Tool registration and handoff (#53)
```powershell
ad-pbip register-tool                                                  # writes agentdata.pbitool.json to %CommonProgramFiles% External Tools
ad-doctor --only powerbi                                               # checks powerbi/external_tool row: registration, path, and registry
ad-pbip handoff --server localhost:54321 --database "00000000-0000-0000-0000-000000000000"  # simulated Desktop ribbon click
ad-pbip desktop status                                                 # automatically picks up handed off server and pid without flags
type .agent\desktop.json                                               # verify server, database, pid, handed_off_at
```
Pass: `register-tool` registers `agentdata.pbitool.json` in Desktop's External Tools folder; `ad-doctor` shows `powerbi/external_tool` ok; Desktop shows `agentdata` in ribbon; clicking ribbon or running `handoff` records `.agent/desktop.json`; downstream verbs prefer handoff when fresh.

## 15. Observe live model via traces, DMVs, and page-cost (#54)
```powershell
ad-pbip dmv deps --server localhost:<port>                             # query DISCOVER_CALC_DEPENDENCY
ad-pbip dmv segments --server localhost:<port>                         # query DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS
ad-pbip refs --live --server localhost:<port>                          # reconcile live graph against TMDL/PBIR files
ad-pbip page-cost --pid <pid> --page "Page 1" --seconds 15             # benchmark page render and visual query latency
ad-pbip trace start --pid <pid> --seconds 60 --out .agent/out/trace.jsonl  # start named-pipe listener and TE2 trace
ad-pbip trace report .agent/out/trace.jsonl                            # aggregate query latencies and correlate to visuals
```
Pass: `dmv deps` and `segments` return formatted tables; `refs --live` shows synced/live-only status; `page-cost` navigates page and computes per-visual and total query time; `trace report` correlates query hashes to visual projections.

## 16. Model authoring, audit, and optimization (#58)
### §Model apply
```powershell
# Tier 1: Live TOM edits directly to running Power BI Desktop instance with session save
ad-pbip model apply --pid <pid> --ops .agent/ops.json --save
# Tier 2: TMDL file writer fallback
ad-pbip model apply --model <definition> --ops .agent/ops.json
# Model best practice audit (8+ rules with fixes)
ad-pbip model audit <definition> [--bpa]
# Copilot AI readiness scored checklist
ad-pbip model audit <definition> --copilot
# Measure optimization with trace evidence and regression protection
ad-pbip model optimize --measure "Margin %" --pid <pid>
```
Pass: `model apply` executes declarative ops over the port through TE2 `-S` or falls back to TMDL file editing with no `lineageTag` written; `--save` triggers UIA session save and waits for Desktop-serialised TMDL to settle; `model audit` returns actionable `fix` snippets; `audit --copilot` outputs a scored checklist; `model optimize` verifies results match before keeping rewrites and rolls back on mismatch.


## 10. Deploy loop (`ad-pbi deploy` → `refresh` → `verify`)
```powershell
# 1. Preview deploy
ad-pbi deploy "tests/fixtures/sample.pbip/Sample.SemanticModel/definition" --workspace "Sales" --model "Sample" --dry-run
# 2. Deploy model over XMLA (with clean tree enforcement and deploy stamp)
ad-pbi deploy "tests/fixtures/sample.pbip/Sample.SemanticModel/definition" --workspace "Sales" --model "Sample"
# 3. Refresh model and poll progress
ad-pbi refresh --workspace "Sales" --model "Sample" --scope full --wait 300
# 4. View recent refresh history
ad-pbi refresh --workspace "Sales" --model "Sample" --top 5
# 5. Check partition row counts
ad-pbi refresh partitions --workspace "Sales" --model "Sample"
# 6. Verify service parity against running Desktop
ad-pbi verify --pbip "tests/fixtures/sample.pbip/Sample.Report" --workspace "Sales" --model "Sample"
```
Pass: `deploy` creates `.agent/out/deploy-<ts>.xmla` on dry-run and logs output to `.agent/out/deploy-<ts>.log`; `refresh` polls until `status: Completed`; `verify` outputs `parity: ok`.

## Triage map (where a failure lands)
| Symptom | Module | Likely fix |
|---|---|---|
| pncli keys not proposed / token indirect | `agentdata/setup/steps/pncli_import.py`, `connectors/jira_api.load_credentials` | key heuristics; support env-var indirection |
| `whoami` 401/404 on DC | `jira_api.detect_flavor` | candidate order, `/rest/api/2` paths |
| `sprint-replay` delta vs Sprint Report | `uat/sprint.py` | boundary convention, done-at rule, sprint field parsing (DC string form) |
| ODBC DSN not visible / driver name | `connectors/odbc.py`, `steps/sources.py` | bitness hint, driver matching |
| keyring backend error | `connectors/secrets.py` | backend detection, hint text |
| TE2 ping / build fails | `steps/powerbi.py`, `pbip/check.run_te2` | argument order, error-line parsing |
| `ad-pbip lint`/`check` errors on Desktop files | `pbip/tmdl.py`, `pbip/pbir.py`, `pbip/check.py` | parser coverage (new keywords/expression kinds), rule strictness |
| `desktop` finds nothing | `pbip/desktop.py` | PowerShell CIM quoting, port file encoding, Store-install paths |
| dscmd rejects `-f` / needs `-d` | `pbip/dax.run_dax`, `steps/powerbi.py` caps probe | flag detection, catalog discovery via `$SYSTEM.DBSCHEMA_CATALOGS` |
| visual-query wrong rows | `pbip/dax.visual_query` | filter translation, aggregation mapping, hierarchy level column |
| reconcile class wrong | `uat/reconcile.classify` | rule order, coverage semantics |
| `JSONDecodeError: Unexpected UTF-8 BOM` or garbled text from a file PowerShell wrote | `agentdata/textio.py` | every reader goes through `textio.read_text` (BOM / UTF-16 sniffing); Luna uses `--set` and `ad-state` instead of writing files |
| pncli says `required option '--x <y>' not specified` | `connectors/pncli.usage_hint`, `cli.py` | pncli is commander.js: arguments are named options. The hint names the exact re-run; confirmed verbs get their own `ad-pncli` subcommand |
| `The filename, directory name, or volume label syntax is incorrect` from `az login` / any `.cmd` tool | `agentdata/proc.py` | the cmd.exe command line must reach Windows as one string; a list goes through `list2cmdline`, which backslash-escapes the quotes |
| az not found although it is installed | `agentdata/proc.TOOL_DIRS`, `steps/powerbi.py` | the Azure CLI `wbin` dir is searched even when the installer left it off PATH; `ad-setup --patch` asks for the path |
| `[WinError 2] The system cannot find the file specified` from any `ad-*` command | `agentdata/proc.py` | the tool is a `.cmd` shim (npm) or a `.bat`, not an `.exe`: resolution honours PATHEXT + the npm global prefix and unwraps the shim to `node <script>`; `ad-pncli where` shows what was tried |
| `pytest` fails on Windows | tests / `.gitattributes` | line endings, path separators |

## Fixed from laptop results
- 2026-09-02 (data_remediation_foundry_dpm_fork, session-bootstrap): `ad-setup --only project --non-interactive --answers .agent\setup-answers.json` failed with `JSONDecodeError: Unexpected UTF-8 BOM` — the answers file came from `Set-Content -Encoding utf8` (Windows PowerShell 5.1 adds a BOM) and the loader crashed with a traceback instead of a TOON error. Fix: every reader sniffs BOM/UTF-16 (`agentdata/textio.py`), `ad-setup --set key=value` removes the need for answer files, `ad-state` replaces hand-written state.json edits, and the three skills say so.
- 2026-09-02 (data_remediation_foundry_dpm_fork, skill jira-triage): `ad-pncli jira search --jql "key = RDSD-22399"` failed with `[WinError 2] The system cannot find the file specified`, and `ad-doctor` had called pncli "ok" because `shutil.which` found the shim while the connector passed the bare name `pncli` to `subprocess`. pncli is an npm package: on Windows it is `pncli.cmd`, there is no `pncli.exe`. Fix: `agentdata/proc.py` resolves PATHEXT + the npm global prefix and runs the shim's Node entry point directly, the doctor row now proves the launcher starts (`--version`), the resolved shim is pinned in `pncli.exe`, and `ad-pncli where` diagnoses it.
- 2026-09-02 (data_remediation_foundry_dpm_fork, skill jira-triage): `ad-pncli raw jira get-issue RDSD-22399` returned `ok: false` — pncli wants `--key <issue-key>`, because it is a commander.js CLI where every argument is a named option, and the skill still carried a `TODO(pin the verb)` placeholder. Fix: `ad-pncli jira get <KEY>` builds the confirmed verb `jira get-issue --key <KEY>`; any pncli usage error is turned into the exact re-run (`usage_hint`); the jira-triage step no longer asks the model to assemble a pncli command.
- 2026-09-02 (data_remediation_foundry_dpm_fork, ad-setup powerbi): `az login` failed with *"The filename, directory name, or volume label syntax is incorrect"*. az is `C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd`, and the cmd.exe command line built for it was handed to `subprocess` as a list, so `list2cmdline` backslash-escaped the inner quotes. Fix: the cmd.exe line is passed to Windows as one string, az is a configurable tool (`powerbi.tools.az_exe`) whose install dirs are searched even when they are off PATH, and `ad-setup --patch` re-asks only the settings that fail.
