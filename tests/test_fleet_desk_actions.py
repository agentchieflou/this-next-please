"""Acting on an agent from the page, and being able to see that you did.

Three defects reported after v0.8.0, all of them about what happens *after* the operator does
something:

* answering an agent in focus mode hid the tile they had just answered, because answering is
  precisely what stops an agent needing you (`#3`);
* the way to unblock a stuck agent was two commands in a terminal the operator had to go and find,
  and neither is named after the problem (`#1`);
* tiles that re-ordered did it by teleporting, so the tile you were reading was somewhere else with
  no way to see that it was the same one (`#5`).

Same rules as `test_fleet_desk_regressions.py`: assert on the rendered page and on the consequence,
not on the source text and not on the mechanism.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time

import pytest

from agentdata.fleet import events as E
from agentdata.fleet import serve as S
from agentdata.fleet import supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_desk_regressions import _drain_and_age
from test_fleet_events import fleet_home                        # noqa: F401 - fixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------- reset: one verb for one intention


def test_reset_is_stop_then_resume_and_the_page_calls_the_same_function(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """`ad-fleet stop` then `ad-fleet start` was the answer, and nobody could find the question.

    The operator has an agent that has stopped answering in a `cmd.exe` window they may not be able
    to locate, and what they want is for it to go again. That is one intention, so `reset` is one
    call, and the dashboard's button and the CLI verb both reach it -- the page never grows a second
    opinion about what unblocking means.
    """
    repo = make_project(tmp_path / "stuck", phase="working", ticket="RDSD-4")
    Registry().add(repo, name="stuck")
    E.append("stuck", [E.event("stuck", "session_id", {"session": "abc123session"})])

    order = []
    monkeypatch.setattr(supervisor, "stop",
                        lambda name, **kw: order.append("stop") or {"repo": name, "stopped": True, "pid": 42})
    monkeypatch.setattr(supervisor, "restart",
                        lambda name, **kw: order.append("restart") or {"pid": 99, "session": "abc123session",
                                                                       "ticket": "RDSD-4", "restarts": 1})

    out = supervisor.reset("stuck")
    assert order == ["stop", "restart"], "it stops before it resumes, or two agents hold one checkout"
    assert out["pid"] == 99 and out["stopped"] is True
    assert out["session"] == "abc123session", "it resumes the same session rather than reading the ticket again"

    # The page's action and the CLI verb are the same function, which is what stops them drifting.
    order.clear()
    answer = S.act("reset", {"repo": "stuck"})
    assert answer["pid"] == 99
    assert order == ["stop", "restart"]


def test_reset_refuses_rather_than_starting_a_second_agent(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """A process that will not die keeps its lock, and reset respects that.

    `stop` deliberately leaves the lock in place when the pid outlives the kill, because a lock
    removed over a live agent is what lets `start` launch a second one beside it -- two `copilot`
    processes editing one working tree. Resetting past that would recreate exactly the situation the
    lock exists to prevent, so the refusal is passed through with the reason.
    """
    repo = make_project(tmp_path / "immortal", phase="working")
    Registry().add(repo, name="immortal")

    started = []
    monkeypatch.setattr(supervisor, "stop", lambda name, **kw: {
        "repo": name, "stopped": False, "pid": 4242,
        "detail": "pid 4242 was still alive 10s after the kill; the lock is kept"})
    monkeypatch.setattr(supervisor, "restart", lambda name, **kw: started.append(name) or {"pid": 1})

    with pytest.raises(supervisor.SupervisorError) as refusal:
        supervisor.reset("immortal")
    assert "would not stop" in refusal.value.msg
    assert "4242" in refusal.value.msg
    assert not started, "nothing may be restarted beside a process that is still holding the checkout"


def test_reset_on_an_unknown_repo_says_so_before_killing_anything(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """A typo must not reach `kill_tree`. The name is checked against the registry first."""
    killed = []
    monkeypatch.setattr(supervisor, "stop", lambda name, **kw: killed.append(name) or {})
    with pytest.raises(Exception):
        supervisor.reset("nosuchrepo")
    assert not killed


def test_the_unknown_action_hint_lists_reset():
    """The hint is the only place the vocabulary is written down, so a new verb goes in it."""
    with pytest.raises(S.ServeError) as refusal:
        S.act("frobnicate", {})
    assert "reset" in refusal.value.hint


# --------------------------------------------------------------------------- the page, in a browser


@pytest.fixture()
def desk(fleet_home, tmp_path):                                 # noqa: F811
    """Three projects: one that needs the human, one quiet, one that will be re-ordered."""
    asks = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-1")
    quiet = make_project(tmp_path / "quiet", phase="done")
    third = make_project(tmp_path / "third", phase="done")
    Registry().add(asks, name="asks")
    Registry().add(quiet, name="quiet")
    Registry().add(third, name="third")
    E.append("asks", [
        E.event("asks", "started", {"prompt": "Ticket RDSD-1"}, ticket="RDSD-1"),
        E.event("asks", "question_opened", {"question": "which sprint boundary?"}, ticket="RDSD-1"),
    ])
    for name in ("quiet", "third"):
        E.append(name, [E.event(name, "started", {"prompt": "t"}), E.event(name, "exited", {"exit_code": 0})])
        _drain_and_age(name, 2 * 86400)
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}&layout=grid"
    try:
        yield url
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _page(p, url):
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(".tile.is-solo", timeout=15000)
    page.wait_for_timeout(900)
    return browser, page, errors


# The two lines above the grid (#530). Each one's coming or going moves every pane, and a line that
# goes is animated out (`.enters`, app.css): it keeps its height for `--motion-base` and then takes
# it away at once, so the grid is still for the whole transition and jumps at its end.
_LINES = """() => ['renew-strip', 'day-strip'].every(id => {
                 const line = document.getElementById(id);
                 return !line || line.getAnimations().length === 0; })"""


def _press(page, selector: str) -> None:
    """Click `selector` once the lines above the grid are at rest (#530).

    Playwright waits for the button itself to hold still over two frames, and it does: a line leaving
    moves nothing until its transition ends. A press between that check and the jump landed on the
    pane under where the button had been, and the pane selected itself instead."""
    page.wait_for_function(_LINES, timeout=15000)
    page.click(selector)


def _visible(page, repo: str) -> bool:
    """On the screen, not merely in the DOM. `display:none` gives a zero rect; `hidden` need not."""
    return page.evaluate(
        """(repo) => {
             const el = document.querySelector(`.tile[data-repo="${repo}"]`);
             if (!el) return false;
             const box = el.getBoundingClientRect();
             return box.width > 0 && box.height > 0;
           }""", repo)


def _wide(page, repo: str) -> bool:
    """Given a width by this window: a pane, not a rail (#233, #234)."""
    return page.evaluate(
        """(repo) => {
             const pane = document.querySelector(`.tile[data-repo="${repo}"]`);
             return !!pane && pane.classList.contains('is-solo') && pane.dataset.tier !== 'rail';
           }""", repo)


@pytest.mark.browser
def test_the_tile_you_just_acted_on_does_not_vanish_after_needs_me(desk):
    """The defect: answering an agent hid the agent you answered.

    Focus mode showed only what `#94`'s fold says needs a person. Replying is what makes an agent
    stop needing one, so the tile went out of the filter at the instant the operator acted on it --
    and the only visible outcome of pressing Send was that the thing they were working on
    disappeared. They went looking for it in the `where` scan, which is where a person goes when
    they believe they have lost something.

    The grid's filter hid tiles; the column's folded bands (#232); the row dimmed rails (#233), and
    kept the one acted on at full strength with a hold. The filter is the *needs me* preset now
    (#234): one write of widths, which nothing takes back when an agent stops needing you. So the
    agent the operator has just answered keeps the width the preset gave it -- through its fold
    changing and through the operator opening another beside it -- with no hold, no note and
    nothing to let go of.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, desk)

        page.click("#preset-needs")
        page.wait_for_selector('.tile[data-repo="quiet"][data-tier="rail"]', timeout=5000)
        page.wait_for_function("() => windowWrites === 0", timeout=5000)
        assert _wide(page, "asks"), "the agent with an open question is what needs me is for"
        assert _visible(page, "quiet"), "a quiet agent nobody touched is a rail, on the glass"

        # Act on it. `stop` on an agent with no live process answers ok and changes nothing on
        # disk, so this is the operator's click without a real process in the fixture.
        page.click('.tile[data-repo="asks"] .stop')

        # Now make it genuinely stop needing the human, which is what a real reply does: the agent
        # opens a turn, and an open turn is `running` -- the first branch of the fold, ahead of the
        # question that is still on its record.
        E.append("asks", [E.event("asks", "turn_started", {}, ticket="RDSD-1")])
        page.evaluate("() => refresh()")
        page.wait_for_function(
            """() => !document.querySelector('.tile[data-repo="asks"]')
                        .classList.contains('needs-human')""", timeout=8000)
        assert _wide(page, "asks"), "the agent the operator acted on lost its width"

        # The operator opens another beside it, and the one they acted on is still on the glass,
        # at a width -- which a hold used to be needed for.
        page.click('.tile[data-repo="third"] .pane-rail', modifiers=["Shift"])
        page.wait_for_selector('.tile[data-repo="third"].is-solo', timeout=5000)
        page.wait_for_function("() => windowWrites === 0", timeout=5000)
        assert _wide(page, "asks"), "opening another took the width off the one acted on"
        assert page.locator(".holdnote, .release").count() == 0, "there is no hold to let go of"
        assert not errors, errors


@pytest.mark.browser
def test_a_reset_button_is_on_every_tile_and_names_what_it_does(desk):
    """The operator could not work out what to do from the page, so the page says it."""
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, desk)
        button = page.query_selector('.tile[data-repo="asks"] .reset')
        assert button is not None, "the one control for 'it is stuck, make it go again'"
        assert button.inner_text().strip().lower() == "reset"
        assert "resume the same session" in (button.get_attribute("title") or "")
        box = button.bounding_box()
        assert box and box["width"] > 0, "and it is on the screen, not merely in the template"
        assert not errors, errors


@pytest.mark.browser
def test_a_tile_never_ends_up_painted_away_from_where_the_layout_put_it(desk):
    """Re-ordering moves tiles visibly (#5), and leaves no tile behind when it is done.

    The animation is a transform applied to a grid that is already in its final state, so the thing
    worth asserting is not that it moved but that nothing is left offset: a stuck `transform` paints
    a tile somewhere its own layout box is not, and every click on it then lands on empty space.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, desk)
        # Three tiles side by side, so a move is a move on the glass: two pinned beside the open
        # one. Only the open agents are laid out now (#232), and a tile that is not laid out has
        # nowhere to travel from.
        page.evaluate("() => post('arrange', { pinned: ['quiet', 'third'] })")
        page.wait_for_function("() => document.querySelectorAll('.tile.is-solo').length === 3",
                               timeout=5000)

        before = page.evaluate("() => Array.from(document.querySelectorAll('.tile')).map(t => t.dataset.repo)")
        assert len(before) == 3

        # The invert is applied synchronously, inside the same call that re-orders the DOM, so it is
        # on the tiles the moment this returns. Without it the tile simply appears in its new place.
        inverted = page.evaluate("""() => {
            moveTile(document.querySelectorAll('.tile')[0].dataset.repo, 1);
            return Array.from(document.querySelectorAll('.tile')).filter(t => t.style.transform).length;
        }""")
        assert inverted > 0, "a re-ordered tile travels to its new place; it does not teleport"

        page.wait_for_timeout(1200)                             # longer than the 260ms transition

        after = page.evaluate("() => Array.from(document.querySelectorAll('.tile')).map(t => t.dataset.repo)")
        assert after[0] == before[1] and after[1] == before[0], "the move actually happened"

        offsets = page.evaluate("""() => Array.from(document.querySelectorAll('.tile')).map(t => {
            const style = getComputedStyle(t);
            return { repo: t.dataset.repo, transform: style.transform };
        })""")
        for row in offsets:
            assert row["transform"] in ("none", "matrix(1, 0, 0, 1, 0, 0)"), \
                f"{row['repo']} is still painted away from its layout box: {row['transform']}"
        assert not errors, errors


@pytest.mark.browser
def test_a_viewer_who_asked_for_less_motion_gets_no_transform_at_all(desk):
    """`prefers-reduced-motion` is honoured before the measurement, not only in the stylesheet.

    The global rule zeroes the duration, which is enough to stop the movement being *seen*; the
    script also skips measuring, so the work is not done either.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900},
                                reduced_motion="reduce")
        page.goto(desk, wait_until="domcontentloaded")
        page.wait_for_selector(".tile.is-solo", timeout=15000)
        page.wait_for_timeout(900)

        assert page.evaluate("() => reduceMotion()") is True
        page.evaluate("() => moveTile(document.querySelectorAll('.tile')[0].dataset.repo, 1)")
        # Immediately: with motion reduced there is no inverted frame to catch.
        stuck = page.evaluate("""() => Array.from(document.querySelectorAll('.tile'))
            .filter(t => t.style.transform).length""")
        assert stuck == 0
        browser.close()


# --------------------------------------------------- sessions the fleet did not start (#2)


def _touch(path: str, age_s: float = 0.0) -> None:
    """Make a file look like it was written `age_s` ago. Adoption turns on exactly this."""
    when = time.time() - age_s
    os.utime(path, (when, when))


def test_a_checkout_being_written_to_is_what_makes_a_session_adoptable(fleet_home, tmp_path):  # noqa: F811
    """`.agent/state.json` has one writer, so its mtime is the last moment an agent said anything.

    That is the whole detector on Windows, where a process's working directory is not readable
    without native calls this package will not make. It is a weaker claim than matching a process to
    a folder, which is why the row carries `how` and the page prints it.
    """
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "busy", phase="working", ticket="RDSD-7")
    Registry().add(repo, name="busy")
    state = os.path.join(repo, ".agent", "state.json")

    _touch(state, 5)
    assert 0 <= A.activity_age(repo) < 60

    rows = A.candidates(processes=[])
    assert [r["repo"] for r in rows] == ["busy"]
    assert rows[0]["how"] == "inferred from recent activity"
    assert rows[0]["pid"] == 0, "no process listing on this platform means no pid to claim"

    # Yesterday's session is not this morning's.
    _touch(state, 3 * A.FRESH_S)
    assert A.candidates(processes=[]) == []


def test_a_process_in_the_checkout_is_matched_exactly(fleet_home, tmp_path):  # noqa: F811
    """Where the platform gives a working directory, the claim is exact and says so."""
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "exact", phase="working")
    Registry().add(repo, name="exact")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)

    rows = A.candidates(processes=[{"pid": 4321, "cmdline": "node copilot", "cwd": repo}])
    assert rows[0]["pid"] == 4321
    assert rows[0]["how"] == "matched by working directory"


def test_adopting_supersedes_the_stale_run_the_fleet_last_started(fleet_home, tmp_path):  # noqa: F811
    """The complaint behind #2: the tile showed a cached session, not the one being worked in.

    Before adoption the fleet's newest knowledge of this repo is a run that ended; the row says
    nothing is supervised. After it, the row is supervised and a new run has begun -- which is what
    makes the transcript stop reading as a continuation of the old one.
    """
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "outside", phase="working", ticket="RDSD-8")
    Registry().add(repo, name="outside")
    E.append("outside", [
        E.event("outside", "started", {"prompt": "an old fleet run"}, ticket="RDSD-2"),
        E.event("outside", "exited", {"exit_code": 0}),
    ])
    _drain_and_age("outside", 2 * 86400)

    before = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "outside"][0]
    assert before["supervised"] is False
    assert before["not_supervised_sentence"], "this is the stale, unsupervised tile"
    assert before["adoptable"], "and the fleet can see there is something to adopt"
    old_run = before["run"]["n"]

    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    out = A.adopt("outside", pid=0)
    assert out["external"] is True

    after = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "outside"][0]
    assert after["supervised"] is True, "an adopted session is somebody working in that checkout now"
    assert after["external"] is True
    assert after["not_supervised_sentence"] == "", "and it is no longer told nothing is supervised"
    assert after["adoptable"] is None, "it is adopted; there is nothing left to offer"
    assert after["run"]["n"] > old_run, "the adopted session is a new run, not more of the old one"


def test_one_checkout_still_holds_one_agent(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """Adoption does not get to break the rule the lock exists for."""
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "taken", phase="working")
    Registry().add(repo, name="taken")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    monkeypatch.setattr(supervisor, "live", lambda name: {"pid": 777, "repo": name})

    with pytest.raises(A.AdoptError) as refusal:
        A.adopt("taken")
    assert "already running an agent" in refusal.value.msg
    assert A.candidates() == [], "nor is one offered for a repo the fleet is already driving"


def test_a_quiet_checkout_cannot_be_adopted(fleet_home, tmp_path):  # noqa: F811
    """The evidence is the activity. With none, there is nothing to take on, and it says so."""
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "still", phase="done")
    Registry().add(repo, name="still")
    _touch(os.path.join(repo, ".agent", "state.json"), 5 * A.FRESH_S)
    with pytest.raises(A.AdoptError) as refusal:
        A.adopt("still")
    assert "nothing has been written" in refusal.value.msg


def test_an_adopted_session_refuses_the_controls_it_cannot_honour(fleet_home, tmp_path):  # noqa: F811
    """There is no pipe to somebody else's stdin, and `kill_tree(0)` is our own process group.

    A Send button that silently does nothing is worse than one that says where to type; and the
    kill path is the one that once took out a CI runner's own test suite, so a lock with no pid must
    never reach it.
    """
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "theirs", phase="working")
    Registry().add(repo, name="theirs")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    A.adopt("theirs", pid=0)

    with pytest.raises(supervisor.SupervisorError) as sending:
        supervisor.send("theirs", "hello")
    assert "did not start" in sending.value.msg
    assert "type in that window" in sending.value.hint

    with pytest.raises(supervisor.SupervisorError) as stopping:
        supervisor.stop("theirs")
    assert "will not say which process" in stopping.value.msg


# The operator's own chat, stood in for (#487): a real process whose argv names `copilot`, started
# from the checkout the way a terminal starts one, that writes down every signal it can catch. It
# says it is ready once its handlers are in, so a test never races a signal against their install.
CHAT = ("import signal, sys, time\n"
        "def said(n, _f):\n"
        "    open(sys.argv[1], 'a').write(str(n) + '\\n')\n"
        "for s in ('SIGTERM', 'SIGINT', 'SIGHUP', 'SIGUSR1', 'SIGUSR2', 'SIGBREAK'):\n"
        "    if hasattr(signal, s):\n"
        "        signal.signal(getattr(signal, s), said)\n"
        "open(sys.argv[2], 'w').close()\n"
        "while True:\n"
        "    time.sleep(0.05)\n")


def _until(predicate, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the stand-in chat never said it was ready"
        time.sleep(0.02)


@pytest.fixture()
def launches(monkeypatch):
    """A launcher that records what it was asked to run and runs nothing."""
    launched: list[list[str]] = []

    class _Child:
        def __init__(self, pid):
            self.pid = pid

    def spawn(repo, name, argv, exe=None):
        launched.append(list(argv))
        return _Child(90000 + len(launched))

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    return launched


@pytest.fixture()
def no_copilot_home(tmp_path, monkeypatch):
    """Copilot's session files and store, in this test's own folder and never a real home."""
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "session-state"))
    monkeypatch.setenv("COPILOT_SESSION_STORE", str(tmp_path / "no-store.db"))
    return tmp_path / "session-state"


def _session_file(root, sid: str, checkout: str) -> str:
    """A Copilot session file for this checkout, written now: `-p` and interactive alike write one."""
    d = os.path.join(str(root), sid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"id: {sid}\ncwd: '{checkout}'\n")
    path = os.path.join(d, "events.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "assistant.turn_start", "data": {"turnId": "0"}}) + "\n")
    return path


def test_stop_and_reset_never_end_a_chat_the_fleet_did_not_start(fleet_home, no_copilot_home, tmp_path,  # noqa: F811
                                                                 monkeypatch, capsys):
    """#487. An adopted pane that knows its chat's pid used to reach `proc.kill_tree` from *Stop*:
    the operator's own terminal chat died of SIGKILL with no confirmation. *Reset* is that stop and
    then a resume, `start --force` stops first too, and `ad-fleet stop` is the same function. Every
    one of them now refuses `external_session`, says where the chat is and how to stop following
    it, and the chat is alive, unsignalled, at the end (SESS-D3: the fleet never ends it)."""
    import subprocess
    import sys

    from agentdata import cli_fleet, proc
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "rigel", phase="working", ticket="RDSD-118")
    Registry().add(repo, name="rigel")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)

    heard, ready = tmp_path / "signals.txt", tmp_path / "ready"
    chat = subprocess.Popen([sys.executable, "-c", CHAT, str(heard), str(ready), "copilot"],
                            cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            **({"start_new_session": True} if os.name != "nt" else {}))
    aimed: list[int] = []
    real_kill = proc.kill_tree
    monkeypatch.setattr(proc, "kill_tree", lambda pid: aimed.append(pid) or real_kill(pid))
    try:
        _until(ready.exists)
        A.adopt("rigel", pid=chat.pid)
        assert supervisor.live("rigel").get("pid") == chat.pid, "the pane knows its chat's pid"

        presses = [
            ("Stop", lambda: supervisor.stop("rigel", wait=1)),
            ("Reset", lambda: supervisor.reset("rigel", wait=1)),
            ("the page's Stop", lambda: S.act("stop", {"repo": "rigel"})),
            ("the page's Reset", lambda: S.act("reset", {"repo": "rigel"})),
            ("start --force", lambda: supervisor.start("rigel", new=True, force=True)),
            ("+ new session", lambda: supervisor.start("rigel", new=True)),
            ("open in a console", lambda: supervisor.console("rigel")),
        ]
        for press, call in presses:
            with pytest.raises(supervisor.SupervisorError) as refused:
                call()
            said = refused.value
            assert said.code == "external_session", (press, said.code, said.msg)
            assert "your own Copilot chat" in said.msg and f"pid {chat.pid}" in said.msg, (press, said.msg)
            assert "close it in its own window" in said.hint, (press, said.hint)
            assert "`ad-fleet release rigel`" in said.hint, (press, said.hint)
            assert "ad-fleet send" not in said.hint and "ad-fleet stop" not in said.hint, \
                (press, "a hint must not point at a verb that refuses too", said.hint)
            assert chat.poll() is None, f"{press} ended the operator's chat"

        # The terminal: one repository is a refusal, exit 2, with the hint; `--all` reports it.
        assert cli_fleet.main(["stop", "rigel"]) == 2
        out = capsys.readouterr().out
        assert "ok: false" in out and "external_session" in out and "ad-fleet release rigel" in out, out
        assert cli_fleet.main(["stop", "--all"]) == 0
        out = capsys.readouterr().out
        assert "stopped: 0" in out and "ad-fleet release rigel" in out, out

        assert chat.poll() is None, "the operator's chat is still running"
        assert chat.pid not in aimed, "nothing reached for a kill aimed at the operator's chat"
        assert not heard.exists() or heard.read_text() == "", f"the chat was signalled: {heard.read_text()}"
        assert supervisor.read_lock("rigel").get("external"), "and the fleet still follows it"
    finally:
        chat.kill()
        chat.wait(timeout=30)


def test_every_start_refuses_beside_a_chat_it_can_name(fleet_home, no_copilot_home, tmp_path,  # noqa: F811
                                                        monkeypatch, launches):
    """#487. After *hand it back*, the strip still names the chat by pid -- and *+ new session* used
    to launch a headless agent beside it at once: two agents in one working tree. The foreign guard
    ran for `--resume` only. Every start now asks, in the adopt strip's words, and launches nothing.
    """
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "orion", phase="idle", ticket="")
    Registry().add(repo, name="orion")
    E.append("orion", [E.event("orion", "started", {"pid": 4100, "session": "", "new": True}),
                       E.event("orion", "session_id", {"session": "sess-orion"}),
                       E.event("orion", "exited", {"exit_code": 0})])
    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    # `**_` because a refusal asks for a fresh listing (`max_age=0`), as the resume guard's tests do.
    monkeypatch.setattr(A, "agent_processes",
                        lambda **_: [{"pid": 26846, "cwd": repo, "cmdline": "node copilot"}])

    assert A.adopt("orion")["pid"] == 26846
    assert A.release("orion")["released"] is True        # hand it back: the chat is still there

    starts = [
        ("+ new session", lambda: supervisor.start("orion", new=True)),
        ("a ticket", lambda: supervisor.start("orion", key="RDSD-118")),
        ("a resume", lambda: supervisor.start("orion", resume="sess-orion")),
        ("a bare start", lambda: supervisor.start("orion", prompt="carry on")),
        ("the page's + new session", lambda: S.act("start", {"repo": "orion", "new": True})),
    ]
    for start, call in starts:
        with pytest.raises(supervisor.SupervisorError) as refused:
            call()
        assert refused.value.code == "foreign_session", (start, refused.value.code, refused.value.msg)
        assert "did not start" in refused.value.msg and "pid 26846" in refused.value.msg, (start, refused.value.msg)
        assert "close that window" in refused.value.hint, (start, refused.value.hint)
    assert launches == [], "no start ran beside the chat"

    # Evidence without a pid (a session file being written, a state file) refuses nothing here.
    monkeypatch.setattr(A, "agent_processes", lambda **_: [])
    _session_file(no_copilot_home, "native-orion", repo)
    supervisor.start("orion", new=True)
    assert len(launches) == 1, "a start with no process to name goes ahead, as it always has"


def test_the_fleets_own_process_and_session_are_never_somebody_elses(fleet_home, no_copilot_home,  # noqa: F811
                                                                      tmp_path, monkeypatch):
    """A `-p` turn writes the same session file an interactive chat does, and its process can still
    be exiting in the checkout when the next start comes. Neither is somebody else's: a start
    straight after a fleet turn is not refused, and `outside` never names the fleet's own pid, its
    own session, or the process asking. The turn is a real one, by the fake `copilot`, so the pid
    and the session id are the ones the supervisor and the process actually recorded."""
    import fakes

    from agentdata.fleet import adopt as A

    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "new-session")
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    cfg = {"fleet": {"notify": {"toast": False}}}
    repo = make_project(tmp_path / "vega", phase="idle", ticket="")
    Registry().add(repo, name="vega")

    def turn() -> tuple[int, str]:
        lock = supervisor.start("vega", new=True, cfg=cfg)
        deadline = time.time() + 60
        while supervisor.live("vega"):
            assert time.time() < deadline, "the fake copilot's turn never ended"
            time.sleep(0.05)
        E.refresh("vega", repo, repo_state=Registry().get("vega").state())
        return int(lock["pid"]), supervisor.session_id("vega")

    pid, session = turn()
    assert pid and session, "the turn recorded its pid and announced its session"
    assert A.fleets_own("vega") == ({pid}, {session})
    # Its process still exiting in the checkout, its `-p` session file fresh, and the asker too.
    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    _touch(_session_file(no_copilot_home, session, repo), 10)      # fresh, and older than the chat's
    monkeypatch.setattr(A, "agent_processes", lambda **_: [
        {"pid": pid, "cwd": repo, "cmdline": "copilot -p"},
        {"pid": os.getpid(), "cwd": repo, "cmdline": "python -m pytest copilot"}])
    assert A.outside("vega", fresh_listing=True) == {}

    # Where the listing cannot place a process (Windows), a session file is the evidence -- and the
    # fleet's own `-p` session file is still not somebody else's.
    monkeypatch.setattr(A, "listing_places", lambda: False)
    assert A.outside("vega") == {}
    again, _ = turn()
    assert again != pid, "a start straight after a fleet turn is not refused"

    # And where the listing places processes, a session file with no process here is nobody's.
    monkeypatch.setattr(A, "agent_processes", lambda **_: [])
    _session_file(no_copilot_home, "native-vega", repo)
    monkeypatch.setattr(A, "listing_places", lambda: True)
    assert A.outside("vega") == {}
    monkeypatch.setattr(A, "listing_places", lambda: False)
    seen = A.outside("vega")
    assert seen["session"] == "native-vega" and seen["pid"] == 0, seen
    assert seen["how"] == "matched by session file" and seen["session_file"]

    # A pid the stream recorded as *adopted* is the operator's, and stays nameable.
    E.append("vega", [E.event("vega", "started", {"pid": 26900, "adopted": True, "external": True})])
    monkeypatch.setattr(A, "agent_processes",
                        lambda **_: [{"pid": 26900, "cwd": repo, "cmdline": "node copilot"}])
    assert A.outside("vega", fresh_listing=True)["pid"] == 26900


def test_a_refused_stop_exits_2_with_its_hint(fleet_home, tmp_path, monkeypatch, capsys):  # noqa: F811
    """`ad-fleet stop` on a refusal printed `ok: true, stopped: 0` and exited 0, and dropped the
    hint -- so a script, or an operator reading the last line, took it for done. A stop of one
    repository that is refused now goes out through `_refuse`: exit 2, `error`, `hint`, `code`."""
    from agentdata import cli_fleet, proc
    from agentdata.fleet import adopt as A

    aimed: list[int] = []
    monkeypatch.setattr(proc, "kill_tree", aimed.append)
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: pid == 4242)

    repo = make_project(tmp_path / "luna", phase="working", ticket="RDSD-118")
    Registry().add(repo, name="luna")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)
    A.adopt("luna", pid=0)

    assert cli_fleet.main(["stop", "luna"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "code: external_session" in out, out
    assert "hint:" in out and "ad-fleet release luna" in out, out

    # A console the fleet opened: the registry has said exit 2 for this since #189.
    A.release("luna")
    supervisor.write_lock("luna", {"pid": 4242, "kind": "console", "repo": "luna",
                                   "path": repo, "session": "sess-c"})
    assert cli_fleet.main(["stop", "luna"]) == 2
    out = capsys.readouterr().out
    assert "code: console_window" in out and "close that window" in out, out

    # `--all` is a sweep: one row per repository, and the refusal's hint in its own column.
    assert cli_fleet.main(["stop", "--all"]) == 0
    out = capsys.readouterr().out
    assert "{repo,stopped,detail,hint}" in out and "close that window" in out, out
    assert supervisor.read_lock("luna").get("kind") == "console", "and the console's lock is kept"
    assert aimed == [], "a refused stop reaches for no kill"


def test_release_hands_back_only_what_was_adopted(fleet_home, tmp_path):  # noqa: F811
    """A release that could clear a real lock would let `start` launch a second agent over a live
    one, which is the failure the lock exists to prevent."""
    from agentdata.fleet import adopt as A

    repo = make_project(tmp_path / "mixed", phase="working")
    Registry().add(repo, name="mixed")
    _touch(os.path.join(repo, ".agent", "state.json"), 3)

    A.adopt("mixed")
    assert A.is_external("mixed")
    assert A.release("mixed")["released"] is True
    assert not A.is_external("mixed")

    supervisor.write_lock("mixed", {"pid": 999, "repo": "mixed", "path": repo})
    with pytest.raises(A.AdoptError) as refusal:
        A.release("mixed")
    assert "the fleet started" in refusal.value.msg
    assert supervisor.read_lock("mixed").get("pid") == 999, "the real lock is untouched"


def test_the_process_listing_is_cached_because_windows_spawns_powershell_for_it(monkeypatch):
    """`fleet_snapshot` runs several times a second for every window on every screen."""
    from agentdata.fleet import adopt as A

    calls = []
    monkeypatch.setattr(A, "_posix_processes", lambda: calls.append(1) or [])
    monkeypatch.setattr(A, "_windows_processes", lambda: calls.append(1) or [])
    A._cache["at"], A._cache["rows"] = 0.0, []

    A.agent_processes()
    A.agent_processes()
    A.agent_processes()
    assert len(calls) == 1, "three polls, one listing"
    A.agent_processes(max_age=0)
    assert len(calls) == 2, "and an explicit adopt can still force a fresh one"


@pytest.fixture()
def outside_desk(fleet_home, tmp_path):                         # noqa: F811
    """A repo whose checkout is being written to by something the fleet did not start."""
    busy = make_project(tmp_path / "busy", phase="working", ticket="RDSD-3")
    Registry().add(busy, name="busy")
    E.append("busy", [
        E.event("busy", "started", {"prompt": "an old fleet run"}),
        E.event("busy", "exited", {"exit_code": 0}),
    ])
    _drain_and_age("busy", 2 * 86400)
    _touch(os.path.join(busy, ".agent", "state.json"), 4)
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}&layout=grid"
    try:
        yield url
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_page_offers_the_session_it_did_not_start_and_takes_it_on(outside_desk, no_copilot_home,  # noqa: F811
                                                                    launches, tmp_path):
    """#2, from the operator's side.

    They have a `copilot` going in a `cmd.exe` window; the tile for that repository was showing the
    last run the *fleet* started, days old, and saying nothing was supervised. The page now says
    there is something here it did not start, and one click makes that session the repository's
    current one.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, outside_desk)

        strip = page.query_selector('.tile[data-repo="busy"] .outside')
        assert strip is not None
        box = strip.bounding_box()
        assert box and box["width"] > 0, "the offer is on the screen, not merely in the template"
        offer = page.inner_text('.tile[data-repo="busy"] .outside')
        assert "the fleet did not start" in offer, offer
        assert "inferred from recent activity" in offer, "it says how strong the claim is"

        # #530: `busy` is idle on a fleet run two days old, with a ticket, so the day line above the
        # grid counts it. A snapshot is read now and handed over only after the adopt's answer.
        page.wait_for_selector("#day-strip:not([hidden])", timeout=15000)
        held, released = [], []

        def hold(route):
            if released:
                route.continue_()
            else:
                held.append((route, route.fetch()))     # read by the server now, handed over later
        page.route(re.compile(r"/api/fleet\?"), hold)
        page.evaluate("() => { refresh(); }")
        deadline = time.time() + 15
        while not held and time.time() < deadline:
            page.wait_for_timeout(20)
        assert held, "the snapshot before the adopt was never asked for"

        _press(page, '.tile[data-repo="busy"] .adopt')
        # Waited for, not slept through (#227): the tile changes on the adopt's answer, and on the
        # Windows 3.14 leg of #269 that answer took over 3 s (the adoption's first write, into a
        # fleet directory the antivirus was still looking at). 900 ms was a guess at a clock.
        page.wait_for_function(
            """() => /is driving this repo/.test(
                   document.querySelector('.tile[data-repo="busy"] .outside').textContent)""",
            timeout=15000)
        # The line goes with the answer, not a snapshot later: the grid moves once, and no press that
        # follows lands on the pane under where its button was (#530).
        assert page.evaluate("() => document.getElementById('day-strip').hidden"), \
            "the answer's own row takes its pane off the day line"
        page.wait_for_function(_LINES, timeout=15000)
        where = "t => t.getBoundingClientRect().top"
        at_answer = page.eval_on_selector('.tile[data-repo="busy"]', where)
        # The held snapshot, read before the adopt, looked at the moment it is drawn and before anything
        # newer can be; then one read after the adopt. Neither counts the pane back or moves the grid.
        drawn = "() => refresh().then(() => document.getElementById('day-strip').hidden)"
        page.evaluate(f"() => {{ window.olderDrawn = ({drawn})(); }}")
        released.append(True)
        for route, response in held:
            route.fulfill(response=response)
        assert page.evaluate("() => window.olderDrawn"), "an older snapshot counted the pane back"
        assert page.evaluate(drawn)
        page.wait_for_function(_LINES, timeout=15000)
        assert page.eval_on_selector('.tile[data-repo="busy"]', where) == at_answer

        after = page.inner_text('.tile[data-repo="busy"] .outside')
        assert "is driving this repo" in after, after
        assert page.inner_text('.tile[data-repo="busy"] .adopt').strip() == "stop following it"
        # Nothing on the tile may still claim the repository is unsupervised.
        assert "nothing is supervised" not in page.inner_text('.tile[data-repo="busy"] .why')
        # And the controls that cannot reach somebody else's stdin say so instead of lying.
        assert page.get_attribute('.tile[data-repo="busy"] .send', "disabled") is not None
        # #489: *start fresh* on the head and first in the strip; Stop and Reset are not offered
        # on the operator's own chat, and say why. Send and Start keep their own words.
        assert page.is_visible('.tile[data-repo="busy"] .freshtoggle')
        assert page.is_visible('.tile[data-repo="busy"] .outside .fresh-strip')
        assert page.eval_on_selector('.tile[data-repo="busy"] .outside', "o => o.querySelector('button:not([hidden])').className") == "fresh-strip"
        for control in ("stop", "reset"):
            assert page.get_attribute(f'.tile[data-repo="busy"] .{control}', "disabled") is not None, control
            assert "start fresh leaves it" in page.get_attribute(f'.tile[data-repo="busy"] .{control}', "title")
        assert "not the fleet's to drive" in page.get_attribute('.tile[data-repo="busy"] .start', "title")
        # Stop is refused for it (#487): the operator's own chat is theirs to close, and the page
        # reads the supervisor's own words and hint, not a button that seemed to do nothing. The
        # button is not offered any more (#489), so the page's own action asks what it would have.
        page.evaluate("""() => action(document.querySelector('.tile[data-repo="busy"]'), 'stop', { repo: 'busy' })""")
        page.wait_for_function(
            """() => /your own Copilot chat/.test(
                   document.querySelector('.tile[data-repo="busy"] .err').textContent)""",
            timeout=15000)
        refused = page.inner_text('.tile[data-repo="busy"] .err')
        assert "close it in its own window" in refused and "ad-fleet release busy" in refused, refused
        assert page.is_visible('.tile[data-repo="busy"] .err'), "the refusal is on the screen"

        _press(page, '.tile[data-repo="busy"] .adopt')            # hand it back
        page.wait_for_function(
            """() => /the fleet did not start/.test(
                   document.querySelector('.tile[data-repo="busy"] .outside').textContent)""",
            timeout=15000)
        assert "the fleet did not start" in page.inner_text('.tile[data-repo="busy"] .outside')

        # #489: start fresh from the adopted pane. The chat is known by its session file (pid 0),
        # so the first press is refused `chat_open` and relabels the button; the second releases
        # the adoption and launches one clean agent on the ticket, never a `--resume`.
        busy = Registry().get("busy").path
        _session_file(no_copilot_home, "native-busy", busy)
        _press(page, '.tile[data-repo="busy"] .adopt')
        page.wait_for_function(
            """() => /is driving this repo/.test(
                   document.querySelector('.tile[data-repo="busy"] .outside').textContent)""",
            timeout=15000)
        page.wait_for_selector('.tile[data-repo="busy"] .freshtoggle:not([hidden])', timeout=15000)
        _press(page, '.tile[data-repo="busy"] .freshtoggle')
        page.wait_for_function(
            """() => /may still be open/.test(document.querySelector('.tile[data-repo="busy"] .err').textContent)""",
            timeout=15000)
        assert page.is_visible('.tile[data-repo="busy"] .err')
        assert page.inner_text('.tile[data-repo="busy"] .freshtoggle') == "start fresh — it is closed"
        assert launches == [], "the first press launches nothing"
        _press(page, '.tile[data-repo="busy"] .freshtoggle')
        deadline = time.time() + 15
        while not launches and time.time() < deadline:
            time.sleep(0.05)
        assert len(launches) == 1 and "--resume" not in launches[0], launches
        assert "RDSD-3" in launches[0][launches[0].index("-p") + 1]
        page.wait_for_function("() => /busy: left/.test(document.getElementById('notice').textContent)",
                               timeout=15000)
        # *Earlier (n)*: the chat that was left reads `your chat` and `left`, without a hover.
        _press(page, '.tile[data-repo="busy"] .spill')
        page.wait_for_function(
            """() => [...document.querySelectorAll('.tile[data-repo="busy"] .sessions .session-row:not([hidden])')]
                      .some(li => li.querySelector('.ss-src').textContent === 'your chat'
                                  && /^left · /.test(li.querySelector('.ss-chip').textContent))""",
            timeout=15000)
        page.keyboard.press("Escape")

        # A compact pane (#489): `=` puts five panes on the glass at once, and a stale one's head
        # still carries *start fresh*, which works from there.
        for name in ("c1", "c2", "c3", "c4"):
            Registry().add(make_project(tmp_path / name, ticket="RDSD-4"), name=name)
            E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-4"),
                            E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-4")])
        page.evaluate("() => refresh()")
        page.wait_for_selector('.tile[data-repo="c4"]', state="attached", timeout=15000)
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.keyboard.press("=")
        page.wait_for_selector('.tile[data-repo="c1"][data-tier="compact"]', timeout=15000)
        page.wait_for_selector('.tile[data-repo="c1"] .freshtoggle:not([hidden])', timeout=15000)
        assert page.is_visible('.tile[data-repo="c1"] .freshtoggle')
        _press(page, '.tile[data-repo="c1"] .freshtoggle')
        deadline = time.time() + 15
        while len(launches) < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert len(launches) == 2 and "--resume" not in launches[1], launches
        assert not errors, errors


# ------------------------------------------------------- the skins, rendered (#4)


@pytest.mark.browser
def test_every_skin_variant_actually_repaints_the_page(desk):
    """The contrast test proves the numbers; this proves the page uses them.

    A variant that is declared in Python, measured by the contrast test and then not written into
    the stylesheet renders as the default one -- and every check passes while the operator looks at
    somebody else's texture. So each variant is applied for real and the panel colour the browser
    computes is compared with the one `skins.py` declared and the contrast test measured.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    from agentdata.fleet import skins as K

    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, desk)
        seen = {}
        for skin_name, variant, spec in K.every_variant():
            full = f"{skin_name}:{variant}"
            page.evaluate("(name) => post('theme', { skin: name })", full)
            page.wait_for_timeout(450)
            page.evaluate("() => refresh()")
            page.wait_for_timeout(650)

            body = page.evaluate("""() => ({
                skin: document.body.getAttribute('data-skin'),
                variant: document.body.getAttribute('data-skin-variant'),
                // What the pane's text is read on: the tile's own fill, or -- for a paper skin whose
                // panes are regions ruled on the page (#253) -- the first ancestor that paints one.
                tile: (() => { for (let e = document.querySelector('.tile'); e; e = e.parentElement) {
                  const c = getComputedStyle(e).backgroundColor;
                  if (c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; }
                  return ''; })(),
                sheets: Array.from(document.head.querySelectorAll('link[data-skin]')).length,
            })""")
            assert body["skin"] == skin_name, (full, body)
            assert body["variant"] == variant, (full, body)
            assert body["sheets"] == 1, "one stylesheet per skin, never two stacked"
            seen[full] = body["tile"]

        # Each variant of a skin must paint its panel differently from its siblings; two variants
        # that compute to the same colour means one of them is not in the stylesheet at all.
        for skin_name, skin in K.SKINS.items():
            panels = {v: seen[f"{skin_name}:{v}"] for v in skin["variants"]}
            assert len(set(panels.values())) == len(panels), \
                f"{skin_name} variants do not repaint distinctly: {panels}"
        assert not errors, errors
