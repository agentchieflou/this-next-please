"""Tests for ad-graph query commands: summary, node, refs, path, cycles, changed, export."""
from __future__ import annotations
import os
import shutil
import tempfile
import time
import pytest

from agentdata.cli_graph import main as graph_main
from agentdata.graph.builder import build_graph
from agentdata.textio import read_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "graph")


def test_query_commands_on_fixture(capsys):
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_copy = os.path.join(tmpdir, "repo")
        shutil.copytree(sample_root, repo_copy)
        out_dir = os.path.join(repo_copy, ".agent", "graph")

        # Build graph first
        build_graph(root=repo_copy, out_dir=out_dir)

        # 1. Summary
        rc = graph_main(["summary", repo_copy, "--graph-dir", out_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "entrypoint" in out
        assert "app.py::main" in out

        # 2. Node
        rc = graph_main(["node", "Processor.read_file", repo_copy, "--graph-dir", out_dir])
        assert rc == 0
        out = capsys.readouterr().out
        assert "app.py::Processor.read_file" in out
        assert "io" in out
        assert "app.py::Processor.process" in out  # caller

        # 3. Refs: depth 2 vs depth 1
        rc = graph_main(["refs", "Processor.read_file", repo_copy, "--graph-dir", out_dir, "--depth", "1"])
        assert rc == 0
        out_d1 = capsys.readouterr().out
        assert "app.py::Processor.process" in out_d1
        assert "app.py::main" not in out_d1  # main is at depth 2

        rc = graph_main(["refs", "Processor.read_file", repo_copy, "--graph-dir", out_dir, "--depth", "2"])
        assert rc == 0
        out_d2 = capsys.readouterr().out
        assert "app.py::Processor.process" in out_d2
        assert "app.py::main" in out_d2  # main reachable at depth 2

        # 4. Path: entrypoint -> io node
        rc = graph_main(["path", "app.py::main", "app.py::Processor.read_file", repo_copy, "--graph-dir", out_dir])
        assert rc == 0
        out_p = capsys.readouterr().out
        assert "app.py::main -> app.py::Processor.process -> app.py::Processor.read_file" in out_p

        # 5. Cycles: deliberate cycle between cycle_a and cycle_b
        rc = graph_main(["cycles", repo_copy, "--graph-dir", out_dir])
        assert rc == 0
        out_c = capsys.readouterr().out
        assert "cycle_a.py" in out_c and "cycle_b.py" in out_c

        # 6. Export
        dot_out = os.path.join(out_dir, "graph.dot")
        rc = graph_main(["export", "--format", "dot", "--out", dot_out, repo_copy, "--graph-dir", out_dir])
        assert rc == 0
        assert os.path.isfile(dot_out)
        assert "digraph CodeGraph" in read_text(dot_out)

        # Export outside .agent/graph refused
        bad_out = os.path.join(tmpdir, "outside.dot")
        rc = graph_main(["export", "--format", "dot", "--out", bad_out, repo_copy, "--graph-dir", out_dir])
        assert rc == 1


def test_ambiguous_and_missing_node(capsys):
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_copy = os.path.join(tmpdir, "repo")
        shutil.copytree(sample_root, repo_copy)
        out_dir = os.path.join(repo_copy, ".agent", "graph")

        build_graph(root=repo_copy, out_dir=out_dir)

        # Missing node
        rc = graph_main(["node", "nonexistent_symbol_12345", repo_copy, "--graph-dir", out_dir])
        assert rc == 2
        out_missing = capsys.readouterr().out
        assert "not found in graph" in out_missing

        # Missing graph
        rc = graph_main(["node", "helper", repo_copy, "--graph-dir", os.path.join(tmpdir, "empty_dir")])
        assert rc != 0
        out_no_graph = capsys.readouterr().out
        assert "run `ad-graph build`" in out_no_graph


def test_summary_performance_on_this_repo(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = os.path.join(tmpdir, ".agent", "graph")
        build_graph(root=REPO_ROOT, out_dir=out_dir)

        t0 = time.time()
        rc = graph_main(["summary", REPO_ROOT, "--graph-dir", out_dir])
        elapsed = time.time() - t0

        assert rc == 0
        out = capsys.readouterr().out
        assert elapsed < 2.0  # Runs in under 2 seconds
        line_count = len(out.splitlines())
        assert line_count < 150  # Bounded TOON output


def test_pretty_rendering(monkeypatch, capsys):
    sample_root = os.path.join(FIXTURES_DIR, "sample_repo")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = os.path.join(tmpdir, ".agent", "graph")
        build_graph(root=sample_root, out_dir=out_dir)

        # Plain execution
        rc = graph_main(["summary", sample_root, "--graph-dir", out_dir])
        assert rc == 0
        plain_out = capsys.readouterr().out
        assert "meta:" in plain_out or "summary" in plain_out

        # Pretty execution
        rc = graph_main(["summary", "--pretty", sample_root, "--graph-dir", out_dir])
        assert rc == 0
        pretty_out = capsys.readouterr().out
        assert len(pretty_out) > 0
