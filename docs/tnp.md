# tnp: setting up this-next-please

`tnp` opens a menu for setting up this-next-please. It asks the same questions as `ad-setup` and runs the same
checks as `ad-doctor`, one screen at a time. Before it writes anything, each screen tells you where the answers
will go. Each screen also ends with the plain command that does the same thing, so you can script it later or
hand it to an agent. `ad-setup` and `ad-doctor` do not change: scripts and agents keep using them.

The layout copies toil's own menu (`toil` with no arguments): a wordmark, one status line, where you are, what
needs attention, then a numbered menu. Move with up/down and press Enter, or press the item's number. `q` goes
back one screen, and quits from home.

```
  ████████  ███    ██  ██████▄
     ██     ████   ██  ██    ██
     ██     ██ ██  ██  ██████▀
     ██     ██  ██ ██  ██
     ██     ██   ████  ██

  this-next-please

  agentdata 0.23.0 · 1 data connection · toil 4 connections · 1 to fix · 2 warnings

  Scope      repo sales-bi
  Repo       C:/Users/me/PycharmProjects/sales-bi
  Branch     main  from https://bitbucket.corp/scm/bi/sales-bi.git
  Writes     machine config: ~/.agentdata/config.json
  Writes     passwords: the OS keyring (never a file)
  Writes     this repo: C:/Users/me/PycharmProjects/sales-bi/AGENTS.md

  Needs attention
  ! power bi target        Finance BI / Sales Overview: no ws_id, report_id yet
      fix: sign in (`ad-pbi auth`), then `tnp` -> Power BI, or `ad-setup --patch repo`: the ids are looked up

  ▸ 1  Test connections      One query against each data source, one read against each toil connection
    2  Data sources          Teradata, Hive, Impala, Oracle, Spark: add, change, test
    3  Power BI              This machine's tools and sign-in; the models and reports each repo changes
    4  This repo             Which environments and Power BI targets sales-bi uses (its AGENTS.md)
    5  Service connections   Jira, Confluence, Bitbucket, GitHub, set up in toil
    6  Health check          Every check ad-doctor runs, with the fix for each
    7  Help                  How tnp works, where each answer is written, a command cheatsheet
    8  Quit                  Back to your shell

  up/down move   enter select   1-8 jump   q quit
```

The wordmark runs from teal to blue. It uses 24-bit colour in Windows Terminal, VS Code and any terminal that
sets `COLORTERM=truecolor`. Other terminals get the nearest 256-colour shade. With `NO_COLOR`, a pipe or
`--color never`, it is drawn in plain blocks.

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

The walkthrough is the same for every source: *Data sources → pick the source → Add a connection*.

1. The screen lists what to have ready and where to find it, then the questions in the order they will be asked.
2. Name the connection, for example `prod` or `uat`. Every repo on the machine refers to it by this name.
3. **Paste a JDBC URL**, if you have one. DBeaver, SQL Developer, Teradata Studio and Hue all show one. tnp reads
   the host, port, transport, HTTP path and Kerberos service out of it and uses them as the defaults for the
   questions that follow. You can keep each one or change it. Leave the URL blank to type every answer yourself.
4. Answer the questions. Enter keeps the answer shown in `[brackets]`. A password goes straight to the OS keyring.
5. **Test it.** tnp runs `SELECT 1` against the new connection. If the test fails, tnp prints the driver's own error
   along with what the common errors for that source mean.
6. **Inside a repo, say whether this repo reads it.** tnp offers to write the connection's name as the repo's fact
   (`env`, `hive_env`, `impala_env`, `oracle_env` or `spark_env`) in its AGENTS.md. Before it writes, it shows
   that file's path.

The screen ends with the commands that do the same: `ad-setup --only sources` for every question, and the
source's own test query.

```
  TNP › Data sources › Spark (Thrift Server) › Add a connection

  You will be asked, in this order:
    1. environment name
    2. connection mode
    3. host
    4. Thrift transport: binary or http
    ...
Name for this Spark (Thrift Server) connection (prod, uat, ...) [prod]: prod
Paste a JDBC URL to fill in the answers (blank = type them yourself): jdbc:hive2://sparkts.corp.example:10001/default;transportMode=http;httpPath=cliservice;principal=hive/_HOST@CORP.EXAMPLE
  ✓ From the URL: host sparkts.corp.example, port 10001, transport http, http_path cliservice, auth GSSAPI,
  service_name hive. They are the defaults below.
[spark:prod] connection mode (native/odbc) [native]:
[spark:prod] host [sparkts.corp.example]:
[spark:prod] Thrift transport (binary/http) [http]:
[spark:prod] port [10001]:
[spark:prod] HTTP path [cliservice]:
[spark:prod] auth mechanism (GSSAPI/PLAIN/LDAP/NOSASL) [GSSAPI]:
[spark:prod] Kerberos service in the server's principal (<service>/host@REALM) [hive]:
[spark:prod] TLS? [y/N]:

  ✓ Saved spark:prod to the machine config (~/.agentdata/config.json).
Test spark:prod now (SELECT 1)? [Y/n]:
  ✓ spark:prod  answered in 0.41s
Make prod the Spark (Thrift Server) environment sales-bi reads (spark_env in .../sales-bi/AGENTS.md)? [Y/n]:
  ✓ spark_env: prod written to C:/Users/me/PycharmProjects/sales-bi/AGENTS.md

  Each step above is a plain command; run it yourself any time:
    ad-setup --only sources          # every Spark (Thrift Server) question, for all connections
    ad-spark --env prod "SELECT 1"
```

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
2. Which workspaces? Answer with numbers from the list or with names. When you're signed in, the list is read
   live from Power BI.
3. For each workspace: which semantic models, and which reports. Picking several of each is normal.
4. When you're signed in, tnp looks up the ids: the workspace id, each model's dataset id, and each report's id.
   A report's model comes from the report itself.

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

## Commands

| Command | What it does |
|---|---|
| `tnp` | Opens this menu. |
| `tnp --repo <name>` | Opens the menu for one repo in this folder. |
| `ad-setup` | Runs the full guided setup, top to bottom. |
| `ad-setup --only sources` | Sets up data source connections only. |
| `ad-setup --repo <name>` | Sets up one repo's AGENTS.md: its environments and Power BI targets. |
| `ad-setup --patch` | Asks again only about what ad-doctor says is wrong. |
| `ad-doctor` | Runs the offline health check; add `--online` to connect too. |
| `toil` | Sets up Jira, Confluence, Bitbucket and GitHub connections. |

`tnp --print` prints the home screen once and exits, which is handy in a bug report.
