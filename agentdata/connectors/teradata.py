"""Teradata via teradatasql. Credentials resolved here, never printed. KRB5 first, LDAP via keyring fallback."""
from __future__ import annotations
from .sql_base import assert_readonly, fetch


def _connect(env: str):
    import teradatasql  # optional dep
    # TODO(data_czars): replace with data_czars.connections.teradata(env) which returns host/user/logmech
    # and, for LDAP, pulls the secret from keyring inside this process.
    import os
    host = os.environ.get(f"TD_HOST_{env.upper()}") or os.environ.get("TD_HOST")
    if not host:
        raise RuntimeError(f"no host for env {env}; set TD_HOST or wire data_czars")
    try:
        return teradatasql.connect(host=host, logmech="KRB5")
    except Exception:
        import keyring, getpass
        user = os.environ.get("TD_USER") or getpass.getuser()
        pw = keyring.get_password(f"teradata:{env}", user)
        if not pw:
            raise
        return teradatasql.connect(host=host, user=user, password=pw, logmech="LDAP")


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = _connect(env)
    try:
        cur = con.cursor()
        return fetch(cur, sql, max_rows, name="td", source=f"teradata:{env}")
    finally:
        con.close()
