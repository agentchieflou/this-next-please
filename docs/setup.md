# Setup: `ad-setup` and `ad-doctor`

Update first, configure second: **`ad-update`** reinstalls the CLI from GitHub and every skill, then
`ad-update --check` shows the version and commit you are actually running (see README → Install and update).

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
| `sources` | per Teradata / Hive / Impala: environments, native driver or ODBC DSN (lists what this 64-bit Python can see), auth mechanism, user. **Oracle is asked differently** (see below): hostname, port, service name or SID, because there is no ODBC DSN to point at. Then `SELECT 1` and capability probes | `sources.<s>.envs.<env>.*`, `capabilities`, `verified.<s>:<env>`; passwords → `keyring` service `<s>:<env>` |
| `powerbi` | locates `TabularEditor.exe`, `dscmd.exe`, `PBIDesktop.exe` and **`az`** (a `.cmd`, searched on PATH and in `%ProgramFiles%\Microsoft SDKs\Azure\CLI2\wbin`); `az login`; lists workspaces via the Power BI REST API; percent-encodes the XMLA URL; smoke-tests each workspace/model with a one-line Tabular Editor script | `powerbi.tools.*` (incl. `az_exe`), `powerbi.workspaces[]`, `powerbi.tenant_id`, `verified.powerbi:xmla:<ws>` |
| `project` | `--project DIR`: writes the packaged project stub into DIR and fills the facts it knows (env names, tool paths, workspace/model/XMLA, first `*.pbip`) | `AGENTS.md`, `.agent/state.json`, `.gitignore` additions (never overwrites existing files) |

Non-interactive (Copilot terminals have no stdin for prompts):
`ad-setup --only project --non-interactive --offline --project . --set project.jira_project=RDSD`. `--set key=value`
answers one prompt key inline (repeatable; `true`/`false` for yes-no prompts; wins over `--answers`). `--answers
answers.json` still works and is read in any encoding PowerShell produces (UTF-8 BOM, UTF-16); answers must never
contain passwords — store them once interactively. `ad-setup --offline` skips network verification.

Repair mode: **`ad-setup --patch`** runs the checks first and then re-asks ONLY the settings behind the rows that
fail — one wrong DSN costs one env's questions, not the whole wizard. Every other answer silently keeps its stored
value, and steps with no failures are never entered. `--include-warnings` covers `warn` rows too; `--only <step>`
narrows it further; `--set key=value` / `--answers` make it non-interactive. The output names what it repaired
(`repairing[]`, `asked[]`) and then the state afterwards. Each check row carries the prompt keys that fix it, so
`--patch` never guesses.

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
`IMPALA_HOST_<ENV>`, `IMPALA_PORT`, `ORA_HOST_<ENV>`, `ORA_PORT_<ENV>`, `ORA_SERVICE_<ENV>`, `ORA_SID_<ENV>`,
`ORA_DSN_<ENV>`, `ORA_USER`, `ORACLE_CLIENT_LIB`, `TNS_ADMIN`;
Jira: `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`; pncli launcher: `PNCLI_EXE`; TLS: `AGENTDATA_CA_BUNDLE`.

## Oracle: the four fields, not one string

Teradata, Hive and Impala can name an ODBC DSN, so one value identifies the connection. Oracle has no such registry,
and python-oracledb wants a connect string — which is why SQL Developer's Basic tab asks for **Name, Hostname, Port,
Service name**. `ad-setup` now asks for exactly those:

```
[oracle] connection names, e.g. OIMPROD1_ROSVC (comma-separated)   <- the Name; it is the --env value
[oracle:OIMPROD1_ROSVC] connection style (basic/tns)
[oracle:OIMPROD1_ROSVC] hostname                                   <- exag1301-scan1.example.net
[oracle:OIMPROD1_ROSVC] port                                       <- 1521
[oracle:OIMPROD1_ROSVC] identified by (service/sid)
[oracle:OIMPROD1_ROSVC] service name                               <- oimprod1_rosvc.prod.example.net
```

They are stored as `host`, `port`, `service_name` (or `sid`) and composed into the connect string at call time:
`host:port/service` (Easy Connect), or the `(DESCRIPTION=…(SID=…))` form when identified by SID. Choose `tns` instead
to give a TNS alias or a connect string you already have — that value is used verbatim, and `TNS_ADMIN` points at the
directory holding `tnsnames.ora`. Every `ad-doctor` run prints the composed target next to the env, so a wrong port or
service name is visible without connecting. A host with no service name or SID fails the check by name rather than at
query time. Oracle never uses the ODBC mode: an ODBC DSN handed to python-oracledb would be read as a TNS alias.

## Windows notes
- Console scripts land in the per-user Scripts folder when site-packages is not writeable; if `ad-*` is "not recognized", use `python -m agentdata <command>` (identical arguments) or add that folder to PATH.
- **npm-installed tools have no `.exe`.** pncli is an npm package (`npm install -g @kolatts/pncli`), so it lands as `pncli.cmd`; `az` is `C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd`. Windows `CreateProcess` only appends `.exe`, which is why launching the bare name returns `[WinError 2] The system cannot find the file specified`. `agentdata/proc.py` resolves PATHEXT, the npm global prefix (`%APPDATA%\npm`) and each tool's install dir (the Azure CLI `wbin`), then runs an npm shim's Node entry point directly so an argument like `updated >= '2026-01-01'` is never re-parsed by cmd.exe. `ad-pncli where` prints what resolved; `ad-setup --patch` pins a path in `pncli.exe` / `powerbi.tools.az_exe`; `PNCLI_EXE` overrides.
- **A `.cmd` that is not an npm shim** (az) is run as `cmd.exe /d /s /c "<quoted line>"` passed to Windows **as one string**. Handing that line to `subprocess` as a list would put it through `list2cmdline`, which backslash-escapes the inner quotes; cmd.exe then reads `\"\"C:\Program` as a filename and answers *"The filename, directory name, or volume label syntax is incorrect"*.
- A 64-bit Python sees only 64-bit ODBC drivers/DSNs; configure them in `C:\Windows\System32\odbcad32.exe`.
- Kerberos (`KRB5`/`GSSAPI`) needs a ticket (`klist`); impyla on Windows needs `pip install winkerberos`.
- `az` resolves to `az.cmd`; `ad-setup` offers `az login --allow-no-subscriptions` when not signed in.
- Console encoding: every `ad-*` command switches stdout to UTF-8 (TOON uses `→ · ≤`).
- File encoding: Windows PowerShell 5.1 writes a BOM with `Set-Content -Encoding utf8` / `Out-File` and UTF-16 with `>`. Every `ad-*` reader (answers, `AGENTS.md`, config, TSV, SQL and DAX files, pncli config, state) sniffs the BOM and accepts the file (`agentdata/textio.py`); the tools themselves write UTF-8 without BOM. When you must write a file from PowerShell use `[IO.File]::WriteAllText($absolutePath, $text)`; for state use `ad-state set`.
- Power BI XMLA needs Premium/PPU/Fabric capacity with the XMLA endpoint set to Read Write by the capacity admin.
