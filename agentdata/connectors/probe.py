"""Connection smoke tests and capability probes (ad-setup, ad-doctor --online). Results feed ad-sql-check."""
from __future__ import annotations
import re
import time
from typing import Any

SCALAR = {"teradata": "SELECT 1", "hive": "SELECT 1", "impala": "SELECT 1", "oracle": "SELECT 1 FROM DUAL"}


def connect(source: str, env: str, cfg: dict | None = None, timeout: int | None = 30):
    if source == "teradata":
        from . import teradata as m
        return m.connect(env, cfg, timeout)
    if source == "oracle":
        from . import oracle as m
        return m.connect(env, cfg, timeout)
    from . import hs2
    return hs2.connect(source, env, cfg, timeout)


def _try(con, sql: str) -> tuple[bool, list[str], list]:
    try:
        cur = con.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in (cur.description or [])]
        return True, cols, [list(r) for r in rows]
    except Exception:  # noqa: BLE001 - a failed probe just means "capability absent"
        return False, [], []


def smoke(source: str, env: str, cfg: dict | None = None) -> dict:
    """SELECT 1 (FROM DUAL for Oracle) + capability probes. Raises on connection failure."""
    t0 = time.time()
    con = connect(source, env, cfg)
    try:
        ok, _, _ = _try(con, SCALAR[source])
        if not ok:
            raise RuntimeError(f"{SCALAR[source]} failed on {source}:{env}")
        caps = capabilities(source, con)
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "elapsed_s": round(time.time() - t0, 2), "capabilities": caps}


def _version(con, sql: str) -> tuple[str | None, int | None]:
    ok, _, rows = _try(con, sql)
    if not ok or not rows or not rows[0]:
        return None, None
    s = str(rows[0][0])
    m = re.search(r"(\d+)\.(\d+)", s)
    return s[:80], (int(m.group(1)) if m else None)


def capabilities(source: str, con) -> dict[str, Any]:
    caps: dict[str, Any] = {}
    if source == "teradata":
        ok, cols, rows = _try(con, "HELP SESSION")
        if ok and rows:
            for i, c in enumerate(cols):
                if "transaction" in str(c).lower():
                    v = str(rows[0][i]).strip().upper()
                    caps["tmode"] = "ANSI" if v.startswith("ANSI") else "TERA"
        caps["trunc_date"] = _try(con, "SELECT TRUNC(CURRENT_DATE, 'MM')")[0]
        caps["to_char"] = _try(con, "SELECT TO_CHAR(CURRENT_DATE, 'YYYY-MM-DD')")[0]
        caps["listagg"] = _try(con, "SELECT LISTAGG(x, ',') WITHIN GROUP (ORDER BY x) FROM (SELECT 'a' AS x) t")[0]
    elif source in ("hive", "impala"):
        v, major = _version(con, "SELECT version()")
        if v:
            caps["version"] = v
        if major is not None:
            caps["major"] = major
    elif source == "oracle":
        v, major = _version(con, "SELECT banner FROM v$version")
        if v:
            caps["version"] = v
        if major is not None:
            caps["major"] = major
    return caps
