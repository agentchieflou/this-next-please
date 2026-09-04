"""Graph builder walking a repository, extracting nodes/edges, and caching incrementally."""
from __future__ import annotations
import fnmatch
import hashlib
import json
import os
import re
import time
from typing import Any

from .extract.generic import GenericExtractor
from .extract.python import PythonExtractor
from .model import Edge, Graph, Node
from .. import proc, textio

DEFAULT_EXCLUDES = (
    ".git",
    ".agent",
    "node_modules",
    "build",
    "dist",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "*.egg-info",
)

EXTRACTOR_VERSIONS = {
    "python": "1.0",
    "generic": "1.0",
}


def find_entrypoints_from_pyproject(root: str) -> set[str]:
    """Inspects pyproject.toml for console scripts and maps them to node IDs."""
    pyproject = os.path.join(root, "pyproject.toml")
    if not os.path.isfile(pyproject):
        return set()

    entrypoints: set[str] = set()
    try:
        content = textio.read_text(pyproject)
        if "[project.scripts]" in content:
            section = content.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
            for match in re.finditer(r'[\w-]+ = "([\w.]+):([\w]+)"', section):
                mod, func = match.group(1), match.group(2)
                # Map module to candidate file paths
                candidate_rel = mod.replace(".", "/") + ".py"
                candidate_path = os.path.join(root, candidate_rel)
                if os.path.isfile(candidate_path):
                    entrypoints.add(f"{candidate_rel}::{func}")
                else:
                    # Could be in src/
                    src_candidate = "src/" + candidate_rel
                    if os.path.isfile(os.path.join(root, src_candidate)):
                        entrypoints.add(f"{src_candidate}::{func}")
                    else:
                        entrypoints.add(f"{candidate_rel}::{func}")
    except Exception:
        pass
    return entrypoints


def collect_files(
    root: str,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Collects relative file paths from root respecting exclusions."""
    norm_root = os.path.abspath(root)
    exclude_patterns = list(DEFAULT_EXCLUDES)
    if exclude:
        exclude_patterns.extend(exclude)

    # Try git ls-files if available
    git_files: list[str] | None = None
    if os.path.isdir(os.path.join(norm_root, ".git")):
        try:
            r = proc.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=norm_root, timeout=10)
            if r.ok:
                git_files = [line.strip().replace("\\", "/") for line in r.stdout.splitlines() if line.strip()]
        except Exception:
            git_files = None

    files: list[str] = []
    if git_files is not None:
        for rel in git_files:
            abs_p = os.path.join(norm_root, rel)
            if not os.path.isfile(abs_p):
                continue
            # Check exclusions
            parts = rel.split("/")
            if any(any(fnmatch.fnmatch(part, pat) for pat in exclude_patterns) for part in parts):
                continue
            if include and not any(fnmatch.fnmatch(rel, inc) for inc in include):
                continue
            files.append(rel)
    else:
        for dirpath, dirnames, filenames in os.walk(norm_root):
            # Prune excluded directories
            rel_dir = os.path.relpath(dirpath, norm_root).replace("\\", "/")
            dirnames[:] = [
                d for d in dirnames
                if not any(fnmatch.fnmatch(d, pat) for pat in exclude_patterns)
            ]
            for fn in filenames:
                if any(fnmatch.fnmatch(fn, pat) for pat in exclude_patterns):
                    continue
                abs_p = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_p, norm_root).replace("\\", "/")
                if include and not any(fnmatch.fnmatch(rel, inc) for inc in include):
                    continue
                files.append(rel)

    return sorted(files)


def build_graph(
    root: str = ".",
    out_dir: str = ".agent/graph",
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    start_time = time.time()
    norm_root = os.path.abspath(root)
    out_path = os.path.abspath(out_dir) if os.path.isabs(out_dir) else os.path.join(norm_root, out_dir)
    graph_json_path = os.path.join(out_path, "graph.json")
    meta_json_path = os.path.join(out_path, "meta.json")

    files = collect_files(norm_root, include=include, exclude=exclude)
    entrypoints = find_entrypoints_from_pyproject(norm_root)
    context = {"entrypoints": sorted(entrypoints)}

    # Check for incremental build cache
    cached_meta: dict[str, Any] | None = None
    cached_graph: Graph | None = None
    if not force and os.path.isfile(meta_json_path) and os.path.isfile(graph_json_path):
        try:
            cached_meta = textio.read_json(meta_json_path, what="meta")
            cached_graph = Graph.load(graph_json_path)
        except Exception:
            cached_meta = None
            cached_graph = None

    py_extractor = PythonExtractor()
    generic_extractor = GenericExtractor()

    file_fingerprints: dict[str, tuple[int, int]] = {}  # rel -> (size, mtime_ns)
    for rel in files:
        abs_p = os.path.join(norm_root, rel)
        try:
            st = os.stat(abs_p)
            file_fingerprints[rel] = (st.st_size, st.st_mtime_ns)
        except OSError:
            pass

    old_fingerprints = cached_meta.get("fingerprints", {}) if cached_meta else {}

    graph = Graph()
    extractor_counts: dict[str, int] = {"python": 0, "generic": 0}
    file_extractors: dict[str, str] = {}

    # File nodes & edges
    for rel in files:
        abs_p = os.path.join(norm_root, rel)
        if not os.path.isfile(abs_p):
            continue

        ext = os.path.splitext(rel)[1].lower()
        extractor_type = "python" if ext == ".py" else "generic"
        extractor_counts[extractor_type] = extractor_counts.get(extractor_type, 0) + 1
        file_extractors[rel] = extractor_type

        # Check if we can reuse cached nodes/edges for this file
        can_reuse = (
            cached_graph is not None
            and not force
            and rel in old_fingerprints
            and old_fingerprints[rel] == list(file_fingerprints.get(rel, ()))
        )

        if can_reuse:
            # Copy nodes and edges belonging to this file from cached_graph
            for n_id, node in cached_graph.nodes.items():
                if n_id == rel or n_id.startswith(f"{rel}::"):
                    graph.add_node(node)
            for edge in cached_graph.edges:
                if edge.source == rel or edge.source.startswith(f"{rel}::"):
                    graph.add_edge(edge)
        else:
            try:
                text = textio.read_text(abs_p)
            except Exception:
                continue

            if extractor_type == "python":
                nodes, edges = py_extractor.extract(rel, text, project_context=context)
            else:
                nodes, edges = generic_extractor.extract(rel, text, project_context=context)

            for n in nodes:
                graph.add_node(n)
            for e in edges:
                graph.add_edge(e)

    # Post-processing: resolve heuristic tests edges `name:<name>` to real function nodes
    # and resolve in-repo import paths
    symbol_name_to_ids: dict[str, list[str]] = {}
    repo_py_files: set[str] = {f for f in files if f.endswith(".py")}

    for node in graph.nodes.values():
        if node.kind in ("function", "class"):
            # function name or Class.method
            leaf = node.name.split(".")[-1]
            symbol_name_to_ids.setdefault(leaf, []).append(node.id)

    updated_edges: list[Edge] = []
    unresolved_calls = 0

    for edge in graph.edges:
        if edge.kind == "tests" and edge.target.startswith("name:"):
            target_name = edge.target[5:]
            if target_name in symbol_name_to_ids:
                # Resolve to first matching in-repo symbol (or prefer tested module)
                matches = symbol_name_to_ids[target_name]
                matched_id = matches[0]
                updated_edges.append(
                    Edge(
                        source=edge.source,
                        target=matched_id,
                        kind="tests",
                        source_type="name",
                        where=edge.where,
                        context=edge.context,
                    )
                )
            else:
                updated_edges.append(edge)
        elif edge.kind == "imports" and edge.target.startswith("ext:"):
            mod = edge.target[4:]
            cand_rel = mod.replace(".", "/") + ".py"
            cand_pkg = mod.replace(".", "/") + "/__init__.py"
            if cand_rel in repo_py_files:
                updated_edges.append(
                    Edge(
                        source=edge.source,
                        target=cand_rel,
                        kind="imports",
                        source_type="static",
                        where=edge.where,
                        context=edge.context,
                    )
                )
            elif cand_pkg in repo_py_files:
                updated_edges.append(
                    Edge(
                        source=edge.source,
                        target=cand_pkg,
                        kind="imports",
                        source_type="static",
                        where=edge.where,
                        context=edge.context,
                    )
                )
            else:
                updated_edges.append(edge)
        else:
            if edge.kind == "calls" and edge.target.startswith("unresolved:"):
                unresolved_calls += 1
            updated_edges.append(edge)

    graph.edges = updated_edges

    # Deterministic sha256
    graph_sha256 = graph.compute_sha256()
    wall_time = round(time.time() - start_time, 3)

    # Save graph.json
    written_graph = graph.save(graph_json_path)

    # Meta
    meta_data = {
        "root": os.path.relpath(norm_root, norm_root).replace("\\", "/") or ".",
        "extractor_versions": EXTRACTOR_VERSIONS,
        "file_count": len(files),
        "sha256": graph_sha256,
        "wall_time_s": wall_time,
        "extractors": extractor_counts,
        "fingerprints": {rel: list(fp) for rel, fp in file_fingerprints.items()},
    }
    written_meta = textio.write_text(meta_json_path, json.dumps(meta_data, indent=2, sort_keys=True))

    nodes_by_kind: dict[str, int] = {}
    for n in graph.nodes.values():
        nodes_by_kind[n.kind] = nodes_by_kind.get(n.kind, 0) + 1

    edges_by_kind: dict[str, int] = {}
    for e in graph.edges:
        edges_by_kind[e.kind] = edges_by_kind.get(e.kind, 0) + 1

    return {
        "ok": True,
        "root": os.path.relpath(norm_root, os.getcwd()).replace("\\", "/") or ".",
        "files": len(files),
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "nodes_by_kind": nodes_by_kind,
        "edges_by_kind": edges_by_kind,
        "unresolved_calls": unresolved_calls,
        "extractors": extractor_counts,
        "sha256": graph_sha256,
        "written": [written_graph, written_meta],
    }
