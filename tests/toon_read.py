"""Reading the TOON a command printed, for tests.

Deliberately not a parser -- `agentdata.toon` is encode-only and this is not the place to grow a
decoder. It is the two shapes a test actually asserts on: the `meta:` block, and a named table. Two
readers that disagreed would be worse than one that is narrow, so the contract slice uses this too.
"""
from __future__ import annotations

from agentdata.toon import _split_row


def meta(text: str) -> dict[str, str]:
    """The `meta:` block as flat strings."""
    out: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        if line.rstrip() == "meta:":
            inside = True
            continue
        if inside:
            if not line.startswith("  ") or not line.strip():
                break
            if ":" in line:
                key, value = line.strip().split(":", 1)
                out[key.strip()] = value.strip().strip('"')
    return out


def table(text: str, name: str) -> list[dict[str, str]]:
    """A `name[N]{cols}:` block as a list of dicts. Empty when the table is absent or has no rows."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(f"{name}[") or not stripped.endswith(":"):
            continue
        head = stripped[len(name) + 1:-1]
        count_text, _, cols_text = head.partition("]")
        cols = [c.strip() for c in cols_text.strip("{}").split(",") if c.strip()]
        rows = []
        for row_line in lines[i + 1:i + 1 + int(count_text or 0)]:
            values = [v.strip().strip('"') for v in _split_row(row_line.strip())]
            rows.append(dict(zip(cols, values)))
        return rows
    return []
