"""Epic #170's acceptance sentence, as one test (issue #176).

Two checkouts of one project registered, one put away; the desk closed and reopened by name; the
hidden tile turning red in the dock and reopening from a toast anchor; an earlier session made live
again by *Stop and resume*; and the *since you were away* strip naming every change.

Real `copilot` processes -- the fake from `tests/fakes/`, launched by the real supervisor -- so the
session ids are ids a process actually announced, and `--new` means a conversation that has never
been used before rather than a fixture with one hard-coded id.
"""
from __future__ import annotations
import json
import os
import threading
import time

import pytest

import fakes
from agentdata.fleet import events as E, serve as S, sessions as SESS, supervisor
from agentdata.fleet.registry import Registry

pytestmark = pytest.mark.slow

SETTLE_S = 90


def _project(root: str, project: str = "RDSD") -> str:
    os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Project\n\n- jira_project: {project}\n")
    with open(os.path.join(root, ".agent", "state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"project": project, "phase": "idle", "active_ticket": None,
                   "open_questions": [], "artifacts": []}, f)
    return root


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


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """One project, two working trees -- the shape `git worktree add` leaves behind."""
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)

    main = _project(str(tmp_path / "luna"))
    os.makedirs(os.path.join(main, ".git", "worktrees", "hotfix"))
    tree = _project(str(tmp_path / "luna-hotfix"))
    with open(os.path.join(tree, ".git"), "w", encoding="utf-8", newline="\n") as f:
        f.write("gitdir: %s\n" % os.path.join(main, ".git", "worktrees", "hotfix"))

    reg = Registry()
    reg.add(main, name="luna")
    added = reg.add(tree)
    assert added.name == "luna-hotfix" and added.project == "luna"
    return {"luna": main, "luna-hotfix": tree}


def _settle(name: str, seconds: float = SETTLE_S) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not supervisor.live(name):
            return
        time.sleep(0.2)
    raise AssertionError(f"{name} was still running after {seconds}s")


def _fold(name: str, path: str) -> dict:
    E.refresh(name, path, repo_state=Registry().get(name).state())
    return [r for r in S.fleet_snapshot()["repos"] if r["repo"] == name][0]


def test_two_checkouts_two_sessions_one_desk_that_comes_back(project, monkeypatch):
    """The epic's acceptance sentence, end to end."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "new-session")

    # 1. Both checkouts run, at once, with two locks and two sessions. One agent per registered
    #    working tree is what the lock has always meant.
    supervisor.start("luna", key="RDSD-1", cfg={"fleet": {"notify": {"toast": False}}})
    supervisor.start("luna-hotfix", key="RDSD-2", cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    _settle("luna-hotfix")

    first = supervisor.session_id("luna")
    assert first, "the run announced a session id"
    assert supervisor.session_id("luna-hotfix") != first, "two checkouts, two conversations"

    # 2. A clean session beside the first one, in the same checkout. The previous one stays
    #    listed and stays resumable.
    supervisor.start("luna", key="RDSD-1", new=True, force=True,
                     cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    second = supervisor.session_id("luna")
    assert second and second != first, "`--new` is a conversation that has not been used before"

    rows = {s["id"]: s for s in SESS.rebuild_sessions("luna", repo_path=project["luna"])}
    assert first in rows and second in rows, sorted(rows)
    assert _fold("luna", project["luna"])["sessions_n"] >= 1, "the strip has an `earlier` to open"

    # 3. The earlier session's transcript is readable by its id, from history, without spawning.
    before = sum(1 for e in E.read("luna") if e["kind"] == "started")
    said = S.transcript_for("luna", first)
    assert said["events"], "an earlier session has a transcript, read by its id"
    assert said["runs"] == 1
    assert sum(1 for e in E.read("luna") if e["kind"] == "started") == before, \
        "reading a session started an agent"

    # 4. *Stop and resume*: the refusal first, then the deliberate second press.
    supervisor.write_lock("luna", {"pid": os.getpid(), "repo": "luna", "ticket": "RDSD-1",
                                   "session": second})
    with pytest.raises(supervisor.SupervisorError) as refused:
        supervisor.start("luna", resume=first)
    assert "already has a live agent" in refused.value.msg
    assert refused.value.code == "live_agent"

    supervisor.clear_lock("luna")
    supervisor.start("luna", resume=first, cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    assert supervisor.session_id("luna") == first, "it went back to the conversation it was told to"
    argv = (supervisor.read_lock("luna") or {}).get("launch") or []
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == first, argv


def test_the_desk_survives_being_closed_and_comes_back_by_name(project, monkeypatch):
    """Acceptance criterion: arrange, hide, `Ctrl-C`, and open the same window again."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "new-session")
    S.arrange("grid", order=["luna", "luna-hotfix"], hidden=["luna"])
    S.update_window("left", focus=True, section="inspector")

    # A project's checkouts are hidden as one, so putting `luna` away took its worktree with it.
    assert sorted(S.desk_state()["arrangement"]["grid"]["hidden"]) == ["luna", "luna-hotfix"]

    # `Ctrl-C`: the handles go, the desk stays.
    S.drop_handles()
    S._desk_loaded = False
    S._selection["arrangement"] = {}
    S._selection["windows"] = {}

    again = S.desk_state()
    assert sorted(again["arrangement"]["grid"]["hidden"]) == ["luna", "luna-hotfix"]
    assert again["arrangement"]["grid"]["order"] == ["luna", "luna-hotfix"]
    assert again["windows"]["left"]["focus"] is True
    assert again["windows"]["left"]["section"] == "inspector"


def test_a_hidden_checkout_that_needs_a_person_is_on_the_glass_and_reachable_by_anchor(
        project, monkeypatch):
    """Acceptance criterion, the half the server owns: hidden is the operator's arrangement, and
    needing a person overrides it. The rendered half -- the red dock chip and the toast anchor
    reopening the tile -- is `tests/test_fleet_desk_hide.py`."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "asks-question")
    S.arrange("grid", order=["luna", "luna-hotfix"], hidden=["luna-hotfix"])

    supervisor.start("luna-hotfix", key="RDSD-2", cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna-hotfix")

    row = _fold("luna-hotfix", project["luna-hotfix"])
    assert row["needs_human"], row["state"]
    assert row["why"], "and it says what it needs"
    assert "luna-hotfix" in S.desk_state()["arrangement"]["grid"]["hidden"], \
        "the arrangement is unchanged: it is the page that refuses to hide a demand"
