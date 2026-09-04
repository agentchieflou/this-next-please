"""Calls into an I/O node from inside a loop -- the N+1 shape.

Pattern:        a `calls` edge whose context carries `loop_depth > 0` (the Python extractor records
                loop nesting at every call site) and whose target is tagged `io`, either directly or
                one callee deeper.
False positive: a loop that runs a bounded, small number of times -- reading four config files in a
                `for` loop is this pattern and is fine. The check cannot see the iteration count.
Confidence:     high
"""
from __future__ import annotations

from . import CheckContext, Finding

KIND = "io-in-loop"
SEVERITY = "perf"
CONFIDENCE = "high"


def _io_targets(ctx: CheckContext) -> set[str]:
    return {nid for nid, n in ctx.graph.nodes.items() if "io" in n.tags}


def check(ctx: CheckContext) -> list[Finding]:
    io_ids = _io_targets(ctx)
    if not io_ids:
        return []

    out: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()

    for e in ctx.graph.edges:
        if e.kind != "calls" or not e.context.get("loop_depth"):
            continue
        depth = e.context["loop_depth"]

        # direct hit, then one hop: a loop calling a helper that is the thing touching the disk
        if e.target in io_ids:
            target, via = e.target, None
        else:
            indirect = sorted(ctx.callees.get(e.target, set()) & io_ids)
            if not indirect:
                continue
            target, via = indirect[0], e.target

        key = (e.source, target, e.where)
        if key in seen:
            continue
        seen.add(key)

        route = f"`{e.source}` -> `{target}`" if via is None else f"`{e.source}` -> `{via}` -> `{target}`"
        src = ctx.graph.nodes.get(e.source)
        out.append(Finding(
            kind=KIND,
            node=e.source,
            where=e.where or (src.where if src else ""),
            severity=SEVERITY,
            confidence=CONFIDENCE,
            hint="hoist the I/O out of the loop, or batch it into one call before the loop runs",
            evidence=f"loop_depth={depth}, {route} (target tagged io)",
        ))
    return out
