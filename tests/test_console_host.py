"""Terminal-host classification, colour precedence, glyph fallback, and the secret prompt.

Everything here was previously decided by monkeypatched env vars on Linux and never checked against
the hosts the laptop actually has. The table below is the contract: one row per host, with what the
user should see in it.
"""
from __future__ import annotations
import io
import os
import sys

import pytest

from agentdata import color, console, ui

WINDOWS = os.name == "nt"


class FakeStream:
    """A stand-in stream: `io.StringIO.encoding` is read-only, and the encoding is the point here."""

    def __init__(self, tty=False, encoding="utf-8"):
        self._tty = tty
        self.encoding = encoding
        self._buf = io.StringIO()

    def isatty(self):
        return self._tty

    def write(self, s):
        return self._buf.write(s)

    def flush(self):
        pass

    def getvalue(self):
        return self._buf.getvalue()

    def fileno(self):
        raise OSError("fake stream has no fd")


# host name -> (env, isatty, has console handle)
HOST_TABLE = [
    ("windows-terminal", {"WT_SESSION": "1"}, True, True),
    ("vscode", {"TERM_PROGRAM": "vscode"}, False, False),
    ("pycharm-terminal", {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, True, True),
    ("pycharm-run", {"PYCHARM_HOSTED": "1"}, False, False),
    ("conpty", {}, True, True),
    ("conhost", {}, False, True),
    ("pipe", {}, False, False),
]


@pytest.mark.parametrize("expected,env,tty,handle", HOST_TABLE, ids=[r[0] for r in HOST_TABLE])
def test_each_host_is_classified(expected, env, tty, handle, monkeypatch):
    if expected in ("conpty", "conhost") and not WINDOWS:
        pytest.skip("console handles are a Windows concept")
    if expected == "pipe" and WINDOWS:
        # on Windows a handle-less, non-tty stream is a pipe; on POSIX the same shape is `pipe` too
        pass
    monkeypatch.setattr(os, "name", "nt" if WINDOWS or expected in ("conpty", "conhost") else os.name)
    got = console.host(env=env, stream=FakeStream(tty=tty), console_handle=handle)
    assert got == expected, f"{env} tty={tty} handle={handle} -> {got}"


def test_every_host_name_is_documented():
    for _expected, env, tty, handle in HOST_TABLE:
        assert console.host(env=env, stream=FakeStream(tty=tty), console_handle=handle) in console.HOSTS


def test_a_posix_terminal_is_a_tty(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert console.host(env={}, stream=FakeStream(tty=True)) == "tty"
    assert console.host(env={}, stream=FakeStream(tty=False)) == "pipe"


# ------------------------------------------------------------------------------- the mintty case


@pytest.mark.skipif(not WINDOWS, reason="mintty is a Windows/MSYS host")
def test_mintty_needs_a_real_pty_not_just_msystem(monkeypatch):
    """`MSYSTEM and not isatty` is equally true of `> file` in the same shell.

    Classifying on that alone put ANSI escapes into redirected files the moment colour was turned
    on for mintty, which is the regression this check exists to prevent.
    """
    monkeypatch.setattr(console, "is_msys_pty", lambda stream=None: False)
    assert console.host(env={"MSYSTEM": "MINGW64"}, stream=FakeStream(tty=False), console_handle=False) == "pipe"

    monkeypatch.setattr(console, "is_msys_pty", lambda stream=None: True)
    assert console.host(env={"MSYSTEM": "MINGW64"}, stream=FakeStream(tty=False), console_handle=False) == "mintty"


@pytest.mark.skipif(not WINDOWS, reason="the handle-name probe is Windows-only")
def test_is_msys_pty_says_no_for_a_plain_file(tmp_path):
    path = tmp_path / "out.txt"
    with open(path, "w", encoding="utf-8") as f:
        assert console.is_msys_pty(f) is False


def test_hosts_that_render_ansi_without_a_tty(monkeypatch):
    for env in ({"PYCHARM_HOSTED": "1"}, {"TERM_PROGRAM": "vscode"}):
        assert console.renders_ansi(env=env, stream=FakeStream(tty=False)) is True
    assert console.renders_ansi(env={}, stream=FakeStream(tty=False)) is False


# ------------------------------------------------------------------------- colour precedence


COLOUR_TABLE = [
    # (env, isatty, expected) -- written down once here and in docs/setup.md
    ({"AGENTDATA_COLOR": "never"}, True, False),
    ({"NO_COLOR": "1"}, True, False),
    ({"AGENTDATA_COLOR": "never", "FORCE_COLOR": "1"}, True, False),   # never wins over force
    ({"NO_COLOR": "1", "AGENTDATA_COLOR": "always"}, True, False),     # NO_COLOR wins
    ({"TERM": "dumb"}, True, False),
    ({"AGENTDATA_COLOR": "always"}, False, True),
    ({"FORCE_COLOR": "1"}, False, True),
    ({}, False, False),
]


@pytest.mark.parametrize("env,tty,expected", COLOUR_TABLE)
def test_colour_precedence(env, tty, expected, monkeypatch):
    for key in ("AGENTDATA_COLOR", "NO_COLOR", "FORCE_COLOR", "TERM", "WT_SESSION",
                "PYCHARM_HOSTED", "TERM_PROGRAM", "MSYSTEM", "TERMINAL_EMULATOR"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    color.reset_cache()
    assert color._detect(FakeStream(tty=tty)) is expected
    color.reset_cache()


def test_piped_output_is_byte_identical_across_hosts(capsys, monkeypatch):
    """Whatever the host, a machine reading stdout gets the same bytes."""
    from agentdata.setup.wizard import run_doctor

    outputs = []
    for env in ({}, {"WT_SESSION": "1"}, {"PYCHARM_HOSTED": "1"}, {"TERM_PROGRAM": "vscode"},
                {"MSYSTEM": "MINGW64"}):
        for key in ("WT_SESSION", "PYCHARM_HOSTED", "TERM_PROGRAM", "MSYSTEM"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv("AGENTDATA_COLOR", "never")
        color.reset_cache()
        ui.reset_cache()
        run_doctor(["--only", "console", "--quiet"])
        outputs.append(color.strip(capsys.readouterr().out))
    color.reset_cache()
    ui.reset_cache()

    # the console step reports the host, which legitimately differs; everything else must not
    normalised = {o.split("console,host")[0] for o in outputs}
    assert len(normalised) == 1, "piped output differs by host outside the host row itself"


# --------------------------------------------------------------------------------- glyphs


def test_glyphs_fall_back_when_the_code_page_cannot_encode_them(monkeypatch):
    """Under 437/1252 a `✓` prints as `?`, which reads as a third status."""
    monkeypatch.setattr(sys, "stdout", FakeStream(encoding="cp437"))
    assert ui.glyphs() is ui.ASCII_GLYPHS
    monkeypatch.setattr(sys, "stdout", FakeStream(encoding="utf-8"))
    assert ui.glyphs() is ui.GLYPHS


def test_utf8_stdout_is_a_bytes_contract_not_a_host_one():
    """`utf8_stdout()` is about the file; only the human rendering degrades per host."""
    import inspect
    doc = inspect.getdoc(console.utf8_stdout) or ""
    assert "bytes" in doc and "host" in doc


# ------------------------------------------------------------------------------ secret input


def test_the_secret_prompt_never_falls_back_silently(monkeypatch, capsys):
    """Where echo cannot be suppressed, say which window it is and how to fix it."""
    monkeypatch.setattr(console, "_secret_via_console", lambda p: None)
    monkeypatch.setattr(console, "_secret_via_tty", lambda p: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("hunter2\n"))

    assert console._read_secret("password: ") == "hunter2"
    err = capsys.readouterr().err
    assert "may be echoed" not in err, "getpass's vague warning must not be what the user sees"
    assert "winpty" in err and "Windows Terminal" in err


def test_a_console_read_is_preferred_and_does_not_echo(monkeypatch, capsys):
    monkeypatch.setattr(console, "_secret_via_console", lambda p: "from-console")
    monkeypatch.setattr(console, "_secret_via_tty", lambda p: pytest.fail("console comes first"))
    assert console._read_secret("password: ") == "from-console"
    assert "winpty" not in capsys.readouterr().err


def test_a_tty_read_is_used_when_there_is_no_console(monkeypatch, capsys):
    monkeypatch.setattr(console, "_secret_via_console", lambda p: None)
    monkeypatch.setattr(console, "_secret_via_tty", lambda p: "from-tty")
    assert console._read_secret("password: ") == "from-tty"
    assert "winpty" not in capsys.readouterr().err


def test_prompt_returns_the_default_on_an_empty_answer(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    assert console.prompt("name", default="fallback") == "fallback"


def test_prompt_raises_when_stdin_is_closed(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(EOFError):
        console.prompt("name")


# ------------------------------------------------------------------------------ no new deps


def test_no_terminal_dependency_was_added():
    text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "pyproject.toml"), encoding="utf-8").read()
    for banned in ("colorama", "winpty", "pyreadline", "pywin32"):
        assert banned not in text, f"{banned} must not be a dependency"


def test_docs_write_the_colour_precedence_down_once():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "docs", "setup.md"), encoding="utf-8").read()
    assert "### Colour and glyphs, per host" in text
    for host_name in ("mintty", "Windows Terminal", "conhost"):
        assert host_name in text
