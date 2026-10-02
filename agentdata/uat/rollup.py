"""Aggregate a finer tier to the grain of the others: `ad-uat rollup`.

`uat-report-visual` step 6 said "aggregate a finer tier with a ≤10-line script before reconciling".
In a fleet that step could not be taken at all: writing the script needs the `write` tool and running
it needs `python`, and a headless turn is allowed neither (`fleet/launch.py`). The operator closed the
fleet and finished the UAT in a local `copilot` (report, 2026-10-02). Summing and counting by a key is
the whole of what that script ever did, so it is a command: allowed, deterministic, and the same
numbers on every machine.
"""
from __future__ import annotations

from ..model import AgentTable


class RollupError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg, self.hint = msg, hint


def _number(value, column: str, row: int):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RollupError(f"{column} row {row} is {value!r}, not a number", "sum only numeric columns")
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        raise RollupError(f"{column} row {row} is {value!r}, not a number",
                          "sum only numeric columns; group by a text column with --by") from None


def rollup(table: AgentTable, by: list[str], sums: list[str], count: str = "") -> AgentTable:
    """One row per distinct `by` tuple, in order of first appearance: each `sums` column added up
    (blanks skipped; a column with no numbers stays blank), and `count` rows when named."""
    missing = [c for c in by + sums if c not in table.columns]
    if missing:
        raise RollupError(f"no column {', '.join(missing)} in {table.source or table.name}",
                          f"its columns: {', '.join(table.columns[:20])}")
    if not by:
        raise RollupError("nothing to group by", "--by <column>[,<column>…]")
    if count and count in by + sums:
        raise RollupError(f"--count {count} names a column already in the result", "pick another name")
    at = {c: i for i, c in enumerate(table.columns)}
    groups: dict[tuple, dict] = {}
    for n, row in enumerate(table.rows, 2):            # row 1 is the header
        key = tuple(row[at[c]] for c in by)
        g = groups.setdefault(key, {"n": 0, **{c: None for c in sums}})
        g["n"] += 1
        for c in sums:
            v = _number(row[at[c]], c, n)
            if v is not None:
                g[c] = v if g[c] is None else g[c] + v
    columns = by + sums + ([count] if count else [])
    rows = []
    for key, g in groups.items():
        values = [round(g[c], 10) if isinstance(g[c], float) else g[c] for c in sums]
        rows.append(list(key) + values + ([g["n"]] if count else []))
    return AgentTable(name="rollup", columns=columns, rows=rows, source=table.source)
