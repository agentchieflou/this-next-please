# PYTHON_ARGCOMPLETE_OK
"""Command-line interface for `ad-graph` — code graph extraction, queries, approval, and guard."""
from __future__ import annotations
import argparse
import os
import sys
from typing import Sequence

from . import completion
from . import policy
from . import ui
from .console import utf8_stdout
from .graph import approval
from .graph import builder
from .graph import explain
from .graph import query
from .model import AgentTable
from .policy import error, render
from .version import version_string


def _get_root(a: argparse.Namespace) -> str:
    return getattr(a, "root_flag", None) or getattr(a, "root", None) or "."


def cmd_build(a: argparse.Namespace) -> int:
    try:
        res = builder.build_graph(
            root=_get_root(a),
            out_dir=a.out or ".agent/graph",
            include=a.include,
            exclude=a.exclude,
            force=a.force,
        )
        rows: list[dict[str, str]] = [
            {"metric": "root", "value": str(res["root"])},
            {"metric": "files", "value": str(res["files"])},
            {"metric": "nodes", "value": str(res["nodes"])},
            {"metric": "edges", "value": str(res["edges"])},
            {"metric": "unresolved_calls", "value": str(res["unresolved_calls"])},
            {"metric": "sha256", "value": str(res["sha256"])},
        ]
        for k, v in sorted(res["nodes_by_kind"].items()):
            rows.append({"metric": f"nodes.{k}", "value": str(v)})
        for k, v in sorted(res["edges_by_kind"].items()):
            rows.append({"metric": f"edges.{k}", "value": str(v)})
        for k, v in sorted(res["extractors"].items()):
            rows.append({"metric": f"extractor.{k}", "value": str(v)})
        for p in res["written"]:
            rows.append({"metric": "written", "value": str(p)})

        t = AgentTable.from_records(rows, name="graph_build", source="ad-graph build")
        extra = {
            "ok": True,
            "source": "ad-graph build",
            "root": res["root"],
            "files": res["files"],
            "sha256": res["sha256"],
        }
        print(render(t, extra=extra))
        return 0
    except Exception as e:
        print(error(str(e), "check directory path or permissions", "ad-graph build"))
        return 1


def cmd_summary(a: argparse.Namespace) -> int:
    try:
        graph, meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        records = query.get_summary(graph, meta, top=a.top)
        t = AgentTable.from_records(records, name="summary", source="ad-graph summary")
        print(render(t, extra={"ok": True, "source": "ad-graph summary", "nodes": len(graph.nodes)}))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph summary"))
        return 1


def cmd_node(a: argparse.Namespace) -> int:
    try:
        graph, _meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        info = query.get_node_details(graph, a.target)
        records = [
            {"property": "id", "value": info["id"]},
            {"property": "kind", "value": info["kind"]},
            {"property": "name", "value": info["name"]},
            {"property": "where", "value": info["where"]},
            {"property": "sha", "value": info["sha"]},
            {"property": "loc", "value": str(info["loc"])},
            {"property": "complexity", "value": str(info["complexity"])},
            {"property": "tags", "value": ", ".join(info["tags"]) if info["tags"] else "none"},
            {"property": "callers", "value": ", ".join(info["callers"]) if info["callers"] else "none"},
            {"property": "callees", "value": ", ".join(info["callees"]) if info["callees"] else "none"},
            {"property": "tests", "value": ", ".join(info["tests"]) if info["tests"] else "none"},
            {"property": "covered", "value": str(info["covered"]).lower() if info["covered"] is not None else "unknown"},
            {"property": "coverage_pct", "value": f"{info['coverage_pct']:.1f}%" if info["coverage_pct"] is not None else "unknown"},
        ]
        t = AgentTable.from_records(records, name="node", source="ad-graph node")
        print(render(t, extra={"ok": True, "source": "ad-graph node", "node_id": info["id"]}))
        return 0
    except query.AmbiguousNodeError as e:
        print(error(str(e), e.hint, "ad-graph node"))
        return 2
    except query.NodeNotFoundError as e:
        print(error(str(e), e.hint, "ad-graph node"))
        return 2
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph node"))
        return 1


def cmd_refs(a: argparse.Namespace) -> int:
    try:
        graph, _meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        records = query.get_refs(graph, a.target, depth=a.depth, reverse=a.reverse)
        t = AgentTable.from_records(records, name="refs", source="ad-graph refs")
        extra = {
            "ok": True,
            "source": "ad-graph refs",
            "target": a.target,
            "depth": a.depth,
            "reverse": a.reverse,
            "count": len(records),
        }
        print(render(t, extra=extra))
        return 0
    except query.AmbiguousNodeError as e:
        print(error(str(e), e.hint, "ad-graph refs"))
        return 2
    except query.NodeNotFoundError as e:
        print(error(str(e), e.hint, "ad-graph refs"))
        return 2
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph refs"))
        return 1


def cmd_path(a: argparse.Namespace) -> int:
    try:
        graph, _meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        paths = query.find_paths(graph, a.from_node, a.to_node, all_paths=a.all, max_paths=a.max)
        records = [
            {"path_index": idx + 1, "length": len(p), "route": " -> ".join(p)}
            for idx, p in enumerate(paths)
        ]
        t = AgentTable.from_records(records, name="path", source="ad-graph path")
        extra = {
            "ok": True,
            "source": "ad-graph path",
            "from": a.from_node,
            "to": a.to_node,
            "count": len(paths),
        }
        print(render(t, extra=extra))
        return 0
    except (query.AmbiguousNodeError, query.NodeNotFoundError) as e:
        print(error(str(e), e.hint, "ad-graph path"))
        return 2
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph path"))
        return 1


def cmd_cycles(a: argparse.Namespace) -> int:
    try:
        graph, _meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        cycles = query.get_cycles(graph)
        records = [
            {"cycle_id": idx + 1, "length": len(c), "cycle": " -> ".join(c)}
            for idx, c in enumerate(cycles)
        ]
        t = AgentTable.from_records(records, name="cycles", source="ad-graph cycles")
        print(render(t, extra={"ok": True, "source": "ad-graph cycles", "count": len(cycles)}))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph cycles"))
        return 1


def cmd_changed(a: argparse.Namespace) -> int:
    try:
        graph, meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        records = query.get_changed(graph, meta, since_ref=a.since, root=_get_root(a))
        t = AgentTable.from_records(records, name="changed", source="ad-graph changed")
        print(render(t, extra={"ok": True, "source": "ad-graph changed", "count": len(records)}))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph changed"))
        return 1


def cmd_export(a: argparse.Namespace) -> int:
    try:
        graph, _meta = query.load_graph(root=_get_root(a), graph_dir=a.graph_dir or ".agent/graph")
        out_p = query.export_graph(graph, a.format, a.out, graph_dir=a.graph_dir or ".agent/graph")
        records = [{"format": a.format, "out": out_p, "nodes": len(graph.nodes), "edges": len(graph.edges)}]
        t = AgentTable.from_records(records, name="export", source="ad-graph export")
        print(render(t, extra={"ok": True, "source": "ad-graph export", "path": out_p}))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph export"))
        return 1


def cmd_explain(a: argparse.Namespace) -> int:
    try:
        res = explain.explain_graph(
            root=_get_root(a),
            out_file=getattr(a, "out", None),
            graph_dir=a.graph_dir or ".agent/graph",
        )
        records = [{"section": s} for s in res["sections"]]
        t = AgentTable.from_records(records, name="explain", source="ad-graph explain")
        extra = {
            "ok": True,
            "source": "ad-graph explain",
            "path": res["rel_path"],
            "graph_sha256": res["graph_sha256"],
        }
        print(render(t, extra=extra))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph explain"))
        return 1
    except Exception as e:
        print(error(str(e), "check directory path or permissions", "ad-graph explain"))
        return 1


def cmd_approve(a: argparse.Namespace) -> int:
    try:
        res = approval.approve_graph(
            root=_get_root(a),
            graph_dir=a.graph_dir or ".agent/graph",
        )
        if not res.get("ok"):
            if res.get("cancelled"):
                print(error(res["error"], res["hint"], "ad-graph approve"))
                return 0
            print(error(res["error"], res["hint"], "ad-graph approve"))
            return res.get("exit_code", 3)

        records = [
            {"property": "approved", "value": "true"},
            {"property": "graph_sha256", "value": res["graph_sha256"]},
            {"property": "understanding_sha256", "value": res["understanding_sha256"]},
            {"property": "approved_by", "value": res["approved_by"]},
            {"property": "approved_at", "value": res["approved_at"]},
        ]
        t = AgentTable.from_records(records, name="approve", source="ad-graph approve")
        extra = {
            "ok": True,
            "source": "ad-graph approve",
            "approved": True,
            "graph_sha256": res["graph_sha256"],
        }
        print(render(t, extra=extra))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph approve"))
        return 1
    except Exception as e:
        print(error(str(e), "unexpected error during approval", "ad-graph approve"))
        return 1


def cmd_status(a: argparse.Namespace) -> int:
    try:
        res = approval.check_approval_status(
            root=_get_root(a),
            graph_dir=a.graph_dir or ".agent/graph",
        )
        records = [
            {"property": "status", "value": res["status"]},
            {"property": "approved", "value": str(res["approved"]).lower()},
            {"property": "graph_sha256", "value": res["graph_sha256"] or "none"},
            {"property": "approved_graph_sha256", "value": res.get("approved_graph_sha256") or "none"},
            {"property": "understanding_sha256", "value": res.get("understanding_sha256") or "none"},
            {"property": "approved_understanding_sha256", "value": res.get("approved_understanding_sha256") or "none"},
            {"property": "changed_nodes", "value": str(res.get("changed_nodes", 0))},
            {"property": "approved_at", "value": res.get("approved_at") or "none"},
            {"property": "approved_by", "value": res.get("approved_by") or "none"},
        ]
        t = AgentTable.from_records(records, name="status", source="ad-graph status")
        extra = {
            "ok": True,
            "source": "ad-graph status",
            "status": res["status"],
            "approved": res["approved"],
            "changed_nodes": res.get("changed_nodes", 0),
        }
        print(render(t, extra=extra))
        return 0
    except query.GraphError as e:
        print(error(str(e), e.hint, "ad-graph status"))
        return 1
    except Exception as e:
        print(error(str(e), "unexpected error checking status", "ad-graph status"))
        return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ad-graph",
        description="Code graph extraction, querying, approval, findings, and guarding.",
    )
    ap.add_argument("-v", "--version", action="version", version=version_string())
    ap.add_argument("--pretty", action="store_true", help="render rich tables")

    sub = ap.add_subparsers(dest="subcmd", required=True)

    # build
    p_b = sub.add_parser("build", help="extract deterministic graph into .agent/graph/")
    p_b.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_b.add_argument("--root", dest="root_flag", help="project root directory")
    p_b.add_argument("--out", default=".agent/graph", help="output directory (default: .agent/graph)")
    p_b.add_argument("--include", action="append", help="glob patterns to include")
    p_b.add_argument("--exclude", action="append", help="glob patterns to exclude")
    p_b.add_argument("--force", action="store_true", help="force rebuild ignoring cache")
    p_b.add_argument("--pretty", action="store_true", help="render rich table")
    p_b.set_defaults(fn=cmd_build)

    # summary
    p_s = sub.add_parser("summary", help="bounded TOON summary of directories, entrypoints, hubs, and cycles")
    p_s.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_s.add_argument("--root", dest="root_flag", help="project root directory")
    p_s.add_argument("--top", type=int, default=20, help="top items per section (default: 20)")
    p_s.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_s.add_argument("--pretty", action="store_true", help="render rich table")
    p_s.set_defaults(fn=cmd_summary)

    # node
    p_n = sub.add_parser("node", help="inspect details of a specific node")
    p_n.add_argument("target", help="node ID, name, or path")
    p_n.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_n.add_argument("--root", dest="root_flag", help="project root directory")
    p_n.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_n.add_argument("--pretty", action="store_true", help="render rich table")
    p_n.set_defaults(fn=cmd_node)

    # refs
    p_r = sub.add_parser("refs", help="transitive blast radius (callers or callees)")
    p_r.add_argument("target", help="node ID, name, or path")
    p_r.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_r.add_argument("--root", dest="root_flag", help="project root directory")
    p_r.add_argument("--depth", type=int, default=3, help="transitive depth limit (default: 3)")
    p_r.add_argument("--reverse", action="store_true", help="follow outgoing callees instead of incoming callers")
    p_r.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_r.add_argument("--pretty", action="store_true", help="render rich table")
    p_r.set_defaults(fn=cmd_refs)

    # path
    p_p = sub.add_parser("path", help="find shortest call/import path(s) between two nodes")
    p_p.add_argument("from_node", help="source node target")
    p_p.add_argument("to_node", help="destination node target")
    p_p.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_p.add_argument("--root", dest="root_flag", help="project root directory")
    p_p.add_argument("--all", action="store_true", help="find all shortest paths up to --max")
    p_p.add_argument("--max", type=int, default=5, help="maximum paths to return (default: 5)")
    p_p.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_p.add_argument("--pretty", action="store_true", help="render rich table")
    p_p.set_defaults(fn=cmd_path)

    # cycles
    p_c = sub.add_parser("cycles", help="find import and call cycles")
    p_c.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_c.add_argument("--root", dest="root_flag", help="project root directory")
    p_c.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_c.add_argument("--pretty", action="store_true", help="render rich table")
    p_c.set_defaults(fn=cmd_cycles)

    # changed
    p_ch = sub.add_parser("changed", help="detect nodes changed on disk or in git diff")
    p_ch.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_ch.add_argument("--root", dest="root_flag", help="project root directory")
    p_ch.add_argument("--since", help="git ref to compare against with git diff --name-only")
    p_ch.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_ch.add_argument("--pretty", action="store_true", help="render rich table")
    p_ch.set_defaults(fn=cmd_changed)

    # export
    p_e = sub.add_parser("export", help="export graph to DOT or JSON under .agent/graph/")
    p_e.add_argument("--format", required=True, choices=["dot", "json"], help="export format")
    p_e.add_argument("--out", required=True, help="output file path under .agent/graph/")
    p_e.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_e.add_argument("--root", dest="root_flag", help="project root directory")
    p_e.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_e.set_defaults(fn=cmd_export)

    # explain
    p_exp = sub.add_parser("explain", help="generate deterministic codebase understanding document")
    p_exp.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_exp.add_argument("--root", dest="root_flag", help="project root directory")
    p_exp.add_argument("--out", default=None, help="output markdown file (default: .agent/graph/understanding.md)")
    p_exp.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_exp.add_argument("--pretty", action="store_true", help="render rich table")
    p_exp.set_defaults(fn=cmd_explain)

    # approve
    p_app = sub.add_parser("approve", help="interactively approve understanding document in a terminal (human only)")
    p_app.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_app.add_argument("--root", dest="root_flag", help="project root directory")
    p_app.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_app.add_argument("--pretty", action="store_true", help="render rich table")
    p_app.set_defaults(fn=cmd_approve)

    # status
    p_st = sub.add_parser("status", help="check graph approval and freshness status")
    p_st.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_st.add_argument("--root", dest="root_flag", help="project root directory")
    p_st.add_argument("--graph-dir", default=".agent/graph", help="graph directory (default: .agent/graph)")
    p_st.add_argument("--pretty", action="store_true", help="render rich table")
    p_st.set_defaults(fn=cmd_status)

    return ap


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdout()
    if argv is not None:
        argv = list(argv)
    else:
        argv = sys.argv[1:]

    # Handle explicit --version / -v before parser subcmd requirement
    if argv and argv[0] in ("-v", "--version"):
        print(version_string())
        return 0

    ap = build_parser()
    completion.autocomplete(ap)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)

    old_ui = os.environ.get("AGENTDATA_UI")
    try:
        if getattr(a, "pretty", False):
            os.environ["AGENTDATA_UI"] = "rich"
            ui.reset_cache()

        fn = getattr(a, "fn", None)
        if fn:
            return fn(a)
        ap.print_help()
        return 0
    finally:
        if getattr(a, "pretty", False):
            if old_ui is None:
                os.environ.pop("AGENTDATA_UI", None)
            else:
                os.environ["AGENTDATA_UI"] = old_ui
            ui.reset_cache()


if __name__ == "__main__":
    sys.exit(main())
