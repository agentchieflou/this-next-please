"""Code the tests run, down a path they have never taken.

Pattern:        a node with line coverage but branch arcs recorded as missing -- logic the suite has
                never seen. `where` points at the untaken branch's line, not at the function, so the
                reviewer lands on the decision itself.
False positive: a branch that cannot be taken in the test environment -- a Windows-only arm on Linux,
                or an `if TYPE_CHECKING`. Coverage reports it as missing all the same.
Confidence:     med

Coverage-only: with no `.agent/graph/coverage.json` this check emits nothing.
"""
from __future__ import annotations

from . import CheckContext, Finding

KIND = "uncovered-branch"
SEVERITY = "logic"
CONFIDENCE = "med"


def check(ctx: CheckContext) -> list[Finding]:
    coverage = (ctx.graph.coverage or {}).get("nodes") or {}
    if not coverage:
        return []

    files_cov = (ctx.graph.coverage or {}).get("files") or {}
    out: list[Finding] = []
    for nid in sorted(ctx.graph.nodes):
        node = ctx.graph.nodes[nid]
        if node.kind not in ("function", "class"):
            continue
        cov = coverage.get(nid) or {}
        pct = cov.get("pct")
        branch_pct = cov.get("branch_pct")
        if not pct or branch_pct is None or branch_pct >= 100.0:
            continue

        missing = [
            b for b in (files_cov.get(node.path, {}).get("branches", {}) or {}).get("branch_missing", [])
            if node.line_start <= b[0] <= node.line_end
        ]
        if not missing:
            continue
        line = sorted(b[0] for b in missing)[0]
        out.append(Finding(
            kind=KIND, node=nid, where=ctx.where(node.path, line),
            severity=SEVERITY, confidence=CONFIDENCE,
            hint="add a case that takes the other arm of this branch before changing anything here",
            evidence=f"line coverage {pct}% but branch coverage {branch_pct}%; {len(missing)} arc(s) never taken, first at line {line}",
        ))
    return out
