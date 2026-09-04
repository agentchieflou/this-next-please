"""Tests for `ad-graph guard` — the command that says no.

Every case here is a refusal the user asked for: no approval, an approval that has gone stale, an
edit to code no test runs, a changed line the tests never execute, and a test that got deleted to
make the guard quiet. The positive cases exist to prove the guard is not simply always refusing.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys

import pytest

from agentdata.cli_graph import main as graph_main
from agentdata.graph import approval, explain, guard
from agentdata.graph.builder import build_graph
from agentdata.textio import read_text, write_json, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

LIB = '''def covered_fn(x):
    return x + 1


def uncovered_fn(x):
    return x * 2


def partly_covered(x):
    if x > 0:
        return "positive"
    return "other"
'''

TEST_LIB = '''from lib import covered_fn


def test_covered():
    assert covered_fn(1) == 2
    assert covered_fn(2) == 3
    assert covered_fn(0) == 1
'''


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _write_coverage(graph_dir):
    """Synthetic coverage in the shape `ad-test coverage` writes.

    `partly_covered` is the interesting one: 90% of its lines run, but line 11 never does, so a
    change landing on line 11 must be refused even though the node as a whole is "covered".
    """
    write_json(os.path.join(graph_dir, "coverage.json"), {
        "files": {"lib.py": {
            "lines_executed": [1, 2, 8, 9, 10, 12],
            "lines_missing": [5, 6, 11],
            "branches": {"branch_executed": [[9, 0]], "branch_missing": [[9, 1]]},
        }},
        "nodes": {
            "lib.py::covered_fn": {"pct": 100.0, "executed": [2], "missing": [], "branch_pct": 100.0, "tests": []},
            "lib.py::uncovered_fn": {"pct": 0.0, "executed": [], "missing": [5, 6], "branch_pct": 100.0, "tests": []},
            "lib.py::partly_covered": {"pct": 90.0, "executed": [9, 10, 12], "missing": [11], "branch_pct": 50.0, "tests": []},
        },
    })


@pytest.fixture()
def repo(tmp_path):
    """A git repo with a built graph, synthetic coverage, and a granted approval."""
    root = str(tmp_path / "proj")
    os.makedirs(os.path.join(root, "tests"))
    write_text(os.path.join(root, "lib.py"), LIB)
    write_text(os.path.join(root, "tests", "test_lib.py"), TEST_LIB)

    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "guard@test")
    _git(root, "config", "user.name", "Guard Test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    graph_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=graph_dir)
    _write_coverage(graph_dir)
    explain.explain_graph(root=root, graph_dir=graph_dir)
    approval.approve_graph(root=root, graph_dir=graph_dir, input_fn=lambda _p: "y")
    return root, graph_dir


def _run(root, graph_dir, **kw):
    return guard.run_guard(root=root, graph_dir=graph_dir, **kw)


def _row(res, node):
    return next(r for r in res["rows"] if r["node"] == node)


def _edit(root, old, new):
    path = os.path.join(root, "lib.py")
    text = read_text(path)
    assert old in text
    write_text(path, text.replace(old, new))


# ------------------------------------------------------------------------------ the happy path


def test_editing_a_covered_function_passes(repo):
    root, graph_dir = repo
    _edit(root, "return x + 1", "return x + 10")
    res = _run(root, graph_dir)
    assert res["ok"] is True and res["refused"] == 0
    assert res["approved"] == "current"
    assert _row(res, "lib.py::covered_fn")["verdict"] == "ok"


def test_an_empty_diff_is_not_a_refusal(repo):
    root, graph_dir = repo
    res = _run(root, graph_dir)
    assert res["ok"] is True and res["rows"] == []


def test_the_guard_never_writes_to_a_source_or_test_file(repo):
    """AGENTS.md rule 12, the same snapshot/diff proof `ad-graph build` uses."""
    root, graph_dir = repo
    _edit(root, "return x * 2", "return x * 22")

    def snapshot():
        seen = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".agent", ".git")]
            for f in filenames:
                p = os.path.join(dirpath, f)
                seen[os.path.relpath(p, root)] = read_text(p)
        return seen

    before = snapshot()
    _run(root, graph_dir)
    _run(root, graph_dir, tests_only=True)
    assert snapshot() == before


# ---------------------------------------------------------------------------- coverage refusals


def test_editing_an_uncovered_function_is_refused_and_names_test_cover(repo):
    root, graph_dir = repo
    _edit(root, "return x * 2", "return x * 22")
    res = _run(root, graph_dir)
    assert res["ok"] is False and res["refused"] == 1
    row = _row(res, "lib.py::uncovered_fn")
    assert row["verdict"] == "refused" and row["covered"] == "false"
    assert "test-cover" in row["hint"]


def test_changing_a_line_the_tests_never_run_is_refused_inside_a_covered_node(repo):
    root, graph_dir = repo
    # partly_covered is 90% covered, above the 0.8 threshold -- but line 11 has never executed
    _edit(root, '        return "positive"', '        return "POSITIVE"')
    res = _run(root, graph_dir)
    row = _row(res, "lib.py::partly_covered")
    assert row["covered"] == "true", "the node as a whole is above the threshold"
    assert row["verdict"] == "refused"
    assert "never run under a test" in row["hint"]


def test_min_coverage_override_waives_the_changed_line_check(repo):
    root, graph_dir = repo
    _edit(root, '        return "positive"', '        return "POSITIVE"')
    res = _run(root, graph_dir, min_coverage=0.5)
    assert _row(res, "lib.py::partly_covered")["verdict"] == "ok"


def test_no_coverage_data_at_all_is_unknown_and_unknown_refuses(repo):
    root, graph_dir = repo
    os.remove(os.path.join(graph_dir, "coverage.json"))
    _edit(root, "return x + 1", "return x + 10")
    res = _run(root, graph_dir)
    row = _row(res, "lib.py::covered_fn")
    assert row["covered"] == "unknown" and row["verdict"] == "refused"
    assert "ad-test coverage" in row["hint"]


# ---------------------------------------------------------------------------- approval refusals


def test_a_missing_approval_refuses_everything(repo):
    root, graph_dir = repo
    os.remove(os.path.join(graph_dir, "approval.json"))
    _edit(root, "return x + 1", "return x + 10")
    res = _run(root, graph_dir)
    assert res["approved"] == "missing" and res["ok"] is False
    assert all(r["verdict"] == "refused" for r in res["rows"])
    assert "ad-graph approve" in _row(res, "lib.py::covered_fn")["hint"]


def test_drift_in_a_file_the_diff_does_not_touch_is_stale(repo):
    root, graph_dir = repo
    # edit one file, and let a *different* file move underneath the approval
    _edit(root, "return x + 1", "return x + 10")
    write_text(os.path.join(root, "other.py"), "def sneaked_in():\n    return 1\n")
    build_graph(root=root, out_dir=graph_dir, force=True)

    res = _run(root, graph_dir, mode="ref", ref="HEAD")
    # other.py is untracked, so `--diff HEAD` does not see it: its drift is unexplained
    assert res["approved"] == "stale"
    assert any("other.py" in nid for nid in res["unexplained_drift"])
    assert "re-approve" in _row(res, "lib.py::covered_fn")["hint"]


def test_editing_only_the_files_in_the_diff_stays_current(repo):
    root, graph_dir = repo
    _edit(root, "return x + 1", "return x + 10")
    build_graph(root=root, out_dir=graph_dir, force=True)
    res = _run(root, graph_dir)
    assert res["approved"] == "current", "a node moving because you edited it is not staleness"


# ------------------------------------------------------------------------- test-file protections


def test_deleting_a_test_is_refused(repo):
    root, graph_dir = repo
    write_text(os.path.join(root, "tests", "test_lib.py"), "from lib import covered_fn\n")
    build_graph(root=root, out_dir=graph_dir, force=True)
    res = _run(root, graph_dir)
    row = _row(res, "tests/test_lib.py::test_covered")
    assert row["verdict"] == "refused"
    assert "never remove or weaken a test" in row["hint"]


def test_hollowing_out_a_test_is_refused(repo):
    root, graph_dir = repo
    write_text(os.path.join(root, "tests", "test_lib.py"),
               "from lib import covered_fn\n\n\ndef test_covered():\n    pass\n")
    build_graph(root=root, out_dir=graph_dir, force=True)
    res = _run(root, graph_dir)
    rows = [r for r in res["rows"] if "test_covered" in r["node"] and "shrank" in r["hint"]]
    assert rows, "a test whose body shrank must be refused"


def test_a_test_file_alone_is_exempt(repo):
    root, graph_dir = repo
    write_text(os.path.join(root, "tests", "test_more.py"),
               "from lib import uncovered_fn\n\n\ndef test_more():\n    assert uncovered_fn(2) == 4\n")
    res = _run(root, graph_dir)
    assert res["ok"] is True, "test-cover must be able to add coverage before anything else"


def test_tests_only_refuses_a_source_file_in_the_same_diff(repo):
    root, graph_dir = repo
    write_text(os.path.join(root, "tests", "test_more.py"),
               "from lib import uncovered_fn\n\n\ndef test_more():\n    assert uncovered_fn(2) == 4\n")
    assert _run(root, graph_dir, tests_only=True)["ok"] is True

    _edit(root, "return x * 2", "return x * 22")
    res = _run(root, graph_dir, tests_only=True)
    assert res["ok"] is False
    assert "--tests-only" in _row(res, "lib.py::uncovered_fn")["hint"]


# ------------------------------------------------------------------------------------- --allow


def test_allow_requires_a_terminal_and_records_nothing(repo):
    root, graph_dir = repo
    before = read_text(os.path.join(graph_dir, "approval.json"))
    p = subprocess.run(
        [sys.executable, "-m", "agentdata.cli_graph", "guard", root,
         "--graph-dir", graph_dir, "--allow", "lib.py::uncovered_fn"],
        capture_output=True, text=True, cwd=REPO_ROOT, stdin=subprocess.DEVNULL,
    )
    assert p.returncode == 3, p.stdout
    assert "terminal" in p.stdout.lower()
    assert read_text(os.path.join(graph_dir, "approval.json")) == before


def test_a_recorded_override_lets_one_node_through_and_is_visible(repo):
    root, graph_dir = repo
    res = guard.allow_node(root, graph_dir, ["lib.py::uncovered_fn"], input_fn=lambda _p: "y")
    assert res["ok"] is True

    record = json.loads(read_text(os.path.join(graph_dir, "approval.json")))
    entry = next(a for a in record["allowed"] if a["node"] == "lib.py::uncovered_fn")
    assert entry["by"] and entry["at"], "an override must say who and when"

    _edit(root, "return x * 2", "return x * 22")
    assert _run(root, graph_dir)["ok"] is True


def test_declining_the_override_records_nothing(repo):
    root, graph_dir = repo
    res = guard.allow_node(root, graph_dir, ["lib.py::uncovered_fn"], input_fn=lambda _p: "n")
    assert res["ok"] is False and res["cancelled"] is True
    assert "allowed" not in json.loads(read_text(os.path.join(graph_dir, "approval.json")))


# --------------------------------------------------------------------------------- the git hook


def test_install_hook_blocks_a_real_commit_then_uninstall_restores_it(repo):
    root, graph_dir = repo
    res = guard.install_hook(root)
    assert res["ok"] is True
    hook = os.path.join(root, ".git", "hooks", "pre-commit")
    assert os.path.isfile(hook) and guard.HOOK_MARKER in read_text(hook)

    _edit(root, "return x * 2", "return x * 22")
    _git(root, "add", "-A")
    p = _git(root, "commit", "-m", "touching uncovered code")
    assert p.returncode != 0, "the hook must block this commit"
    assert _git(root, "log", "--oneline").stdout.count("\n") == 1, "nothing new was committed"

    # --no-verify is the documented escape, and it must still work
    assert _git(root, "commit", "-m", "forced", "--no-verify").returncode == 0

    assert guard.uninstall_hook(root)["removed"] is True
    assert not os.path.exists(hook)


def test_install_hook_never_overwrites_someone_elses_hook(repo):
    root, _graph_dir = repo
    hooks = os.path.join(root, ".git", "hooks")
    os.makedirs(hooks, exist_ok=True)
    mine = os.path.join(hooks, "pre-commit")
    write_text(mine, "#!/bin/sh\necho mine\n")

    res = guard.install_hook(root)
    assert res["ok"] is False and res["exit_code"] == 2
    assert "already exists" in res["error"]
    assert read_text(mine) == "#!/bin/sh\necho mine\n"

    out = guard.uninstall_hook(root)
    assert out["ok"] is False and "not written by ad-graph" in out["error"]
    assert os.path.isfile(mine)


# ------------------------------------------------------------------------------------- the CLI


def test_cli_exit_codes(repo, capsys):
    root, graph_dir = repo
    _edit(root, "return x + 1", "return x + 10")
    assert graph_main(["guard", root, "--graph-dir", graph_dir]) == 0
    assert "ok: true" in capsys.readouterr().out

    _edit(root, "return x * 2", "return x * 22")
    assert graph_main(["guard", root, "--graph-dir", graph_dir]) == 1
    out = capsys.readouterr().out
    assert "ok: false" in out and "refused" in out


def test_cli_without_a_graph_exits_3(tmp_path, capsys):
    root = str(tmp_path / "bare")
    os.makedirs(root)
    _git(root, "init", "-q", ".")
    assert graph_main(["guard", root, "--graph-dir", os.path.join(root, ".agent", "graph")]) == 3
    assert "ad-graph build" in capsys.readouterr().out


def test_guard_ignores_its_own_agent_directory(repo):
    """Without this the graph and coverage files it just wrote read as an uncovered change."""
    root, graph_dir = repo
    build_graph(root=root, out_dir=graph_dir, force=True)
    files = guard.collect_diff(root, "worktree")
    assert not any(".agent" in rel.split("/") for rel in files)


def test_docs_explain_the_guard():
    text = read_text(os.path.join(REPO_ROOT, "docs", "code-graph.md"))
    assert "## The guard: what it refuses and how a human overrides it" in text


def test_changed_since_ref_actually_uses_git(repo):
    """Regression: proc.run returns a tuple, so `r.ok` raised and --since matched nothing."""
    root, graph_dir = repo
    from agentdata.graph.query import get_changed, load_graph

    _edit(root, "return x + 1", "return x + 10")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "second")

    graph, meta = load_graph(root, graph_dir=graph_dir)
    rows = get_changed(graph, meta, since_ref="HEAD~1", root=root)
    assert any(r["id"].startswith("lib.py") and "git diff" in r["reason"] for r in rows)
