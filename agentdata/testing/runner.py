"""Execution and result normalization for test runners."""
from __future__ import annotations
import datetime
import os
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any

from .. import config as C
from .. import proc
from .. import textio
from .. import ui
from ..model import AgentTable
from .detect import detect_runner, TestRunnerInfo
from .kill import kill_tree


def safe_relpath(path: str, start: str) -> str:
    try:
        return textio.norm_path(os.path.relpath(path, start))
    except ValueError:
        return textio.norm_path(path)


def resolve_selectors(root: str, selectors: list[str]) -> list[str]:
    """Map graph node IDs or paths to test IDs via the code graph, when present."""
    if not selectors:
        return []
    graph_json = os.path.join(root, ".agent", "graph", "graph.json")
    if not os.path.exists(graph_json):
        return list(selectors)

    try:
        from ..graph import query
        g, _sha = query.load_graph(root)
    except Exception:
        return list(selectors)

    resolved: list[str] = []
    seen: set[str] = set()

    for sel in selectors:
        node = query.find_node(g, sel)
        linked_tests: list[str] = []
        if node:
            linked_tests = [e.source for e in g.edges if e.kind == "tests" and e.target == node.id]
            if node.tests:
                linked_tests.extend(node.tests)

        if linked_tests:
            for t in linked_tests:
                if t not in seen:
                    seen.add(t)
                    resolved.append(t)
        else:
            if sel not in seen:
                seen.add(sel)
                resolved.append(sel)

    return resolved


def parse_junit_xml(xml_path: str, root: str = ".") -> tuple[int, int, int, int, list[dict[str, str]]]:
    """Parse JUnit XML into (passed, failed, skipped, errors, failures_list)."""
    tree = ET.parse(xml_path)
    xml_root = tree.getroot()

    suites: list[ET.Element] = []
    if xml_root.tag == "testsuite":
        suites.append(xml_root)
    elif xml_root.tag == "testsuites":
        suites.extend(xml_root.findall("testsuite"))
        if not suites:
            suites.append(xml_root)
    else:
        suites.append(xml_root)

    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    failures: list[dict[str, str]] = []

    for suite in suites:
        for tc in suite.findall("testcase"):
            total_tests += 1
            tc_name = tc.get("name", "")
            tc_class = tc.get("classname", "")
            test_id = f"{tc_class}::{tc_name}" if tc_class and tc_name else (tc_name or tc_class or "test")

            fail_elem = tc.find("failure")
            err_elem = tc.find("error")
            skip_elem = tc.find("skipped")

            if skip_elem is not None:
                total_skipped += 1
                continue

            target_elem = fail_elem if fail_elem is not None else err_elem
            if target_elem is not None:
                if fail_elem is not None:
                    total_failures += 1
                else:
                    total_errors += 1

                # Extract message
                raw_msg = target_elem.get("message", "")
                if raw_msg:
                    msg = raw_msg.strip().splitlines()[0]
                else:
                    lines = (target_elem.text or "").strip().splitlines()
                    msg = lines[0] if lines else "test failed"

                # Extract where (file:line)
                where = ""
                elem_text = target_elem.text or ""
                # Pytest traceback pattern: path/to/file.py:123: ErrorName
                m = re.search(r"([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+):(\d+):", elem_text)
                if m:
                    raw_file = textio.norm_path(m.group(1))
                    if os.path.isabs(raw_file):
                        rel_file = safe_relpath(raw_file, root)
                    else:
                        rel_file = raw_file
                    where = f"{rel_file}:{m.group(2)}"
                elif tc.get("file") and tc.get("line"):
                    tc_file = textio.norm_path(tc.get("file", ""))
                    if os.path.isabs(tc_file):
                        tc_file = safe_relpath(tc_file, root)
                    where = f"{tc_file}:{tc.get('line')}"

                failures.append({
                    "test": test_id,
                    "where": where,
                    "message": msg,
                })

    passed = max(0, total_tests - total_failures - total_errors - total_skipped)
    return passed, total_failures, total_skipped, total_errors, failures


def parse_junit_cases(xml_path: str) -> list[dict[str, Any]]:
    """Every test case with its outcome, for `ad-test run --snapshot` / `--compare`.

    `parse_junit_xml` returns counts and failures, which cannot answer "did this test vanish" or
    "did this one go from passed to skipped" -- both of which are regressions.
    """
    xml_root = ET.parse(xml_path).getroot()
    suites: list[ET.Element] = []
    if xml_root.tag == "testsuites":
        suites.extend(xml_root.findall("testsuite")) or suites.append(xml_root)
    else:
        suites.append(xml_root)

    cases: list[dict[str, Any]] = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            name, cls = tc.get("name", ""), tc.get("classname", "")
            test_id = f"{cls}::{name}" if cls and name else (name or cls or "test")
            if tc.find("skipped") is not None:
                outcome = "skipped"
            elif tc.find("error") is not None:
                outcome = "error"
            elif tc.find("failure") is not None:
                outcome = "failed"
            else:
                outcome = "passed"
            try:
                seconds = float(tc.get("time") or 0.0)
            except ValueError:
                seconds = 0.0
            cases.append({"test": test_id, "outcome": outcome, "time_ms": round(seconds * 1000.0, 3)})
    cases.sort(key=lambda c: c["test"])
    return cases


def parse_text_fallback(text: str, returncode: int, root: str = ".") -> tuple[Any, Any, int, int, list[dict[str, str]]]:
    """Parse textual test output (unittest, npm, etc.) when machine formats are unavailable."""
    failures: list[dict[str, str]] = []

    # Check unittest format:
    # FAILED (failures=1, errors=0, skipped=0) or OK (skipped=1)
    # Ran 3 tests in 0.001s
    ran_m = re.search(r"Ran\s+(\d+)\s+tests?", text)
    if ran_m:
        total = int(ran_m.group(1))
        failed = 0
        errors = 0
        skipped = 0

        fail_summary = re.search(r"FAILED\s*\((.*?)\)", text)
        if fail_summary:
            parts = fail_summary.group(1)
            fm = re.search(r"failures=(\d+)", parts)
            em = re.search(r"errors=(\d+)", parts)
            sm = re.search(r"skipped=(\d+)", parts)
            if fm:
                failed = int(fm.group(1))
            if em:
                errors = int(em.group(1))
            if sm:
                skipped = int(sm.group(1))
        else:
            skip_m = re.search(r"OK\s*\(skipped=(\d+)\)", text)
            if skip_m:
                skipped = int(skip_m.group(1))

        # Extract unittest failure blocks
        # FAIL: test_fail (test_mod.SampleTest)
        block_matches = re.finditer(r"(FAIL|ERROR):\s+([\w\.]+)\s+\(([\w\.]+)\)", text)
        for bm in block_matches:
            test_id = f"{bm.group(3)}::{bm.group(2)}"
            start_pos = bm.end()
            chunk = text[start_pos:start_pos + 1000]
            where = ""
            wm = re.search(r'File "([^"]+)", line (\d+)', chunk)
            if wm:
                where = f"{safe_relpath(wm.group(1), root)}:{wm.group(2)}"
            # Message is the last line of chunk before next block or empty line
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            msg = lines[-1] if lines else "AssertionError"
            failures.append({"test": test_id, "where": where, "message": msg})

        passed = max(0, total - failed - errors - skipped)
        return passed, failed, skipped, errors, failures

    # Generic pass/fail regexes
    pm = re.search(r"(\d+)\s+pass(?:ed|ing)", text, re.I)
    fm = re.search(r"(\d+)\s+fail(?:ed|ing|ures?)", text, re.I)
    sm = re.search(r"(\d+)\s+skip(?:ped)?", text, re.I)

    if pm or fm or sm:
        passed = int(pm.group(1)) if pm else 0
        failed = int(fm.group(1)) if fm else 0
        skipped = int(sm.group(1)) if sm else 0
        return passed, failed, skipped, 0, failures

    # Unknown runner output
    if returncode == 0:
        return "unknown", 0, 0, 0, failures
    return "unknown", "unknown", 0, 0, failures


def run_tests(
    root: str = ".",
    *,
    runner_name: str | None = None,
    timeout: int = 600,
    selectors: list[str] | None = None,
    junit_out: str | None = None,
    flag_cmd: str | None = None,
) -> dict[str, Any]:
    """Execute the detected or specified test runner under timeout and normalize results."""
    root = os.path.abspath(root)

    # 1. Resolve runner
    if flag_cmd:
        runner = "configured"
        cmd_str = flag_cmd
    elif runner_name:
        runner = runner_name
        if runner == "pytest":
            cmd_str = "python -m pytest"
        elif runner == "unittest":
            cmd_str = "python -m unittest discover"
        elif runner == "npm":
            cmd_str = "npm test"
        elif runner == "dotnet":
            cmd_str = "dotnet test"
        elif runner == "make":
            cmd_str = "make test"
        else:
            cmd_str = runner_name
    else:
        info = detect_runner(root)
        if not info:
            return {
                "ok": False,
                "source": "ad-test run",
                "error": "no test runner detected",
                "hint": "set test_cmd in AGENTS.md",
                "runner": "",
                "cmd": "",
                "duration_s": 0.0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "log": "",
                "failures": [],
                "table": AgentTable.from_records([], name="failures", source="ad-test run"),
            }
        runner = info.runner
        cmd_str = info.cmd

    # 2. Check executable resolution
    cmd_parts = shlex.split(cmd_str, posix=(os.name != "nt"))
    first_bin = cmd_parts[0] if cmd_parts else ""
    if first_bin == "python":
        first_bin = sys.executable

    res_info = proc.resolve(first_bin)
    if not res_info.get("found"):
        return {
            "ok": False,
            "source": "ad-test run",
            "error": f"{first_bin}: executable not found",
            "hint": f"install {runner} and put it on PATH",
            "runner": runner,
            "cmd": cmd_str,
            "duration_s": 0.0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "log": "",
            "failures": [],
            "table": AgentTable.from_records([], name="failures", source="ad-test run"),
        }

    # 3. Setup out dir, log file, junit path
    out_dir = os.path.join(root, ".agent", "out")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(out_dir, f"test-{ts}.log")
    junit_file = junit_out or os.path.join(out_dir, f"junit-{ts}.xml")

    # 4. Resolve selectors via code graph
    resolved_sels = resolve_selectors(root, selectors or [])

    # 5. Assemble command list
    full_cmd: list[str]
    if runner == "pytest" or "pytest" in cmd_str:
        full_cmd = [
            sys.executable,
            "-m",
            "pytest",
            f"--junitxml={junit_file}",
            "-o",
            f"cache_dir={os.path.join(out_dir, '.pytest_cache')}",
        ]
        if resolved_sels:
            full_cmd.extend(resolved_sels)
    elif runner == "unittest":
        full_cmd = [sys.executable, "-m", "unittest", "discover"]
        if resolved_sels:
            full_cmd.extend(resolved_sels)
    elif runner == "npm":
        full_cmd = ["npm", "test"]
        if resolved_sels:
            full_cmd.extend(["--", *resolved_sels])
    elif runner == "dotnet":
        trx_file = os.path.join(out_dir, f"test-{ts}.trx")
        full_cmd = [
            "dotnet",
            "test",
            f"--logger:trx;LogFileName={os.path.basename(trx_file)}",
            f"--results-directory:{out_dir}",
        ]
        if resolved_sels:
            filt = "|".join(f"FullyQualifiedName~{s}" for s in resolved_sels)
            full_cmd.extend(["--filter", filt])
    else:
        full_cmd = list(cmd_parts)
        if resolved_sels:
            full_cmd.extend(resolved_sels)

    # 6. Execute under timeout
    real, _info = proc.prepare(full_cmd)
    t0 = time.time()
    timed_out = False
    stdout = ""
    stderr = ""
    rc = 0

    try:
        run_env = os.environ.copy()
        run_env["PYTHONDONTWRITEBYTECODE"] = "1"
        with ui.progress(f"Running tests ({runner})..."):
            p = subprocess.Popen(
                real,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=root,
                start_new_session=(os.name != "nt"),
                env=run_env,
            )
            try:
                stdout, stderr = p.communicate(timeout=timeout)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_tree(p.pid)
                try:
                    stdout, stderr = p.communicate(timeout=5)
                except Exception:
                    pass
    except Exception as e:
        duration_s = time.time() - t0
        return {
            "ok": False,
            "source": "ad-test run",
            "error": str(e),
            "hint": "re-run the test command directly to diagnose",
            "runner": runner,
            "cmd": " ".join(full_cmd) if isinstance(full_cmd, list) else str(full_cmd),
            "duration_s": round(duration_s, 3),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "log": "",
            "failures": [],
            "table": AgentTable.from_records([], name="failures", source="ad-test run"),
        }

    duration_s = time.time() - t0

    # 7. Write log file
    log_content = f"=== COMMAND: {' '.join(full_cmd) if isinstance(full_cmd, list) else full_cmd} ===\n=== STDOUT ===\n{stdout}\n=== STDERR ===\n{stderr}\n"
    textio.write_text(log_path, log_content)
    rel_log = safe_relpath(log_path, root)

    if timed_out:
        return {
            "ok": False,
            "source": "ad-test run",
            "fail": "timeout",
            "hint": "raise --timeout or narrow --select",
            "runner": runner,
            "cmd": " ".join(full_cmd) if isinstance(full_cmd, list) else full_cmd,
            "duration_s": round(duration_s, 3),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "log": rel_log,
            "failures": [],
            "table": AgentTable.from_records([], name="failures", source="ad-test run"),
        }

    # 8. Parse results
    failures: list[dict[str, str]] = []
    passed: Any = 0
    failed: Any = 0
    skipped: Any = 0
    errors: Any = 0

    if os.path.exists(junit_file):
        try:
            passed, failed, skipped, errors, failures = parse_junit_xml(junit_file, root=root)
        except Exception:
            passed, failed, skipped, errors, failures = parse_text_fallback(stdout + "\n" + stderr, rc, root=root)
    else:
        passed, failed, skipped, errors, failures = parse_text_fallback(stdout + "\n" + stderr, rc, root=root)

    ok = (rc == 0) and (failed == 0 or failed == "unknown") and (errors == 0)
    if failed not in (0, "unknown") or errors != 0:
        ok = False

    table = AgentTable.from_records(
        failures,
        name="failures",
        source="ad-test run",
    )

    return {
        "ok": ok,
        "source": "ad-test run",
        "runner": runner,
        "cmd": " ".join(full_cmd) if isinstance(full_cmd, list) else full_cmd,
        "duration_s": round(duration_s, 3),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "log": rel_log,
        "failures": failures,
        "table": table,
    }
