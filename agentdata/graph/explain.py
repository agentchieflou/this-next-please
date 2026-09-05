"""`ad-graph explain` — generate deterministic codebase understanding skeleton."""
from __future__ import annotations
import collections
import os
import re
from typing import Any

from .model import Graph, Node
from .query import get_cycles, load_graph
from .. import textio

# a symbol with at least this many distinct callers is a "hub". One definition, used by the Modules,
# Hubs and Tests sections alike -- when these drifted apart a module row said "hubs: none" while the
# Hubs section listed three of its symbols.
HUB_MIN_CALLERS = 1
# every fact line ends in an id `ad-graph node` resolves. Repo-wide aggregates ("0 hubs", "tested_ratio")
# are about no single node, so they carry this sentinel instead -- it is deliberately not a node id.
ROOT_ANCHOR = "root"
SECTIONS = (
    "Entrypoints",
    "Modules",
    "Hubs",
    "Data and side effects",
    "Tests",
    "Cycles",
    "Open questions",
)


def parse_model_blocks(content: str) -> dict[str, str]:
    """Extract model comments under <!-- model --> ... <!-- /model --> keyed by section title."""
    blocks: dict[str, str] = {}
    if not content:
        return blocks

    # Match each ## Section up to next ## or end of file
    sections = re.split(r"(?m)^##\s+", content)
    for s in sections[1:]:
        lines = s.splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        sec_body = "\n".join(lines[1:])
        m = re.search(r"<!-- model -->([\s\S]*?)<!-- /model -->", sec_body)
        if m:
            blocks[title] = m.group(1).strip("\r\n")

    return blocks


def _format_model_block(text: str) -> str:
    if text and text.strip():
        return f"\n<!-- model -->\n{text.strip()}\n<!-- /model -->\n"
    return "\n<!-- model -->\n<!-- /model -->\n"


def _find_shortest_io_path(graph: Graph, start_id: str) -> list[str] | None:
    """BFS to find the shortest call path from start_id to any node tagged with 'io'."""
    io_node_ids = {nid for nid, n in graph.nodes.items() if "io" in n.tags}
    if start_id in io_node_ids:
        return [start_id]

    queue = collections.deque([[start_id]])
    visited = {start_id}

    while queue:
        path = queue.popleft()
        cur = path[-1]
        for edge in graph.edges:
            if edge.source == cur and edge.kind == "calls":
                nxt = edge.target
                if nxt in io_node_ids:
                    return path + [nxt]
                if nxt in graph.nodes and nxt not in visited:
                    visited.add(nxt)
                    queue.append(path + [nxt])

    return None


def _fact(text: str, anchor: str) -> str:
    """One fact bullet ending in the node id a reviewer can paste into `ad-graph node`.

    The anchor is appended only when the sentence does not already end with it, so a line about a
    single node reads `- \\`app.py::main\\`: 3 callers` rather than naming it twice.
    """
    suffix = f"`{anchor}`"
    if text.rstrip().endswith(suffix):
        return f"- {text.rstrip()}"
    return f"- {text.rstrip()} {suffix}"


def _module_of(node: Node) -> str:
    """Top-level directory, or the bare file stem for a file at the repo root."""
    parts = node.path.split("/")
    if len(parts) > 1:
        return parts[0]
    stem = parts[0]
    return stem[: -len(".py")] if stem.endswith(".py") else stem.rsplit(".", 1)[0] or stem


def generate_understanding(graph: Graph, meta: dict[str, Any], existing_content: str | None = None) -> str:
    """Generate the skeleton understanding document from graph facts, preserving model notes."""
    model_blocks = parse_model_blocks(existing_content or "")

    graph_sha = meta.get("sha256", "unknown")
    sections: list[str] = []

    # Front matter
    sections.append(f"""---
graph_sha256: "{graph_sha}"
---

# Codebase Understanding
""")

    # 1. ## Entrypoints
    ep_title = "Entrypoints"
    ep_lines = []
    entrypoint_ids = {nid for nid in meta.get("entrypoints") or [] if nid in graph.nodes}
    entrypoint_ids |= {nid for nid, node in graph.nodes.items() if "entrypoint" in node.tags}

    # A file whose `main` is itself tagged is represented by that symbol: the file node has no call
    # edges of its own, so keeping both only ever produced a "no call path to IO" line next to the
    # real one.
    symbol_paths = {graph.nodes[nid].path for nid in entrypoint_ids if graph.nodes[nid].kind != "file"}
    entrypoint_ids = {
        nid for nid in entrypoint_ids
        if graph.nodes[nid].kind != "file" or graph.nodes[nid].path not in symbol_paths
    }

    if entrypoint_ids:
        for ep_id in sorted(entrypoint_ids):
            io_path = _find_shortest_io_path(graph, ep_id)
            if io_path and len(io_path) > 1:
                route = " -> ".join(f"`{step}`" for step in io_path)
                ep_lines.append(_fact(f"Entrypoint `{ep_id}` reaches IO via {route}", io_path[-1]))
            else:
                ep_lines.append(_fact(f"Entrypoint `{ep_id}`: no call path to an IO node", ep_id))
    else:
        ep_lines.append("- No explicit entrypoints found `root`")

    ep_section = "## " + ep_title + "\n\n" + "\n".join(ep_lines) + "\n" + _format_model_block(model_blocks.get(ep_title, ""))
    sections.append(ep_section)

    # 2. ## Modules
    mod_title = "Modules"
    modules: dict[str, list[Node]] = collections.defaultdict(list)
    for node in graph.nodes.values():
        modules[_module_of(node)].append(node)

    # Compute in-degrees (callers count) for hubs
    callers: dict[str, set[str]] = collections.defaultdict(set)
    for edge in graph.edges:
        if edge.kind == "calls" and edge.target in graph.nodes:
            callers[edge.target].add(edge.source)

    def _hub_rank(node_id: str) -> tuple[int, str]:
        return (-len(callers.get(node_id, set())), node_id)

    def _is_hub(node: Node) -> bool:
        return node.kind in ("function", "class") and len(callers.get(node.id, set())) >= HUB_MIN_CALLERS

    # meta["extractors"] is {extractor: file_count}; the per-file mapping is what a module row needs.
    file_extractors: dict[str, str] = meta.get("file_extractors") or {}

    mod_lines = []
    for mod_name in sorted(modules):
        nodes_in_mod = modules[mod_name]
        files = sorted({n.path for n in nodes_in_mod})
        # LOC comes off the file nodes; summing symbols instead undercounts module-level code and
        # reported 0 for a tests/ directory whose nodes are all kind "test".
        file_locs = {n.path: n.loc for n in nodes_in_mod if n.kind == "file"}
        tot_loc = sum(file_locs.values()) or sum(n.loc for n in nodes_in_mod if n.kind != "file")
        mod_hubs = sorted((n.id for n in nodes_in_mod if _is_hub(n)), key=_hub_rank)
        hubs_str = ", ".join(f"`{h}`" for h in mod_hubs[:3]) if mod_hubs else "none"
        exts = sorted({file_extractors.get(f, "generic") for f in files}) or ["generic"]
        ext_str = ", ".join(f"`{e}`" for e in exts)
        # the anchor is a file node, not the bare module name: a module is a grouping, so naming it
        # would give the reviewer an id `ad-graph node` cannot resolve.
        mod_lines.append(_fact(
            f"**{mod_name}**: {len(files)} file{'' if len(files) == 1 else 's'}, {tot_loc} LOC, "
            f"hubs: {hubs_str}, extractor: {ext_str}",
            files[0] if files else "root",
        ))

    if not mod_lines:
        mod_lines.append("- No modules found `root`")

    mod_section = "## " + mod_title + "\n\n" + "\n".join(mod_lines) + "\n" + _format_model_block(model_blocks.get(mod_title, ""))
    sections.append(mod_section)

    # 3. ## Hubs
    hub_title = "Hubs"
    # Sort all nodes by callers count descending
    hub_candidates = [
        (nid, len(callers.get(nid, set())))
        for nid in sorted(graph.nodes)
        if _is_hub(graph.nodes[nid])
    ]
    hub_candidates.sort(key=lambda x: (-x[1], x[0]))

    hub_lines = []
    top_hubs = hub_candidates[:15]
    if top_hubs:
        for nid, count in top_hubs:
            n = graph.nodes[nid]
            plural = "caller" if count == 1 else "callers"
            hub_lines.append(_fact(f"{count} {plural}, {n.kind} at `{n.where}` — ", nid))
    else:
        hub_lines.append("- No hubs detected `root`")

    hub_section = "## " + hub_title + "\n\n" + "\n".join(hub_lines) + "\n" + _format_model_block(model_blocks.get(hub_title, ""))
    sections.append(hub_section)

    # 4. ## Data and side effects
    io_title = "Data and side effects"
    io_nodes = [n for n in graph.nodes.values() if "io" in n.tags]
    io_lines = []
    if io_nodes:
        by_module: dict[str, list[Node]] = collections.defaultdict(list)
        for n in io_nodes:
            by_module[_module_of(n)].append(n)
        for mod_name in sorted(by_module):
            for n in sorted(by_module[mod_name], key=lambda x: x.id):
                tags_str = ", ".join(sorted(n.tags))
                io_lines.append(_fact(f"**{mod_name}** · {tags_str} at `{n.where}` — ", n.id))
    else:
        io_lines.append("- No IO-tagged nodes identified `root`")

    io_section = "## " + io_title + "\n\n" + "\n".join(io_lines) + "\n" + _format_model_block(model_blocks.get(io_title, ""))
    sections.append(io_section)

    # 5. ## Tests
    test_title = "Tests"
    fn_nodes = [n for n in graph.nodes.values() if n.kind == "function"]
    if graph.coverage:
        tested_fns = {n.id for n in fn_nodes if n.covered or (n.coverage_pct is not None and n.coverage_pct > 0)}
    else:
        tested_fns = set()
        for e in graph.edges:
            if e.kind == "tests" and e.target in graph.nodes:
                tested_fns.add(e.target)

    test_ratio = (len(tested_fns) / max(1, len(fn_nodes))) if fn_nodes else 0.0
    test_lines = [
        f"- tested_ratio: {test_ratio * 100.0:.1f}% ({len(tested_fns)} of {len(fn_nodes)} functions) `root`"
    ]

    # Untested hubs by name
    untested_hubs = [
        nid for nid, _count in hub_candidates
        if nid not in tested_fns and not graph.nodes[nid].covered
    ]
    if untested_hubs:
        for uh in untested_hubs[:10]:
            test_lines.append(_fact(f"Untested hub: `{uh}`", uh))
    else:
        test_lines.append("- Untested hubs: none `root`")

    test_section = "## " + test_title + "\n\n" + "\n".join(test_lines) + "\n" + _format_model_block(model_blocks.get(test_title, ""))
    sections.append(test_section)

    # 6. ## Cycles
    cycles_title = "Cycles"
    cycles = get_cycles(graph)
    cycle_lines = []
    if cycles:
        for idx, c in enumerate(cycles[:10]):
            c_str = " -> ".join(f"`{step}`" for step in c)
            cycle_lines.append(_fact(f"Cycle {idx + 1}: {c_str}", c[0]))
    else:
        cycle_lines.append("- No cycles detected `root`")

    cycle_section = "## " + cycles_title + "\n\n" + "\n".join(cycle_lines) + "\n" + _format_model_block(model_blocks.get(cycles_title, ""))
    sections.append(cycle_section)

    # 7. ## Open questions
    oq_title = "Open questions"
    oq_lines = []
    # Identify unresolved calls or generic extractors
    unresolved_calls = [
        e for e in graph.edges
        if e.kind == "calls" and (e.target.startswith("name:") or e.target.startswith("ext:") or e.context.get("unresolved"))
    ]
    if unresolved_calls:
        for uc in sorted(unresolved_calls, key=lambda e: (e.source, e.target))[:10]:
            oq_lines.append(_fact(
                f"Unresolved call `{uc.source}` -> `{uc.target}` — confirm what it resolves to",
                uc.source,
            ))

    # Files no language extractor understood: their symbols and calls are a plain-text guess, so a
    # reviewer has to confirm them by hand.
    for rel in sorted(f for f, ext in file_extractors.items() if ext == "generic"):
        oq_lines.append(_fact(
            f"`{rel}` was read by the `generic` extractor — confirm its symbols and calls",
            rel,
        ))

    if not oq_lines:
        oq_lines.append("- None `root`")

    oq_section = "## " + oq_title + "\n\n" + "\n".join(oq_lines) + "\n" + _format_model_block(model_blocks.get(oq_title, ""))
    sections.append(oq_section)

    return "\n".join(sections) + "\n"


def explain_graph(
    root: str = ".",
    out_file: str | None = None,
    graph_dir: str = ".agent/graph",
) -> dict[str, Any]:
    """Generate or update understanding.md from graph facts."""
    root = os.path.abspath(root)
    graph, meta = load_graph(root, graph_dir=graph_dir)

    out_path = out_file or os.path.join(graph_dir, "understanding.md")
    if not os.path.isabs(out_path):
        out_path = os.path.join(root, out_path)

    existing_content: str | None = None
    if os.path.isfile(out_path):
        existing_content = textio.read_text(out_path)

    doc = generate_understanding(graph, meta, existing_content=existing_content)
    textio.write_text(out_path, doc)

    return {
        "ok": True,
        "path": out_path,
        "rel_path": textio.norm_path(os.path.relpath(out_path, root)),
        "graph_sha256": meta.get("sha256", ""),
        "sections": list(SECTIONS),
    }
