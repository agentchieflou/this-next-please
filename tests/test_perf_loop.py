"""The perf-optimize loop, run as the commands the skill prescribes rather than by a model.

This is the acceptance test for the whole area: an approved graph, a covered finding, a guarded
change, and a proven speedup — and the same sequence stopping dead at the guard when the node is not
covered. If this passes, the two properties the area exists to guarantee hold end to end.
"""
from __future__ import annotations
import os
import shutil
import subprocess

import pytest

from agentdata import state as S
from agentdata.graph import approval, explain, findings, guard
from agentdata.graph.builder import build_graph
from agentdata.testing import bench_node, collect_coverage, compare_bench
from agentdata.textio import read_text, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "testing")
SKILL = os.path.join(REPO_ROOT, "skills", "perf-optimize", "SKILL.md")

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


@pytest.fixture()
def loop_repo(tmp_path):
    """bench_project under git, with a measured graph and a granted approval.

    `slow_version` is covered by a test; `uncovered_hot` deliberately is not.
    """
    root = str(tmp_path / "loop")
    shutil.copytree(os.path.join(FIXTURES, "bench_project"), root)
    src = os.path.join(root, "src", "hot.py")
    write_text(src, read_text(src) + '''

def uncovered_hot(items):
    """Nothing tests this, so the guard must refuse any change to it."""
    seen = []
    for it in items:
        if it in seen:
            continue
        seen.append(it)
    return len(seen)
''')

    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "loop@test")
    _git(root, "config", "user.name", "Loop Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    graph_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=graph_dir)
    assert collect_coverage(root, branch=True)["ok"] is True     # step 2
    explain.explain_graph(root=root, graph_dir=graph_dir)         # step 2 of codebase-map
    approval.approve_graph(root=root, graph_dir=graph_dir, input_fn=lambda _p: "y")  # step 3
    write_text(os.path.join(root, ".agent", "state.json"),
               '{"phase": "idle", "tools": {}, "open_questions": [], "artifacts": []}')
    return root, graph_dir


# ------------------------------------------------------------------------- the loop, end to end


def test_the_full_loop_on_a_covered_node(loop_repo):
    root, graph_dir = loop_repo

    # step 1: the graph is approved
    assert approval.check_approval_status(root=root, graph_dir=graph_dir)["status"] == "current"

    # step 3: a covered finding exists and the uncovered one is not in the list
    covered_rows = findings.collect(root=root, graph_dir=graph_dir, covered_only=True)["findings"]
    assert covered_rows, "the fixture must offer something legal to work on"
    assert all(r["covered"] == "true" for r in covered_rows)
    assert not any("uncovered_hot" in r["node"] for r in covered_rows)

    # step 4: baseline
    before = bench_node(root, node="src/hot.py::slow_version", runs=2, warmup=1, label="before")
    assert before["ok"] is True, before.get("error")

    # step 5: the smallest change that removes the pattern the hint names (list scan -> set)
    S.save(S.apply(S.load(os.path.join(root, ".agent", "state.json")), {"phase": "optimizing"}),
           os.path.join(root, ".agent", "state.json"))
    src = os.path.join(root, "src", "hot.py")
    write_text(src, read_text(src).replace(
        '''    seen = []
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
        seen.append(it)
    return hits''',
        '''    seen = set()
    hits = 0
    for it in items:
        if it in seen:
            hits += 1
        seen.add(it)
    return hits''',
        1,
    ))
    assert "seen = set()" in read_text(src)

    # step 6: the guard allows it -- the node is covered and the graph is approved
    verdict = guard.run_guard(root=root, graph_dir=graph_dir)
    assert verdict["ok"] is True, [r for r in verdict["rows"] if r["verdict"] == "refused"]
    assert verdict["approved"] == "current"

    # step 7: it is actually faster, measured through the tests that exercise it
    after = bench_node(root, node="src/hot.py::slow_version", runs=2, warmup=1, label="after")
    assert after["ok"] is True
    cmp_row = compare_bench(os.path.join(root, before["path"]),
                            os.path.join(root, after["path"]))["row"]
    assert cmp_row["verdict"] == "faster", cmp_row
    assert cmp_row["meets_min_speedup"] is True, cmp_row


def test_the_loop_stops_at_the_guard_on_an_uncovered_node(loop_repo):
    root, graph_dir = loop_repo
    src = os.path.join(root, "src", "hot.py")
    write_text(src, read_text(src).replace(
        "    seen = []\n    for it in items:", "    seen = set()\n    for it in items:", 1,
    ).replace("        seen.append(it)\n    return len(seen)", "        seen.add(it)\n    return len(seen)", 1))

    verdict = guard.run_guard(root=root, graph_dir=graph_dir)
    assert verdict["ok"] is False
    refused = [r for r in verdict["rows"] if r["verdict"] == "refused"]
    assert len(refused) == 1, refused
    assert refused[0]["node"] == "src/hot.py::uncovered_hot"
    assert refused[0]["covered"] == "false"
    assert "test-cover" in refused[0]["hint"], "the refusal must name the way out"


def test_an_unapproved_graph_stops_the_loop_before_anything_else(loop_repo):
    root, graph_dir = loop_repo
    os.remove(os.path.join(graph_dir, "approval.json"))
    assert approval.check_approval_status(root=root, graph_dir=graph_dir)["status"] == "none"

    src = os.path.join(root, "src", "hot.py")
    write_text(src, read_text(src).replace("seen = []", "seen = set()", 1))
    verdict = guard.run_guard(root=root, graph_dir=graph_dir)
    assert verdict["ok"] is False and verdict["approved"] == "missing"
    assert all("ad-graph approve" in r["hint"] for r in verdict["rows"] if r["verdict"] == "refused")


# ------------------------------------------------------------------------------ state and rules


def test_optimizing_is_a_real_phase_and_an_unknown_one_still_fails():
    assert "optimizing" in S.PHASES
    st = {"phase": "idle"}
    assert S.apply(st, {"phase": "optimizing"})["phase"] == "optimizing"
    with pytest.raises(S.StateError):
        S.apply(st, {"phase": "going-fast"})


def test_agents_md_carries_the_guard_stop_condition():
    text = read_text(os.path.join(REPO_ROOT, "AGENTS.md"))
    stop = text.split("## Stop conditions", 1)[1].split("## Style", 1)[0]
    line = next(ln for ln in stop.splitlines() if "ad-graph guard" in ln)
    assert line.strip().startswith("14."), "the stop conditions must stay contiguously numbered"
    assert "not `ok`" in line


def test_the_project_stub_carries_the_facts_this_area_reads():
    stub = read_text(os.path.join(REPO_ROOT, "agentdata", "templates", "project-stub", "AGENTS.md"))
    for fact in ("test_cmd", "graph_min_coverage", "graph_min_speedup"):
        assert f"- {fact}:" in stub, f"the project stub does not offer {fact}"


# ------------------------------------------------------------------------------------- the skill


def test_skill_keeps_the_stops_a_later_edit_might_drop():
    text = read_text(SKILL)
    for literal in ("never approve yourself", "No `--allow`", "revert"):
        assert literal in text, f"perf-optimize/SKILL.md no longer says {literal!r}"


def test_skill_sequences_the_gates_in_order():
    # the body only: the frontmatter description names the skills it hands off to, out of order
    text = read_text(SKILL).split("---", 2)[2]
    order = ["ad-graph status", "ad-test run", "ad-graph findings", "ad-test bench",
             "ad-graph guard", "test-regress"]
    positions = [text.index(cmd) for cmd in order]
    assert positions == sorted(positions), "the gates must appear in the order they must run"


def test_router_routes_performance_work_to_perf_optimize():
    text = read_text(os.path.join(REPO_ROOT, "skills", "router", "SKILL.md"))
    row = next(ln for ln in text.splitlines() if "`perf-optimize`" in ln)
    assert "make it faster" in row


def test_docs_carry_the_workflow_and_what_the_human_sees():
    text = read_text(os.path.join(REPO_ROOT, "docs", "code-graph.md"))
    assert "## Workflow: from an unseen repository to a proven speedup" in text
    section = text.split("## Workflow", 1)[1].split("\n## ", 1)[0]
    assert section.count("The human sees") >= 4


def test_changelog_tells_an_updating_user_to_patch_their_project():
    text = read_text(os.path.join(REPO_ROOT, "CHANGELOG.md"))
    entry = text.split("## ", 2)[1]
    assert "ad-setup --patch" in entry
    for fact in ("graph_min_coverage", "graph_min_speedup"):
        assert fact in entry
