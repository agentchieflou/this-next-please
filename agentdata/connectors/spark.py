"""Spark SQL via the Spark Thrift Server (HiveServer2 protocol, impyla GSSAPI/LDAP/PLAIN, binary or HTTP transport) or
a pyodbc DSN (the Simba Spark ODBC driver). Read-only, like every query adapter: GSSAPI needs a live TGT (klist)."""
from __future__ import annotations
from . import hs2
from .sql_base import assert_readonly, fetch


def connect(env: str, cfg: dict | None = None, timeout: int | None = None):
    return hs2.connect("spark", env, cfg, timeout)


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = connect(env, timeout=timeout)
    try:
        return fetch(con.cursor(), sql, max_rows, name="spark", source=f"spark:{env}")
    finally:
        con.close()
