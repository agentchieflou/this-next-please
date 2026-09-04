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
from .graph import builder
from .model import AgentTable
from .policy import error, render
from .version import version_string


def cmd_build(a: argparse.Namespace) -> int:
    try:
        res = builder.build_graph(
            root=a.root or ".",
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
    p_b.add_argument("--out", default=".agent/graph", help="output directory (default: .agent/graph)")
    p_b.add_argument("--include", action="append", help="glob patterns to include")
    p_b.add_argument("--exclude", action="append", help="glob patterns to exclude")
    p_b.add_argument("--force", action="store_true", help="force rebuild ignoring cache")
    p_b.add_argument("--pretty", action="store_true", help="render rich table")
    p_b.set_defaults(fn=cmd_build)

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

    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()

    fn = getattr(a, "fn", None)
    if fn:
        return fn(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
