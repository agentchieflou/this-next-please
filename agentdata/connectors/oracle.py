"""Oracle via python-oracledb.

Two independent settings. `client_lib` turns on thick mode (Instant Client): needed for Kerberos or a wallet, and for
some older servers. `auth` says how to authenticate: `password` (user + keyring password — valid in BOTH thin and
thick mode), `kerberos` or `wallet` (external, thick only). Configs written before `auth` existed meant Kerberos by
setting client_lib, and still do."""
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
    auth = str(e.get("auth") or ("kerberos" if (e.get("client_lib") or e.get("thick")) else "password")).lower()
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
    if auth in ("kerberos", "wallet"):
        if not (e.get("client_lib") or e.get("thick")):
            raise ConfigError(f"oracle:{env} uses {auth} auth but no Oracle client is configured (thin mode cannot)",
                              hint="set client_lib to the Instant Client lib dir: ad-setup --patch sources.oracle")
        con = oracledb.connect(externalauth=True, dsn=dsn)   # Kerberos / wallet via sqlnet.ora
    else:
        user = e.get("user") or getpass.getuser()
        pw = secrets.get_password("oracle", env, user)
        if not pw:
            raise secrets.missing_password_error("oracle", env, user) from None
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
