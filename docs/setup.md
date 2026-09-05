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
| `content_understanding` | optional, and `skip` until a project says it uses it: the Microsoft Foundry resource endpoint (shape-checked offline -- a pasted portal key and an endpoint with the API path already on it are the two mistakes it catches), auth mode, and a default analyzer. Online, `get_analyzer` proves endpoint + credential + permission + analyzer id in one call and sends no document anywhere | `content_understanding.endpoint/auth/analyzer`, `verified.content_understanding:<analyzer>`; the resource key -> `keyring` service `content_understanding:default` |
| `project` | `--project DIR`: writes the packaged project stub into DIR and fills the facts it knows (env names, tool paths, workspace/model/XMLA, first `*.pbip`) | `AGENTS.md`, `.agent/state.json`, `.gitignore` additions (never overwrites existing files) |

Non-interactive (Copilot terminals have no stdin for prompts):
`ad-setup --only project --non-interactive --offline --project . --set project.jira_project=RDSD`. `--set key=value`
answers one prompt key inline (repeatable; `true`/`false` for yes-no prompts; wins over `--answers`). `--answers
answers.json` still works, and is read in any encoding another tool produced; answers must never
contain passwords — store them once interactively. `ad-setup --offline` skips network verification.

Quick mode: **`ad-setup --quick`** accepts unambiguous detected defaults (e.g. a single ODBC DSN found for a source,
tools located at known paths, a single workspace returned by Azure CLI) without prompting stdin. Each auto-accepted value
is printed to stderr (`[quick] auto-accepted ...`). Anything genuinely ambiguous (multiple ODBC DSNs, multiple workspaces)
and anything needing credentials (passwords always prompt, `getpass`, never auto-filled) still prompts interactively. The
final check report notes how many settings were auto-accepted (`auto_accepted: N`).

Parallel verification: Online network verification across multiple sources, environments, and Power BI workspaces runs
concurrently via bounded worker threads. This substantially reduces wall-clock time for setups with multiple environments,
while ensuring all verdicts, timestamps, and capabilities are recorded in clean, deterministic order.

Repair mode: **`ad-setup --patch`** runs the checks first and then re-asks ONLY the settings behind the rows that
fail. A missing Oracle service name is one question; a wrong ODBC DSN is one question. Every other answer silently
keeps its stored value, and steps with no failing rows are never entered.

- A row that **no answer can fix** — a missing package, an ODBC DSN that does not exist, no Kerberos ticket — carries
  no prompt keys, so `--patch` lists it under `manual` with its hint instead of asking pointless questions. That is
  the difference between "run `pip install …`" and a wizard walking you through settings that were already correct.
- **Name a target to skip the scan**: `ad-setup --patch sources.oracle` re-asks that area on demand,
  `ad-setup --patch sources.oracle.OIMPROD1_ROSVC.host` re-asks exactly one field. Targets start with a step key.
- `--include-warnings` covers `warn` rows; `--only <step>` narrows the scan; `--set key=value` / `--answers` make it
  non-interactive. Without a terminal (a piped run) it does not die on the first prompt: it prints `needs_answers[]`
  and the `--set` line that would answer them.
- The scan runs the online checks too unless `--offline`, so a failing `SELECT 1` is repairable.

## Sharing setup across a team (`--export-defaults` and `--import`)

Everything stored in `~/.agentdata/config.json` is non-secret by design (`save()` rejects credential-shaped keys;
passwords go to `keyring` and tokens stay in pncli). That makes the configuration safe to share across a team so new
hires don't re-type hostnames, ports, and workspace names from scratch:

1. **Export defaults**:
   ```bash
   ad-setup --export-defaults team-defaults.json
   ```
   Writes current non-secret settings without laptop-specific `verified` stamps.

2. **Import defaults**:
   ```bash
   ad-setup --import team-defaults.json
   ```
   Loads the file as starting defaults for the wizard. It **never overwrites** a setting the target machine already
   configured differently. Can be combined with `--quick` (`ad-setup --import team-defaults.json --quick`) to accept
   all team defaults and only prompt for personal credentials and passwords. Can also be layered with `--patch`
   for existing installs adopting newly published team defaults.

Session state: `ad-state show` / `ad-state set phase=<phase> active_ticket=<KEY> --artifact <path>=<what> --question "…"`
is the only writer of `.agent/state.json` (validated keys and phases, `last_updated`, artifacts pruned after 7 days,
UTF-8 without BOM).

Jira transitions: `ad-jira transitions <KEY>` lists what that one issue can move to; `ad-jira transition <KEY> --to
<intent|name>` runs it. A workflow belongs to the **issue type**, so a Story's `In Review` may not exist on a Task —
the intents `todo`, `in-progress`, `review`, `blocked`, `done` resolve against the transitions Jira offers, and an
intent the workflow cannot satisfy is refused with the list of what it can do. `--dry-run` resolves without moving,
`--resolution` / `--field NAME=VALUE` answer a transition screen, and `--pin` stores the resolved status under
`jira.workflow.<type>.<intent>` so the next issue of that type resolves exactly.

Confluence pages: `ad-confluence html <file.md>` converts a Markdown file to storage format (Confluence renders
Markdown as literal text) and refuses a body it cannot parse as XML, which is what Confluence would reject. Publish
the result with `ad-pncli raw --body-file <file.html> confluence create-page …`; that command refuses a body that is
still Markdown.

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
Content Understanding: `CONTENT_UNDERSTANDING_ENDPOINT`, `CONTENT_UNDERSTANDING_ANALYZER`, `CONTENT_UNDERSTANDING_KEY`.

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
directory holding `tnsnames.ora`.

**Authentication is a separate question from thick mode.** `auth` is `password`, `kerberos` or `wallet`;
`client_lib` (the Instant Client lib dir) turns on thick mode. They are independent: thick mode is also how you reach
an older server or use a wallet, and it still takes a username and password. Only `kerberos` and `wallet` skip the
credential prompts — and both require `client_lib`, which the doctor now checks by name. A config written before this
question existed (a `client_lib` and nothing else) still means Kerberos. Every `ad-doctor` run prints the composed target next to the env, so a wrong port or
service name is visible without connecting. A host with no service name or SID fails the check by name rather than at
query time. Oracle never uses the ODBC mode: an ODBC DSN handed to python-oracledb would be read as a TNS alias.

## Content Understanding (Microsoft Foundry): an optional service, and why it stays `skip`

`ad-dpm extract-fields --engine azure-content-understanding` and `ad-foundry` talk to Azure AI Content Understanding.
Most installs never call it, so the step reports one `skip` row until a project says otherwise, and the SDK is an
optional extra:

```
pip install "agentdata[content-understanding]"
```

An unconfigured optional service is not a broken install. A `fail` row for it would push the rows that matter off the
reader's screen, which is the same reason `console` never fails the doctor.

**The endpoint is the resource host and nothing else** — `https://<resource>.services.ai.azure.com`. The SDK appends
its own path, so an endpoint carrying `/contentunderstanding` produces a 404 that reads like a missing analyzer. The
check is offline and shape-only; the mistake it catches most often is a portal **key** pasted where the endpoint goes,
which otherwise fails as an authentication error rather than a URL error.

**Auth is `entra` by default and stores nothing** — `DefaultAzureCredential` over the same `az login` the Power BI step
already needs, so an operator who can reach a workspace can reach this with nothing new to rotate. `key` puts the
resource key in the keyring under `content_understanding:default` (user `resource-key`), the same place and shape as a
data source's password; `CONTENT_UNDERSTANDING_KEY` overrides it for one session. The key never goes in config —
`save()` refuses it.

**A default analyzer is optional on purpose.** A default that is wrong for half the jobs is worse than none, so
`--analyzer <id>` per run is a supported answer and the row stays `warn` rather than `fail`. `ad-foundry analyzers
list` shows what the resource has; `ad-foundry analyzers get <id>` shows the field schema it declares, which is the
list your job schema has to agree with. Analyzers are authored in the Foundry portal — nothing here creates one.

## Windows notes
- Console scripts land in the per-user Scripts folder when site-packages is not writeable; if `ad-*` is "not recognized", use `python -m agentdata <command>` (identical arguments) or add that folder to PATH.
- **npm-installed tools have no `.exe`.** pncli is an npm package (`npm install -g @kolatts/pncli`), so it lands as `pncli.cmd`; `az` is `C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd`. Windows `CreateProcess` only appends `.exe`, which is why launching the bare name returns `[WinError 2] The system cannot find the file specified`. `agentdata/proc.py` resolves PATHEXT, the npm global prefix (`%APPDATA%\npm`) and each tool's install dir (the Azure CLI `wbin`), then runs an npm shim's Node entry point directly so an argument like `updated >= '2026-01-01'` is never re-parsed by cmd.exe. `ad-pncli where` prints what resolved; `ad-setup --patch` pins a path in `pncli.exe` / `powerbi.tools.az_exe`; `PNCLI_EXE` overrides.
- **A `.cmd` that is not an npm shim** (az) is run as `cmd.exe /d /s /c "<quoted line>"` passed to Windows **as one string**. Handing that line to `subprocess` as a list would put it through `list2cmdline`, which backslash-escapes the inner quotes; cmd.exe then reads `\"\"C:\Program` as a filename and answers *"The filename, directory name, or volume label syntax is incorrect"*.
- A 64-bit Python sees only 64-bit ODBC drivers/DSNs; configure them in `C:\Windows\System32\odbcad32.exe`.
- Kerberos (`KRB5`/`GSSAPI`) needs a ticket (`klist`); impyla on Windows needs `pip install winkerberos`.
- `az` resolves to `az.cmd`; `ad-setup` offers `az login --allow-no-subscriptions` when not signed in.
- **PowerShell 7 (`pwsh`) is the floor.** Windows PowerShell 5.1 is not supported: it is not tested, and
  `ad-doctor` prints a `console/shell` warn row telling a 5.1 session to install pwsh
  (`winget install Microsoft.PowerShell`) or use Git Bash. Nothing here carries a 5.1 workaround any more.
- Colour: on when a human is looking, off when a machine is. `ad-*` output is coloured for a terminal — VT
  sequences are enabled through the console API, so no `colorama` and nothing to install — plus
  PyCharm's run window and the VS Code terminal, which render ANSI without being TTYs. When stdout is piped — Luna's
  terminal, a script, a log — colour is off and the TOON is byte-identical to before, so no escape ever reaches an
  agent's context. Override with `--color always|never`, `AGENTDATA_COLOR=always|never`, or the conventional
  `NO_COLOR` / `FORCE_COLOR`. Status words are green/yellow/red, prompts cyan, defaults and hints dim.
- Console encoding: every `ad-*` command switches stdout to UTF-8 (TOON uses `→ · ≤`).
- File encoding: **pwsh 7 writes UTF-8 without a BOM** through `>`, `Out-File` and `Set-Content`, so the old `[IO.File]::WriteAllText` workaround is gone — CI asserts it on every run (see below). The 5.1 hazards it existed for (a BOM from `-Encoding utf8`, UTF-16 from `>`) belong to a shell this project no longer supports. Every `ad-*` reader still sniffs a BOM and accepts UTF-16 on **read** (`agentdata/textio.py`) — files arrive from Notepad, from older scripts and from other teams, which is not a shell concern. For state, always use `ad-state set`: it is the only sanctioned writer.
- Power BI XMLA needs Premium/PPU/Fabric capacity with the XMLA endpoint set to Read Write by the capacity admin.

### Colour and glyphs, per host

`ad-doctor` prints `console/host` and `console/shell` so a pasted report says where it ran.

| Host | Detected by | Colour | Glyphs | Secret prompt |
|---|---|---|---|---|
| Windows Terminal | `WT_SESSION` | on | `✓ ✗` (UTF-8) | console, no echo |
| PyCharm terminal tab | `TERMINAL_EMULATOR=JetBrains-JediTerm` | on | `✓ ✗` | console, no echo |
| PyCharm run window | `PYCHARM_HOSTED=1` | on (not a TTY, renders ANSI) | `✓ ✗` | not interactive |
| VS Code terminal | `TERM_PROGRAM=vscode` | on (not a TTY) | `✓ ✗` | console, no echo |
| conpty / conhost (pwsh 7) | a console handle answers `GetConsoleMode` | on (VT enabled through the console API) | ASCII under code page 437/1252 | console, no echo |
| standalone mintty (Git Bash) | `MSYSTEM` **and** an MSYS pty handle | on | `✓ ✗` | see below |
| piped / redirected | none of the above | **off** | n/a | n/a |

Two details that took a while to get right:

- **mintty is not a Windows console.** Python's stdio are pipes, `isatty()` is `False`, and asking
  the console API to enable VT has nothing to enable — which is why colour used to switch itself off
  in a window that renders ANSI perfectly well. It is now detected by the *handle name* (an MSYS pty
  is a named pipe containing `msys-…-pty`), not by `MSYSTEM and not isatty` — because `> file` in
  the same shell looks identical, and would otherwise collect escape sequences.
- **Echo cannot be turned off from inside a mintty session.** mintty's pty does the echoing, and
  Windows Python reaches neither a console handle nor `/dev/tty`. `ad-setup`'s password prompt uses
  the Windows console (`msvcrt`) or a real controlling terminal (`termios`) where either exists; in
  a standalone mintty window it prints one line naming the fix — run from Windows Terminal or
  PyCharm, or prefix the command with `winpty`, which ships with Git for Windows — instead of
  `getpass`'s vague *"Password input may be echoed"* followed by echoing it.

**Code page.** Under 437/1252 the status glyphs cannot be encoded, so `ui.glyphs()` returns
`+ ! x -` and rich draws ASCII boxes. The *file* contract is unaffected: piped and redirected output
is UTF-8 on every host. To get the box drawing in a conhost pwsh window, put
`[Console]::OutputEncoding = [Text.Encoding]::UTF8` in your `$PROFILE`, or use Windows Terminal.

**Colour precedence**, highest first: `NO_COLOR` (any value) → `AGENTDATA_COLOR=never` → `--color`
→ `AGENTDATA_COLOR=always` / `FORCE_COLOR` → `TERM=dumb` → the host table above. Piped output is
byte-identical to `AGENTDATA_COLOR=never`, so no escape ever reaches an agent's context or a log.


### What CI proves per shell

The laptop runbook (`docs/windows-verification.md`) only needs to cover what CI cannot. CI runs
`windows-latest` on Python 3.12 (the floor) and 3.14 (the laptop), and each of these is its own step, so
a red job names the shell:

| Step | Shell | What it proves |
|---|---|---|
| `smoke · pwsh 7` | pwsh 7 | `ad-update --check` exits 0; `ad-doctor` exits 0 or 1 and never anything else; its stdout is TOON and every `fail` row carries a `hint`; every `ad-*` from the installed distribution answers `--version`; the PowerShell completion script registers; piped stdout has no ANSI and equals `AGENTDATA_COLOR=never`; `>` and `Out-File` produce UTF-8 with no BOM |
| `smoke · Git Bash` | bash | the same contract, plus `ad-setup --print-completion bash \| bash -n` |
| `smoke · cmd` | cmd.exe | console scripts and the module form work, and redirected stdout is still TOON |
| `encoding · code page 437` | cmd | `ui.glyphs()` falls back to ASCII rather than printing `?` |
| `encoding · code page 65001` | cmd | `→ · ≤` survive |
| `floor · PowerShell 5.1 is refused` | powershell 5.1 | `smoke.ps1`'s `#Requires -Version 7.0` refuses to run, **and** `ad-doctor` prints the "PowerShell 7 required" row. This is the only 5.1 step in the workflow and exists to prove the refusal, not to support the shell |
| `floor · pip refuses the wheel on 3.11` | bash | the built wheel declares `Requires-Python: >=3.12`, and pip on 3.11 refuses it with *"requires a different Python"* — the message the user actually sees |
| `lint · shellcheck + PSScriptAnalyzer` | both | `smoke.sh` passes `shellcheck --shell=bash` (the bash 4.4 floor), `smoke.ps1` passes PSScriptAnalyzer with `PSUseCompatibleSyntax` targeting 7.x |

The smoke scripts live in `.github/scripts/` and are the same files a person can run on the laptop.


## What a person sees, and what Luna sees

`ad-setup`, `ad-doctor`, `ad-update` and `python -m agentdata` render a panel and a table on a terminal, and the
same TOON they always did when stdout is piped or captured. The switch is `AGENTDATA_UI`:

| value | operator commands | query results |
|---|---|---|
| `auto` (default) | drawn on a terminal, TOON when piped | TOON always |
| `rich` | drawn | drawn |
| `plain` | TOON | TOON |

Query results and data commands are deliberately not drawn under `auto`: nothing can tell Luna's shell from a person's, and a table
in box characters is not TOON. Ask for one when you want to read it — `--pretty` on `ad-td` / `ad-ora` / `ad-hive`
/ `ad-impala` / `ad-view` / `ad-jira` / `ad-pbip` / `ad-uat` / `ad-dpm` / `ad-confluence` / `ad-state`, or `AGENTDATA_UI=rich`. Use `AGENTDATA_UI=plain` to paste a report into a ticket, and
`AGENTDATA_WIDTH=100` to pin the width for a screenshot. `NO_COLOR`, `FORCE_COLOR` and `AGENTDATA_COLOR` still
control colour on its own.

The rendering needs `rich` (a dependency since 0.5.0). Without it every command prints exactly what it printed
before, so an older install is not broken — it is just plainer.
