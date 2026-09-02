# Setup: `ad-setup` and `ad-doctor`

`ad-setup` is the guided, idempotent wizard a new laptop runs after installing the CLI
(`pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"` — never inside a project repo). `ad-doctor` is the offline
health check that `session-bootstrap` runs at the start of every Luna session (`--online` adds network checks).
Prompts go to stderr; only TOON goes to stdout. Re-running shows current values as defaults.

The skills are installed separately and once per laptop:
`gh skill install agentchieflou/this-next-please --all --scope user`. `--all` installs every skill without opening the
interactive picker (its first row is a search box that swallows Enter, so paging requires arrowing down first);
`--scope user` makes them available in every repo instead of only the current one.

## Steps (`--only <key>` runs one)
| key | what it does | writes |
|---|---|---|
| `pncli` | resolves the pncli launcher (PATH + PATHEXT + the npm global prefix) and proves it starts with `--version`; finds `~/.pncli/config.json`, lists its keys (values masked), asks which keys hold the Jira URL / email / token; verifies with `/myself` and detects Cloud (v3, Basic) vs Data Center (v2, Bearer) | `pncli.exe` (the resolved shim), `pncli.config_path`, `pncli.keys.*` (key **names**), `jira.base_url/flavor/auth/api`, `verified.jira` |
| `sources` | per Teradata / Hive / Impala / Oracle: environments, native driver or ODBC DSN (lists what this 64-bit Python can see), auth mechanism, user; `SELECT 1` smoke test; capability probes | `sources.<s>.envs.<env>.*`, `capabilities`, `verified.<s>:<env>`; passwords → `keyring` service `<s>:<env>` |
| `powerbi` | locates `TabularEditor.exe`, `dscmd.exe`, `PBIDesktop.exe`; `az login`; lists workspaces via the Power BI REST API; percent-encodes the XMLA URL; smoke-tests each workspace/model with a one-line Tabular Editor script | `powerbi.tools.*`, `powerbi.workspaces[]`, `powerbi.tenant_id`, `verified.powerbi:xmla:<ws>` |
| `project` | `--project DIR`: writes the packaged project stub into DIR and fills the facts it knows (env names, tool paths, workspace/model/XMLA, first `*.pbip`) | `AGENTS.md`, `.agent/state.json`, `.gitignore` additions (never overwrites existing files) |

Non-interactive (Copilot terminals have no stdin for prompts):
`ad-setup --only project --non-interactive --offline --project . --set project.jira_project=RDSD`. `--set key=value`
answers one prompt key inline (repeatable; `true`/`false` for yes-no prompts; wins over `--answers`). `--answers
answers.json` still works and is read in any encoding PowerShell produces (UTF-8 BOM, UTF-16); answers must never
contain passwords — store them once interactively. `ad-setup --offline` skips network verification.

Session state: `ad-state show` / `ad-state set phase=<phase> active_ticket=<KEY> --artifact <path>=<what> --question "…"`
is the only writer of `.agent/state.json` (validated keys and phases, `last_updated`, artifacts pruned after 7 days,
UTF-8 without BOM).

## Config file
`~/.agentdata/config.json` (override the path with `AGENTDATA_CONFIG`). It never contains a credential: `save()`
refuses keys that look like one. Capability probes recorded per source env (used by `ad-sql-check`): Teradata `tmode`
(ANSI vs TERA decides whether `=` is case-sensitive), `trunc_date`, `to_char`, `listagg`; Hive/Impala `version`/`major`.

## Precedence for every setting
CLI flag → environment variable → `~/.agentdata/config.json` → project `AGENTS.md` fact → error with a hint.
Env overrides keep working: `TD_HOST_<ENV>`/`TD_HOST`, `TD_USER`, `TD_LOGMECH`, `HIVE_HOST_<ENV>`, `HIVE_PORT`,
`IMPALA_HOST_<ENV>`, `IMPALA_PORT`, `ORA_DSN_<ENV>`, `ORA_USER`, `ORACLE_CLIENT_LIB`, `TNS_ADMIN`;
Jira: `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`; pncli launcher: `PNCLI_EXE`; TLS: `AGENTDATA_CA_BUNDLE`.

## Windows notes
- Console scripts land in the per-user Scripts folder when site-packages is not writeable; if `ad-*` is "not recognized", use `python -m agentdata <command>` (identical arguments) or add that folder to PATH.
- **npm-installed tools have no `.exe`.** pncli is an npm package (`npm install -g @kolatts/pncli`), so it lands as `pncli.cmd`; `az` is `az.cmd`. Windows `CreateProcess` only appends `.exe`, which is why launching the bare name returns `[WinError 2] The system cannot find the file specified`. `agentdata/proc.py` resolves PATHEXT and the npm global prefix (`%APPDATA%\npm`), then runs the shim's Node entry point directly so an argument like `updated >= '2026-01-01'` is never re-parsed by cmd.exe. `ad-pncli where` prints what resolved; `ad-setup --only pncli` pins it in `pncli.exe`; `PNCLI_EXE` overrides.
- A 64-bit Python sees only 64-bit ODBC drivers/DSNs; configure them in `C:\Windows\System32\odbcad32.exe`.
- Kerberos (`KRB5`/`GSSAPI`) needs a ticket (`klist`); impyla on Windows needs `pip install winkerberos`.
- `az` resolves to `az.cmd`; `ad-setup` offers `az login --allow-no-subscriptions` when not signed in.
- Console encoding: every `ad-*` command switches stdout to UTF-8 (TOON uses `→ · ≤`).
- File encoding: Windows PowerShell 5.1 writes a BOM with `Set-Content -Encoding utf8` / `Out-File` and UTF-16 with `>`. Every `ad-*` reader (answers, `AGENTS.md`, config, TSV, SQL and DAX files, pncli config, state) sniffs the BOM and accepts the file (`agentdata/textio.py`); the tools themselves write UTF-8 without BOM. When you must write a file from PowerShell use `[IO.File]::WriteAllText($absolutePath, $text)`; for state use `ad-state set`.
- Power BI XMLA needs Premium/PPU/Fabric capacity with the XMLA endpoint set to Read Write by the capacity admin.
