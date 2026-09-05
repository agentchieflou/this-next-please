"""The fleet supervisor: registration, the launch line, and one agent per repository.

No real `copilot` is started here. The CLI is replaced by a fake through the `tests/fakes/` harness
(#72), because what needs proving is *what the supervisor asks for* and *what it refuses* — the
allow-list, the lock, the fact that the repository's `.agent/` is never written. The real binary is
the laptop runbook's job (#102), and the event shapes it produces are recorded in
`docs/fleet-spike.md`.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.fleet import launch, registry, supervisor
from agentdata.fleet.registry import Registry, RegistryError


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    """A fleet directory of our own, so nothing here can see a developer's real one."""
    home = tmp_path / "fleet"
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(home))
    return home


def make_project(root, *, phase="idle", ticket="", project="RDSD") -> str:
    """A folder shaped like something `ad-setup --project` produced."""
    root = str(root)
    os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Project\n\n- jira_project: {project}\n")
    with open(os.path.join(root, ".agent", "state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"project": project, "phase": phase, "active_ticket": ticket}, f)
    return root


# ------------------------------------------------------------------------------- the registry


def test_a_folder_that_is_not_a_project_is_refused(fleet_home, tmp_path):
    """An agent needs AGENTS.md and .agent/state.json; without them it has no facts and no state."""
    plain = tmp_path / "just-a-folder"
    plain.mkdir()
    with pytest.raises(RegistryError) as e:
        Registry().add(str(plain))
    assert "not an agent project" in e.value.msg
    assert "ad-setup --project" in e.value.hint


def test_registration_is_explicit_and_round_trips(fleet_home, tmp_path):
    repo = make_project(tmp_path / "repo-a", project="RDSD")
    added = Registry().add(repo, name="a")
    assert added.name == "a" and added.jira_project == "RDSD"

    again = Registry()
    assert list(again.repos) == ["a"]
    assert again.get("a").path.endswith("repo-a")

    again.remove("a")
    assert list(Registry().repos) == []


def test_an_unknown_repo_names_the_ones_that_exist(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "known"), name="known")
    with pytest.raises(RegistryError) as e:
        Registry().get("nope")
    assert "known" in e.value.hint, e.value.hint


def test_two_repos_cannot_share_a_name(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "one"), name="dup")
    with pytest.raises(RegistryError) as e:
        Registry().add(make_project(tmp_path / "two"), name="dup")
    assert "--name" in e.value.hint


# ------------------------------------------------------------------------------ the launch line


def test_the_launch_line_never_grants_blanket_permission():
    argv = launch.launch_command("copilot", "C:/repo", "do the thing", log_dir="C:/logs")
    joined = " ".join(argv)
    for forbidden in launch.FORBIDDEN_FLAGS:
        assert forbidden not in joined, f"{forbidden} reached the launch line"
    assert "--no-ask-user" in argv, "headless, there is nobody to ask"
    # The CLI ships a built-in MCP server, so epic #91's no-MCP rule is an argument, not an absence.
    assert "--disable-builtin-mcps" in argv
    assert "--output-format" in argv and "json" in argv


def _patterns(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_the_allow_list_never_grants_the_agent_the_fleet_itself():
    """`shell(ad-)` would have. It is a PREFIX, so it covers every console script this package
    installs -- including `ad-fleet`, which reads every *other* registered repository's
    `.agent/state.json` (AGENTS.md rule 3, broken from inside an agent) and can stop other agents."""
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs")
    allowed = _patterns(argv, "--allow-tool")
    assert "shell(ad-)" not in allowed, "the family prefix would include ad-fleet and ad-update"
    assert "shell(ad-state)" in allowed, allowed
    assert "skill" in allowed, "without the skill tool the router cannot run"

    denied = _patterns(argv, "--deny-tool")
    for forbidden in ("shell(ad-fleet)", "shell(ad-update)", "shell(ad-setup)"):
        assert forbidden in denied, f"{forbidden} must be denied outright"


def test_a_deny_prefix_cannot_rescue_a_loose_allow_so_the_allow_is_tight():
    """A deny is a prefix too, not a substring: `shell(git push --force)` does not match
    `git push -u origin HEAD --force`. So the allow-list has to stop before the dangerous
    continuation can be appended -- there is no push allow at all, and commit stops at `-m`."""
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs")
    allowed, denied = _patterns(argv, "--allow-tool"), _patterns(argv, "--deny-tool")

    assert not any(a.startswith("shell(git push") for a in allowed), allowed
    assert "shell(git commit -m)" in allowed
    assert "shell(git commit)" not in allowed, "that would also permit `git commit --no-verify`"
    assert "shell(git push)" in denied and "shell(git commit --no-verify)" in denied


def test_configuration_can_narrow_the_allow_list_but_never_the_deny_list():
    """An operator adding one deny must not silently lose the rest. `--show-launch` would have
    printed the loss as though it were the guarantee."""
    cfg = {"fleet": {"allow_tools": ["shell(ad-state)"], "deny_tools": ["shell(npm)"]}}
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=cfg)
    allowed, denied = _patterns(argv, "--allow-tool"), _patterns(argv, "--deny-tool")

    assert allowed == ["shell(ad-state)"], "configuration narrows the allow-list"
    assert "shell(npm)" in denied, "and adds to the deny-list"
    for floor in launch.DEFAULT_DENY:
        assert floor in denied, f"{floor} is a floor, not a default"


@pytest.mark.parametrize("bad", ["--allow-all", "--yolo", "--allow-all-tools"])
def test_a_config_that_asks_for_blanket_permission_is_refused_by_name(bad):
    """Not filtered out quietly: the operator who wrote it believes the fleet runs that way, and
    the gap between what they believe and what runs is the whole risk."""
    cfg = {"fleet": {"allow_tools": ["shell(ad-)", bad]}}
    with pytest.raises(launch.LaunchError) as e:
        launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=cfg)
    assert bad in e.value.msg
    assert "shell(" in e.value.hint


def test_the_prompt_template_is_configurable_and_defaults_to_the_router():
    assert "session-bootstrap" in launch.prompt_for("RDSD-1", None, {})
    assert launch.prompt_for("RDSD-1", None, {}).startswith("Ticket RDSD-1.")
    assert launch.prompt_for(None, "just do this", {}) == "just do this"
    cfg = {"fleet": {"prompt_template": "work {key} now"}}
    assert launch.prompt_for("X-9", None, cfg) == "work X-9 now"


def test_the_child_carries_the_markers_the_approval_gate_keys_on():
    env = launch.child_env("repo-a", "C:/fleet")
    assert env[registry.AGENT_ENV] == "repo-a"
    assert env[registry.FLEET_DIR_ENV] == "C:/fleet"
    assert env["AGENTDATA_COLOR"] == "never", "the events are read by a machine"


# --------------------------------------------------------------------------------- the agent


def _fake_copilot(tmp_path) -> str:
    """A stand-in `copilot` that emits two plausible JSONL events and exits.

    An npm-style `.cmd` on Windows, which is the shape `proc.resolve` has to unwrap -- `copilot` is
    installed by npm and exists as `copilot.cmd`, never `copilot.exe`.
    """
    import sys

    script = tmp_path / "fake_copilot.py"
    script.write_text(
        "import json, sys, time\n"
        "print(json.dumps({'type': 'assistant.message', 'timestamp': '2026-01-01T00:00:00Z',\n"
        "                  'data': {'content': 'hello', 'toolRequests': []}}), flush=True)\n"
        "print(json.dumps({'type': 'result', 'timestamp': '2026-01-01T00:00:01Z',\n"
        "                  'sessionId': 'sess-1', 'exitCode': 0,\n"
        "                  'usage': {'premiumRequests': 0.33}}), flush=True)\n",
        encoding="utf-8", newline="\n")
    if os.name == "nt":
        shim = tmp_path / "copilot.cmd"
        shim.write_text(f'@ECHO OFF\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8", newline="")
    else:
        shim = tmp_path / "copilot"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                        encoding="utf-8", newline="\n")
        os.chmod(shim, 0o755)
    return str(shim)


def test_the_supervisor_starts_an_agent_and_never_writes_the_repo(fleet_home, tmp_path):
    """The repository belongs to the agent. `ad-state` is the only writer of `state.json`, and a
    supervisor that edited it would be a second source of truth."""
    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    before = _tree(repo)

    lock = supervisor.start("a", key="RDSD-1", exe=_fake_copilot(tmp_path))
    assert lock["pid"] > 0
    _settle("a")

    assert _tree(repo) == before, "the fleet wrote inside the agent's repository"
    events = supervisor.read_events("a")
    assert [e["type"] for e in events] == ["assistant.message", "result"]
    assert supervisor.session_id("a") == "sess-1"


def test_a_second_start_is_refused_while_an_agent_is_live(fleet_home, tmp_path, monkeypatch):
    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    supervisor.write_lock("a", {"pid": 4242, "repo": "a", "ticket": "RDSD-9"})
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: pid == 4242)

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("a", key="RDSD-1", exe=_fake_copilot(tmp_path))
    assert "already has a live agent" in e.value.msg
    assert "RDSD-9" in e.value.msg and "ad-fleet stop a" in e.value.hint


def test_a_stale_lock_does_not_block_the_repo_forever(fleet_home, tmp_path, monkeypatch):
    """A supervisor that crashed must not leave the repo unusable.

    `live()` reports the lock is dead but no longer *deletes* it, and the difference matters: the
    lock says which ticket the agent died on and where its stderr is, and `lifecycle.reap` needs
    both to say what happened. Deleting it here meant the first innocent status poll destroyed the
    evidence and a crash was reported as nothing at all. So: `live()` answers, `reap` clears, and
    the repo is startable either way -- which is what this test is actually about.
    """
    from agentdata.fleet import lifecycle

    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    supervisor.write_lock("a", {"pid": 999999, "repo": "a", "ticket": "RDSD-1"})
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: False)

    assert supervisor.live("a") == {}
    assert supervisor.read_lock("a")["ticket"] == "RDSD-1", "the evidence was destroyed by a query"

    lifecycle.reap("a")
    assert not os.path.isfile(supervisor.lock_path("a")), "the reaper did not clear the stale lock"


@pytest.mark.posix
@pytest.mark.skipif(os.name == "nt", reason="zombies are a POSIX idea; Windows has no equivalent")
def test_a_finished_child_is_not_reported_as_alive(fleet_home, tmp_path):
    """On POSIX a child that has exited stays a zombie until somebody waits for it, and
    `os.kill(pid, 0)` succeeds on a zombie.

    `ad-fleet start` exits immediately and hands its orphan to init, which hid this completely.
    `ad-fleet serve` does not exit -- so an agent started from the dashboard finished, became a
    zombie, and sat on its tile as `running` for the life of the server. CI found it; this keeps
    it found.
    """
    import subprocess
    import sys
    import time

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.time() + 30
    while child.poll() is None and time.time() < deadline:
        time.sleep(0.02)
    assert child.poll() is not None, "the probe process never exited"

    assert supervisor.pid_alive(child.pid) is False, "a finished child was reported as running"


def test_starting_a_different_ticket_mid_ticket_is_refused_without_force(fleet_home, tmp_path):
    repo = make_project(tmp_path / "repo-a", phase="triaged", ticket="RDSD-7")
    Registry().add(repo, name="a")
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("a", key="RDSD-8", exe=_fake_copilot(tmp_path))
    assert "RDSD-7" in e.value.msg and "triaged" in e.value.msg
    assert "--force" in e.value.hint


def test_status_reads_each_repos_own_state(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "a", phase="triaged", ticket="RDSD-1"), name="a")
    Registry().add(make_project(tmp_path / "b", phase="idle", ticket=""), name="b")
    rows = {r["repo"]: r for r in supervisor.status()}
    assert rows["a"]["ticket"] == "RDSD-1" and rows["a"]["phase"] == "triaged"
    assert rows["b"]["ticket"] == "" and rows["b"]["agent"] == "idle"


def test_a_denied_tool_is_how_waiting_is_detected(fleet_home, tmp_path):
    """The spike's sharpest finding: there is no permission-request event, and a denied tool does
    not fail the turn -- it comes back on `tool.execution_complete` and the turn exits 0. So
    "this agent needs me" is only visible here."""
    Registry().add(make_project(tmp_path / "a"), name="a")

    # The real order, which is the whole point: the tool is attempted, refused, the model narrates
    # it, and the turn ENDS. An earlier version of this test wrote `result` first and passed against
    # a rule that could never fire on real output.
    _write_events("a", [
        {"type": "tool.execution_complete", "timestamp": "2026-01-01T00:00:05Z",
         "data": {"success": False, "error": {"code": "denied"}}},
        {"type": "result", "timestamp": "2026-01-01T00:00:06Z",
         "sessionId": "s", "exitCode": 0, "usage": {"premiumRequests": 0.33}},
    ])

    state = supervisor.agent_state("a")
    assert state["agent"] == "waiting", state
    assert state["denied_tools"] == 1
    assert state["premium_requests"] == 0.33, "cost comes from result.usage, at the top level"
    assert state["session"] == "s"


def test_a_later_clean_turn_clears_waiting(fleet_home, tmp_path):
    """Only the last completed turn counts: an approval that unblocked the agent must show."""
    Registry().add(make_project(tmp_path / "a"), name="a")
    _write_events("a", [
        {"type": "tool.execution_complete", "timestamp": "2026-01-01T00:00:05Z",
         "data": {"success": False, "error": {"code": "denied"}}},
        {"type": "result", "timestamp": "2026-01-01T00:00:06Z", "sessionId": "s", "exitCode": 0,
         "usage": {"premiumRequests": 0.33}},
        {"type": "tool.execution_complete", "timestamp": "2026-01-01T00:01:00Z",
         "data": {"success": True}},
        {"type": "result", "timestamp": "2026-01-01T00:01:01Z", "sessionId": "s", "exitCode": 0,
         "usage": {"premiumRequests": 1.0}},
    ])
    state = supervisor.agent_state("a")
    assert state["agent"] == "exited", state
    assert state["turns"] == 2 and state["premium_requests"] == 1.33


def test_a_turn_that_never_finished_is_crashed_not_idle(fleet_home, tmp_path):
    """`idle` means "never started". A process that died mid-turn is a different thing, and the
    operator needs to be able to tell them apart."""
    Registry().add(make_project(tmp_path / "a"), name="a")
    _write_events("a", [{"type": "assistant.message", "timestamp": "2026-01-01T00:00:00Z",
                         "data": {"content": "working"}}])
    assert supervisor.agent_state("a")["agent"] == "crashed"


def _write_events(name, events):
    path = supervisor.events_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def test_ephemeral_events_are_dropped_unless_asked_for(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "a"), name="a")
    path = supervisor.events_path("a")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "assistant.message_delta", "ephemeral": True, "data": {}}) + "\n")
        f.write(json.dumps({"type": "assistant.message", "data": {"content": "hi"}}) + "\n")
    assert [e["type"] for e in supervisor.read_events("a")] == ["assistant.message"]
    assert len(supervisor.read_events("a", raw=True)) == 2


def test_a_missing_copilot_says_how_to_install_it(fleet_home, tmp_path, monkeypatch):
    Registry().add(make_project(tmp_path / "a"), name="a")
    from agentdata import proc

    def not_installed(*_a, **_k):
        raise proc.ProcError("not_found", "copilot: executable not found", "", {"tried": []})

    monkeypatch.setattr(proc, "command", not_installed)
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("a", key="X-1")
    assert "npm install -g @github/copilot" in e.value.hint


def _tree(root: str) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, root)] = os.path.getsize(full)
    return out


def _settle(name: str, seconds: float = 20.0) -> None:
    import time

    deadline = time.time() + seconds
    while time.time() < deadline:
        if not supervisor.live(name):
            return
        time.sleep(0.1)
