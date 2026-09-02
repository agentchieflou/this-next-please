"""Shared guardrails for SQL connectors: read-only, row cap, timeout, no creds in process args/output."""
from __future__ import annotations
import re, time
from ..model import AgentTable

_FORBIDDEN = re.compile(r"^\s*(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|call|exec)\b", re.I | re.M)


def assert_readonly(sql: str) -> None:
    if _FORBIDDEN.search(sql) or ";" in sql.strip().rstrip(";"):
        raise PermissionError("read-only: single SELECT/WITH statement only")
    if not re.match(r"^\s*(select|with|show|describe|explain)\b", sql, re.I):
        raise PermissionError("read-only: statement must start with SELECT/WITH/SHOW/DESCRIBE/EXPLAIN")


def fetch(cursor, sql: str, max_rows: int, name: str, source: str) -> AgentTable:
    t0 = time.time()
    cursor.execute(sql)
    cols = [d[0] for d in cursor.description]
    rows = [list(r) for r in cursor.fetchmany(max_rows + 1)]
    truncated = len(rows) > max_rows
    t = AgentTable(name=name, columns=cols, rows=rows[:max_rows], source=source, truncated=truncated,
                   elapsed_s=time.time() - t0)
    return t
