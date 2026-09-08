"""Tests for stderr progress indication on long-running queries and operations."""
import sys
import pytest
from agentdata import ui
from agentdata import proc


def test_progress_writes_to_stderr_never_stdout(monkeypatch, capsys):
    monkeypatch.setenv("AGENTDATA_PROGRESS", "always")
    # conftest sets AGENTDATA_UI=plain so 700 other tests see deterministic TOON; these three
    # are about the rich progress indicator, so they ask for it back
    monkeypatch.delenv("AGENTDATA_UI", raising=False)
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    ui.reset_cache()

    with ui.progress("Testing operation..."):
        pass

    captured = capsys.readouterr()
    assert captured.out == "", "ui.progress must NEVER write to stdout"
    assert "Testing operation..." in captured.err, "ui.progress should write description to stderr"


def test_progress_is_noop_in_plain_mode(monkeypatch, capsys):
    monkeypatch.setenv("AGENTDATA_UI", "plain")
    monkeypatch.setenv("AGENTDATA_PROGRESS", "always")
    ui.reset_cache()

    with ui.progress("Testing operation..."):
        pass

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_progress_is_noop_when_stderr_not_tty_and_not_forced(monkeypatch, capsys):
    monkeypatch.delenv("AGENTDATA_PROGRESS", raising=False)
    monkeypatch.setenv("AGENTDATA_UI", "auto")
    ui.reset_cache()

    with ui.progress("Testing operation..."):
        pass

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_proc_run_with_progress(monkeypatch, capsys):
    monkeypatch.setenv("AGENTDATA_PROGRESS", "always")
    # conftest sets AGENTDATA_UI=plain so 700 other tests see deterministic TOON; these three
    # are about the rich progress indicator, so they ask for it back
    monkeypatch.delenv("AGENTDATA_UI", raising=False)
    ui.reset_cache()

    rc, out, err, el = proc.run([sys.executable, "-c", "print('hello')"], progress="Running python...")
    assert rc == 0
    assert out.strip() == "hello"
    captured = capsys.readouterr()
    assert captured.out == "", "proc.run progress must not leak to captured sys.stdout"
    assert "Running python..." in captured.err


def test_run_dax_with_progress(monkeypatch, capsys, tmp_path):
    from agentdata.pbip import dax

    monkeypatch.setenv("AGENTDATA_PROGRESS", "always")
    # conftest sets AGENTDATA_UI=plain so 700 other tests see deterministic TOON; these three
    # are about the rich progress indicator, so they ask for it back
    monkeypatch.delenv("AGENTDATA_UI", raising=False)
    ui.reset_cache()

    dummy_dscmd = tmp_path / "dscmd.exe"
    dummy_dscmd.write_text("echo", encoding="utf-8")

    def mock_run(args, timeout):
        # Write CSV output as dscmd would
        out_csv = args[2]
        with open(out_csv, "w", encoding="utf-8") as f:
            f.write("Col1,Col2\nVal1,Val2\n")
        return 0, "", ""

    table = dax.run_dax("EVALUATE {1}", "localhost:5000", str(dummy_dscmd), run=mock_run)
    assert table.columns == ["Col1", "Col2"]
    assert table.rows == [["Val1", "Val2"]]

    captured = capsys.readouterr()
    assert captured.out == "", "dax query execution must not write to stdout"
    assert "Running DAX query" in captured.err

