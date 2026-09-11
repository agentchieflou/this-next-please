"""Sessions: D — the switcher (issue #174).

The earlier-run rows were text with no handler, and the only session-changing gesture in the whole
page was *adopt*, which then disabled Send. So a session you had finished with was something you
could read about and not open, and *I started it in a terminal yesterday* had no answer at all.

A tab strip under the run line now names this checkout's live session, the project's other
checkouts, this checkout's earlier sessions, and a clean one. Reading a session is a GET and
nothing else; making one live again is a second, deliberate press.
"""
from __future__ import annotations
import threading

import pytest

from agentdata import proc
from agentdata.fleet import events as E, registry, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a
    suite that gives every test a fresh fleet directory. Same reasoning as
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


def _started(name, session="", **data):
    return E.event(name, "started", {"session": session, **data}, ticket="RDSD-1")


def _two_sessions(name):
    """A checkout that ran session one, opened a clean session two beside it, then went back to
    one, then back to two -- which is what an afternoon of two tickets in one worktree looks like.

    Interleaved on purpose: a session is *not* a contiguous slice of the stream, so a switcher that
    sliced `earlier[]` by position would show session one's first half and call it the whole
    conversation. Session two is last, so it is the one the tile is live on.
    """
    return [
        _started(name),
        E.event(name, "session_id", {"session": "sess-1"}, ticket="RDSD-1"),
        E.event(name, "assistant_text", {"text": "one, first turn"}, ticket="RDSD-1"),
        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1"),

        _started(name, new=True),
        E.event(name, "session_id", {"session": "sess-2"}, ticket="RDSD-2"),
        E.event(name, "assistant_text", {"text": "two, first turn"}, ticket="RDSD-2"),
        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-2"),

        _started(name, session="sess-1", resumed=True),
        E.event(name, "assistant_text", {"text": "one, second turn"}, ticket="RDSD-1"),
        E.event(name, "turn_ended", {"turn": "1"}, ticket="RDSD-1"),

        _started(name, session="sess-2", resumed=True),
        E.event(name, "assistant_text", {"text": "two, second turn"}, ticket="RDSD-2"),
        E.event(name, "turn_ended", {"turn": "1"}, ticket="RDSD-2"),
    ]


def _repo(tmp_path, name="alpha", events=None):
    path = make_project(tmp_path / name, ticket="RDSD-1")
    Registry().add(path, name=name)
    E.append(name, events if events is not None else _two_sessions(name))
    return path


class _FakeChild:
    def __init__(self, pid):
        self.pid = pid


@pytest.fixture()
def spawns(monkeypatch):
    """A launcher that records what it was asked to run and never runs it.

    The acceptance criterion is that a resume is launched with `--resume <id>`, which is a claim
    about the argv -- so the argv is what the test reads, off the lock the supervisor writes, and
    no `copilot` is involved on either side of the assertion.
    """
    alive: set[int] = set()
    launched: list[list[str]] = []
    next_pid = [4300]

    def spawn(repo, name, argv, exe=None):
        launched.append(list(argv))
        next_pid[0] += 1
        alive.add(next_pid[0])
        return _FakeChild(next_pid[0])

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(proc, "kill_tree", lambda pid: alive.discard(pid))
    return {"alive": alive, "launched": launched}


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# --------------------------------------------------------------------------------- the server


def test_a_transcript_is_gathered_by_session_id_and_not_by_position(fleet_home, tmp_path):
    _repo(tmp_path)
    out = S.transcript_for("alpha", "sess-1")
    said = [(ev["data"] or {}).get("text") for ev in out["events"]
            if ev["kind"] == "assistant_text"]
    assert said == ["one, first turn", "one, second turn"], \
        "both of session one's runs, and none of session two's"
    assert out["runs"] == 2
    assert out["more"] is False

    other = S.transcript_for("alpha", "sess-2")
    assert [(ev["data"] or {}).get("text") for ev in other["events"]
            if ev["kind"] == "assistant_text"] == ["two, first turn", "two, second turn"]


def test_a_transcript_is_paged_from_the_end_it_is_read_from(fleet_home, tmp_path):
    _repo(tmp_path)
    tail = S.transcript_for("alpha", "sess-1", limit=2)
    assert tail["more"] is True and len(tail["events"]) == 2
    assert tail["cursor"] == tail["events"][0]["seq"]

    whole = [ev["seq"] for ev in S.transcript_for("alpha", "sess-1")["events"]]
    above = S.transcript_for("alpha", "sess-1", limit=2, before=tail["cursor"])
    assert [ev["seq"] for ev in above["events"]] == whole[-4:-2], \
        "the two immediately above the page just read, not the two oldest"
    assert all(ev["seq"] < tail["cursor"] for ev in above["events"])


def test_a_session_nobody_ran_has_an_empty_transcript_rather_than_an_error(fleet_home, tmp_path):
    _repo(tmp_path)
    out = S.transcript_for("alpha", "sess-nothing")
    assert out["events"] == [] and out["runs"] == 0 and out["more"] is False


def test_the_row_counts_the_other_sessions_without_a_rebuild(fleet_home, tmp_path):
    """`sessions.json` exists only once somebody has rebuilt it, and a tab that said `earlier (0)`
    over three real sessions is worse than no tab at all."""
    _repo(tmp_path)
    row = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "alpha"][0]
    assert row["sessions_n"] == 1, "sess-1; sess-2 is the one the tile is live on"


def test_a_resume_is_refused_beside_a_console_the_fleet_did_not_start(
        fleet_home, tmp_path, monkeypatch, spawns):
    """Never two agents in one working tree. The lock cannot catch this one -- the console window
    that owns it never took a lock -- so the resume asks who else is in there, in the adopt strip's
    own words."""
    from agentdata.fleet import adopt as A

    path = _repo(tmp_path)
    monkeypatch.setattr(A, "agent_processes",
                        lambda: [{"pid": 5150, "cwd": path, "cmdline": "copilot"}])

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("alpha", resume="sess-1")
    assert "did not start" in e.value.msg and "5150" in e.value.msg
    assert "ad-fleet adopt alpha" in e.value.hint
    assert e.value.code == "foreign_session"
    assert not spawns["launched"], "and it refused before launching anything"


def test_a_checkout_someone_saved_a_file_in_still_resumes(fleet_home, tmp_path, monkeypatch, spawns):
    """`candidates` also offers a checkout that was merely *written to* in the last quarter of an
    hour, with no pid to name. That is the operator saving a file in their editor, and refusing
    every resume on it would refuse nearly all of them."""
    from agentdata.fleet import adopt as A

    _repo(tmp_path)
    monkeypatch.setattr(A, "agent_processes", lambda: [])
    assert A.candidates()[0]["pid"] == 0, "the evidence is the writing, and there is no pid in it"

    lock = supervisor.start("alpha", resume="sess-1")
    assert lock["session"] == "sess-1"
    assert "--resume" in spawns["launched"][0]


# ---------------------------------------------------------------------------- the rendered page


def _eventually(predicate, timeout: float = 10.0):
    """Wait for something the *server* does. The page's own outcomes are waited for in the page;
    this is for the ones only Python can see, like a lock the supervisor wrote."""
    import time as _t

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        if predicate():
            return True
        _t.sleep(0.05)
    return False


def _page(p, port, token):
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
    page.wait_for_selector(".tile:visible", timeout=15000)
    return browser, page, errors


@pytest.mark.browser
def test_earlier_opens_a_session_read_only_and_spawns_nothing(fleet_home, tmp_path):
    """Acceptance criterion: choosing an earlier session never spawns anything — counted in
    `started` events, which is the only place a spawn can hide."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repo(tmp_path)
    before = sum(1 for ev in E.read("alpha") if ev["kind"] == "started")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            tile = page.locator('.tile[data-repo="alpha"]')

            tab = tile.locator(".earlier-tab")
            assert "earlier (1)" in tab.inner_text().lower()
            tab.click()
            page.wait_for_selector('.tile[data-repo="alpha"] .session-row:not([hidden]) .ss-open',
                                   timeout=5000)
            row = tile.locator(".session-row:not([hidden]) .ss-open").first
            assert "sess-1" in (row.get_attribute("title") or ""), "the one the tile is not on"

            row.click()
            page.wait_for_selector('.tile[data-repo="alpha"] .history:not([hidden])', timeout=5000)
            history = tile.locator(".history").inner_text()
            assert "one, first turn" in history and "one, second turn" in history, \
                "both of that session's runs, gathered by id across the stream"
            assert "two, first turn" not in history

            # Read-only: the reply box is gone rather than disabled, and one sentence says why.
            assert not tile.locator(".row.bottom").is_visible()
            assert "ended" in tile.locator(".ro-what").inner_text()

            # Back, and the live transcript is whole -- it was hidden, never thrown away.
            tile.locator(".ro-back").click()
            page.wait_for_selector('.tile[data-repo="alpha"] .transcript:not([hidden])', timeout=5000)
            assert tile.locator(".row.bottom").is_visible()
            assert "two, second turn" in tile.locator(".transcript").inner_text()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    after = sum(1 for ev in E.read("alpha") if ev["kind"] == "started")
    assert after == before, "reading a session started an agent"


@pytest.mark.browser
def test_resume_here_is_refused_while_an_agent_is_live_and_the_second_press_takes_it(
        fleet_home, tmp_path, spawns):
    """Acceptance criterion: *Resume here* refuses in the supervisor's own words while something is
    live, and the second, deliberate press stops it and resumes — launched with `--resume <id>`.
    Never a silent force, and never two agents in one working tree."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repo(tmp_path)
    # Session two is the live one, the way it would be a moment after `+ new`.
    supervisor.write_lock("alpha", {"pid": 4242, "repo": "alpha", "ticket": "RDSD-2",
                                    "session": "sess-2"})
    spawns["alive"].add(4242)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            tile = page.locator('.tile[data-repo="alpha"]')
            tile.locator(".earlier-tab").click()
            page.wait_for_selector('.tile[data-repo="alpha"] .session-row:not([hidden]) .ss-open',
                                   timeout=5000)
            tile.locator(".session-row:not([hidden]) .ss-open").first.click()
            page.wait_for_selector('.tile[data-repo="alpha"] .history:not([hidden])', timeout=5000)

            tile.locator(".ro-resume").click()
            page.wait_for_function(
                """() => /already has a live agent/.test(
                     document.querySelector('.tile[data-repo="alpha"] .ro-note').textContent)""",
                timeout=5000)
            note = tile.locator(".ro-note").inner_text()
            assert "ad-fleet stop alpha" in note, "the supervisor's own hint, not a reworded one"
            assert "stop and resume" in tile.locator(".ro-resume").inner_text().lower()
            assert not spawns["launched"], "the first press must not have started anything"

            tile.locator(".ro-resume").click()
            # The pane closes because the resume took: a refusal would have written the note again
            # and left it open.
            page.wait_for_selector('.tile[data-repo="alpha"] .readonly[hidden]', timeout=5000,
                                   state="attached")
            assert _eventually(lambda: len(spawns["launched"]) == 1)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert len(spawns["launched"]) == 1, "exactly one agent, after the second press"
    argv = spawns["launched"][0]
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == "sess-1"
    assert 4242 not in spawns["alive"], "the live one was stopped, not run beside"


@pytest.mark.browser
def test_the_strip_is_operable_without_a_mouse(fleet_home, tmp_path, spawns):
    """Acceptance criterion: end to end from the keyboard. `Alt+[` / `Alt+]` walk the strip and
    `Alt+N` is a clean session — a tab that cannot be reached by hand is a window somebody loses."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repo(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            tile = page.locator('.tile[data-repo="alpha"]')

            tile.locator(".main-tab").focus()
            page.keyboard.press("Alt+]")                     # to *earlier*, and open it
            page.wait_for_selector('.tile[data-repo="alpha"] .session-row:not([hidden])',
                                   timeout=5000)
            assert page.evaluate(
                "() => document.activeElement.classList.contains('earlier-tab')")

            page.keyboard.press("Alt+[")                     # back to main, which closes the list
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="alpha"] .sessions').hidden""",
                timeout=5000)
            assert page.evaluate(
                "() => document.activeElement.classList.contains('main-tab')")

            page.keyboard.press("Alt+N")                     # a clean session beside this one
            assert _eventually(lambda: len(spawns["launched"]) == 1), "Alt+N started nothing"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert len(spawns["launched"]) == 1, "Alt+N started exactly one clean session"
    assert "--resume" not in spawns["launched"][0], "clean means clean"
