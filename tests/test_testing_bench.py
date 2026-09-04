"""Tests for `ad-test bench`, `ad-test run --snapshot/--compare`, and the `test-regress` skill.

The point of this slice is that "faster" and "nothing broke" stop being claims. So the assertions
here are about the verdicts: a real speedup says `faster`, a 3% wobble says `same`, and a test that
stopped passing is a `regression` no matter how it stopped.
"""
from __future__ import annotations
import glob
import os
import shutil

import pytest

from agentdata import config
from agentdata.cli_test import main as run_cli
from agentdata.graph.builder import build_graph
from agentdata.testing import bench_node, compare_bench, compare_runs, snapshot_run
from agentdata.testing.bench import linked_tests
from agentdata.textio import read_text, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "testing")
BENCH_FIXTURES = os.path.join(FIXTURES, "bench")


@pytest.fixture()
def bench_repo(tmp_path):
    root = str(tmp_path / "bp")
    shutil.copytree(os.path.join(FIXTURES, "bench_project"), root)
    build_graph(root=root, out_dir=os.path.join(root, ".agent", "graph"))
    return root


def _fx(name):
    return os.path.join(BENCH_FIXTURES, name)


# ----------------------------------------------------------------------------------- bench --node


def test_bench_node_times_the_node_and_profiles_it(bench_repo):
    res = bench_node(bench_repo, node="src/hot.py::slow_version", runs=2, warmup=0, label="before")
    assert res["ok"] is True, res.get("error")
    row = res["row"]
    assert row["runs"] == 2
    assert row["median_ms"] > 0
    assert row["node_cum_ms"] != "n/a" and float(row["node_cum_ms"]) > 0
    assert row["tests"] == 1 and row["runner"] == "pytest"
    assert os.path.isfile(os.path.join(bench_repo, res["path"]))


def test_bench_without_linked_tests_names_test_cover(bench_repo):
    src = os.path.join(bench_repo, "src", "hot.py")
    write_text(src, read_text(src) + "\n\ndef orphan(x):\n    return x\n")
    build_graph(root=bench_repo, out_dir=os.path.join(bench_repo, ".agent", "graph"), force=True)

    res = bench_node(bench_repo, node="src/hot.py::orphan", runs=1, warmup=0)
    assert res["ok"] is False
    assert "no tests are linked" in res["error"]
    assert res["hint"] == "run test-cover for src/hot.py::orphan"


def test_name_derived_test_links_are_reported_not_trusted_silently(bench_repo):
    tests, source = linked_tests(bench_repo, "src/hot.py::slow_version")
    assert tests and source == "name", "no coverage collected yet, so the link is the name heuristic"


# --------------------------------------------------------------------------------- bench compare


def test_a_real_speedup_is_faster():
    res = compare_bench(_fx("before.tsv"), _fx("after_faster.tsv"))
    row = res["row"]
    assert row["basis"] == "node_cum_ms", "the node's own cost, not the suite's wall time"
    assert row["verdict"] == "faster"
    assert row["speedup"] == 2.0 and row["meets_min_speedup"] is True


def test_a_change_inside_the_noise_floor_is_same():
    row = compare_bench(_fx("before.tsv"), _fx("after_noise.tsv"))["row"]
    assert abs(row["change_pct"]) == pytest.approx(3.0, abs=0.1)
    assert row["verdict"] == "same", "3% is not a win"
    assert row["meets_min_speedup"] is False


def test_a_slowdown_is_slower():
    row = compare_bench(_fx("before.tsv"), _fx("after_slower.tsv"))["row"]
    assert row["verdict"] == "slower" and row["delta_ms"] > 0


def test_a_runner_with_no_profiler_falls_back_to_wall_time():
    row = compare_bench(_fx("before_wall_only.tsv"), _fx("after_wall_only.tsv"))["row"]
    assert row["basis"] == "median_ms"
    assert row["verdict"] == "faster" and row["speedup"] == pytest.approx(1.667, abs=0.01)


def test_min_speedup_gate_is_configurable():
    assert compare_bench(_fx("before.tsv"), _fx("after_faster.tsv"), min_speedup=1.10)["row"]["meets_min_speedup"]
    assert not compare_bench(_fx("before.tsv"), _fx("after_faster.tsv"), min_speedup=3.0)["row"]["meets_min_speedup"]
    assert config.min_speedup({}) == config.DEFAULT_MIN_SPEEDUP


def test_an_unstable_baseline_has_to_clear_a_higher_bar(tmp_path):
    """The floor is max(5%, 2 x the before run's own spread)."""
    wobbly = str(tmp_path / "wobbly.tsv")
    write_text(wobbly, "node\tlabel\truns\tmedian_ms\tmin_ms\tp90_ms\tnode_cum_ms\ttests\trunner\n"
                       "n\tbefore\t5\t100.0\t80.0\t130.0\t40.0\t1\tpytest\n")   # 20% spread -> 40% floor
    after = str(tmp_path / "after.tsv")
    write_text(after, "node\tlabel\truns\tmedian_ms\tmin_ms\tp90_ms\tnode_cum_ms\ttests\trunner\n"
                      "n\tafter\t5\t75.0\t70.0\t80.0\t30.0\t1\tpytest\n")       # a 25% improvement
    row = compare_bench(wobbly, after)["row"]
    assert row["noise_floor_pct"] == pytest.approx(40.0, abs=0.1)
    assert row["verdict"] == "same", "25% does not clear a 40% floor on an unstable baseline"


# --------------------------------------------------------------------------- run snapshot/compare


def _snapshot(tmp_path, name, cases):
    path = str(tmp_path / name)
    lines = ["test\toutcome\ttime_ms"] + [f"{t}\t{o}\t1.0" for t, o in cases]
    write_text(path, "\n".join(lines) + "\n")
    return path


def test_a_test_that_stopped_passing_is_a_regression(tmp_path):
    before = _snapshot(tmp_path, "b.tsv", [("t::a", "passed"), ("t::b", "passed")])
    after = _snapshot(tmp_path, "a.tsv", [("t::a", "passed"), ("t::b", "failed")])
    res = compare_runs(before, after)
    assert res["ok"] is False and res["regressions"] == 1
    assert next(r for r in res["rows"] if r["test"] == "t::b")["status"] == "regression"


def test_a_vanished_test_is_a_regression_too(tmp_path):
    before = _snapshot(tmp_path, "b.tsv", [("t::a", "passed"), ("t::gone", "passed")])
    after = _snapshot(tmp_path, "a.tsv", [("t::a", "passed")])
    res = compare_runs(before, after)
    assert res["ok"] is False
    row = next(r for r in res["rows"] if r["test"] == "t::gone")
    assert row["status"] == "regression" and row["after"] == "absent"


def test_a_test_quietly_turned_into_a_skip_is_a_regression(tmp_path):
    before = _snapshot(tmp_path, "b.tsv", [("t::a", "passed")])
    after = _snapshot(tmp_path, "a.tsv", [("t::a", "skipped")])
    assert compare_runs(before, after)["ok"] is False


def test_an_added_passing_test_is_not_a_regression(tmp_path):
    before = _snapshot(tmp_path, "b.tsv", [("t::a", "passed")])
    after = _snapshot(tmp_path, "a.tsv", [("t::a", "passed"), ("t::new", "passed")])
    res = compare_runs(before, after)
    assert res["ok"] is True and res["added"] == 1
    assert next(r for r in res["rows"] if r["test"] == "t::new")["status"] == "added"


def test_snapshot_writes_per_test_outcomes(bench_repo):
    res = snapshot_run(bench_repo, label="before")
    assert res["ok"] is True and res["cases"] == 2
    path = os.path.join(bench_repo, res["path"])
    header = read_text(path).splitlines()[0]
    assert header.split("\t") == ["test", "outcome", "time_ms"]


# ------------------------------------------------------------------ the end-to-end regression gate


def test_a_genuine_optimisation_passes_the_gate_and_a_slower_one_fails(bench_repo):
    """The fixture ships the slow/fast pair so this measures real code, not a stub."""
    slow = bench_node(bench_repo, node="src/hot.py::slow_version", runs=2, warmup=1, label="before")
    fast = bench_node(bench_repo, node="src/hot.py::fast_version", runs=2, warmup=1, label="after")
    assert slow["ok"] and fast["ok"]

    before = os.path.join(bench_repo, slow["path"])
    after = os.path.join(bench_repo, fast["path"])
    good = compare_bench(before, after)["row"]
    assert good["verdict"] == "faster" and good["meets_min_speedup"] is True

    # the same comparison the other way round is what `regress: FAIL slower` is built on
    bad = compare_bench(after, before)["row"]
    assert bad["verdict"] == "slower"


def test_nothing_is_written_outside_agent_out(bench_repo):
    def snapshot():
        seen = {}
        for dirpath, dirnames, filenames in os.walk(bench_repo):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".agent")]
            for f in filenames:
                p = os.path.join(dirpath, f)
                seen[os.path.relpath(p, bench_repo)] = os.path.getsize(p)
        return seen

    before = snapshot()
    snapshot_run(bench_repo, label="probe")
    compare_bench(_fx("before.tsv"), _fx("after_faster.tsv"))
    assert snapshot() == before
    assert not glob.glob(os.path.join(bench_repo, "*.prof")), "cProfile output must land under .agent/out"


# ------------------------------------------------------------------------------------- the skill


def test_test_regress_skill_states_its_limits():
    text = read_text(os.path.join(REPO_ROOT, "skills", "test-regress", "SKILL.md"))
    assert "never re-run" in text
    assert "never edits" in text
    assert "regress: ok" in text and "regress: FAIL" in text


def test_router_routes_to_test_regress():
    text = read_text(os.path.join(REPO_ROOT, "skills", "router", "SKILL.md"))
    row = next(ln for ln in text.splitlines() if "`test-regress`" in ln)
    assert "is it faster" in row


def test_docs_carry_the_noise_floor_rule():
    text = read_text(os.path.join(REPO_ROOT, "docs", "testing.md"))
    assert "## Benchmarks" in text and "## Regression gate" in text
    assert "noise floor" in text.lower()


# --------------------------------------------------------------------------------------- the CLI


def test_cli_bench_requires_a_node(bench_repo, capsys):
    assert run_cli(["bench", bench_repo]) == 2
    assert "--node is required" in capsys.readouterr().out


def test_cli_bench_compare_and_run_compare(bench_repo, tmp_path, capsys):
    assert run_cli(["bench", bench_repo, "--compare", _fx("before.tsv"), _fx("after_faster.tsv")]) == 0
    out = capsys.readouterr().out
    assert "faster" in out and "speedup" in out

    before = _snapshot(tmp_path, "b.tsv", [("t::a", "passed")])
    after = _snapshot(tmp_path, "a.tsv", [("t::a", "failed")])
    assert run_cli(["run", bench_repo, "--compare", before, after]) == 1
    out = capsys.readouterr().out
    assert "ok: false" in out and "regression" in out


def test_cli_bench_compare_missing_file(bench_repo, capsys):
    assert run_cli(["bench", bench_repo, "--compare", _fx("before.tsv"), "nope.tsv"]) == 1
    assert "bench file not found" in capsys.readouterr().out
