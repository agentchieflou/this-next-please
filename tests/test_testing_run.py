"""Tests for ad-test run and ad-test detect (Sub-issue #45)."""
from __future__ import annotations
import os
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import pytest

from agentdata import __main__ as M
from agentdata import cli_test
from agentdata.testing import detect_all, detect_runner, kill_tree, run_tests

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "testing")


def test_detect_order_and_empty_project(tmp_path):
    # 1. Empty project
    empty_dir = os.path.join(FIXTURES, "empty_project")
    info = detect_runner(empty_dir)
    assert info is None

    # CLI detect on empty project
    rc = cli_test.main(["detect", empty_dir])
    assert rc == 1

    # 2. Pytest project
    pytest_dir = os.path.join(FIXTURES, "pytest_project")
    info = detect_runner(pytest_dir)
    assert info is not None
    assert info.runner == "pytest"
    assert "pytest" in info.cmd
    assert info.evidence == "pyproject.toml"

    # 3. Unittest-only project
    unittest_dir = os.path.join(FIXTURES, "unittest_project")
    info = detect_runner(unittest_dir)
    assert info is not None
    assert info.runner == "unittest"
    assert "unittest discover" in info.cmd

    # 4. npm project
    npm_dir = os.path.join(FIXTURES, "npm_project")
    info = detect_runner(npm_dir)
    assert info is not None
    assert info.runner == "npm"
    assert info.cmd == "npm test"

    # 5. Configured command in AGENTS.md takes priority over pytest
    agents_md_proj = tmp_path / "agents_proj"
    agents_md_proj.mkdir()
    (agents_md_proj / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (agents_md_proj / "AGENTS.md").write_text("- test_cmd: custom-test-cmd --fast\n")
    info = detect_runner(str(agents_md_proj))
    assert info is not None
    assert info.runner == "configured"
    assert info.cmd == "custom-test-cmd --fast"
    assert info.evidence == "AGENTS.md:test_cmd"

    # detect_all returns both configured and pytest
    all_cand = detect_all(str(agents_md_proj))
    assert len(all_cand) >= 2
    assert all_cand[0].runner == "configured"
    assert all_cand[1].runner == "pytest"


def test_run_pytest_fixture_counts_and_failure_row():
    pytest_dir = os.path.join(FIXTURES, "pytest_project")
    res = run_tests(pytest_dir, timeout=60)

    assert res["ok"] is False
    assert res["runner"] == "pytest"
    assert res["passed"] == 1
    assert res["failed"] == 1
    assert res["skipped"] == 1
    assert res["errors"] == 0

    failures = res["failures"]
    assert len(failures) == 1
    f = failures[0]
    assert "test_fail" in f["test"]
    # where points at line 9 in test_sample.py (the assert 1 == 2 line)
    assert "test_sample.py:9" in f["where"]
    # message is equal to the first line of the assertion error
    assert f["message"] == "assert 1 == 2"


def test_timeout_kills_process_tree():
    timeout_dir = os.path.join(FIXTURES, "timeout_project")
    t0 = time.time()
    res = run_tests(timeout_dir, timeout=2)
    elapsed = time.time() - t0

    assert res["ok"] is False
    assert res["fail"] == "timeout"
    assert "raise --timeout" in res["hint"]
    # Bounded time: should terminate shortly after 2 seconds, well before 15 seconds
    assert elapsed < 10.0


def test_select_maps_graph_node_to_tests(tmp_path):
    graph_dir = os.path.join(FIXTURES, "graph_project")
    # Copy graph_project to tmp_path to keep fixture pristine
    work_dir = tmp_path / "graph_work"
    shutil.copytree(graph_dir, work_dir)

    junit_file = str(work_dir / ".agent" / "out" / "custom_junit.xml")
    res = run_tests(
        str(work_dir),
        selectors=["src/calculator.py::add"],
        junit_out=junit_file,
        timeout=60,
    )

    assert res["ok"] is True
    assert res["passed"] == 1
    assert res["failed"] == 0

    # Parse JUnit XML to verify only test_add ran
    tree = ET.parse(junit_file)
    testcases = tree.findall(".//testcase")
    assert len(testcases) == 1
    assert testcases[0].get("name") == "test_add"


def test_run_never_writes_outside_agent_out(tmp_path):
    pytest_dir = os.path.join(FIXTURES, "pytest_project")
    work_dir = tmp_path / "snapshot_work"
    shutil.copytree(pytest_dir, work_dir)

    def snapshot(d: str) -> set[str]:
        items = set()
        for root, dirs, files in os.walk(d):
            rel_root = os.path.relpath(root, d).replace("\\", "/")
            if rel_root.startswith(".agent/out"):
                continue
            for f in files:
                items.add(f"{rel_root}/{f}".lstrip("./"))
        return items

    before = snapshot(str(work_dir))
    res = run_tests(str(work_dir), timeout=60)
    after = snapshot(str(work_dir))

    # Assert no files were added or modified outside .agent/out/
    diff = after - before
    assert diff == set(), f"Files written outside .agent/out/: {diff}"


def test_cli_test_dispatch(capsys):
    pytest_dir = os.path.join(FIXTURES, "pytest_project")
    rc = cli_test.main(["detect", pytest_dir])
    assert rc == 0
    out = capsys.readouterr().out
    assert "runner: pytest" in out or "pytest" in out

    # Version check
    rc = cli_test.main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("agentdata ")

    # Module form
    rc = M.main(["test", "--version"])
    assert rc == 0
