# PYTHON_ARGCOMPLETE_OK
"""Command-line interface for `ad-test` — repository test runner detection, execution, and normalization."""
from __future__ import annotations
import argparse
import os
import sys
from typing import Sequence

from . import completion
from . import policy
from . import ui
from .console import utf8_stdout
from .model import AgentTable
from .policy import error, render
from . import config
from .testing import (
    bench_node, collect_coverage, compare_bench, compare_runs, detect_all, detect_runner,
    diff_coverage, run_tests, snapshot_run,
)
from .version import version_string


def cmd_detect(a: argparse.Namespace) -> int:
    root = a.root or "."
    flag_cmd = getattr(a, "test_cmd", None)

    if a.all:
        candidates = detect_all(root, flag_cmd=flag_cmd)
        if not candidates:
            print(error("no test runner detected", "set test_cmd in AGENTS.md", "ad-test detect"))
            return 1
        rows = [c.to_dict() for c in candidates]
        t = AgentTable.from_records(rows, name="detected_runners", source="ad-test detect")
        extra = {"ok": True, "source": "ad-test detect", "count": len(rows), "root": root}
        print(render(t, extra=extra))
        return 0

    info = detect_runner(root, flag_cmd=flag_cmd)
    if not info:
        print(error("no test runner detected", "set test_cmd in AGENTS.md", "ad-test detect"))
        return 1

    rows = [info.to_dict()]
    t = AgentTable.from_records(rows, name="detected_runner", source="ad-test detect")
    extra = {
        "ok": True,
        "source": "ad-test detect",
        "runner": info.runner,
        "cmd": info.cmd,
        "evidence": info.evidence,
        "root": root,
    }
    print(render(t, extra=extra))
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    root = a.root or "."

    if getattr(a, "compare", None):
        before, after = a.compare
        for pth in (before, after):
            if not os.path.isfile(pth):
                print(error(f"snapshot not found: {pth}", "run `ad-test run --snapshot <label>` first",
                            "ad-test run --compare"))
                return 1
        res = compare_runs(before, after)
        t = AgentTable.from_records(res["rows"], name="run_compare", source="ad-test run --compare",
                                    fields=["test", "before", "after", "status"])
        print(render(t, extra={
            "ok": res["ok"], "source": "ad-test run --compare",
            "regressions": res["regressions"], "added": res["added"],
            "before_total": res["before_total"], "after_total": res["after_total"],
        }))
        return 0 if res["ok"] else 1

    if getattr(a, "snapshot", None):
        res = snapshot_run(root, label=a.snapshot, timeout=a.timeout, runner_name=a.runner,
                           selectors=a.select)
        if "error" in res:
            print(error(res["error"], res["hint"], "ad-test run --snapshot"))
            return 1
        rows = [{"property": k, "value": str(v)} for k, v in res.items() if k not in ("ok", "source")]
        t = AgentTable.from_records(rows, name="snapshot", source="ad-test run --snapshot")
        print(render(t, extra={"ok": res["ok"], "source": "ad-test run --snapshot", "path": res["path"]}))
        return 0 if res["ok"] else 1

    res = run_tests(
        root=root,
        runner_name=a.runner,
        timeout=a.timeout,
        selectors=a.select,
        junit_out=a.junit,
        flag_cmd=getattr(a, "test_cmd", None),
    )

    if "error" in res and not res.get("runner"):
        print(error(res["error"], res.get("hint", ""), "ad-test run"))
        return 1

    extra = {
        "ok": res["ok"],
        "source": "ad-test run",
        "runner": res.get("runner", ""),
        "cmd": res.get("cmd", ""),
        "duration_s": res.get("duration_s", 0.0),
        "passed": res.get("passed", 0),
        "failed": res.get("failed", 0),
        "skipped": res.get("skipped", 0),
        "errors": res.get("errors", 0),
        "log": res.get("log", ""),
    }

    if "fail" in res:
        extra["fail"] = res["fail"]
    if "hint" in res:
        extra["hint"] = res["hint"]
    if "error" in res:
        extra["error"] = res["error"]

    table = res.get("table")
    if table is None:
        table = AgentTable.from_records([], name="failures", source="ad-test run")

    print(render(table, extra=extra))
    return 0 if res["ok"] else 1


def cmd_coverage(a: argparse.Namespace) -> int:
    root = a.root or "."
    root = os.path.abspath(root)

    # 1. Handle --diff
    if a.diff:
        cur_cov_path = os.path.join(root, ".agent", "graph", "coverage.json")
        if not os.path.exists(cur_cov_path):
            print(error("current coverage.json not found", "run ad-test coverage first", "ad-test coverage --diff"))
            return 1
        base_path = a.diff if os.path.isabs(a.diff) else os.path.join(root, a.diff)
        if not os.path.exists(base_path):
            print(error(f"base coverage file not found: {a.diff}", "check base file path", "ad-test coverage --diff"))
            return 1
        try:
            import json
            from . import textio
            cur_cov = json.loads(textio.read_text(cur_cov_path))
            base_cov = json.loads(textio.read_text(base_path))
            rows = diff_coverage(cur_cov, base_cov)
            t = AgentTable.from_records(rows, name="coverage_diff", source="ad-test coverage --diff")
            extra = {"ok": True, "source": "ad-test coverage --diff", "count": len(rows)}
            print(render(t, extra=extra))
            return 0
        except Exception as e:
            print(error(f"failed to compare coverage: {e}", "", "ad-test coverage --diff"))
            return 1

    # 2. Handle --node
    if a.node:
        cov_path = os.path.join(root, ".agent", "graph", "coverage.json")
        if not os.path.exists(cov_path):
            print(error("coverage.json not found", "run ad-test coverage first", "ad-test coverage --node"))
            return 1
        try:
            import json
            from . import textio
            cov_data = json.loads(textio.read_text(cov_path))
            nodes_cov = cov_data.get("nodes", {})
            ncov = nodes_cov.get(a.node)
            if not ncov:
                for nid, val in nodes_cov.items():
                    if nid.endswith(a.node) or a.node.endswith(nid):
                        ncov = val
                        break
            if not ncov:
                print(error(f"node not found in coverage: {a.node}", "run ad-test coverage or check node id", "ad-test coverage --node"))
                return 1

            rows = [
                {"metric": "node", "value": a.node},
                {"metric": "pct", "value": f"{ncov.get('pct', 0.0)}%"},
                {"metric": "branch_pct", "value": f"{ncov.get('branch_pct', 100.0)}%"},
                {"metric": "executed_lines", "value": ",".join(str(x) for x in ncov.get("executed", []))},
                {"metric": "missing_lines", "value": ",".join(str(x) for x in ncov.get("missing", []))},
                {"metric": "tests", "value": ", ".join(ncov.get("tests", []))},
            ]
            t = AgentTable.from_records(rows, name="node_coverage", source="ad-test coverage --node")
            extra = {"ok": True, "source": "ad-test coverage --node", "node": a.node, "pct": ncov.get("pct")}
            print(render(t, extra=extra))
            return 0
        except Exception as e:
            print(error(f"failed to read node coverage: {e}", "", "ad-test coverage --node"))
            return 1

    # 3. Collect / Import coverage
    import_fmt = None
    import_file = None
    if getattr(a, "import_cov", None):
        import_fmt, import_file = a.import_cov

    res = collect_coverage(
        root=root,
        runner_name=a.runner,
        import_format=import_fmt,
        import_file=import_file,
        branch=a.branch,
        contexts=a.contexts,
        flag_cmd=getattr(a, "test_cmd", None),
    )

    if not res.get("ok"):
        print(error(res.get("error", "coverage collection failed"), res.get("hint", ""), "ad-test coverage"))
        return 1

    rows = [
        {"metric": "graph_sha256", "value": str(res.get("graph_sha256", ""))},
        {"metric": "source", "value": str(res.get("data", {}).get("source", ""))},
        {"metric": "collected_at", "value": str(res.get("data", {}).get("collected_at", ""))},
        {"metric": "files_covered", "value": str(res.get("files_covered", 0))},
        {"metric": "nodes_covered", "value": str(res.get("nodes_covered", 0))},
        {"metric": "coverage_json", "value": str(res.get("path", ""))},
    ]
    unmatched = res.get("data", {}).get("unmatched", [])
    if unmatched:
        rows.append({"metric": "unmatched_files", "value": ", ".join(unmatched)})

    t = AgentTable.from_records(rows, name="coverage_summary", source="ad-test coverage")
    extra = {
        "ok": True,
        "source": "ad-test coverage",
        "graph_sha256": res.get("graph_sha256", ""),
        "files_covered": res.get("files_covered", 0),
        "nodes_covered": res.get("nodes_covered", 0),
        "coverage_json": res.get("path", ""),
    }
    print(render(t, extra=extra))
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    root = a.root
    if a.compare:
        before, after = a.compare
        for pth in (before, after):
            if not os.path.isfile(pth):
                print(error(f"bench file not found: {pth}", "run `ad-test bench --node <id> --label <name>` first",
                            "ad-test bench --compare"))
                return 1
        res = compare_bench(before, after, min_speedup=config.min_speedup(root=root))
        if not res["ok"]:
            print(error(res["error"], res["hint"], "ad-test bench --compare"))
            return 1
        row = res["row"]
        t = AgentTable.from_records([row], name="bench_compare", source="ad-test bench --compare")
        print(render(t, extra={"ok": True, "source": "ad-test bench --compare",
                               "verdict": row["verdict"], "speedup": row["speedup"],
                               "min_speedup": res["min_speedup"]}))
        return 0

    if not a.node:
        print(error("--node is required", "ad-test bench --node <node-id> [--runs N]", "ad-test bench"))
        return 2

    res = bench_node(root, node=a.node, runs=a.runs, warmup=a.warmup, label=a.label,
                     timeout=a.timeout, runner_name=a.runner)
    if not res["ok"]:
        print(error(res["error"], res["hint"], "ad-test bench"))
        return 1
    t = AgentTable.from_records([res["row"]], name="bench", source="ad-test bench")
    extra = {"ok": True, "source": "ad-test bench", "path": res["path"],
             "test_source": res["test_source"], "profiled": res["profiled"]}
    if res["warnings"]:
        extra["warnings"] = res["warnings"]
    print(render(t, extra=extra))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ad-test",
        description="Repository test runner detection, execution under timeout, and normalized TOON results.",
    )
    p.add_argument("-v", "--version", action="version", version=version_string())
    p.add_argument("--pretty", action="store_true", help="force human-facing table format")

    sub = p.add_subparsers(dest="subcommand", metavar="COMMAND")

    # detect
    p_detect = sub.add_parser("detect", help="detect test runner for the repo")
    p_detect.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_detect.add_argument("--all", action="store_true", help="list all detected runner candidates")
    p_detect.add_argument("--test-cmd", help="override test command")
    p_detect.set_defaults(fn=cmd_detect)

    # run
    p_run = sub.add_parser("run", help="run tests under timeout and normalize results")
    p_run.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_run.add_argument("--runner", help="explicit runner name (pytest, unittest, npm, dotnet, make)")
    p_run.add_argument("--timeout", type=int, default=600, help="timeout in seconds (default: 600)")
    p_run.add_argument("--select", action="append", default=[], help="node id, test id, or path to run")
    p_run.add_argument("--junit", help="write JUnit XML output to this path")
    p_run.add_argument("--test-cmd", help="override test command")
    p_run.add_argument("--snapshot", metavar="LABEL", help="save the per-test result table for later --compare")
    p_run.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="diff two snapshots for regressions")
    p_run.set_defaults(fn=cmd_run)

    # coverage
    p_cov = sub.add_parser("coverage", help="collect or import line and branch coverage")
    p_cov.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_cov.add_argument("--runner", help="explicit runner name (pytest, unittest)")
    p_cov.add_argument("--import", dest="import_cov", nargs=2, metavar=("FORMAT", "FILE"), help="import coverage file (lcov or cobertura)")
    p_cov.add_argument("--branch", action="store_true", help="measure branch coverage")
    p_cov.add_argument("--contexts", action="store_true", help="record test context for each line")
    p_cov.add_argument("--node", help="show coverage details for a specific node id")
    p_cov.add_argument("--diff", help="compare coverage with a base coverage.json file")
    p_cov.add_argument("--test-cmd", help="override test command")
    p_cov.set_defaults(fn=cmd_coverage)

    # bench
    p_bench = sub.add_parser("bench", help="time a node through the tests that exercise it")
    p_bench.add_argument("root", nargs="?", default=".", help="project root directory (default: .)")
    p_bench.add_argument("--node", help="graph node id to benchmark")
    p_bench.add_argument("--runs", type=int, default=5, help="timed runs (default: 5)")
    p_bench.add_argument("--warmup", type=int, default=1, help="untimed warmup runs (default: 1)")
    p_bench.add_argument("--label", default="bench", help="label for the output file (e.g. before, after)")
    p_bench.add_argument("--runner", help="explicit runner name")
    p_bench.add_argument("--timeout", type=int, default=600, help="timeout in seconds (default: 600)")
    p_bench.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two bench files")
    p_bench.set_defaults(fn=cmd_bench)

    completion.autocomplete(p)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdout()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-v", "--version"):
        print(version_string())
        return 0

    p = build_parser()
    if not args or args[0] in ("-h", "--help"):
        p.print_help()
        return 0

    parsed = p.parse_args(args)
    if not hasattr(parsed, "fn"):
        p.print_help()
        return 0

    old_ui = os.environ.get("AGENTDATA_UI")
    if getattr(parsed, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()

    try:
        return parsed.fn(parsed)
    finally:
        if getattr(parsed, "pretty", False):
            if old_ui is None:
                os.environ.pop("AGENTDATA_UI", None)
            else:
                os.environ["AGENTDATA_UI"] = old_ui
            ui.reset_cache()


if __name__ == "__main__":
    sys.exit(main())
