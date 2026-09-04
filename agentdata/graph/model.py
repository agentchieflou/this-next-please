"""Graph data model with deterministic serialization and hashing."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import Any

from .. import textio


@dataclass
class Node:
    id: str
    kind: str  # "file", "module", "class", "function", "test"
    name: str
    where: str  # "relpath:line-endline" or "relpath:line"
    sha: str  # sha256 of the node's source code
    loc: int = 1
    complexity: int = 1
    tags: list[str] = field(default_factory=list)
    covered: bool | None = None
    coverage_pct: float | None = None
    tests: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        if self.where and ":" in self.where:
            return textio.norm_path(self.where.split(":", 1)[0])
        return textio.norm_path(self.id.split("::", 1)[0])

    @property
    def line_start(self) -> int:
        if self.where and ":" in self.where:
            part = self.where.split(":", 1)[1]
            start_str = part.split("-")[0]
            try:
                return int(start_str)
            except ValueError:
                return 1
        return 1

    @property
    def line_end(self) -> int:
        if self.where and ":" in self.where:
            part = self.where.split(":", 1)[1]
            if "-" in part:
                end_str = part.split("-")[1]
                try:
                    return int(end_str)
                except ValueError:
                    return self.line_start
            return self.line_start
        return self.line_start

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "where": self.where,
            "sha": self.sha,
            "loc": self.loc,
            "complexity": self.complexity,
            "tags": sorted(self.tags),
        }
        if self.covered is not None:
            d["covered"] = self.covered
        if self.coverage_pct is not None:
            d["coverage_pct"] = self.coverage_pct
        if self.tests:
            d["tests"] = sorted(self.tests)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Node:
        return cls(
            id=d["id"],
            kind=d["kind"],
            name=d["name"],
            where=d.get("where", ""),
            sha=d.get("sha", ""),
            loc=d.get("loc", 1),
            complexity=d.get("complexity", 1),
            tags=list(d.get("tags", [])),
            covered=d.get("covered"),
            coverage_pct=d.get("coverage_pct"),
            tests=list(d.get("tests", [])),
        )


@dataclass
class Edge:
    source: str
    target: str
    kind: str  # "imports", "defines", "calls", "contains", "tests"
    source_type: str = "static"  # "static", "name", "coverage"
    where: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "source_type": self.source_type,
        }
        if self.where:
            d["where"] = self.where
        if self.context:
            d["context"] = self.context
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Edge:
        return cls(
            source=d["source"],
            target=d["target"],
            kind=d["kind"],
            source_type=d.get("source_type", "static"),
            where=d.get("where", ""),
            context=dict(d.get("context", {})),
        )

    def sort_key(self) -> tuple:
        return (self.source, self.target, self.kind, self.where, self.source_type)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.coverage: dict[str, Any] | None = None
        self._reverse_edges: dict[str, list[Edge]] | None = None
        self._forward_edges: dict[str, list[Edge]] | None = None

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        self._reverse_edges = None
        self._forward_edges = None

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    @property
    def forward_edges(self) -> dict[str, list[Edge]]:
        if self._forward_edges is None:
            res: dict[str, list[Edge]] = {}
            for e in self.edges:
                res.setdefault(e.source, []).append(e)
            self._forward_edges = res
        return self._forward_edges

    @property
    def reverse_edges(self) -> dict[str, list[Edge]]:
        if self._reverse_edges is None:
            res: dict[str, list[Edge]] = {}
            for e in self.edges:
                res.setdefault(e.target, []).append(e)
            self._reverse_edges = res
        return self._reverse_edges

    def callers_of(self, node_id: str) -> list[Edge]:
        """Incoming call edges."""
        return [e for e in self.reverse_edges.get(node_id, []) if e.kind == "calls"]

    def callees_of(self, node_id: str) -> list[Edge]:
        """Outgoing call edges."""
        return [e for e in self.forward_edges.get(node_id, []) if e.kind == "calls"]

    def compute_sha256(self) -> str:
        sorted_nodes = [self.nodes[k].to_dict() for k in sorted(self.nodes)]
        sorted_edges = [e.to_dict() for e in sorted(self.edges, key=lambda e: e.sort_key())]
        canonical = json.dumps({"nodes": sorted_nodes, "edges": sorted_edges}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        sorted_nodes = [self.nodes[k].to_dict() for k in sorted(self.nodes)]
        sorted_edges = [e.to_dict() for e in sorted(self.edges, key=lambda e: e.sort_key())]
        return {"nodes": sorted_nodes, "edges": sorted_edges}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Graph:
        g = cls()
        for nd in d.get("nodes", []):
            g.add_node(Node.from_dict(nd))
        for ed in d.get("edges", []):
            g.add_edge(Edge.from_dict(ed))
        return g

    def save(self, path: str) -> str:
        data = self.to_dict()
        text = json.dumps(data, indent=2, sort_keys=True)
        return textio.write_text(path, text)

    @classmethod
    def load(cls, path: str) -> Graph:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Graph file not found: {path}")
        d = textio.read_json(path, what="graph")
        return cls.from_dict(d)
