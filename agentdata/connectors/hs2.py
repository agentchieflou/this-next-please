"""HiveServer2 (Hive) and Impala via impyla, or a pyodbc DSN. Credentials resolved at call time, never printed.
GSSAPI needs a live TGT (klist); on Windows install `winkerberos`."""
from __future__ import annotations
import getpass
from ..config import ConfigError, source_env
from . import odbc, secrets

DEFAULT_PORT = {"hive": 10000, "impala": 21050}
DEFAULT_SERVICE = {"hive": "hive", "impala": "impala"}
PASSWORD_AUTH = ("PLAIN", "LDAP")


def connect(source: str, env: str, cfg: dict | None = None, timeout: int | None = None):
    e = source_env(cfg, source, env)
    user = e.get("user") or getpass.getuser()
    auth = str(e.get("auth") or "GSSAPI").upper()
    if e.get("mode") == "odbc":
        pw = secrets.get_password(source, env, user) if auth in PASSWORD_AUTH else None
        return odbc.connect(odbc.dsn_conn_str(e["dsn"], user if pw else None, pw), timeout)
    try:
        from impala.dbapi import connect as _connect  # optional dep
    except ImportError:
        raise ConfigError("impyla is not installed",
                          hint='pip install -e ".[impala]" (Windows Kerberos: pip install winkerberos)') from None
    kw: dict = {"host": e["host"], "port": int(e.get("port") or DEFAULT_PORT[source]), "auth_mechanism": auth,
                "use_ssl": bool(e.get("ssl", False))}
    if timeout:
        kw["timeout"] = int(timeout)
    if auth == "GSSAPI":
        kw["kerberos_service_name"] = e.get("service_name") or DEFAULT_SERVICE[source]
    elif auth in PASSWORD_AUTH:
        pw = secrets.get_password(source, env, user)
        if not pw:
            raise ConfigError(f"no password in keyring for {source}:{env} user {user}", hint="ad-setup --only sources")
        kw.update(user=user, password=pw)
    if e.get("database"):
        kw["database"] = e["database"]
    return _connect(**kw)
