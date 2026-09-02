"""Oracle via python-oracledb. Thin mode by default (no client libraries, user+password from keyring);
thick mode with `client_lib` for Kerberos/external auth (Thin cannot do KRB5)."""
from __future__ import annotations
import getpass
from ..config import ConfigError, expand, source_env
from ..install import install_cmd
from . import secrets
from .sql_base import assert_readonly, fetch

_thick_ready = False


def connect(env: str, cfg: dict | None = None, timeout: int | None = None):
    global _thick_ready
    e = source_env(cfg, "oracle", env)
    try:
        import oracledb  # optional dep
    except ImportError:
        raise ConfigError("oracledb is not installed", hint=install_cmd("oracle")) from None
    dsn = e["dsn"]
    if e.get("tns_admin"):
        oracledb.defaults.config_dir = expand(e["tns_admin"])
    if e.get("client_lib") or e.get("thick"):
        if not _thick_ready:
            kw = {}
            if e.get("client_lib"):
                kw["lib_dir"] = expand(e["client_lib"])
            if e.get("tns_admin"):
                kw["config_dir"] = expand(e["tns_admin"])
            try:
                oracledb.init_oracle_client(**kw)
            except Exception as ex:  # noqa: BLE001
                raise ConfigError(f"oracle thick-mode init failed: {ex}",
                                  hint="check client_lib (ad-setup --only sources)") from None
            _thick_ready = True
        con = oracledb.connect(externalauth=True, dsn=dsn)  # Kerberos via sqlnet.ora
    else:
        user = e.get("user") or getpass.getuser()
        pw = secrets.get_password("oracle", env, user)
        if not pw:
            raise ConfigError(f"no password in keyring for oracle:{env} user {user}",
                              hint="ad-setup --only sources (thin mode needs a password; set client_lib for Kerberos)")
        con = oracledb.connect(user=user, password=pw, dsn=dsn)
    if timeout:
        con.call_timeout = int(timeout) * 1000
    return con


def query(sql: str, env: str, max_rows: int = 5000, timeout: int = 120):
    assert_readonly(sql)
    con = connect(env, timeout=timeout)
    try:
        cur = con.cursor()
        return fetch(cur, sql, max_rows, name="ora", source=f"oracle:{env}")
    finally:
        con.close()
