"""Each agent's branch on its project's branch lanes (#403, epic #295).

The git poll already reads every local branch of every checkout every 30 s; it used to keep only the
counts. It now keeps the rows in a side cache on the `Poller`, and `/api/map` folds them into one
branch list per project, with which checkout stands on each branch. Fake readers everywhere but one
real-git case, so the fold is proven on the answer `read_branches` really gives.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request

import pytest

from agentdata.fleet import fleetmap as M, poll as P, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_branches import _repo
from test_fleet_map import row, snap

OFF = {"fleet": {"poll": {"jira": False, "pr": False, "powerbi": False}}}
T0 = 1_700_000_000.0


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def worktree(tmp_path, main_path, folder, ticket):
    """A checkout whose `.git` is a file pointing back into the main checkout, as git writes it."""
    gitdir = os.path.join(main_path, ".git", "worktrees", folder)
    os.makedirs(gitdir, exist_ok=True)
    tree = make_project(tmp_path / folder, ticket=ticket)
    with open(os.path.join(tree, ".git"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"gitdir: {gitdir}\n")
    return tree


# One repository's refs, as every checkout of it reads them: unmerged first, newest first.
SHARED = [
    {"name": "feature/RDSD-101-velocity", "unmerged": True, "at": T0 - 60},
    {"name": "feature/RDSD-101-velocity-2", "unmerged": True, "at": T0 - 120},
    {"name": "fix/RDSD-9", "unmerged": True, "at": T0 - 600},
    {"name": "main", "unmerged": False, "at": T0 - 3600},
]
CURRENT = {"luna": "main", "luna-velocity": "feature/RDSD-101-velocity", "luna-hotfix": "fix/RDSD-9"}


class Readers:
    """Counting fakes for the poller's two git reads."""

    def __init__(self, rows=SHARED, current=CURRENT):
        self.rows, self.current, self.calls = rows, current, 0

    def git(self, repo):
        self.calls += 1
        return {"branch": self.current.get(repo.name, "main"), "dirty": False, "ahead": 0, "behind": 0}

    def branches(self, repo, *, full=True):
        self.calls += 1
        assert full is False, "the poll makes the cheap read only"
        cur = self.current.get(repo.name, "main")
        ticket = P._active_ticket(repo)
        rows = [{"name": r["name"], "sha": "abc1234", "at": r["at"], "age_s": T0 - r["at"],
                 "upstream": "", "track": "", "ticket": P.ticket_in(r["name"]),
                 "current": r["name"] == cur, "unmerged": r["unmerged"], "ahead": None}
                for r in self.rows]
        carrying = [r["name"] for r in rows if ticket and r["ticket"] == ticket]
        return {"default": "main", "current": cur, "branches": rows, "count": len(rows),
                "unmerged": sum(1 for r in rows if r["unmerged"]), "more": False, "commits": [],
                "ticket": ticket, "carrying": carrying, "full": False, "at": T0}


def three_checkouts(tmp_path) -> None:
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(main)
    Registry().add(worktree(tmp_path, main, "luna-velocity", "RDSD-101"))
    Registry().add(worktree(tmp_path, main, "luna-hotfix", "RDSD-9"))


def ticked(readers: Readers) -> P.Poller:
    p = P.Poller(Registry(), cfg=OFF, now=lambda: T0)
    p.git_reader, p.branch_reader = readers.git, readers.branches
    p.tick(T0)
    return p


def served():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", token


def get(base, token, route) -> dict:
    with urllib.request.urlopen(f"{base}{route}?t={token}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------------------------ the lanes


def test_every_agent_sits_on_its_branch_in_one_list_per_project(fleet_home, tmp_path, monkeypatch):
    """Acceptance criteria 1 and 2. A main and two worktrees give ONE branch list; each checkout's
    current branch lists that checkout in `current_in`; each agent's `on` is its checkout's, names a
    branch of its project, and its `says` names the branch; the ticket carrier is marked."""
    three_checkouts(tmp_path)
    p = ticked(Readers())
    monkeypatch.setitem(S._desk, "poller", p)
    g = M.graph(S.fleet_snapshot(), branch_rows=p.branch_rows)

    assert [x["name"] for x in g["projects"]] == ["luna"]
    proj = g["projects"][0]
    assert proj["default"] == "main"
    assert [b["name"] for b in proj["branches"]] == [r["name"] for r in SHARED], "one list, in order"
    by = {b["name"]: b for b in proj["branches"]}
    assert by["feature/RDSD-101-velocity"]["id"] == "b:luna:feature/RDSD-101-velocity"
    for c in g["checkouts"]:
        name = CURRENT[c["repo"]]
        assert c["on"] == f"b:luna:{name}" and c["agent"]["on"] == c["on"]
        assert c["agent"]["branch"] == name and f"on {name}" in c["agent"]["says"]
        assert by[name]["current_in"] == [c["id"]]
    assert by["feature/RDSD-101-velocity-2"]["current_in"] == []

    # luna-velocity is on RDSD-101 and two branches carry it; luna-hotfix carries RDSD-9 alone.
    assert by["feature/RDSD-101-velocity"]["carrying"] and by["feature/RDSD-101-velocity-2"]["carrying"]
    assert by["fix/RDSD-9"]["carrying"] and not by["main"]["carrying"]
    agents = {c["repo"]: c["agent"] for c in g["checkouts"]}
    assert agents["luna-velocity"]["says"].endswith(" · on feature/RDSD-101-velocity · carries RDSD-101")
    assert agents["luna"]["says"].endswith(" · on main"), "main carries no ticket"
    assert by["feature/RDSD-101-velocity"]["says"] == ("feature/RDSD-101-velocity · never reached main"
                                                       " · current in luna-velocity · carries RDSD-101")
    assert by["main"]["says"] == "main · current in luna"
    assert by["feature/RDSD-101-velocity"]["age_s"] == 60.0, "measured against the read"

    assert proj["branches_says"] == "4 branches, 3 never reached main"
    assert proj["says"].endswith("; 4 branches, 3 never reached main")
    assert proj["carry_lines"] == [
        "two branches carry RDSD-101 (feature/RDSD-101-velocity, feature/RDSD-101-velocity-2); "
        "only one can merge"]


def test_the_union_when_the_main_was_not_read(fleet_home, tmp_path, monkeypatch):
    """No root in the cache: the list is the union over the worktrees, unmerged first, newest first,
    and a checkout the cache has not read falls back to its git cell's branch."""
    three_checkouts(tmp_path)
    p = ticked(Readers())
    monkeypatch.setitem(S._desk, "poller", p)
    extra = dict(p.branch_rows("luna-hotfix"))
    extra["rows"] = extra["rows"] + [{"name": "spike/x", "current": False, "unmerged": True,
                                      "ticket": "", "at": T0 - 30}]
    cache = {"luna-velocity": p.branch_rows("luna-velocity"), "luna-hotfix": extra}
    g = M.graph(S.fleet_snapshot(), branch_rows=cache.get)

    proj = g["projects"][0]
    assert [b["name"] for b in proj["branches"]] == ["spike/x"] + [r["name"] for r in SHARED]
    main = next(c for c in g["checkouts"] if c["repo"] == "luna")
    assert main["on"] == "b:luna:main", "the git cell's branch"
    assert next(b for b in proj["branches"] if b["name"] == "main")["current_in"] == ["c:luna"]


# ----------------------------------------------------------------------------- the cost


def test_the_map_makes_no_git_call_of_its_own(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion 3. Five `/api/map` requests add 0 reader calls, and still see the lanes."""
    three_checkouts(tmp_path)
    readers = Readers()
    p = ticked(readers)
    monkeypatch.setitem(S._desk, "poller", p)
    before = readers.calls
    assert before == 6
    server, base, token = served()
    try:
        answers = [get(base, token, "/api/map") for _ in range(5)]
    finally:
        server.shutdown()
        server.server_close()
    assert readers.calls == before
    assert all(len(a["projects"][0]["branches"]) == 4 for a in answers)


def test_rows_are_capped_at_forty_and_carry_no_ahead(fleet_home, tmp_path):
    """Acceptance criterion 4."""
    Registry().add(make_project(tmp_path / "many", ticket="RDSD-7"))
    rows = [{"name": f"wip/{i:02d}", "unmerged": True, "at": T0 - i} for i in range(55)]
    p = ticked(Readers(rows=rows, current={"many": "wip/00"}))
    entry = p.branch_rows("many")
    assert len(entry["rows"]) == 40 and entry["more"] is True
    assert [r["name"] for r in entry["rows"]] == [f"wip/{i:02d}" for i in range(40)]
    assert all(set(r) == {"name", "current", "unmerged", "ticket", "at"} for r in entry["rows"])
    assert set(entry) == {"default", "current", "ticket", "carrying", "rows", "more", "at"}

    g = M.graph(snap(row("many")), branch_rows=p.branch_rows)
    proj = g["projects"][0]
    assert len(proj["branches"]) == 40 and not any("ahead" in b for b in proj["branches"])
    assert proj["branches_says"] == "40+ branches, 40+ never reached main"


def test_a_cache_entry_is_replaced_not_mutated(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "luna", ticket="RDSD-1"))
    p = ticked(Readers(current={"luna": "main"}))
    first = p.branch_rows("luna")
    snapshot = json.dumps(first)
    p.tick(T0 + 31)
    assert p.branch_rows("luna") is not first and json.dumps(first) == snapshot


# ------------------------------------------------------------------------- before the poll


def test_no_poller_means_no_lanes_and_says_why(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion 5. `current_poller()` never constructs one, nor does a map request; with
    nothing read, `branches` is empty, every `on` is "", and `branches_says` says why."""
    Registry().add(make_project(tmp_path / "luna", ticket="RDSD-1"))
    assert S.current_poller() is None and S._desk["poller"] is None
    monkeypatch.setattr(S, "poller", lambda: None)         # nothing polls
    server, base, token = served()
    try:
        body = get(base, token, "/api/map")
    finally:
        server.shutdown()
        server.server_close()
    assert S._desk["poller"] is None, "the map request did not create a poller"
    why = "branches not read yet (the git poll runs every 30 s)"
    for g in (body, M.graph(snap(row("luna"))),
              M.graph(snap(row("luna")), branch_rows=P.Poller(Registry(), cfg=OFF).branch_rows)):
        proj = g["projects"][0]
        assert proj["branches"] == [] and proj["branches_says"] == why and proj["says"].endswith(why)
        assert proj["carry_lines"] == [] and proj["default"] == ""
        assert all(c["on"] == "" and c["agent"]["on"] == "" and c["agent"]["branch"] == ""
                   for c in g["checkouts"])


def test_the_fleet_rows_and_the_git_cell_are_unchanged(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion 6. The side cache rides beside the cells: the `/api/fleet` row keys and
    the git cell's fields and values are what they were before #403."""
    Registry().add(make_project(tmp_path / "luna", ticket="RDSD-101"))
    readers = Readers(current={"luna": "feature/RDSD-101-velocity"})
    p = P.Poller(Registry(), cfg=OFF, now=lambda: T0)
    p.git_reader, p.branch_reader = readers.git, readers.branches
    monkeypatch.setitem(S._desk, "poller", p)
    before = S.fleet_snapshot()["repos"][0]
    p.tick(T0)
    after = S.fleet_snapshot()["repos"][0]
    assert set(after) == set(before)
    assert set(after["polls"]) == set(before["polls"])

    repo = Registry().sorted()[0]
    want = P._git_value({**readers.git(repo), **readers.branches(repo, full=False)})
    assert after["polls"]["git"]["value"] == want
    assert set(want) == {"text", "branch", "ahead", "behind", "dirty", "count", "unmerged", "default",
                         "line2", "warn", "warn_at", "carrying"}
    assert "rows" not in json.dumps(after["polls"]), "the rows never ride on the fleet row"


def test_ten_projects_of_forty_branches_fit_in_160_kb():
    """Acceptance criterion 7."""
    rows, cache = [], {}
    for p in range(10):
        project = f"proj{p:02d}"
        names = [f"feature/RDSD-10{n:02d}-xxxxxxxxxxxx" for n in range(40)]
        for k in range(2):
            repo = f"{project}-{k}"
            rows.append(row(repo, project=project, path=f"/work/{repo}",
                            worktree_of="" if k == 0 else f"/work/{project}-0",
                            ticket="RDSD-1000", state="running",
                            polls={"git": {"value": {"branch": names[k]}}}))
            cache[repo] = {"default": "main", "current": names[k], "ticket": "RDSD-1000",
                           "carrying": [names[0]], "more": True, "at": T0,
                           "rows": [{"name": nm, "current": nm == names[k], "unmerged": True,
                                     "ticket": P.ticket_in(nm), "at": T0 - i}
                                    for i, nm in enumerate(names)]}
    g = M.graph(snap(*rows), branch_rows=cache.get)
    assert len(g["checkouts"]) == 20 and sum(len(x["branches"]) for x in g["projects"]) == 400
    assert len(json.dumps({"ok": True, **g, "theme": {}})) < 160 * 1024


# ------------------------------------------------------------------------------ real git


def test_seven_real_branches_through_the_poll(fleet_home, tmp_path):
    """The real read, through `Poller.tick` with the other sources off: seven branches, three that
    never reached main, HEAD on the newer of the two carrying the checkout's ticket."""
    _repo(tmp_path)
    p = P.Poller(Registry(), cfg=OFF, now=lambda: 1_000_000.0)
    p.tick(1_000_000.0)
    entry = p.branch_rows("luna")
    assert entry["current"] == "feature/RDSD-7-part-2" and len(entry["rows"]) == 7

    g = M.graph(snap(row("luna", ticket="RDSD-7")), branch_rows=p.branch_rows)
    proj, (c,) = g["projects"][0], g["checkouts"]
    assert proj["branches_says"] == "7 branches, 3 never reached main"
    assert [b["name"] for b in proj["branches"]][0] == "feature/RDSD-7-part-2"
    assert c["on"] == c["agent"]["on"] == "b:luna:feature/RDSD-7-part-2"
    assert c["agent"]["says"].endswith("· on feature/RDSD-7-part-2 · carries RDSD-7")
    carriers = {b["name"] for b in proj["branches"] if b["carrying"]}
    assert carriers == {"feature/RDSD-7-part-1", "feature/RDSD-7-part-2"}
    assert proj["carry_lines"] == [P.carry_line(entry)] and proj["carry_lines"][0]
