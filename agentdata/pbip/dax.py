"""DAX runner (DAX Studio `dscmd`) and a visual -> DAX query builder.

dscmd reaches a running Desktop with `-s localhost:<port>` (ad-pbip desktop) and the service with the XMLA URL.
`-f/--file` support differs across dscmd builds, so the runner falls back to passing the query with `-q`.
Result headers come back as `Table[Column]`; they are reduced to the bare column name (same rule pbi-tools applies).
"""
from __future__ import annotations
import csv
import os
import re
import tempfile
from typing import Callable

from ..model import AgentTable, _coerce
from . import pbir as P
from .normalize import ModelIndex

Runner = Callable[[list[str], int], tuple[int, str, str]]
_HEADER = re.compile(r"^[^\[]*\[([^\]]+)\]$")
_LIT_STR = re.compile(r"^'(.*)'$", re.S)
_LIT_NUM = re.compile(r"^(-?\d+(?:\.\d+)?)[LDM]?$")
_LIT_DT = re.compile(r"^datetime'(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2}))?")


class DaxError(RuntimeError):
    pass


def clean_header(h: str) -> str:
    m = _HEADER.match(h or "")
    return m.group(1) if m else h


def _q(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def col(table: str, column: str) -> str:
    return f"{_q(table)}[{column}]"


def literal(v: str) -> str | None:
    """PBIR literal -> DAX literal: 'Done' -> \"Done\"; 2026L -> 2026; true/false; null -> BLANK(); datetime'...' -> DATE()."""
    s = str(v).strip()
    if s.lower() == "null":
        return "BLANK()"
    if s.lower() in ("true", "false"):
        return s.upper()
    m = _LIT_STR.match(s)
    if m:
        return '"' + m.group(1).replace('"', '""') + '"'
    m = _LIT_DT.match(s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if m.group(4) and (m.group(4), m.group(5), m.group(6)) != ("00", "00", "00"):
            return f"DATE({int(y)},{int(mo)},{int(d)}) + TIME({int(m.group(4))},{int(m.group(5))},{int(m.group(6))})"
        return f"DATE({int(y)},{int(mo)},{int(d)})"
    m = _LIT_NUM.match(s)
    if m:
        return m.group(1)
    return None


def filter_expressions(filters: list[dict]) -> tuple[list[str], list[str]]:
    """Categorical `In` filters -> TREATAS({...}, 'T'[C]); everything else is reported as skipped."""
    exprs, notes = [], []
    for f in filters:
        refs = [r for r in (f.get("refs") or []) if r.entity and r.kind == "column"]
        cond = None
        try:
            cond = (f.get("raw") or {}).get("filter", {}).get("Where", [{}])[0].get("Condition")
        except (AttributeError, IndexError):
            cond = None
        if not refs or not cond or "In" not in cond:
            notes.append(f"filter {f.get('name') or ''} ({f.get('type')}) on {f.get('field')} not translated")
            continue
        values = []
        for row in cond["In"].get("Values") or []:
            lit = (row[0].get("Literal") or {}).get("Value") if row and isinstance(row[0], dict) else None
            dv = literal(lit) if lit is not None else None
            if dv is not None:
                values.append(dv)
        if not values:
            notes.append(f"filter on {f.get('field')} has no literal values; skipped")
            continue
        exprs.append(f"TREATAS({{{', '.join(values)}}}, {col(refs[0].entity, refs[0].prop)})")
    return exprs, notes


def visual_query(visual: P.Visual, index: ModelIndex, extra_filters: list[dict] | None = None, top_n: int = 500) -> tuple[str, list[str]]:
    """SUMMARIZECOLUMNS over the visual's group-by columns and measures, with categorical filters as TREATAS."""
    groups: list[str] = []
    measures: list[tuple[str, str]] = []
    notes: list[str] = []
    for r in visual.fields:
        if not r.entity or not r.context.startswith("projection:"):
            continue
        if r.kind == "column" and r.agg:
            fn = {"Sum": "SUM", "Avg": "AVERAGE", "Min": "MIN", "Max": "MAX", "Count": "COUNTA", "DistinctCount": "DISTINCTCOUNT",
                  "Median": "MEDIAN", "StdDev": "STDEV.P", "Var": "VAR.P"}.get(r.agg)
            if fn:
                measures.append((f"{r.agg} of {r.prop}", f"CALCULATE({fn}({col(r.entity, r.prop)}))"))
            else:
                notes.append(f"aggregation {r.agg} over {r.label()} not translated")
        elif r.kind == "column":
            c = col(r.entity, r.prop)
            if c not in groups:
                groups.append(c)
        elif r.kind == "measure":
            measures.append((r.prop, f"[{r.prop}]"))
        elif r.kind == "level":
            column = index.level_column.get((r.entity, r.hierarchy, r.prop)) if hasattr(index, "level_column") else None
            if column:
                c = col(r.entity, column)
                if c not in groups:
                    groups.append(c)
            else:
                notes.append(f"hierarchy level {r.label()} has no column mapping; skipped")
        elif r.kind == "hierarchy":
            notes.append(f"whole hierarchy {r.label()} skipped (levels are queried individually)")
    filt, fnotes = filter_expressions(list(visual.filters) + list(extra_filters or []))
    notes += fnotes
    seen: set[str] = set()
    measure_args = []
    for name, expr in measures:
        if name in seen:
            continue
        seen.add(name)
        measure_args.append(f'"{name}", {expr}')
    if not groups and not measure_args:
        raise DaxError(f"visual {visual.id} has no model fields to query")
    if groups or filt:
        args = groups + filt + measure_args
        body = "SUMMARIZECOLUMNS(\n    " + ",\n    ".join(args) + "\n)"
        if groups:
            body = f"TOPN({top_n}, {body})"
    else:
        body = "ROW(\n    " + ",\n    ".join(measure_args) + "\n)"
    dax = "// " + (visual.title or visual.id) + f" ({visual.type}) on page {visual.page_name}\n" + "".join(f"// skipped: {n}\n" for n in notes) + "EVALUATE\n" + body + "\n"
    return dax, notes


def measure_probe(measure: str) -> str:
    return f'EVALUATE ROW("value", [{measure}])\n'


INFO_MEASURES = 'EVALUATE SELECTCOLUMNS(INFO.VIEW.MEASURES(), "Table", [Table], "Measure", [Name])\n'


def run_dax(dax: str, server: str, dscmd: str, database: str | None = None, out_csv: str | None = None,
            run: Runner | None = None, file_flag: bool = True, name: str = "dax", timeout: int = 300) -> AgentTable:
    from .desktop import default_run
    run = run or default_run
    if not dscmd or not os.path.exists(dscmd):
        raise DaxError(f"dscmd not found: {dscmd!r} (set powerbi.tools.dscmd_exe via ad-setup --only powerbi)")
    with tempfile.TemporaryDirectory() as td:
        out_csv = out_csv or os.path.join(td, "out.csv")
        qf = os.path.join(td, "query.dax")
        with open(qf, "w", encoding="utf-8") as f:
            f.write(dax)
        args = [dscmd, "csv", out_csv, "-s", server] + (["-d", database] if database else []) + (["-f", qf] if file_flag else ["-q", dax])
        rc, out, err = run(args, timeout)
        if rc != 0 or not os.path.exists(out_csv):
            raise DaxError(((out or "") + "\n" + (err or "")).strip()[-400:] or f"dscmd exit {rc}")
        with open(out_csv, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
    cols = [clean_header(h) for h in (rows[0] if rows else [])]
    return AgentTable(name, cols, [[_coerce(v) for v in r] for r in rows[1:]], source=f"dscmd {server}" + (f" {database}" if database else ""))
