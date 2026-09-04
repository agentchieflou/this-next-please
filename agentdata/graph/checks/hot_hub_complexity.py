"""Busy and branchy at the same time -- where a speedup actually pays off.

Pattern:        fan-in in the top decile of the call graph *and* cyclomatic complexity above
                COMPLEXITY_MIN. Neither alone is interesting: a hot one-liner is already cheap and a
                gnarly function nobody calls is not on any hot path.
False positive: a dispatcher. A `main()` that is a long if/elif over subcommands scores high on both
                and is exactly as fast as it needs to be.
Confidence:     med
"""
from __future__ import annotations

from . import CheckContext, Finding

KIND = "hot-hub-complexity"
SEVERITY = "perf"
CONFIDENCE = "med"
COMPLEXITY_MIN = 5


def check(ctx: CheckContext) -> list[Finding]:
    cut = ctx.top_decile_fan_in()
    out: list[Finding] = []
    for nid in sorted(ctx.graph.nodes):
        node = ctx.graph.nodes[nid]
        if node.kind not in ("function", "class"):
            continue
        fan_in = ctx.fan_in(nid)
        if fan_in < cut or node.complexity <= COMPLEXITY_MIN:
            continue
        out.append(Finding(
            kind=KIND, node=nid, where=node.where,
            severity=SEVERITY, confidence=CONFIDENCE,
            hint="measure before changing anything: run `ad-test bench` on this node, then optimise the branch the profile names",
            evidence=f"fan_in={fan_in} (top-decile cut {cut}), complexity={node.complexity}, loc={node.loc}",
        ))
    return out
