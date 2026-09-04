"""Heavily called, and no test has ever run it.

Pattern:        fan-in in the top decile of the call graph, and coverage data says the node is below
                `graph.min_coverage`. The most valuable `test-cover` target there is: the guard will
                refuse edits here until a test exists.
False positive: a node whose coverage the collector could not attribute -- a decorator-wrapped
                function, or one whose lines the runner reported against a different file.
Confidence:     high

Silent until coverage exists: with no `.agent/graph/coverage.json` every node is `unknown`, and
guessing would put the model to work on a node no test protects.
"""
from __future__ import annotations

from . import CheckContext, Finding

KIND = "untested-hub"
SEVERITY = "logic"
CONFIDENCE = "high"


def check(ctx: CheckContext) -> list[Finding]:
    coverage = (ctx.graph.coverage or {}).get("nodes") or {}
    if not coverage:
        return []

    cut = ctx.top_decile_fan_in()
    threshold = ctx.min_coverage * 100.0
    out: list[Finding] = []
    for nid in sorted(ctx.graph.nodes):
        node = ctx.graph.nodes[nid]
        if node.kind not in ("function", "class"):
            continue
        fan_in = ctx.fan_in(nid)
        if fan_in < cut:
            continue
        pct = (coverage.get(nid) or {}).get("pct")
        if pct is None or pct >= threshold:
            continue
        out.append(Finding(
            kind=KIND, node=nid, where=node.where,
            severity=SEVERITY, confidence=CONFIDENCE,
            hint="run `test-cover` on this node first: the guard refuses edits to code no test executes",
            evidence=f"fan_in={fan_in} (top-decile cut {cut}), coverage={pct}% < {threshold:g}%",
        ))
    return out
