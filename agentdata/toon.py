"""Minimal TOON (Token-Oriented Object Notation) encoder.

Tabular:   name[N]{c1,c2}:\n  v1,v2
Scalar:    key: value
List:      key[N]: a,b,c
Nested:    key:\n  sub: value
Values containing , : " or newline are double-quoted with "" escaping.
"""
from __future__ import annotations
from typing import Any

_NEEDS_QUOTE = set(',:"\n\r')


def _v(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        return repr(x) if isinstance(x, float) else str(x)
    s = str(x)
    if not s or s != s.strip() or any(ch in _NEEDS_QUOTE for ch in s):
        return '"' + s.replace('"', '""') + '"'
    return s


def table(name: str, columns: list[str], rows: list[list[Any]], indent: int = 0) -> str:
    pad = " " * indent
    head = f"{pad}{name}[{len(rows)}]{{{','.join(columns)}}}:"
    body = [f"{pad}  " + ",".join(_v(v) for v in r) for r in rows]
    return "\n".join([head, *body])


def encode(obj: Any, indent: int = 0, key: str | None = None) -> str:
    pad = " " * indent
    if isinstance(obj, dict):
        lines = [f"{pad}{key}:"] if key is not None else []
        inner = indent + (2 if key is not None else 0)
        for k, v in obj.items():
            lines.append(encode(v, inner, str(k)))
        return "\n".join(lines)
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            cols: list[str] = []
            for x in obj:
                for k in x:
                    if k not in cols:
                        cols.append(k)
            if all(not isinstance(x.get(c), (dict, list)) for x in obj for c in cols):
                return table(key or "items", cols, [[x.get(c) for c in cols] for x in obj], indent)
            lines = [f"{pad}{key or 'items'}[{len(obj)}]:"]
            for x in obj:
                lines.append(encode(x, indent + 2, "-"))
            return "\n".join(lines)
        return f"{pad}{key or 'items'}[{len(obj)}]: " + ",".join(_v(x) for x in obj)
    return f"{pad}{key}: {_v(obj)}" if key is not None else f"{pad}{_v(obj)}"
