"""Query engine for the code graph: summary, node, refs, path, cycles, changed, and export."""
from __future__ import annotations
from collections import deque
import json
import os
import sys
from typing import Any

from .model import Edge, Graph, Node
from .. import proc, textio


class GraphError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class GraphNotFoundError(GraphError):
    def __init__(self, path: str) -> None:
        super().__init__(
            f"graph file not found: {path}",
            hint="run `ad-graph build` to generate the code graph",
        )


class AmbiguousNodeError(GraphError):
    def __init__(self, target: str, candidates: list[str]) -> None:
        c_str = ", ".join(candidates[:5])
        if len(candidates) > 5:
            c_str += f", ... ({len(candidates)} total)"
        super().__init__(
            f"ambiguous node target '{target}' matches multiple nodes: {c_str}",
            hint="specify the exact full node ID (e.g. relpath::function_or_method)",
        )
        self.candidates = candidates


class NodeNotFoundError(GraphError):
    def __init__(self, target: str) -> None:
        super().__init__(
            f"node not found in graph: '{target}'",
            hint="check `ad-graph summary` or provide valid file/symbol ID",
        )


def load_graph(root: str = ".", graph_dir: str = ".agent/graph") -> tuple[Graph, dict[str, Any]]:
    """Loads graph.json and meta.json or raises GraphNotFoundError."""
    norm_root = os.path.abspath(root)
    out_dir = os.path.abspath(graph_dir) if os.path.isabs(graph_dir) else os.path.join(norm_root, graph_dir)
    g_path = os.path.join(out_dir, "graph.json")
    m_path = os.path.join(out_dir, "meta.json")

    if not os.path.isfile(g_path):
        raise GraphNotFoundError(g_path)

    graph = Graph.load(g_path)
    meta = textio.read_json(m_path, what="meta") if os.path.isfile(m_path) else {}

    # Load coverage if present
    cov_path = os.path.join(out_dir, "coverage.json")
    if os.path.isfile(cov_path):
        try:
            cov = textio.read_json(cov_path, what="coverage")
            graph.coverage = cov
            # Annotate nodes with coverage
            nodes_cov = cov.get("nodes", {})
            for nid, node in graph.nodes.items():
                if nid in nodes_cov:
                    cdata = nodes_cov[nid]
                    node.coverage_pct = cdata.get("pct")
                    node.covered = (node.coverage_pct is not None and node.coverage_pct > 0)
                    if "tests" in cdata:
                        node.tests = sorted(list(set(node.tests + cdata["tests"])))
        except Exception:
            pass

    return graph, meta


def find_node(graph: Graph, target: str) -> Node:
    """Finds a single node by ID, path, or name, raising an error if missing or ambiguous."""
    # 1. Exact match
    if target in graph.nodes:
        return graph.nodes[target]

    # 2. Match by exact symbol name or suffix
    exact_name_matches: list[Node] = []
    suffix_matches: list[Node] = []

    for node in graph.nodes.values():
        if node.name == target:
            exact_name_matches.append(node)
        elif node.id.endswith(f"::{target}"):
            suffix_matches.append(node)
        elif node.id == target.replace("\\", "/"):
            return node

    candidates = exact_name_matches or suffix_matches
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        raise AmbiguousNodeError(target, [n.id for n in candidates])

    # 3. Substring match
    sub_matches = [node for node in graph.nodes.values() if target in node.id]
    if len(sub_matches) == 1:
        return sub_matches[0]
    elif len(sub_matches) > 1:
        raise AmbiguousNodeError(target, [n.id for n in sub_matches])

    raise NodeNotFoundError(target)


def get_summary(graph: Graph, meta: dict[str, Any], top: int = 20) -> list[dict[str, Any]]:
    """Calculates summary tables of directory distribution, entrypoints, hubs, fanout, cycles, and test stats."""
    records: list[dict[str, Any]] = []

    # 1. Directories
    dir_stats: dict[str, dict[str, Any]] = {}
    file_nodes = [n for n in graph.nodes.values() if n.kind == "file"]
    for fn in file_nodes:
        parts = fn.id.split("/")
        top_dir = parts[0] if len(parts) > 1 else "."
        stat = dir_stats.setdefault(top_dir, {"files": 0, "loc": 0, "extractors": {}})
        stat["files"] += 1
        stat["loc"] += fn.loc
        ext = "python" if fn.id.endswith(".py") else "generic"
        stat["extractors"][ext] = stat["extractors"].get(ext, 0) + 1

    for dname, dstat in sorted(dir_stats.items()):
        dom = max(dstat["extractors"].items(), key=lambda x: x[1])[0] if dstat["extractors"] else "generic"
        records.append({
            "section": "directory",
            "name": dname,
            "metric": f"files={dstat['files']}, loc={dstat['loc']}",
            "detail": f"extractor={dom}",
        })

    # 2. Entrypoints
    entrypoints = [n for n in graph.nodes.values() if "entrypoint" in n.tags]
    for ep in entrypoints[:top]:
        records.append({
            "section": "entrypoint",
            "name": ep.id,
            "metric": f"kind={ep.kind}",
            "detail": ep.where,
        })

    # 3. Highest fan-in (hubs)
    fan_in_counts: dict[str, int] = {}
    fan_out_counts: dict[str, int] = {}
    for e in graph.edges:
        if e.kind in ("calls", "imports"):
            fan_in_counts[e.target] = fan_in_counts.get(e.target, 0) + 1
            fan_out_counts[e.source] = fan_out_counts.get(e.source, 0) + 1

    sorted_fan_in = sorted(
        [(nid, cnt) for nid, cnt in fan_in_counts.items() if nid in graph.nodes],
        key=lambda x: x[1],
        reverse=True,
    )
    for nid, cnt in sorted_fan_in[:top]:
        node = graph.nodes[nid]
        records.append({
            "section": "hub_fan_in",
            "name": nid,
            "metric": f"fan_in={cnt}",
            "detail": node.where,
        })

    # 4. Highest fan-out
    sorted_fan_out = sorted(
        [(nid, cnt) for nid, cnt in fan_out_counts.items() if nid in graph.nodes],
        key=lambda x: x[1],
        reverse=True,
    )
    for nid, cnt in sorted_fan_out[:top]:
        node = graph.nodes[nid]
        records.append({
            "section": "hub_fan_out",
            "name": nid,
            "metric": f"fan_out={cnt}",
            "detail": node.where,
        })

    # 5. Cycles (imports)
    cycles = get_cycles(graph)
    records.append({
        "section": "cycles",
        "name": "import_cycles",
        "metric": f"count={len(cycles)}",
        "detail": " -> ".join(cycles[0]) if cycles else "none",
    })
    for cyc in cycles[:3]:
        records.append({
            "section": "cycle_sample",
            "name": "cycle",
            "metric": f"len={len(cyc)}",
            "detail": " -> ".join(cyc),
        })

    # 6. IO nodes grouped by module
    io_nodes = [n for n in graph.nodes.values() if "io" in n.tags]
    io_by_module: dict[str, list[str]] = {}
    for ion in io_nodes:
        mod = ion.id.split("::")[0]
        io_by_module.setdefault(mod, []).append(ion.name)

    for mod, fns in sorted(io_by_module.items())[:top]:
        records.append({
            "section": "io_nodes",
            "name": mod,
            "metric": f"count={len(fns)}",
            "detail": ", ".join(fns[:5]),
        })

    # 7. Test coverage ratio
    fn_nodes = [n for n in graph.nodes.values() if n.kind == "function"]
    if graph.coverage:
        tested_functions = {n.id for n in fn_nodes if n.covered or (n.coverage_pct is not None and n.coverage_pct > 0)}
    else:
        tested_functions = set()
        for e in graph.edges:
            if e.kind == "tests" and e.target in graph.nodes:
                tested_functions.add(e.target)

    test_count = len([n for n in graph.nodes.values() if n.kind == "test"])
    tested_ratio = (len(tested_functions) / max(1, len(fn_nodes))) if fn_nodes else 0.0

    records.append({
        "section": "test_stats",
        "name": "functions",
        "metric": f"total={len(fn_nodes)}, tested={len(tested_functions)}",
        "detail": f"tested_ratio={tested_ratio:.1%}, test_nodes={test_count}",
    })

    return records


def get_node_details(graph: Graph, target: str) -> dict[str, Any]:
    node = find_node(graph, target)

    callers = [e for e in graph.callers_of(node.id)]
    callees = [e for e in graph.callees_of(node.id)]

    # Tests linking to this node
    tests = [e.source for e in graph.edges if e.kind == "tests" and e.target == node.id]
    if node.tests:
        tests = sorted(list(set(tests + node.tests)))

    return {
        "id": node.id,
        "kind": node.kind,
        "name": node.name,
        "where": node.where,
        "sha": node.sha,
        "loc": node.loc,
        "complexity": node.complexity,
        "tags": node.tags,
        "callers": [c.source for c in callers],
        "callees": [c.target for c in callees],
        "tests": tests,
        "covered": node.covered,
        "coverage_pct": node.coverage_pct,
    }


def get_refs(graph: Graph, target: str, depth: int = 3, reverse: bool = False) -> list[dict[str, Any]]:
    """Transitive caller (or callee if reverse) blast radius up to depth."""
    start_node = find_node(graph, target)
    visited: set[str] = {start_node.id}
    queue: deque[tuple[str, int]] = deque([(start_node.id, 0)])

    results: list[dict[str, Any]] = []

    while queue:
        curr_id, curr_depth = queue.popleft()
        if curr_depth >= depth:
            continue

        if reverse:
            edges = [e for e in graph.edges if e.source == curr_id and e.kind in ("calls", "imports")]
            for e in edges:
                if e.target not in visited:
                    visited.add(e.target)
                    queue.append((e.target, curr_depth + 1))
                    results.append({
                        "source": curr_id,
                        "target": e.target,
                        "depth": curr_depth + 1,
                        "kind": e.kind,
                        "where": e.where or (graph.nodes[e.target].where if e.target in graph.nodes else ""),
                    })
        else:
            edges = [e for e in graph.edges if e.target == curr_id and e.kind in ("calls", "imports")]
            for e in edges:
                if e.source not in visited:
                    visited.add(e.source)
                    queue.append((e.source, curr_depth + 1))
                    results.append({
                        "source": e.source,
                        "target": curr_id,
                        "depth": curr_depth + 1,
                        "kind": e.kind,
                        "where": e.where or (graph.nodes[e.source].where if e.source in graph.nodes else ""),
                    })

    return results


def find_paths(
    graph: Graph,
    from_target: str,
    to_target: str,
    all_paths: bool = False,
    max_paths: int = 5,
) -> list[list[str]]:
    """Finds shortest call/import path(s) between two nodes."""
    start_node = find_node(graph, from_target)
    end_node = find_node(graph, to_target)

    if start_node.id == end_node.id:
        return [[start_node.id]]

    # Adjacency map for calls and imports
    adj: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.kind in ("calls", "imports"):
            adj.setdefault(e.source, []).append(e.target)

    # BFS for shortest paths
    queue: deque[list[str]] = deque([[start_node.id]])
    paths: list[list[str]] = []
    shortest_len = None

    while queue:
        curr_path = queue.popleft()
        curr_node = curr_path[-1]

        if shortest_len is not None and len(curr_path) > shortest_len:
            break

        if curr_node == end_node.id:
            paths.append(curr_path)
            if not all_paths:
                return paths
            if shortest_len is None:
                shortest_len = len(curr_path)
            if len(paths) >= max_paths:
                break
            continue

        for neighbor in adj.get(curr_node, []):
            if neighbor not in curr_path:  # avoid cycles
                queue.append(curr_path + [neighbor])

    return paths


def get_cycles(graph: Graph) -> list[list[str]]:
    """Detects cycles on import and call edges, returning unique simple cycles sorted by length."""
    adj: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.kind == "imports":
            adj.setdefault(e.source, []).append(e.target)

    # Simple cycle detection using DFS
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: list[str] = []

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.append(node)

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                cycle_start = rec_stack.index(neighbor)
                cycle = rec_stack[cycle_start:] + [neighbor]
                # Normalize cycle representation (start with min element)
                min_idx = cycle[:-1].index(min(cycle[:-1]))
                normalized = cycle[:-1][min_idx:] + cycle[:-1][:min_idx] + [cycle[:-1][min_idx]]
                if normalized not in cycles:
                    cycles.append(normalized)

        rec_stack.pop()

    for node_id in sorted(graph.nodes):
        if node_id not in visited:
            dfs(node_id)

    cycles.sort(key=lambda c: (len(c), c))
    return cycles


def get_changed(
    graph: Graph,
    meta: dict[str, Any],
    since_ref: str | None = None,
    root: str = ".",
) -> list[dict[str, Any]]:
    """Detects nodes whose sha differs or whose file appears in git diff --name-only."""
    norm_root = os.path.abspath(root)
    diff_files: set[str] = set()

    if since_ref:
        try:
            # proc.run returns a tuple, not a record: unpacking it is the difference between this
            # working and the AttributeError below silently making --since match nothing
            rc, out, _err, _el = proc.run(["git", "diff", "--name-only", since_ref], cwd=norm_root, timeout=10)
            if rc == 0:
                diff_files = {line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()}
        except Exception:
            pass

    changed: list[dict[str, Any]] = []

    for node in graph.nodes.values():
        parts = node.id.split("::")
        rel_file = parts[0]

        if rel_file in diff_files:
            changed.append({
                "id": node.id,
                "kind": node.kind,
                "where": node.where,
                "reason": f"git diff against {since_ref}",
            })
            continue

        # Check file stat against meta fingerprints if available
        abs_p = os.path.join(norm_root, rel_file)
        if not os.path.isfile(abs_p):
            changed.append({
                "id": node.id,
                "kind": node.kind,
                "where": node.where,
                "reason": "file missing on disk",
            })
            continue

        try:
            st = os.stat(abs_p)
            fp = [st.st_size, st.st_mtime_ns]
            old_fp = meta.get("fingerprints", {}).get(rel_file)
            if old_fp and old_fp != fp:
                changed.append({
                    "id": node.id,
                    "kind": node.kind,
                    "where": node.where,
                    "reason": "file modified on disk",
                })
        except OSError:
            pass

    return changed


def export_graph(graph: Graph, fmt: str, out_path: str, graph_dir: str = ".agent/graph") -> str:
    """Exports graph to DOT or JSON under .agent/graph/."""
    norm_out = os.path.abspath(out_path)
    norm_dir = os.path.abspath(graph_dir)

    # Must be under .agent/graph/
    if not norm_out.startswith(norm_dir):
        raise GraphError(
            f"export path must be inside {graph_dir}",
            hint=f"provide a path like {graph_dir}/export.{fmt}",
        )

    if fmt == "json":
        data = graph.to_dict()
        text = json.dumps(data, indent=2, sort_keys=True)
    elif fmt == "dot":
        lines = ["digraph CodeGraph {", '  rankdir="LR";']
        for node in sorted(graph.nodes.values(), key=lambda n: n.id):
            label = f"{node.name}\\n({node.kind})"
            lines.append(f'  "{node.id}" [label="{label}", shape="box"];')
        for e in sorted(graph.edges, key=lambda e: e.sort_key()):
            lines.append(f'  "{e.source}" -> "{e.target}" [label="{e.kind}"];')
        lines.append("}")
        text = "\n".join(lines) + "\n"
    else:
        raise GraphError(f"unsupported format: {fmt}", hint="format must be dot or json")

    return textio.write_text(norm_out, text)
