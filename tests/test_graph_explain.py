"""Tests for `ad-graph explain`, `ad-graph approve` and `ad-graph status` — the human approval gate.

The point of this file is issue #41's central claim: an agent cannot approve its own understanding of a
codebase. So the interesting assertions are the negative ones — a redirected stdin exits 3 and leaves the
filesystem untouched, and no flag exists that would let a caller opt out of the terminal.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

from agentdata import state as S
from agentdata.cli_graph import build_parser, main as graph_main
from agentdata.graph import approval, explain
from agentdata.graph.builder import build_graph
from agentdata.graph.query import NodeNotFoundError, find_node, load_graph
from agentdata.textio import read_text, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "graph")


@pytest.fixture()
def repo(tmp_path):
    """A copy of the sample fixture with a freshly built graph, and its .agent/graph dir."""
    root = str(tmp_path / "repo")
    shutil.copytree(os.path.join(FIXTURES_DIR, "sample_repo"), root)
    out_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=out_dir)
    return root, out_dir


def _understanding(out_dir):
    return os.path.join(out_dir, "understanding.md")


def _fact_anchors(doc: str) -> list[str]:
    """The trailing `id` of every fact bullet in the document."""
    anchors = []
    for line in doc.splitlines():
        if not line.startswith("- "):
            continue
        m = re.search(r"`([^`]+)`\s*$", line)
        assert m, f"fact line does not end in a backticked node id: {line!r}"
        anchors.append(m.group(1))
    return anchors


# --------------------------------------------------------------------------------------- explain


def test_explain_writes_seven_sections_with_resolvable_anchors(repo, capsys):
    root, out_dir = repo
    assert graph_main(["explain", root, "--graph-dir", out_dir]) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out

    doc = read_text(_understanding(out_dir))
    assert re.search(r'(?m)^graph_sha256: "[0-9a-f]{64}"$', doc), "front matter must record graph_sha256"
    for section in explain.SECTIONS:
        assert f"## {section}" in doc, f"missing section {section}"

    graph, _meta = load_graph(root, graph_dir=out_dir)
    anchors = _fact_anchors(doc)
    assert anchors, "the fixture must produce fact lines"
    for anchor in anchors:
        if anchor == explain.ROOT_ANCHOR:
            continue  # repo-wide aggregate, deliberately not a node
        find_node(graph, anchor)  # raises NodeNotFoundError / AmbiguousNodeError if a reviewer could not


def test_explain_never_names_the_same_node_twice_on_one_line(repo):
    """The anchor is appended only when the sentence does not already end with it."""
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    for line in read_text(_understanding(out_dir)).splitlines():
        if not line.startswith("- "):
            continue
        ids = re.findall(r"`([^`]+)`", line)
        anchor = ids[-1]
        # an id may legitimately repeat inside a call route (a -> b -> a); it may not be *appended* to a
        # sentence that already ended with it
        assert not line.rstrip().endswith(f"`{anchor}` `{anchor}`"), f"duplicated anchor: {line!r}"


def test_explain_reports_the_real_extractor_and_module_hubs(repo):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    doc = read_text(_understanding(out_dir))
    modules = [ln for ln in doc.splitlines() if ln.startswith("- **")]
    app_row = next(ln for ln in modules if ln.startswith("- **app**"))
    # the fixture is all Python: no module may claim the generic fallback
    assert "extractor: `python`" in app_row
    assert "`generic`" not in app_row
    # a module whose symbols appear under ## Hubs may not simultaneously report "hubs: none"
    assert "hubs: none" not in app_row
    assert "app.py::Processor" in app_row
    # LOC comes off the file node, so a tests/ directory is not reported as 0
    tests_row = next(ln for ln in modules if ln.startswith("- **tests**"))
    assert re.search(r", (\d+) LOC", tests_row).group(1) != "0"


def test_explain_names_generic_extractor_files_under_open_questions(tmp_path):
    root = str(tmp_path / "np")
    shutil.copytree(os.path.join(FIXTURES_DIR, "non_python_repo"), root)
    out_dir = os.path.join(root, ".agent", "graph")
    build_graph(root=root, out_dir=out_dir)
    graph_main(["explain", root, "--graph-dir", out_dir])

    doc = read_text(_understanding(out_dir))
    questions = doc.split("## Open questions", 1)[1]
    for rel in ("index.js", "model.tmdl", "query.sql"):
        assert f"`{rel}` was read by the `generic` extractor" in questions
    # a repo with no extractor still gets file-level nodes, so the graph is never empty
    assert "- No modules found" not in doc


def test_explain_preserves_model_text_and_refreshes_facts_around_it(repo):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    path = _understanding(out_dir)

    note = "`utils.py::helper` is the only shared leaf; everything else is local to app.py."
    doc = read_text(path)
    doc = doc.replace(
        "## Modules\n",
        "## Modules\n",
    ).replace("<!-- model -->\n<!-- /model -->", f"<!-- model -->\n{note}\n<!-- /model -->", 1)
    write_text(path, doc)

    # change the code so a fact must move, then rebuild and re-explain
    app = os.path.join(root, "app.py")
    write_text(app, read_text(app) + "\n\ndef added_helper():\n    return 1\n")
    build_graph(root=root, out_dir=out_dir, force=True)
    assert graph_main(["explain", root, "--graph-dir", out_dir]) == 0

    refreshed = read_text(path)
    assert note in refreshed, "model prose between the markers must survive a refresh"
    assert "added_helper" in refreshed or "26 LOC" not in refreshed
    ratio_before = re.search(r"tested_ratio: ([\d.]+)%", doc).group(1)
    ratio_after = re.search(r"tested_ratio: ([\d.]+)%", refreshed).group(1)
    assert ratio_before != ratio_after, "an added untested function must move tested_ratio"


def test_explain_without_a_graph_is_an_error_row(tmp_path, capsys):
    root = str(tmp_path / "bare")
    os.makedirs(root)
    assert graph_main(["explain", root, "--graph-dir", os.path.join(root, ".agent", "graph")]) == 1
    out = capsys.readouterr().out
    assert "ok: false" in out and "ad-graph build" in out


# --------------------------------------------------------------------------------------- approve


def test_approve_has_no_escape_hatch_flag():
    """There is deliberately no --yes / --non-interactive: the absence is part of the contract."""
    parser = build_parser()
    ns = parser.parse_args(["approve", "."])
    assert not hasattr(ns, "yes")
    assert not hasattr(ns, "non_interactive")
    for bad in (["approve", ".", "--yes"], ["approve", ".", "--non-interactive"]):
        with pytest.raises(SystemExit):
            parser.parse_args(bad)


@pytest.mark.parametrize("stdin_mode", ["devnull", "pipe"])
def test_approve_refuses_without_a_terminal_and_writes_nothing(repo, stdin_mode):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    before = sorted(os.listdir(out_dir))

    kwargs = {"stdin": subprocess.DEVNULL} if stdin_mode == "devnull" else {"input": b"y\n"}
    p = subprocess.run(
        [sys.executable, "-m", "agentdata.cli_graph", "approve", root, "--graph-dir", out_dir],
        capture_output=True,
        cwd=REPO_ROOT,
        **kwargs,
    )
    assert p.returncode == 3, p.stdout.decode(errors="replace")
    out = p.stdout.decode(errors="replace")
    assert "ok: false" in out
    assert "terminal" in out.lower()
    assert sorted(os.listdir(out_dir)) == before
    assert not os.path.exists(os.path.join(out_dir, "approval.json"))


def _state_file(root):
    path = os.path.join(root, ".agent", "state.json")
    write_text(path, json.dumps({"phase": "idle", "tools": {}}, indent=2))
    return path


def test_approve_yes_writes_approval_and_stamps_state(repo):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    state_path = _state_file(root)

    res = approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "y")
    assert res["ok"] is True

    data = json.loads(read_text(os.path.join(out_dir, "approval.json")))
    assert re.fullmatch(r"[0-9a-f]{64}", data["graph_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", data["understanding_sha256"])
    assert data["approved_at"].endswith("Z") and data["approved_by"]

    stamped = S.load(state_path)["tools"]["graph_approved"]
    assert stamped == data["graph_sha256"][:8], "state carries the short graph sha"


def test_approve_no_writes_nothing(repo):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    state_path = _state_file(root)

    res = approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "n")
    assert res["ok"] is False and res["cancelled"] is True
    assert not os.path.exists(os.path.join(out_dir, "approval.json"))
    assert S.load(state_path).get("tools", {}).get("graph_approved") is None


def test_approve_requires_an_understanding_document(repo):
    root, out_dir = repo
    res = approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "y")
    assert res["ok"] is False
    assert "ad-graph explain" in res["hint"]


# ---------------------------------------------------------------------------------------- status


def test_status_none_then_current_then_stale(repo, capsys):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    _state_file(root)

    assert graph_main(["status", root, "--graph-dir", out_dir]) == 0
    assert "none" in capsys.readouterr().out

    approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "y")
    assert graph_main(["status", root, "--graph-dir", out_dir]) == 0
    out = capsys.readouterr().out
    assert "current" in out and "stale" not in out

    # touch the code and rebuild: the approval was for one tree, not for the repository forever
    app = os.path.join(root, "app.py")
    write_text(app, read_text(app) + "\n\ndef drift():\n    return 2\n")
    build_graph(root=root, out_dir=out_dir, force=True)

    assert graph_main(["status", root, "--graph-dir", out_dir]) == 0
    out = capsys.readouterr().out
    assert "stale" in out
    res = approval.check_approval_status(root=root, graph_dir=out_dir)
    assert res["status"] == "stale" and res["approved"] is False
    assert res["changed_nodes"] >= 1


def test_status_goes_stale_when_the_document_is_edited(repo):
    root, out_dir = repo
    graph_main(["explain", root, "--graph-dir", out_dir])
    _state_file(root)
    approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "y")
    assert approval.check_approval_status(root=root, graph_dir=out_dir)["status"] == "current"

    path = _understanding(out_dir)
    write_text(path, read_text(path) + "\nAn edit the human never approved.\n")
    assert approval.check_approval_status(root=root, graph_dir=out_dir)["status"] == "stale"


# ----------------------------------------------------------------------------------------- skill


def test_codebase_map_skill_forbids_self_approval():
    text = read_text(os.path.join(REPO_ROOT, "skills", "codebase-map", "SKILL.md"))
    assert "never run `ad-graph approve`" in text
    assert text.rstrip().endswith("STOP.")


def test_router_routes_unfamiliar_code_to_codebase_map():
    text = read_text(os.path.join(REPO_ROOT, "skills", "router", "SKILL.md"))
    row = next(ln for ln in text.splitlines() if "`codebase-map`" in ln)
    assert "unfamiliar code" in row


def test_session_bootstrap_prints_graph_status_when_blocked_on_approval():
    text = read_text(os.path.join(REPO_ROOT, "skills", "session-bootstrap", "SKILL.md"))
    blocked = next(ln for ln in text.splitlines() if ln.startswith("5."))
    assert "ad-graph approve" in blocked and "ad-graph status" in blocked


def test_docs_explain_the_approval_gate():
    text = read_text(os.path.join(REPO_ROOT, "docs", "code-graph.md"))
    assert "## The approval gate: why the command needs a terminal" in text


# ------------------------------------------------------------------------------- writes stay put


def test_explain_and_approve_write_only_under_the_graph_dir(repo):
    """AGENTS.md rule 12: nothing outside .agent/ may change."""
    root, out_dir = repo
    _state_file(root)

    def snapshot():
        seen = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".agent")]
            for f in filenames:
                p = os.path.join(dirpath, f)
                seen[os.path.relpath(p, root).replace("\\", "/")] = os.path.getsize(p)
        return seen

    before = snapshot()
    graph_main(["explain", root, "--graph-dir", out_dir])
    approval.approve_graph(root=root, graph_dir=out_dir, input_fn=lambda _p: "y")
    assert snapshot() == before, "a read-only command changed a source file"
