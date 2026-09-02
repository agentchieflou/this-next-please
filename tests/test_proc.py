"""Starting programs on Windows. `pncli` is an npm package: it exists as pncli.cmd, never pncli.exe, so handing the
bare name to CreateProcess fails with [WinError 2] — the 2026-09-02 laptop failure of `ad-pncli jira search`.
Windows behaviour is exercised on any OS through the `windows=` switch."""
import json
import os
import stat
import sys

import pytest

from agentdata import proc
from agentdata.connectors import pncli as P

NPM7_CMD = """@ECHO off\r
GOTO start\r
:find_dp0\r
SET dp0=%~dp0\r
EXIT /b\r
:start\r
SETLOCAL\r
CALL :find_dp0\r
IF EXIST "%dp0%\\node.exe" (SET "_prog=%dp0%\\node.exe") ELSE (SET "_prog=node")\r
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  "%dp0%\\node_modules\\@kolatts\\pncli\\bin\\cli.js" %*\r
"""
NPM6_CMD = '@IF EXIST "%~dp0\\node.exe" (\r\n  "%~dp0\\node.exe"  "%~dp0\\node_modules\\@kolatts\\pncli\\bin\\cli.js" %*\r\n)\r\n'
SH_SHIM = '#!/bin/sh\nbasedir=$(dirname "$0")\nexec node  "$basedir/node_modules/@kolatts/pncli/bin/cli.js" "$@"\n'


def npm_install(d, *, shim=NPM7_CMD, name="pncli", script=True, node=True):
    """A directory shaped like npm's global prefix on Windows."""
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, name + ".cmd"), "w", newline="").write(shim)
    open(os.path.join(d, name), "w", newline="\n").write(SH_SHIM)
    if node:
        open(os.path.join(d, "node.exe"), "w").write("")
    if script:
        bin_dir = os.path.join(d, "node_modules", "@kolatts", "pncli", "bin")
        os.makedirs(bin_dir, exist_ok=True)
        open(os.path.join(bin_dir, "cli.js"), "w").write("// entry point\n")
    return d


def test_which_prefers_exe_then_cmd_and_finds_the_shim(tmp_path):
    d = npm_install(str(tmp_path / "npm"))
    assert proc.which("pncli", path=d, windows=True) == os.path.normpath(os.path.join(d, "pncli.cmd"))
    assert proc.which("pncli", path=d, windows=True, pathext=".COM;.EXE;.BAT;.CMD").endswith("pncli.cmd")
    open(os.path.join(d, "pncli.exe"), "w").write("")
    assert proc.which("pncli", path=d, windows=True).endswith("pncli.exe")   # a real executable wins
    assert proc.which("pncli.cmd", path=d, windows=True).endswith("pncli.cmd")
    assert proc.which("nope", path=d, windows=True) is None
    assert proc.which(os.path.join(d, "pncli"), windows=True).endswith("pncli.exe")   # a pinned path gets PATHEXT too
    assert proc.which(os.path.join(npm_install(str(tmp_path / "n2")), "pncli"), windows=True).endswith("pncli.cmd")


def test_unwrap_npm_shim_for_every_shim_style(tmp_path):
    for i, shim in enumerate((NPM7_CMD, NPM6_CMD)):
        d = npm_install(str(tmp_path / f"npm{i}"), shim=shim)
        node, script = proc.unwrap_shim(os.path.join(d, "pncli.cmd"), windows=True)
        assert node.endswith("node.exe") and script.endswith(os.path.join("bin", "cli.js")) and os.path.isfile(script)
    d = npm_install(str(tmp_path / "sh"), node=False)
    got = proc.unwrap_shim(os.path.join(d, "pncli"), windows=False)
    assert got is None or got[1].endswith("cli.js")          # depends on a `node` being installed here
    d2 = npm_install(str(tmp_path / "broken"), script=False)  # shim present, entry point gone
    assert proc.unwrap_shim(os.path.join(d2, "pncli.cmd"), windows=True) is None


def test_command_runs_the_node_entry_point_not_cmd_exe(tmp_path):
    d = npm_install(str(tmp_path / "npm"))
    jql = "project = RDSD AND updated >= '2026-01-01'"
    argv = proc.command(["pncli", "jira", "search", "--jql", jql], windows=True, path=d)
    assert argv[0].endswith("node.exe") and argv[1].endswith("cli.js") and argv[2:] == ["jira", "search", "--jql", jql]
    info = proc.resolve("pncli", windows=True, path=d)
    assert info["kind"] == "npm shim" and info["found"] and info["path"].endswith("pncli.cmd")


def test_command_falls_back_to_cmd_exe_with_safe_quoting(tmp_path, monkeypatch):
    d = npm_install(str(tmp_path / "npm"), script=False)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    argv = proc.command(["pncli", "jira", "search", "--jql", "a >= b"], windows=True, path=d)
    assert argv[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert argv[4].startswith('""') and argv[4].endswith('"') and '"a >= b"' in argv[4]   # `>` stays inside quotes
    assert argv[4].count('"pncli.cmd"') == 0 and '/npm/pncli.cmd"' in argv[4]              # the exe path is quoted too
    assert proc.resolve("pncli", windows=True, path=d)["kind"] == "cmd shim"
    assert proc.cmd_line(["x.cmd", "plain", 'say "hi"']) == '""x.cmd" "plain" "say ""hi""""'
    with pytest.raises(proc.ProcError) as e:
        proc.cmd_line(["x.cmd", "%USERPROFILE%"])
    assert e.value.code == "cmd_unsafe_argument" and "PNCLI_EXE" in e.value.hint


def test_not_found_names_what_was_tried(tmp_path):
    with pytest.raises(proc.ProcError) as e:
        proc.command(["pncli", "jira"], windows=True, path=str(tmp_path), hint="install pncli")
    assert e.value.code == "not_found" and e.value.hint == "install pncli"
    assert any("PATHEXT" in t for t in e.value.detail["tried"])
    info = proc.resolve("pncli", exe=str(tmp_path / "gone.cmd"), windows=True)
    assert not info["found"] and "configured path not found" in info["error"]


def test_run_returns_streams_and_reports_start_failure(tmp_path):
    rc, out, err, el = proc.run([sys.executable, "-c", "print('hi')"])
    assert rc == 0 and out.strip() == "hi" and err == "" and el >= 0
    with pytest.raises(proc.ProcError) as e:
        proc.run(["definitely-not-installed-xyz", "--version"])
    assert e.value.code == "not_found"
    with pytest.raises(proc.ProcError) as e:
        proc.run([sys.executable, "-c", "import sys; sys.exit(3)"], check=True)
    assert e.value.code == "exit_code" and e.value.detail["exit_code"] == 3


def _fake_pncli(tmp_path, body: str) -> str:
    p = tmp_path / "pncli-fake"
    p.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell stand-in for pncli")
def test_pncli_run_surfaces_exit_code_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, 'echo \'{"issues": [{"key": "RDSD-1"}]}\''))
    payload, el = P.run(["jira", "search", "--jql", "key = RDSD-1"])
    assert payload["issues"][0]["key"] == "RDSD-1" and el >= 0
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, 'echo "not json"; exit 3'))
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "bad_output" and e.value.detail["exit_code"] == 3 and "not json" in e.value.msg
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, 'echo \'{"ok": false, "error": "bad JQL"}\''))
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "pncli_error" and e.value.msg == "bad JQL"
    monkeypatch.setenv("PNCLI_EXE", str(tmp_path / "gone.cmd"))
    with pytest.raises(proc.ProcError) as e:
        P.run(["jira", "search"])
    assert e.value.code == "not_found" and "npm install -g @kolatts/pncli" in e.value.hint and "no pncli.exe" not in e.value.hint


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell stand-in for pncli")
def test_pncli_where_and_install_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("PNCLI_EXE", _fake_pncli(tmp_path, 'echo "pncli/1.4.0"'))
    info = P.where()
    assert info["found"] and info["rc"] == 0 and info["version"] == "pncli/1.4.0" and info["kind"] == "executable"
    monkeypatch.delenv("PNCLI_EXE")
    with open(tmp_path / "cfg.json", "w", encoding="utf-8") as f:
        json.dump({"pncli": {"npm_package": "@acme/pncli"}}, f)
    assert "@acme/pncli" in P.install_hint()
