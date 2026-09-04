"""Graph-derived checks: named, mechanical findings instead of a model eyeballing a repository.

Every check lives in its own module here and must declare, in its module docstring, three things:

    Pattern:        what shape in the graph or AST makes it fire.
    False positive: the case it is known to get wrong. A check with no honest failure mode is a
                    check nobody has thought about; `test_graph_findings.py` fails a module that
                    omits this line.
    Confidence:     low | med | high -- how much a row from this check should be trusted.

A check exposes `KIND`, `SEVERITY`, `CONFIDENCE` and `check(ctx) -> list[Finding]`. It never reads
coverage or ranks anything: `covered` and `leverage` are stamped by the runner in `..findings`, so a
check stays a statement about the code and nothing else.
"""
from __future__ import annotations
import ast
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..model import Graph, Node
from ... import textio

SEVERITIES = ("perf", "logic", "hygiene")
CONFIDENCE_ORDER = {"low": 0, "med": 1, "high": 2}


@dataclass
class Finding:
    """One row. `covered` and `leverage` are filled in by the runner, not by the check."""
    kind: str
    node: str
    where: str
    severity: str
    confidence: str
    hint: str
    evidence: str
    covered: str = "unknown"
    leverage: int = 0


class CheckContext:
    """Everything a check may look at, built once per `ad-graph findings` run.

    Source files are parsed at most once each: several checks need AST detail the graph does not
    carry (an `except:` body, the arguments at a call site), and re-parsing per check turned a run
    over this repository into a measurable pause.
    """

    def __init__(self, graph: Graph, meta: dict[str, Any], root: str, min_coverage: float = 0.8) -> None:
        self.graph = graph
        self.meta = meta
        self.root = os.path.abspath(root)
        self.min_coverage = min_coverage
        self.file_extractors: dict[str, str] = meta.get("file_extractors") or {}
        self._source: dict[str, str | None] = {}
        self._tree: dict[str, ast.Module | None] = {}
        self._nodes_by_file: dict[str, list[Node]] | None = None
        self._strings: set[str] | None = None

        self.callers: dict[str, set[str]] = {}
        self.callees: dict[str, set[str]] = {}
        for e in graph.edges:
            if e.kind != "calls":
                continue
            self.callees.setdefault(e.source, set()).add(e.target)
            if e.target in graph.nodes:
                self.callers.setdefault(e.target, set()).add(e.source)

    # ------------------------------------------------------------------ source access

    @property
    def python_files(self) -> list[str]:
        """Relpaths the Python extractor handled, sorted. Checks that need an AST use only these."""
        if self.file_extractors:
            return sorted(f for f, ext in self.file_extractors.items() if ext == "python")
        return sorted({n.path for n in self.graph.nodes.values() if n.path.endswith(".py")})

    def source(self, relpath: str) -> str | None:
        if relpath not in self._source:
            path = os.path.join(self.root, relpath.replace("/", os.sep))
            try:
                self._source[relpath] = textio.read_text(path)
            except Exception:
                self._source[relpath] = None
        return self._source[relpath]

    def tree(self, relpath: str) -> ast.Module | None:
        if relpath not in self._tree:
            text = self.source(relpath)
            try:
                self._tree[relpath] = ast.parse(text) if text is not None else None
            except SyntaxError:
                # a file the graph could still index by name but this Python cannot parse
                self._tree[relpath] = None
        return self._tree[relpath]

    @property
    def string_literals(self) -> set[str]:
        """Every string constant in the repository, and the last dotted segment of each.

        A name that appears as a string is a name something can reach with `getattr` or a registry
        lookup, so it is a possible reference the call graph will never carry an edge for.
        """
        if self._strings is None:
            found: set[str] = set()
            for rel in self.python_files:
                tree = self.tree(rel)
                if tree is None:
                    continue
                for n in ast.walk(tree):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value:
                        found.add(n.value)
                        found.add(n.value.rsplit(".", 1)[-1])
            self._strings = found
        return self._strings

    # ------------------------------------------------------------------ node lookup

    @property
    def nodes_by_file(self) -> dict[str, list[Node]]:
        if self._nodes_by_file is None:
            by_file: dict[str, list[Node]] = {}
            for n in self.graph.nodes.values():
                by_file.setdefault(n.path, []).append(n)
            for v in by_file.values():
                v.sort(key=lambda n: (n.line_start, -n.line_end))
            self._nodes_by_file = by_file
        return self._nodes_by_file

    def node_at(self, relpath: str, line: int) -> Node | None:
        """The innermost function/class node containing `line`, else the file node."""
        best: Node | None = None
        for n in self.nodes_by_file.get(relpath, []):
            if n.kind == "file":
                best = best or n
                continue
            if n.line_start <= line <= n.line_end:
                if best is None or best.kind == "file" or n.line_start >= best.line_start:
                    best = n
        return best

    def where(self, relpath: str, line: int) -> str:
        return f"{relpath}:{line}"

    def fan_in(self, node_id: str) -> int:
        return len(self.callers.get(node_id, ()))

    def top_decile_fan_in(self) -> int:
        """The fan-in a node must reach to sit in the busiest tenth of the call graph."""
        counts = sorted((self.fan_in(nid) for nid in self.graph.nodes), reverse=True)
        counts = [c for c in counts if c > 0]
        if not counts:
            return 1
        cut = counts[max(0, len(counts) // 10 - 1)]
        return max(1, cut)


# --------------------------------------------------------------------------------- registry

CheckFn = Callable[[CheckContext], list[Finding]]


def all_checks() -> list[Any]:
    """Every check module, in a stable order. Import here so a module is registered by existing."""
    from . import (  # noqa: F401  (imported for the registry)
        dead_code,
        hot_hub_complexity,
        import_cycle,
        io_in_loop,
        quadratic_scan,
        recursion_no_guard,
        repeated_call,
        swallowed_exception,
        uncovered_branch,
        untested_hub,
    )

    mods = [
        dead_code,
        hot_hub_complexity,
        import_cycle,
        io_in_loop,
        quadratic_scan,
        recursion_no_guard,
        repeated_call,
        swallowed_exception,
        uncovered_branch,
        untested_hub,
    ]
    return sorted(mods, key=lambda m: m.KIND)


def kinds() -> list[str]:
    return [m.KIND for m in all_checks()]
