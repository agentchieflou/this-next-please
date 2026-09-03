"""Colour: on for a human terminal (including PowerShell 5.1, PyCharm, VS Code), never for a pipe."""
import io
import os

import pytest

from agentdata import color
from agentdata import policy
from agentdata.setup import wizard as W


@pytest.fixture(autouse=True)
def _reset():
    color.reset_cache()
    yield
    color.reset_cache()


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_never_colours_a_pipe_and_honours_the_env(monkeypatch):
    for var in ("AGENTDATA_COLOR", "NO_COLOR", "FORCE_COLOR", "TERM", "PYCHARM_HOSTED", "TERM_PROGRAM", "WT_SESSION"):
        monkeypatch.delenv(var, raising=False)
    assert color._detect(io.StringIO()) is False                    # a pipe: an agent or a log file is reading
    monkeypatch.setenv("NO_COLOR", "1")
    assert color._detect(Tty()) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("AGENTDATA_COLOR", "never")
    assert color._detect(Tty()) is False
    monkeypatch.setenv("AGENTDATA_COLOR", "always")
    assert color._detect(io.StringIO()) is True                     # forced even when piped
    monkeypatch.delenv("AGENTDATA_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert color._detect(Tty()) is False


@pytest.mark.skipif(os.name == "nt", reason="the Windows path needs the console API")
def test_pycharm_and_vscode_count_as_terminals(monkeypatch):
    for var in ("AGENTDATA_COLOR", "NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PYCHARM_HOSTED", "1")
    assert color._detect(io.StringIO()) is True                     # PyCharm's run window is not a TTY but renders ANSI
    monkeypatch.delenv("PYCHARM_HOSTED")
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    assert color._detect(io.StringIO()) is True


def test_paint_and_status_are_reversible_and_safe():
    color.set_enabled(False)
    assert color.paint("x", "red") == "x" and color.status("fail") == "fail"
    color.set_enabled(True)
    painted = color.paint("x", "red", "bold")
    assert painted == "\x1b[31;1mx\x1b[0m" and color.strip(painted) == "x"
    assert color.strip(color.status("ok")) == "ok" and color.strip(color.status("warn")) == "warn"
    assert color.paint("x", "not-a-style") == "x" and color.paint("", "red") == ""
    assert "," not in color.status("fail") and ":" not in color.status("fail")   # never breaks a TOON cell


def test_toon_stays_parseable_and_uncoloured_when_piped(capsys):
    color.set_enabled(False)
    assert "\x1b[" not in policy.error("boom", "do this", "src")
    color.set_enabled(True)
    out = policy.error("boom", "do this", "src")
    assert "\x1b[" in out and color.strip(out).splitlines()[-1].strip() == "hint: do this"
    row = W.Check("sources", "oracle:prod", "fail", "detail", "hint").row()
    assert color.strip(row[2]) == "fail" and row[0] == "sources"
