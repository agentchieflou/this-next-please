"""The Desk defects that shipped green, one test each, and why the old tests missed them.

Every failure in this file was found by opening the page in a browser and looking, after the epic
that was supposed to build these had already merged. The tests that were meant to cover it passed
because they read the *source text* of `app.js` and `index.html` and asserted a substring was
present -- which proves an author wrote a line, not that a person can use the page. So the rules
here are:

* **Assert on the rendered page, not on the file.** Computed styles, hit-testing, and the text a
  person would read. A test that greps a stylesheet cannot know that an id selector outranks the
  user agent's `[hidden]` rule, which is the bug that made every panel permanent.
* **Assert the consequence, not the mechanism.** "A tile can be clicked" outlives any particular
  reason it could not be.
* Where the browser is not needed -- the server's own arithmetic about runs and ages -- assert it
  in Python, because those tests run everywhere and always.

`docs/plan-desk-refactor.md` is the design; #146 is the harness these belong to.
"""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.request

import pytest

from agentdata.fleet import agentstate, serve as S
from agentdata.fleet import events as E
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_events import fleet_home                        # noqa: F401 - fixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


# ------------------------------------------------------------------ the server's own arithmetic


def _drain_and_age(name: str, seconds: int) -> None:
    """Take one snapshot to drain the first read, then backdate the whole stream.

    The first read of a repository synthesises a `phase_changed` from its `.agent/state.json`,
    stamped now -- correct behaviour, and it would otherwise make every fixture look brand new.
    Draining that and then ageing the file is what a repository worked on yesterday looks like.
    """
    S.fleet_snapshot()
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - seconds))
    path = E.normalized_path(name)
    rows = []
    for line in open(path, encoding="utf-8").read().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        ev["ts"] = old
        rows.append(json.dumps(ev))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(rows) + "\n")


def test_the_age_comes_from_the_fold_when_the_supervisor_has_none():
    """Every chip rendered with an empty age, and this is why.

    `supervisor.status()` knows the age of the log it is tailing, so it answers -1 for every agent
    it is not currently running -- which is most of them, most of the time. The fold already
    carries the timestamp of the last event it saw. Reading the age from there is the difference
    between "done" and "done - 2d", and only one of those is information.
    """
    assert S.age_of_stamp("") == -1
    assert S.age_of_stamp("not a timestamp") == -1
    assert S.age_of_stamp(E.stamp()) < 5
    three_hours = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3 * 3600))
    assert 10700 < S.age_of_stamp(three_hours) < 10900


def test_a_tile_that_needs_the_human_is_never_told_it_is_unsupervised(fleet_home, tmp_path):  # noqa: F811
    """The contradiction #147 exists to remove.

    The sentence says "nothing is supervised now". An agent that stopped with an open question is
    not supervised either -- but it still needs the human, and a tile that says "needs you" in its
    chip and "nothing is supervised" in the same breath has told the operator two different things
    about the same agent. One of them has to be wrong and they cannot tell which, so the sentence
    belongs only to agents that are genuinely quiet.
    """
    repo = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-1")
    Registry().add(repo, name="asks")
    E.append("asks", [
        E.event("asks", "started", {"prompt": "Ticket RDSD-1"}, ticket="RDSD-1"),
        E.event("asks", "question_opened", {"question": "which sprint boundary?"}, ticket="RDSD-1"),
    ])
    row = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "asks"][0]

    assert agentstate.needs_the_human(row["state"]), row["state"]
    assert row["not_supervised_sentence"] == "", "an agent that needs the human is not 'unsupervised'"
    assert row["why"], "it keeps its own sentence -- the question the operator has to answer"


def test_a_quiet_tile_says_so_once_and_carries_an_age(fleet_home, tmp_path):  # noqa: F811
    """The other half: an agent with nothing outstanding and no process holding it says so."""
    repo = make_project(tmp_path / "quiet", phase="done")
    Registry().add(repo, name="quiet")
    E.append("quiet", [
        E.event("quiet", "started", {"prompt": "Ticket RDSD-9"}),
        E.event("quiet", "exited", {"exit_code": 0}),
    ])
    _drain_and_age("quiet", 2 * 86400)
    row = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "quiet"][0]

    assert not agentstate.needs_the_human(row["state"])
    assert "nothing is supervised" in row["not_supervised_sentence"]
    assert row["last_event_age_s"] > 86400, "a two-day-old run reports a two-day-old age"
    assert row["run"]["since_start"] is False, "it began before this server did"


def test_a_run_that_began_after_the_server_did_is_marked_as_this_session(fleet_home, tmp_path):  # noqa: F811
    repo = make_project(tmp_path / "fresh")
    Registry().add(repo, name="fresh")
    E.append("fresh", [E.event("fresh", "started", {"prompt": "now"})])
    row = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "fresh"][0]
    assert row["run"]["since_start"] is True
    assert row["run"]["n"] == 1


def test_the_transcript_belongs_to_the_current_run_only(fleet_home, tmp_path):  # noqa: F811
    """A tile replaying forty events of history showed a run that ended days ago as if it were now."""
    repo = make_project(tmp_path / "three")
    Registry().add(repo, name="three")
    E.append("three", [
        E.event("three", "started", {"prompt": "one"}), E.event("three", "exited", {"exit_code": 0}),
        E.event("three", "started", {"prompt": "two"}), E.event("three", "exited", {"exit_code": 0}),
        E.event("three", "started", {"prompt": "three"}),
        E.event("three", "assistant_text", {"text": "the only line that belongs to the current run"}),
    ])
    row = [r for r in S.fleet_snapshot()["repos"] if r["repo"] == "three"][0]

    assert row["run"]["n"] == 3
    assert len(row["earlier"]) == 2
    kinds = [ev["kind"] for ev in row["run"]["events"]]
    assert kinds[:2] == ["started", "assistant_text"], kinds
    assert "exited" not in kinds, "an earlier run's ending leaked into the current transcript"
    blob = json.dumps(row["run"]["events"])
    assert '"one"' not in blob and '"two"' not in blob, "the first two runs are not this transcript"


# ------------------------------------------------------------------------- the page, in a browser

pytestmark_browser = pytest.mark.browser


@pytest.fixture()
def desk(fleet_home, tmp_path):                                 # noqa: F811
    """A fleet server with two projects: one that needs the human, one that is quiet."""
    asks = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-1")
    quiet = make_project(tmp_path / "quiet", phase="done")
    Registry().add(asks, name="asks")
    Registry().add(quiet, name="quiet")
    E.append("asks", [
        E.event("asks", "started", {"prompt": "Ticket RDSD-1"}, ticket="RDSD-1"),
        E.event("asks", "question_opened", {"question": "which sprint boundary?"}, ticket="RDSD-1"),
    ])
    E.append("quiet", [
        E.event("quiet", "started", {"prompt": "Ticket RDSD-9"}),
        E.event("quiet", "exited", {"exit_code": 0}),
    ])
    _drain_and_age("quiet", 2 * 86400)
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


@pytest.mark.browser
def test_nothing_the_page_has_hidden_is_still_on_the_screen(desk):
    """The defect that made the whole dashboard unusable, and the one no test could see.

    Every panel sets `display: flex` under an id selector, which outranks the user agent's
    `[hidden] { display: none }`. So `el.hidden = true` -- the only way this page closes anything --
    changed an attribute and nothing else, and five full-height panels stayed on the glass.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, errors = _page(p, desk)
        showing = page.evaluate("""() => [...document.querySelectorAll('[hidden]')]
            .filter(e => { const r = e.getBoundingClientRect();
                           return getComputedStyle(e).display !== 'none' && r.width > 0 && r.height > 0; })
            .map(e => e.id || e.className || e.tagName)""")
        browser.close()
    assert showing == [], f"hidden, and yet on the screen: {showing}"
    assert errors == [], errors


@pytest.mark.browser
def test_a_tile_can_actually_be_clicked(desk):
    """What the operator hit first: a hidden panel over the grid still swallows the pointer.

    `display` is what removes an element from hit-testing; the `hidden` attribute alone does not.
    So the closed board sat over the left half of the grid and ate every click meant for a tile,
    which reads exactly like a dashboard whose buttons do nothing.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        covered = page.evaluate("""() => {
            const t = document.querySelector('.tile');
            const r = t.getBoundingClientRect();
            const top = document.elementFromPoint(r.left + Math.min(60, r.width / 2), r.top + 12);
            return (top && t.contains(top)) ? '' : ((top && (top.id || top.className)) || 'nothing');
        }""")
        browser.close()
    assert covered == "", f"a tile is covered by {covered!r}"


@pytest.mark.browser
def test_every_state_on_the_page_carries_its_age(desk):
    """"done" is not information. "done - 2d" is."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        chips = page.evaluate("""() => [...document.querySelectorAll('.tile .chip')]
            .map(c => ({ text: c.textContent.trim(), age: (c.querySelector('.chipage') || {}).textContent || '' }))""")
        browser.close()
    assert chips, "no chips drawn"
    for chip in chips:
        assert chip["age"].strip(), f"a state with no age: {chip['text']!r}"


@pytest.mark.browser
def test_no_tile_contradicts_its_own_chip(desk):
    """A tile that says "needs you" must not also say "nothing is supervised now"."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        bad = page.evaluate("""() => [...document.querySelectorAll('.tile')]
            .filter(t => /running|waiting|needs|blocked|error/.test(t.querySelector('.chip').textContent.toLowerCase())
                      && /nothing is supervised/.test((t.querySelector('.why') || {}).textContent || ''))
            .map(t => t.dataset.repo + ': ' + t.querySelector('.chip').textContent
                    + ' / ' + t.querySelector('.why').textContent)""")
        browser.close()
    assert bad == [], bad


@pytest.mark.browser
def test_every_tile_says_which_run_its_transcript_belongs_to(desk):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        lines = page.evaluate("""() => [...document.querySelectorAll('.tile')]
            .map(t => ((t.querySelector('.runline') || {}).textContent || '').trim())""")
        browser.close()
    assert lines and all(len(line) > 4 for line in lines), lines
    assert any("run 1" in line for line in lines), lines


@pytest.mark.browser
def test_the_sidebar_sits_beside_the_grid_and_does_not_cover_it(desk):
    """HIG *Split views*. Five fixed overlays at one edge is what this replaced."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        page.keyboard.press("b")
        page.wait_for_timeout(500)
        got = page.evaluate("""() => {
            const s = document.getElementById('side'), m = document.querySelector('main');
            if (!s || s.hidden) return null;
            const sb = s.getBoundingClientRect(), mb = m.getBoundingClientRect();
            return { position: getComputedStyle(s).position, overlaps: sb.left < mb.right - 2 };
        }""")
        browser.close()
    assert got, "pressing b opened no sidebar"
    assert got["position"] != "fixed", "the sidebar is an overlay again"
    assert not got["overlaps"], "the sidebar is sitting on top of the grid"


@pytest.mark.browser
def test_one_control_per_meaning_in_the_toolbar(desk):
    """A segmented layout picker AND a select offering the same eight choices is two controls."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        got = page.evaluate("""() => ({
            segments: document.querySelectorAll('#layoutgroup .segment').length,
            legacy: !!document.querySelector('select#layout'),
            skin: !!document.getElementById('skin'),
            theme: !!document.getElementById('theme'),
            clipped: document.querySelector('.toolbar').scrollWidth > document.querySelector('.toolbar').clientWidth,
        })""")
        browser.close()
    assert got["segments"] == 3, got
    assert not got["legacy"], "the old layout select is back beside the segmented control"
    assert got["skin"] and got["theme"], "the palette and the skin are both chosen from the page"
    assert not got["clipped"], "the toolbar is wider than the window and a control is off the edge"


@pytest.mark.browser
def test_changing_the_layout_keeps_the_page(desk):
    """The picker used to set `location.search`, which reloads: every transcript and open panel went."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        page.evaluate("window.__kept = 'still here'")
        page.click('.segment[data-layout="roles"]')
        page.wait_for_timeout(600)
        kept = page.evaluate("window.__kept")
        url = page.url
        browser.close()
    assert kept == "still here", "the page reloaded"
    assert "layout=roles" in url, url


@pytest.mark.browser
def test_a_skin_loads_only_when_it_is_asked_for(desk):
    """#154's contract: no skin bytes reach the page until somebody chooses one."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser, page, _ = _page(p, desk)
        assert page.evaluate("() => !document.head.querySelector('link[data-skin]')")
        page.evaluate("""async () => {
            const u = new URL(location.href);
            await fetch('/api/theme?t=' + u.searchParams.get('t'),
                        { method: 'POST', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ skin: 'voxel' }) });
        }""")
        page.wait_for_timeout(2500)
        href = page.evaluate("""() => { const l = document.head.querySelector('link[data-skin]');
                                        return l ? l.href : ''; }""")
        browser.close()
    assert "/static/skins/voxel/skin.css" in href, href
