# Windows verification runbook (post PR #2)

Everything that could be proven on Linux CI was proven (parsers, lint rules, replay algorithm, validators, wizard with
fake drivers). What remains is every integration seam that only exists on the laptop: pncli's real config, the real Jira
instance, ODBC/native drivers, keyring, `az`, Tabular Editor 2, DAX Studio's `dscmd` flags, Power BI Desktop discovery,
and PBIR/TMDL files as the current Desktop writes them. Run this top to bottom; paste results back as described and
each failure becomes a fix with a reproducing test.

Conventions: run in PowerShell inside the project checkout; every `ad-*` command prints TOON; **paste the whole TOON block** (it never contains a token or password) plus any Python traceback. Where a step says "paste", paste even on success for the first run so expectations can be calibrated. Stop at the first failing step inside a section and continue with the next section (sections are independent).

## 0. Baseline
```powershell
git pull origin main
pip install "agentdata[keyring,odbc,pbi,uat,teradata,impala,oracle] @ git+https://github.com/agentchieflou/this-next-please.git"
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
ad-setup --only powerbi          # tool paths, az login, workspace list, TE2 ping per workspace/model
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
"DIVIDE ( [Margin], [Total Sales] )" | Set-Content margin.dax
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
```
Pass: `AGENTS.md` facts filled (env names, tool paths, workspace, model, `pbi_xmla`, `pbip_path`), `.agent\state.json` present, `.gitignore` extended. Paste: the generated `AGENTS.md`.

## 11. Luna dry run (optional but the real test)
In PyCharm with the skills installed (`gh skill install agentchieflou/this-next-please --all --scope user` — `--all` skips the interactive picker, whose search row swallows Enter), ask Luna: "add a measure `<X>` to `<Table>` that does `<Y>` and make sure the report still works". Pass: it runs `pbip-projection` → `tmdl-edit` (`ad-pbip measure set`) → `pbi-validate` (`check --te2`, `desktop`, `visual-query`) without hand-editing TMDL. Paste: the friction log if it stops (`.agent\friction\*.md`).

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
| `pytest` fails on Windows | tests / `.gitattributes` | line endings, path separators |
