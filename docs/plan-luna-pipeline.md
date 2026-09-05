# Plan: Power BI pipeline, UAT engine, setup CLI, SQL dialect guardrails for Luna

_Status: IMPLEMENTED (2026-09-02) — all six slices landed on `claude/repository-push-bekwfa` (PR #2), 96 tests green. Residual unknowns below are verified on the Windows laptop._

## Context

`this-next-please` (merged PR #1) is a skills + `agentdata` adapter repo that lets a cheap Copilot model ("Luna", GPT-5.x in PyCharm on Windows) run data-analyst work across projects. Today it covers Jira search via pncli, read-only SQL (Teradata/Oracle/Hive), TE2 deploy/refresh, DAX Studio export, and a Jira-vs-Teradata UAT diff. It does **not** know PBIP/PBIR/TMDL, has no setup CLI, no dialect guidance, no Jira changelog access, and no visual-level UAT.

Problems the user hit with Luna: (1) it edits TMDL wrong (tabs/indent depth, multi-line expressions, quoting, schema alignment); (2) it edits the model and never checks the report still resolves; (3) it gets SQL dialect syntax wrong on first try; (4) new laptops need a guided setup (pncli import, ODBC, Power BI); (5) UAT needs to run from a doc/CSV plus "which chart / which TMDL file"; (6) it must reason about a source-of-truth hierarchy (live Jira > Jira history tables in Teradata > Power BI) and flag data the lower tier cannot reproduce; (7) pncli has no Jira changelog, so build one on the Jira REST API reusing pncli's token.

User decisions (2026-09-02): Jira flavor **detected at runtime**; pncli config at **`~/.pncli/config.json`**; report repos use **PBIR + TMDL**; installed tools **Tabular Editor 2 CLI, Power BI Desktop, DAX Studio (dscmd)**. **pbi-tools is NOT installed** — parts donor only. Research confirmed pbi-tools is **AGPL-3.0-or-later** and **does not read or write PBIP at all** (PBIX/PBIT/PbixProj only), so we port *behaviour* learned from its docs and from Microsoft's underlying APIs, never code, and we never invoke its binaries.

Design principle carried from the repo: *mechanize what a cheap model gets wrong*. Every "Luna must know X" becomes (a) a crystallized reference file the skill points at, **and** (b) a CLI that performs or checks X deterministically, returning `ok:true|false` + `hint` TOON exactly like the existing `ad-*` commands (`agentdata/policy.py:error`, `agentdata/cli.py` exit codes 0/1/2).

## Requirements traceability

| # | Ask | Delivered by |
|---|-----|--------------|
| R1 | Grow Power BI tooling; pbi-tools as parts donor | `agentdata/pbip/*` (desktop discovery, projection, check, DAX runner), `docs/pbi-tools-parts.md` |
| R2 | Luna edits TMDL correctly (indent/schema/triple-quote) | `skills/tmdl-edit/` + `references/tmdl-syntax.md`; `ad-pbip lint`, `ad-pbip measure set` (mechanical insertion) |
| R3 | Backend edit ⇒ frontend validation | `ad-pbip check` (model↔report cross-reference + TE2 build), `ad-pbip visual-query` (evaluate a visual's DAX against Desktop/XMLA), skill `pbi-validate`; `tmdl-edit` ends with mandatory handoff → `pbi-validate` |
| R4 | PBIP → normalized JSON → TOON/TSV + targeted Markdown, non-destructive | `ad-pbip project` writes `.agent/pbip/<name>/` (normalized.json, *.tsv, MODEL.md, REPORT.md, LINEAGE.md, meta.json); PBIP never modified by projection |
| R5 | Setup CLI on clone: pncli import, ODBC (Teradata/Hive/Impala), Power BI workspaces, extensible | `ad-setup` wizard (step registry) + `ad-doctor`; `~/.agentdata/config.json`; `session-bootstrap` runs `ad-doctor` |
| R6 | Crystallized SQL docs: Teradata 20, Hadoop (Hive/Impala), Oracle | `skills/<x>-query/references/*.md` + side-by-side `skills/data-adapter/references/sql-dialects.md`; `ad-sql-check` pre-flight lint wired into `ad-td/ad-ora/ad-hive/ad-impala` |
| R7 | UAT from doc/CSV + "which chart / which TMDL" | skill `uat-report-visual`; `ad-uat expect`, `ad-uat plan`, `ad-uat reconcile` |
| R8 | Truth hierarchy + inconsistency detection | `agentdata/uat/reconcile.py` tiering + classification (`report-bug`, `history-gap`, `lag`, `mapping-bug`, `expectation-wrong`, `unexplained`) with coverage checks |
| R9 | Jira changelog via REST reusing pncli token | `agentdata/connectors/jira_api.py`, `ad-jira whoami|fields|changelog|sprint-replay` |

## Architecture (new code)

```
agentdata/
  config.py                 global config (~/.agentdata/config.json) + project facts (AGENTS.md "- key: value" lines) + env overrides
  setup/
    wizard.py               ad-setup / ad-doctor: ordered Step registry (detect → ask → verify → write), idempotent, --check, --only, --non-interactive
    steps/pncli_import.py   detect ~/.pncli/config.json, list key names (never values), pick jira url/email/token keys, verify with /myself
    steps/sources.py        Teradata/Hive/Impala/Oracle: pyodbc drivers/DSNs, native or ODBC per env, `SELECT 1` smoke, capability probes
    steps/powerbi.py        find TE2/dscmd/PBIDesktop; az login state; list workspaces (REST); XMLA smoke via TE2 script
    steps/project.py        generate project stub (templates/project-stub) with facts filled from config
  pbip/
    tmdl.py                 tolerant line-model TMDL parser (tabs, `=` expressions, ``` fences / indented blocks), lint, surgical writer
    pbir.py                 PBIR loader: report.json, pages/*.json, visuals/*/visual.json, bookmarks, reportExtension; recursive field-ref walk
    normalize.py            → {model:{tables,columns,measures,hierarchies,relationships,partitions,expressions,roles,perspectives}, report:{pages,visuals,fields,filters,bookmarks}, lineage}
    project.py              projection writer: normalized.json, tables/columns/measures/relationships/visuals/visual_fields/filters .tsv, MODEL.md, REPORT.md, LINEAGE.md, meta.json (source hashes)
    check.py                model↔report cross-ref + TMDL lint + PBIR naming rules + optional TE2 build/BPA + optional live evaluate; TOON findings; exit codes
    edit.py                 mechanical edits: measure add/set, property set; (stretch) rename with report propagation
    desktop.py              Power BI Desktop instance discovery (msmdsrv.exe cmdline → port file → parent PBIDesktop.exe) → localhost:<port>
    dax.py                  run DAX via dscmd (localhost:<port> or XMLA) → CSV → AgentTable; SUMMARIZECOLUMNS builder for a visual; INFO.VIEW.* metadata pulls
  connectors/
    jira_api.py             stdlib urllib; flavor detect; changelog (paged), bulkfetch, fields, status categories, agile sprint/board; 429 handling
    impala.py               impyla port 21050 (or pyodbc DSN when configured); hive.py gains the same ODBC option
  sqlcheck/
    rules.py                per-dialect regex rules → {severity, message, fix, doc_anchor}; capability-aware (reads probes from config)
  uat/
    expect.py               CSV/TSV/XLSX/MD(table)/DOCX(table) → expected AgentTable (grain inferred from header)
    sprint.py               changelog backward-replay → committed/completed points per sprint (+ added/removed/re-estimated/carried)
    reconcile.py            tiered comparison + classification + coverage checks → findings TOON + findings.md
```

Zero new required dependencies (stdlib `urllib`, `json`, `re`, `subprocess`, `csv`, `base64`, `datetime`, `hashlib`). Optional extras in `pyproject.toml`: `odbc=["pyodbc"]`, `impala=["impyla"]`, `uat=["openpyxl","python-docx"]`, `pbi=["psutil"]` (only for exact open-file path detection; PowerShell CIM fallback is stdlib); add `keyring` to `teradata`/`oracle` extras (imported today but undeclared).

## CLI surface (added to `[project.scripts]`)

| Command | Purpose |
|---|---|
| `ad-setup [--check] [--only pncli|sources|powerbi|project] [--non-interactive] [--project <dir>]` | wizard; `--check` = doctor (no prompts, exit 1 on failures, TOON summary with per-step `hint`) |
| `ad-doctor` | alias of `ad-setup --check`; `session-bootstrap` step 3 calls it |
| `ad-pbip project <pbip-dir> [--out .agent/pbip]` | build/refresh projection; skips when `meta.json` hashes match |
| `ad-pbip check <pbip-dir> [--te2] [--bpa] [--server localhost:<port>|xmla] [--legacy-ok]` | cross-validate model↔report (+ naming/uniqueness rules); `--te2` runs TE2 build for real TMDL/DAX errors; `--server` evaluates every measure used by the report |
| `ad-pbip refs <pbip-dir> (--table T [--column C|--measure M] | --visual NAME | --page NAME)` | where-used / what-feeds-this (forward and reverse lineage) |
| `ad-pbip lint <tmdl-folder|file>` | TMDL syntax lint with line numbers |
| `ad-pbip measure set <pbip-dir> --table T --name N --expr-file f.dax [--format-string ..] [--display-folder ..] [--description ..]` | upsert a measure with correct indentation/fenced multi-line form; writes lineageTag; re-runs lint |
| `ad-pbip desktop` | list running Power BI Desktop instances: pid, port, workspace dir, window title, matched file |
| `ad-pbip launch <pbip>` | `os.startfile` the PBIP (refuses Store install only when detection says so) |
| `ad-pbip visual-query <pbip-dir> --visual NAME [--page P] --server <localhost:port|xmla> [--db <model>]` | generate the visual's DAX and run it via dscmd → TOON/TSV |
| `ad-jira whoami` | detect flavor/auth from pncli config, call `/myself`; store flavor in config |
| `ad-jira fields [--like Sprint]` | name ↔ id map (`GET /rest/api/3/field`); pins `Sprint`, `Story Points`, `Story point estimate` |
| `ad-jira changelog KEY... [--fields status,Sprint,"Story Points"] [--since ISO]` | rows: key, changelog_id, created_utc, author, field, fieldId, from, fromString, to, toString |
| `ad-jira sprint-replay --sprint <id|name> [--board <id>] [--jql ...] [--points-at commit|close] [--include-subtasks] [--compare-sprintreport]` | committed/completed points via replay; per-issue table + summary |
| `ad-impala --env .. --sql/--sql-file ..` | same flags as `ad-td` |
| `ad-sql-check --dialect teradata|hive|impala|oracle <file.sql>` | dialect pre-flight; also runs automatically inside `ad-td/ad-ora/ad-hive/ad-impala` (errors block with `ok:false` + hint + doc anchor; warnings pass through in `meta.warnings`) |
| `ad-uat expect <file> [--sheet ..] [--table-index n]` | expected values → TSV |
| `ad-uat plan <pbip-dir> --visual NAME [--ticket KEY]` | UAT recipe: measures → columns → source tables (from partition M) → SQL templates → commands to run (TOON) |
| `ad-uat reconcile --expected e.tsv [--jira j.tsv] [--hist h.tsv] [--pbi p.tsv] --key K --cols a,b [--window start,end] [--hist-coverage cov.tsv]` | tiered comparison + classification; writes `<KEY>-uat-findings.md` |

All commands print TOON via `agentdata.policy.render` / `toon.encode`; errors via `policy.error(msg, hint, source)`. Every entry point first calls `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (Windows cp1252 console vs `→ · ≤`). Output files under `OUT_DIR` (`.agent/out/`) except the projection (`.agent/pbip/`, committed) and edits (in the PBIP itself).

## Config

`~/.agentdata/config.json` (global, like pncli; **never contains secrets**; path overridable by `AGENTDATA_CONFIG` for tests):
```json
{"version": 1,
 "pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
 "jira": {"base_url": "…", "flavor": "cloud|dc", "auth": "basic|bearer", "api": "3|2",
          "fields": {"sprint": "customfield_10020", "story_points": ["customfield_10026", "customfield_10016"]}},
 "sources": {"teradata": {"envs": {"prod": {"mode": "native|odbc", "host": "…", "dsn": "…", "logmech": "KRB5|LDAP|TD2|TDNEGO", "tmode": "ANSI|TERA",
                                             "capabilities": {"trunc_date": true, "to_char": true, "listagg": false}}}},
             "hive": {"envs": {"prod": {"mode": "native|odbc", "host": "…", "port": 10000, "dsn": "…", "auth": "GSSAPI|PLAIN|LDAP", "version": "3|4"}}},
             "impala": {"envs": {"prod": {"mode": "native|odbc", "host": "…", "port": 21050, "dsn": "…", "auth": "GSSAPI|LDAP|NOSASL"}}},
             "oracle": {"envs": {"prod": {"dsn": "host:1521/service", "tns_admin": "…", "thick": false}}}},
 "powerbi": {"tenant_id": "…", "auth": "user|spn", "tools": {"te2_exe": "…", "dscmd_exe": "…", "pbi_desktop_exe": "…"},
             "workspaces": [{"name": "…", "id": "…", "xmla": "powerbi://api.powerbi.com/v1.0/myorg/…", "models": ["…"]}]},
 "verified": {"pncli": "2026-09-02", "jira": "2026-09-02", "teradata:prod": "2026-09-02", "powerbi:xmla:<ws>": "…"}}
```
Token resolution at runtime: `jira_api` reads `pncli.config_path`, walks `keys.jira_token` dot-path; env `JIRA_TOKEN`/`JIRA_EMAIL`/`JIRA_URL` override; nothing written or printed. `config.py` also exposes `project_facts()` (parsed `- key: value` lines from the project `AGENTS.md`) so CLIs default `--pbip`, `--env`, `te2_exe`, `dscmd_exe`, `pbi_workspace`, `pbi_model` from it.

Project stub additions (`templates/project-stub/AGENTS.md`): `pbip_path`, `pbi_xmla` (percent-encoded XMLA URL), `impala_env`, `jira_hist_table`, `jira_sprint_table`, `jira_board_id`, `skills_dir`, `ws_id`, `ds_id` (the last three are already referenced by skills but missing).

### Setup wizard steps (each: detect → show → ask → verify → write `verified.<step>`)
1. **pncli import** — `~/.pncli/config.json` exists? Parse JSON (not JSON → fail with hint; no YAML parser); print key *paths* with values masked; propose url/email/token keys by name heuristics (`url|base_url|host`, `email|user`, `token|api_token|pat`); confirm; verify via `GET /myself` (flavor detect). Also `pncli --help` once → `verified.pncli`.
2. **Sources** — for each of Teradata, Hive, Impala, Oracle: "have it? (y/n)"; show `pyodbc.drivers()` / `pyodbc.dataSources()` (64-bit Python sees only 64-bit DSNs; 64-bit admin is `C:\Windows\System32\odbcad32.exe`); choose `native` (teradatasql / impyla / oracledb thin) or `odbc` (pick DSN; Teradata ODBC uses `MechanismName=` + `UseIntegratedSecurity=1` for LDAP/KRB5, driver name matched from `pyodbc.drivers()` never hardcoded); env name(s); auth; `SELECT 1` (`SELECT 1 FROM DUAL` Oracle). **Capability probes** recorded for `ad-sql-check`: Teradata `tmode` (ANSI vs TERA → `=` case sensitivity), `TRUNC(CURRENT_DATE,'MM')`, `TO_CHAR(CURRENT_DATE,'YYYY-MM-DD')`, `LISTAGG`; Hive/Impala `SELECT version()`. Passwords (LDAP/PLAIN) → `keyring` under `teradata:<env>` / `oracle:<env>` (existing) / `hive:<env>` / `impala:<env>` (new).
3. **Power BI** — locate `TabularEditor.exe`, `dscmd.exe`, `PBIDesktop.exe` (well-known paths + `where`); `az account show` (offer `az login --allow-no-subscriptions`); `az rest --resource https://analysis.windows.net/powerbi/api --url https://api.powerbi.com/v1.0/myorg/groups` → pick workspaces; XMLA URL `powerbi://api.powerbi.com/v1.0/myorg/<Workspace%20Name>` — workspace names **must be RFC 3986 percent-encoded** (verified), `myorg` = home tenant (guests use the host tenant domain); requires Premium/PPU/Fabric capacity with XMLA **Read Write** enabled by the capacity admin (read-only is the default) and a PPU license for the user unless the model is on Premium capacity. Smoke test each chosen workspace+model: `TabularEditor.exe "<xmla>" "<model>" -S ping.csx` where `ping.csx` = `Info(Model.Tables.Count.ToString());` — verified that `-S` without `-B/-F/-TMDL/-D` loads, runs, exits without saving, exit 1 on connection failure; integrated/interactive auth by default (`-L user pass` for explicit creds, never stored). Store `verified.powerbi:xmla:<ws>` and record `dscmd_caps` (see DAX runner). Note both REST audiences: `https://analysis.windows.net/powerbi/api` (datasets/refresh) vs `https://api.fabric.microsoft.com` (item definitions).
4. **Project** (`--project <dir>`) — copy `templates/project-stub/`, fill facts from config (env names, tool paths, workspace/model, `pbip_path` by globbing `*.pbip`), append `.gitignore-additions` (+ `localSettings.json` for PBIP).
Registry: `Step` dataclass (`key, title, detect(), ask(), verify(), write()`), ordered list; `--only` filters; `--check` runs `detect+verify` only. A future source = one new Step file.

## Skills (new / changed) — all `< 120` lines, frontmatter `name`+`description` only, imperative numbered steps, STOP/handoff ending

New:
- `skills/pbip-projection/SKILL.md` — run `ad-pbip project`, read `MODEL.md`/`REPORT.md`/`LINEAGE.md`, staleness rule (meta hashes). `references/pbip-layout.md` (PBIP/PBIR/TMDL folder layout, `.platform`/`definition.pbir`/`version.json` constants, volatile fields, never touch `logicalId`/`name`/`$schema`).
- `skills/tmdl-edit/SKILL.md` — locate via `ad-pbip refs` → prefer `ad-pbip measure set` → other edits per `references/tmdl-syntax.md` → `ad-pbip lint` → commit → **mandatory** handoff → `pbi-validate`. `references/tmdl-syntax.md` (rules + worked examples below).
- `skills/pbi-validate/SKILL.md` — `ad-pbip check --te2`; if Desktop open (`ad-pbip desktop`; Desktop must be **reopened** after TMDL edits, it does not hot-reload) → `ad-pbip check --server localhost:<port>` + `ad-pbip visual-query` per affected visual; fail → `friction-log`; pass → `state-update phase=validating` → `pbi-deploy-te2` or `bitbucket-pr`.
- `skills/uat-report-visual/SKILL.md` — inputs: ticket, context file(s) in `.agent/in/`, visual/page name, optional table/measure. Steps: `ad-uat plan` → `ad-uat expect` → tier 3 `ad-pbip visual-query` → tier 2 SQL from `references/uat-sql-templates.md` via `ad-td` → tier 1 `ad-pncli jira search` + `ad-jira sprint-replay` → `ad-uat reconcile` → findings → `confluence-publish`. `references/uat-method.md` (tiers, taxonomy, coverage checks, replay conventions).
- `skills/jira-changelog/SKILL.md` — `ad-jira fields` once per project (pin ids in AGENTS.md), `ad-jira changelog`, `ad-jira sprint-replay`; when to use vs `ad-pncli jira search`. `references/jira-changelog.md` (response shapes, edge cases).

Changed:
- `router` — rows: PBIP/report/visual/page → `pbip-projection`; edit measure/column/TMDL/format string → `tmdl-edit`; validate report/broken visual/"does the report still work" → `pbi-validate`; UAT with document/CSV or "chart X wrong" → `uat-report-visual`; sprint report/committed/completed/changelog/field history → `jira-changelog`; Impala → `hive-query`. Remove `TMDL` from the `pbi-deploy-te2` row.
- `session-bootstrap` step 3 — `ad-doctor --quiet`; fail → print its hint (`ad-setup --only <step>`), STOP.
- `teradata-query` / `hive-query` / `oracle-query` — step 0 "read `references/<dialect>-sql.md` §limit/§dates before writing"; step 3 reads `meta.warnings`; `hive-query` gains Impala (`ad-impala`) and the `||` warning.
- `data-adapter` — new commands in the table; `references/sql-dialects.md` side-by-side.
- `uat-jira-vs-source` — add "sprint/points questions → `uat-report-visual`".
- `dax-studio-export` — `localhost:<port>` server option via `ad-pbip desktop`.
- `pbi-deploy-te2` / `pbi-refresh-xmla` — `tmdl_path` is the `<Model>.SemanticModel/definition` folder (must contain `model.tmdl`); workspace name in the XMLA URL must be percent-encoded (use `pbi_xmla` fact written by the wizard instead of interpolating `<pbi_workspace>`).

References live **inside skill folders** (`skills/<name>/references/*.md`) because `gh skill install` ships `skills/*` only; repo `docs/` keeps repo-level policy (`data-format-policy.md`, new `pbi-tools-parts.md`, `setup.md`).

## Key algorithms and verified format facts

### TMDL (`pbip/tmdl.py`) — verified from Microsoft's sample PBIP + Microsoft TMDL guidelines
Syntax facts to encode in parser, lint, writer and `references/tmdl-syntax.md`:
- Object header: `<type> <Name>` or `<type> <Name> = <expr>` (measure/partition/expression/calculated column default property). Types seen: `database`, `model`, `table`, `column`, `measure`, `partition`, `hierarchy`, `level`, `relationship`, `role`, `tablePermission`, `perspective`, `cultureInfo`/`culture`, `expression`, `annotation`, `extendedProperty`, `changedProperty`, `dataAccessOptions`, `ref`.
- Properties `key: value`; boolean properties are **bare keywords** (`isHidden`, `isKey`, `discourageImplicitMeasures`, `legacyRedirects`).
- **Indentation: Desktop writes one TAB per level**; spaces are accepted by the serializer but must be consistent within a file. Lint: mixed styles → error; default writer style = detected file style (tabs).
- Names with spaces or `. = : '` → **single quotes**, in declarations and references (`sortByColumn: 'Week Day (#)'`, `fromColumn: Sales.'Order Date'`).
- Multi-line expressions: **two valid forms** — ``` ``` ```-fenced block after `=` (Microsoft's recommended default; fence lines indented, content indented one level deeper than the header, closing fence on its own line) and a bare indented block after `=`. Writer always emits the fenced form. Parser accepts both: after `=` with empty remainder, consume lines indented deeper than the header until dedent; if the first such line is ```` ``` ````, consume until the closing fence.
- Descriptions: consecutive `///` lines **above** the object; `//` comments are **not supported** in TMDL (only inside DAX/M blocks). Lint: top-level `//` → error.
- `model.tmdl` ends with `ref table X` / `ref culture en-US` (sample) or `ref cultureInfo` (guidelines) / `ref role` / `ref perspective` lines — new tables need a `ref table` line; writer preserves whichever `ref culture*` form the file uses.
- Column block (Desktop output): `column Name` + `dataType`, `sourceColumn` (imported) or `= <dax>` (calculated), `lineageTag`, `summarizeBy`, `formatString`, `isHidden`, `sortByColumn`, `annotation SummarizationSetBy = Automatic|User`. Measure block: `measure 'Name' = <expr>` + `formatString`, `displayFolder`, `lineageTag`, optional `isHidden`. Partition: `partition Name = m` + `mode: import` + `source =` M block (or `= calculated` with DAX). Relationships live in `relationships.tmdl` as `relationship <guid>` + `fromColumn: T.C` / `toColumn: T.C` (+ `isActive: false`, `crossFilteringBehavior`). ⏳ resend will confirm minor details (hierarchy/level shape, `changedProperty`, `annotation PBI_*`).
- Desktop conventions (verified on Microsoft's sample): continuation lines of a multi-line expression sit at declaration depth **+2 tabs**; measures before columns; per-object property order = declaration → `dataType` → `isHidden` → `formatString` → `isAvailableInMdx` → `lineageTag` → `summarizeBy` → `sourceColumn` → `sortByColumn` → blank → `changedProperty = X` lines → blank-separated `annotation` lines. Booleans are bare only when true (`isAvailableInMdx: false` is written as key:value). `database.tmdl` must open with `database <name>`.
- **`lineageTag` policy (Microsoft guidance): do NOT write `lineageTag` on hand-created objects** — Desktop assigns GUIDs on first save; a copied/duplicated tag corrupts lineage. `measure set` omits it by default (`--lineage-tag` opts in). Never add `annotation PBI_*` by hand; new roles never get `PBI_Id`.
- Partition forms: `partition X = m` + `mode: import` + `source =` M block; `= calculated` + `source =` DAX block; `= entity` (Direct Lake) with a `source` block and no `=`; `= calculationGroup` with no source. `extendedProperty X =` takes an indented JSON block. Hierarchies: `hierarchy 'Name'` → `level L` → `column: C` (same table).
- File conventions: sample files are UTF-8, **LF, no BOM**, trailing newline; preserve whatever the file has, default LF/no BOM for new files (a BOM or CRLF flip turns a one-line edit into a whole-file diff); keywords lowercase; never touch `.platform` `logicalId`.
- Lint rules: spaces-vs-tabs mix, indent jump > 1 level, continuation lines not deeper than the declaration, unterminated fence, unquoted name containing space/`.`/`=`/`:`/`'` (declarations **and** references), duplicate `lineageTag` across the model (missing tag is fine), `sortByColumn`/relationship endpoints/hierarchy `column:` missing, `//` comment outside DAX/M, `database.tmdl` not starting with `database`, mixed CRLF/LF, missing trailing newline, table without `ref table` in `model.tmdl`.
- Worked examples in the reference: add measure (fenced, no lineageTag), add calculated column (`column X = <dax>` — grammar-derived, flagged verify-on-save), change `formatString`, add relationship, edit partition M, add table (file + `ref table`), add hierarchy.

### PBIR field references (`pbip/pbir.py`) — verified from Microsoft's JSON schemas
- All references are `QueryExpressionContainer` objects with exactly one expression key. Model-resolvable kinds: `Column{Expression,Property}`, `Measure{Expression,Property}`, `Hierarchy{Expression,Hierarchy}`, `HierarchyLevel{Expression(Hierarchy),Level}`, `Aggregation{Expression,Function}` (0 Sum,1 Avg,2 DistinctCount,3 Min,4 Max,5 Count,6 Median,7 StdDev,8 Var), `PropertyVariationSource`, wrappers `Min/Max/Percentile`. Skip: `Literal`, `NativeMeasure|NativeColumn|NativeVisualCalc` (inline DAX), `SelectRef`, `RoleRef`, `TransformTableRef`, `ThemeDataColor`, `ResourcePackageItem`.
- `SourceRef` has two forms: standalone `{"SourceRef":{"Entity":"Table"}}` in `field`/projection positions, and alias `{"SourceRef":{"Source":"s"}}` inside `filter.Where`/`prototypeQuery`, where `s` is the `Name` of an entry in the sibling `From[]` (`{Name, Entity, Type}`); resolve only `Type` 0 (model table); `Type` 1 = presentation object, 2 = expression table.
- Classification anchors: `visual.query.queryState.<Role>.projections[].field` (+ `queryRef` = `Entity.Property` or `CountNonNull(Entity.Property)`), `queryState.<Role>.fieldParameters[].parameterExpr`, `visual.query.sortDefinition.sort[].field`, `filterConfig.filters[].field` + `.filter.From/Where` (visual, page, report), `visual.expansionStates[].levels[]`, `objects.*[].selector.data[]`, `visualContainerObjects`. Conditional formatting values are **untyped** in the schema → do a **recursive walk** of every JSON file for objects keyed `Column|Measure|Aggregation|Hierarchy|HierarchyLevel|PropertyVariationSource` for completeness; use anchors for classification (role, filter, sort, format).
- Files: `definition/version.json` (`"2.0.0"`), `definition/report.json`, `definition/pages/pages.json` (`pageOrder`, `activePageName`), `pages/<pageId>/page.json` (`displayName`, `filterConfig`, `visualInteractions`), `pages/<pageId>/visuals/<visualId>/visual.json` (`name` = 20 hex, `position`, `visual.visualType`, `filterConfig`, `isHidden`, `parentGroupName`), `definition/bookmarks/*.json`, `definition/reportExtension.json` (report-level measures: entities/measures with DAX). `definition.pbir` (`version "4.0"`, `datasetReference.byPath.path` relative with `/`), `.platform` (never regenerate `logicalId`), `localSettings.json` (never commit).
- Naming rules to check: visual `name` unique per page (20 lowercase hex); page `name` unique per report; filter `name` (`Filter`+24 hex) **unique across the whole report**; `$schema` preserved, never bumped (compare path prefix only); `queryState` roles must be under `query.queryState`.
- Legacy `report.json` (single file, stringified `config`/`filters`/`query`/`dataTransforms`; `singleVisual.prototypeQuery.From/Select`, filter `expression` not `field`, `howCreated` numeric, bookmarks in `config.bookmarks[].explorationState`): supported **best-effort** behind `--legacy-ok` so the loader does not crash on older repos; not a first-class target.
- Volatile/noise for projection & diff: `position` floats (round 2dp in projection), `expansionStates`, `annotations`, `howCreated`, `themeCollection.customTheme.name` GUID rotation, `$schema` minor versions. Stable/load-bearing: `name`s, `pageOrder`, filter names, `logicalId`.

### Cross-reference (`pbip/check.py`)
Resolve `(Entity, Property)` against the normalized model: tables, columns (incl. calculated), measures, hierarchies+levels; report-level measures from `reportExtension.json` count as valid measures for their entity. Model lint: relationship endpoints, `sortByColumn`, duplicate lineageTags, DAX refs `'T'[C]`/`T[C]`/`[M]` (best-effort regex, warning severity). Report lint: naming/uniqueness rules above, `definition.pbir` path resolves to the model folder, `pageOrder` ↔ page folders consistent, bookmarks → existing visual names. `--te2`: `TabularEditor.exe "<Model>.SemanticModel\definition" -B "<tmp>\model.bim"` (the folder passed must directly contain `model.tmdl`; always include an action switch or TE2 opens its GUI). This is the authoritative check: it parses TMDL and builds the TOM graph, so it catches malformed TMDL with line info, invalid properties/enums, unresolved `fromColumn`/`toColumn`/`sortByColumn`/level columns, dangling `ref`s and **DAX syntax errors**. Exit 1 iff ≥1 error (warnings stay exit 0); `--bpa` adds `-A` (only high-severity BPA rules raise errors); add `-G`/`-V` for CI annotations. Stderr/stdout lines containing `Error` → findings. `-X <file>` (no deploy, emit TMSL) remains the deploy dry-run used by `pbi-deploy-te2`. `--server`: `EVALUATE ROW("v", [Measure])` per report-used measure via dscmd; plus INFO.VIEW.MEASURES()/COLUMNS() pull to cross-check the parse. Findings: `severity, kind, where (file:jsonpath|line), object, message, hint`; exit 1 on any `error`.

### Desktop discovery (`pbip/desktop.py`) — behaviour learned from pbi-tools `info` (AGPL: logic only, no code)
- Enumerate **`msmdsrv.exe`** processes (one per open Desktop document), not `PBIDesktop.exe`. Stdlib path: `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='msmdsrv.exe'\" | Select ProcessId,ParentProcessId,CommandLine | ConvertTo-Json"`.
- Workspace dir = cmdline `-s <dir>`, workspace name = `-n`; port file `<dir>\msmdsrv.port.txt` read as **UTF-16** (`encoding="utf-16"`, strip, int). Fallback when cmdline unavailable: glob `%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*\Data\msmdsrv.port.txt` (Store builds/`PBITOOLS_AppDataDir` differ, hence fallback only).
- Parent process = `PBIDesktop.exe`; report its PID. Open file: with `psutil` installed → `Process(ppid).open_files()` filtered to `.pbix/.pbit/.pbip`, excluding `%USERPROFILE%…TempSaves…`; without psutil → `Get-Process -Id <ppid> | Select MainWindowTitle` (`"<Name> - Power BI Desktop"`) and match `<Name>` to `*.pbip` basenames under the project (`pbip_path` fact / cwd glob). Elevated Desktop from non-elevated Python → skipped with a warning.
- Output rows: `pid, port, server (localhost:<port>), workspace_dir, title, file, matched`.

### DAX runner (`pbip/dax.py`)
- Visual → `SUMMARIZECOLUMNS(<group-by 'T'[C] …>, <TREATAS({…}, 'T'[C]) for categorical filters / FILTER(ALL('T'[C]), …) for ranges>, "M1", [M1], …)`; aggregation projections (`Aggregation` over a column) → `CALCULATE(SUM('T'[C]))` etc. by function code; `TOPN(500, …)` while exploring (existing convention).
- Run via `dscmd csv "<out.csv>" -s <server> [-d <db>] (-f q.dax | -q "<dax>")`. `-s localhost:<port>` is the documented way to reach a Desktop instance (the `--server "<name>.pbix"` shortcut of dscmd ≥ 3.3.0 is unverified for `.pbip`, so always use the port). `-f/--file` is unverified: `dax.py` probes `dscmd csv --help` once (cached in config `powerbi.tools.dscmd_caps`) and falls back to passing the file content via `-q`. `-d` for a Desktop workspace is a GUID-ish name: try without `-d`, else discover via DMV `SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS` through `-q`, else TE2 `-L "<name>" -S name.csx` (TE2 `-L` connects to a local Desktop instance by loaded file name). Parse CSV with `utf-8-sig` → `AgentTable` (reuse `csv2toon` logic); headers `Table[Column]` → bare column names (mirrors pbi-tools' header transform). Other dscmd commands used: `export csv <dir> -s -d [-t tables…]` (bulk), `vpax` (existing skill).
- Metadata cross-check: `EVALUATE INFO.VIEW.MEASURES()` / `INFO.VIEW.COLUMNS()` / `INFO.VIEW.TABLES()` → compare with TMDL parse (catches parser gaps); `EVALUATE 'Table'` for bulk export (pbi-tools `export-data` equivalent; names single-quoted, `'` in names escaped as `''`).

### Jira connector (`connectors/jira_api.py`) — verified shapes
- **Flavor detection**: host ends with `.atlassian.net` → `cloud`, API `3`, `Authorization: Basic base64(email:token)`. Else try `GET /rest/api/2/myself` with `Bearer <token>` (DC PAT), then Basic; record `flavor/auth/api`. Never log the token.
- **Per-issue changelog**: `GET /rest/api/{v}/issue/{key}/changelog?startAt=&maxResults=100` → `{values[], startAt, maxResults, total, isLast, nextPage}`; loop on `isLast`; use the *echoed* `maxResults`. Items: `field, fieldId, fieldtype, from, fromString, to, toString` (`toString` missing from Atlassian's schema but present in responses). `author` may be null. `created` ISO with ms and `+0000` (no colon) → `strptime("%Y-%m-%dT%H:%M:%S.%f%z")`, normalize to UTC.
- **DC fallback**: probe `/rest/api/2/issue/{key}/changelog`; on 404 use `?expand=changelog` → `changelog.histories[]` (newest-first); if `changelog.total != len(histories)` the expand was truncated → error with hint (no other DC path).
- **Bulk** (cloud only): `POST /rest/api/3/changelog/bulkfetch` `{issueIdsOrKeys[≤1000], fieldIds[≤10], maxResults, nextPageToken}` → `{issueChangeLogs[{issueId, changeHistories[]}], nextPageToken}`; `created` may be epoch seconds — accept int or ISO; dedupe by `(issueId, changelog.id)`; on 404 fall back to per-issue.
- **Fields**: `GET /rest/api/3/field` → name↔id; coalesce `Story Points` and `Story point estimate`. **Sprint** item: `from`/`to` = full comma-separated sprint **ID** sets, `fromString`/`toString` = names; prefer IDs; `added = to − from`, `removed = from − to`.
- **Status categories**: `GET /rest/api/3/status` → id → `statusCategory.key == "done"`; never name-match.
- **Agile**: `GET /rest/agile/1.0/sprint/{id}` (`state future|active|closed`; dates **absent** on future sprints; offsets like `+10:00`), `GET /rest/agile/1.0/board/{id}/sprint?state=`, candidate set = JQL `sprint = <id>` ∪ `/sprint/{id}/issue` (current only; `fields.closedSprints[]`).
- **Rate limits**: 429 → honour `Retry-After`; missing → exponential backoff (1,2,4,8 s, max 5). Proxy/CA: `urllib` honours `HTTPS_PROXY`; `ssl.create_default_context(cafile=os.environ.get("AGENTDATA_CA_BUNDLE"))`.
- Optional cross-check only: `GET /rest/greenhopper/1.0/rapid/charts/sprintreport?rapidViewId=&sprintId=` (undocumented) behind `--compare-sprintreport`.

### Sprint replay (`uat/sprint.py`) — backward replay
`value_at(current, items, t)`: start from the **current** value; walk that field's items newest-first; for each with `created > t` set `v = from`; stop at first `created <= t`. Correct when a field was set at creation with no changelog entry. Half-open boundary (event at exactly `startDate` counts as before start). Sort by `(created, changelog_id)`; one changelog entry is atomic. All timestamps tz-aware UTC.
- `T_close = completeDate or endDate` (active → `now()`, flagged provisional).
- `committed = Σ points_at(startDate)` over issues with `S ∈ sprints_at(startDate)`; `completed = Σ points_at(T_close)` over issues with `S ∈ sprints_at(T_close)` and `status_category_at(T_close) == done`, excluding done-transitions outside `[startDate, T_close]` or made while `S ∉ sprints` (`completed_in_another_sprint`).
- Per issue: `added_after_start`, `removed_before_close`, `re_estimated`, `estimated_mid_sprint`, `carried_over`, `is_subtask` (excluded by default). `--points-at commit|close` (default `close`, stated in output).

### Reconcile (`uat/reconcile.py`)
Join on `--key`; compare tiers T1 jira, T2 hist, T3 pbi, plus `expected`. Truth = highest available tier. Classes: `report-bug` (T3≠T2, T2=T1), `history-gap` (T2≠T1 and coverage fails: no history rows covering the window or null points), `lag` (T2≠T1 and max hist timestamp < window end), `mapping-bug` (T2≠T1 with coverage OK), `expectation-wrong` (expected ≠ all agreeing tiers), `unexplained`. Coverage from `--hist-coverage cov.tsv` (per key: first_ts, last_ts, n_rows) produced by a template SQL. Findings TOON (counts + first 20 per class) and `<KEY>-uat-findings.md` (≤ 40 lines) with an explicit "history table cannot reproduce Jira" callout for `history-gap`.

### SQL pre-flight (`sqlcheck/rules.py`) — E = blocks, W = `meta.warnings`; comments/strings stripped before matching
- Common: `GROUP BY <ordinal>` (W; E for Oracle).
- **Teradata**: `LIMIT n` (E → `TOP n`/`SAMPLE n`/`QUALIFY ROW_NUMBER()`), `FETCH FIRST` (E), backticks (E → `"…"`), `AS STRING` (E → `VARCHAR(n)`), `%` modulo (E → `MOD`), `TOP` with `QUALIFY` (E), `/*+` hints (E), `FROM DUAL` (W), `date_add|datediff|date_format(` (E), `SUM(int)/COUNT` without `CAST` (W: integer truncation), `TRUNC(date,'MM')`/`TO_CHAR`/`LISTAGG` when probe false (E with fallback), string `=` when `tmode=TERA` (W: case-insensitive unless `CASESPECIFIC`).
- **Oracle**: `LIMIT` (E → `FETCH FIRST n ROWS ONLY`), `TOP n` (E), `FROM <t> AS <alias>` (E), FROM-less SELECT (E → `FROM DUAL`), `ROWNUM` with `ORDER BY` in same block (W), `= ''` (W → `IS NULL`), `AS STRING|VARCHAR(` (W → `VARCHAR2`), backticks (E), `GROUP BY <ordinal>` (E), string literal vs DATE column without `TO_DATE`/`DATE '…'` (W).
- **Hive**: `TOP n`/`FETCH FIRST`/`SAMPLE n` (E → `LIMIT`), `QUALIFY` when `version < 4` (E), `LIMIT <non-literal>` (E), `"double-quoted identifiers"` (E → backticks), `FROM DUAL` (W), `SYSDATE`/`TO_CHAR`/`TO_DATE(x, fmt)` (E), `trunc(d,'DD'|'WW'|…)` (E: MONTH/QUARTER/YEAR only), `NVL(a,b,c)` (W).
- **Impala**: Hive set plus `||` (E → `concat()`; `||` is logical OR), `QUALIFY` (E), `LATERAL VIEW` (E), `collect_list|collect_set` (E → `group_concat`), `date_format(` (E → `from_timestamp`), `DATE_TRUNC(ts,'MM')`/`TRUNC('MONTH', ts)` arg order (E), `CONCAT(` with possible NULLs (W), unquoted reserved words (W: backtick all identifiers).
Output: `meta{ok, dialect, errors, warnings}` + `findings[n]{severity,line,rule,message,fix,doc}`.

### Dialect references (outline; facts tagged verified / verify-on-instance in the file)
`skills/teradata-query/references/teradata-sql.md`, `skills/hive-query/references/hive-impala-sql.md`, `skills/oracle-query/references/oracle-sql.md`, `skills/data-adapter/references/sql-dialects.md`. Sections: limit/offset, QUALIFY, dates, NULLs (+ Oracle `''` IS NULL), strings (concat, substr, `instr(str,sub)` vs `locate(sub,str)`, replace, regex, case sensitivity), types/division/modulo, identifiers, aggregation/window/string-agg, set ops, joins, temp objects/CTE, metadata queries, scalar select, top-10 gotchas, "verify on your instance" list (Teradata `tmode`, `TRUNC` date overload, `TO_CHAR`, `LISTAGG`; Hive version; `hive.datetime.formatter`). Grammar-verified headline facts: Impala `||` = logical OR; Hive `||` = concat; Hive 4 QUALIFY / Hive 3 none / Impala none / Oracle none (26ai only); Hive+Impala `EXCEPT|MINUS`; Hive `LIMIT` literals only; Hive `trunc` MONTH/QUARTER/YEAR only; Hive `nvl` = coalesce; Impala `TRUNC(ts,unit)` vs `DATE_TRUNC(unit,ts)`; Impala `/` → DOUBLE, `DIV`; Teradata int/int truncates, no `%`; Oracle ROWNUM+ORDER BY, no `AS` on table alias, `FROM DUAL`, `d1-d2` fractional.

### Connectors (existing, touched)
- `teradata.py`: `mode=odbc` (pyodbc, driver from `pyodbc.drivers()`, `MechanismName`, `UseIntegratedSecurity=1`) or native `teradatasql.connect(host, logmech, tmode, user/password from keyring)`; `--timeout` where supported.
- `hive.py`/`impala.py`: impyla `connect(host, port, auth_mechanism, use_ssl, kerberos_service_name)`; ODBC DSN via pyodbc when `mode=odbc`.
- `oracle.py`: thin-mode `config_dir`/`TNS_ADMIN`; thick kept for KRB5.
- Lookup order everywhere: CLI flag → env var (existing `TD_HOST_<ENV>` etc.) → config → error with hint `ad-setup --only sources`.

## `docs/pbi-tools-parts.md` — what we learned and re-implemented (logic only)
- License: **AGPL-3.0-or-later**; we do not copy code, templates, or schemas; we do not invoke its binaries. Facts about Power BI Desktop/AS are not copyrightable.
- Ported behaviours: `info` → `ad-pbip desktop` (msmdsrv cmdline `-s`/`-n`, UTF-16 port file, parent = PBIDesktop, open-file filtering incl. `TempSaves`); `export-data` → `ad-pbip dax`/`visual-query` via dscmd (`$SYSTEM.TMSCHEMA_TABLES` / `EVALUATE 'Table'`, bare-column headers); PbixProj normalization ideas (sorted/stable output, volatile-field stripping) → projection writer; `launch-pbi` → `ad-pbip launch`.
- Not ported: `extract`/`compile` (PBIX-only; Desktop opens PBIP natively; pbi-tools cannot read PBIP), `deploy` (compiles PBIX + Imports API; model via TOM/XMLA — TE2 already covers the model), `cache`, `git`, `-modelSerialization Tmdl` (Microsoft `TmdlSerializer`; TE2 `-B` covers BIM export).
- Stretch (documented, not built now): Fabric item-definition API deploy of PBIR report/TMDL model (`POST /v1/workspaces/{ws}/reports` / `semanticModels`, `updateDefinition` replaces the whole definition, never include `.platform`, `format=PBIR`/`TMDL`, 202 + `Operation-Id`/`Location` polling, `msal` for tokens); rename propagation across TMDL + PBIR.

## Repo housekeeping in the same change
- `pyproject.toml`: new scripts + extras; `.gitignore` fix (`build/` and `dist/` on separate lines).
- `README.md`: install → `pip install -e ".[dev]"` then `ad-setup`; layout rows for new dirs; Desktop preview features to enable (PBIP save, TMDL storage, PBIR) — names marked as reported, TMDL upgrade is one-way.
- `HANDOFF.md`: checklist updated (done items ticked; new open items: Fabric REST deploy, rename propagation, Spark, verify Teradata probes on a real instance).
- `docs/data-format-policy.md`: connector notes for `ad-pbip`, `ad-jira`, `ad-uat`, `ad-sql-check` + changelog line (no threshold change); fix the rule-7 doc mismatch (`render_nested` writes `.tsv` only).
- Defects fixed along the way: `--timeout` no-op in teradata/hive where the driver allows; `ad-pncli raw --raw` dead flag.

## Tests (pytest, style of `tests/test_toon.py`)
- `tests/fixtures/sample.pbip/` — `Sample.pbip`, `Sample.Report/` (`.platform`, `definition.pbir` byPath, `definition/version.json`, `report.json`, `pages/pages.json`, 2 pages, 4 visuals incl. one referencing a missing column and one with a `filterConfig` alias-form filter, one bookmark), `Sample.SemanticModel/` (`.platform`, `definition.pbism`, `definition/database.tmdl`, `model.tmdl` with `ref table` lines, `tables/Sales.tmdl` (fenced + indented multi-line measures, calculated column, M partition), `tables/Calendar.tmdl`, `relationships.tmdl`, `expressions.tmdl`); one file saved with CRLF+BOM to exercise preservation.
- `test_tmdl.py`, `test_pbir.py` (anchors + recursive walk + alias resolution + Type 1/2 skipped), `test_check.py`, `test_project.py` (deterministic, hash skip), `test_dax.py` (visual → SUMMARIZECOLUMNS text), `test_desktop.py` (CIM JSON fixture + UTF-16 port file in tmp dir).
- `test_jira_api.py` (recorded pages, bulkfetch int `created`, DC expand truncation, fields, future sprint w/o dates, flavor detection, token never in output), `test_sprint.py` (edge-case table), `test_reconcile.py`, `test_sqlcheck.py` (each rule + canonical queries clean + capability gating), `test_setup.py` (non-interactive with fake detectors; no secrets in config; doctor exit codes), `test_config.py`, `test_skills.py` (< 120 lines, frontmatter keys, router rows resolve, references exist).

## Verification (end-to-end)
1. `pip install -e ".[dev]" && pytest -q` green (Linux, this session).
2. `ad-pbip project tests/fixtures/sample.pbip && ad-pbip check …` → finding on the broken visual; fixed copy → exit 0.
3. `ad-pbip measure set …` on the fixture → `ad-pbip lint` clean; `git diff` shows only the inserted fenced block; CRLF/BOM preserved.
4. `ad-sql-check --dialect impala` on `a || b` → `ok:false` + hint; `--dialect oracle` on `LIMIT` → `ok:false`; canonical queries pass.
5. `ad-setup --check --non-interactive` with nothing installed → per-step failures with hints, exit 1; with fakes → exit 0.
6. On Windows (user): `ad-setup` end-to-end incl. pncli import + `ad-jira whoami`; `ad-pbip desktop` lists an open Desktop; `ad-pbip check --te2` on a real PBIP; `ad-pbip visual-query` returns rows; `ad-jira sprint-replay --compare-sprintreport` on a closed sprint matches or explains deltas.

## Implementation order (PR slices)
1. `config.py` + `setup/` (`ad-setup`, `ad-doctor`) + README/HANDOFF + `session-bootstrap` + connector config lookup.
2. `sqlcheck/` + dialect references + query-skill updates + `ad-impala`.
3. `jira_api.py` + `ad-jira` + `uat/sprint.py` + skill `jira-changelog`.
4. `pbip/` tmdl + pbir + normalize + project + check + refs + lint + `measure set` + skills `pbip-projection`, `tmdl-edit`, `pbi-validate` + fixtures.
5. `desktop.py` + `dax.py` (`ad-pbip desktop|launch|visual-query`, `check --server`) + `dax-studio-export` update.
6. `uat/expect.py` + `uat/reconcile.py` + `ad-uat` + skill `uat-report-visual` + router update + `docs/pbi-tools-parts.md` + policy changelog + defect fixes.

## Residual unknowns (verify on the Windows laptop during slice 5; none block the design)
- dscmd: `-f/--file` support and exit codes (probe `dscmd csv --help`; `-q` fallback built in); `-d` optional for a single-database Desktop instance.
- TE2 `-L "<name>"` matching a PBIP window (documented for `.pbix` names).
- TMDL: exact emitted form of `column X = <dax>` calculated columns; keyword case sensitivity; BOM tolerance (we never write one).
- Preview-feature checkbox names in Desktop (README lists them as reported).


## Design-pass corrections (adopted after approval; refine, do not change, the approved scope)
1. **Jira Cloud search** uses `GET /rest/api/3/search/jql` (`nextPageToken` paging, explicit `fields` list — it returns ids only otherwise); fall back to `/rest/api/3/search` on 404/410; DC keeps `/rest/api/2/search` (`startAt`/`total`).
2. **Punted issues** are not reachable via JQL `sprint = <id>` (removed issues drop the id). `sprint-replay` widens the candidate set with `--jql` (recommend `project = X AND updated >= "<start - 1d>"`) and states the limitation in the skill and reference.
3. **Changelog columns** are snake_case: `key, changelog_id, created_utc, author, field, field_id, field_type, from_id, from_str, to_id, to_str` (`from` is a Python keyword; mixed casing is error-prone in TSV).
4. **`ad-jira`** also gets `statuses` (id, name, category) and `sprints --board ID [--state]` (needed to resolve `--sprint NAME`). Field ids are pinned in **global config** via `ad-jira fields --pin` (per Jira instance), not in AGENTS.md; AGENTS.md may override with `jira_sprint_field`/`jira_points_field`.
5. **`ad-doctor` is offline by default** (it runs every session); network checks (`/myself`, `SELECT 1`, XMLA) run only with `--online` or inside `ad-setup`.
6. **Wizard I/O**: prompts and progress on **stderr**; TOON only on stdout. Non-interactive answers come from a JSON answers file / env; an answers file containing a `password` key is rejected (exit 2).
7. **sqlcheck**: Hive n-ary `NVL(a,b,c)` = W with fix `COALESCE` (Hive's `nvl` is `coalesce`, so it runs; Impala's `nvl` is 2-arg → E). Teradata has no `LISTAGG`: the probe records `false` and the fix is the `XMLAGG(TRIM(col) || ',' ORDER BY col)` idiom. Hive/Impala `version` lives under `capabilities` (single read path). Operator escape `AGENTDATA_SQLCHECK=warn|off` exists, is shown by the doctor, and is never mentioned in skills.
8. **Reconcile** adds class `missing` (key present in only one tier) and `--tol` numeric tolerance; coverage TSV contract: `key, first_ts, last_ts, n_rows, points_null`.
9. **Shared connector helpers** `connectors/hs2.py` (impyla for Hive+Impala) and `connectors/odbc.py` (pyodbc DSN path) so hive/impala/teradata do not duplicate code; `policy.render(t, raw, extra=)` gains an `extra` meta dict (used for `meta.warnings` and `grain`); `render_nested(raw=)` makes the `ad-pncli raw --raw` fix real.
10. **Oracle**: default thin mode; ask about `TNS_ADMIN`/thick only when `SELECT 1 FROM DUAL` fails.
11. **Templates**: `templates/project-stub/` stays where it is; the project step resolves it relative to `agentdata.__file__/..` (editable install, as README already prescribes).
12. **Timestamps**: `parse_ts` accepts `+0000`, `+10:00`, `Z`, epoch seconds and milliseconds (`> 1e11` → ms); never rely on `fromisoformat` for `+0000` on 3.10.
13. **Windows**: `az` resolves as `az.cmd` via `shutil.which`; `winkerberos` (not `kerberos`) for impyla GSSAPI on Windows; `klist` absence is a warning, never a failure; `AGENTDATA_CA_BUNDLE`/`SSL_CERT_FILE` for corporate CAs, never disable verification.

## Status after implementation (2026-09-02)

All six slices are committed (one commit each) and pushed; `pytest -q` → 96 passed. Entry points: `ad-setup`, `ad-doctor`,
`ad-sql-check`, `ad-impala`, `ad-jira`, `ad-pbip`, `ad-uat` (plus the original `ad-*`). New skills: `jira-changelog`,
`pbip-projection`, `tmdl-edit`, `pbi-validate`, `uat-report-visual`; references live under each skill's `references/`.

**Verify on the Windows laptop (cannot be exercised from Linux CI):** `ad-setup` end to end (pncli import → `ad-jira whoami`
flavor detection, ODBC DSN listing, keyring, TE2 XMLA ping, `az rest` workspace listing); `ad-pbip desktop` finding an open
Desktop; `ad-pbip check --te2` on a real PBIP; `ad-pbip visual-query --server localhost:<port>` (dscmd `-f` vs `-q`);
`ad-jira sprint-replay --compare-sprintreport` on a closed sprint. Anything that fails there is a bug report against the
matching module, not a design gap.
