# tnp: the this-next-please menu

`tnp` is the one place to set up and run this-next-please. It covers:

- **Setup.** Data source connections, Power BI, each repo's settings, and toil's service connections.
- **A health check.**
- **The fleet desk.**
- **Commands.** Every `ad-*` command and subcommand: browse them, search them, read their arguments and flags, and
  run them.

The setup screens ask the same questions as `ad-setup` and write the same files. Before a flow starts, its first
screen shows the command that asks the same questions (`$ ad-setup --only sources`). When the flow is done, the
command is printed again with every answer you gave filled in (`ad-setup --non-interactive --only sources --set
…`), so anything done here can be scripted or handed to an agent. `ad-setup` and `ad-doctor` are unchanged, and
scripts and agents keep using them.

The layout copies toil's own menu (`toil` with no arguments): a wordmark, one status line, where you are, what
needs attention, then a numbered menu. The wordmark and the breadcrumb stay at the top of every screen. Nothing
is wider than the terminal: long lines end in `…`. Nothing is taller than it either: long lists and pages scroll,
marked `↑ N more` and `↓ N more`. File paths are never cut; they wrap.

```
  ████████  ███    ██  ██████▄
     ██     ████   ██  ██    ██
     ██     ██ ██  ██  ██████▀
     ██     ██  ██ ██  ██
     ██     ██   ████  ██

  this-next-please

  agentdata 0.23.0 · 1 to fix · 1 warning · 1 data connection · toil 4 connections · last tested 2026-10-21

  Scope      repo sales-bi
  Repo       C:/Users/me/PycharmProjects/sales-bi
  Branch     main  from https://bitbucket.corp/scm/bi/sales-bi.git
  Writes     machine config: ~/.agentdata/config.json
  Writes     passwords: the OS keyring (never a file)
  Writes     this repo: C:/Users/me/PycharmProjects/sales-bi/AGENTS.md

  Needs attention
  ✗ spark:prod             impala not installed
  ! power bi target        Finance BI / Sales Overview: no ws_id, report_id yet

  ▸ 1  Test connections      One query against each data source, one read against each toil connection
    2  Data sources          Teradata, Hive, Impala, Oracle, Spark: add, change, test
    3  Power BI              This machine's tools and sign-in; the models and reports each repo changes
    4  This repo             Which environments and Power BI targets sales-bi uses (its AGENTS.md)
    5  Service connections   Jira, Confluence, Bitbucket, GitHub, set up in toil
    6  Commands              Browse, search and run every ad-* command
    7  Fleet desk            Open the agents' desk in the browser, or start one
    8  Health check          Every check ad-doctor runs, with the fix for each
    9  Help                  How tnp works, where each answer is written, keys, the docs
       Quit                  Back to your shell

  up/down move   enter select   1-9 jump   q quit
```

*Needs attention* gives one line per problem; the fix for each is on *Health check*.

## Keys

| Key | What it does |
|---|---|
| up/down, or j/k | Move. |
| Enter | Select, or go on to the next question. |
| 1–9 | Jump to that item. |
| Space | Tick a box in a list where you can pick several. |
| Esc, Backspace or ← | Go back one screen. |
| q | Quit tnp, from any screen. |
| Ctrl-U | Clear a text field. |
| PgUp/PgDn | Scroll a long page. |

Questions are answered on the screen:

- a text field is prefilled with the current answer (`host: tdprod.corp▏`);
- a choice is a pick list;
- yes/no is a two-item list;
- "which of these" is a checkbox list;
- a password is drawn as dots, and goes to the OS keyring.

Every answer so far stays on the screen above the next question. Without a terminal (a pipe, a CI log), each
question falls back to a single numbered line prompt.

The wordmark runs from teal to blue. It uses 24-bit colour in Windows Terminal, VS Code and any terminal that
sets `COLORTERM=truecolor`; other terminals get the nearest 256-colour shade. The selected row is a lighter
blue, about 8:1 on a dark background, and every text colour reaches at least 4.5:1. With `NO_COLOR`, a pipe or
`--color never`, the screen is drawn without colour. `NO_COLOR` wins over `--color always`.

## Where things are written

Setup now says where it is running and writes only where it says.

| Place | What goes there |
|---|---|
| Machine config | Connections, tool paths, Power BI sign-in and the workspaces this account can reach. There is one file per Windows account, and every repository on the machine shares it. |
| OS keyring | Passwords and tokens. They never go in a file, on screen or in AGENTS.md. |
| A repo's AGENTS.md | Which environment of each source that repository reads, plus the Power BI semantic models and reports it changes. The file is committed with the repo, so the whole team sees the same settings. |
| toil's own config | Jira, Confluence, Bitbucket and GitHub connections. You set these up in `toil`; tnp only reads them. |

Where you start `tnp` (or `ad-setup`) decides the **scope**:

- **Inside a repository** (the repo scope). Connections still go in the machine config. This repo's own answers
  go in its `AGENTS.md`: which environment it reads, and its Power BI targets.
- **In a folder of repositories, such as `PycharmProjects`** (the folder scope). This is a machine-wide setup and
  only the machine config is written. The repositories in the folder are listed with what each one uses. Under
  *Repos in this folder* you can give one of them its own settings without changing directory. From a script,
  use `ad-setup --repo <name>` instead.
- **Anywhere else** (the machine scope). This is a machine-wide setup too.

`ad-setup` shows the same scope and the same files in its banner. `ad-setup --non-interactive` adds `scope` and
`writes` to its result.

## Adding a data connection

The walkthrough is the same for every source: *Data sources → pick the source → Add a connection*. Before you
start, the source's screen lists what to have ready and where to find it. The flow then runs in numbered steps:

1. **Name.** For example `prod` or `uat`. Every repo on the machine refers to the connection by this name.
2. **JDBC URL**, if you have one. DBeaver, SQL Developer, Teradata Studio and Hue all show one. tnp reads the host,
   port, transport, HTTP path and Kerberos service out of it, and they become the defaults for the next step.
   Leave it blank to type every answer yourself.
3. **Connection details.** The mode, the host, the auth and so on, one question at a time. A password goes
   straight to the OS keyring.
4. **Test.** tnp runs `SELECT 1` against the new connection. If it fails, tnp shows the driver's own error and what
   the usual errors for that source mean.
5. **This repo** (inside a repo only). tnp offers to write the connection's name as the repo's fact (`env`,
   `hive_env`, `impala_env`, `oracle_env` or `spark_env`) in its AGENTS.md, and shows that file's path first.

The last screen gives the command that repeats it all and the source's own test query:

```
  TNP › Data sources › Teradata › Add a connection › uat

  Step 3 of 5: connection details

  $ ad-setup --only sources   asks the same, for every connection

  ✓ From the URL: host tduat.corp.example, logmech LDAP, tmode ANSI

  connection mode                               native
  host                                          tduat.corp.example
  logon mechanism                               LDAP
  transaction mode ANSI/TERA (blank = serve…    ANSI
  user                                          svc_bi
  password (stored in keyring only): ••••••▏

  type   enter go on   ctrl-u clear   esc back
```

```
  TNP › Data sources › Teradata › Add a connection › uat

  ✓ From the URL: host tduat.corp.example, logmech LDAP, tmode ANSI
  ✓ Saved teradata:uat to the machine config (~/.agentdata/config.json).
  ✓ teradata:uat  answered in 0.38s
  ✓ env: uat written to C:/Users/me/PycharmProjects/sales-bi/AGENTS.md

  Each step above is a plain command: run it yourself any time.
    ad-setup --non-interactive --only sources --set sources.teradata.uat.mode=native --set
      sources.teradata.uat.host=tduat.corp.example --set sources.teradata.uat.logmech=LDAP --set
      sources.teradata.uat.tmode=ANSI --set sources.teradata.uat.user=svc_bi
    ad-td --env uat "SELECT 1"
```

The repeat command leaves the password out: `--set` never carries one.

### Teradata

Connects to Teradata Vantage through the `teradatasql` driver, or through an ODBC DSN you already have.

- **Have ready:** the host name (use the DNS name, not an IP, when Kerberos is used) and the logon mechanism.
  On a domain laptop that is KRB5; otherwise it is LDAP or TD2 with a password.
- **Where to find it:** the *Host* field of your Teradata Studio or SQL Assistant connection. As a JDBC URL:
  `jdbc:teradata://tdprod.corp.example/LOGMECH=KRB5,TMODE=ANSI`.
- **Asks:** the name, the mode (native or odbc), the host or DSN, the logon mechanism and the transaction mode.
  It asks for a user and password only with LDAP or TD2.
- **Test:** `ad-td --env <env> "SELECT 1"`
- **When it fails:**
  - *KRB5 "no credentials"*: there is no Kerberos ticket. Sign in to the domain, and check with `klist`.
  - *timeout*: the host can't be reached. Check the VPN.
  - *8017*: the user or password is wrong. Run `ad-setup --patch`.

### Hive (HiveServer2)

Connects to Hive through HiveServer2 with impyla, or through an ODBC DSN.

- **Have ready:** the HiveServer2 host and port (10000 by default), and the auth. It is GSSAPI if the URL has
  `principal=`, and LDAP if you type a password.
- **Where to find it:** the JDBC URL in DBeaver or Hue, for example
  `jdbc:hive2://hive.corp.example:10000/default;principal=hive/_HOST@CORP.EXAMPLE`.
- **Asks:** the name, the mode, the host, the port, the auth and TLS. It asks for a user and password only with
  PLAIN or LDAP.
- **Test:** `ad-hive --env <env> "SELECT 1"`
- **When it fails:**
  - *GSS failure*: there is no ticket, or the host is an alias that doesn't match the principal.
  - *TTransportException*: the port is wrong, or the server wants TLS.

### Impala

Connects to the Impala daemons with impyla, or through an ODBC DSN.

- **Have ready:** an impalad or load-balancer host, port 21050, and the auth (GSSAPI or LDAP).
- **Where to find it:** Hue's Impala editor, or the Cloudera driver's URL, for example
  `jdbc:impala://impala.corp.example:21050/default;AuthMech=1;KrbServiceName=impala`. In that URL, `AuthMech=1`
  means Kerberos and `3` means a user and password.
- **Asks:** the name, the mode, the host, the port, the auth and TLS.
- **Test:** `ad-impala --env <env> "SELECT 1"`
- **When it fails:**
  - *port 21000*: that is impala-shell's port. JDBC and impyla use 21050.
  - *GSS failure*: there is no ticket.

### Oracle

Connects to Oracle through python-oracledb. Thin mode works with a password. Kerberos and wallets need thick
mode, which uses the Instant Client.

- **Have ready:** the host, the port (1521) and the service name. Alternatively, a TNS alias plus the folder that
  holds `tnsnames.ora`. For Kerberos or a wallet, you also need the Instant Client folder.
- **Where to find it:** the *Basic* tab of your SQL Developer connection. As a JDBC URL:
  `jdbc:oracle:thin:@ora.corp.example:1521/SALESPRD`. URLs of the form `@host:1521:SID`, `@//host/service`, a
  TNS alias, or a `(DESCRIPTION=…)` all work too.
- **Asks:** the connection name, the style (basic or tns), the host, port and service or SID, the
  authentication, `TNS_ADMIN`, the Instant Client folder, and the user and password.
- **Test:** `ad-ora --env <name> "SELECT 1 FROM DUAL"`
- **When it fails:**
  - *ORA-12514*: the listener doesn't know that service name. Check the value in SQL Developer.
  - *DPY-3015*: that auth needs thick mode. Give the Instant Client folder.

### Spark (Thrift Server)

Runs Spark SQL through the Spark Thrift Server, which speaks the HiveServer2 protocol. `ad-spark` uses the same
driver as `ad-hive`.

- **Have ready:**
  - the Thrift Server host;
  - its transport: binary (port 10000), or http (port 10001, path `cliservice`);
  - the auth, and for Kerberos the service named in the principal (usually `hive`).
- **Where to find it:** the cluster's Spark Thrift JDBC URL, for example
  `jdbc:hive2://sparkts.corp.example:10001/default;transportMode=http;httpPath=cliservice;principal=hive/_HOST@CORP.EXAMPLE`.
- **Asks:** the name, the mode, the host, the transport, the port, the HTTP path, the auth, the Kerberos
  service and TLS.
- **Test:** `ad-spark --env <env> "SELECT 1"`
- **When it fails:**
  - *connection reset on 10001*: that port is http. Choose the http transport.
  - *GSS "server not found"*: the principal's service isn't `hive`. Answer the Kerberos service question with
    the right one.

In AGENTS.md, a repo names the Spark environment it reads as `spark_env`. The SQL rules are Hive's; see
`skills/hive-query/references/hive-impala-sql.md`, section *Spark SQL*.

## Power BI for one repo

Most repos only read Teradata, Hive or Impala. The one or two that change Power BI each change different semantic
models and reports, in different workspaces. That's why Power BI setup is split in two:

**Once per machine** (*Power BI → This machine*, or `ad-setup --only powerbi`). This writes the machine config:

- the tools: Tabular Editor 2 and DAX Studio's `dscmd`;
- the sign-in (`az login`, checked with `ad-pbi auth`);
- the workspaces this account can reach.

**Per repo** (*Power BI → this repo's models and reports*, *A repo's models and reports* from a folder, or
`ad-setup --repo <name>`). This writes only that repo's AGENTS.md:

1. Does this repo change Power BI at all? Most answer no, and nothing is written.
2. Which workspaces? Tick them in a checkbox list (Space ticks, Enter goes on). When you're signed in, the list is
   read live from Power BI. For a workspace that isn't listed, choose *Another, not listed…* and type its name.
3. For each workspace: tick its semantic models, then its reports. Picking several of each is normal.
4. When you're signed in, tnp looks up the ids: the workspace id, each model's dataset id, and each report's id.
   A report's model comes from the report itself.

A repo with no AGENTS.md yet is offered *Set the repo up* first, which creates it from the project stub.

From a script, `ad-setup --repo <name>` asks the same questions with numbers or names, comma-separated
(`--set "repo.pbi.workspaces=Finance BI, Ops"`).

Each pick becomes one row of a table in the repo's AGENTS.md:

```markdown
## Power BI targets
One row per semantic model or report this repository changes. `ad-setup` in this repository (or `tnp` ->
Power BI) writes it; the first row is also the single `pbi_*` facts above.

| workspace | ws_id | model | ds_id | report | report_id |
|---|---|---|---|---|---|
| Finance BI | 6f1c… | Sales | 2a7e… | Sales Overview | 91b0… |
| Finance BI | 6f1c… | Margin | 77d3… | - | - |
| Ops | c41a… | Ops Model | 5e02… | - | - |
```

The first row is also copied into the single facts (`pbi_workspace`, `ws_id`, `pbi_model`, `ds_id`,
`pbi_xmla`), so every skill that reads those keeps working. A row without its ids shows up as a warning in
`ad-doctor`. To fill them in, sign in and run the same screen again.

## Service connections (toil)

`ad-jira`, `ad-confluence publish` and `ad-git pr` work through toil. Each one does its own dry run and asks for
approval first, then runs the matching toil command. *Service connections* lists toil's connections: name, area,
host, whether writes are on, and which one is the default. *Open toil* hands the terminal to `toil`, where you
add a connection, sign in again or turn writes on. toil stores the token itself; tnp never copies a token or a
JSON file. A write needs writes turned on for that connection in toil.

## Running any ad-* command

*Commands* lists every `ad-*` command and subcommand, about 250 in all. The list is read from the commands
themselves, so a new flag or subcommand appears here the day it ships.

- **Find a command** searches names and descriptions. `pr` finds `ad-git pr` first; `refresh` finds `ad-pbi
  refresh`, `ad-pbip model refresh` and `ad-fleet refresh`.
- **A command's page** shows what it does, its usage, its arguments and its flags, with the required ones marked.
- **Run it** asks for each argument and each required flag in a field (or a pick list, when there's a fixed
  set of values). The remaining flags go in one line. The command line appears first, starting with `$ ad-…`,
  and then the command runs in your own terminal, so its own dry run and approval prompt work exactly as
  they do in a shell.

```
  TNP › Commands › ad-pbi › refresh

  refresh model on service and poll status

  $ ad-pbi refresh [-h] --workspace WORKSPACE --model MODEL [--scope SCOPE] [--wait WAIT] [--history]

  Flags
    --workspace, -w <workspace>  workspace name or ID                                       required
    --model, -m <model>          model name                                                 required
    --scope <scope>              refresh scope: full | table:<T> | partition:<T>/<P>
    --wait <wait>                wait timeout in seconds (default: 1800; 0 to skip waiting)

  ▸ 1  Run it   Asks for its arguments, then flags

  enter run it   esc back   q quit
```

## The fleet desk

*Fleet desk* says whether the desk is running. *Open the desk* runs `ad-fleet open`, which opens the desk in
your browser and starts it first if needed. *Quickstart this folder* runs `ad-fleet quickstart` on the folder
that holds your repos. *Every fleet command* opens `ad-fleet` in Commands.

## Health check

*Health check* starts with this machine:

- agentdata's version and commit;
- which Python runs it;
- the config file, and whether it exists yet;
- the keyring backend;
- toil's version and path;
- the scope.

Then come every check `ad-doctor` runs, problems first, each with its fix. When something is wrong, *Repair*
runs `ad-setup --patch`, which asks again only the settings behind those rows.

## Commands

| Command | What it does |
|---|---|
| `tnp` | Opens this menu. |
| `tnp --repo <name>` | Opens the menu for one repo in this folder. |
| `python -m agentdata.tnp` | The same as `tnp`, when the console script isn't on PATH. |
| `ad-setup` | Runs the full guided setup, top to bottom. |
| `ad-setup --only sources` | Sets up data source connections only. |
| `ad-setup --repo <name>` | Sets up one repo's AGENTS.md: its environments and Power BI targets. |
| `ad-setup --patch` | Asks again only about what ad-doctor says is wrong. |
| `ad-doctor` | Runs the offline health check; add `--online` to connect too. |
| `toil` | Sets up Jira, Confluence, Bitbucket and GitHub connections. |

Tab completion covers `tnp` as well as the `ad-*` commands (`ad-setup --print-completion bash --install`).

`tnp --print` prints the home screen once and exits, which is handy in a bug report.
