"""Resizing: gutters, snaps, the three presets, and widths per window (issue #234, slice E of #229).

The operator's sentence (docs/plan-panes.md §Decisions 4): *we don't have the ability to resize the
active or the inactive agents dynamically.* #217's footprint was integer spans, snapped to tracks the
grid measured, and nothing between two panes could be taken hold of. What is asserted here is
plan-panes §Resizing:

* a gutter between every two panes on the glass; dragging it moves width between THOSE two panes and
  every other pane stays exactly where it is -- to the pixel, measured;
* the snaps while dragging: under 120px a pane settles to a 48px rail, the compact minimum is a
  floor, and the full minimum and an even share with the neighbour take the hand within 8px;
* the drag is the preview and nothing else: one write when the hand comes up -- exactly one POST,
  counted -- and `Esc` in the middle puts the widths back with nothing written;
* the footer's undo takes the last change back, in one more write;
* the three presets, `1` one, `=` all and `f` needs me, each one write, and *needs me* hides nothing;
* widths are the window's: two windows hold different widths over the same agents in the same order,
  and a write of widths older than the record is refused rather than put over it;
* a frame of the drag is inside the page's 50ms budget (#219, #220);
* and every one of those gestures again from the keyboard.
"""
from __future__ import annotations
import json
import os
import re
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_column import _until
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")

RAIL_PX = 48
COMPACT_FROM = 160
FULL_FROM = 360
#: The page's own budget for a gesture it can answer out of what it already has (#219).
LOCAL_BUDGET_MS = 50.0


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
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
    monkeypatch.setattr(S, "_refreshed_at", {})


def _repos(tmp_path, names, *, needs=()):
    """Agents that have each said one thing, and -- for `needs` -- asked one question."""
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        events = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                  E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                  E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
        if name in needs:
            events.append(E.event(name, "question_opened",
                                  {"question": "which window should " + name + " land in?",
                                   "id": "q1", "blocking": True}, ticket="RDSD-1"))
        E.append(name, events)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _page(browser, port, token, *, w="", width=1400, height=900, wide=1):
    """A desk page, waited on until it has settled: `wide` panes with a width, every pane with its
    tier, and this window's own first write (`seen`) answered -- so what a test counts afterwards
    is what its gesture caused."""
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    posts = []
    page.on("request", lambda r: posts.append((r.url, r.post_data or ""))
            if r.method == "POST" else None)
    page.goto(f"http://127.0.0.1:{port}/?t={token}" + (f"&w={w}" if w else ""),
              wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile.is-solo[data-tier="full"],'
                  + '#grid .tile.is-solo[data-tier="compact"]').length === {wide}
             && [...document.querySelectorAll('#grid .tile:not(.is-hidden)')]
                  .every(t => !!t.dataset.tier)
             && windowWrites === 0 && !document.body.classList.contains('is-stale')""",
        timeout=15000)
    return page, errors, posts


# Every pane on the glass: where it starts, how wide it is, and whether it is wide or a rail.
READ = """() => [...document.querySelectorAll('#grid .tile:not(.is-hidden):not(.is-grouped)')]
  .map(t => { const r = t.getBoundingClientRect();
              return { repo: t.dataset.repo, left: r.left, width: r.width,
                       wide: t.classList.contains('is-solo'), tier: t.dataset.tier || '' }; })"""


def _read(page):
    return {p["repo"]: p for p in page.evaluate(READ)}


# The row's widths, twice, two frames apart.
_STILL = """() => new Promise(done => {
  const widths = () => [...document.querySelectorAll('#grid .tile')]
    .map(t => t.getBoundingClientRect().width.toFixed(1)).join();
  const first = widths();
  requestAnimationFrame(() => requestAnimationFrame(() => done(first === widths())));
})"""


def _read_settled(page, timeout=10.0):
    """The row as it came to rest after a gesture: nothing travelling, no view transition, and the
    same widths two frames apart. Read the moment a write is answered, a slower runner was still
    drawing the step before -- 45.8px of a 50px drag on Windows 3.14 (#270), and one of five even
    shares 20px wide -- so it is waited for, not assumed. A width that is wrong at rest still fails."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        if page.evaluate(SETTLED) and page.evaluate(_STILL):
            return _read(page)
        assert time.monotonic() < deadline, "the row never came to rest"
        page.wait_for_timeout(50)


def _window_posts(posts):
    return [json.loads(body) for url, body in posts if "/api/window" in url]


def _widths_posts(posts):
    return [b for b in _window_posts(posts) if "widths" in b]


#: Nothing on the row is moving: no view transition over it, and no pane still travelling to where
#: a reorder or a swap put it. A gutter's box read in the middle of either is where the gutter WAS,
#: and a press there lands on whatever has moved in under it.
SETTLED = """() => !inViewTransition &&
  [...document.querySelectorAll('#grid .tile')]
    .every(t => !t.style.transform && t.getAnimations().length === 0)"""


def _gutter_point(page, repo):
    """Where to press the gutter on the right of `repo`: its centre, once the row has stopped
    moving and the page itself says that point is the gutter. A pane put back by FLIP is displaced
    by an inline transform for two frames before its transition even starts, and a busy runner
    makes those frames long."""
    page.wait_for_function(f"""() => {{
      if (!({SETTLED})()) return false;
      const g = document.querySelector('.tile[data-repo="{repo}"] > .gutter');
      if (!g || g.hidden) return false;
      const r = g.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === g;
    }}""", timeout=8000)
    box = page.locator(f'.tile[data-repo="{repo}"] > .gutter').bounding_box()
    assert box, f"no gutter on the right of {repo}"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _drag_gutter(page, repo, dx, *, steps=12, cancel=False):
    """A real pointer gesture on the gutter to the right of `repo`: down, across in steps, up.

    Confirmed held before it is carried across: Playwright gives the page the whole journey at
    once, and a page that had not yet taken the press would see a release with no drag in front of
    it (the lesson of `test_fleet_window._drag`, from Windows CI)."""
    x, y = _gutter_point(page, repo)
    page.mouse.move(x, y)
    page.mouse.down()
    page.wait_for_function("() => !!gutterHeld", timeout=8000)
    page.mouse.move(x + dx, y, steps=steps)
    if cancel:
        page.keyboard.press("Escape")
    page.mouse.up()


def _near(a, b, slack=1.0):
    return abs(a - b) <= slack


def _record(w="main"):
    return (S.desk_state()["windows"].get(w) or {}).get("widths") or {}


def _shares(widths, names):
    """A record's weights as shares of the wide ones, so two records that draw the same row compare
    equal whatever they were scaled by."""
    total = sum(widths.get(n, 0) for n in names) or 1
    return {n: round(widths.get(n, 0) / total, 3) for n in names}


# ------------------------------------------------------------------------- a gutter, dragged


@pytest.mark.browser
def test_a_gutter_drag_moves_width_between_exactly_two_panes_in_one_post(fleet_home, tmp_path):
    """The rule that makes a resize predictable: the two panes beside the gutter trade width, and
    every other pane stays exactly where it is -- its left edge and its width, to the pixel. Thirty
    moves under the hand are one write when it comes up, and nothing else is posted at all."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 1, "delta": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=3)
            before = _read_settled(page)
            posts.clear()
            _drag_gutter(page, "alpha", 90, steps=30)
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            after = _read_settled(page)
            edge = page.evaluate("() => paneEdge()")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _near(after["alpha"]["width"], before["alpha"]["width"] + 90, 1.5), (before, after)
    assert _near(after["beta"]["width"], before["beta"]["width"] - 90, 1.5), (before, after)
    assert _near(after["beta"]["left"], before["beta"]["left"] + 90, 1.5), (before, after)
    for other in ("gamma", "delta"):
        assert _near(after[other]["left"], before[other]["left"]), (other, before, after)
        assert _near(after[other]["width"], before[other]["width"]), (other, before, after)
    # One gesture, one write, and nothing else on the wire: not the pane's click (which selects the
    # project for every window), not an arrangement.
    assert [url for url, _ in sent if "/api/window" not in url] == [], sent
    writes = _widths_posts(sent)
    assert len(writes) == 1 and len(_window_posts(sent)) == 1, sent
    # And the record is what is on the glass: each wide pane's width less its own edges (which
    # `flex-grow` does not share out), as shares of the row.
    want = _shares({n: after[n]["width"] - edge if after[n]["wide"] else 0 for n in names}, names)
    assert _shares(_record(), names) == pytest.approx(want, abs=0.002), (_record(), want)


@pytest.mark.browser
def test_the_snaps_are_the_rail_the_two_minimums_and_an_even_share(fleet_home, tmp_path):
    """plan-panes §Resizing: under 120px a pane settles to a 48px rail, the compact minimum is a
    floor, and the full minimum and an even share with the neighbour take the hand within 8px --
    read off the one function the drag and the keys both go through, and then done by hand: a
    gutter pulled until the pane on its left is under 120px leaves it a rail, and the record says
    so."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            got = page.evaluate("""() => ({
              // Two panes 800px wide between them.
              rail: [60, 110, 119].map(a => snapPair(a, 800)),
              compact: [121, 150, 159, 165, 168, 169].map(a => snapPair(a, 800)),
              full: [351, 352, 355, 365, 368, 369].map(a => snapPair(a, 800)),
              even: [391, 392, 395, 405, 408, 409].map(a => snapPair(a, 800)),
              free: [300, 500, 600].map(a => snapPair(a, 800)),
              // The neighbour keeps the same rules: under 120px it is the rail.
              neighbour: [650, 675, 685, 790].map(a => snapPair(a, 800)),
              // Two rails have nowhere to go, and a pair that cannot hold two compact panes has
              // exactly two states, the nearer of which wins.
              rails: snapPair(70, 96),
              narrow: [100, 135, 155].map(a => snapPair(a, 290)),
            })""")
            before = _read_settled(page)
            posts.clear()
            # Pull alpha down to 100px: it settles to a rail and beta takes the rest.
            _drag_gutter(page, "alpha", 100 - before["alpha"]["width"], steps=20)
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            after = _read_settled(page)
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert got["rail"] == [RAIL_PX] * 3, got
    assert got["compact"] == [COMPACT_FROM] * 5 + [169], got
    assert got["full"] == [351] + [FULL_FROM] * 4 + [369], got
    assert got["even"] == [391] + [400] * 4 + [409], got
    assert got["free"] == [300, 500, 600], got
    assert got["neighbour"] == [640, 640, 752, 752], got
    assert got["rails"] == RAIL_PX, got
    assert got["narrow"] == [RAIL_PX, RAIL_PX, 290 - RAIL_PX], got

    assert round(after["alpha"]["width"]) == RAIL_PX and not after["alpha"]["wide"], after
    assert _near(after["beta"]["width"], before["alpha"]["width"] + before["beta"]["width"] - RAIL_PX,
                 1.5), (before, after)
    assert _near(after["gamma"]["left"], before["gamma"]["left"]), (before, after)
    assert len(_widths_posts(sent)) == 1, sent
    assert _record()["alpha"] == 0 and _record()["beta"] > 0, _record()


@pytest.mark.browser
def test_escape_in_the_middle_of_a_drag_puts_the_widths_back_and_writes_nothing(fleet_home,
                                                                               tmp_path):
    """The hand is the preview, so the preview has to be cancellable: `Esc` with the button still
    down restores every pane's width, posts nothing, and is not the page's own `Esc` (back to the
    last pane) as well."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})
    record = dict(_record())

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            # A pane to go back to, so that an `Esc` that leaked through would show.
            page.evaluate("() => { previousOpen = 'gamma'; }")
            before = _read_settled(page)
            posts.clear()
            x, y = _gutter_point(page, "alpha")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + 150, y, steps=15)
            # The preview is the real layout: alpha is wider under the hand before anything is sent.
            page.wait_for_function(
                f"""() => document.querySelector('.tile[data-repo="alpha"]')
                            .getBoundingClientRect().width > {before['alpha']['width'] + 100}""",
                timeout=8000)
            assert [u for u, _ in posts] == [], "the drag posted before the hand came up"
            # Put down with the hand back over alpha: the release that follows is not a click on
            # alpha either, which would select it for every window.
            page.mouse.move(x - 40, y, steps=4)
            page.keyboard.press("Escape")
            page.mouse.up()
            page.wait_for_function("() => !gutterHeld", timeout=8000)
            after = _read_settled(page)
            # Nothing is waited for to arrive, so give anything that was going to be sent the time.
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            page.wait_for_timeout(300)
            state = page.evaluate("() => ({ open: openName(), hash: location.hash })")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    for name in names:
        assert _near(after[name]["width"], before[name]["width"]), (name, before, after)
        assert _near(after[name]["left"], before[name]["left"]), (name, before, after)
    assert sent == [], f"Esc wrote something: {sent}"
    assert _record() == record
    assert state["open"] == "alpha", "the page's own Esc went back a pane as well"


@pytest.mark.browser
def test_the_footers_undo_takes_a_drag_back_in_one_more_write(fleet_home, tmp_path):
    """One write per gesture, and a way back from it that is not another drag: the footer offers
    the undo the moment the widths change, and pressing it is one more write, of the widths as they
    were."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})
    record = dict(_record())

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            before = _read_settled(page)
            assert not page.locator("#undo").is_visible()
            posts.clear()
            _drag_gutter(page, "alpha", -120)
            page.wait_for_selector("#undo:not([hidden])", timeout=8000)
            said = page.inner_text("#undo")
            _until(lambda: _record() != record)
            page.locator("#undo").click()
            page.wait_for_function(
                f"""() => Math.abs(document.querySelector('.tile[data-repo="alpha"]')
                           .getBoundingClientRect().width - {before['alpha']['width']}) < 1""",
                timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            after = _read_settled(page)
            gone = page.evaluate("() => document.getElementById('undo').hidden")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert "undo" in said and "resize" in said, said
    for name in names:
        assert _near(after[name]["width"], before[name]["width"]), (name, before, after)
    assert gone, "the undo is still offered after it was used"
    assert len(_widths_posts(sent)) == 2, sent
    assert _shares(_record(), names) == pytest.approx(_shares(record, names), abs=0.002)


# ----------------------------------------------------------------------------- the presets


@pytest.mark.browser
def test_each_preset_is_one_write_and_needs_me_hides_nothing(fleet_home, tmp_path):
    """The three presets where the arrangement picker was: *one* (`1`) the pane with the keys wide
    and every other a rail, *all* (`=`) an even share each, *needs me* (`f`) whoever needs a person
    wide and the rest rails -- with the keys moved to one of them, and nothing hidden. Each is one
    write, by its button or its key, and the undo takes it back."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta", "epsilon"]
    _repos(tmp_path, names, needs=("gamma", "epsilon"))
    S.arrange(order=names)
    # A window that has its record already: a fresh one's first write is followed by its first
    # `seen`, which is the page meeting its own record and not the gesture.
    S.update_window("main", open="alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, width=1600)
            page.wait_for_selector('.tile[data-repo="epsilon"].needs-human', timeout=15000)
            seen = {}

            posts.clear()
            page.locator("#preset-all").click()
            page.wait_for_function(
                "() => document.querySelectorAll('#grid .tile.is-solo').length === 5", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            seen["all"] = (_read_settled(page), list(posts))

            posts.clear()
            page.keyboard.press("f")
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile.is-solo')]
                          .map(t => t.dataset.repo).join() === 'gamma,epsilon'""", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            seen["needs"] = (_read_settled(page), list(posts), page.evaluate("() => openName()"),
                             page.evaluate("() => document.querySelectorAll('.tile.is-hidden').length"))

            posts.clear()
            page.keyboard.press("1")
            page.wait_for_function(
                "() => document.querySelectorAll('#grid .tile.is-solo').length === 1", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            seen["one"] = (_read_settled(page), list(posts), page.evaluate("() => openName()"))

            # The keyboard on a rail: `1` makes THAT pane the one.
            posts.clear()
            page.focus('.tile[data-repo="beta"] .pane-rail')
            page.keyboard.press("1")
            page.wait_for_selector('.tile[data-repo="beta"].is-solo', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            seen["one-here"] = (_read_settled(page), list(posts), page.evaluate("() => openName()"))
            _until(lambda: S.desk_state()["windows"]["main"].get("open") == "beta")

            # And back: the undo of a preset is the preset before it.
            posts.clear()
            page.keyboard.press("u")
            page.wait_for_selector('.tile[data-repo="beta"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            seen["undo"] = (_read_settled(page), list(posts), page.evaluate("() => openName()"))
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    panes, sent = seen["all"]
    widths = sorted(round(p["width"]) for p in panes.values())
    assert widths[-1] - widths[0] <= 1, f"all is an even share each: {widths}"
    assert len(_widths_posts(sent)) == 1 and len(sent) == 1, sent

    panes, sent, open_, hidden = seen["needs"]
    assert {n for n, p in panes.items() if p["wide"]} == {"gamma", "epsilon"}, panes
    assert all(round(p["width"]) == RAIL_PX for n, p in panes.items() if not p["wide"]), panes
    assert len(panes) == 5 and hidden == 0, "needs me hides nothing"
    assert open_ in ("gamma", "epsilon"), "the keys go with the width"
    assert len(_widths_posts(sent)) == 1 and len(sent) == 1, sent

    panes, sent, open_ = seen["one"]
    assert [n for n, p in panes.items() if p["wide"]] == [open_], panes
    assert len(_widths_posts(sent)) == 1 and len(sent) == 1, sent

    panes, sent, open_ = seen["one-here"]
    assert [n for n, p in panes.items() if p["wide"]] == ["beta"] and open_ == "beta", panes
    assert len(sent) == 1, sent

    panes, sent, open_ = seen["undo"]
    assert [n for n, p in panes.items() if p["wide"]] == [seen["one"][2]], panes
    assert open_ == seen["one"][2], "the undo gives the keys back too"
    assert len(sent) == 1, sent


@pytest.mark.browser
def test_needs_me_with_nobody_needing_you_says_so_and_writes_nothing(fleet_home, tmp_path):
    """A preset that made every pane a rail would be the blank window the desk exists to stop."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta"]
    _repos(tmp_path, names)
    S.arrange(order=names)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token)
            posts.clear()
            page.keyboard.press("f")
            page.wait_for_function(
                "() => document.getElementById('notice').textContent.indexOf('nothing needs you') >= 0",
                timeout=8000)
            page.wait_for_timeout(300)
            wide = page.evaluate("() => document.querySelectorAll('#grid .tile.is-solo').length")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert wide == 1 and sent == [], sent


# ------------------------------------------------------------------- the window's own widths


@pytest.mark.browser
def test_two_windows_hold_different_widths_over_the_same_order(fleet_home, tmp_path):
    """plan-panes §Where this plan pushes back, item 4: the left monitor holds alpha wide and the
    right one beta, while both show the same agents in the same order. A drag in one leaves the
    other's record alone; a move in either reorders both."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("left", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})
    S.update_window("right", open="gamma", widths={"alpha": 0, "beta": 0, "gamma": 1})
    right_record = dict(_record("right"))

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            left, errors_l, posts_l = _page(browser, port, token, w="left", wide=2)
            right, errors_r, posts_r = _page(browser, port, token, w="right", wide=1)
            wide_l = [n for n, p in _read(left).items() if p["wide"]]
            wide_r = [n for n, p in _read(right).items() if p["wide"]]
            order = lambda page: [t for t in page.evaluate(
                "() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)")]
            same_order = order(left) == order(right) == names

            _drag_gutter(left, "alpha", 60)
            left.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            _until(lambda: _record("left").get("alpha", 0) > _record("left").get("beta", 0))
            # The other window heard the desk change and drew nothing different.
            right.wait_for_function(
                f"() => desk.desk.version >= {S.desk_state()['version']}", timeout=8000)
            wide_r_after = [n for n, p in _read(right).items() if p["wide"]]

            # The order is the desk's: a move in the right window reorders the left one.
            right.focus('.tile[data-repo="gamma"]')
            right.keyboard.press("Alt+ArrowLeft")
            left.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)
                          .join() === 'alpha,gamma,beta'""", timeout=8000)
            wide_l_after = [n for n, p in _read(left).items() if p["wide"]]
            assert not errors_l and not errors_r, (errors_l, errors_r)
            browser.close()
    finally:
        _stop(server)

    assert wide_l == ["alpha", "beta"] and wide_r == ["gamma"], (wide_l, wide_r)
    assert same_order
    assert _record("right") == right_record, "a drag in one window wrote the other's widths"
    assert wide_r_after == ["gamma"]
    assert sorted(wide_l_after) == ["alpha", "beta"], "a move changed a window's widths"


def test_widths_are_the_windows_and_refused_when_they_are_not_weights(fleet_home, tmp_path):
    """The record, server side: `widths` per window, beside `open`, kept across a restart; each
    window's own; and a shape that is not repository-to-weight refused with a code, not repaired."""
    _repos(tmp_path, ["alpha", "beta"])
    S.update_window("left", widths={"alpha": 2, "beta": 0})
    S.update_window("right", widths={"alpha": 0, "beta": 1.5})
    state = S.desk_state()
    assert state["windows"]["left"]["widths"] == {"alpha": 2.0, "beta": 0.0}
    assert state["windows"]["right"]["widths"] == {"alpha": 0.0, "beta": 1.5}
    assert state["windows"]["left"]["widths_at"] < state["windows"]["right"]["widths_at"]
    assert "widths" not in state["arrangement"], "widths are not the shared arrangement's"
    # The answer is a copy: editing it does not edit the desk.
    state["windows"]["left"]["widths"]["alpha"] = 99
    assert S.desk_state()["windows"]["left"]["widths"]["alpha"] == 2.0

    for bad in ([1, 2], "wide", {"alpha": -1}, {"alpha": "2"}, {"alpha": True},
                {"alpha": float("nan")}, {"alpha": float("inf")}):
        with pytest.raises(S.ServeError) as refused:
            S.update_window("left", widths=bad)
        assert refused.value.code == "widths_shape", bad
    assert S.desk_state()["windows"]["left"]["widths"] == {"alpha": 2.0, "beta": 0.0}

    # And a restart brings each window back to its own.
    S.drop_handles()
    S._desk_loaded = False
    S._selection["windows"] = {}
    again = S.desk_state()["windows"]
    assert again["left"]["widths"] == {"alpha": 2.0, "beta": 0.0}
    assert again["right"]["widths"] == {"alpha": 0.0, "beta": 1.5}


def test_a_write_of_widths_older_than_the_record_is_refused(fleet_home, tmp_path):
    """The version check (#234). Two pages can share one window record -- two tabs with no `?w=` --
    and each sends every pane's width, so the one that had not heard the other's gesture would put
    it back unseen. A page sends the version it last heard; widths written after it are newer than
    anything that page knows, and its write is refused with a code the page acts on."""
    _repos(tmp_path, ["alpha", "beta"])
    heard = S.update_window("main", widths={"alpha": 1, "beta": 0})["version"]
    # The same page's next write: it heard its own.
    S.update_window("main", widths={"alpha": 1, "beta": 1}, version=heard)
    # Another page, which heard only the first, is refused -- and nothing in its write lands.
    with pytest.raises(S.ServeError) as refused:
        S.update_window("main", widths={"alpha": 0, "beta": 1}, open="beta", version=heard)
    assert refused.value.code == "widths_stale"
    win = S.desk_state()["windows"]["main"]
    assert win["widths"] == {"alpha": 1.0, "beta": 1.0} and win.get("open", "") != "beta"
    # Other fields are not checked (they are this page's alone), nor is a write with no version --
    # an older page, or a caller that has no desk to have heard.
    S.update_window("main", open="beta", version=0)
    S.update_window("main", widths={"alpha": 2, "beta": 1})
    # Another window's record has its own clock.
    S.update_window("left", widths={"alpha": 1}, version=0)
    # A version that is not a number `int()` can take is no version, never a 500: JSON allows
    # `Infinity`, and `int(float("inf"))` overflows.
    for unreadable in (float("inf"), float("-inf"), 1e400, "1e400", "soon", float("nan")):
        S.update_window("left", widths={"alpha": 2}, version=unreadable)

    # And over the wire, as a 409 carrying the code.
    import urllib.error
    import urllib.request
    server, token, port = _serve()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/window?t={token}",
            data=json.dumps({"w": "main", "widths": {"alpha": 1}, "version": heard}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as http:
            urllib.request.urlopen(req, timeout=10)
        assert http.value.code == 409
        body = json.loads(http.value.read())
        assert body["ok"] is False and body["code"] == "widths_stale", body
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_refused_write_of_widths_puts_the_page_back_and_says_why(fleet_home, tmp_path):
    """The other half of optimistic, for this window's record: the page painted the step, the
    server refused it, and the page puts its widths back, says so in the server's words, and reads
    the desk again so the next gesture starts from what is really there."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            before = _read_settled(page)

            def refuse(route):
                body = json.loads(route.request.post_data or "{}")
                if "widths" not in body:
                    return route.continue_()
                return route.fulfill(status=409, content_type="application/json", body=json.dumps(
                    {"ok": False, "error": "window 'main' was given other widths since this page "
                                           "last heard",
                     "hint": "another page under the same `?w=` moved them",
                     "code": "widths_stale"}))

            page.route("**/api/window*", refuse)
            page.focus('.tile[data-repo="alpha"]')
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_function(
                "() => document.getElementById('notice').textContent.indexOf('other widths') >= 0",
                timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            page.wait_for_function(
                f"""() => Math.abs(document.querySelector('.tile[data-repo="alpha"]')
                           .getBoundingClientRect().width - {before['alpha']['width']}) < 1""",
                timeout=8000)
            undo = not page.evaluate("() => document.getElementById('undo').hidden")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert not undo, "a refused change is not offered back"


# -------------------------------------------------------------------------- the other gestures


@pytest.mark.browser
def test_a_double_click_on_a_gutter_evens_the_two_panes_in_one_write(fleet_home, tmp_path):
    """VS Code's sash does this, and so does the desk: the two panes beside the gutter end even,
    and the two presses that make a double click write nothing of their own -- nor select the
    project, nor open the pane, which is what a click and a double click on a pane mean."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 3, "beta": 1, "gamma": 1})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=3)
            before = _read_settled(page)
            assert before["alpha"]["width"] > before["beta"]["width"] + 100, before
            posts.clear()
            page.locator('.tile[data-repo="alpha"] > .gutter').dblclick()
            page.wait_for_function(
                """() => { const w = n => document.querySelector('.tile[data-repo="' + n + '"]')
                                          .getBoundingClientRect().width;
                           return Math.abs(w('alpha') - w('beta')) < 1; }""", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            page.wait_for_timeout(300)
            after = _read_settled(page)
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _near(after["alpha"]["width"] + after["beta"]["width"],
                 before["alpha"]["width"] + before["beta"]["width"], 1.5)
    assert _near(after["gamma"]["left"], before["gamma"]["left"]), (before, after)
    assert len(sent) == 1 and len(_widths_posts(sent)) == 1, sent


@pytest.mark.browser
def test_shift_click_opens_a_rail_beside_the_open_pane(fleet_home, tmp_path):
    """How two are open without a drag: Shift and a rail, and the rail shares the width of the pane
    that has the keys -- which keeps them. Every other pane stays where it was."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="beta", widths={"alpha": 1, "beta": 1, "gamma": 0, "delta": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            before = _read_settled(page)
            posts.clear()
            page.locator('.tile[data-repo="delta"] .pane-rail').click(modifiers=["Shift"])
            page.wait_for_selector('.tile[data-repo="delta"].is-solo:not([data-tier="rail"])',
                                   timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            after = _read_settled(page)
            open_ = page.evaluate("() => openName()")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert open_ == "beta", "the keys stay on the pane that had them"
    assert _near(after["beta"]["width"], after["delta"]["width"], 1.5), after
    assert _near(after["beta"]["width"] + after["delta"]["width"],
                 before["beta"]["width"] + RAIL_PX, 1.5), (before, after)
    assert _near(after["alpha"]["width"], before["alpha"]["width"]), (before, after)
    assert round(after["gamma"]["width"]) == RAIL_PX
    assert len(sent) == 1 and len(_widths_posts(sent)) == 1, sent


@pytest.mark.browser
def test_a_rail_pressed_takes_the_width_of_the_pane_that_had_the_keys(fleet_home, tmp_path):
    """The column's swap, kept: in a window with widths of its own, the rail pressed takes the width
    of the open pane, which becomes a rail in its own slot -- one write, `open` and the widths
    together, and every other pane where it was."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 2, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            before = _read_settled(page)
            posts.clear()
            page.locator('.tile[data-repo="gamma"] .pane-rail').click()
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            after = _read_settled(page)
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _near(after["gamma"]["width"], before["alpha"]["width"], 1.5), (before, after)
    assert _near(after["beta"]["width"], before["beta"]["width"], 1.5), (before, after)
    windows = _window_posts(sent)
    assert len(windows) == 1 and windows[0]["open"] == "gamma" and "widths" in windows[0], sent
    record = _record()
    assert record["alpha"] == 0 and record["gamma"] > record["beta"] > 0, record
    assert S.desk_state()["windows"]["main"]["open"] == "gamma"


@pytest.mark.browser
def test_every_gesture_again_from_the_keyboard(fleet_home, tmp_path):
    """The rule every gesture on this page keeps. `Alt+Shift+←/→` moves the gutter on the pane's
    right one step; `Alt+Enter` evens it (the double click); `←`/`→` walk the row; `Shift+Enter` on
    a rail opens it beside (the Shift-click); `Enter` swaps it in; `u` takes the last change back.
    A rail stepped wide keeps the keyboard, so the next press still reaches it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0, "delta": 0})
    width = """(n) => document.querySelector('.tile[data-repo="' + n + '"]')
                        .getBoundingClientRect().width"""
    here = "() => document.activeElement.closest('.tile').dataset.repo"

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            start = _read_settled(page)
            posts.clear()

            # The gutter, one step.
            page.focus('.tile[data-repo="alpha"]')
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_function(f"() => Math.abs(({width})('alpha') - "
                                   f"{start['alpha']['width'] + 40}) < 1", timeout=8000)
            step = _read_settled(page)
            # The double click: even.
            page.keyboard.press("Alt+Enter")
            page.wait_for_function(f"() => Math.abs(({width})('alpha') - ({width})('beta')) < 1",
                                   timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            even = _read_settled(page)

            # Along the row, and Shift+Enter on a rail: open beside the pane with the keys.
            page.keyboard.press("ArrowRight")
            assert page.evaluate(here) == "beta"
            page.keyboard.press("ArrowRight")
            assert page.evaluate(here) == "gamma"
            assert page.evaluate("() => document.activeElement.classList.contains('pane-rail')")
            page.keyboard.press("ArrowLeft")
            page.keyboard.press("ArrowRight")
            page.keyboard.press("Shift+Enter")
            page.wait_for_selector('.tile[data-repo="gamma"].is-solo', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            beside = _read_settled(page)
            beside_open = page.evaluate("() => openName()")

            # `u`: back to before the Shift+Enter.
            page.keyboard.press("u")
            page.wait_for_selector('.tile[data-repo="gamma"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            undone = _read_settled(page)

            # Enter on the rail: the swap.
            page.focus('.tile[data-repo="gamma"] .pane-rail')
            page.keyboard.press("Enter")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0 && openName() === 'gamma'",
                                   timeout=8000)

            # A rail stepped wide from its own face, twice: the face goes, the keyboard stays.
            page.focus('.tile[data-repo="alpha"] .pane-rail')
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="compact"]', timeout=8000)
            page.wait_for_function(f"() => Math.abs(({width})('alpha') - {COMPACT_FROM}) < 1",
                                   timeout=8000)
            page.wait_for_function(f"() => ({here})() === 'alpha'", timeout=8000)
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_function(f"() => Math.abs(({width})('alpha') - {COMPACT_FROM + 40}) < 1",
                                   timeout=8000)
            # And back down into a rail in two.
            page.keyboard.press("Alt+Shift+ArrowLeft")
            page.keyboard.press("Alt+Shift+ArrowLeft")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)

            # The presets are keys already (`test_each_preset_is_one_write_and_needs_me_hides_nothing`);
            # `=` once more here, from a pane, to see the keyboard reach it wherever it is.
            page.keyboard.press("=")
            page.wait_for_function(
                "() => document.querySelectorAll('#grid .tile.is-solo').length === 4", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _near(step["beta"]["width"], start["beta"]["width"] - 40, 1.5), (start, step)
    assert _near(step["gamma"]["left"], start["gamma"]["left"]), (start, step)
    assert _near(even["alpha"]["width"], even["beta"]["width"]), even
    assert beside_open == "alpha", "Shift+Enter opens beside the pane with the keys, not in it"
    assert _near(beside["alpha"]["width"], beside["gamma"]["width"], 1.5), beside
    assert _near(beside["beta"]["width"], even["beta"]["width"], 1.5), (even, beside)
    for name in names:
        assert _near(undone[name]["width"], even[name]["width"], 1.5), (name, even, undone)
    # One write per press: step, even, beside, undo, swap, four steps and a preset.
    assert len(_widths_posts(sent)) == 10, [b for b in _window_posts(sent)]


# ------------------------------------------------------------------------------ the budget


@pytest.mark.browser
@pytest.mark.measured
def test_a_frame_of_the_drag_is_inside_the_budget(fleet_home, tmp_path):
    """#219's fifty milliseconds, for the one gesture that runs a frame at a time: each frame of a
    gutter drag writes two panes' widths and nothing else, and is marked (`gutter:frame`); the
    release that writes them once is marked too (`widths:drag`). What is asserted is what the page
    decides -- how long each of those holds the thread -- and not the runner's frame rate, which a
    headless Chromium throttles to whatever it likes (#220). The frame gaps and every long task
    across the drag are printed beside it: a long task there is the browser laying the row out
    under the hand, which is what a drag that IS the preview asks it to do, and on a runner shared
    with three other browsers that is a measure of the sharing. The stream is closed first, so the
    server's heartbeat is not drawn in the middle of the hand's frames."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(6)]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="r00",
                    widths={"r00": 1, "r01": 1, "r02": 1, "r03": 0, "r04": 0, "r05": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, width=1920, height=1080, wide=3)
            page.evaluate("""() => {
              if (source) { source.close(); source = null; }
              performance.clearMeasures();
              window.__long = [];
              window.__stamps = [];
              window.__obs = new PerformanceObserver(list => {
                list.getEntries().forEach(e => window.__long.push(
                  { at: e.startTime, until: e.startTime + e.duration, ms: Math.round(e.duration) }));
              });
              try { window.__obs.observe({ entryTypes: ['longtask'] }); } catch (e) {}
              window.__ticking = true;
              const tick = t => { window.__stamps.push(t); if (window.__ticking) requestAnimationFrame(tick); };
              requestAnimationFrame(tick);
            }""")
            x, y = _gutter_point(page, "r00")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            for dx in (40, 80, 120, 80, 20, -40, -80, -40, 30):
                page.mouse.move(x + dx, y, steps=6)
                page.wait_for_function(
                    "() => !gutterHeld || gutterHeld.frame === 0", timeout=8000)
            page.mouse.up()
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            out = page.evaluate("""() => {
              window.__ticking = false;
              window.__obs.disconnect();
              const gaps = [];
              for (let i = 1; i < window.__stamps.length; i++)
                gaps.push(window.__stamps[i] - window.__stamps[i - 1]);
              const ours = performance.getEntriesByType('measure')
                .filter(m => m.name.indexOf('gutter:frame') === 0 ||
                             m.name.indexOf('widths:drag') === 0);
              return {
                frames: ours.filter(m => m.name.indexOf('gutter:frame') === 0)
                            .map(m => m.duration),
                release: ours.filter(m => m.name.indexOf('widths:drag') === 0)
                             .map(m => m.duration),
                // A long task is the drag's when it runs across one of the drag's own marks.
                blocking: window.__long.filter(t => ours.some(m =>
                  m.startTime < t.until && m.startTime + m.duration > t.at)).map(t => t.ms),
                long: window.__long.map(t => t.ms), gaps: gaps,
              };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    frames = sorted(out["frames"])
    gaps = sorted(out["gaps"])
    if frames and gaps:
        print(f"\ngutter drag: {len(frames)} frames written, worst {frames[-1]:.2f}ms of work, "
              f"release {max(out['release'] or [0]):.2f}ms, median gap "
              f"{gaps[len(gaps) // 2]:.1f}ms, worst gap {gaps[-1]:.1f}ms, long tasks across its "
              f"marks {out['blocking']}ms, every long task {out['long']}ms")
    assert len(frames) >= 3, f"the drag painted almost nothing: {out}"
    assert frames[-1] < LOCAL_BUDGET_MS, f"a frame of the drag took {frames[-1]:.1f}ms"
    assert len(out["release"]) == 1 and out["release"][0] < LOCAL_BUDGET_MS, out["release"]


# -------------------------------------------------------------------------- reduced motion


@pytest.mark.browser
def test_under_reduced_motion_a_preset_applies_at_once_and_the_drag_is_unchanged(fleet_home,
                                                                                 tmp_path):
    """plan-panes §Resizing: under `prefers-reduced-motion` the swap and the presets apply at once
    -- the widths are what they will be before the gesture's own task has ended -- and the gutter
    drag is exactly what it was, because it was never an animation."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            page.emulate_media(reduced_motion="reduce")
            at_once = page.evaluate("""() => {
              applyPreset('all');
              const tilesNow = [...document.querySelectorAll('#grid .tile')];
              return {
                wide: document.querySelectorAll('#grid .tile.is-solo').length,
                transition: inViewTransition,
                travelling: tilesNow.filter(t => t.style.transform || t.classList.contains('flip'))
                                    .length,
              };
            }""")
            # The stylesheet's reduced-motion block gives every element a 0.01ms transition, so a
            # width is drawn a frame later rather than inside the gesture's own task: at once, with
            # nothing travelling and no view transition in between.
            page.wait_for_function(
                """() => { const w = [...document.querySelectorAll('#grid .tile')]
                                   .map(t => t.getBoundingClientRect().width);
                           return Math.max(...w) - Math.min(...w) < 1; }""", timeout=5000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            before = _read_settled(page)
            _drag_gutter(page, "alpha", 50)
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            after = _read_settled(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert at_once["wide"] == 3 and at_once["transition"] is False, at_once
    assert at_once["travelling"] == 0, "a preset under reduced motion travelled"
    assert _near(after["alpha"]["width"], before["alpha"]["width"] + 50, 1.5), (before, after)
    assert _near(after["gamma"]["left"], before["gamma"]["left"]), (before, after)


# --------------------------------------------------------------------- ownership, and the old


@pytest.mark.browser
def test_an_idle_desk_with_widths_of_its_own_makes_no_mutation(fleet_home, tmp_path):
    """The render contract over the whole document, for a window with widths: `paintWidths` and the
    gutters are written from the record on every pass, so a pass with nothing new must touch
    nothing -- the same arithmetic on the page and in what it wrote is what makes that true."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta"]
    _repos(tmp_path, names, needs=("delta",))
    S.arrange(order=names)
    S.update_window("main", open="alpha",
                    widths={"alpha": 1.3, "beta": 0.7, "gamma": 1, "delta": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=3)
            page.wait_for_selector('#grid .tile.needs-human[data-tier="rail"]', timeout=15000)
            count = page.evaluate("""async () => {
              // Idle means the same answer: a live `/api/fleet` carries ages that are MEANT to
              // move a chip once a second, so the answer is replayed byte for byte (as
              // `test_fleet_panes` does for the whole document).
              const real = window.fetch.bind(window);
              const body = await (await real(q('/api/fleet'))).text();
              window.fetch = function (url, opts) {
                if (String(url).indexOf('/api/fleet') >= 0) {
                  return Promise.resolve(new Response(body, {
                    status: 200, headers: { 'Content-Type': 'application/json' } }));
                }
                return real(url, opts);
              };
              const frame = () => new Promise(done => requestAnimationFrame(() => done()));
              await refresh(); place(); redrawAll(); await frame(); await frame();
              let n = 0;
              const seen = [];
              const obs = new MutationObserver(records => {
                n += records.length;
                records.slice(0, 5).forEach(r => seen.push(r.type + ' ' + (r.attributeName || '') +
                                                          ' ' + (r.target.className || r.target.nodeName)));
              });
              obs.observe(document.getElementById('grid'), { subtree: true, childList: true,
                                                              attributes: true, characterData: true });
              for (let i = 0; i < 6; i++) { await refresh(); place(); redrawAll(); await frame(); }
              obs.takeRecords().forEach(() => { n += 1; });
              obs.disconnect();
              return { n: n, seen: seen };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle desk wrote to the row: {count}"


@pytest.mark.browser
def test_a_reload_draws_the_widths_it_left_and_writes_none(fleet_home, tmp_path):
    """The open pane dragged down to a rail stays one through a reload. The reload answers the
    address's `#tile=`, which names the open pane, and opening the pane that already has the keys
    must not be a swap with itself -- it widened the rail the hand had just made. A press on that
    rail is the hand asking, and does widen it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            # Opened by the hand, as the operator would have: the address now names it.
            page.locator('.tile[data-repo="alpha"] .head .repo').click()
            page.wait_for_function("() => location.hash === '#tile=alpha' && windowWrites === 0",
                                   timeout=8000)
            before = _read_settled(page)
            assert before["alpha"]["wide"] and before["beta"]["wide"], "opening it swapped it"
            _drag_gutter(page, "alpha", RAIL_PX + 10 - before["alpha"]["width"], steps=16)
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            _until(lambda: _record().get("alpha") == 0)
            assert page.evaluate("() => location.hash") == "#tile=alpha"
            record = dict(_record())

            posts.clear()
            page.reload(wait_until="domcontentloaded")
            page.wait_for_function(
                """() => !document.body.classList.contains('is-stale') && windowWrites === 0
                         && desk.desk.version !== undefined""", timeout=15000)
            # The anchor is answered after the desk loads; give it that turn, then read.
            page.wait_for_function("() => pendingDesk === null", timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            after = _read_settled(page)
            reloaded = list(posts)
            assert not after["alpha"]["wide"] and after["beta"]["wide"], \
                f"the reload widened the rail the hand had made: {after}"

            posts.clear()
            page.locator('.tile[data-repo="alpha"] .pane-rail').click()
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo:not([data-tier="rail"])',
                                   timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            pressed = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert _widths_posts(reloaded) == [], f"a reload wrote widths: {reloaded}"
    assert len(_widths_posts(pressed)) == 1, pressed
    assert _record()["alpha"] > 0 and record["alpha"] == 0


@pytest.mark.browser
def test_a_desk_an_older_build_wrote_still_draws_its_widths(fleet_home, tmp_path):
    """Data compatibility: a desk.json with #217's `size` and no widths anywhere loads, and a window
    that has never been given widths draws the open pane and the pins wide as before the gutters --
    at the `size.cols` it was left with, which plan-panes' migration makes its weight. Nothing is
    written to make that so."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names, pinned=["beta"], size={"alpha": {"cols": 2, "rows": 3}})
    S.update_window("main", open="alpha")
    path = S._desk_file()
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["arrangement"]["size"] = {"alpha": 2}               # the oldest spelling there was
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle)
    S._desk_loaded = False
    S._selection["arrangement"] = {}

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=2)
            panes = _read_settled(page)
            edge = page.evaluate("() => paneEdge()")
            mine = page.evaluate("() => myWidths")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert mine is None, "a window with no widths has none until a gesture gives it some"
    assert panes["alpha"]["wide"] and panes["beta"]["wide"] and not panes["gamma"]["wide"]
    ratio = (panes["alpha"]["width"] - edge) / (panes["beta"]["width"] - edge)
    assert abs(ratio - 2) < 0.02, ratio
    assert "widths" not in (S.desk_state()["windows"]["main"])


# ------------------------------------------------------------------------------- the source


def test_a_drag_draws_nothing_but_widths():
    """plan-panes ground rule 4, read off the source: while a gutter is held `place()` waits, the
    frame writes two panes' widths and marks itself, and one function writes a pane's width at
    rest."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    place = js[js.index("function place() {"):]
    place = place[:place.index("\n}\n")]
    assert "if (gutterHeld) { placeWanted = true; return; }" in place.split("\n")[1], \
        "the first thing place() does is wait for the hand"
    frame = js[js.index("function paintHeld() {"):]
    frame = frame[:frame.index("\n}\n")]
    for never in ("place(", "drawTile(", "reorderDomTiles(", "redrawAll(", "post("):
        assert never not in frame, f"a frame of the drag calls {never}"
    assert frame.count("paintHeldWidth(") == 3
    # One writer of a pane's width at rest, one while it is held, and one rule that reads it.
    assert js.count('style(entry.el, "--w"') == 1
    assert js.count('style(el, "--w"') == 1
    assert js.count('toggle(entry.el, "is-solo"') == 1
    assert ".tile.is-solo { flex: var(--w, 1) 1 0; min-width: var(--compact-from); }" in css
    # Pointer capture, on the gutter, and every gutter in the markup of the one pane template.
    gutter = js[js.index("function bindGutter(gutter, el) {"):]
    assert "gutter.setPointerCapture(e.pointerId)" in gutter[:gutter.index("\n}\n")]
    assert html.count('class="gutter"') == 1
    assert '.tile[data-tier="rail"] > :not(.pane-rail):not(.gutter)' in css


def test_the_span_resize_is_gone_and_its_marks_with_it():
    """#217's `size` was a span in a grid that no longer exists; the gutters replace it (#234). What
    stays is the reading of an old `size` as a starting weight, never a write of one."""
    # What the code does, not what its comments say it used to do.
    strip = lambda text: re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
    js = strip(open(os.path.join(STATIC, "app.js"), encoding="utf-8").read())
    css = strip(open(os.path.join(STATIC, "app.css"), encoding="utf-8").read())
    html = re.sub(r"<!--.*?-->", " ", open(os.path.join(STATIC, "index.html"),
                                            encoding="utf-8").read(), flags=re.S)
    for gone in ("function setTileSize(", "function toggleTileSize(", "function resizeTile(",
                 "function sizeOf(", "SIZE_MAX_COLS", '"size")', "size: sizes", "--cols",
                 "--rows", "size-2"):
        assert gone not in js, gone
    for gone in ("--cols", "--rows", "size-2", "rsz-x", "rsz-y", "rszghost"):
        assert gone not in css, gone
        assert gone not in html, gone
    assert "function legacyShare(name)" in js
    assert "Alt</kbd>+<kbd>Shift</kbd>+<kbd>↑" not in html, "a pane has no height to change"
