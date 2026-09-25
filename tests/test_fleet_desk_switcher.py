"""Sessions: D — the switcher (issue #174).

The earlier-run rows were text with no handler, and the only session-changing gesture in the whole
page was *adopt*, which then disabled Send. So a session you had finished with was something you
could read about and not open, and *I started it in a terminal yesterday* had no answer at all.

A tab strip under the run line now names this checkout's live session, the project's other
checkouts, this checkout's earlier sessions, and a clean one. Reading a session is a GET and
nothing else; making one live again is a second, deliberate press.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time

import pytest

from agentdata import cli_fleet, proc
from agentdata.fleet import adopt as A, events as E, fingerprint as FP, registry, serve as S, supervisor
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
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
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


# ------------------------------------------------------------------ start fresh, in the markup (#489)


def test_start_fresh_is_one_action_under_one_word():
    """SESS-D1: *start fresh* replaces *+ new session* everywhere, and every door is one function
    that posts the verb `ad-fleet fresh` calls. A stale or adopted rail is marked, never coloured."""
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "agentdata", "fleet", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(static, "app.css"), encoding="utf-8").read()
    head = html[html.index('<div class="head"'):html.index('<p class="runline">')]
    assert head.index('class="oldsession"') < head.index('class="freshtoggle wordbtn"')
    assert "+ new session" not in html
    assert re.search(r'class="sm-new[^>]*>\s*<span class="sm-new-label">start fresh</span><span class="sm-model">', html)
    assert "<kbd>Alt</kbd>+<kbd>N</kbd> start this pane fresh" in html
    assert re.search(r'class="fresh-strip"[^>]*>start fresh</button><button type="button" class="adopt">', html)
    assert js.count('post("fresh"') == 1 and "function newSession" not in js
    assert '"new": true' not in js, "no door posts `start {new: true}` any more"
    rings = re.findall(r"\.pane-rail:is\(\.is-stale, \.is-outside\)[^{]*\{([^}]*)\}", css)
    assert rings and all("var(--muted)" in r for r in rings), rings
    for rule in rings:
        for state in ("--running", "--waiting", "--human", "--done", "--idle"):
            assert state not in rule, rule


def test_the_start_button_posts_fresh_only_when_the_box_is_empty():
    """#509: with the reply box empty, the bottom row's Start is *Start fresh* and calls #489's
    `startFresh` (which posts `fresh`); with text in it, it posts `start` with that text as the
    ticket, as it always did. One handler, one condition, and the label follows the box."""
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "agentdata", "fleet", "static")
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(static, "app.css"), encoding="utf-8").read()
    handler = js[js.index('el.querySelector(".start")'):]
    handler = handler[:handler.index("});") + 3]
    assert re.search(r"if \(!say\.value\.trim\(\)\) startFresh\(el, row\.repo, startBtn\);", handler), handler
    assert 'action(el, "start", { repo: row.repo, ticket: say.value.trim() })' in handler, handler
    assert js.count('post("fresh"') == 1, "the only post of `fresh` is still startFresh's"
    assert re.search(r'say\.addEventListener\("input", function \(\) \{ drawStart\(', js)
    assert 'var label = empty ? "Start fresh" : "Start";' in js
    # Compact panes show the head's *start fresh* whatever `offer` says; a full pane keeps #489's rule.
    assert '.tile:not([data-tier="compact"]) .head .freshtoggle:not(.is-offer) { display: none; }' in css


def test_start_refuses_text_that_is_not_a_ticket_key(fleet_home, tmp_path, capsys, spawns):
    """#509: text in the reply box that is not a ticket key used to start an agent on it
    (`Ticket hello.`) on a pane with no ticket, and to be refused `mid_ticket` on any other. It is
    refused `not_a_ticket` on every pane, before anything else is asked, through all three doors."""
    Registry().add(make_project(tmp_path / "mid", phase="querying", ticket="RDSD-1"), name="mid")
    Registry().add(make_project(tmp_path / "free"), name="free")
    for name in ("mid", "free"):
        with pytest.raises(supervisor.SupervisorError) as e:
            supervisor.start(name, key="hello")
        assert e.value.code == "not_a_ticket" and e.value.msg == "hello is not a ticket key", e.value.msg
        assert "RDSD-123" in e.value.hint and "Start fresh" in e.value.hint and "Send" in e.value.hint
        with pytest.raises(supervisor.SupervisorError) as e:
            S.act("start", {"repo": name, "ticket": "hello"})
        assert e.value.code == "not_a_ticket"
        assert cli_fleet.main(["start", name, "hello"]) == 2
        out = capsys.readouterr().out
        assert "code: not_a_ticket" in out and "hello is not a ticket key" in out
    assert spawns["launched"] == [], "nothing launches on text that is not a ticket key"
    # A key typed in lower case is still a key; the pattern is not loosened, and not tightened.
    supervisor.start("free", key="rdsd-7")
    assert len(spawns["launched"]) == 1


#: What is installed now, for a checkout whose session is on current skills (not stale).
INSTALLED = {"version": "0.13.2", "commit": "bbbbbbbbbbbb", "skills": "222222222222"}


def _yesterdays(tmp_path, name, *, ticket="RDSD-1", phase="querying", questions=None):
    """A checkout idle on a fleet session that began yesterday, on current skills (#509): the pane
    `ad-fleet serve` shows the morning after, marked *before this session*."""
    path = make_project(tmp_path / name, phase=phase, ticket=ticket)
    if questions is not None:
        state_path = os.path.join(path, ".agent", "state.json")
        st = json.load(open(state_path, encoding="utf-8"))
        st["open_questions"] = questions
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(st, f)
    Registry().add(path, name=name)
    yday = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 86400))
    E.append(name, [
        E.event(name, "started", {"pid": 1, "resumed": False, "new": True, "session": "",
                                  "install": dict(INSTALLED)}, ticket=ticket, ts=yday),
        E.event(name, "session_id", {"session": f"s-{name}"}, ticket=ticket, ts=yday),
        E.event(name, "turn_ended", {"turn": "0"}, ticket=ticket, ts=yday),
    ])
    return path


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
    # `**_` because a refusal asks for a *fresh* listing (`max_age=0`) rather than the cached one.
    monkeypatch.setattr(A, "agent_processes",
                        lambda **_: [{"pid": 5150, "cwd": path, "cmdline": "copilot"}])

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("alpha", resume="sess-1")
    assert "did not start" in e.value.msg and "5150" in e.value.msg
    assert "ad-fleet adopt alpha" in e.value.hint
    assert e.value.code == "foreign_session"
    assert not spawns["launched"], "and it refused before launching anything"


def test_a_resume_is_not_refused_on_a_process_that_has_already_gone(
        fleet_home, tmp_path, monkeypatch, spawns):
    """The refusal above, asked ten seconds too late.

    `agent_processes` memoises its listing for ten seconds so that drawing a dashboard does not
    walk `/proc` on every poll. That is right for drawing and wrong for refusing: stopping a
    console and resuming inside that window was refused on the strength of a process that had
    already exited, and the fleet named a pid that no longer existed. It cost this repository's CI
    a red leg on three separate runs before anybody read it as a product bug rather than a flake.
    """
    from agentdata.fleet import adopt as A

    path = _repo(tmp_path)
    asked = []

    def listing(**kwargs):
        asked.append(kwargs.get("max_age"))
        # What a cache would still be holding, against what is really running now.
        return [] if kwargs.get("max_age") == 0 else [
            {"pid": 5150, "cwd": path, "cmdline": "copilot"}]

    monkeypatch.setattr(A, "agent_processes", listing)
    supervisor.start("alpha", resume="sess-1")
    assert asked and asked[0] == 0, f"the refusal read a cached listing: {asked}"
    assert spawns["launched"], "and so the resume went ahead"


def test_a_checkout_someone_saved_a_file_in_still_resumes(fleet_home, tmp_path, monkeypatch, spawns):
    """`candidates` also offers a checkout that was merely *written to* in the last quarter of an
    hour, with no pid to name. That is the operator saving a file in their editor, and refusing
    every resume on it would refuse nearly all of them."""
    from agentdata.fleet import adopt as A

    _repo(tmp_path)
    # `**_` again: without it the fresh-listing call raises `TypeError`, the broad `except` around
    # it swallows that, and this test passes for the wrong reason -- no refusal because the
    # listing blew up, rather than no refusal because there was no pid.
    monkeypatch.setattr(A, "agent_processes", lambda **_: [])
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
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
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

            # One control: the pill opens the menu, and *earlier (n)* is a label inside it
            # rather than a fourth tab beside three others (#206).
            tile.locator(".spill").click()
            page.wait_for_selector('.tile[data-repo="alpha"] .smenu:not([hidden])', timeout=5000)
            assert "earlier (1)" in tile.locator(".sm-earlier-label").inner_text().lower()
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
            tile.locator(".spill").click()
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
def test_the_session_menu_is_operable_without_a_mouse(fleet_home, tmp_path, spawns, monkeypatch):
    """Acceptance criterion: end to end from the keyboard. `Alt+[` / `Alt+]` walk the menu and
    `Alt+N` is a clean session — an item that cannot be reached by hand is a window somebody
    loses. The menu opens on the first step rather than needing a click first (#206)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repo(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            tile = page.locator('.tile[data-repo="alpha"]')
            # #489: its sessions began before the fleet recorded installs, so it is stale, and the
            # rail's face says so and names the key.
            page.wait_for_function(
                """() => /old skills/.test(document.querySelector('.tile[data-repo="alpha"] .pane-rail').getAttribute('aria-label'))""",
                timeout=10000)
            assert "Alt+N starts fresh" in tile.locator(".pane-rail").get_attribute("aria-label")
            assert tile.locator(".sm-new").inner_text().startswith("start fresh")

            tile.locator(".spill").focus()
            page.keyboard.press("Alt+]")                     # opens the menu, on *this session*
            page.wait_for_selector('.tile[data-repo="alpha"] .smenu:not([hidden])', timeout=5000)
            page.wait_for_function(
                """() => document.activeElement.classList.contains('sm-live')""", timeout=5000)
            # The earlier sessions come by their own fetch, and land between *this session* and
            # *new*. A walk begun before they arrive steps from *this session* straight to *new*;
            # the row then appears between the two, and `Alt+[` stops on it rather than going back
            # -- the Windows 3.14 leg of #258, twice. What is walked is the list, so it is waited for,
            # with `stepMenu`'s own filter (the row's pattern is in the list too, hidden).
            page.wait_for_function(
                """() => [...document.querySelectorAll('.tile[data-repo="alpha"] .sessions .ss-open')]
                          .some(b => !b.disabled && b.offsetParent !== null)""", timeout=10000)

            page.keyboard.press("Alt+]")                     # forward, into the sessions
            assert page.evaluate(
                "() => !!document.activeElement.closest('.smenu')"
                " && !document.activeElement.classList.contains('sm-live')"), \
                "Alt+] did not walk the menu"

            page.keyboard.press("Alt+[")                     # and back again
            page.wait_for_function(
                """() => document.activeElement.classList.contains('sm-live')""", timeout=5000)

            page.keyboard.press("Alt+N")                     # start this pane fresh (#489)
            assert _eventually(lambda: len(spawns["launched"]) == 1), "Alt+N started nothing"
            page.wait_for_function("() => /^alpha: /.test(document.getElementById('notice').textContent)",
                                   timeout=10000)

            # A rail says its answer in the footer: its `.err` is not on the glass. Another pane
            # opens, alpha folds to a rail, and `Alt+N` on its face is refused mid-turn -- the fresh
            # session is running -- in the server's words, and nothing more is launched.
            _repo(tmp_path, "beta")
            page.evaluate("() => refresh()")
            page.wait_for_selector('.tile[data-repo="beta"]', state="attached", timeout=10000)
            page.evaluate("() => openAgent('beta')")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=10000)
            page.evaluate("() => say('')")
            page.focus('.tile[data-repo="alpha"] .pane-rail')
            page.keyboard.press("Alt+N")
            page.wait_for_function(
                "() => /^alpha: a session changes between turns/.test(document.getElementById('notice').textContent)",
                timeout=10000)
            assert page.is_visible("#notice")
            assert len(spawns["launched"]) == 1, "Alt+N started exactly one clean session"
            assert "--resume" not in spawns["launched"][0], "clean means clean"

            # #509: start fresh is one visible press on every pane. The operator's morning: a pane
            # mid-ticket on current skills, in a fleet session that began yesterday, idle.
            monkeypatch.setattr(FP, "current", lambda: dict(INSTALLED))
            _yesterdays(tmp_path, "gamma")                    # the full pane
            _yesterdays(tmp_path, "eps")                      # its twin, for the compact pane
            _yesterdays(tmp_path, "delta", ticket="", phase="idle")
            _yesterdays(tmp_path, "asking", ticket="RDSD-4",
                        questions=[{"id": "q1", "q": "which workspace?"}])
            posts: list[tuple[str, dict]] = []
            page.on("request", lambda r: posts.append((r.url.split("?")[0].rsplit("/", 1)[-1],
                                                       json.loads(r.post_data or "{}")))
                    if r.method == "POST" else None)

            def open_pane(name, tier="full"):
                page.evaluate("() => refresh()")
                page.wait_for_selector(f'.tile[data-repo="{name}"]', state="attached", timeout=10000)
                page.evaluate(f"() => openAgent('{name}')")
                page.wait_for_selector(f'.tile[data-repo="{name}"][data-tier="{tier}"]', timeout=10000)
                return page.locator(f'.tile[data-repo="{name}"]')

            def launches(n):
                assert _eventually(lambda: len(spawns["launched"]) == n), spawns["launched"]
                return spawns["launched"][-1]

            def prompt_of(argv):
                return argv[argv.index("-p") + 1]

            gamma = open_pane("gamma")
            start, box = gamma.locator(".bottom .start"), gamma.locator(".say")
            page.wait_for_function(
                """() => /before this session/.test(document.querySelector('.tile[data-repo="gamma"] .runline').textContent)
                      && document.querySelector('.tile[data-repo="gamma"] .bottom .start').textContent === 'Start fresh'""",
                timeout=10000)
            title = start.get_attribute("title")
            assert "RDSD-1" in title and "the CLI's own choice" in title and "began yesterday" in title, title
            assert not gamma.locator(".head .freshtoggle").is_visible(), "a full pane keeps #489's head rule"
            # Text that is not a ticket key is refused, never launched: on a mid-ticket pane ...
            box.fill("hello")
            assert start.inner_text() == "Start"
            start.click()
            page.wait_for_function(
                """() => /hello is not a ticket key/.test(document.querySelector('.tile[data-repo="gamma"] .err').textContent)""",
                timeout=10000)
            assert posts[-1] == ("start", {"repo": "gamma", "ticket": "hello"}), posts
            # ... and the empty box's one press leaves yesterday's session for a clean one.
            box.fill("")
            assert start.inner_text() == "Start fresh"
            start.click()
            argv = launches(2)
            assert posts[-1] == ("fresh", {"repo": "gamma"}), posts
            assert "--resume" not in argv and "RDSD-1" in prompt_of(argv) and "s-gamma" in prompt_of(argv)
            began = [e["data"] for e in E.read("gamma") if e["kind"] == "started"][-1]
            assert began["new"] is True and began["leaves"]["session"] == "s-gamma", began
            # A ticket key in the box is today's *Start {ticket}*: it posts `start`, and the live agent
            # the press just began refuses it -- nothing more is launched.
            box.fill("RDSD-1")
            assert start.inner_text() == "Start"
            start.click()
            page.wait_for_function(
                """() => /already has a live agent/.test(document.querySelector('.tile[data-repo="gamma"] .err').textContent)""",
                timeout=10000)
            assert posts[-1] == ("start", {"repo": "gamma", "ticket": "RDSD-1"}), posts
            assert len(spawns["launched"]) == 2

            # No ticket: `hello` is refused here too, and *Start fresh* is one keyless session.
            delta = open_pane("delta")
            start, box = delta.locator(".bottom .start"), delta.locator(".say")
            box.fill("hello")
            start.click()
            page.wait_for_function(
                """() => /hello is not a ticket key/.test(document.querySelector('.tile[data-repo="delta"] .err').textContent)""",
                timeout=10000)
            assert len(spawns["launched"]) == 2, "`hello` on a pane with no ticket launches nothing"
            box.fill("")
            assert "no ticket — session-bootstrap, then router" in start.get_attribute("title")
            start.click()
            argv = launches(3)
            assert "Ticket ." not in prompt_of(argv) and "session-bootstrap" in prompt_of(argv)

            # Refusals keep their words: a pane that needs you says so in `.err`, and launches nothing.
            asking = open_pane("asking")
            asking.locator(".bottom .start").click()
            page.wait_for_function(
                """() => /answer it first/.test(document.querySelector('.tile[data-repo="asking"] .err').textContent)""",
                timeout=10000)
            assert len(spawns["launched"]) == 3

            # A chat that may still be open (a session file and no pid, the Windows shape): the pressed
            # Start arms *start fresh — it is closed*, as #489's head button does.
            monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "session-state"))
            places = A.listing_places
            monkeypatch.setattr(A, "listing_places", lambda: False)
            win = _yesterdays(tmp_path, "win")
            os.makedirs(tmp_path / "session-state" / "native-win")
            (tmp_path / "session-state" / "native-win" / "workspace.yaml").write_text(
                f"id: native-win\ncwd: '{win}'\n", encoding="utf-8")
            (tmp_path / "session-state" / "native-win" / "events.jsonl").write_text(
                json.dumps({"type": "assistant.turn_start", "data": {"turnId": "0"}}) + "\n", encoding="utf-8")
            pane = open_pane("win")
            pane.locator(".bottom .start").click()
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="win"] .bottom .start').textContent === 'start fresh — it is closed'
                      && /may still be open/.test(document.querySelector('.tile[data-repo="win"] .err').textContent)""",
                timeout=10000)
            assert len(spawns["launched"]) == 3
            monkeypatch.setattr(A, "listing_places", places)

            # A compact pane hides the bottom row's Start: its head's *start fresh* shows on every
            # compact pane, and one press does the same.
            S.act("settings", {"set": [{"key": "fleet.tiers.full_px", "value": 1600}]})
            eps = open_pane("eps", tier="compact")
            head = eps.locator(".head .freshtoggle")
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="eps"] .head .freshtoggle').offsetParent !== null""",
                timeout=10000)
            assert not eps.locator(".bottom .start").is_visible()
            head.click()
            argv = launches(4)
            assert "--resume" not in argv and "RDSD-1" in prompt_of(argv) and "s-eps" in prompt_of(argv)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert len(spawns["launched"]) == 4, "one launch per press, and none for a refusal"
