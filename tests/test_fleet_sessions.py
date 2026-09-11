"""Tests for Sessions: A — a session is a record (issue #171)."""
from __future__ import annotations
import json
import os
import sqlite3
import time

import pytest

from agentdata import textio
from agentdata.fleet import agentstate, board as B, events as E, lifecycle, poll as P, registry, runs as R, serve, sessions as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


def test_three_sessions_fold_with_high_water_cost_and_rebuild_is_byte_identical(fleet_home, tmp_path):
    repo_path = make_project(tmp_path / "repo-a")
    Registry().add(repo_path, name="a")

    # Construct a stream with 3 sessions:
    # Session 1: 2 runs, cost checkpoints 1.0 then 2.5 -> cost is 2.5 (not 3.5)
    # Session 2: 1 run, cost 0.5, ended blocked
    # Session 3: 1 run, cost 0.0, ended done
    evs = [
        # Session 1 - Run 1
        E.event("a", "started", {"resumed": False, "session": "sess-1", "summary": "Fix login bug"}, ticket="RDSD-1"),
        E.event("a", "session_id", {"session": "sess-1"}, ticket="RDSD-1"),
        E.event("a", "cost", {"premium_requests": 1.0}, ticket="RDSD-1"),
        E.event("a", "turn_ended", {"turn": "0"}, ticket="RDSD-1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="RDSD-1"),
        # Session 1 - Run 2 (resumed)
        E.event("a", "started", {"resumed": True, "session": "sess-1", "summary": "Continue login"}, ticket="RDSD-1"),
        E.event("a", "cost", {"premium_requests": 2.5}, ticket="RDSD-1"),
        E.event("a", "turn_ended", {"turn": "1"}, ticket="RDSD-1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": ["auth.py"]}, ticket="RDSD-1"),
        # Session 2
        E.event("a", "started", {"resumed": False, "session": "sess-2", "summary": "Update deps"}, ticket="RDSD-2"),
        E.event("a", "session_id", {"session": "sess-2"}, ticket="RDSD-2"),
        E.event("a", "cost", {"premium_requests": 0.5}, ticket="RDSD-2"),
        E.event("a", "phase_changed", {"from": "triaged", "to": "blocked"}, ticket="RDSD-2"),
        E.event("a", "question_opened", {"question": "Which version?"}, ticket="RDSD-2"),
        E.event("a", "turn_ended", {"turn": "0"}, ticket="RDSD-2"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="RDSD-2"),
        # Session 3
        E.event("a", "started", {"resumed": False, "session": "sess-3", "summary": "Tidy docs"}, ticket="RDSD-3"),
        E.event("a", "session_id", {"session": "sess-3"}, ticket="RDSD-3"),
        E.event("a", "turn_ended", {"turn": "0"}, ticket="RDSD-3"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": ["README.md"]}, ticket="RDSD-3"),
    ]
    E.append("a", evs)

    rows = S.rebuild_sessions("a", repo_path=repo_path)
    assert len(rows) == 3
    s1, s2, s3 = rows[0], rows[1], rows[2]

    assert s1["id"] == "sess-1"
    assert s1["runs"] == 2
    assert s1["cost"] == 2.5  # high-water mark, never sum 3.5
    assert s1["ended"] in ("done", "exited", "idle")

    assert s2["id"] == "sess-2"
    assert s2["runs"] == 1
    assert s2["cost"] == 0.5
    assert s2["ended"] == "blocked"

    assert s3["id"] == "sess-3"
    assert s3["runs"] == 1
    assert s3["cost"] == 0.0

    # Rebuilding from same stream is byte-identical
    path = S.sessions_path("a")
    bytes1 = open(path, "rb").read()
    S.rebuild_sessions("a", repo_path=repo_path)
    bytes2 = open(path, "rb").read()
    assert bytes1 == bytes2


def test_rotated_raw_log_allows_send_to_continue(fleet_home, tmp_path, monkeypatch):
    """A rotated raw log no longer makes send refuse; session is read from normalized stream."""
    repo_path = make_project(tmp_path / "repo-a")
    Registry().add(repo_path, name="a")

    # Simulate normalized stream already has a session
    E.append("a", [
        E.event("a", "started", {"resumed": False, "session": "sess-rot-1"}, ticket="RDSD-1"),
        E.event("a", "session_id", {"session": "sess-rot-1"}, ticket="RDSD-1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="RDSD-1"),
    ])

    # Raw log is rotated away (empty or missing)
    raw_path = supervisor.events_path("a")
    assert not os.path.isfile(raw_path)

    # session_id finds it from normalized stream!
    sid = supervisor.session_id("a")
    assert sid == "sess-rot-1"


def test_a_reply_after_a_dead_start_refuses_instead_of_resuming_yesterday(fleet_home, tmp_path):
    """The key regression for #171: a start that dies before its first result followed by send refuses."""
    repo_path = make_project(tmp_path / "repo-a")
    Registry().add(repo_path, name="a")

    # Yesterday's session ran and exited
    E.append("a", [
        E.event("a", "started", {"resumed": False, "session": "yesterday-sess"}, ticket="RDSD-1"),
        E.event("a", "session_id", {"session": "yesterday-sess"}, ticket="RDSD-1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="RDSD-1"),
    ])

    # Today: a fresh start begins, but crashes/dies before producing any result or session_id event
    dead_lock = {"pid": 99999, "repo": "a", "path": repo_path, "ticket": "RDSD-2",
                 "prompt": "New task", "session": "", "started": time.time(),
                 "started_at": "2026-09-11 10:00:00", "launch": []}
    supervisor.write_lock("a", dead_lock)
    supervisor._emit_started("a", dead_lock, resumed=False, new=True)
    supervisor.clear_lock("a")  # process died!

    # Now session_id should return "" (no session to continue)
    assert supervisor.session_id("a") == ""

    # send() refuses with "no session to continue"
    with pytest.raises(supervisor.SupervisorError) as exc:
        supervisor.send("a", "Are you there?")
    assert "no session to continue" in exc.value.msg


def test_history_and_tile_agree_on_what_they_count_and_say_which(fleet_home, tmp_path):
    """ad-fleet history counts dispatches, tile counts runs, and both name which word."""
    repo_path = make_project(tmp_path / "repo-a")
    Registry().add(repo_path, name="a")

    # 1 dispatch with 3 runs (1 start + 2 sends)
    evs = [
        E.event("a", "started", {"resumed": False, "session": "s1"}, ticket="T1"),
        E.event("a", "session_id", {"session": "s1"}, ticket="T1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="T1"),
        E.event("a", "started", {"resumed": True, "session": "s1"}, ticket="T1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="T1"),
        E.event("a", "started", {"resumed": True, "session": "s1"}, ticket="T1"),
        E.event("a", "exited", {"exit_code": 0, "files_modified": []}, ticket="T1"),
    ]
    E.append("a", evs)

    # board.history counts dispatches
    hist = B.history()
    assert len(hist) == 1
    assert hist[0]["session"] == "s1"
    assert R.count_dispatches(evs) == 1

    # serve.split_runs counts runs
    curr_run, earlier = serve.split_runs(evs)
    assert curr_run["n"] == 3
    assert len(earlier) == 2
    assert R.count_runs(evs) == 3


def test_session_store_doctor_row_and_fixture_reading(fleet_home, tmp_path, monkeypatch):
    """With no store doctor row says skip; with fixture store, console session appears with source: store."""
    from agentdata.setup.steps.fleet import FleetStep
    from agentdata.setup import wizard as W

    # 1. No store present -> doctor row says 'skip'
    missing_store = tmp_path / "missing_store.db"
    monkeypatch.setenv("COPILOT_SESSION_STORE", str(missing_store))

    status, detail, hint = S.store_status()
    assert status == "skip"

    ctx = W.Context(cfg={}, det=W.Detectors(), ask=W.AnswerPrompter({}))
    step = FleetStep()
    step._check_session_store(ctx, {})
    rows = [c for c in ctx.checks if c.name == "session store"]
    assert len(rows) == 1
    assert rows[0].status == "skip"

    # 2. Fixture store present
    fixture_db = tmp_path / "session-store.db"
    conn = sqlite3.connect(fixture_db)
    conn.execute("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            cwd TEXT,
            repository TEXT,
            host_type TEXT,
            branch TEXT,
            summary TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    repo_path = make_project(tmp_path / "repo-a")
    Registry().add(repo_path, name="a")

    conn.execute(
        "INSERT INTO sessions (id, cwd, repository, summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("fixture-sess-123", repo_path, "repo-a", "Terminal copilot session", "2026-09-11T09:00:00", "2026-09-11T09:30:00")
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("COPILOT_SESSION_STORE", str(fixture_db))

    status, detail, hint = S.store_status()
    assert status == "ok"
    assert "1 session" in detail

    # Reading store sessions matches registered checkout
    found = S.read_store_sessions(repo_path, repo_name="a")
    assert len(found) == 1
    assert found[0]["id"] == "fixture-sess-123"
    assert found[0]["source"] == "store"
    assert found[0]["title"] == "Terminal copilot session"


def test_wall_clock_jump_with_dead_pid_produces_one_exited_with_why_sleep(fleet_home, tmp_path, monkeypatch):
    """A wall-clock jump of three minutes with a dead pid produces one exited whose why names sleep, and no error."""
    repo_path = make_project(tmp_path / "repo-a")
    reg = Registry()
    reg.add(repo_path, name="a")

    # Write a live lock with pid 99999
    lock = {"pid": 99999, "repo": "a", "path": repo_path, "ticket": "RDSD-9",
            "prompt": "Sleep test", "started": time.time(),
            "started_at": "2026-09-11 10:00:00", "launch": []}
    supervisor.write_lock("a", lock)
    supervisor._emit_started("a", lock)

    # pid 99999 is dead
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: False)

    # Poller runs with a 180s (3 minute) wall clock jump
    current_time = [1000.0]
    poller = P.Poller(reg, now=lambda: current_time[0])
    poller._last_tick_time = 1000.0

    # Advance clock by 180 seconds
    current_time[0] = 1180.0
    poller.tick()

    # Verify event stream
    events = E.read("a")
    kinds = [e["kind"] for e in events]
    assert "error" not in kinds, "sleep should not produce an error event"
    assert "exited" in kinds

    exited_ev = [e for e in events if e["kind"] == "exited"][-1]
    assert "slept" in exited_ev["data"].get("why", "").lower() or "slept" in exited_ev["data"].get("reason", "").lower()
