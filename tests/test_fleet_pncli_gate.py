"""The fleet's pncli shim: a read reaches the real pncli untouched, a write is refused and the extension named.

pncli is used directly, so in a fleet the agent types `pncli ...` and `shell(pncli)` allows every verb. The gate
is the shim `launch.child_env` puts first on the agent's PATH (`agentdata/fleet/pncli_gate.py`). These run the
real shim file through a shell, against the recorded fake pncli (`tests/fakes/pncli/`), on every OS.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from agentdata.connectors import pncli as P
from agentdata.fleet import launch as L
from agentdata.fleet import pncli_gate as GATE
from agentdata.fleet import registry

import fakes

WINDOWS = os.name == "nt"


def _agent_env(tmp_path, case: str, *, in_fleet: bool = True) -> dict:
    """What a fleet agent's shell has: `child_env`'s PATH (the shim first) over the fake pncli's bin."""
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    base = fakes.install(tmp_path, ["pncli"], case=case)
    env = L.child_env("luna", str(fleet), login=lambda: {})
    shims = L.shim_dir(str(fleet))
    env["PATH"] = os.pathsep.join([shims, base["PATH"]])
    for key in ("AGENTDATA_FAKE_DIR", "AGENTDATA_FAKE_CASE", "AGENTDATA_FAKE_LOG", "APPDATA"):
        if key in base:
            env[key] = base[key]
    env["AGENTDATA_CONFIG"] = str(tmp_path / "cfg.json")
    env.pop("PNCLI_EXE", None)
    env.pop(GATE.GUARD_ENV, None)
    if not in_fleet:
        env.pop(registry.AGENT_ENV, None)
    return env


def _pncli(env: dict, *args: str, cwd) -> subprocess.CompletedProcess:
    """`pncli <args>` exactly as the agent's shell starts it: the first `pncli` on PATH is the shim."""
    shim = os.path.join(env[P.SHIM_ENV], "pncli.cmd" if WINDOWS else "pncli")
    return subprocess.run([shim, *args], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=60)


def test_a_read_passes_through_with_its_output_and_exit_code_untouched(tmp_path):
    env = _agent_env(tmp_path, "search_ok")
    got = _pncli(env, "jira", "search", "--jql", "key = RDSD-1", cwd=tmp_path)
    assert got.returncode == 0 and got.stdout == '{"issues": [{"key": "RDSD-1"}]}', got
    assert fakes.calls(env, "pncli") == [["jira", "search", "--jql", "key = RDSD-1"]]
    (tmp_path / "other").mkdir()
    bad = _agent_env(tmp_path / "other", "bad_json")
    got = _pncli(bad, "jira", "search", "--jql", "x", cwd=tmp_path)
    assert got.returncode == 3 and got.stdout == "not json", "pncli's own exit code, not the shim's"


@pytest.mark.parametrize("argv, hint", [
    (["confluence", "create-page", "--space", "RDSD", "--title", "T", "--body", "x"], "ad-confluence publish"),
    (["bitbucket", "create-pr", "--title", "RDSD-1: x"], "ad-git pr"),
    (["jira", "add-comment", "--key", "RDSD-1", "--body", "x"], "ad-jira comment"),
    (["jira", "transition", "--key", "RDSD-1", "--to", "Done"], "ad-jira transition"),
    (["config", "set", "--key", "x"], "ask the operator"),
])
def test_a_write_is_refused_with_the_extension_that_does_it(tmp_path, argv, hint):
    env = _agent_env(tmp_path, "search_ok")
    got = _pncli(env, *argv, cwd=tmp_path)
    assert got.returncode == 2, got
    assert "refused: pncli_write_in_fleet" in got.stdout and hint in got.stdout, got.stdout
    assert f"pncli {argv[0]} {argv[1]} writes to a system of record" in got.stdout
    assert fakes.calls(env, "pncli") == [], "a refused write never reaches pncli"


@pytest.mark.parametrize("argv", [["bitbucket", "create-pr", "--dry-run", "--title", "x"],
                                  ["confluence", "create-page", "--help"], ["--version"]])
def test_a_dry_run_help_or_version_passes(tmp_path, argv):
    env = _agent_env(tmp_path, "version" if argv == ["--version"] else "")
    got = _pncli(env, *argv, cwd=tmp_path)
    assert "pncli_write_in_fleet" not in got.stdout
    assert fakes.calls(env, "pncli") == [argv], "the real pncli was asked, with the same argv"


def test_outside_a_fleet_everything_passes(tmp_path):
    env = _agent_env(tmp_path, "search_ok", in_fleet=False)
    _pncli(env, "confluence", "create-page", "--title", "T", cwd=tmp_path)
    assert fakes.calls(env, "pncli") == [["confluence", "create-page", "--title", "T"]]


def test_the_shim_never_resolves_itself(tmp_path, monkeypatch):
    """Its own directory is left out of the search, a pin into it is ignored, and if it ever does start
    itself the guard stops it rather than looping."""
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    shims = L.write_shim(str(fleet))
    monkeypatch.setenv("PATH", os.pathsep.join([shims, os.environ.get("PATH", "")]))
    monkeypatch.setenv(P.SHIM_ENV, shims)
    monkeypatch.setenv("PNCLI_EXE", os.path.join(shims, "pncli"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    assert P.exe() is None, "a pin into the shim's directory is the gate, not pncli"
    assert shims not in (P.search_path() or "").split(os.pathsep)
    info = __import__("agentdata.proc", fromlist=["resolve"]).resolve("pncli", path=P.search_path())
    assert not info["found"] or os.path.dirname(os.path.abspath(info["path"])) != os.path.abspath(shims)
    monkeypatch.setenv(GATE.GUARD_ENV, "1")
    assert GATE.passthrough(["jira", "search"]) == 127


def test_child_env_puts_the_shim_first_and_writes_it_for_this_interpreter(tmp_path, monkeypatch):
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join(["/venv/bin", "/usr/bin"]))
    env = L.child_env("luna", str(fleet), login=lambda: {})
    shims = L.shim_dir(str(fleet))
    assert env["PATH"].split(os.pathsep)[0] == shims and env[P.SHIM_ENV] == shims
    posix = open(os.path.join(shims, "pncli"), encoding="utf-8", newline="").read()
    assert posix == f'#!/bin/sh\nexec "{sys.executable}" -m agentdata.fleet.pncli_gate "$@"\n'
    cmd = open(os.path.join(shims, "pncli.cmd"), encoding="utf-8", newline="").read()
    assert cmd == f'@"{sys.executable}" -m agentdata.fleet.pncli_gate %*\r\n'
    if not WINDOWS:
        assert os.stat(os.path.join(shims, "pncli")).st_mode & 0o777 == 0o755
    again = L.child_env("luna", str(fleet), login=lambda: {})
    assert again["PATH"].split(os.pathsep).count(shims) == 1, "idempotent: written once, listed once"
    assert L.child_env("luna", str(tmp_path / "missing"), login=lambda: {}).get(P.SHIM_ENV) is None
    assert not (tmp_path / "missing").exists(), "no fleet directory is created for the shim"


def test_the_deny_floor_no_longer_has_pncli_and_the_strict_allow_list_does():
    strict = {"fleet": {"permissions": "strict"}}
    assert "shell(pncli)" not in L.DEFAULT_DENY and "shell(pncli)" not in L.deny_tools(strict)
    assert "shell(pncli)" in L.allow_tools(strict)
    assert "shell(ad-git pr)" in L.allow_tools(strict)
    retired = "ad-" + "pncli"
    assert not any(retired in p for p in L.DEFAULT_ALLOW + L.DEFAULT_DENY)
