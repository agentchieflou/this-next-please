"""Oracle via python-oracledb. Kerberos requires Thick mode (Oracle client libs) — Thin cannot do KRB5."""
from __future__ import annotations
from .sql_base import assert_readonly, fetch


def _connect(env: str):
    import os, oracledb
    # TODO(data_czars): resolve dsn/user/wallet from data_czars; keyring for LDAP fallback.
    dsn = os.environ.get(f"ORA_DSN_{env.upper()}") or os.environ.get("ORA_DSN")
    if not dsn:
        raise RuntimeError(f"no DSN for env {env}")
    lib = os.environ.get("ORACLE_CLIENT_LIB")
    if lib:
        oracledb.init_oracle_client(lib_dir=lib)
        return oracledb.connect(externalauth=True, dsn=dsn)  # Kerberos via sqlnet.ora
    import keyring, getpass
    user = os.environ.get("ORA_USER") or getpass.getuser()
    pw = keyring.get_password(f"oracle:{env}", user)
    if not pw:
        raise RuntimeError("no Oracle client lib for KRB5 and no keyring secret for LDAP fallback")
    return oracledb.connect(user=user, password=pw, dsn=dsn)


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = _connect(env)
    try:
        con.call_timeout = timeout * 1000
        return fetch(con.cursor(), sql, max_rows, name="ora", source=f"oracle:{env}")
    finally:
        con.close()
