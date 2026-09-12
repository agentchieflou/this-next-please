"""Console: F — the whole epic, exercised end to end (issue #193).

One checkout, one session, and every surface it passes through: the fleet opens a console for it,
the tile reads that session from Copilot's own file while the window is still open, the operator
types a reply from the tile and the helper puts it into the window, the window closes, and *Resume
here* brings the same session back headless. Counted in `started`, `said`, `exited` and exactly one
`--resume`, because the point of the epic is that there is one session and one record of it --
never two pictures of the same work to reconcile.

The console host and the console helper are fakes: there is no `cmd.exe` on CI and nothing to
attach to. What is real is everything between them -- the supervisor's verbs, the lock, the refusals,
the fold of Copilot's file, the session index. The three things only a Windows machine can answer
are runbook rows C1-C8 in `docs/windows-verification.md`.
"""
from __future__ import annotations
import json
import os
import sys
import time

import pytest

from agentdata.fleet import events as E, lifecycle, serve as S, sessions as SESS, supervisor
from agentdata.fleet.registry import Registry

import fakes
from test_fleet import make_project

pytestmark = [pytest.mark.slow]

FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes")
SETTLE_S = 90


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "copilot" / "session-state"))
    monkeypatch.setenv("AGENTDATA_FAKE_SAY_LOG", str(tmp_path / "helper.jsonl"))
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    (tmp_path / "cfg.json").write_text(json.dumps({"fleet": {
        "console": {"host": "fake", "helper": [sys.executable, os.path.join(FAKES, "say_helper.py")]},
        "notify": {"toast": False}}}), encoding="utf-8")
    return tmp_path


def _cfg(tmp_path) -> dict:
    return json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))


def _eventually(check, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


def _fold(name: str, path: str) -> list[dict]:
    E.refresh(name, path, repo_state=Registry().get(name).state())
    return E.read(name)


def _kinds(name: str, kind: str) -> int:
    return sum(1 for e in E.read(name) if e["kind"] == kind)


def test_one_session_through_a_console_a_reply_and_back_to_the_fleet(desk, monkeypatch):
    """Acceptance (#193). The demo the epic is finished by: a console the fleet opened, read live
    from Copilot's file; a reply typed into that window from the tile; the window closing; the same
    session resumed headless. One session id throughout, and one transcript of it."""
    cfg = _cfg(desk)
    path = make_project(desk / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "console-session")

    # 1. The fleet opens the window and takes the lock with its pid.
    lock = supervisor.console("luna", key="RDSD-7", cfg=cfg)
    session = lock["session"]
    assert lock["kind"] == "console" and lock["pid"]
    assert "-p" not in lock["launch"], "a console is the operator's to type in"

    # 2. The tile reads that session from Copilot's own file, while the window is still open.
    file = SESS.session_state_path(session)
    assert _eventually(lambda: os.path.isfile(file)
                       and "Hello from the console" in open(file, encoding="utf-8").read())
    assert "Hello from the console." in [e["data"]["text"] for e in _fold("luna", path)
                                         if e["kind"] == "assistant_text"]
    row = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}["luna"]
    assert row["console"]["session"] == session and row["supervised"]
    assert not row["external"], "a console the fleet opened is the fleet's own"

    # 3. The operator replies from the tile. `send` would be a second agent in this working tree;
    #    `say` types into the window that is already there, and the console echoes it.
    monkeypatch.setenv("AGENTDATA_FAKE_SAY_FILE", file)
    with pytest.raises(supervisor.SupervisorError) as refused:
        supervisor.send("luna", "use the staging connection string", cfg=cfg)
    assert refused.value.code == "external_session"

    out = S.act("say", {"repo": "luna", "message": "use the staging connection string"})
    assert out["ok"] and out["echoed"] == "use the staging connection string"
    said = [e for e in E.read("luna") if e["kind"] == "said"]
    assert len(said) == 1 and said[0]["data"]["session"] == session
    calls = [json.loads(line)["argv"] for line in
             open(os.environ["AGENTDATA_FAKE_SAY_LOG"], encoding="utf-8") if line.strip()]
    assert calls == [["say-into", str(lock["pid"]), "use the staging connection string"]]
    assert _eventually(lambda: "Heard: use the staging connection string"
                       in [e["data"].get("text", "") for e in _fold("luna", path)
                           if e["kind"] == "assistant_text"])

    # 4. The fleet does not close the operator's window, and the tile does not pretend it can.
    with pytest.raises(supervisor.SupervisorError) as kept:
        supervisor.stop("luna")
    assert kept.value.code == "console_window"
    assert supervisor.pid_alive(lock["pid"]), "stop killed the console"

    # 5. The window closes on its own. The reaper says so in the operator's words.
    assert _eventually(lambda: not supervisor.pid_alive(lock["pid"]), timeout=SETTLE_S)
    fresh = lifecycle.reap("luna")
    assert [e["kind"] for e in fresh] == ["exited"]
    assert fresh[0]["data"]["why"] == "the console closed"

    # 6. *Resume here*: the same session, headless, on one `--resume`. Nothing holds the checkout
    #    now -- the window is gone and the lock went with it -- so it simply runs, which is the
    #    whole of what *Resume here* has meant since #174.
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "triage-ok")
    back = supervisor.start("luna", resume=session, cfg=cfg)
    assert back["session"] == session and back["launch"].count("--resume") == 1
    assert _eventually(lambda: not supervisor.live("luna"), timeout=SETTLE_S)
    lifecycle.reap("luna")
    _fold("luna", path)

    # 7. One session. Two surfaces, three runs, and the index says which held it when.
    assert _kinds("luna", "started") == 2 and _kinds("luna", "said") == 1
    rows = {r["id"]: r for r in SESS.rebuild_sessions("luna", path)}
    assert list(rows) == [session], f"one session throughout: {list(rows)}"
    assert rows[session]["sources"] == ["console", "fleet"]
    assert rows[session]["runs"] == 2

    # And nothing the fleet did wrote anything inside Copilot's own directory but the fake's own
    # session file -- the store, the workspace metadata and every other session are read-only.
    root = os.environ["COPILOT_SESSION_STATE"]
    written = {os.path.relpath(os.path.join(folder, name), root)
               for folder, _, files in os.walk(root) for name in files}
    assert written == {os.path.join(session, "events.jsonl")}, written
