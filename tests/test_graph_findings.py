"""Tests for `ad-graph findings` — one positive and one near-miss per check, plus ranking and baseline.

Each check owns a fixture file in tests/fixtures/graph/findings/ with a `positive_*` symbol that must
fire and a `nearmiss_*` symbol that must not. A check that fires on its own near-miss is a check that
would send the model to rewrite working code.
"""
from __future__ import annotations
import json
import os
import re
import shutil

import pytest

from agentdata.cli_graph import main as graph_main
from agentdata.graph import checks as C
from agentdata.graph import findings as F
from agentdata.graph.builder import build_graph
from agentdata.model import AgentTable
from agentdata.textio import read_text, write_json, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "graph", "findings")


@pytest.fixture()
def fixture_repo(tmp_path):
    root = str(tmp_path / "fnd")
    shutil.copytree(FIXTURES, root)
    out_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=out_dir)
    return root, out_dir


def _rows(root, out_dir, **kw):
    return F.collect(root=root, graph_dir=out_dir, **kw)["findings"]


def _nodes_for(rows, kind):
    return {r["node"] for r in rows if r["kind"] == kind}


# ------------------------------------------------------------------- positives and near-misses

# kind -> (fixture file, the symbol that must fire, the symbol that must not)
CASES = [
    ("io-in-loop", "io_in_loop.py", "positive_io_in_loop", "nearmiss_io_hoisted"),
    ("repeated-call", "repeated_call.py", "positive_repeated_call", "nearmiss_rebound_between"),
    ("quadratic-scan", "quadratic_scan.py", "positive_quadratic_scan", "nearmiss_set_membership"),
    ("swallowed-exception", "swallowed_exception.py", "positive_swallowed", "nearmiss_handled"),
    ("recursion-no-guard", "recursion_no_guard.py", "positive_unguarded", "nearmiss_guarded"),
    ("dead-code", "dead_code.py", "positive_dead", "nearmiss_dynamic"),
    ("hot-hub-complexity", "hot_hub.py", "positive_hot_and_branchy", "nearmiss_hot_but_simple"),
]


@pytest.mark.parametrize("kind,relfile,positive,nearmiss", CASES, ids=[c[0] for c in CASES])
def test_check_fires_on_positive_and_is_silent_on_nearmiss(fixture_repo, kind, relfile, positive, nearmiss):
    root, out_dir = fixture_repo
    hit = _nodes_for(_rows(root, out_dir, kinds=[kind]), kind)
    assert f"{relfile}::{positive}" in hit, f"{kind} did not fire on its positive"
    assert f"{relfile}::{nearmiss}" not in hit, f"{kind} fired on its near-miss"


def test_import_cycle_fires_on_the_ring_and_not_on_the_bystander(fixture_repo):
    root, out_dir = fixture_repo
    rows = [r for r in _rows(root, out_dir, kinds=["import-cycle"])]
    assert rows, "the deliberate cycle_x / cycle_y ring must be reported"
    evidence = " ".join(r["evidence"] for r in rows)
    assert "cycle_x.py" in evidence and "cycle_y.py" in evidence
    assert "standalone.py" not in evidence, "a module that only imports one half is not a cycle"


def test_every_kind_is_reachable(fixture_repo):
    """The registry and the CLI agree, and the coverage-only checks are the only silent ones."""
    root, out_dir = fixture_repo
    fired = {r["kind"] for r in _rows(root, out_dir)}
    coverage_only = {"untested-hub", "uncovered-branch"}
    assert set(C.kinds()) - fired == coverage_only
    assert coverage_only.isdisjoint(fired), "coverage checks must stay silent with no coverage data"


# ----------------------------------------------------------------------------------- docstrings


@pytest.mark.parametrize("mod", C.all_checks(), ids=lambda m: m.KIND)
def test_every_check_states_its_pattern_false_positive_and_confidence(mod):
    doc = mod.__doc__ or ""
    for label in ("Pattern:", "False positive:", "Confidence:"):
        assert label in doc, f"{mod.KIND}: docstring is missing a `{label}` line"
    assert mod.SEVERITY in C.SEVERITIES
    assert mod.CONFIDENCE in C.CONFIDENCE_ORDER


# ------------------------------------------------------------------------- coverage and ranking


def _write_coverage(out_dir, pcts, branch=None):
    """A minimal .agent/graph/coverage.json in the shape `ad-test coverage` writes."""
    nodes = {
        nid: {"pct": pct, "executed": [], "missing": [], "branch_pct": (branch or {}).get(nid, 100.0), "tests": []}
        for nid, pct in pcts.items()
    }
    write_json(os.path.join(out_dir, "coverage.json"), {"files": {}, "nodes": nodes})


def test_covered_join_and_ranking(fixture_repo):
    root, out_dir = fixture_repo
    covered = "hot_hub.py::positive_hot_and_branchy"
    uncovered = "quadratic_scan.py::positive_quadratic_scan"
    _write_coverage(out_dir, {covered: 95.0, uncovered: 10.0})

    rows = _rows(root, out_dir)
    by_node = {r["node"]: r for r in rows}
    assert by_node[covered]["covered"] == "true"      # >= graph.min_coverage (0.8)
    assert by_node[uncovered]["covered"] == "false"   # data exists and says no
    # a node with no entry in the coverage file at all is unknown, which is not the same as false
    unknown = [r for r in rows if r["node"] not in (covered, uncovered)]
    assert unknown and all(r["covered"] == "unknown" for r in unknown)

    # covered rows first, then leverage descending
    flags = [r["covered"] == "true" for r in rows]
    assert flags == sorted(flags, reverse=True), "covered findings must be ranked first"
    lev = [r["leverage"] for r in rows if r["covered"] == "true"]
    assert lev == sorted(lev, reverse=True)


def test_covered_only_keeps_just_the_actionable_rows(fixture_repo):
    root, out_dir = fixture_repo
    covered = "hot_hub.py::positive_hot_and_branchy"
    _write_coverage(out_dir, {covered: 95.0, "quadratic_scan.py::positive_quadratic_scan": 10.0})

    rows = _rows(root, out_dir, covered_only=True)
    assert rows, "the covered hub must survive the filter"
    assert {r["node"] for r in rows} == {covered}


def test_untested_hub_and_uncovered_branch_need_coverage(fixture_repo):
    root, out_dir = fixture_repo
    hub = "hot_hub.py::positive_hot_and_branchy"
    assert not _rows(root, out_dir, kinds=["untested-hub", "uncovered-branch"])

    _write_coverage(out_dir, {hub: 20.0}, branch={hub: 40.0})
    rows = _rows(root, out_dir, kinds=["untested-hub"])
    assert _nodes_for(rows, "untested-hub") == {hub}


def test_uncovered_branch_points_at_the_untaken_line(fixture_repo):
    root, out_dir = fixture_repo
    hub = "hot_hub.py::positive_hot_and_branchy"
    write_json(os.path.join(out_dir, "coverage.json"), {
        "files": {"hot_hub.py": {"branches": {"branch_executed": [[5, 0]], "branch_missing": [[9, 1]]}}},
        "nodes": {hub: {"pct": 90.0, "executed": [], "missing": [], "branch_pct": 50.0, "tests": []}},
    })
    rows = _rows(root, out_dir, kinds=["uncovered-branch"])
    assert len(rows) == 1
    assert rows[0]["where"] == "hot_hub.py:9", "where must land on the branch, not the function"


def test_min_confidence_and_kind_filters(fixture_repo):
    root, out_dir = fixture_repo
    assert all(r["confidence"] == "high" for r in _rows(root, out_dir, min_confidence="high"))
    only = _rows(root, out_dir, kinds=["io-in-loop"])
    assert only and {r["kind"] for r in only} == {"io-in-loop"}


def test_top_bounds_rows_but_reports_the_real_total(fixture_repo):
    root, out_dir = fixture_repo
    res = F.collect(root=root, graph_dir=out_dir, top=3)
    assert len(res["findings"]) == 3
    assert res["total"] > 3


# -------------------------------------------------------------------------------------- baseline


def test_baseline_reports_one_fixed_row_when_a_positive_is_removed(fixture_repo, tmp_path):
    root, out_dir = fixture_repo
    before = _rows(root, out_dir, kinds=["swallowed-exception"])
    assert len(before) == 1

    baseline = str(tmp_path / "baseline.tsv")
    t = F.to_table(before)
    write_text(baseline, "\t".join(t.columns) + "\n" + "\n".join("\t".join(str(v) for v in r) for r in t.rows) + "\n")

    # fix it: the broad handler now returns a fallback the caller can see
    path = os.path.join(root, "swallowed_exception.py")
    write_text(path, read_text(path).replace("    except Exception:\n        pass", "    except OSError:\n        return \"\""))
    build_graph(root=root, out_dir=out_dir, force=True)

    after = _rows(root, out_dir, kinds=["swallowed-exception"])
    diffed = F.diff_baseline(after, baseline)
    assert [r["status"] for r in diffed] == ["fixed"]
    assert diffed[0]["node"] == before[0]["node"]


def test_baseline_marks_unchanged_rows_same(fixture_repo, tmp_path):
    root, out_dir = fixture_repo
    rows = _rows(root, out_dir, kinds=["io-in-loop"])
    baseline = str(tmp_path / "b.tsv")
    t = F.to_table(rows)
    write_text(baseline, "\t".join(t.columns) + "\n" + "\n".join("\t".join(str(v) for v in r) for r in t.rows) + "\n")
    diffed = F.diff_baseline(rows, baseline)
    assert {r["status"] for r in diffed} == {"same"}


# ------------------------------------------------------------------------------------- the CLI


def test_cli_emits_toon_and_writes_the_full_list(fixture_repo, capsys):
    root, out_dir = fixture_repo
    assert graph_main(["findings", root, "--graph-dir", out_dir]) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "findings[" in out
    for col in ("kind", "node", "where", "severity", "confidence", "covered", "leverage", "hint", "evidence"):
        assert col in out
    path = re.search(r"^\s*path: (.+)$", out, re.M).group(1).strip()
    assert os.path.isfile(path), "the full list must land on disk"


def test_cli_rejects_an_unknown_kind(fixture_repo, capsys):
    root, out_dir = fixture_repo
    assert graph_main(["findings", root, "--graph-dir", out_dir, "--kind", "not-a-check"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "io-in-loop" in out


def test_cli_baseline_flag_adds_a_status_column(fixture_repo, tmp_path, capsys):
    root, out_dir = fixture_repo
    rows = _rows(root, out_dir, kinds=["io-in-loop"])
    baseline = str(tmp_path / "b.tsv")
    t = F.to_table(rows)
    write_text(baseline, "\t".join(t.columns) + "\n" + "\n".join("\t".join(str(v) for v in r) for r in t.rows) + "\n")

    assert graph_main(["findings", root, "--graph-dir", out_dir, "--kind", "io-in-loop", "--baseline", baseline]) == 0
    out = capsys.readouterr().out
    assert "status" in out and "same" in out


# -------------------------------------------------------------- it must survive a real codebase


def test_findings_runs_on_this_repository_and_every_where_resolves(tmp_path):
    out_dir = str(tmp_path / "selfgraph")
    build_graph(root=REPO_ROOT, out_dir=out_dir)
    res = F.collect(root=REPO_ROOT, graph_dir=out_dir, top=60)
    assert res["total"] > 0

    for row in res["findings"]:
        rel, _, span = row["where"].rpartition(":")
        assert rel, f"where has no file part: {row['where']}"
        line = int(span.split("-")[0])
        path = os.path.join(REPO_ROOT, rel.replace("/", os.sep))
        assert os.path.isfile(path), f"{row['kind']}: {rel} does not exist"
        assert 1 <= line <= len(read_text(path).splitlines()), f"{row['kind']}: {row['where']} is past EOF"


def test_docs_carry_a_checks_table():
    text = read_text(os.path.join(REPO_ROOT, "docs", "code-graph.md"))
    assert "## Checks" in text
    for kind in C.kinds():
        assert f"`{kind}`" in text, f"docs/code-graph.md does not describe {kind}"
