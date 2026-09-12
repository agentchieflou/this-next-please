"""Console: A — the file (issue #188).

Copilot writes every session -- interactive or `-p` -- to `~/.copilot/session-state/<id>/events.jsonl`
as it runs, in the catalogue `events.from_copilot` folds. The fleet's own agents get their events
because the supervisor redirects stdout into a file it owns; a session in a console has no such pipe,
so its file is the only stream there is. It is read from a byte offset on the desk's own tick, and
never written.
"""
from __future__ import annotations
import inspect
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from agentdata.fleet import events as E, registry, serve as S, sessions as SESS, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project

FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "copilot" / "session-state"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


def _line(kind: str, **data) -> str:
    return json.dumps({"type": kind, "id": "e", "parentId": None,
                       "timestamp": "2026-09-12T10:00:00Z", "data": data}) + "\n"


def _console(tmp_path, name="luna", session="sess-console"):
    """A checkout with a console lock naming a session, and that session's file."""
    path = make_project(tmp_path / name, ticket="RDSD-7")
    Registry().add(path, name=name)
    supervisor.write_lock(name, {"pid": os.getpid(), "kind": "console", "session": session,
                                 "repo": name, "path": path, "ticket": "RDSD-7",
                                 "started": time.time(), "restarts": 0, "launch": []})
    E.append(name, [E.event(name, "started", {"pid": os.getpid(), "console": True, "session": session},
                            ticket="RDSD-7")])
    file = SESS.session_state_path(session)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    return path, file


# ------------------------------------------------------------------------------------ the path


def test_the_session_file_is_under_copilots_own_directory_and_the_id_is_one_segment(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "state"))
    assert SESS.session_state_path("abc-123") == os.path.join(str(tmp_path / "state"), "abc-123", "events.jsonl")
    assert SESS.session_state_path("") == "" and SESS.session_state_path("..") == ""
    assert SESS.session_state_path("../../etc/passwd") == os.path.join(str(tmp_path / "state"), "passwd", "events.jsonl")
    monkeypatch.delenv("COPILOT_SESSION_STATE")
    assert SESS.session_state_dir() == os.path.expanduser("~/.copilot/session-state")


def test_nothing_in_the_session_state_functions_can_write():
    """Acceptance criterion. Read-only by construction: the source of the two functions carries no
    call that could create, write or remove anything."""
    for fn in (SESS.session_state_dir, SESS.session_state_path):
        src = inspect.getsource(fn)
        for bad in ("open(", "makedirs", "write", "remove", "rename", "unlink", "rmtree", "mkdir"):
            assert bad not in src, f"{fn.__name__} carries {bad!r}"


# ------------------------------------------------------------------------------------ the fold


def test_a_line_appended_to_the_session_file_is_an_agent_frame_on_the_next_tick(fleet_home, tmp_path):
    """Acceptance criterion. The console's file is folded by the same function on the same tick
    as the fleet's own logs, so a line Copilot writes is an SSE `agent` frame inside
    `FOLD_EVERY_S + TICK_S`, the bar the desk already keeps."""
    assert S.FOLD_EVERY_S + S.TICK_S < 1.0
    _path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.turn_start", turnId="0"))
        f.write(_line("assistant.message", content="Reading the ticket.", model="m", toolRequests=[]))

    out: list[str] = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert '"kind": "assistant_text"' in frames and "Reading the ticket." in frames
    assert '"kind": "turn_started"' in frames

    # One more line, one more fold, one more frame -- and only the new one.
    with open(file, "a", encoding="utf-8") as f:
        f.write(_line("tool.execution_start", toolName="shell", toolCallId="t1", arguments={"command": "git status"}))
    cursors = {"luna": max(ev["seq"] for ev in E.read("luna"))}
    S._desk["last_fold"] = 0.0
    out.clear()
    S.stream_events(cursors, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert '"kind": "tool_call"' in frames and "git status" in frames
    assert "Reading the ticket." not in frames


def test_the_file_is_read_from_its_offset_and_a_half_written_line_waits(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion. The second fold reads only the bytes appended since the first -- a
    console session's file grows for hours -- and a partial last line is neither folded nor lost."""
    _path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        for i in range(2000):
            f.write(_line("assistant.message", content=f"line {i} " + "x" * 200, model="m", toolRequests=[]))
    big = os.path.getsize(file)
    reads: list[tuple[str, int, int]] = []
    real = E._read_from

    def counted(path, offset):
        lines, new_offset, n = real(path, offset)
        reads.append((path, offset, new_offset - offset))
        return lines, new_offset, n

    monkeypatch.setattr(E, "_read_from", counted)
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, 0, big)]
    assert sum(1 for ev in E.read("luna") if ev["kind"] == "assistant_text") == 2000

    reads.clear()
    half = _line("assistant.message", content="the last one", model="m", toolRequests=[])
    with open(file, "a", encoding="utf-8") as f:
        f.write(half[:40])                                     # the writer is mid-line
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, 0)], "a partial line is not consumed"
    assert sum(1 for ev in E.read("luna") if ev["kind"] == "assistant_text") == 2000

    reads.clear()
    with open(file, "a", encoding="utf-8") as f:
        f.write(half[40:])
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, len(half.encode("utf-8")))]
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts.count("the last one") == 1 and len(texts) == 2001


def test_a_cursor_written_as_a_line_count_is_read_once_as_an_offset(fleet_home, tmp_path):
    """Every cursor before #188 counted lines. Upgrading skips nothing and repeats nothing."""
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    raw = supervisor.events_path("luna")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    with open(raw, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="one", model="m", toolRequests=[]))
        f.write(_line("assistant.message", content="two", model="m", toolRequests=[]))
    E.write_cursor("luna", {"raw_lines": 1})                  # the old shape: one line consumed
    E.refresh("luna", path, repo_state={})
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts == ["two"], texts
    cursor = E.read_cursor("luna")
    assert cursor["raw_lines"] == 2 and cursor["raw_offset"] == os.path.getsize(raw)
    E.reset_raw_cursor("luna")
    assert E.read_cursor("luna")["raw_offset"] == 0 and E.read_cursor("luna")["raw_lines"] == 0


def test_a_new_session_is_a_new_file_and_the_offset_belongs_to_the_path(fleet_home, tmp_path):
    path, file = _console(tmp_path, session="sess-one")
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="first session", model="m", toolRequests=[]))
    E.refresh("luna", path, repo_state={})
    supervisor.write_lock("luna", {**supervisor.read_lock("luna"), "session": "sess-two"})
    second = SESS.session_state_path("sess-two")
    os.makedirs(os.path.dirname(second), exist_ok=True)
    with open(second, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="second session", model="m", toolRequests=[]))
    E.refresh("luna", path, repo_state={})
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts == ["first session", "second session"]
    assert E.read_cursor("luna")["console_file"] == second


def test_without_a_console_lock_no_session_file_is_read(fleet_home, tmp_path):
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    assert E.console_path("luna") == ""
    supervisor.write_lock("luna", {"pid": 1, "repo": "luna", "session": "sess-fleet", "launch": []})
    assert E.console_path("luna") == "", "a fleet lock's session is on the fleet's own pipe"
    supervisor.write_lock("luna", {"pid": 0, "repo": "luna", "external": True, "session": "s",
                                   "session_file": str(tmp_path / "somewhere" / "events.jsonl")})
    assert E.console_path("luna") == str(tmp_path / "somewhere" / "events.jsonl")


# --------------------------------------------------------------------------------- never written


def test_copilots_directory_is_never_written_by_a_fold(fleet_home, tmp_path):
    """Acceptance criterion. Every fold path runs against Copilot's directory and nothing under it
    changes: not a file, not a timestamp, not a listing."""
    path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="hello", model="m", toolRequests=[]))
    root = SESS.session_state_dir()

    def snapshot():
        out = {}
        for d, _dirs, files in os.walk(root):
            for name in files:
                p = os.path.join(d, name)
                out[p] = (os.path.getsize(p), os.path.getmtime(p))
            out[d] = ("dir", os.path.getmtime(d))
        return out

    before = snapshot()
    for _ in range(3):
        E.refresh("luna", path, repo_state={"active_ticket": "RDSD-7", "phase": "triaged"})
        S.stream_events({}, threading.Event(), lambda s: None, once=True)
        S._desk["last_fold"] = 0.0
    assert snapshot() == before


# ------------------------------------------------------------------------------------- the fake


def test_the_fake_copilot_writes_its_session_file_in_the_order_it_prints(tmp_path, monkeypatch):
    """Acceptance criterion. The fake's session file and its stdout carry the same events in the
    same order, so CI has a file that grows the way Copilot's does."""
    state = tmp_path / "state"
    env = dict(os.environ, COPILOT_SESSION_STATE=str(state), AGENTDATA_FAKE_CASE="triage-ok")
    done = subprocess.run([sys.executable, os.path.join(FAKES, "runner.py"), "copilot", "-p", "hello",
                           "--resume", "sess-file"], capture_output=True, text=True, env=env,
                          cwd=str(tmp_path), timeout=120)
    assert done.returncode == 0, done.stderr
    printed = [ln for ln in done.stdout.splitlines() if ln.startswith("{")]
    file = state / "sess-file" / "events.jsonl"
    assert file.is_file()
    written = [ln for ln in file.read_text(encoding="utf-8").splitlines() if ln.startswith("{")]
    assert written == printed and len(written) >= 2
    assert json.loads(written[-1])["type"] == "result"
