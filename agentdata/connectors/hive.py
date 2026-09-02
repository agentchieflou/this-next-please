"""Hive via HiveServer2 (impyla GSSAPI/LDAP/PLAIN) or a pyodbc DSN. GSSAPI needs a live TGT (klist)."""
from __future__ import annotations
from . import hs2
from .sql_base import assert_readonly, fetch


def connect(env: str, cfg: dict | None = None, timeout: int | None = None):
    return hs2.connect("hive", env, cfg, timeout)


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = connect(env, timeout=timeout)
    try:
        return fetch(con.cursor(), sql, max_rows, name="hive", source=f"hive:{env}")
    finally:
        con.close()
