"""Fake external tools that behave like the real ones, on every OS.

Six tests in `tests/test_proc.py` were `skipif(os.name == "nt")` with the reason "POSIX shell
stand-in for pncli" — so the Windows behaviour of the module that exists *because of* Windows was
skipped on Windows. That is the gap this harness closes: a fake materialises as an npm-style
`.cmd` shim on Windows and an `sh` script on POSIX, and the same test runs on both.

A fake replays a **transcript** — real output captured from the real tool — chosen by
`AGENTDATA_FAKE_CASE`. A fake that invents output is worth less than no fake: it proves the code
handles a shape nobody has ever seen. Unknown arguments exit 99 and echo the argv, so a failing test
shows exactly what the code sent rather than a silent zero.

A fake must never touch the network and never read the real config.
"""
from __future__ import annotations
import json
import os
import stat
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOWS = os.name == "nt"

# `runner.py` is what every fake actually executes: one Python file, so the behaviour is identical
# on both platforms and only the shim around it differs.
RUNNER = os.path.join(HERE, "runner.py")

NPM_SHIM = """@ECHO OFF\r
SETLOCAL\r
IF EXIST "%~dp0\\node.exe" (\r
  "%~dp0\\node.exe" "%~dp0\\node_modules\\{package}\\bin\\cli.js" %*\r
) ELSE (\r
  "{python}" "{runner}" {tool} %*\r
)\r
"""

CMD_SHIM = """@ECHO OFF\r
"{python}" "{runner}" {tool} %*\r
"""

SH_SHIM = """#!/bin/sh
exec "{python}" "{runner}" {tool} "$@"
"""


def transcript_dir(tool: str) -> str:
    return os.path.join(HERE, tool, "transcripts")


def cases(tool: str) -> list[str]:
    d = transcript_dir(tool)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(n)[0] for n in os.listdir(d) if n.endswith(".json"))


def load_case(tool: str, case: str) -> dict[str, Any]:
    with open(os.path.join(transcript_dir(tool), f"{case}.json"), encoding="utf-8") as f:
        return json.load(f)


def _write_executable(path: str, text: str, *, crlf: bool) -> None:
    with open(path, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
        f.write(text)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def install(tmp_path, tools: list[str], *, case: str | None = None, npm: bool = True) -> dict[str, str]:
    """Materialise `tools` into a temp bin dir and return the environment to run them with.

    On Windows each tool becomes `<tool>.cmd` -- npm's real shim text when `npm=True`, because that
    is what `proc.py` has to unwrap -- plus an extension-less `sh` shim so Git Bash finds it too.
    On POSIX only the `sh` shim is written.
    """
    import sys

    bin_dir = os.path.join(str(tmp_path), "fakebin")
    os.makedirs(bin_dir, exist_ok=True)
    python = sys.executable

    for tool in tools:
        sh_path = os.path.join(bin_dir, tool)
        _write_executable(sh_path, SH_SHIM.format(python=python, runner=RUNNER, tool=tool), crlf=False)
        if WINDOWS:
            template = NPM_SHIM if npm else CMD_SHIM
            _write_executable(
                os.path.join(bin_dir, f"{tool}.cmd"),
                template.format(package=f"@kolatts/{tool}", python=python, runner=RUNNER, tool=tool),
                crlf=True,
            )

    env = dict(os.environ)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["AGENTDATA_FAKE_DIR"] = HERE
    if case:
        env["AGENTDATA_FAKE_CASE"] = case
    # `proc.py` looks for npm's global prefix under APPDATA; point it at the same place so the
    # resolution path is exercised rather than bypassed
    env["APPDATA"] = str(tmp_path)
    os.makedirs(os.path.join(str(tmp_path), "npm"), exist_ok=True)
    return env


def apply(monkeypatch, tmp_path, tools: list[str], *, case: str | None = None, npm: bool = True) -> str:
    """`install`, but pushed into `os.environ` for in-process code. Returns the bin directory."""
    env = install(tmp_path, tools, case=case, npm=npm)
    for key in ("PATH", "AGENTDATA_FAKE_DIR", "AGENTDATA_FAKE_CASE", "APPDATA"):
        if key in env:
            monkeypatch.setenv(key, env[key])
    return env["PATH"].split(os.pathsep)[0]
