"""`ad-graph findings` — run every check, stamp each row with coverage and leverage, rank, diff.

Ranking is the whole point of the command. A finding on code no test covers cannot be acted on: the
guard (#43) refuses the edit. So covered rows come first, and within them the ones with the most
leverage -- fan-in times complexity, so the model works on the hot hub rather than the leaf nobody
calls. Uncovered rows are not noise, they are `test-cover` targets.
"""
from __future__ import annotations
import os
from typing import Any

from . import checks as C
from .checks import CONFIDENCE_ORDER, CheckContext, Finding
from .query import load_graph
from .. import config
from ..model import AgentTable

COLUMNS = [
    "kind", "node", "where", "severity", "confidence", "covered", "leverage", "hint", "evidence",
]


def _covered(pct: float | None, has_coverage: bool, min_coverage: float) -> str:
    """`unknown` is not `false`: one means no data, the other means data that says no."""
    if not has_coverage or pct is None:
        return "unknown"
    return "true" if pct >= min_coverage * 100.0 else "false"


def _leverage(ctx: CheckContext, node_id: str) -> int:
    node = ctx.graph.nodes.get(node_id)
    if node is None:
        return 0
    return max(1, ctx.fan_in(node_id)) * max(1, node.complexity)


def _sort_key(f: Finding) -> tuple:
    # covered first (only those may be changed), then leverage desc, then a stable tiebreak
    return (0 if f.covered == "true" else 1, -f.leverage, f.kind, f.node, f.where)


def collect(
    root: str = ".",
    graph_dir: str = ".agent/graph",
    *,
    kinds: list[str] | None = None,
    min_confidence: str = "low",
    covered_only: bool = False,
    top: int | None = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    graph, meta = load_graph(root, graph_dir=graph_dir)
    min_coverage = config.min_coverage(cfg, root=root)
    ctx = CheckContext(graph, meta, root, min_coverage=min_coverage)

    node_cov = (graph.coverage or {}).get("nodes") or {}
    has_coverage = bool(node_cov)

    wanted = set(kinds) if kinds else None
    floor = CONFIDENCE_ORDER.get(min_confidence, 0)

    rows: list[Finding] = []
    ran: list[str] = []
    for mod in C.all_checks():
        if wanted is not None and mod.KIND not in wanted:
            continue
        ran.append(mod.KIND)
        for f in mod.check(ctx):
            if CONFIDENCE_ORDER.get(f.confidence, 0) < floor:
                continue
            f.covered = _covered((node_cov.get(f.node) or {}).get("pct"), has_coverage, min_coverage)
            f.leverage = _leverage(ctx, f.node)
            rows.append(f)

    if covered_only:
        rows = [f for f in rows if f.covered == "true"]

    rows.sort(key=_sort_key)
    total = len(rows)
    if top is not None and top > 0:
        rows = rows[:top]

    by_kind: dict[str, int] = {}
    for f in rows:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1

    return {
        "ok": True,
        "findings": [f.__dict__.copy() for f in rows],
        "total": total,
        "shown": len(rows),
        "checks_run": ran,
        "by_kind": by_kind,
        "coverage": "present" if has_coverage else "absent",
        "min_coverage": min_coverage,
    }


def to_table(records: list[dict[str, Any]]) -> AgentTable:
    return AgentTable.from_records(records, name="findings", source="ad-graph findings", fields=COLUMNS)


# --------------------------------------------------------------------------------- baseline diff


def _key(rec: dict[str, Any]) -> str:
    return f"{rec.get('kind', '')}|{rec.get('node', '')}|{rec.get('where', '')}"


def diff_baseline(current: list[dict[str, Any]], baseline_path: str) -> list[dict[str, Any]]:
    """Tag each row `new` / `same`, and append a `fixed` row per baseline finding that is gone.

    Reads the baseline through `AgentTable.read_tsv`, the same reader `ad-diff` uses, so a findings
    file written by an earlier run is the baseline format -- there is no second serialisation to
    keep in step.
    """
    base = AgentTable.read_tsv(baseline_path, "baseline")
    cols = list(base.columns)
    base_recs = [dict(zip(cols, r)) for r in base.rows]
    base_keys = {_key(r): r for r in base_recs}

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rec in current:
        k = _key(rec)
        seen.add(k)
        out.append({**rec, "status": "same" if k in base_keys else "new"})

    for k, rec in base_keys.items():
        if k not in seen:
            out.append({
                **{c: rec.get(c, "") for c in COLUMNS if c in rec},
                "kind": rec.get("kind", ""),
                "node": rec.get("node", ""),
                "where": rec.get("where", ""),
                "status": "fixed",
            })
    order = {"new": 0, "same": 1, "fixed": 2}
    out.sort(key=lambda r: (order.get(r["status"], 3), r.get("kind", ""), r.get("node", "")))
    return out
