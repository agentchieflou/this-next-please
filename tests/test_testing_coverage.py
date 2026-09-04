"""Tests for ad-test coverage (Sub-issue #46)."""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile

import pytest

from agentdata import cli_graph, cli_test
from agentdata.graph import builder, query
from agentdata.testing import collect_coverage, diff_coverage

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "testing")


def test_missing_graph_fails_cleanly(tmp_path):
    res = collect_coverage(str(tmp_path))
    assert res["ok"] is False
    assert "graph file not found" in res["error"]
    assert "run ad-graph build" in res["hint"]


def test_python_coverage_with_contexts(tmp_path):
    # Copy graph_project to tmp_path
    work_dir = tmp_path / "graph_proj"
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), work_dir)

    # Build the code graph first
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    # Run coverage with --contexts and --branch
    res = collect_coverage(str(work_dir), branch=True, contexts=True)
    assert res["ok"] is True

    cov_file = work_dir / ".agent" / "graph" / "coverage.json"
    assert cov_file.exists()
    data = json.loads(cov_file.read_text())

    nodes = data["nodes"]
    add_node = nodes.get("src/calculator.py::add")
    sub_node = nodes.get("src/calculator.py::subtract")

    assert add_node is not None
    assert sub_node is not None

    # Tested function: pct is 100, lists exact test id under tests
    assert add_node["pct"] == 100.0
    assert any("test_add" in t for t in add_node["tests"])

    # Untested function: pct is 0 (since only test_add ran if only add was called, or subtract was tested?)
    # Wait, in test_calculator.py, test_subtract also exists unless we run only test_add!
    # Let's verify: test_calculator.py has both test_add and test_subtract!
    # If both ran, both are 100. Let's test with only test_add running:
    # We can pass flag_cmd="python -m pytest tests/test_calculator.py -k test_add"
    res_partial = collect_coverage(
        str(work_dir),
        contexts=True,
        flag_cmd=f"{sys.executable} -m pytest tests/test_calculator.py -k test_add",
    )
    assert res_partial["ok"] is True
    data_partial = json.loads(cov_file.read_text())
    nodes_partial = data_partial["nodes"]

    add_node_p = nodes_partial["src/calculator.py::add"]
    sub_node_p = nodes_partial["src/calculator.py::subtract"]

    assert add_node_p["pct"] == 100.0
    assert any("test_add" in t for t in add_node_p["tests"])
    assert sub_node_p["pct"] == 0.0
    assert sub_node_p["tests"] == []


def test_import_lcov_and_cobertura(tmp_path):
    work_dir = tmp_path / "graph_proj"
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), work_dir)
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    lcov_file = os.path.join(FIXTURES, "sample.lcov")
    res_lcov = collect_coverage(
        str(work_dir),
        import_format="lcov",
        import_file=lcov_file,
    )
    assert res_lcov["ok"] is True
    data_lcov = res_lcov["data"]
    assert "src/calculator.py" in data_lcov["files"]
    assert any("unknown_module" in u for u in data_lcov["unmatched"])

    cobertura_file = os.path.join(FIXTURES, "sample_cobertura.xml")
    res_cob = collect_coverage(
        str(work_dir),
        import_format="cobertura",
        import_file=cobertura_file,
    )
    assert res_cob["ok"] is True
    data_cob = res_cob["data"]
    assert "src/calculator.py" in data_cob["files"]
    assert any("unknown_module" in u for u in data_cob["unmatched"])

    # Both produced the same lines executed and missing for src/calculator.py
    f_lcov = data_lcov["files"]["src/calculator.py"]
    f_cob = data_cob["files"]["src/calculator.py"]
    assert f_lcov["lines_executed"] == f_cob["lines_executed"]
    assert f_lcov["lines_missing"] == f_cob["lines_missing"]


def test_ad_graph_reads_coverage_and_updates_summary(tmp_path, capsys):
    work_dir = tmp_path / "graph_proj"
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), work_dir)
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    # Before coverage: ad-graph summary
    g_before, _ = query.load_graph(str(work_dir))
    assert g_before.coverage is None

    # Collect coverage
    collect_coverage(str(work_dir), contexts=True)

    # After coverage: load_graph loads coverage
    g_after, _ = query.load_graph(str(work_dir))
    assert g_after.coverage is not None
    tested_node = g_after.nodes["src/calculator.py::add"]
    assert tested_node.covered is True
    assert tested_node.coverage_pct is not None

    # CLI ad-graph node shows covered: true
    rc = cli_graph.main(["node", "src/calculator.py::add", "--root", str(work_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "covered" in out
    assert "true" in out


def test_branch_coverage_and_missing_arcs(tmp_path):
    work_dir = tmp_path / "branch_proj"
    shutil.copytree(os.path.join(FIXTURES, "branch_project"), work_dir)
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    res = collect_coverage(str(work_dir), branch=True)
    assert res["ok"] is True
    data = res["data"]
    f_cov = data["files"].get("src/branchy.py")
    assert f_cov is not None
    branches = f_cov["branches"]
    # There should be missing branch arcs because only positive was tested
    assert len(branches["branch_missing"]) > 0


def test_coverage_diff_node_by_node(tmp_path):
    base_cov = {
        "nodes": {
            "src/app.py::foo": {"pct": 50.0},
            "src/app.py::bar": {"pct": 0.0},
        }
    }
    cur_cov = {
        "nodes": {
            "src/app.py::foo": {"pct": 100.0},
            "src/app.py::bar": {"pct": 75.0},
        }
    }

    diff_rows = diff_coverage(cur_cov, base_cov)
    assert len(diff_rows) == 2
    row_foo = next(r for r in diff_rows if r["node"] == "src/app.py::foo")
    assert row_foo["pct_before"] == 50.0
    assert row_foo["pct_after"] == 100.0
    assert row_foo["delta"] == 50.0

    row_bar = next(r for r in diff_rows if r["node"] == "src/app.py::bar")
    assert row_bar["pct_before"] == 0.0
    assert row_bar["pct_after"] == 75.0
    assert row_bar["delta"] == 75.0


def test_coverage_never_writes_outside_agent(tmp_path):
    work_dir = tmp_path / "snap_proj"
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), work_dir)
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    def snapshot(d: str) -> set[str]:
        items = set()
        for root, dirs, files in os.walk(d):
            rel_root = os.path.relpath(root, d).replace("\\", "/")
            if rel_root.startswith(".agent"):
                continue
            for f in files:
                items.add(f"{rel_root}/{f}".lstrip("./"))
        return items

    before = snapshot(str(work_dir))
    collect_coverage(str(work_dir), branch=True, contexts=True)
    after = snapshot(str(work_dir))

    diff = after - before
    assert diff == set(), f"Files written outside .agent/: {diff}"
    assert not (work_dir / ".coverage").exists()
    assert not (work_dir / ".coveragerc").exists()


def test_cli_coverage_node_and_diff(tmp_path, capsys):
    work_dir = tmp_path / "cli_cov_proj"
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), work_dir)
    builder.build_graph(root=str(work_dir), out_dir=str(work_dir / ".agent" / "graph"))

    # 1. Run coverage
    rc = cli_test.main(["coverage", str(work_dir), "--contexts"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "coverage_json" in out

    # 2. Inspect node
    rc = cli_test.main(["coverage", str(work_dir), "--node", "src/calculator.py::add"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "100.0%" in out

    # 3. Diff coverage against itself
    cov_path = str(work_dir / ".agent" / "graph" / "coverage.json")
    rc = cli_test.main(["coverage", str(work_dir), "--diff", cov_path])
    assert rc == 0
    out = capsys.readouterr().out
    assert "delta" in out
