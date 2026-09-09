"""Tests for Desk on Windows: run boundaries, persistence, and arrangement (Issue #147 & #149)."""
from __future__ import annotations
import json
import os
import time

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


def test_format_age_str():
    assert S.format_age_str(-1) == ""
    assert S.format_age_str(30) == "30s"
    assert S.format_age_str(300) == "5m"
    assert S.format_age_str(7200) == "2h"
    assert S.format_age_str(90000) == "yesterday"
    assert S.format_age_str(200000) == "2 days ago"


def test_desk_persistence_across_reset_and_reload(fleet_home, tmp_path):
    # Select a project
    S.select("alpha", screens=["beta", "gamma"])
    desk_path = os.path.join(registry.fleet_dir(), "desk.json")
    assert os.path.isfile(desk_path)

    # Check file content
    with open(desk_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["selected"] == "alpha"
    assert data["screens"] == ["beta", "gamma"]
    assert "arrangement" in data

    # Arrange a layout
    S.arrange("grid", order=["gamma", "alpha"], size={"gamma": 2}, pinned=["gamma"])
    state = S.desk_state()
    assert state["arrangement"]["grid"]["order"] == ["gamma", "alpha"]
    assert state["arrangement"]["grid"]["size"] == {"gamma": 2}
    assert state["arrangement"]["grid"]["pinned"] == ["gamma"]

    # Verify on disk
    with open(desk_path, encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["arrangement"]["grid"]["pinned"] == ["gamma"]


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
