"""Tests for ad-graph build and graph extraction."""
from __future__ import annotations
import os
import shutil
import tempfile
import pytest

from agentdata.cli_graph import main as graph_main
from agentdata.dpm.guard import diff, snapshot
from agentdata.graph.builder import build_graph
from agentdata.graph.model import Graph
from agentdata.textio import read_text, write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "graph")


def test_build_sample_repo_fixture():
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = os.path.join(tmpdir, ".agent", "graph")
        res = build_graph(root=sample_root, out_dir=out_dir)
        assert res["ok"] is True
        assert res["files"] >= 3

        g = Graph.load(os.path.join(out_dir, "graph.json"))

        # Verify class, method, function nodes
        app_main = g.get_node("app.py::main")
        assert app_main is not None
        assert app_main.kind == "function"
        assert "entrypoint" in app_main.tags

        proc_read = g.get_node("app.py::Processor.read_file")
        assert proc_read is not None
        assert "io" in proc_read.tags

        helper_node = g.get_node("utils.py::helper")
        assert helper_node is not None
        assert helper_node.kind == "function"

        # Verify test nodes
        test_helper = g.get_node("tests/test_app.py::test_helper")
        assert test_helper is not None
        assert test_helper.kind == "test"

        # Verify edges: class contains method
        contains_edges = [e for e in g.edges if e.kind == "contains" and e.source == "app.py::Processor"]
        assert len(contains_edges) >= 2

        # Verify tests edge
        tests_edges = [e for e in g.edges if e.kind == "tests" and e.source == "tests/test_app.py::test_helper"]
        assert len(tests_edges) >= 1
        assert any(e.target == "utils.py::helper" for e in tests_edges)


def test_consecutive_and_incremental_builds_are_deterministic():
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Copy fixture into tmpdir so we can edit files
        repo_copy = os.path.join(tmpdir, "repo")
        shutil.copytree(sample_root, repo_copy)
        out_dir = os.path.join(repo_copy, ".agent", "graph")

        res1 = build_graph(root=repo_copy, out_dir=out_dir)
        graph_file = os.path.join(out_dir, "graph.json")
        bytes1 = read_text(graph_file)
        sha1 = res1["sha256"]

        # Second build without changes
        res2 = build_graph(root=repo_copy, out_dir=out_dir)
        bytes2 = read_text(graph_file)
        sha2 = res2["sha256"]

        assert bytes1 == bytes2
        assert sha1 == sha2

        # Edit one file
        utils_path = os.path.join(repo_copy, "utils.py")
        content = read_text(utils_path) + "\n\ndef another_func():\n    return 42\n"
        write_text(utils_path, content)

        # Incremental build
        res_inc = build_graph(root=repo_copy, out_dir=out_dir)
        bytes_inc = read_text(graph_file)

        # Force build
        res_force = build_graph(root=repo_copy, out_dir=out_dir, force=True)
        bytes_force = read_text(graph_file)

        assert res_inc["sha256"] == res_force["sha256"]
        assert bytes_inc == bytes_force


def test_build_never_writes_outside_out():
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_copy = os.path.join(tmpdir, "repo")
        shutil.copytree(sample_root, repo_copy)
        out_dir = os.path.join(tmpdir, "isolated_out")

        before = snapshot(repo_copy)
        build_graph(root=repo_copy, out_dir=out_dir)
        after = snapshot(repo_copy)

        diffs = diff(before, after)
        assert diffs == [], f"Build modified source tree: {diffs}"


def test_non_python_repo_produces_generic_graph():
    non_py_root = os.path.join(FIXTURES_DIR, "non_python_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = os.path.join(tmpdir, ".agent", "graph")
        res = build_graph(root=non_py_root, out_dir=out_dir)

        assert res["ok"] is True
        assert res["files"] >= 3
        assert res["extractors"]["generic"] >= 3
        assert res["extractors"]["python"] == 0

        g = Graph.load(os.path.join(out_dir, "graph.json"))
        file_nodes = [n for n in g.nodes.values() if n.kind == "file"]
        assert len(file_nodes) >= 3


def test_build_on_this_repository():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = os.path.join(tmpdir, ".agent", "graph")
        res = build_graph(root=REPO_ROOT, out_dir=out_dir)
        assert res["ok"] is True

        g = Graph.load(os.path.join(out_dir, "graph.json"))

        # Every [project.scripts] target should be an entrypoint function node
        entrypoint_nodes = [n for n in g.nodes.values() if "entrypoint" in n.tags and n.kind == "function"]
        entrypoint_ids = {n.id for n in entrypoint_nodes}

        # Check key entrypoints
        assert any("cli_graph.py::main" in nid for nid in entrypoint_ids)
        assert any("cli_setup.py::main_setup" in nid for nid in entrypoint_ids)
        assert any("cli_pbip.py::main" in nid for nid in entrypoint_ids)

        # Tests functions should be test nodes
        test_nodes = [n for n in g.nodes.values() if n.kind == "test"]
        assert len(test_nodes) >= 100
        test_ids = {n.id for n in test_nodes}
        assert any("test_entrypoints.py" in tid for tid in test_ids)


def test_cli_graph_build(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
        out_dir = os.path.join(tmpdir, "graph")
        rc = graph_main(["build", sample_root, "--out", out_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ok: true" in out or "meta:" in out
        assert "graph_build" in out
