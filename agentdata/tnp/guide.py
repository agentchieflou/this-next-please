"""What `tnp` tells a person before it asks anything: per connection, what it is, what to have in hand, where to find
it, the questions in the order they come, how to prove it works, and what the usual failures mean.

One source of truth for the TUI's screens and for docs/tnp.md (tests/test_tnp.py checks the two agree).
"""
from __future__ import annotations

from ..setup.jdbc import EXAMPLE

# Where every answer goes. Shown on the home screen and the Help page, and said again before each write.
WHERE = [
    ("Machine config", "connections, tool paths, Power BI sign-in and the workspaces this account can reach. "
                       "One file per Windows account; every repository on the machine shares it."),
    ("OS keyring", "passwords and tokens. Never a file, never on screen, never in AGENTS.md."),
    ("A repo's AGENTS.md", "which environment of each source THAT repository reads, and the Power BI semantic "
                           "models and reports it changes. Committed with the repo, so the team sees the same."),
    ("toil's own config", "Jira, Confluence, Bitbucket and GitHub connections. `toil` sets them up; tnp only "
                          "reads them and says which one each ad-* command will use."),
]

SCOPES = {
    "repo": "You are inside a repository. Connections are still machine-wide; this repo's own answers (its "
            "environments, its Power BI targets) go to its AGENTS.md.",
    "folder": "You are in a folder of repositories (like PycharmProjects). This is a machine-wide setup: only the "
              "machine config is written. Pick a repo under 'Repos in this folder' to give it its own settings.",
    "machine": "No repository here. This is a machine-wide setup: only the machine config is written.",
}

# Per source: the walkthrough. `questions` are in the order ad-setup asks them (sources.py ask_env).
SOURCES: dict[str, dict] = {
    "teradata": {
        "command": "ad-td",
        "what": "Teradata Vantage over the teradatasql driver (or an ODBC DSN you already have).",
        "have": ["the host name (the system's DNS name, not an IP if Kerberos is used)",
                 "the logon mechanism: KRB5 on a domain laptop, LDAP or TD2 with a password otherwise"],
        "find": "Teradata Studio / SQL Assistant: the connection's Host field. A JDBC URL looks like "
                + EXAMPLE["teradata"] + ".",
        "questions": ["environment name (prod, uat, ...)", "connection mode: native or odbc",
                      "host (native) or DSN (odbc)", "logon mechanism: KRB5, TDNEGO, LDAP, TD2",
                      "transaction mode ANSI/TERA (blank = the server's)",
                      "user and password, only for LDAP/TD2 (password to the keyring)"],
        "test": 'ad-td --env <env> "SELECT 1"',
        "fails": [("KRB5 'no credentials'", "no Kerberos ticket: sign in to the domain, or run `klist` to see one"),
                  ("timeout", "host unreachable: VPN, or the host is a load balancer name you have not been given"),
                  ("8017 / logon failed", "wrong user or password: `ad-setup --patch sources.teradata.<env>.`")],
    },
    "hive": {
        "command": "ad-hive",
        "what": "Hive through HiveServer2 (impyla), or an ODBC DSN.",
        "have": ["the HiveServer2 host and port (10000 by default)",
                 "the auth: GSSAPI (Kerberos) if the URL has principal=, LDAP if you type a password"],
        "find": "DBeaver / Hue: the connection's JDBC URL, e.g. " + EXAMPLE["hive"] + ". Paste it and tnp "
                "fills host, port and auth.",
        "questions": ["environment name", "connection mode", "host", "port", "auth: GSSAPI, PLAIN, LDAP, NOSASL",
                      "TLS?", "user and password, only for PLAIN/LDAP"],
        "test": 'ad-hive --env <env> "SELECT 1"',
        "fails": [("GSS failure", "no ticket (`klist`), or the host is an alias the principal does not match"),
                  ("TTransportException", "wrong port, or the server wants TLS (answer yes to TLS)")],
    },
    "impala": {
        "command": "ad-impala",
        "what": "Impala daemons (impyla), or an ODBC DSN.",
        "have": ["an impalad or load-balancer host, port 21050", "the auth: GSSAPI or LDAP"],
        "find": "Hue's Impala editor, or the Cloudera driver's URL, e.g. " + EXAMPLE["impala"] + " "
                "(AuthMech=1 is Kerberos, 3 is user and password).",
        "questions": ["environment name", "connection mode", "host", "port", "auth", "TLS?",
                      "user and password, only for PLAIN/LDAP"],
        "test": 'ad-impala --env <env> "SELECT 1"',
        "fails": [("port 21000", "that is impala-shell's port; JDBC/impyla use 21050"),
                  ("GSS failure", "no ticket, or the service is not `impala`")],
    },
    "oracle": {
        "command": "ad-ora",
        "what": "Oracle through python-oracledb: thin with a password, thick (Instant Client) for Kerberos/wallet.",
        "have": ["host, port (1521) and service name -- or a TNS alias and the folder holding tnsnames.ora",
                 "for Kerberos or a wallet: the Instant Client folder"],
        "find": "SQL Developer: the connection's Basic tab (Hostname, Port, Service name). A JDBC URL looks like "
                + EXAMPLE["oracle"] + ".",
        "questions": ["connection name (e.g. OIMPROD1_ROSVC)", "style: basic or tns", "host, port, service or SID",
                      "authentication: password, kerberos, wallet", "TNS_ADMIN folder (optional)",
                      "Instant Client folder (required unless password)", "user and password"],
        "test": 'ad-ora --env <name> "SELECT 1 FROM DUAL"',
        "fails": [("ORA-12514", "listener does not know that service name: check SQL Developer's value"),
                  ("DPY-3015 / thin mode", "that auth needs thick mode: give the Instant Client folder")],
    },
    "spark": {
        "command": "ad-spark",
        "what": "Spark SQL through the Spark Thrift Server, which speaks the HiveServer2 protocol.",
        "have": ["the Thrift Server host", "its transport: binary (port 10000) or http (port 10001, path "
                 "cliservice)", "the auth, and for Kerberos the service in the principal (usually hive)"],
        "find": "the cluster's Spark Thrift JDBC URL, e.g. " + EXAMPLE["spark"] + ". transportMode=http and "
                "httpPath= mean http transport.",
        "questions": ["environment name", "connection mode", "host", "Thrift transport: binary or http", "port",
                      "HTTP path (http only)", "auth", "Kerberos service (GSSAPI only)", "TLS?",
                      "user and password, only for PLAIN/LDAP"],
        "test": 'ad-spark --env <env> "SELECT 1"',
        "fails": [("connection reset on 10001", "that port is http: choose transport http"),
                  ("GSS 'server not found'", "the principal's service is not hive: answer the Kerberos service")],
    },
}

POWER_BI = {
    "machine": ["Tools: Tabular Editor 2 and DAX Studio's dscmd (found or pointed at)",
                "Sign-in: `az login` with the account that can open the workspaces",
                "Workspaces this account can reach, read from Power BI: the catalog every repo picks from"],
    "repo": ["Inside the repo (or `--repo <name>` from the folder): does this repo change Power BI at all?",
             "Which workspaces -- by number from the list, or by name",
             "Per workspace: which semantic models and which reports (several of each is normal)",
             "Ids are looked up for you when signed in; each pick becomes one row of `## Power BI targets` in the "
             "repo's AGENTS.md. The first row is also pbi_workspace / pbi_model / ws_id / ds_id."],
    "why": "Most repos only read Teradata, Hive or Impala. The one or two that change Power BI each change "
           "different models in different workspaces, so that belongs to the repo, not the machine.",
}

SERVICES = {
    "what": "Jira, Confluence, Bitbucket and GitHub go through toil: ad-jira, ad-confluence publish and ad-git pr "
            "run the matching toil command after their own dry-run and approval.",
    "add": "Run `toil` and choose Connections -> Add. toil asks for the host, signs you in and stores the token "
           "itself; tnp never copies a token or a JSON file.",
    "writes": "A write (creating a ticket, publishing a page, opening a PR) needs writes turned on for that "
              "connection in toil (Connections -> the connection -> Writes).",
}

CHEATSHEET = [
    ("tnp", "this menu"),
    ("tnp --repo <name>", "the menu, for one repo in this folder"),
    ("ad-setup", "the full guided setup, top to bottom"),
    ("ad-setup --only sources", "data source connections only"),
    ("ad-setup --repo <name>", "one repo's AGENTS.md: environments and Power BI targets"),
    ("ad-setup --patch", "re-ask only what ad-doctor says is wrong"),
    ("ad-doctor", "offline health check; --online also connects"),
    ("toil", "Jira / Confluence / Bitbucket / GitHub connections"),
]
