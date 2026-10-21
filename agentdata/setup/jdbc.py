"""A JDBC URL, read into the answers `ad-setup` asks for one data source connection.

Almost everyone who needs a Teradata, Hive, Impala, Oracle or Spark connection already has one working somewhere
else -- DBeaver, SQL Developer, Teradata Studio, a team wiki -- and that tool shows a JDBC URL. Pasting it is easier
and less error-prone than reading the host, port, transport and Kerberos principal back out of it by hand, so the
walkthrough (`tnp` -> Data sources -> Add a connection) offers to, and every answer it fills is still shown, as the
default, for the person to keep or change. Nothing here connects or stores anything.
"""
from __future__ import annotations

import re

from .. import config as C

# jdbc:<scheme> per source. Spark Thrift Servers speak HiveServer2, so `jdbc:hive2:` is the usual Spark URL too.
SCHEMES = {"teradata": ("teradata",), "hive": ("hive2", "hive"), "impala": ("impala", "hive2"),
           "oracle": ("oracle",), "spark": ("hive2", "spark", "databricks")}


def _params(text: str, sep: str) -> dict[str, str]:
    out = {}
    for part in text.split(sep):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _hs2(source: str, rest: str) -> dict:
    """//host:port/db;k=v;k=v  (Hive, Impala and Spark Thrift)."""
    m = re.match(r"//([^/:;?]+)(?::(\d+))?(?:/([^;?]*))?(.*)$", rest)
    if not m:
        raise ValueError("expected //host:port/database;key=value...")
    host, port, _db, tail = m.groups()
    p = _params(tail.replace("?", ";"), ";")
    e: dict = {"host": host}
    if port:
        e["port"] = int(port)
    mode = (p.get("transportmode") or p.get("transport") or "").lower()
    if p.get("httppath") or mode == "http":
        e["transport"] = "http"
        e["http_path"] = (p.get("httppath") or "cliservice").lstrip("/")
    elif mode == "binary":
        e["transport"] = "binary"
    if source != "spark":                    # only the Spark step asks for a transport; Hive/Impala stay binary
        e.pop("transport", None)
        e.pop("http_path", None)
    principal = p.get("principal") or p.get("krbhostfqdn") and f"{p.get('krbservicename', 'impala')}/_HOST"
    authmech = p.get("authmech")              # Cloudera / Simba drivers: 1 Kerberos, 3 user+password, 0 none
    if principal or authmech == "1":
        e["auth"] = "GSSAPI"
        service = (principal.split("/", 1)[0] if principal else p.get("krbservicename")) or ""
        if source == "spark" and service:
            e["service_name"] = service
    elif authmech == "3" or p.get("user") or p.get("uid"):
        e["auth"] = "LDAP"
        e["user"] = p.get("user") or p.get("uid") or ""
    elif authmech == "0" or (p.get("auth") or "").lower() == "nosasl":
        e["auth"] = "NOSASL"
    if (p.get("ssl") or p.get("usessl") or "").lower() in ("true", "1"):
        e["ssl"] = True
    return {k: v for k, v in e.items() if v not in ("", None)}


def _teradata(rest: str) -> dict:
    """//host[:port]/KEY=value,KEY=value"""
    m = re.match(r"//([^/:]+)(?::(\d+))?/?(.*)$", rest)
    if not m:
        raise ValueError("expected //host/LOGMECH=...,TMODE=...")
    host, _port, tail = m.groups()
    p = _params(tail, ",")
    e: dict = {"host": host}
    if p.get("logmech"):
        e["logmech"] = p["logmech"].upper()
    if p.get("tmode") and p["tmode"].upper() in ("ANSI", "TERA"):
        e["tmode"] = p["tmode"].upper()
    if p.get("user"):
        e["user"] = p["user"]
    return e


def _oracle(rest: str) -> dict:
    """thin:@host:port/service, thin:@host:port:SID, thin:@//host:port/service, thin:@alias, thin:@(DESCRIPTION=...)"""
    m = re.match(r"(?:thin|oci):(?:[^@]*)@(.+)$", rest)
    if not m:
        raise ValueError("expected thin:@host:port/service")
    target = m.group(1).strip()
    if target.startswith("(") or "/" not in target and ":" not in target:
        return {"style": "tns", "dsn": target}
    target = target.lstrip("/")
    m = re.match(r"([^:/]+)(?::(\d+))?(?:/([^?]+)|:([^/?]+))?", target)
    if not m or not (m.group(3) or m.group(4)):
        return {"style": "tns", "dsn": target}
    host, port, service, sid = m.groups()
    e: dict = {"style": "basic", "host": host, "port": int(port) if port else C.ORACLE_PORT}
    if service:
        e["service_name"] = service
    else:
        e["sid"] = sid
    return e


def parse(source: str, url: str) -> dict:
    """The connection fields a JDBC URL gives for `source`. Raises ValueError with what was expected."""
    url = (url or "").strip().strip('"').strip("'")
    m = re.match(r"jdbc:([a-z0-9]+):(.*)$", url, re.IGNORECASE)
    if not m:
        raise ValueError("a JDBC URL starts with jdbc:, e.g. " + EXAMPLE[source])
    scheme, rest = m.group(1).lower(), m.group(2)
    if scheme not in SCHEMES[source]:
        raise ValueError(f"a {scheme} URL is not a {source} connection; expected e.g. {EXAMPLE[source]}")
    if source == "teradata":
        e = _teradata(rest)
    elif source == "oracle":
        e = _oracle(rest)
    else:
        e = _hs2(source, rest)
    e["mode"] = "native"
    return e


EXAMPLE = {
    "teradata": "jdbc:teradata://tdprod.corp.example/LOGMECH=KRB5,TMODE=ANSI",
    "hive": "jdbc:hive2://hive.corp.example:10000/default;principal=hive/_HOST@CORP.EXAMPLE",
    "impala": "jdbc:impala://impala.corp.example:21050/default;AuthMech=1;KrbServiceName=impala",
    "oracle": "jdbc:oracle:thin:@ora.corp.example:1521/SALESPRD",
    "spark": "jdbc:hive2://sparkts.corp.example:10001/default;transportMode=http;httpPath=cliservice;"
             "principal=hive/_HOST@CORP.EXAMPLE",
}
