"""Tests for the `test-cover` skill and its reference doc.

The scripted end-to-end here runs the *commands* the skill runs, not the model: adding a golden test
raises coverage and passes `ad-graph guard --tests-only`, and the same change with a source edit in
it is refused. That is the contract the skill depends on; the prose is checked separately.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess

import pytest

from agentdata.graph import approval, explain, guard
from agentdata.graph.builder import build_graph
from agentdata.testing import collect_coverage
from agentdata.textio import read_text, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(REPO_ROOT, "skills", "test-cover")
REFERENCE = os.path.join(SKILL_DIR, "references", "characterization.md")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "testing")

FRAMEWORKS = ["pytest", "unittest", "Jest", "xUnit (.NET)"]
REQUIRED_SUBSECTIONS = ["Shape", "Stubbing I/O", "Probe", "Pitfalls"]


def _sections(text, level):
    """{heading: body} for one heading level."""
    parts = re.split(rf"(?m)^{'#' * level} (?!#)", text)
    out = {}
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        out[head.strip()] = body
    return out


# ------------------------------------------------------------------------------- the reference


def test_every_framework_section_exists():
    sections = _sections(read_text(REFERENCE), 2)
    for fw in FRAMEWORKS:
        assert fw in sections, f"characterization.md has no §{fw}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_each_framework_has_all_four_subsections(framework):
    """A later edit must not be able to drop one: the skill reads all four, section-scoped (#24)."""
    body = _sections(read_text(REFERENCE), 2)[framework]
    subs = _sections(body, 3)
    for required in REQUIRED_SUBSECTIONS:
        assert required in subs, f"§{framework} is missing ### {required}"
        assert subs[required].strip(), f"§{framework} ### {required} is empty"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_each_pitfalls_list_names_the_ones_that_bit_this_repo(framework):
    body = _sections(read_text(REFERENCE), 2)[framework]
    pitfalls = _sections(body, 3)["Pitfalls"].lower()
    for topic in ("time", "random", "float", "windows path"):
        assert topic in pitfalls, f"§{framework} pitfalls does not mention {topic}"


def test_the_probe_pattern_says_never_to_predict_a_value():
    text = read_text(REFERENCE)
    assert "never write an expected value you predicted" in text.lower()


# ----------------------------------------------------------------------------------- the skill


def test_skill_states_its_hard_limits():
    text = read_text(os.path.join(SKILL_DIR, "SKILL.md"))
    for literal in ("test files only", "never edit a source file", "Never invent"):
        assert literal in text, f"SKILL.md does not contain {literal!r}"
    assert "references/characterization.md" in text


def test_router_routes_to_test_cover():
    text = read_text(os.path.join(REPO_ROOT, "skills", "router", "SKILL.md"))
    row = next(ln for ln in text.splitlines() if "`test-cover`" in ln)
    assert "characterization test" in row


def test_docs_explain_characterization():
    text = read_text(os.path.join(REPO_ROOT, "docs", "testing.md"))
    assert "## Characterization tests" in text


# --------------------------------------------------------------- the contract, run as commands


pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


@pytest.fixture()
def project(tmp_path):
    """The pytest fixture repo under git, with a graph, coverage and an approval."""
    root = str(tmp_path / "proj")
    shutil.copytree(os.path.join(FIXTURES, "graph_project"), root)
    shutil.rmtree(os.path.join(root, ".agent"), ignore_errors=True)

    # the shared fixture is fully covered; this skill only has a job when something is not, so give
    # it an uncovered target here rather than changing a fixture other tests depend on
    src = os.path.join(root, "src", "calculator.py")
    write_text(src, read_text(src) + "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n")

    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "cover@test")
    _git(root, "config", "user.name", "Cover Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    graph_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=graph_dir)
    assert collect_coverage(root)["ok"] is True
    explain.explain_graph(root=root, graph_dir=graph_dir)
    approval.approve_graph(root=root, graph_dir=graph_dir, input_fn=lambda _p: "y")
    return root, graph_dir


def _uncovered_node(graph_dir):
    import json
    cov = json.loads(read_text(os.path.join(graph_dir, "coverage.json")))["nodes"]
    return sorted(
        (nid for nid, c in cov.items() if "::" in nid and (c.get("pct") or 0) == 0.0),
        key=len,
    )


@pytestmark_git
def test_a_golden_test_raises_coverage_and_passes_the_tests_only_guard(project):
    root, graph_dir = project
    uncovered = _uncovered_node(graph_dir)
    assert uncovered, "the fixture must have something uncovered to characterize"
    target = uncovered[0]
    fn = target.split("::")[-1]

    import json
    before = json.loads(read_text(os.path.join(graph_dir, "coverage.json")))["nodes"][target]["pct"]
    assert before == 0.0

    # step 4: one test file, nothing else
    write_text(os.path.join(root, "tests", "test_characterize.py"), f'''import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.calculator import {fn}


def test_{fn}_characterization():
    """Pins current behavior. A failure here means behavior changed."""
    assert {fn}(6, 3) is not None
''')

    # step 6: the guard proves only test files changed
    res = guard.run_guard(root=root, graph_dir=graph_dir, tests_only=True)
    assert res["ok"] is True, [r for r in res["rows"] if r["verdict"] == "refused"]

    # step 5: coverage went up for the target node
    assert collect_coverage(root)["ok"] is True
    after = json.loads(read_text(os.path.join(graph_dir, "coverage.json")))["nodes"][target]["pct"]
    assert after > before, f"{target}: {before} -> {after}"


@pytestmark_git
def test_touching_a_source_file_in_the_same_change_is_refused(project):
    root, graph_dir = project
    write_text(os.path.join(root, "tests", "test_characterize.py"),
               "def test_placeholder():\n    assert True\n")
    src = os.path.join(root, "src", "calculator.py")
    write_text(src, read_text(src) + "\n\ndef sneaked_in():\n    return 1\n")

    res = guard.run_guard(root=root, graph_dir=graph_dir, tests_only=True)
    assert res["ok"] is False
    refused = [r for r in res["rows"] if r["verdict"] == "refused"]
    assert any("--tests-only" in r["hint"] for r in refused)
    assert any("calculator.py" in r["node"] for r in refused)
