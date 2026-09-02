"""Hive via impyla + GSSAPI. Needs a live TGT (klist). Fragile on Windows; beeline fallback is a TODO."""
from __future__ import annotations
from .sql_base import assert_readonly, fetch


def _connect(env: str):
    import os
    from impala.dbapi import connect
    # TODO(data_czars): host/port per env from data_czars.
    host = os.environ.get(f"HIVE_HOST_{env.upper()}") or os.environ.get("HIVE_HOST")
    port = int(os.environ.get("HIVE_PORT", "10000"))
    if not host:
        raise RuntimeError(f"no host for env {env}")
    return connect(host=host, port=port, auth_mechanism="GSSAPI", kerberos_service_name="hive")


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = _connect(env)
    try:
        return fetch(con.cursor(), sql, max_rows, name="hive", source=f"hive:{env}")
    finally:
        con.close()
