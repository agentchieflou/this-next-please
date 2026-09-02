"""Impala (port 21050) via impyla GSSAPI/LDAP or a pyodbc DSN. Remember: `||` is logical OR in Impala."""
from __future__ import annotations
from . import hs2
from .sql_base import assert_readonly, fetch


def connect(env: str, cfg: dict | None = None, timeout: int | None = None):
    return hs2.connect("impala", env, cfg, timeout)


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = connect(env, timeout=timeout)
    try:
        return fetch(con.cursor(), sql, max_rows, name="impala", source=f"impala:{env}")
    finally:
        con.close()
