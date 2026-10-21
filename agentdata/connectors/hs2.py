"""HiveServer2 (Hive), Impala and the Spark Thrift Server via impyla, or a pyodbc DSN. Credentials resolved at call
time, never printed. GSSAPI needs a live TGT (klist); on Windows install `winkerberos`. The Spark Thrift Server speaks
HiveServer2's protocol, often over HTTP (`transport: http`, port 10001, `http_path: cliservice`)."""
from __future__ import annotations
import getpass
from ..config import ConfigError, source_env
from ..install import install_cmd
from . import odbc, secrets

DEFAULT_PORT = {"hive": 10000, "impala": 21050, "spark": 10000}
# The Kerberos service in the server's principal (`<service>/<host>@REALM`). A Spark Thrift Server is usually started
# with Hive's principal, so `hive` is its default too; `service_name` in the env overrides it.
DEFAULT_SERVICE = {"hive": "hive", "impala": "impala", "spark": "hive"}
DEFAULT_HTTP_PATH = "cliservice"
PASSWORD_AUTH = ("PLAIN", "LDAP")


def connect(source: str, env: str, cfg: dict | None = None, timeout: int | None = None):
    e = source_env(cfg, source, env)
    user = e.get("user") or getpass.getuser()
    auth = str(e.get("auth") or "GSSAPI").upper()
    if e.get("mode") == "odbc":
        pw = secrets.get_password(source, env, user) if auth in PASSWORD_AUTH else None
        if auth in PASSWORD_AUTH and not pw:
            # native mode below refuses the same gap before dialing out; ODBC must too, or the driver connects
            # with neither UID nor PWD and is free to hang or show its own native credential prompt
            raise secrets.missing_password_error(source, env, user) from None
        return odbc.connect(odbc.dsn_conn_str(e["dsn"], user if pw else None, pw), timeout)
    try:
        from impala.dbapi import connect as _connect  # optional dep
    except ImportError:
        raise ConfigError("impyla is not installed",
                          hint=install_cmd("impala") + " (Windows Kerberos: pip install winkerberos)") from None
    kw: dict = {"host": e["host"], "port": int(e.get("port") or DEFAULT_PORT[source]), "auth_mechanism": auth,
                "use_ssl": bool(e.get("ssl", False))}
    if timeout:
        kw["timeout"] = int(timeout)
    if str(e.get("transport") or "binary").lower() == "http":
        kw["use_http_transport"] = True
        kw["http_path"] = e.get("http_path") or DEFAULT_HTTP_PATH
    if auth == "GSSAPI":
        kw["kerberos_service_name"] = e.get("service_name") or DEFAULT_SERVICE[source]
    elif auth in PASSWORD_AUTH:
        pw = secrets.get_password(source, env, user)
        if not pw:
            raise secrets.missing_password_error(source, env, user) from None
        kw.update(user=user, password=pw)
    if e.get("database"):
        kw["database"] = e["database"]
    return _connect(**kw)
