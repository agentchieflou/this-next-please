"""The cleanup guide's server side (`fleet/cleanup.py`, `GET /api/tidy`, the `tidy` action).

Two registered checkouts of one project -- a main checkout and a real `git worktree` of it -- each
with uncommitted changes, some to the same file. The guide lists them most recent first, sees the
shared file in both, recommends by tech debt, refuses a tree whose agent is mid-turn, and journals
what it did in the fleet's own folder.
"""
from __future__ import annotations
import json
import os
import subprocess

import pytest

from agentdata.fleet import cleanup as CL, registry, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet_tidy import DAY, NOW, git, write

pytestmark = pytest.mark.usefixtures("identity")


@pytest.fixture()
def identity(monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path


def _project(root):
    os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
    write(root, "AGENTS.md", "# Project\n\n- jira_project: RDSD\n")
    write(root, ".agent/state.json", json.dumps({"project": "RDSD", "phase": "idle", "active_ticket": ""}))


@pytest.fixture()
def two(fleet_home, tmp_path):
    """`luna` (main checkout, on a stale feature branch) and `luna-hotfix` (a worktree on a fresh one)."""
    main = str(tmp_path / "luna")
    os.makedirs(main)
    git(main, "init", "-q", "-b", "main")
    write(main, "a.py", "a\n")
    write(main, "b.py", "b\n")
    write(main, ".gitignore", ".agent/\nAGENTS.md\n")
    git(main, "add", ".")
    git(main, "commit", "-qm", "init", when=NOW - 20 * DAY)
    git(main, "checkout", "-qb", "feature/RDSD-1-old")
    write(main, "a.py", "a\nold\n")
    git(main, "commit", "-qam", "old", when=NOW - 15 * DAY)
    git(main, "checkout", "-q", "main")
    for i in range(4):
        write(main, "b.py", f"b{i}\n")
        git(main, "commit", "-qam", f"main {i}", when=NOW - 3 * DAY + i)
    git(main, "checkout", "-q", "feature/RDSD-1-old")
    wt = str(tmp_path / "luna-hotfix")
    git(main, "worktree", "add", "-q", "-b", "feature/RDSD-2-fresh", wt, "main")
    for root in (main, wt):
        _project(root)
    Registry().add(main, name="luna")
    Registry().add(wt, name="luna-hotfix")
    write(main, "a.py", "a\nold\nedit in luna\n")
    write(wt, "a.py", "a\nedit in the hotfix\n")
    write(wt, "c.py", "new\n")
    os.utime(os.path.join(main, "a.py"), (NOW - DAY, NOW - DAY))
    os.utime(os.path.join(wt, "a.py"), (NOW - 60, NOW - 60))
    os.utime(os.path.join(wt, "c.py"), (NOW - 60, NOW - 60))
    return main, wt


def test_every_dirty_tree_most_recent_first_with_the_shared_file_found(two):
    plans = CL.plans(now=NOW)
    assert [t["repo"] for t in plans["trees"]] == ["luna-hotfix", "luna"], "the most recent first"
    assert [t["step"] for t in plans["trees"]] == [1, 2]
    hot, old = plans["trees"]
    assert hot["overlaps"][0]["where"] == "checkout luna" and hot["overlaps"][0]["files"] == ["a.py"]
    # the fresh worktree carries less debt than the stale branch: it keeps its work...
    assert hot["recommended"] == "commit" and "less tech debt" in hot["why"]
    # ...and the stale one is told to stash, which keeps its work too
    assert old["recommended"] == "stash" and "checkout luna-hotfix" in old["why"]
    assert plans["says"] == "2 dirty trees, the most recent first"


def test_the_guide_opened_on_one_tree_still_sees_its_sibling(two):
    plans = CL.plans(["luna"], now=NOW)
    assert [t["repo"] for t in plans["trees"]] == ["luna"]
    assert plans["trees"][0]["overlaps"][0]["where"] == "checkout luna-hotfix"


def test_a_decision_is_applied_journaled_and_the_tree_is_surveyed_again(two, fleet_home):
    main, wt = two
    plan = next(t for t in CL.plans()["trees"] if t["repo"] == "luna-hotfix")
    out = S.act("tidy", {"repo": "luna-hotfix", "plan_id": plan["plan_id"], "choice": "commit",
                         "message": "fix: RDSD-2 hotfix edit"})
    assert out["done"]["did"] == "commit" and out["done"]["clean"] is True
    assert out["trees"] == [], "the answer is that tree's fresh state: clean"
    assert git(wt, "log", "-1", "--format=%s").strip() == "fix: RDSD-2 hotfix edit"
    journal = open(os.path.join(fleet_home, "fleet", CL.JOURNAL), encoding="utf-8").read().splitlines()
    row = json.loads(journal[-1])
    assert row["repo"] == "luna-hotfix" and row["did"] == "commit" and row["undo"] == "git reset --soft HEAD~1"
    # the sibling's overlap moved with it: a.py now changes on the committed branch, not in a dirty tree
    assert [o["where"] for o in CL.plans()["trees"][0]["overlaps"]] == ["branch feature/RDSD-2-fresh"]


def test_a_tree_whose_agent_is_mid_turn_is_never_touched(two):
    main, _ = two
    supervisor.write_lock("luna", {"pid": os.getpid(), "repo": "luna", "path": main})
    try:
        plan = next(t for t in CL.plans()["trees"] if t["repo"] == "luna")
        assert plan["busy"]["kind"] == "turn" and plan["recommended"] == "skip"
        with pytest.raises(S.ServeError) as e:
            S.act("tidy", {"repo": "luna", "plan_id": plan["plan_id"], "choice": "stash"})
        assert e.value.code == "agent_busy"
        assert "edit in luna" in open(os.path.join(main, "a.py"), encoding="utf-8").read()
    finally:
        supervisor.clear_lock("luna") if hasattr(supervisor, "clear_lock") else os.remove(
            os.path.join(registry.agent_dir("luna"), supervisor.LOCK))


@pytest.mark.parametrize("body,code", [
    ({"repo": "ghost", "plan_id": "x", "choice": "commit"}, "no_repo"),
    ({"repo": "luna", "plan_id": "stale", "choice": "commit"}, "changed"),
    ({"repo": "luna", "plan_id": "stale", "choice": "discard"}, "bad_choice"),
])
def test_a_refused_press_says_why_and_changes_nothing(two, body, code):
    main, _ = two
    before = git(main, "status", "--porcelain")
    with pytest.raises(S.ServeError) as e:
        S.act("tidy", body)
    assert e.value.code == code
    assert git(main, "status", "--porcelain") == before


def test_the_page_and_its_api_are_served(two):
    import threading
    import urllib.request

    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tidy?t={token}&repo=luna", timeout=10) as r:
            got = json.loads(r.read())
        assert [t["repo"] for t in got["trees"]] == ["luna"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/tidy?t={token}", timeout=10) as r:
            html = r.read().decode("utf-8")
        assert f'"/static/tidy.js?t={token}"' in html and f'"/static/tidy.css?t={token}"' in html
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def test_a_clean_fleet_says_so(fleet_home, tmp_path):
    root = str(tmp_path / "solo")
    os.makedirs(root)
    git(root, "init", "-q", "-b", "main")
    write(root, ".gitignore", ".agent/\nAGENTS.md\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    _project(root)
    Registry().add(root, name="solo")
    plans = CL.plans()
    assert plans["trees"] == [] and plans["clean"] == ["solo"] and plans["says"] == "every working tree is clean"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout == ""
