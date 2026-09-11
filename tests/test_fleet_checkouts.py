"""Sessions: E — checkouts of one project (issue #175).

Two `git worktree` checkouts of one repository registered as two strangers: the same links, blank
branches, two colours, and an inbox that gave up rather than choose between them. They are two
working trees of one piece of work, and one field says so.

**One agent per registered working tree**, not per repository: the lock, the agent directory, the
event stream and the session are all per checkout, and `project` is only what groups them.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import theme_project
from agentdata.fleet import inbox as IN, registry, scan, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a
    suite that gives every test a fresh fleet directory. CI shuffles the order twice on purpose,
    so a fixture that borrows these has to give them back. Same reasoning as
    `tests/test_fleet_desk_sessions_b.py`."""
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


def _worktree(tmp_path, main_path, folder="luna-hotfix", ticket="RDSD-2"):
    """A checkout whose `.git` is a file pointing back into the main checkout, as git writes it."""
    os.makedirs(os.path.join(main_path, ".git", "worktrees", "hotfix"), exist_ok=True)
    tree = make_project(tmp_path / folder, ticket=ticket)
    with open(os.path.join(tree, ".git"), "w", encoding="utf-8", newline="\n") as f:
        f.write("gitdir: %s\n" % os.path.join(main_path, ".git", "worktrees", "hotfix"))
    return tree


# ------------------------------------------------------------------------------- the registry


def test_a_registry_from_the_previous_release_loads_and_saves_back_unchanged(fleet_home, tmp_path):
    """Acceptance criterion. `project` defaults to `name`, so a registry written before this slice
    is unchanged by definition -- and `extra` round-trips, which is what lets anything be added to
    an entry at all."""
    repo = make_project(tmp_path / "luna", ticket="RDSD-1")
    os.makedirs(fleet_home, exist_ok=True)
    before = json.dumps({"version": 1, "repos": [
        {"name": "luna", "path": repo, "jira_project": "RDSD", "added": "2026-01-01 09:00"}]},
        indent=2) + "\n"
    path = os.path.join(fleet_home, "registry.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(before)

    reg = Registry()
    assert reg.get("luna").project == "luna"
    assert reg.get("luna").worktree_of == ""
    reg.save()
    with open(path, encoding="utf-8") as f:
        assert f.read() == before, "saving back changed a registry nobody edited"


def test_an_unknown_key_survives_a_round_trip(fleet_home, tmp_path):
    """`load()` used to drop what it did not recognise, so a field written by a newer build was
    erased by the next `repo add` from an older one."""
    repo = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(repo, name="luna")
    path = os.path.join(fleet_home, "registry.json")
    body = json.loads(open(path, encoding="utf-8").read())
    body["repos"][0]["invented_by_a_later_build"] = "kept"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(body, indent=2) + "\n")

    reg = Registry()
    assert reg.get("luna").extra["invented_by_a_later_build"] == "kept"
    reg.save()
    again = json.loads(open(path, encoding="utf-8").read())
    assert again["repos"][0]["invented_by_a_later_build"] == "kept"


def test_adding_a_worktree_names_it_after_the_project_it_belongs_to(fleet_home, tmp_path):
    """Acceptance criterion: `repo add` of a worktree registers it as `proj-<basename>` with
    `project: proj`."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)

    reg = Registry()
    reg.add(main, name="luna")
    added = reg.add(tree)

    assert added.name == "luna-hotfix", "and not luna-luna-hotfix"
    assert added.project == "luna"
    assert added.worktree_of.lower().endswith("/luna")
    assert Registry().get("luna-hotfix").project == "luna", "and it survives the reload"


def test_a_worktree_of_something_unregistered_is_its_own_project(fleet_home, tmp_path):
    """The `gitdir:` line is followed, but a main checkout nobody registered groups nothing: the
    fleet does not register a repository because it found a pointer to it."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)

    added = Registry().add(tree)
    assert added.name == "luna-hotfix" and added.project == "luna-hotfix"
    assert added.worktree_of.lower().endswith("/luna"), "the fact is still recorded"
    assert "luna" not in Registry().repos, "and nothing was registered on its behalf"


def test_project_can_be_said_by_hand(fleet_home, tmp_path):
    a = make_project(tmp_path / "one", ticket="RDSD-1")
    b = make_project(tmp_path / "two", ticket="RDSD-2")
    reg = Registry()
    reg.add(a, name="one", project="velocity")
    reg.add(b, name="two", project="velocity")
    assert [r.project for r in Registry().sorted()] == ["velocity", "velocity"]


# ----------------------------------------------------------------------------------- the scan


def test_the_scan_says_a_candidate_is_a_worktree_of_a_project_it_knows(fleet_home, tmp_path):
    """Acceptance criterion: the scan's line says *a worktree of proj* -- in the one line the human
    decides on, and without reading anything inside the main checkout."""
    holder = tmp_path / "projects"
    holder.mkdir()
    main = make_project(holder / "luna", ticket="RDSD-1")
    _worktree(holder, main, folder="luna-hotfix")
    Registry().add(main, name="luna")

    found = {c.name: c for c in scan.scan(str(holder), depth=1)}
    assert "luna-hotfix" in found, sorted(found)
    row = found["luna-hotfix"]
    assert "a worktree of luna" in row.why
    assert "would be registered as a checkout of it" in row.why
    assert row.worktree_of.lower().endswith("/luna")
    assert "worktree_of" in row.to_json()


def test_the_scan_says_so_even_when_the_main_checkout_is_a_stranger(fleet_home, tmp_path):
    holder = tmp_path / "projects"
    holder.mkdir()
    main = make_project(holder / "luna", ticket="RDSD-1")
    _worktree(holder, main, folder="luna-hotfix")

    found = {c.name: c for c in scan.scan(str(holder), depth=1)}
    assert "a git worktree; its main checkout is not registered here" in found["luna-hotfix"].why


# ------------------------------------------------------------------------- one colour, one tray


def test_two_checkouts_of_one_project_wear_one_colour(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion. The colour is chosen for the *project*, so a worktree wears its
    project's without anyone having to configure it twice -- and it is looked up under the project
    key, which is the only name the operator ever said."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    other = make_project(tmp_path / "velocity", ticket="RDSD-9")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)
    reg.add(other, name="velocity")

    monkeypatch.setattr(theme_project.config, "load",
                        lambda *a, **k: {"theme": {"default": "greens",
                                                   "projects": {"luna": "blues"}}})
    by_name = {e["name"]: e for e in theme_project.resolve_project_themes()}
    assert by_name["luna"]["theme_name"] == by_name["luna-hotfix"]["theme_name"] == "blues", \
        "the worktree was never named in the config, and still wears the project's colour"
    assert by_name["luna"]["accent"] == by_name["luna-hotfix"]["accent"]
    assert by_name["velocity"]["theme_name"] == "greens", \
        "and a project nobody chose for is still the default"
    assert by_name["luna-hotfix"]["project"] == "luna"


def test_the_hook_rules_are_longest_path_first(fleet_home, tmp_path):
    """A worktree checked out *inside* its main checkout would otherwise be recoloured by the
    parent's prefix rule before its own was reached."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    inside = _worktree(tmp_path / "luna", main, folder="wt")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(inside)

    paths = [e["path"] for e in theme_project.resolve_project_themes()]
    assert paths == sorted(paths, key=len, reverse=True)
    assert paths[0].lower().endswith("/luna/wt")


def test_a_download_naming_the_key_goes_to_the_checkout_working_it(fleet_home, tmp_path):
    """Acceptance criterion: not `unsorted`. Two checkouts of one project share a `jira_project`,
    which used to be exactly the tie the inbox refused to break."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main, ticket="RDSD-2")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)

    tray = IN.Inbox(registry=reg)
    project, ticket, why = tray._match("RDSD-2 uat refresh.xlsx")
    assert project == "luna-hotfix", why
    assert ticket == "RDSD-2"
    assert "unsorted" not in why


def test_a_download_with_no_ticket_falls_to_the_primary_checkout(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main, ticket="RDSD-2")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)

    project, ticket, why = IN.Inbox(registry=reg)._match("RDSD-77 something nobody is on.xlsx")
    assert project == "luna", why
    assert "unsorted" not in why


def test_two_different_projects_are_still_unsorted(fleet_home, tmp_path):
    """The tie that has no answer still has none. A wrong attach is a file in the wrong agent's
    inputs, and there is no undo for the confusion."""
    a = make_project(tmp_path / "one", ticket="RDSD-1")
    b = make_project(tmp_path / "two", ticket="RDSD-3")
    reg = Registry()
    reg.add(a, name="one")
    reg.add(b, name="two")

    project, _ticket, why = IN.Inbox(registry=reg)._match("RDSD-77 nobody is on this.xlsx")
    assert project == "" and "unsorted" in why


# -------------------------------------------------------------------------------- the fleet row


def test_the_row_carries_the_project_and_the_checkouts_beside_it(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    other = make_project(tmp_path / "velocity", ticket="RDSD-9")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)
    reg.add(other, name="velocity")

    rows = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}
    assert rows["luna"]["project"] == "luna"
    assert [s["repo"] for s in rows["luna"]["siblings"]] == ["luna-hotfix"]
    assert [s["repo"] for s in rows["luna-hotfix"]["siblings"]] == ["luna"]
    assert rows["velocity"]["siblings"] == [], "a project of one has no tabs beside it"


def test_a_project_is_hidden_and_pinned_as_one(fleet_home, tmp_path):
    """Putting half a piece of work away is an arrangement nobody asked for. Expanded on the
    server, so `ad-fleet hide` and every open window agree by construction."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    other = make_project(tmp_path / "velocity", ticket="RDSD-9")
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)
    reg.add(other, name="velocity")

    S.arrange("grid", hidden=["luna"], pinned=["velocity"])
    arr = S.desk_state()["arrangement"]["grid"]
    assert sorted(arr["hidden"]) == ["luna", "luna-hotfix"]
    assert arr["pinned"] == ["velocity"], "a project of one is still just itself"


def test_an_arrangement_naming_an_unregistered_tile_keeps_it(fleet_home, tmp_path):
    """An arrangement outlives a registration: a disconnected drive must not silently lose the
    operator's desk."""
    repo = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(repo, name="luna")
    S.arrange("grid", hidden=["luna", "gone-last-week"])
    assert S.desk_state()["arrangement"]["grid"]["hidden"] == ["luna", "gone-last-week"]


def test_both_checkouts_hold_their_own_lock(fleet_home, tmp_path):
    """Acceptance criterion: two agents at once, two locks. One agent per registered *working
    tree* is what the lock has always meant."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)

    supervisor.write_lock("luna", {"pid": 4242, "repo": "luna", "ticket": "RDSD-1"})
    supervisor.write_lock("luna-hotfix", {"pid": 4343, "repo": "luna-hotfix", "ticket": "RDSD-2"})
    assert supervisor.read_lock("luna")["pid"] == 4242
    assert supervisor.read_lock("luna-hotfix")["pid"] == 4343
    assert registry.agent_dir("luna") != registry.agent_dir("luna-hotfix")


def test_show_takes_the_branch_from_the_checkout_not_from_the_index(fleet_home, tmp_path,
                                                                    monkeypatch):
    """Acceptance criterion: `/api/show` for a worktree carries its *own* branch.

    The catalogue writes one entry per repository and its branch reader will not follow a
    worktree's `gitdir:` pointer -- rightly, that is a second repository's internals -- so two
    checkouts read the same branch, which is the one string they most need to differ in. The poll
    already shells out in each checkout, so it is the reader with the answer.
    """
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)

    monkeypatch.setattr(S, "poll_state", lambda name: {
        "git": {"source": "git", "value": {"branch": "feature/RDSD-2", "text": "feature/RDSD-2"},
                "age_s": 1.0, "error": "", "grey": False}})
    out = S.show_for("luna-hotfix")
    assert out["branch"] == "feature/RDSD-2"
    assert out["branch_from"] == "poll"
    assert out["project"] == "luna"
    assert out["worktree_of"].lower().endswith("/luna")


def test_a_checkout_with_no_poll_running_still_answers(fleet_home, tmp_path, monkeypatch):
    """Every half of this panel degrades on its own: no poller is a blank branch, not an error."""
    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    Registry().add(main, name="luna")
    monkeypatch.setattr(S, "poll_state", lambda name: {})
    out = S.show_for("luna")
    assert out["branch"] == "" and out["branch_from"] == ""


# ---------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_the_strip_carries_the_other_checkouts_of_this_project(fleet_home, tmp_path):
    """The tabs beside the main one are the project's other checkouts, each with its own agent and
    its own chip. Clicking one selects that checkout's tile -- the strip stays, so the way back is
    one click and never `Esc`."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    import threading

    from agentdata.fleet import events as E

    main = make_project(tmp_path / "luna", ticket="RDSD-1")
    tree = _worktree(tmp_path, main)
    reg = Registry()
    reg.add(main, name="luna")
    reg.add(tree)
    for name, ticket in (("luna", "RDSD-1"), ("luna-hotfix", "RDSD-2")):
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket=ticket),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket=ticket)])

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        from test_fleet_desk_browser import launch_chromium

        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            tile = page.locator('.tile[data-repo="luna"]')
            page.wait_for_selector('.tile[data-repo="luna"] .sib-tab:not([hidden])', timeout=5000)
            sib = tile.locator(".sib-tab:not([hidden])").first
            assert "luna-hotfix" in (sib.get_attribute("title") or "") or \
                   "luna-hotfix" in sib.inner_text()

            sib.click()
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="luna-hotfix"]')
                          .classList.contains('is-focused')""",
                timeout=5000)
            # The strip is still there on the tile it went to, so the way back is a click.
            assert page.locator('.tile[data-repo="luna-hotfix"] .sib-tab:not([hidden])').count() == 1
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
