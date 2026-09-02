"""Teradata via teradatasql (KRB5 / TDNEGO / TD2 / LDAP) or a pyodbc DSN. Credentials resolved here, never printed.
Connection settings come from ~/.agentdata/config.json (ad-setup) or TD_HOST_<ENV> / TD_HOST env vars."""
from __future__ import annotations
import getpass
from ..config import ConfigError, source_env
from ..install import install_cmd
from . import odbc, secrets
from .sql_base import assert_readonly, fetch

PASSWORD_LOGMECH = ("LDAP", "TD2")


def connect(env: str, cfg: dict | None = None, timeout: int | None = None):
    e = source_env(cfg, "teradata", env)
    user = e.get("user") or getpass.getuser()
    logmech = str(e.get("logmech") or "").upper()
    if e.get("mode") == "odbc":
        pw = secrets.get_password("teradata", env, user) if logmech in PASSWORD_LOGMECH else None
        return odbc.connect(odbc.dsn_conn_str(e["dsn"], user if pw else None, pw), timeout)
    try:
        import teradatasql  # optional dep
    except ImportError:
        raise ConfigError("teradatasql is not installed", hint=install_cmd("teradata")) from None
    kw: dict = {"host": e["host"]}
    if e.get("port"):
        kw["dbs_port"] = str(e["port"])
    if e.get("tmode"):
        kw["tmode"] = str(e["tmode"])
    if e.get("database"):
        kw["database"] = e["database"]
    if logmech in PASSWORD_LOGMECH:
        pw = secrets.get_password("teradata", env, user)
        if not pw:
            raise ConfigError(f"no password in keyring for teradata:{env} user {user}", hint="ad-setup --only sources")
        return teradatasql.connect(**kw, user=user, password=pw, logmech=logmech)
    if logmech:
        return teradatasql.connect(**kw, logmech=logmech)
    try:  # unconfigured: Kerberos first, LDAP via keyring as fallback
        return teradatasql.connect(**kw, logmech="KRB5")
    except Exception:
        pw = secrets.get_password("teradata", env, user) if secrets.has_password("teradata", env, user) else None
        if not pw:
            raise
        return teradatasql.connect(**kw, user=user, password=pw, logmech="LDAP")


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    """`timeout` bounds the connection only; teradatasql exposes no statement timeout."""
    assert_readonly(sql)
    con = connect(env, timeout=timeout)
    try:
        cur = con.cursor()
        return fetch(cur, sql, max_rows, name="td", source=f"teradata:{env}")
    finally:
        con.close()
