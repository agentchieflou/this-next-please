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
from .testing import detect_all, detect_runner, run_tests
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
    p_run.set_defaults(fn=cmd_run)

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
