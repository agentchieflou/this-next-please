"""The fleet's toil shim: a read reaches the real toil untouched, a write is refused and the extension named.

toil is used directly, so in a fleet the agent types `toil ...` and `shell(toil)` allows every command. The gate
is the shim `launch.child_env` puts first on the agent's PATH (`agentdata/fleet/toil_gate.py`). These run the
real shim file through a shell, against the recorded fake toil (`tests/fakes/toil/`), on every OS.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from agentdata.connectors import toil as T
from agentdata.fleet import launch as L
from agentdata.fleet import toil_gate as GATE
from agentdata.fleet import registry

import fakes

WINDOWS = os.name == "nt"


def _agent_env(tmp_path, case: str, *, in_fleet: bool = True) -> dict:
    """What a fleet agent's shell has: `child_env`'s PATH (the shim first) over the fake toil's bin."""
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    base = fakes.install(tmp_path, ["toil"], case=case)
    env = L.child_env("luna", str(fleet), login=lambda: {})
    shims = L.shim_dir(str(fleet))
    env["PATH"] = os.pathsep.join([shims, base["PATH"]])
    for key in ("AGENTDATA_FAKE_DIR", "AGENTDATA_FAKE_CASE", "AGENTDATA_FAKE_LOG", "APPDATA"):
        if key in base:
            env[key] = base[key]
    env["AGENTDATA_CONFIG"] = str(tmp_path / "cfg.json")
    env.pop("TOIL_EXE", None)
    env.pop(GATE.GUARD_ENV, None)
    if not in_fleet:
        env.pop(registry.AGENT_ENV, None)
    return env


def _toil(env: dict, *args: str, cwd) -> subprocess.CompletedProcess:
    """`toil <args>` exactly as the agent's shell starts it: the first `toil` on PATH is the shim."""
    shim = os.path.join(env[T.SHIM_ENV], "toil.cmd" if WINDOWS else "toil")
    return subprocess.run([shim, *args], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=60)


def test_a_read_passes_through_with_its_output_and_exit_code_untouched(tmp_path):
    env = _agent_env(tmp_path, "search_ok")
    got = _toil(env, "jira", "issue", "search", "--jql", "key = RDSD-22399", cwd=tmp_path)
    assert got.returncode == 0 and got.stdout.startswith('{"ok":true'), got
    assert fakes.calls(env, "toil") == [["jira", "issue", "search", "--jql", "key = RDSD-22399"]]
    (tmp_path / "other").mkdir()
    missing = _agent_env(tmp_path / "other", "not_found")
    got = _toil(missing, "jira", "issue", "get", "NOPE-1", cwd=tmp_path)
    assert got.returncode == 1 and '"code":"NOT_FOUND"' in got.stdout, "toil's own exit code, not the shim's"


@pytest.mark.parametrize("argv, hint", [
    (["confluence", "page", "create", "--space", "RDSD", "--title", "T", "--body-file", "-", "--allow-write"],
     "ad-confluence publish"),
    (["bitbucket", "pr", "create", "--title", "RDSD-1: x", "--allow-write"], "ad-git pr"),
    (["bitbucket", "pr", "merge", "42", "--allow-write"], "ad-git pr"),
    (["jira", "issue", "comment", "RDSD-1", "--body", "x", "--allow-write"], "ad-jira comment"),
    (["jira", "issue", "transition", "RDSD-1", "--to", "done", "--allow-write"], "ad-jira transition"),
    (["jira", "api", "POST", "rest/api/2/issue", "--body-file", "x.json", "--allow-write"], "ad-jira"),
    (["--allow-write", "jira", "issue", "transition", "RDSD-1", "--to", "done"], "ad-jira transition"),
    (["jenkins", "run", "start", "deploy", "--allow-write=true"], "ask the operator"),
    (["connections", "add", "corp", "--area", "jira"], "ask the operator"),
    (["dossiers", "init", "pay"], "ask the operator"),
    (["skill", "install", "--claude"], "ask the operator"),
    (["feedback", "bug", "--consent"], "ask the operator"),
    (["mcp", "--areas", "jira"], "ask the operator"),
])
def test_a_write_is_refused_with_the_extension_that_does_it(tmp_path, argv, hint):
    env = _agent_env(tmp_path, "search_ok")
    got = _toil(env, *argv, cwd=tmp_path)
    assert got.returncode == 2, got
    assert "refused: toil_write_in_fleet" in got.stdout and hint in got.stdout, got.stdout
    assert fakes.calls(env, "toil") == [], "a refused write never reaches toil"


@pytest.mark.parametrize("argv", [["jira", "issue", "get", "RDSD-22399"],
                                  ["confluence", "page", "create", "--help"], ["version"],
                                  ["connections", "list"], ["dossiers", "show"],
                                  ["--workspace", "connections", "jira", "issue", "get", "X-1"]])
def test_a_read_help_or_listing_passes(tmp_path, argv):
    env = _agent_env(tmp_path, "")
    got = _toil(env, *argv, cwd=tmp_path)
    assert "toil_write_in_fleet" not in got.stdout
    assert fakes.calls(env, "toil") == [argv], "the real toil was asked, with the same argv"


def test_outside_a_fleet_everything_passes(tmp_path):
    env = _agent_env(tmp_path, "page_created", in_fleet=False)
    _toil(env, "confluence", "page", "create", "--title", "T", "--allow-write", cwd=tmp_path)
    assert fakes.calls(env, "toil") == [["confluence", "page", "create", "--title", "T", "--allow-write"]]


def test_the_shim_never_resolves_itself(tmp_path, monkeypatch):
    """Its own directory is left out of the search, a pin into it is ignored, and if it ever does start
    itself the guard stops it rather than looping."""
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    shims = L.write_shim(str(fleet))
    monkeypatch.setenv("PATH", os.pathsep.join([shims, os.environ.get("PATH", "")]))
    monkeypatch.setenv(T.SHIM_ENV, shims)
    monkeypatch.setenv("TOIL_EXE", os.path.join(shims, "toil"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    assert T.exe() is None, "a pin into the shim's directory is the gate, not toil"
    assert shims not in (T.search_path() or "").split(os.pathsep)
    info = __import__("agentdata.proc", fromlist=["resolve"]).resolve("toil", path=T.search_path())
    assert not info["found"] or os.path.dirname(os.path.abspath(info["path"])) != os.path.abspath(shims)
    monkeypatch.setenv(GATE.GUARD_ENV, "1")
    assert GATE.passthrough(["jira", "issue", "search"]) == 127


def test_child_env_puts_the_shim_first_and_writes_it_for_this_interpreter(tmp_path, monkeypatch):
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join(["/venv/bin", "/usr/bin"]))
    env = L.child_env("luna", str(fleet), login=lambda: {})
    shims = L.shim_dir(str(fleet))
    assert env["PATH"].split(os.pathsep)[0] == shims and env[T.SHIM_ENV] == shims
    posix = open(os.path.join(shims, "toil"), encoding="utf-8", newline="").read()
    assert posix == f'#!/bin/sh\nexec "{sys.executable}" -m agentdata.fleet.toil_gate "$@"\n'
    cmd = open(os.path.join(shims, "toil.cmd"), encoding="utf-8", newline="").read()
    assert cmd == f'@"{sys.executable}" -m agentdata.fleet.toil_gate %*\r\n'
    if not WINDOWS:
        assert os.stat(os.path.join(shims, "toil")).st_mode & 0o777 == 0o755
    again = L.child_env("luna", str(fleet), login=lambda: {})
    assert again["PATH"].split(os.pathsep).count(shims) == 1, "idempotent: written once, listed once"
    assert L.child_env("luna", str(tmp_path / "missing"), login=lambda: {}).get(T.SHIM_ENV) is None
    assert not (tmp_path / "missing").exists(), "no fleet directory is created for the shim"


def test_the_retired_pncli_shim_is_removed(tmp_path):
    fleet = tmp_path / "fleet"
    shims = L.shim_dir(str(fleet))
    os.makedirs(shims)
    for name in ("pncli", "pncli.cmd"):
        (tmp_path / "fleet" / "bin" / name).write_text("old shim", encoding="utf-8")
    L.write_shim(str(fleet))
    assert sorted(os.listdir(shims)) == ["toil", "toil.cmd"]


def test_toil_is_allowed_and_never_on_the_deny_floor():
    strict = {"fleet": {"permissions": "strict"}}
    assert "shell(toil)" not in L.DEFAULT_DENY and "shell(toil)" not in L.deny_tools(strict)
    assert "shell(toil)" in L.allow_tools(strict)
    assert "shell(ad-git pr)" in L.allow_tools(strict)
    assert not any("pncli" in p for p in L.DEFAULT_ALLOW + L.DEFAULT_DENY)
