"""One agent open, every other one beside it -- the column (issue #203), and the row that replaced it
(issue #233).

The column put every agent that was not open into a band, one above another, in a box beside the
glass. The operator's correction (docs/plan-panes.md §Decisions 3): *each agent is a column, not
each agent is stacked in one column -- skinnier agents.* So every agent is a pane in one row now, the
open one wide and every other one a 48px rail, and what the column's tests asserted is asserted of
the row:

* *so there isn't so much negative space* -- the panes SUM to the row's width, and every one of them
  is the row's full height, measured at three viewport heights;
* the swap, `Esc` back, the digits and `j`/`k`, the hidden count, the red that nothing reorders, the
  three controls and their keys -- each ported from the band to the pane that carries it now.

The tiers themselves (rail, compact, full) at three window widths are `tests/test_fleet_panes.py`.
"""
from __future__ import annotations
import os
import re
import threading
import time

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a suite
    that gives every test a fresh fleet directory."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    # The hand-refresh floor is per process and per repository, which is right for a server and
    # wrong for a suite where every test has its own fleet directory and reuses the same names.
    monkeypatch.setattr(S, "_refreshed_at", {})


def _repos(tmp_path, *names, needs=()):
    for name in names:
        path = make_project(tmp_path / name, ticket="RDSD-1")
        Registry().add(path, name=name)
        events = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                  E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
        if name in needs:
            events.append(E.event(name, "question_opened",
                                  {"question": "which window should this land in?",
                                   "id": "q1", "blocking": True},
                                  ticket="RDSD-1"))
        E.append(name, events)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _until(ready, timeout: float = 10.0) -> None:
    """Wait for something the server holds -- a record, not a pixel -- rather than for a clock."""
    deadline = time.monotonic() + timeout
    while not ready():
        assert time.monotonic() < deadline, "the server never got there"
        time.sleep(0.05)


def _open(page, port, token, extra=""):
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    # What is meant, not the first `.tile` in the DOM: an open pane that has been given its width,
    # and at least one rail beside it.
    page.wait_for_selector('.tile.is-solo[data-tier="full"]', timeout=10000)
    page.wait_for_selector('.tile[data-tier="rail"]', timeout=10000)


# The rails on the glass, in the row's order.
RAILS = """() => [...document.querySelectorAll(
                   '#grid .tile[data-tier="rail"]:not(.is-hidden):not(.is-grouped)')]
                   .map(t => t.dataset.repo)"""


def _rail(repo):
    return f'.tile[data-repo="{repo}"] .pane-rail'


# ----------------------------------------------------------------------------------- the server


def test_the_open_agent_is_the_windows_own_and_the_selection_is_shared(fleet_home, tmp_path):
    """Two monitors read two agents; the inspector still follows one selection. `open` is therefore
    per window and `selected` is not, and a restart brings each window back to its own."""
    _repos(tmp_path, "alpha", "beta")
    S.update_window("main", open="alpha")
    S.update_window("left", open="beta")
    state = S.desk_state()
    assert state["windows"]["main"]["open"] == "alpha"
    assert state["windows"]["left"]["open"] == "beta"

    # A clean shutdown keeps the desk (#172), so each window comes back where it was left.
    S.drop_handles()
    S._desk_loaded = False
    S._selection["windows"] = {}
    again = S.desk_state()["windows"]
    assert again["main"]["open"] == "alpha"
    assert again["left"]["open"] == "beta"


def test_a_window_written_before_this_slice_loads_without_an_open_key(fleet_home, tmp_path):
    """`open` is additive: a window saved by an older build has none and must not raise."""
    _repos(tmp_path, "alpha")
    S.update_window("main", focus=False)
    del S._selection["windows"]["main"]["open"]
    S.update_window("main", open="alpha")
    assert S.desk_state()["windows"]["main"]["open"] == "alpha"


# ------------------------------------------------------------------------------ the rendered page


@pytest.mark.browser
@pytest.mark.parametrize("height", [720, 1080, 1440])
def test_the_panes_fill_the_row_at_every_viewport_height(fleet_home, tmp_path, height):
    """The column's acceptance criterion, ported to the row: *so there isn't so much negative
    space.* Five agents, one open, four rails -- and the five panes between them account for the
    row's whole width, and every one of them its whole height, rather than sitting in a clump.
    (It was four bands summing to the column's height; #233.)"""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon")
    S.arrange(order=["alpha", "beta", "gamma", "delta", "epsilon"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": height})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            page.wait_for_function(f"() => ({RAILS})().length === 4", timeout=10000)

            measured = page.evaluate("""() => {
              const row = document.getElementById('grid');
              const panes = [...row.querySelectorAll('.tile:not(.is-hidden)')];
              const style = getComputedStyle(row);
              const inner = row.clientWidth - parseFloat(style.paddingLeft) -
                            parseFloat(style.paddingRight);
              const tall = row.clientHeight - parseFloat(style.paddingTop) -
                           parseFloat(style.paddingBottom);
              const gap = parseFloat(style.columnGap || '0') * (panes.length - 1);
              return {
                panes: panes.length,
                sum: panes.reduce((n, t) => n + t.getBoundingClientRect().width, 0) + gap,
                inner: inner,
                heights: panes.map(t => t.getBoundingClientRect().height),
                tall: tall,
                rails: panes.filter(t => t.dataset.tier === 'rail')
                            .map(t => Math.round(t.getBoundingClientRect().width)),
                scrolls: row.scrollWidth > row.clientWidth + 1,
              };
            }""")
            assert not errors, errors
            assert measured["panes"] == 5, "every agent is a pane"
            assert measured["rails"] == [48, 48, 48, 48], "one of five is open; four are rails"
            # Within a pixel: the panes share the row's whole width, and nothing scrolls.
            assert abs(measured["sum"] - measured["inner"]) < 1.5, measured
            assert not measured["scrolls"], measured
            # And every pane is the row's full height, the rails included.
            assert all(abs(h - measured["tall"]) < 1.5 for h in measured["heights"]), measured
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_twelve_agents_fit_the_row_and_the_footer_counts_who_needs_you(fleet_home, tmp_path):
    """Past its minimums the column scrolled and its head counted the bands. The row does not
    scroll: twelve agents are one pane and eleven rails, every one on the glass, and the footer
    says how many want a person. The column's head, and its "go to the first" jump, went with the
    column (#233): a red rail is never off the glass to be jumped to."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(12)]
    _repos(tmp_path, *names, needs=("r03", "r07"))
    S.arrange(order=names)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": 720})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            page.wait_for_function(f"() => ({RAILS})().length === 11", timeout=10000)

            out = page.evaluate("""() => {
              const row = document.getElementById('grid');
              const rails = [...row.querySelectorAll('.tile[data-tier="rail"]')];
              const glass = document.documentElement;
              return {
                n: rails.length,
                scrolls: row.scrollWidth > row.clientWidth + 1 ||
                         glass.scrollWidth > glass.clientWidth + 1,
                narrowest: Math.min(...rails.map(t => t.getBoundingClientRect().width)),
                onGlass: rails.every(t => {
                  const r = t.getBoundingClientRect();
                  return r.left >= 0 && r.right <= window.innerWidth + 0.5;
                }),
                counts: document.getElementById('counts').textContent,
                red: [...row.querySelectorAll('.pane-rail.needs-human')]
                       .map(f => f.closest('.tile').dataset.repo),
                column: !!document.getElementById('column'),
              };
            }""")
            assert not errors, errors
            assert out["n"] == 11 and not out["scrolls"], out
            assert out["narrowest"] >= 47.5, "a crushed rail is not a rail"
            assert out["onGlass"], "a rail past the edge of the window is an agent off the glass"
            assert "12 agents" in out["counts"] and "2 need you" in out["counts"], out["counts"]
            assert sorted(out["red"]) == ["r03", "r07"], out
            assert out["column"] is False, "the column went with #233"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_one_checkout_is_one_pane_and_it_fills_the_row(fleet_home, tmp_path):
    """A column with nothing in it was a strip of empty panel down the side of the one thing you
    were reading. One agent is one pane, the whole width of the row, with no rail beside it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-tier="full"]', timeout=10000)

            out = page.evaluate("""() => {
              const tile = document.querySelector('.tile').getBoundingClientRect();
              return {
                column: !!document.getElementById('column'),
                dock: !!document.getElementById('dock'),
                rails: document.querySelectorAll('.tile[data-tier="rail"]').length,
                width: tile.width, page: window.innerWidth,
              };
            }""")
            assert not errors, errors
            assert out["column"] is False, "the column went with #233"
            assert out["dock"] is False, "the dock went with the grid (#232)"
            assert out["rails"] == 0, out
            assert out["width"] > out["page"] * 0.9, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_clicking_a_rail_swaps_it_with_the_open_pane_in_their_own_slots(fleet_home, tmp_path):
    """The swap, and `Esc` back again -- "show me the other one for a second" is the gesture the
    column was for, and the row keeps it (#233): the rail takes the open pane's width and the open
    pane becomes a rail, each where it was in the order. Nothing travels along the row."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            order = "() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)"
            before = page.evaluate(order)

            first = page.evaluate("document.querySelector('.tile.is-solo').dataset.repo")
            second = page.evaluate(RAILS)[0]
            page.click(_rail(second))
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo === '{second}'",
                timeout=5000)
            page.wait_for_selector(f'.tile[data-repo="{second}"][data-tier="full"]', timeout=5000)
            assert second != first

            # The one that was open is a rail now, in its own slot: not gone, and not moved.
            page.wait_for_selector(f'.tile[data-repo="{first}"][data-tier="rail"]', timeout=5000)
            assert page.evaluate(order) == before, "a swap moved something along the row"

            page.keyboard.press("Escape")
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo === '{first}'",
                timeout=5000)
            assert not errors, errors

            # And the server was told, so a reload opens on the same agent. Waited for on the
            # server's record, not the pixels: the page swaps first and writes after (#245).
            _until(lambda: S.desk_state()["windows"]["main"]["open"] == first)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=10000)
            assert page.evaluate("document.querySelector('.tile.is-solo').dataset.repo") == first
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


SOLO = "document.querySelector('.tile.is-solo').dataset.repo"


@pytest.mark.browser
def test_another_window_writing_the_old_zoom_to_the_same_record_does_not_move_the_column(
        fleet_home, tmp_path):
    """#230: every window without `?w=` shares `main`. A grid window's zoom wrote `zoomed` there, and
    the column window re-opened that agent on every frame after -- twice per click.

    The grid is gone (#232), but the shape of the bug is not: a second window on the same record,
    writing a field this window does not own. A tab still running a page from before the update
    sends exactly that -- `zoomed` and the arrangement it thought it was in -- and the server keeps
    none of it, so the click on beta stays on beta."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            other = browser.new_page(viewport={"width": 1280, "height": 900})
            other.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            other.wait_for_selector(".tile.is-solo", timeout=10000)
            answer = other.evaluate("""() => post('window', {
              w: 'main', zoomed: 'gamma', layout: 'grid', view: 'all', screen: 0 })""")
            assert answer["ok"], answer
            page.wait_for_timeout(600)
            record = S.desk_state()["windows"]["main"]
            for gone in ("zoomed", "layout", "view", "screen"):
                assert gone not in record, f"the server kept {gone}: {record}"

            page.click(_rail("beta"))
            page.wait_for_function(f"() => {SOLO} === 'beta'", timeout=5000)
            page.wait_for_timeout(1500)
            assert page.evaluate(SOLO) == "beta"
            _until(lambda: S.desk_state()["windows"]["main"]["open"] == "beta")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_reload_opens_the_agent_that_was_clicked_not_the_one_the_address_named(fleet_home, tmp_path):
    """#230: `openBand` never wrote `#tile=`, so a reload's `followHash` re-opened the agent from
    before the click -- and saved it over the server's record as well."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column#tile=gamma",
                      wait_until="domcontentloaded")
            page.wait_for_function(f"() => document.querySelector('.tile.is-solo') && {SOLO} === 'gamma'",
                                   timeout=10000)
            page.click(_rail("beta"))
            page.wait_for_function(f"() => {SOLO} === 'beta'", timeout=5000)
            assert page.evaluate("location.hash") == "#tile=beta"
            # The page opens beta before the server hears of it, and the write queues behind the
            # window's own (#230). On a slow disk those are not the same moment (#245), and a
            # reload in between would be a different test: this one is about the address.
            _until(lambda: S.desk_state()["windows"]["main"]["open"] == "beta")

            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=10000)
            page.wait_for_timeout(800)
            assert page.evaluate(SOLO) == "beta"
            assert S.desk_state()["windows"]["main"]["open"] == "beta"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_answer_read_before_a_click_cannot_undo_it(fleet_home, tmp_path):
    """#230: `/api/fleet` replaced the desk state outright. An answer the server computed before a
    click, landing after the frame that carried the click, put the old agent back and rolled
    `version` from 5 to 3. Every payload now comes through `acceptDesk`, which drops an older one."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])
    S.update_window("main", open="alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            assert page.evaluate(SOLO) == "alpha"
            # Hold the next `/api/fleet` answer after the server has written it: a stale answer, on
            # purpose, delivered when the test says so. A refresh the stream already had in flight
            # is not one: `refresh()` answers with that one rather than fetching, and nothing would
            # ever be held -- so it is let finish first.
            page.evaluate("""() => {
              const real = window.fetch.bind(window);
              window.fetch = function (url, opts) {
                const p = real(url, opts);
                if (String(url).indexOf('/api/fleet') < 0 || window.__held) return p;
                window.__held = true;
                return p.then(r => new Promise(done => { window.__release = () => done(r); }));
              };
              const ask = () => {
                if (window.__held) return;
                if (pendingRefresh) { pendingRefresh.then(ask, ask); return; }
                refresh();
              };
              ask();
            }""")
            page.wait_for_function("() => !!window.__release", timeout=5000)
            before = page.evaluate("desk.desk.version")

            page.click(_rail("beta"))
            # Until the page holds the frame that carries the click itself -- not only the select's
            # answer, which raises `version` and says nothing about this window.
            page.wait_for_function(
                f"() => {SOLO} === 'beta' && desk.desk.version > {before} && "
                "desk.desk.windows && desk.desk.windows.main.open === 'beta'", timeout=5000)
            after = page.evaluate("desk.desk.version")

            page.evaluate("() => { window.__release(); }")
            page.wait_for_timeout(800)
            assert page.evaluate(SOLO) == "beta", "the stale answer put the old agent back"
            assert page.evaluate("desk.desk.version") >= after, "the stale answer rolled the version back"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_four_opens_in_one_frame_leave_the_record_on_the_last(fleet_home, tmp_path):
    """#230: four window writes in flight at once reached the server in whatever order its threads
    took the lock, and the record -- then the page, from the record -- ended on delta after the
    operator asked for alpha last. Found by `test_fleet_motion.py`'s superseded gestures under load."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            _open(page, port, token)
            page.evaluate("() => { openPane('beta'); openPane('gamma'); openPane('delta'); openPane('alpha'); }")
            page.wait_for_function("() => windowWrites === 0", timeout=10000)
            assert S.desk_state()["windows"]["main"]["open"] == "alpha"
            page.wait_for_timeout(800)
            assert page.evaluate(SOLO) == "alpha"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_pinned_agent_is_open_too_and_the_two_split_the_glass(fleet_home, tmp_path):
    """Pinning already meant *first, always* in the grid. In the column the first thing was the open
    thing, so a pinned agent is one that is always on the glass -- and in the row (#233) that means
    it has a width: the two open panes share what the rails leave, evenly, and it is not a rail."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"], pinned=["gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate(f"""() => {{
              const open = [...document.querySelectorAll('.tile.is-solo')].map(t => t.dataset.repo);
              const widths = [...document.querySelectorAll('.tile.is-solo')]
                .map(t => Math.round(t.getBoundingClientRect().width));
              return {{ open, widths, rails: ({RAILS})() }};
            }}""")
            assert not errors, errors
            assert "gamma" in out["open"], "a pinned agent is always open"
            assert len(out["open"]) == 2, out
            assert abs(out["widths"][0] - out["widths"][1]) <= 2, "pins split the row evenly"
            assert "gamma" not in out["rails"], "and it is not also a rail"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_digits_and_j_k_reach_every_pane_without_a_mouse(fleet_home, tmp_path):
    """A desk that can only be arranged with a mouse cannot be arranged by somebody typing, which is
    the rule every gesture on this page already keeps. `j`/`k` walk the row (#233): the open pane
    itself, then each rail's face -- a real button, so `Enter` swaps it in. The digits count the
    panes on the glass in the row's order, and the number is printed on each one. From `2`: `1` is
    the *one* preset since the gutters (#234), the key the plan gave it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            here = "document.activeElement.closest('.tile').dataset.repo"

            page.keyboard.press("j")
            assert page.evaluate(here) == "alpha", "the first stop is the first pane: the open one"
            page.keyboard.press("j")
            page.keyboard.press("j")
            page.keyboard.press("k")
            assert page.evaluate("document.activeElement.classList.contains('pane-rail')")
            assert page.evaluate(here) == "beta"
            page.keyboard.press("Enter")
            page.wait_for_function(
                "() => document.querySelector('.tile.is-solo').dataset.repo === 'beta'",
                timeout=5000)

            # And a digit opens the Nth pane, which is the number printed on it -- on the rail's
            # face and on the open pane's head alike.
            page.wait_for_selector('.tile[data-repo="gamma"][data-tier="rail"]', timeout=5000)
            assert page.inner_text('.tile[data-repo="gamma"] .pr-n') == "3"
            page.keyboard.press("3")
            page.wait_for_function(
                "() => document.querySelector('.tile.is-solo').dataset.repo === 'gamma'",
                timeout=5000)
            page.wait_for_selector('.tile[data-repo="gamma"][data-tier="full"]', timeout=5000)
            assert page.inner_text('.tile[data-repo="gamma"] .head .n') == "3"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------ what the band said, on the rail (#204, #233)


def test_one_age_formatter_dates_the_agent_everywhere_it_is_dated():
    """The same tile read `6d` in its chip and `160h` in its tab, three centimetres apart: `age()`
    stops at hours and `ageChip()` does not. `age()` still dates DURATIONS -- how long an approval
    has waited, how old a poll is -- and `agentAge` dates the agent, on all four surfaces."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function agentAge(seconds) { return ageChip(seconds).text; }" in js
    assert "age(row.last_event_age_s)" not in js, "the strip is back on the short formatter"
    assert "age(ageOf(row))" not in js, "the rail is back on the short formatter"
    # The surfaces that used to disagree with the chip now call it: the strip's main tab and the
    # agent rail's chip (the dock chip was the third, and went with the grid in #232). The chip and
    # the pane's rail (the band's heir, #233) read `ageChip` straight, because they want the
    # `stale` flag beside the text -- the same formatter either way, which is the point.
    assert js.count("agentAge(") >= 3, js.count("agentAge(")
    assert js.count("ageChip(") >= 3, js.count("ageChip(")


def test_the_fold_says_what_the_agent_last_said(fleet_home, tmp_path):
    """`why` answers *what does this need from me* and is empty of news when the answer is nothing.
    A column of ten idle agents needs the other question answered too."""
    from agentdata.fleet import agentstate

    name = "alpha"
    _repos(tmp_path, name)
    E.append(name, [E.event(name, "assistant_text",
                            {"text": "rebuilt the semantic model and pushed the branch"},
                            ticket="RDSD-1")])
    derived = agentstate.derive(E.read(name))
    assert derived["state"] == "idle"
    assert derived["last_said"] == "rebuilt the semantic model and pushed the branch"


@pytest.mark.browser
def test_every_rail_says_what_its_agent_last_said(fleet_home, tmp_path):
    """The dock could fit a state and an age, which is how an agent that spoke an hour ago and went
    quiet became unreadable from it. The band had the room and used it; a rail is 48px, so what it
    last said is the rail's accessible name and its title (#233) -- read by a screen reader, and by
    anybody who points at it -- with the state and its age beside it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    E.append("beta", [E.event("beta", "assistant_text",
                              {"text": "rebuilt the semantic model and pushed the branch"},
                              ticket="RDSD-1")])
    S.arrange(order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            face = page.locator(_rail("beta"))
            label = face.get_attribute("aria-label") or ""
            assert label.startswith("beta: idle"), label
            assert " ago" in label, "the rail's label carries the age"
            assert "rebuilt the semantic model" in label, label
            assert face.get_attribute("title") == label
            assert "beta" in face.inner_text(), "and the name is on the rail itself"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_rails_node_survives_every_tick_so_the_keyboard_and_the_hover_do(fleet_home, tmp_path):
    """`place()` runs about two and a half times a second while an agent is talking. A row that
    cloned its panes on every pass would take the keyboard off the rail `j` had just reached."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate(f"""() => {{
              const one = document.querySelector('.tile[data-repo="beta"]');
              one.__marker = 'still me';
              one.querySelector('.pane-rail').focus();
              for (let i = 0; i < 20; i++) {{ place(); redrawAll(); }}
              const after = document.querySelector('.tile[data-repo="beta"]');
              return {{
                same: after.__marker === 'still me',
                keyboard: document.activeElement === after.querySelector('.pane-rail'),
                rails: ({RAILS})().length,
              }};
            }}""")
            assert not errors, errors
            assert out["same"], "the pane was torn down and cloned again"
            assert out["keyboard"], "twenty draws took the keyboard off the rail"
            assert out["rails"] == 2, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_hidden_agent_is_counted_in_the_footer_and_a_press_brings_it_back(fleet_home, tmp_path):
    """A pane never simply disappears: hiding one is the operator's own arrangement. It leaves the
    row, and the footer -- where the column's foot used to say it -- reads `1 hidden`. One press on
    that brings them all back (#233)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"], hidden=["gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            page.wait_for_function(
                "() => document.getElementById('hiddencount').textContent === '1 hidden'",
                timeout=5000)
            assert page.locator("#hiddencount").is_visible()
            assert not page.locator('.tile[data-repo="gamma"]').is_visible(), "it left the row"
            assert "gamma" not in page.evaluate(RAILS)
            page.click("#hiddencount")
            page.wait_for_function(f"() => ({RAILS})().indexOf('gamma') >= 0", timeout=5000)
            assert page.inner_text("#hiddencount") == ""
            assert not page.locator("#hiddencount").is_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_agent_that_needs_a_person_keeps_its_slot_and_says_its_ask_in_full(fleet_home, tmp_path):
    """Nothing reorders itself under the operator's hand, so a rail that turns red stays where they
    put it, and the footer counts it. Its question is never cut short: a rail cannot show it, so its
    label says it whole (#233) -- and one press on the red opens the pane where it is answered."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", needs=("gamma",))
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate(f"""() => {{
              const rails = ({RAILS})();
              const red = document.querySelector('#grid .pane-rail.needs-human');
              return {{
                redIsLast: rails[rails.length - 1] === red.closest('.tile').dataset.repo,
                ask: red.getAttribute('aria-label'),
                counts: document.getElementById('counts').textContent,
              }};
            }}""")
            assert not errors, errors
            assert out["redIsLast"], "the red rail moved; nothing reorders itself here"
            assert "which window should this land in?" in out["ask"], out["ask"]
            assert "1 need you" in out["counts"], out["counts"]

            page.click(_rail("gamma"))
            page.wait_for_selector('.tile[data-repo="gamma"][data-tier="full"] .asks:not([hidden])',
                                   timeout=5000)
            assert "which window should this land in?" in \
                page.inner_text('.tile[data-repo="gamma"] .asks')
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# --------------------------------------------- hide, refresh and the model on both (#205)


def test_refresh_is_free_and_refuses_a_second_press_inside_two_seconds(fleet_home, tmp_path):
    """The one button on the tile that is always safe to press: nothing is sent to the agent, so
    nothing is spent. Pressed twice in a breath it refuses, because it re-reads what the tick reads
    and the second press cannot tell the operator anything the first did not."""
    import time as _time

    _repos(tmp_path, "alpha")
    before = E.read("alpha")
    spend_before = [e for e in before if e["kind"] in ("said", "started", "turn_started")]

    answer = S.act("refresh", {"repo": "alpha"})
    assert answer["repo"] == "alpha"
    assert answer["row"]["repo"] == "alpha"
    # Re-folding the stream may ADD to it -- that is the whole job, and it is what the tick does.
    # What it must never do is spend: no turn is started and nothing is typed at the agent.
    after = E.read("alpha")
    spend_after = [e for e in after if e["kind"] in ("said", "started", "turn_started")]
    assert spend_after == spend_before, "refresh must not spawn or speak to an agent"

    with pytest.raises(S.ServeError) as e:
        S.act("refresh", {"repo": "alpha"})
    assert e.value.code == "refresh_busy"

    S._refreshed_at["alpha"] = _time.time() - (S.REFRESH_FLOOR_S + 0.5)
    assert S.act("refresh", {"repo": "alpha"})["repo"] == "alpha"


def test_refresh_refuses_a_repository_that_is_not_registered(fleet_home, tmp_path):
    _repos(tmp_path, "alpha")
    with pytest.raises(S.ServeError) as e:
        S.act("refresh", {"repo": "nope"})
    assert "not a registered repository" in e.value.msg


def test_refresh_is_in_the_vocabulary_an_unknown_action_lists(fleet_home, tmp_path):
    """Every refusal in this server speaks one vocabulary; an action missing from the hint is one
    nobody can discover from the error."""
    _repos(tmp_path, "alpha")
    with pytest.raises(S.ServeError) as e:
        S.act("nonsense", {})
    assert "refresh" in (e.value.hint or "") + e.value.msg


def test_the_tile_row_carries_the_configured_model_and_the_one_that_ran(fleet_home, tmp_path):
    """The settings page has shown both since #199 and the tile showed neither -- its row had no
    model field at all. Same two functions, so a page and a tile cannot disagree."""
    from agentdata import config as C
    from agentdata.fleet import launch as L

    _repos(tmp_path, "alpha")
    E.append("alpha", [E.event("alpha", "assistant_text",
                               {"text": "done", "model": "claude-haiku-4.5"}, ticket="RDSD-1")])
    C.save({"fleet": {"models": {"alpha": {"model": "claude-opus-5", "effort": "high"}}}})

    row = S.row_for("alpha")
    assert row["model"] == "claude-opus-5"
    assert row["effort"] == "high"
    assert row["model_source"] == "fleet.models.alpha"
    # What the tenant actually served, which is the fact the configured value cannot tell you.
    assert row["actual"] == "claude-haiku-4.5"
    assert L.model_for("alpha", C.load())[0] == "claude-opus-5"


def test_the_cli_and_the_page_refresh_through_one_function(fleet_home, tmp_path, capsys):
    """The page is a view of a verb: `ad-fleet refresh` calls what the button calls."""
    from agentdata import cli_fleet

    _repos(tmp_path, "alpha")
    assert cli_fleet.main(["refresh", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "ad-fleet refresh" in out and "alpha" in out


@pytest.mark.browser
def test_the_same_three_controls_are_on_every_pane_and_their_keys_reach_a_rail(fleet_home, tmp_path):
    """The operator's sentence was *active and inactive both* (#205). The band carried hide,
    refresh and the model beside the open tile's; the band is gone (#233), and a compact pane
    carries the same three buttons a full one does, with the same titles. A rail has no room for a
    head, so it keeps the same three KEYS: `h`, `r` and `m` on the rail the keyboard is on."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon")
    # alpha three shares wide, the two pins one each: one full pane and two compact ones at 1000px.
    S.arrange(order=["alpha", "beta", "gamma", "delta", "epsilon"], pinned=["beta", "gamma"],
              size={"alpha": 3})
    S.update_window("main", open="alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1000, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            page.wait_for_selector('.tile[data-repo="beta"][data-tier="compact"]', timeout=5000)

            out = page.evaluate("""() => {
              const read = root => [...root.querySelectorAll('.head [data-tool]')].map(b => ({
                tool: b.dataset.tool, title: b.title,
                tall: Math.round(b.getBoundingClientRect().height),
                wide: Math.round(b.getBoundingClientRect().width),
              }));
              return {
                full: read(document.querySelector('.tile[data-repo="alpha"]')),
                compact: read(document.querySelector('.tile[data-repo="beta"]')),
                tier: document.querySelector('.tile[data-repo="alpha"]').dataset.tier,
              };
            }""")
            assert not errors, errors
            assert out["tier"] == "full", out
            assert [b["tool"] for b in out["full"]] == ["hide", "refresh", "model"], out["full"]
            assert [b["tool"] for b in out["compact"]] == ["hide", "refresh", "model"], out
            for full, compact in zip(out["full"], out["compact"]):
                assert full["title"] == compact["title"], (full, compact)
                assert full["tall"] >= 28 and compact["tall"] >= 28, "the HIG desktop hit-target floor"
                assert compact["wide"] >= 20, "on the glass, not merely in the markup"

            # The rail: the same three, from the keyboard.
            page.focus(_rail("delta"))
            page.keyboard.press("m")
            page.wait_for_selector("#modelcard:not([hidden])", timeout=5000)
            assert page.inner_text("#mc-repo") == "delta"
            page.keyboard.press("Escape")
            page.wait_for_selector("#modelcard[hidden]", state="attached", timeout=5000)

            page.focus(_rail("delta"))
            page.keyboard.press("r")
            deadline = 50
            while "delta" not in S._refreshed_at and deadline:
                page.wait_for_timeout(100)
                deadline -= 1
            assert "delta" in S._refreshed_at, "`r` on a rail re-read nothing"

            page.focus(_rail("delta"))
            page.keyboard.press("h")
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="delta"]')
                           .classList.contains('is-hidden')""", timeout=5000)
            page.wait_for_function(
                "() => document.getElementById('hiddencount').textContent === '1 hidden'",
                timeout=5000)
            # The hide paints before it is written (#219); the record is what outlives the page.
            _until(lambda: S.desk_state()["arrangement"]["hidden"] == ["delta"])
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_model_card_writes_what_the_settings_page_writes_and_refuses_what_it_refuses(
        fleet_home, tmp_path):
    """Two ways to set one thing must not become two rules about it: the card posts the settings
    action, so `fleet.models.<repo>` is written by one function and refused by one function."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata import config as C

    monkey = tmp_path / "cfg.json"
    os.environ["AGENTDATA_CONFIG"] = str(monkey)
    try:
        _repos(tmp_path, "rdsd.pbi", "beta")
        S.arrange(order=["beta", "rdsd.pbi"])

        server, token, port = _serve()
        try:
            with sync_playwright() as p:
                browser = launch_chromium(p)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                _open(page, port, token)

                # From a rail, which is where the band's model button went (#233): `m` on it.
                page.focus(_rail("rdsd.pbi"))
                page.keyboard.press("m")
                page.wait_for_selector("#modelcard:not([hidden])", timeout=5000)
                assert page.inner_text("#mc-repo") == "rdsd.pbi"

                # A value that would become a second argument is refused, in the settings page's
                # own words, and nothing is written.
                page.fill("#mc-model", "x --allow-all-tools")
                page.click("#mc-save")
                page.wait_for_function(
                    "() => /one argument|whitespace|dash/.test("
                    "document.getElementById('mc-note').textContent)", timeout=5000)
                assert C.get_leaf(C.load(), "fleet.models", "rdsd.pbi", {}) == {}

                page.fill("#mc-model", "claude-opus-5")
                page.fill("#mc-effort", "high")
                page.click("#mc-save")
                page.wait_for_function(
                    "() => /saved/.test(document.getElementById('mc-note').textContent)",
                    timeout=5000)
                assert not errors, errors

                # A repo name with a dot in it survives, which is the failure `put_leaf` exists for.
                saved = C.get_leaf(C.load(), "fleet.models", "rdsd.pbi")
                assert saved == {"model": "claude-opus-5", "effort": "high"}
                browser.close()
        finally:
            server.stopping.set()
            server.shutdown()
            server.server_close()
    finally:
        os.environ.pop("AGENTDATA_CONFIG", None)


# ------------------------------------------- the two focuses become open and needs me (#207)


def test_the_two_focuses_have_names_that_say_which_is_which():
    """`focus()` zoomed one tile and `focusMode()` filtered for the ones that need a person: two
    modes named alike, and the toolbar's *back to grid* undid only the first. The zoom went with
    the grid (#232), and `backAgent` and *back to grid* with it. `openAgent` is not `open`, which
    in a non-module script would replace `window.open` for the page -- and the `focus` alias went
    for the same reason once the type check read it (#236): `var focus` *was* `window.focus`, so a
    `window.focus()` from anything on the page shut the drawer and wrote the window's record."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert "function openAgent(name, skipPost) {" in js
    assert "backAgent" not in js and "unfocus" not in js
    assert 'id="unfocus"' not in html and "back to grid" not in html
    # Declarations, not the words in the comment that explains why there are none. A `var` only at
    # the top of the file: one inside a function is that function's, as every `var open` here is.
    for name in ("open", "focus"):
        assert not re.search(rf"(?m)^(\s*function\s+{name}\s*\(|var\s+{name}\b)", js), \
            f"a bare `{name}` declaration replaces window.{name} for the whole page"


@pytest.mark.browser
def test_needs_me_widens_the_red_rather_than_emptying_the_row(fleet_home, tmp_path):
    """Acceptance criterion, ported from the column's folded band (#207, #233) to the *needs me*
    preset that replaced the filter (#234): two red of five are the two wide panes, the three quiet
    ones are rails -- each still named, still 48px, still one press away, dimmed by nothing -- and
    the footer reads `2 need you`. A mode that removed nine panes of ten would be the *where did it
    go* this arrangement exists to answer."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon", needs=("delta", "epsilon"))
    S.arrange(order=["alpha", "beta", "gamma", "delta", "epsilon"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            page.keyboard.press("f")
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile.is-solo')]
                          .map(t => t.dataset.repo).join() === 'delta,epsilon'""", timeout=5000)
            page.wait_for_function(f"() => ({RAILS})().length === 3", timeout=5000)
            out = page.evaluate(f"""() => {{
              const rails = ({RAILS})().map(n => document.querySelector(
                '.tile[data-repo="' + n + '"]'));
              return {{
                n: rails.length,
                repos: rails.map(t => t.dataset.repo),
                dimmed: rails.filter(t => parseFloat(getComputedStyle(t).opacity) < 1)
                             .map(t => t.dataset.repo),
                named: rails.every(t => t.querySelector('.pr-name').textContent.length > 0),
                wide: rails.every(t => Math.round(t.getBoundingClientRect().width) === 48),
                hidden: document.querySelectorAll('#grid .tile.is-hidden').length,
                counts: document.getElementById('counts').textContent,
                backBtn: !!document.getElementById('unfocus'),
              }};
            }}""")
            assert not errors, errors
            assert out["n"] == 3 and out["repos"] == ["alpha", "beta", "gamma"], out
            assert out["hidden"] == 0, "needs me hides nothing"
            assert out["dimmed"] == [], "a quiet rail is not dimmed: it is a rail, which says enough"
            assert out["named"] and out["wide"], "a quiet rail is still a whole rail, named"
            assert "2 need you" in out["counts"], out["counts"]
            assert out["backBtn"] is False, "there is no zoom to go back from"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
