"""Minimal TOON (Token-Oriented Object Notation) encoder.

Tabular:   name[N]{c1,c2}:\n  v1,v2
Scalar:    key: value
List:      key[N]: a,b,c
Nested:    key:\n  sub: value
Values containing , : " or newline are double-quoted with "" escaping.
"""
from __future__ import annotations
import re
import sys
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


# --------------------------------------------------------------------------------- validation

_ANSI = re.compile(r"\x1b\[")
_SCALAR = re.compile(r"^(\s*)([A-Za-z_][\w.\-]*): ?(.*)$")
_BLOCK = re.compile(r"^(\s*)([A-Za-z_][\w.\-]*):$")
_TABLE = re.compile(r"^(\s*)([A-Za-z_][\w.\-]*)\[(\d+)\]\{([^}]*)\}:$")
_LIST = re.compile(r"^(\s*)([A-Za-z_][\w.\-]*)\[(\d+)\]: ?(.*)$")


def validate(text: str) -> list[str]:
    """Problems with `text` as TOON, empty when it is fine.

    This exists so CI can assert that a command's stdout is the format the docs promise, from every
    shell -- a traceback, a `pip` warning, or an ANSI-coloured table piped into a file all read as
    "output" to a shell script and are caught here instead.
    """
    problems: list[str] = []
    if not text.strip():
        return ["empty output"]
    if _ANSI.search(text):
        problems.append("ANSI escape sequences in piped output")

    lines = text.splitlines()
    if any(ln.startswith("Traceback (most recent call last)") for ln in lines):
        problems.append("a Python traceback reached stdout")

    expect_rows, cols, seen_rows, table_name = 0, 0, 0, ""
    for n, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        if expect_rows and seen_rows < expect_rows and not (_TABLE.match(raw) or _BLOCK.match(raw)):
            fields = _split_row(raw.strip())
            if len(fields) != cols:
                problems.append(f"line {n}: {table_name} row has {len(fields)} fields, header declares {cols}")
            seen_rows += 1
            continue
        m = _TABLE.match(raw)
        if m:
            if expect_rows and seen_rows != expect_rows:
                problems.append(f"line {n}: {table_name} declared {expect_rows} rows, found {seen_rows}")
            table_name, expect_rows = m.group(2), int(m.group(3))
            cols, seen_rows = len([c for c in m.group(4).split(",") if c]), 0
            continue
        lm = _LIST.match(raw)
        if lm:
            declared, items = int(lm.group(3)), _split_row(lm.group(4))
            if lm.group(4).strip() and len(items) != declared:
                problems.append(f"line {n}: {lm.group(2)} declares {declared} items, found {len(items)}")
            continue
        if _BLOCK.match(raw) or _SCALAR.match(raw):
            continue
        problems.append(f"line {n}: not a TOON scalar, block or table header: {raw.strip()[:60]!r}")

    if expect_rows and seen_rows != expect_rows:
        problems.append(f"{table_name} declared {expect_rows} rows, found {seen_rows}")
    return problems


def _split_row(row: str) -> list[str]:
    """Split a data row on commas that are not inside double quotes."""
    out, cur, quoted = [], [], False
    for ch in row:
        if ch == '"':
            quoted = not quoted
            cur.append(ch)
        elif ch == "," and not quoted:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m agentdata.toon",
                                 description="Validate that text is the TOON this repo emits.")
    ap.add_argument("--validate", metavar="FILE", required=True, help="file to check, or - for stdin")
    a = ap.parse_args(argv)

    if a.validate == "-":
        text = sys.stdin.read()
    else:
        from . import textio
        text = textio.read_text(a.validate)

    problems = validate(text)
    if problems:
        for p in problems:
            print(f"not TOON: {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
