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
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
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
    page.wait_for_selector(".tile", timeout=15000)
    page.wait_for_timeout(900)
    return browser, page, errors


def _visible(page, repo: str) -> bool:
    """On the screen, not merely in the DOM. `display:none` gives a zero rect; `hidden` need not."""
    return page.evaluate(
        """(repo) => {
             const el = document.querySelector(`.tile[data-repo="${repo}"]`);
             if (!el) return false;
             const box = el.getBoundingClientRect();
             return box.width > 0 && box.height > 0;
           }""", repo)


@pytest.mark.browser
def test_the_tile_you_just_acted_on_does_not_vanish_from_focus_mode(desk):
    """The defect: answering an agent hid the agent you answered.

    Focus mode shows only what `#94`'s fold says needs a person. Replying is what makes an agent
    stop needing one, so the tile went out of the filter at the instant the operator acted on it --
    and the only visible outcome of pressing Send was that the thing they were working on
    disappeared. They went looking for it in the `where` scan, which is where a person goes when
    they believe they have lost something.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, errors = _page(p, desk)

        page.click("#focus")
        page.wait_for_timeout(300)
        assert _visible(page, "asks"), "the agent with an open question is what focus mode is for"
        assert not _visible(page, "quiet"), "a quiet agent nobody touched stays filtered out"

        # Act on it. `stop` on an agent with no live process answers ok and changes nothing on
        # disk, so this is the operator's click without a real process in the fixture.
        page.click('.tile[data-repo="asks"] .stop')
        page.wait_for_timeout(600)

        # Now make it genuinely stop needing the human, which is what a real reply does: the agent
        # opens a turn, and an open turn is `running` -- the first branch of the fold, ahead of the
        # question that is still on its record.
        E.append("asks", [E.event("asks", "turn_started", {}, ticket="RDSD-1")])
        page.evaluate("() => refresh()")
        page.wait_for_timeout(700)
        assert not page.evaluate(
            """() => document.querySelector('.tile[data-repo="asks"]').classList.contains('needs-human')"""
        ), "the fixture has to actually stop needing the human, or this test proves nothing"

        assert _visible(page, "asks"), \
            "the tile the operator acted on is held on screen; vanishing reads as data loss"
        assert not _visible(page, "quiet"), "holding one tile does not disable the filter"

        note = page.inner_text('.tile[data-repo="asks"] .holdnote')
        assert "you stopped" in note, note
        assert "no longer needs you" in note, "it says why it is still here"

        # And the operator can let it go, which is the whole of the escape hatch.
        page.click('.tile[data-repo="asks"] .release')
        page.wait_for_timeout(400)
        assert not _visible(page, "asks"), "released, it leaves focus mode like anything else"
        assert not errors, errors


@pytest.mark.browser
def test_leaving_focus_mode_lets_every_held_tile_go(desk):
    """A hold is for this pass through the queue, not for ever.

    Otherwise the next `f` opens on the leftovers of the last visit and focus mode slowly fills up
    with agents that stopped needing anybody some time yesterday.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    with playwright_module.sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        page.click("#focus")
        page.wait_for_timeout(300)
        page.click('.tile[data-repo="asks"] .stop')
        page.wait_for_timeout(500)
        assert page.evaluate("() => held.size") == 1

        page.click("#focus")                                    # off
        page.wait_for_timeout(300)
        assert page.evaluate("() => held.size") == 0
        page.click("#focus")                                    # on again
        page.wait_for_timeout(300)
        assert page.evaluate("() => held.size") == 0, "a new pass starts clean"


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
        page.wait_for_selector(".tile", timeout=15000)
        page.wait_for_timeout(900)

        assert page.evaluate("() => reduceMotion()") is True
        page.evaluate("() => moveTile(document.querySelectorAll('.tile')[0].dataset.repo, 1)")
        # Immediately: with motion reduced there is no inverted frame to catch.
        stuck = page.evaluate("""() => Array.from(document.querySelectorAll('.tile'))
            .filter(t => t.style.transform).length""")
        assert stuck == 0
        browser.close()
