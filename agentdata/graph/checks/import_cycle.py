"""Modules that import each other, directly or round a longer ring.

Pattern:        every cycle `ad-graph cycles` reports. One row per cycle, anchored on its first node.
False positive: a cycle that only exists under `TYPE_CHECKING`, or one broken at runtime by a
                function-local import. The graph records the import either way.
Confidence:     high
"""
from __future__ import annotations

from . import CheckContext, Finding
from ..query import get_cycles

KIND = "import-cycle"
SEVERITY = "hygiene"
CONFIDENCE = "high"


def check(ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    for cycle in get_cycles(ctx.graph):
        if not cycle:
            continue
        head = cycle[0]
        node = ctx.graph.nodes.get(head)
        out.append(Finding(
            kind=KIND, node=head, where=node.where if node else head,
            severity=SEVERITY, confidence=CONFIDENCE,
            hint="move the shared names into a third module both can import, or defer one import into the function that needs it",
            evidence=" -> ".join(cycle),
        ))
    return out
