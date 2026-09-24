"""`GET /api/map`: the fleet's structure as one graph (#401, docs/fleet-map.md §The graph).

Pure Python. The registry cases build real checkouts under a temporary fleet home (the worktree is a
`.git` file pointing into its main checkout, as git writes it -- no git needed); the kind and sentence
cases fold hand-built rows, because `graph()` reads nothing but the snapshot it is given.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from agentdata.fleet import events as E, fleetmap as M, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """serve's desk globals are process-wide; every test here gets its own."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})
    monkeypatch.setattr(S, "_measure_asks", {})


def _worktree(tmp_path, main_path, folder="luna-hotfix", ticket="RDSD-2"):
    """A checkout whose `.git` is a file pointing back into the main checkout, as git writes it."""
    os.makedirs(os.path.join(main_path, ".git", "worktrees", "hotfix"), exist_ok=True)
    tree = make_project(tmp_path / folder, ticket=ticket)
    with open(os.path.join(tree, ".git"), "w", encoding="utf-8", newline="\n") as f:
        f.write("gitdir: %s\n" % os.path.join(main_path, ".git", "worktrees", "hotfix"))
    return tree


def _walk(node, keys: list, strings: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            keys.append(k)
            _walk(v, keys, strings)
    elif isinstance(node, list):
        for v in node:
            _walk(v, keys, strings)
    elif isinstance(node, str):
        strings.append(node)


def row(repo="luna", **over) -> dict:
    """A `/api/fleet` row with only the keys the map reads, quiet by default."""
    base = {"repo": repo, "path": f"/work/{repo}", "project": repo, "worktree_of": "",
            "supervised": False, "external": False, "console": None, "adoptable": None,
            "state": "idle", "needs_human": False, "ticket": "", "phase": "", "model": "",
            "last_event_age_s": -1, "turns": 0, "sessions_n": 0,
            "stale": {"stale": False}, "renew_queued": False, "last_seq": 0,
            "as_of": {"run": "r", "n": 1}, "polls": {},
            "run": {"n": 0, "origin": "", "events": None, "events_n": 0},
            "why": "SECRET-EVENT-TEXT", "last_said": "SECRET-EVENT-TEXT",
            "recent": [{"kind": "assistant_text", "data": {"text": "SECRET-EVENT-TEXT"}}]}
    base.update(over)
    return base


def origin(o: str) -> dict:
    return {"n": 1, "origin": o, "events": None, "events_n": 3}


def snap(*rows) -> dict:
    return {"repos": list(rows), "theme": {}}


def agent_of(r: dict) -> dict:
    return M.graph(snap(r))["checkouts"][0]["agent"]


# ------------------------------------------------------------------------------- checkouts


def test_a_main_its_worktree_and_an_unrelated_repo(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(main)
    Registry().add(_worktree(tmp_path, main))
    Registry().add(make_project(tmp_path / "uat", ticket="RDSD-9"))

    g = M.graph(S.fleet_snapshot())
    assert [p["name"] for p in g["projects"]] == ["luna", "uat"]
    by = {c["repo"]: c for c in g["checkouts"]}
    assert sorted(by) == ["luna", "luna-hotfix", "uat"]
    assert by["luna-hotfix"]["worktree_of"] == "c:luna"
    assert by["luna-hotfix"]["worktree_of_unregistered"] is False
    assert {r for r, c in by.items() if c["main"]} == {"luna", "uat"}
    assert [p["root"] for p in g["projects"]] == ["c:luna", "c:uat"]
    assert [c["repo"] for c in g["checkouts"]] == ["luna", "luna-hotfix", "uat"], "main first"
    assert by["luna-hotfix"]["says"] == "worktree luna-hotfix, of luna"
    assert g["says"] == "2 projects, 3 checkouts, no agents working, nobody needs you"


def test_a_worktree_of_an_unregistered_main(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(_worktree(tmp_path, main))

    g = M.graph(S.fleet_snapshot())
    (c,) = g["checkouts"]
    assert c["worktree_of"] == "" and c["worktree_of_unregistered"] is True
    assert c["main"] is False
    assert g["projects"][0]["root"] == ""


def test_worktree_of_resolves_across_slashes_and_case():
    main = row("luna", path="C:\\Work\\Luna")
    tree = row("luna-velocity", project="luna", worktree_of="c:/work/luna" if os.name == "nt"
               else "C:/Work/Luna", polls={"git": {"value": {"branch": "feature/RDSD-101-velocity"}}})
    g = M.graph(snap(tree, main))
    by = {c["repo"]: c for c in g["checkouts"]}
    assert by["luna-velocity"]["worktree_of"] == "c:luna"
    assert by["luna-velocity"]["says"] == "worktree luna-velocity on feature/RDSD-101-velocity, of luna"


def test_git_cells_come_from_the_poll_and_default_before_it_ticks():
    quiet = M.graph(snap(row()))["checkouts"][0]
    assert (quiet["branch"], quiet["dirty"], quiet["ahead"], quiet["behind"]) == ("", False, 0, 0)
    polled = M.graph(snap(row(polls={"git": {"value": {
        "branch": "main", "dirty": True, "ahead": 2, "behind": 1}}})))["checkouts"][0]
    assert (polled["branch"], polled["dirty"], polled["ahead"], polled["behind"]) == ("main", True, 2, 1)
    assert polled["says"] == "main checkout luna on main, uncommitted changes, 2 ahead, 1 behind"


# ------------------------------------------------------------------------------- kinds


@pytest.mark.parametrize("over, kind", [
    ({"supervised": True, "console": {"pid": 7, "session": "s", "host": "wt"}}, "console"),
    ({"supervised": True, "external": True}, "adopted"),
    ({"adoptable": {"repo": "luna", "pid": 9}}, "adoptable"),
    ({"run": origin("fleet")}, "headless"),
    ({"run": origin("console")}, "console"),
    ({"run": origin("adopted")}, "adopted"),
    ({}, "none"),
])
def test_each_kind_comes_from_a_row_shaped_like_it(over, kind):
    a = agent_of(row(**over))
    assert a["kind"] == kind and a["kind"] in M.KINDS


def test_kinds_are_exported_in_the_order_they_are_decided():
    assert M.KINDS == ("console", "adopted", "headless", "adoptable", "none")


def test_a_finished_headless_run_that_needs_you():
    a = agent_of(row(run=origin("fleet"), state="needs_human", needs_human=True))
    assert a["kind"] == "headless" and a["live"] is False and a["role"] == "human"
    assert a["says"] == "background agent (headless) · finished · needs you"


def test_a_live_headless_run_and_a_console_and_no_session():
    running = agent_of(row(supervised=True, pid=4, run=origin("fleet"), state="running",
                           ticket="RDSD-101"))
    assert running["says"] == "background agent (headless) · running · RDSD-101"
    console = agent_of(row(supervised=True, console={"pid": 1}, run=origin("console"),
                           state="needs_human", needs_human=True))
    assert console["says"] == "console agent · needs you"
    assert agent_of(row())["says"] == "no session · idle"


def test_a_checkout_with_no_stream_is_kind_none():
    a = agent_of(row(run={"n": 0, "origin": "", "events": None, "events_n": 0}))
    assert a["kind"] == "none" and a["live"] is False and a["role"] == "idle"


# ------------------------------------------------------------------------------- run.origin


@pytest.mark.parametrize("data, want", [
    ({"pid": 1, "console": True}, "console"),
    ({"pid": 1, "adopted": True}, "adopted"),
    ({"pid": 1, "external": True}, "adopted"),
    ({"pid": 1}, "fleet"),
])
def test_split_runs_says_who_started_the_current_run(data, want):
    stream = [E.event("luna", "started", {"pid": 1}, seq=1),
              E.event("luna", "turn_ended", {"turn": "0"}, seq=2),
              E.event("luna", "started", data, seq=3)]
    current, earlier = S.split_runs(stream)
    assert current["origin"] == want
    assert earlier and all("origin" not in run for run in earlier)


def test_split_runs_without_a_started_event_has_no_origin():
    assert S.split_runs([])[0]["origin"] == ""
    current, _ = S.split_runs([E.event("luna", "assistant_text", {"text": "hi"}, seq=1)])
    assert current["origin"] == ""


# ------------------------------------------------------------------------------- sentences


@pytest.mark.parametrize("n, tail", [
    (0, ""), (1, " · 1 sub-agent (not yet measured)"), (2, " · 2 sub-agents (not yet measured)"),
])
def test_says_counts_sub_agents(n, tail):
    assert agent_of(row(subagents=n))["says"] == "no session · idle" + tail


def test_says_stale_and_renew_queued():
    a = agent_of(row(run=origin("fleet"), stale={"stale": True}, renew_queued=True, state="done"))
    assert a["says"] == "background agent (headless) · finished · done · began on an older install · renew queued"
    assert a["stale"] is True and a["renew_queued"] is True


@pytest.mark.parametrize("counts, said", [
    ((0, 0, 0, 0), "no projects, no checkouts, no agents working, nobody needs you"),
    ((1, 1, 1, 1), "1 project, 1 checkout, 1 agent working, 1 needs you"),
    ((3, 5, 4, 2), "3 projects, 5 checkouts, 4 agents working, 2 need you"),
])
def test_the_graph_sentence_plurals_and_zeros(counts, said):
    assert M.graph_says(*counts) == said


def test_working_counts_only_running():
    g = M.graph(snap(row("a", state="running"), row("b", state="starting"),
                     row("c", state="waiting_approval", needs_human=True), row("d", state="done")))
    assert g["says"] == "4 projects, 4 checkouts, 1 agent working, 1 needs you"
    assert M.graph(snap())["says"] == "no projects, no checkouts, no agents working, nobody needs you"


def test_the_cursor_and_as_of():
    g = M.graph(snap(row("uat", last_seq=4), row("luna", last_seq=12)))
    assert g["cursor"] == "luna:12,uat:4"
    assert g["as_of"] == {"run": "r", "n": 1}
    assert M.graph(snap())["as_of"] is None


# ------------------------------------------------------------------------------- what it never carries


def test_no_path_no_tmp_path_no_event_text(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(main)
    Registry().add(_worktree(tmp_path, main))
    E.append("luna", [E.event("luna", "started", {"pid": 1}, ticket="RDSD-1"),
                      E.event("luna", "assistant_text", {"text": "SECRET-EVENT-TEXT"}, ticket="RDSD-1"),
                      E.event("luna", "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    keys, strings = [], []
    _walk(M.graph(S.fleet_snapshot()), keys, strings)
    assert "path" not in keys
    tmp = str(tmp_path)
    for s in strings:
        assert tmp not in s and tmp.replace("\\", "/") not in s
        assert "SECRET-EVENT-TEXT" not in s
    keys, strings = [], []
    _walk(M.graph(snap(row())), keys, strings)
    assert "path" not in keys and not any("SECRET" in s or "/work/" in s for s in strings)


def test_twenty_checkouts_fit_in_eighteen_kib():
    rows = [row(f"proj01-feature-{n:02d}", project="proj01",
                worktree_of="" if n == 0 else "/work/proj01-feature-00",
                run=origin("fleet"), state="running", ticket=f"RDSD-{100 + n}",
                model="claude-sonnet-4.5", subagents=n % 2,
                polls={"git": {"value": {"branch": f"feature/RDSD-{100 + n}-velocity",
                                         "dirty": True, "ahead": 3, "behind": 1}}},
                last_seq=1000 + n)
            for n in range(20)]
    g = M.graph(snap(*rows))
    assert len(json.dumps(g)) < 18 * 1024
    assert sum(1 for c in g["checkouts"] if c["main"]) == 1


def test_one_snapshot_twice_is_equal():
    s = snap(row("luna", run=origin("fleet")), row("uat", supervised=True, external=True))
    assert M.graph(s) == M.graph(s)


# ------------------------------------------------------------------------------- the route


def test_the_route_needs_the_token(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "luna", ticket="RDSD-1"))
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    port = server.server_address[1]
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/map", timeout=10)
        assert refused.value.code == 403
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/map?t={token}", timeout=10) as r:
            body = json.loads(r.read().decode("utf-8"))
        assert body["ok"] is True and body["schema"] == 1
        assert [c["repo"] for c in body["checkouts"]] == ["luna"]
        assert "theme" in body
    finally:
        server.shutdown()
        server.server_close()
