"""Sitting: E — branches on the tile, and the caution the agents share (issue #184).

The operator's sentence was *make sure they're not erroneously committing too much work on one
work tree and then not having everything actually hit main*. Read against the checkout that is
stranded work: local branches with commits ahead of the default and no pull request, several per
ticket, none of them the one that will merge. `read_git` saw one branch; the catalogue never shells
out; the agent that created the next branch had never been asked to look.

`read_branches` reads the refs; the git cell says the count and goes amber at `fleet.branches.warn`;
the inspector's pane lists the rows, unmerged first; `/api/branches` and `ad-fleet branches` come
from the same function. The fixtures are real repositories built with real git: a parser test on
invented `for-each-ref` output would prove the parser and nothing about the refs.
"""
from __future__ import annotations
import io
import json
import os
import subprocess
import threading
import time
import urllib.request

import pytest

from agentdata import proc
from agentdata.fleet import launch, poll as P, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

sys_git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    P._branches_cache.clear()
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


def git(root, *args, when: int = 0) -> str:
    """One git call in the fixture. `when` pins the commit's date, because a fixture built in one
    second has every branch at the same date and the order the pane promises is then a tie."""
    env = dict(os.environ)
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{1_700_000_000 + when} +0000"
    done = subprocess.run(sys_git + list(args), cwd=root, capture_output=True, text=True, check=True, env=env)
    return done.stdout


def seven_branches(root, ticket="RDSD-7") -> str:
    """The fixture the acceptance criteria name: seven local branches, three that never reached
    `main`, two of them carrying one ticket key, and HEAD on the newer of those two."""
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "the beginning", when=100)
    for name in ("old/a", "old/b", "old/c"):                  # merged: at main
        git(root, "branch", name)
    git(root, "checkout", "-q", "-b", f"feature/{ticket}-part-1")
    git(root, "commit", "-q", "--allow-empty", "-m", f"{ticket} the first half", when=200)
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-q", "-b", "fix/RDSD-9")
    git(root, "commit", "-q", "--allow-empty", "-m", "RDSD-9 a fix nobody pushed", when=300)
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-q", "-b", f"feature/{ticket}-part-2")
    git(root, "commit", "-q", "--allow-empty", "-m", f"{ticket} the second half, one", when=400)
    git(root, "commit", "-q", "--allow-empty", "-m", f"{ticket} the second half, two", when=500)
    return root


def two_branches(root) -> str:
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "the beginning")
    git(root, "checkout", "-q", "-b", "feature/RDSD-1")
    git(root, "commit", "-q", "--allow-empty", "-m", "RDSD-1 the work")
    return root


def _repo(tmp_path, name="luna", ticket="RDSD-7", build=seven_branches):
    path = make_project(tmp_path / name, ticket=ticket)
    build(path)
    return Registry().add(path, name=name)


# ------------------------------------------------------------------------------------ the read


def test_the_read_counts_seven_three_unmerged_first_and_two_carrying_the_ticket(fleet_home, tmp_path):
    """Acceptance criterion. Seven branches, three never reached main, listed first; two carry the
    ticket and the pane's line says so. `ahead` is counted for the unmerged only."""
    repo = _repo(tmp_path)
    got = P.read_branches(repo)
    assert got["default"] == "main" and got["current"] == "feature/RDSD-7-part-2"
    assert got["count"] == 7 and got["unmerged"] == 3 and not got["more"]
    names = [b["name"] for b in got["branches"]]
    assert set(names[:3]) == {"feature/RDSD-7-part-1", "feature/RDSD-7-part-2", "fix/RDSD-9"}, names
    assert all(b["unmerged"] for b in got["branches"][:3])
    assert not any(b["unmerged"] for b in got["branches"][3:])
    assert names[0] == "feature/RDSD-7-part-2", "newest first within the unmerged"
    by = {b["name"]: b for b in got["branches"]}
    assert by["feature/RDSD-7-part-2"]["ahead"] == 2 and by["feature/RDSD-7-part-1"]["ahead"] == 1
    assert by["main"]["ahead"] is None and by["old/a"]["ahead"] is None
    assert by["feature/RDSD-7-part-2"]["current"] and by["feature/RDSD-7-part-2"]["ticket"] == "RDSD-7"
    assert by["fix/RDSD-9"]["ticket"] == "RDSD-9" and by["old/a"]["ticket"] == ""
    assert all(b["upstream"] == "" for b in got["branches"]), "nothing was ever pushed"
    assert got["ticket"] == "RDSD-7"
    assert got["carrying"] == ["feature/RDSD-7-part-2", "feature/RDSD-7-part-1"]
    assert P.carry_line(got) == ("two branches carry RDSD-7 (feature/RDSD-7-part-2, "
                                 "feature/RDSD-7-part-1); only one can merge")
    assert len(got["commits"]) == 3 and "the second half, two" in got["commits"][0]


def test_the_cheap_read_makes_no_rev_list_and_the_full_one_is_bounded(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion. Forty unmerged branches: the count stops at twenty and says *and
    more*; the git tick's read makes no `rev-list` at all; and the whole read finishes inside the
    poll's own timeout."""
    root = make_project(tmp_path / "many", ticket="RDSD-7")
    git(root, "init", "-q", "-b", "main")
    git(root, "commit", "-q", "--allow-empty", "-m", "the beginning")
    for i in range(40):
        git(root, "checkout", "-q", "-b", f"wip/{i:02d}", "main")
        git(root, "commit", "-q", "--allow-empty", "-m", f"wip {i}")
    repo = Registry().add(root, name="many")

    calls: list[list[str]] = []
    real = proc.run

    def counted(argv, **kw):
        calls.append(list(argv))
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", counted)
    t0 = time.time()
    cheap = P.read_branches(repo, full=False)
    assert cheap["count"] == 41 and cheap["unmerged"] == 40 and cheap["commits"] == []
    assert not any("rev-list" in a for a in calls), "the tick's read must never count"
    calls.clear()
    full = P.read_branches(repo)
    assert time.time() - t0 < 30, "inside the poll timeout"
    assert full["more"] is True
    assert sum(1 for a in calls if "rev-list" in a) == P.BRANCH_COUNT_LIMIT
    assert sum(1 for b in full["branches"] if b["ahead"] is not None) == P.BRANCH_COUNT_LIMIT
    assert len(full["commits"]) <= P.BRANCH_COUNT_LIMIT


def test_the_read_is_read_only_and_asks_git_with_no_optional_locks(fleet_home, tmp_path, monkeypatch):
    """Every call is a read verb and every call carries `--no-optional-locks`, for the reason
    `read_git` gives: a status on a repository the IDE is indexing must not take its lock."""
    repo = _repo(tmp_path)
    calls: list[list[str]] = []
    real = proc.run

    def counted(argv, **kw):
        calls.append(list(argv))
        assert kw.get("cwd") == repo.path
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", counted)
    P.read_branches(repo)
    verbs = {a[2] for a in calls}
    assert verbs <= {"symbolic-ref", "rev-parse", "for-each-ref", "branch", "rev-list", "log"}, verbs
    assert all(a[1] == "--no-optional-locks" for a in calls), calls
    for a in calls:
        if a[2] == "branch":
            assert "--no-merged" in a and not any(x in a for x in ("-d", "-D", "-m", "-M", "-f"))


def test_a_folder_that_is_not_a_repository_is_an_error_not_a_clean_count(fleet_home, tmp_path):
    path = make_project(tmp_path / "plain")
    repo = Registry().add(path, name="plain")
    with pytest.raises(OSError) as e:
        P.read_branches(repo)
    assert "not a git repository" in str(e.value)


def test_the_default_branch_is_origin_head_then_main_then_master(fleet_home, tmp_path):
    root = make_project(tmp_path / "m")
    git(root, "init", "-q", "-b", "master")
    git(root, "commit", "-q", "--allow-empty", "-m", "one")
    assert P.default_branch(root) == "master"
    git(root, "branch", "main")
    assert P.default_branch(root) == "main", "main outranks master when both exist"
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(root, "branch", "-D", "main")
    git(root, "branch", "trunk")
    git(root, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    assert P.default_branch(root) == "trunk", "origin/HEAD outranks both"


def test_the_ticket_a_branch_carries_is_the_jira_key_in_its_name():
    assert P.ticket_in("feature/RDSD-22490-velocity") == "RDSD-22490"
    assert P.ticket_in("rdsd-7-lowercase") == "RDSD-7"
    assert P.ticket_in("main") == "" and P.ticket_in("hotfix/velocity") == ""


# ------------------------------------------------------------------------------------ the cell


def test_the_git_cell_carries_the_count_and_goes_amber_at_the_warn_count(fleet_home, tmp_path):
    """Acceptance criteria. Seven branches: `7 branches · 3 never reached main`, amber at the
    default six. Two branches: the count, not amber; `fleet.branches.warn: 3` makes it amber. And
    the tick announced nothing: a poll cell, never a toast."""
    seven = _repo(tmp_path, "seven")
    two = _repo(tmp_path, "two", ticket="RDSD-1", build=two_branches)

    poller = P.Poller(Registry(), cfg={"fleet": {"poll": {"jira": False, "pr": False, "powerbi": False}}},
                      now=lambda: 1_000_000.0)
    assert poller.tick(1_000_000.0) == [], "the count is never an event"
    cell = poller.state_for("seven")["git"].value
    assert cell["text"].startswith("feature/RDSD-7-part-2"), cell     # `dirty`: AGENTS.md is untracked
    assert cell["line2"] == "7 branches · 3 never reached main"
    assert cell["warn"] is True and cell["warn_at"] == 6 and cell["count"] == 7 and cell["unmerged"] == 3
    assert cell["carrying"] == ["feature/RDSD-7-part-2", "feature/RDSD-7-part-1"]
    assert poller.state_for("seven")["git"].grey is False

    cell = poller.state_for("two")["git"].value
    assert cell["line2"] == "2 branches · 1 never reached main" and cell["warn"] is False

    strict = P.Poller(Registry(), cfg={"fleet": {"branches": {"warn": 3},
                                                 "poll": {"jira": False, "pr": False, "powerbi": False}}},
                      now=lambda: 2_000_000.0)
    strict.tick(2_000_000.0)
    assert strict.state_for("two")["git"].value["warn"] is False, "two is under three"
    strict2 = P.Poller(Registry(), cfg={"fleet": {"branches": {"warn": 2},
                                                  "poll": {"jira": False, "pr": False, "powerbi": False}}},
                       now=lambda: 3_000_000.0)
    strict2.tick(3_000_000.0)
    assert strict2.state_for("two")["git"].value["warn"] is True, "at the warn count, amber"
    assert P.warn_at({"fleet": {"branches": {"warn": "six"}}}) == 6, "a typo falls back"
    assert P.warn_at({"fleet": {"branches": {"warn": 0}}}) == 1


def test_a_checkout_git_cannot_read_greys_the_cell_with_the_error(fleet_home, tmp_path):
    path = make_project(tmp_path / "plain")
    Registry().add(path, name="plain")
    poller = P.Poller(Registry(), cfg={"fleet": {"poll": {"jira": False, "pr": False, "powerbi": False}}},
                      now=lambda: 1_000_000.0)
    poller.tick(1_000_000.0)
    cell = poller.state_for("plain")["git"]
    assert cell.grey and "not a git repository" in cell.error


# ------------------------------------------------------------------------- the api and the cli


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def test_the_api_and_the_cli_print_the_same_rows_from_the_same_read(fleet_home, tmp_path, capsys):
    """Acceptance criterion. `ad-fleet branches` prints the same rows the pane reads, and both are
    cached for the git interval: two reads inside it cost one set of git calls."""
    from agentdata import cli_fleet

    _repo(tmp_path)
    server, token, port = _serve()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/branches?repo=luna&t={token}") as r:
            api = json.loads(r.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/branches?repo=luna&t={token}") as r:
            again = json.loads(r.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/branches?repo=nobody&t={token}") as r:
            pass
    except urllib.error.HTTPError as e:
        assert e.code == 404
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert api["ok"] and api["count"] == 7 and api["unmerged"] == 3 and api["warn"] is True
    assert api["cached"] is False and again["cached"] is True
    assert api["carry_line"].startswith("two branches carry RDSD-7")
    assert [b["name"] for b in api["branches"]] == [b["name"] for b in again["branches"]]

    assert cli_fleet.main(["branches", "luna"]) == 0
    out = capsys.readouterr().out
    assert "branches: 7" in out and "unmerged: 3" in out and "warn: true" in out
    assert "two branches carry RDSD-7" in out
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("branches[7]{branch,"))
    rows = []
    for ln in lines[start + 1:]:
        if not ln.startswith("  "):
            break
        rows.append(ln.strip().split(","))
    assert [r[0] for r in rows] == [b["name"] for b in api["branches"]], \
        "the CLI's rows are the pane's rows, in the pane's order"
    assert [r[-1] for r in rows] == ["yes", "yes", "yes", "-", "-", "-", "-"]
    assert "none pushed" in out and "the second half, two" in out


def test_the_cli_refuses_an_unregistered_name_and_a_folder_git_cannot_read(fleet_home, tmp_path, capsys):
    from agentdata import cli_fleet

    assert cli_fleet.main(["branches", "nobody"]) == 2
    assert "ok: false" in capsys.readouterr().out
    Registry().add(make_project(tmp_path / "plain"), name="plain")
    assert cli_fleet.main(["branches", "plain"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "not a git repository" in out


# ----------------------------------------------------------------------------- the allow-list


def _patterns(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_the_agent_may_look_and_may_not_delete():
    """Acceptance criterion. The allow-list stays enumerated: the two filters are permitted,
    `git branch -D` and a bare `git branch` are not, and `for-each-ref` has no write to permit.
    Checked with the fake's own `permitted`, which reproduces the CLI's prefix rule."""
    from fakes.runner import permitted

    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs")
    allow, deny = _patterns(argv, "--allow-tool"), _patterns(argv, "--deny-tool")
    for ok in ("git branch --list", "git branch --no-merged main --format=%(refname:short)",
               "git for-each-ref refs/heads --format=%(refname:short)", "git rev-list --count main..x",
               "git checkout -b feature/RDSD-7"):
        assert permitted(ok, allow, deny)[0], ok
    for no in ("git branch -D feature/x", "git branch -d feature/x", "git branch -m a b",
               "git branch feature/x", "git checkout feature/x", "git switch feature/x",
               "git push -u origin HEAD", "git for-each-ref refs/heads --format=%(refname) | xargs git branch -D"):
        assert not permitted(no, allow, deny)[0] or "for-each-ref" in no, no
    assert "shell(git branch)" not in allow, "the verb would permit -D"
    # ...and git itself refuses the one combination a prefix cannot: a filter with a delete.
    root = os.path.join(os.environ.get("TMPDIR") or "/tmp", "agentdata-branch-filter")
    os.makedirs(root, exist_ok=True)
    if not os.path.isdir(os.path.join(root, ".git")):
        git(root, "init", "-q", "-b", "main")
        git(root, "commit", "-q", "--allow-empty", "-m", "one")
        git(root, "branch", "x")
    for argv in (["branch", "--list", "-D", "x"], ["branch", "--no-merged", "main", "-D", "x"]):
        done = subprocess.run(sys_git + argv, cwd=root, capture_output=True, text=True)
        assert done.returncode != 0, argv
    assert "x" in git(root, "branch", "--list"), "the branch is still there"


def test_the_rule_the_skills_and_the_stub_say_the_same_thing():
    """The rule is numbered after the duplicated 14 is fixed, the two skills cite it, and the
    bootstrap prints the count from the same two reads the fleet makes."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agents = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    numbers = [ln.split(".")[0] for ln in agents.splitlines() if ln[:2].rstrip(".").isdigit() and ". " in ln[:4]]
    assert numbers == [str(i) for i in range(1, len(numbers) + 1)], f"the rules are not contiguous: {numbers}"
    rule = next(ln for ln in agents.splitlines() if "Before `git checkout -b`, look" in ln)
    assert rule.startswith("16.")
    assert "fleet.branches.warn" in agents and "a branch is the operator's to delete" in agents
    for skill in ("session-bootstrap", "bitbucket-pr"):
        body = open(os.path.join(root, "skills", skill, "SKILL.md"), encoding="utf-8").read()
        assert "rule 16" in body, f"{skill} does not cite the rule"
        assert "git for-each-ref refs/heads" in body and "git branch --no-merged" in body, skill
    boot = open(os.path.join(root, "skills", "session-bootstrap", "SKILL.md"), encoding="utf-8").read()
    assert "branches=<n> (<m> unmerged)" in boot


# ------------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_the_cell_reads_the_count_is_amber_and_the_click_opens_the_pane(fleet_home, tmp_path):
    """Acceptance criterion. On the rendered page the git cell reads `7 branches · 3 never reached
    main` and is amber; the click opens the inspector on a pane that lists the three unmerged first
    and says which two carry the ticket. The amber is measured against `--waiting` resolved through
    the same probe the scrollbar test uses, so the comparison is between two computed colours."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repo(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="luna"] .cell[data-cell="git"]', timeout=20000)
            page.wait_for_function(
                """() => /7 branches/.test(document.querySelector('.tile[data-repo="luna"] .cell[data-cell="git"]').textContent)""",
                timeout=20000)
            cell = page.locator('.tile[data-repo="luna"] .cell[data-cell="git"]')
            assert cell.evaluate("el => el.tagName") == "BUTTON"
            assert "7 branches · 3 never reached main" in cell.inner_text()
            assert "feature/RDSD-7-part-2" in cell.inner_text()
            got = page.evaluate("""() => {
                const probe = document.createElement('i');
                probe.style.color = 'var(--waiting)';
                document.body.appendChild(probe);
                const waiting = getComputedStyle(probe).color;
                probe.remove();
                const c = getComputedStyle(document.querySelector('.tile[data-repo="luna"] .cell[data-cell="git"]'));
                return { waiting, border: c.borderTopColor, color: c.color, warn: document.querySelector('.tile[data-repo="luna"] .cell[data-cell="git"]').classList.contains('warn') };
            }""")
            assert got["warn"] and got["border"] == got["waiting"] and got["color"] == got["waiting"], got

            cell.click()
            page.wait_for_selector("#inspector:not([hidden]) .branches .branchrow", timeout=10000)
            page.wait_for_function(
                "() => document.querySelectorAll('#inspector .branches .branchrow').length === 7", timeout=10000)
            rows = page.eval_on_selector_all("#inspector .branches .branchrow", """els => els.map(e => ({
                name: e.querySelector('.bname').textContent, unmerged: e.classList.contains('unmerged'),
                carries: e.classList.contains('carries'), meta: e.querySelector('.bmeta').textContent }))""")
            assert [r["unmerged"] for r in rows] == [True, True, True, False, False, False, False], rows
            assert rows[0]["name"] == "feature/RDSD-7-part-2" and "+2 ahead" in rows[0]["meta"] and "current" in rows[0]["meta"]
            assert [r["name"] for r in rows if r["carries"]] == ["feature/RDSD-7-part-2", "feature/RDSD-7-part-1"]
            assert all("none pushed" in r["meta"] for r in rows)
            carry = page.locator("#inspector .branches-carry").inner_text()
            assert carry == "two branches carry RDSD-7 (feature/RDSD-7-part-2, feature/RDSD-7-part-1); only one can merge"
            assert "7 branches · 3 never reached main · on feature/RDSD-7-part-2" in page.locator("#inspector .branches-sum").inner_text()
            assert "the second half, two" in page.locator("#inspector .commits").inner_text()
            assert not page.locator("#inspector .branches-note").count(), "nothing more to say on seven"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
