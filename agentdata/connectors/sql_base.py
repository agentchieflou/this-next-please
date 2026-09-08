"""Shared guardrails for SQL connectors: read-only, row cap, timeout, no creds in process args/output."""
from __future__ import annotations
import re, time
from ..model import AgentTable

_FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|call|exec)\b", re.I)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"'(?:[^']|'')*'")


def _code_only(sql: str) -> str:
    """The statement with comments and string literals removed.

    Both are places a forbidden keyword can appear harmlessly (`WHERE action = 'delete'`) and, more
    to the point, places one can be hidden. Removing them first means the keyword search can look
    at the whole statement rather than only at the start of each line -- which is what let
    `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` through: the DML was mid-line, and the
    statement opened with a perfectly innocent `WITH`.
    """
    without_strings = _STRING.sub("''", sql)
    without_block = _BLOCK_COMMENT.sub(" ", without_strings)
    return _LINE_COMMENT.sub(" ", without_block)


def assert_readonly(sql: str) -> None:
    code = _code_only(sql)
    hit = _FORBIDDEN.search(code)
    if hit:
        raise PermissionError(
            f"read-only: `{hit.group(1).upper()}` is not allowed anywhere in the statement, "
            "including inside a CTE or after a comment")
    if ";" in code.strip().rstrip(";"):
        raise PermissionError("read-only: single SELECT/WITH statement only")
    if not re.match(r"^\s*(select|with|show|describe|explain)\b", code, re.I):
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
