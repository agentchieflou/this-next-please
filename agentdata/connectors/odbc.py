"""pyodbc helpers (DSN based). A 64-bit Python sees only 64-bit drivers and DSNs
(configure them in C:\\Windows\\System32\\odbcad32.exe, not SysWOW64)."""
from __future__ import annotations
from ..config import ConfigError
from ..install import install_cmd


def _pyodbc():
    try:
        import pyodbc  # optional dep
    except ImportError:
        raise ConfigError("pyodbc is not installed", hint=install_cmd("odbc")) from None
    return pyodbc


def available() -> bool:
    try:
        _pyodbc()
        return True
    except ConfigError:
        return False


def drivers() -> list[str]:
    try:
        return sorted(_pyodbc().drivers())
    except ConfigError:
        return []


def data_sources() -> dict[str, str]:
    try:
        return dict(sorted(_pyodbc().dataSources().items()))
    except ConfigError:
        return {}


def find_driver(needle: str) -> str | None:
    for d in drivers():
        if needle.lower() in d.lower():
            return d
    return None


def dsn_conn_str(dsn: str, user: str | None = None, password: str | None = None) -> str:
    parts = [f"DSN={dsn}"]
    if user:
        parts.append(f"UID={user}")
    if password:
        parts.append(f"PWD={password}")
    return ";".join(parts) + ";"


def connect(conn_str: str, timeout: int | None = None):
    con = _pyodbc().connect(conn_str, autocommit=True, timeout=int(timeout or 0))
    if timeout:
        try:
            con.timeout = int(timeout)  # statement timeout, seconds
        except Exception:  # noqa: BLE001
            pass
    return con
