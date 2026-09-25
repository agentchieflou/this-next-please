"""Tests for Desk on Windows: run boundaries, persistence, and arrangement (Issue #147 & #149)."""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.request

import pytest

from agentdata.fleet import events as E, registry, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - fixture


def test_split_runs_empty():
    run, earlier = S.split_runs([])
    assert run["n"] == 0
    assert run["events"] == []
    assert earlier == []


def test_split_runs_single_run_with_started(tmp_path):
    stream = [
        {"kind": "started", "ts": "2026-09-08T10:00:00Z", "seq": 1, "data": {"session": "sess-1"}},
        {"kind": "tool_call", "ts": "2026-09-08T10:01:00Z", "seq": 2, "data": {"tool": "cat"}},
        {"kind": "assistant_text", "ts": "2026-09-08T10:02:00Z", "seq": 3, "data": {"text": "done"}},
    ]
    run, earlier = S.split_runs(stream, live=True)
    assert run["n"] == 1
    assert run["started"] == "2026-09-08T10:00:00Z"
    assert run["session"] == "sess-1"
    assert len(run["events"]) == 3
    assert earlier == []


def test_split_runs_multiple_runs_started_boundary():
    stream = [
        # Run 1: finished
        {"kind": "started", "ts": "2026-09-08T08:00:00Z", "seq": 1, "ticket": "PROJ-1"},
        {"kind": "phase_changed", "ts": "2026-09-08T08:30:00Z", "seq": 2, "data": {"to": "done"}},
        # Run 2: ended in error
        {"kind": "started", "ts": "2026-09-08T09:00:00Z", "seq": 3, "ticket": "PROJ-2"},
        {"kind": "error", "ts": "2026-09-08T09:10:00Z", "seq": 4, "data": {"exit_code": 1}},
        # Run 3: current run
        {"kind": "started", "ts": "2026-09-08T10:00:00Z", "seq": 5, "ticket": "PROJ-3"},
        {"kind": "assistant_text", "ts": "2026-09-08T10:05:00Z", "seq": 6, "data": {"text": "working..."}},
    ]
    run, earlier = S.split_runs(stream, live=True)

    # Current run is Run 3
    assert run["n"] == 3
    assert run["started"] == "2026-09-08T10:00:00Z"
    assert run["ticket"] == "PROJ-3"
    assert len(run["events"]) == 2

    # Earlier runs are 1 and 2
    assert len(earlier) == 2
    assert earlier[0]["n"] == 1
    assert earlier[0]["ticket"] == "PROJ-1"
    assert earlier[0]["state"] == "done"

    assert earlier[1]["n"] == 2
    assert earlier[1]["ticket"] == "PROJ-2"
    assert earlier[1]["state"] == "error"


def test_the_session_began_at_the_last_start_that_was_not_a_resume(fleet_home):
    """#499: a Send writes a `started` with `resumed: true`, so a run is not a session."""
    from agentdata.fleet import runs as R, sessions as SS

    stream = [
        {"kind": "started", "ts": "2026-09-03T12:00:00", "repo": "luna", "data": {"session": "a"}},
        {"kind": "started", "ts": "2026-09-04T09:00:00", "repo": "luna", "data": {"session": "a", "resumed": True}},
        {"kind": "started", "ts": "2026-09-04T10:00:00", "repo": "luna",
         "data": {"session": "a", "resumed": True, "console": True}},
    ]
    assert R.session_start(stream)["ts"] == "2026-09-03T12:00:00"
    run, _ = S.split_runs(stream)
    assert run["started"] == "2026-09-04T10:00:00" and run["session_began"] == "2026-09-03T12:00:00"
    marked = stream + [{"kind": "started", "ts": "2026-09-05T08:00:00", "repo": "luna",
                        "data": {"session": "b", "resumed": True, "new": True}}]
    assert S.split_runs(marked)[0]["session_began"] == "2026-09-05T08:00:00"
    adopted = stream + [{"kind": "started", "ts": "2026-09-06T08:00:00", "repo": "luna",
                         "data": {"session": "c", "resumed": True, "adopted": True}}]
    assert S.split_runs(adopted)[0]["session_began"] == "2026-09-06T08:00:00"

    # The session's first `started` rolled out of the stream: sessions.json's `first_seen` answers.
    rolled = stream[1:]
    assert R.session_start(rolled) == {}
    assert S.split_runs(rolled)[0]["session_began"] == ""
    SS.save_sessions("luna", [{"id": "a", "first_seen": "2026-09-03T11:59:00"}])
    assert S.split_runs(rolled)[0]["session_began"] == "2026-09-03T11:59:00"


def test_format_age_str():
    assert S.format_age_str(-1) == ""
    assert S.format_age_str(30) == "30s"
    assert S.format_age_str(300) == "5m"
    assert S.format_age_str(7200) == "2h"
    assert S.format_age_str(90000) == "yesterday"
    assert S.format_age_str(200000) == "2 days ago"


def test_desk_persistence_across_reset_and_reload(fleet_home, tmp_path):
    # Select a project
    S.select("alpha")
    desk_path = os.path.join(registry.fleet_dir(), "desk.json")
    assert os.path.isfile(desk_path)

    # Check file content: schema 2, one arrangement, and no per-monitor pinning (#232).
    with open(desk_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema"] == 2
    assert data["selected"] == "alpha"
    assert "screens" not in data
    assert "arrangement" in data

    # Arrange a layout
    S.arrange(order=["gamma", "alpha"], size={"gamma": 2}, pinned=["gamma"])
    state = S.desk_state()
    assert state["arrangement"]["order"] == ["gamma", "alpha"]
    # #217: one number became two. `size=2` on the way in is "two columns wide", and it is
    # stored -- and read back by every window -- as the footprint it always meant.
    assert state["arrangement"]["size"] == {"gamma": {"cols": 2, "rows": 1}}
    assert state["arrangement"]["pinned"] == ["gamma"]

    # Verify on disk
    with open(desk_path, encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["arrangement"]["pinned"] == ["gamma"]


def test_fleet_snapshot_carries_run_earlier_and_supervision(fleet_home, tmp_path):
    p = make_project(tmp_path / "repo-desk")
    Registry().add(p, name="repo-desk")

    # Add historical run and current run
    E.append("repo-desk", [
        {"kind": "started", "ts": "2026-09-08T08:00:00Z", "data": {"resumed": False}},
        {"kind": "phase_changed", "ts": "2026-09-08T08:10:00Z", "data": {"to": "done"}},
        {"kind": "started", "ts": "2026-09-08T09:00:00Z", "data": {"resumed": True}},
        {"kind": "assistant_text", "ts": "2026-09-08T09:05:00Z", "data": {"text": "in progress"}},
    ])

    snap = S.fleet_snapshot()
    repo_row = [r for r in snap["repos"] if r["repo"] == "repo-desk"][0]

    assert repo_row["run"]["n"] == 2
    assert repo_row["run"]["resumed"] is True
    assert len(repo_row["earlier"]) == 1
    assert repo_row["earlier"][0]["state"] == "done"

    # Since no active pid/live supervisor process, it is not supervised:
    assert repo_row["supervised"] is False
    assert "not supervised" in repo_row["not_supervised_sentence"].lower() or "last run ended" in repo_row["not_supervised_sentence"].lower()


def test_hig_chrome_toolbar_and_inspector():
    static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agentdata", "fleet", "static")
    html = open(os.path.join(static_dir, "index.html"), encoding="utf-8").read()
    # The `window` group chose an arrangement, and there is one (#232).
    assert "toolbar-group group-window" not in html
    assert "toolbar-group group-view" in html
    assert "toolbar-group group-actions" in html
    assert 'id="layoutgroup"' not in html
    assert 'id="inspector"' in html


def test_desk_arrange_api(fleet_home, tmp_path):
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        req = urllib.request.Request(
            f"{base}/api/arrange?t={token}",
            data=json.dumps({"layout": "grid", "order": ["x", "y"], "size": {"x": 2}, "pinned": ["x"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
            res = json.loads(r.read())
            assert res["ok"] is True
            assert res["action"] == "arrange"
            assert res["arrangement"]["order"] == ["x", "y"]
            assert res["arrangement"]["size"] == {"x": {"cols": 2, "rows": 1}}
            assert res["arrangement"]["pinned"] == ["x"]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
