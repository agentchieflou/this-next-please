# Setup: `ad-setup` and `ad-doctor`

`ad-setup` is the guided, idempotent wizard a new laptop runs after `pip install -e .`. `ad-doctor` is the offline
health check that `session-bootstrap` runs at the start of every Luna session (`--online` adds network checks).
Prompts go to stderr; only TOON goes to stdout. Re-running shows current values as defaults.

## Steps (`--only <key>` runs one)
| key | what it does | writes |
|---|---|---|
| `pncli` | finds `~/.pncli/config.json`, lists its keys (values masked), asks which keys hold the Jira URL / email / token; verifies with `/myself` and detects Cloud (v3, Basic) vs Data Center (v2, Bearer) | `pncli.config_path`, `pncli.keys.*` (key **names**), `jira.base_url/flavor/auth/api`, `verified.jira` |
| `sources` | per Teradata / Hive / Impala / Oracle: environments, native driver or ODBC DSN (lists what this 64-bit Python can see), auth mechanism, user; `SELECT 1` smoke test; capability probes | `sources.<s>.envs.<env>.*`, `capabilities`, `verified.<s>:<env>`; passwords → `keyring` service `<s>:<env>` |
| `powerbi` | locates `TabularEditor.exe`, `dscmd.exe`, `PBIDesktop.exe`; `az login`; lists workspaces via the Power BI REST API; percent-encodes the XMLA URL; smoke-tests each workspace/model with a one-line Tabular Editor script | `powerbi.tools.*`, `powerbi.workspaces[]`, `powerbi.tenant_id`, `verified.powerbi:xmla:<ws>` |
| `project` | `--project DIR`: copies `templates/project-stub/` into DIR and fills the facts it knows (env names, tool paths, workspace/model/XMLA, first `*.pbip`) | `AGENTS.md`, `.agent/state.json`, `.gitignore` additions (never overwrites existing files) |

Non-interactive: `ad-setup --non-interactive --answers answers.json` (prompt key → answer; an answers file must not
contain passwords — store them once interactively). `ad-setup --offline` skips network verification.

## Config file
`~/.agentdata/config.json` (override the path with `AGENTDATA_CONFIG`). It never contains a credential: `save()`
refuses keys that look like one. Capability probes recorded per source env (used by `ad-sql-check`): Teradata `tmode`
(ANSI vs TERA decides whether `=` is case-sensitive), `trunc_date`, `to_char`, `listagg`; Hive/Impala `version`/`major`.

## Precedence for every setting
CLI flag → environment variable → `~/.agentdata/config.json` → project `AGENTS.md` fact → error with a hint.
Env overrides keep working: `TD_HOST_<ENV>`/`TD_HOST`, `TD_USER`, `TD_LOGMECH`, `HIVE_HOST_<ENV>`, `HIVE_PORT`,
`IMPALA_HOST_<ENV>`, `IMPALA_PORT`, `ORA_DSN_<ENV>`, `ORA_USER`, `ORACLE_CLIENT_LIB`, `TNS_ADMIN`;
Jira: `JIRA_URL`, `JIRA_EMAIL`, `JIRA_TOKEN`; TLS: `AGENTDATA_CA_BUNDLE`.

## Windows notes
- A 64-bit Python sees only 64-bit ODBC drivers/DSNs; configure them in `C:\Windows\System32\odbcad32.exe`.
- Kerberos (`KRB5`/`GSSAPI`) needs a ticket (`klist`); impyla on Windows needs `pip install winkerberos`.
- `az` resolves to `az.cmd`; `ad-setup` offers `az login --allow-no-subscriptions` when not signed in.
- Console encoding: every `ad-*` command switches stdout to UTF-8 (TOON uses `→ · ≤`).
- Power BI XMLA needs Premium/PPU/Fabric capacity with the XMLA endpoint set to Read Write by the capacity admin.
