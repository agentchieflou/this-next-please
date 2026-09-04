"""Symbols nothing calls.

Pattern:        zero fan-in, not tagged `entrypoint`, not a test, and no unresolved call edge
                anywhere in the graph that could name it dynamically.
False positive: anything reached by a name the extractor never resolved -- `getattr(mod, name)`,
                a plugin registry, a framework hook. Confidence drops to `low` for a file the generic
                extractor read, because there the call graph is a text guess rather than an AST fact.
Confidence:     high (Python-extracted), low (generic-extracted)
"""
from __future__ import annotations

from . import CheckContext, Finding

KIND = "dead-code"
SEVERITY = "hygiene"
CONFIDENCE = "high"


def check(ctx: CheckContext) -> list[Finding]:
    # a name mentioned by any unresolved edge could be reached dynamically; do not call it dead
    dynamic_names: set[str] = set()
    for e in ctx.graph.edges:
        if e.kind != "calls" or e.target in ctx.graph.nodes:
            continue
        tail = e.target.split(":", 1)[-1]
        dynamic_names.add(tail)
        dynamic_names.add(tail.rsplit(".", 1)[-1])

    out: list[Finding] = []
    for nid in sorted(ctx.graph.nodes):
        node = ctx.graph.nodes[nid]
        if node.kind not in ("function", "class"):
            continue
        if "entrypoint" in node.tags or ctx.fan_in(nid) > 0:
            continue
        if node.name in dynamic_names or nid in dynamic_names:
            continue
        # named by a string somewhere: getattr, a registry, an entry-point table. Not an edge, but a
        # reference all the same, so the honest answer is "cannot tell", not "dead".
        if node.name in ctx.string_literals:
            continue
        # a private helper of a class that is itself used is reachable through the class
        if node.name.startswith("__") and node.name.endswith("__"):
            continue

        extractor = ctx.file_extractors.get(node.path, "python" if node.path.endswith(".py") else "generic")
        out.append(Finding(
            kind=KIND, node=nid, where=node.where,
            severity=SEVERITY,
            confidence=CONFIDENCE if extractor == "python" else "low",
            hint="delete it, or add the caller the graph is missing (a dynamic reference is not an edge)",
            evidence=f"fan_in=0, tags={sorted(node.tags) or 'none'}, extractor={extractor}",
        ))
    return out
