"""The tile as a window (issue #217).

The grid had HTML5 drag on the tile's head and one width toggle: one column or two. The browser
drew its own translucent copy of the tile during a drag and the tile itself stayed where it was,
which is the gesture reading as "nothing is happening"; on a trackpad it needed a press-and-hold
nobody discovers; and a tile could be made wider but never taller.

What a window manager does instead is what this file asserts: the thing under the hand moves,
every pointer gesture has a keyboard equivalent, `Esc` leaves the arrangement alone, and a
footprint written by an older build still reads. The edge handles that showed a snap before the
hand came up went with the grid (#232): they snapped to its `auto-fit` tracks. The footprint itself
went with the gutters (#234), which are `tests/test_fleet_gutters.py`: a pane's width is a weight in
its window's record, and `size` is only read, as the starting weight of a window with none.
"""
from __future__ import annotations
import json
import os
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_column import _until
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})


def _repos(tmp_path, *names):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name,
                                                         "model": "claude-haiku-4.5"},
                                ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# --------------------------------------------------------- the footprint, and what it used to be


def test_one_number_reads_as_two_and_two_read_as_themselves():
    assert S.size_cell(2) == {"cols": 2, "rows": 1}
    assert S.size_cell(1) == {"cols": 1, "rows": 1}
    assert S.size_cell({"cols": 3, "rows": 2}) == {"cols": 3, "rows": 2}
    # A preference is not a schema. Anything unreadable is a tile at its default size rather than
    # a dashboard that will not draw.
    assert S.size_cell(None) == {"cols": 1, "rows": 1}
    assert S.size_cell("two") == {"cols": 1, "rows": 1}
    assert S.size_cell({"cols": "x"}) == {"cols": 1, "rows": 1}
    # And it clamps, in both directions.
    assert S.size_cell({"cols": 99, "rows": 99}) == {"cols": S.SIZE_MAX_COLS,
                                                     "rows": S.SIZE_MAX_ROWS}
    assert S.size_cell({"cols": -4, "rows": 0}) == {"cols": 1, "rows": 1}


def test_a_desk_written_before_this_opens_with_its_tiles_the_width_they_were_left(
        fleet_home, tmp_path):
    """The migration, which is the whole of it: an old file is brought forward by being used."""
    _repos(tmp_path, "alpha", "beta")
    S.arrange(order=["alpha", "beta"])
    path = S._desk_file()
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["arrangement"]["size"] = {"alpha": 2}        # what an older build wrote
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle)

    S._desk_loaded = False
    S._selection["arrangement"] = {}
    state = S.desk_state()
    assert state["arrangement"]["size"] == {"alpha": {"cols": 2, "rows": 1}}, \
        "an old size did not come forward"

    # And the file itself is migrated the next time the arrangement changes, not before.
    S.arrange(order=["beta", "alpha"])
    with open(path, encoding="utf-8") as handle:
        again = json.load(handle)
    assert again["arrangement"]["size"] == {"alpha": {"cols": 2, "rows": 1}}


def test_the_api_takes_either_shape(fleet_home, tmp_path):
    _repos(tmp_path, "alpha")
    S.arrange(size={"alpha": 2})
    assert S.desk_state()["arrangement"]["size"] == {"alpha": {"cols": 2, "rows": 1}}
    S.arrange(size={"alpha": {"cols": 3, "rows": 2}})
    assert S.desk_state()["arrangement"]["size"] == {"alpha": {"cols": 3, "rows": 2}}


def test_the_page_reads_the_same_two_numbers_the_server_writes():
    """One arithmetic, on both sides of the wire -- the bug this repository keeps relearning.

    Since the gutters (#234) the page writes no `size` at all; what is left is the reading of one,
    as the starting weight of a window that has no widths yet (plan-panes' migration: `size.cols`
    becomes the weight). Both spellings, clamped to the server's own four columns."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    reader = js[js.index("function legacyShare(name) {"):]
    reader = reader[:reader.index("\n}\n")]
    assert 'typeof v === "object" ? v.cols : v' in reader, "both of #217's spellings"
    assert "Math.min(%d," % S.SIZE_MAX_COLS in reader and "Math.max(1," in reader
    for gone in ("function sizeOf(", "function setTileSize(", "function resizeTile(",
                 "function toggleTileSize(", "var SIZE_MAX_ROWS"):
        assert gone not in js, gone


def test_the_footprint_has_one_owner():
    """`grid-column` was set by a class and then by a custom property. Both at once is the
    two-owners bug the render contract is named after, so there is exactly one rule -- and since
    the row (#233) it is a wide pane's weight, not a span. Since the gutters (#234) the weight is
    `--w`, this window's own width for the pane, and `--cols` and `--rows` went with the span: there
    are no tracks to span and no rows to span down, because a pane is always the row's full
    height."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    assert css.count("grid-column: span") == 0, "a span is back in a row that has no tracks"
    assert "grid-row: span" not in css, "a pane is always the row's full height"
    assert css.count("var(--w, 1)") == 1
    assert ".tile.is-solo { flex: var(--w, 1) 1 0; min-width: var(--compact-from); }" in css
    assert "var(--cols" not in css and "var(--rows" not in css
    assert ".tile.size-2 { grid-column: span 2; }" not in css
    # And the width toggle's button went with it: Alt+Shift+arrows answer that question with more
    # than two answers, and the head was already crowded.
    assert "sizetoggle" not in css
    assert "sizetoggle" not in open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "sizetoggle" not in open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()


def test_the_gestures_are_pointer_events_and_the_handles_are_in_the_markup():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert "function bindDragToReorder(handle, host, name)" in js
    assert "setPointerCapture" in js
    assert 'addEventListener("pointerdown"' in js
    # The head is no longer an HTML5 drag source; tickets and files still are, on the tile.
    assert 'class="head" draggable="true"' not in html
    assert 'e.dataTransfer.setData("application/x-agentdata-tile"' not in js
    assert "maxtoggle" in html
    # The edge handles and their ghost snapped to the grid's `auto-fit` tracks, and went with the
    # grid (#232). What a pane is resized by now is the gutter on its right (#234), a pointer
    # gesture of its own with the capture taken on the press.
    for gone in ("rsz-x", "rsz-y", "rszghost"):
        assert gone not in html, gone
    for gone in ("function bindResizeEdges", "function gridTracks", "function showResizeGhost"):
        assert gone not in js, gone
    assert 'class="gutter" role="separator"' in html
    assert "function bindGutter(gutter, el)" in js


# ----------------------------------------------------------------------------- in a browser


def _drag(page, handle, target, *, steps=8, cancel=False):
    """A real pointer gesture: down on the handle, across in steps, up on the target.

    The gesture is confirmed to have *started* before it is carried across. Playwright dispatches
    a stepped move with no delay between the steps, and on a loaded runner the page can be given
    the whole journey before it has processed the first pixel of it -- which is a drop with no
    drag in front of it, and a reorder that never happens. Windows CI found that; the wait is what
    turns "the page probably kept up" into "the page said it did".
    """
    a = page.locator(handle).bounding_box()
    b = page.locator(target).bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(a["x"] + a["width"] / 2 + 10, a["y"] + a["height"] / 2 + 10, steps=2)
    page.wait_for_function("() => !!dragging", timeout=8000)
    # A quarter of the way in on both axes: before the midpoint, which is what makes the drop land
    # *before* the target -- across for the open tiles, down in the column -- and far enough from
    # the edges to be the target rather than whatever is drawn over its corner. Eight pixels in was
    # the column's own sticky head on Windows, where the scrollbar takes a different width and the
    # first band sits that much higher: `elementFromPoint` answered with the head, `closest`
    # found no repo on it, and nothing ever lit.
    page.mouse.move(b["x"] + b["width"] * 0.25, b["y"] + b["height"] * 0.25, steps=steps)
    if cancel:
        page.keyboard.press("Escape")
    else:
        # And that it found somewhere to land, for the same reason.
        page.wait_for_selector(".drop-before, .drop-after", timeout=8000)
    page.mouse.up()


RAILS = """() => [...document.querySelectorAll(
                   '#grid .tile[data-tier="rail"]:not(.is-hidden):not(.is-grouped)')]
                  .map(t => t.dataset.repo)"""


@pytest.mark.browser
def test_dragging_a_rail_onto_another_reorders_and_escape_leaves_it_alone(fleet_home, tmp_path):
    """Both halves of the acceptance criterion in one gesture each, on the same page. It was a tile
    in the grid, then a band in the column; both went (#232, #233), and a rail is dragged by its
    face -- which is one button, so the press is the rail's -- across the row."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)
            page.wait_for_function(f"() => ({RAILS})().length === 3", timeout=15000)
            assert page.evaluate(RAILS) == ["beta", "gamma", "delta"]

            # Cancelled mid-flight: the order is exactly what it was.
            _drag(page, '.tile[data-repo="delta"] .pane-rail', '.tile[data-repo="beta"]',
                  cancel=True)
            page.wait_for_timeout(500)
            assert page.evaluate(RAILS) == ["beta", "gamma", "delta"], "Esc did not cancel the drag"
            assert page.evaluate("() => document.querySelectorAll('.is-dragging').length") == 0

            # And carried through: delta lands before beta, and the server agrees.
            _drag(page, '.tile[data-repo="delta"] .pane-rail', '.tile[data-repo="beta"]')
            page.wait_for_function(f"() => ({RAILS})()[0] === 'delta'", timeout=15000)
            page.wait_for_timeout(400)
            assert page.evaluate(RAILS) == ["delta", "beta", "gamma"]
            assert page.evaluate("() => document.querySelector('.tile.is-solo').dataset.repo") \
                == "alpha", "a drag is not a press: the open pane is still the open pane"
            # The drop paints before it is written (#219): the record, not the pixels, is waited on.
            _until(lambda: S.desk_state()["arrangement"]["order"]
                   == ["alpha", "delta", "beta", "gamma"])
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    # Every other window agrees, because the arrangement is the fleet's and not the page's.
    assert S.desk_state()["arrangement"]["order"] == ["alpha", "delta", "beta", "gamma"]


@pytest.mark.browser
def test_every_pointer_gesture_has_a_keyboard_equivalent(fleet_home, tmp_path):
    """The rule this desk has kept since #5. Alt+arrows still moves; the resize is the shifted pair,
    because a gesture somebody has learned is not one to take away for a new one. Since the gutters
    (#234) the pair moves the gutter on the pane's right, as a drag of it would: from the open pane
    beside a rail, one step left pulls the rail out to the compact minimum and one step right puts
    it back -- a pair, not a ratchet. Up and down went with `rows`: a pane is always full height.
    Every other gesture's key is `tests/test_fleet_gutters.py`."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)

            tile = page.locator('.tile[data-repo="alpha"]')
            tile.click(position={"x": 6, "y": 60})       # into the tile, not onto a control
            page.evaluate("""() => document.querySelector('.tile[data-repo="alpha"]').focus()""")
            page.keyboard.press("Alt+Shift+ArrowLeft")
            page.wait_for_selector('.tile[data-repo="beta"].is-solo[data-tier="compact"]',
                                   timeout=8000)
            assert round(page.evaluate("""() => document.querySelector('.tile[data-repo="beta"]')
                                                  .getBoundingClientRect().width""")) == 160
            # And back, so the keys are a pair and not a ratchet.
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_selector('.tile[data-repo="beta"][data-tier="rail"]', timeout=8000)
            assert page.evaluate("() => document.querySelectorAll('.tile.is-solo').length") == 1
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            _until(lambda: (S.desk_state()["windows"]["main"].get("widths") or {}).get("beta") == 0)

            # Alt+arrows is still the move it has always been, and the open agent stays open.
            page.keyboard.press("Alt+ArrowRight")
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')]
                          .map(t => t.dataset.repo)[0] === 'beta'""", timeout=8000)
            assert page.evaluate(
                "() => document.querySelector('.tile.is-solo').dataset.repo") == "alpha"
            _until(lambda: S.desk_state()["arrangement"]["order"] == ["beta", "alpha", "gamma"])
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert S.desk_state()["arrangement"]["order"] == ["beta", "alpha", "gamma"]


@pytest.mark.browser
def test_minimise_takes_it_off_the_glass_and_maximise_opens_it(fleet_home, tmp_path):
    """Two gestures the desk already had, under the names everybody already knows. Maximise is
    `openAgent`: on a pinned tile beside the open one, it makes that one the open agent and the
    other goes back to being a rail. Minimise is hide: off the glass, its place kept, and counted
    in the footer (the dock that held it went with the grid, #232, and the column's foot with the
    column, #233)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"], pinned=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="beta"].is-solo', timeout=15000)
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)

            page.locator('.tile[data-repo="beta"] .maxtoggle').click()
            page.wait_for_function(
                """() => !document.querySelector('.tile[data-repo="alpha"]')
                           .classList.contains('is-solo')""", timeout=8000)
            assert page.evaluate("() => openName()") == "beta"
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            assert S.desk_state()["windows"]["main"]["open"] == "beta"

            page.locator('.tile[data-repo="beta"] .hidetoggle').click()
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="beta"]')
                           .classList.contains('is-hidden')""", timeout=8000)
            # It keeps its place: minimise is not "remove", and the footer counts it.
            assert page.evaluate(
                "() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)") \
                == ["beta", "alpha", "gamma"]
            page.wait_for_function(
                "() => document.getElementById('hiddencount').textContent === '1 hidden'",
                timeout=8000)
            _until(lambda: S.desk_state()["arrangement"]["hidden"] == ["beta"])
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert S.desk_state()["arrangement"]["hidden"] == ["beta"]


@pytest.mark.browser
def test_a_draw_in_the_middle_of_a_drag_does_not_put_the_gesture_down(fleet_home, tmp_path):
    """`place()` runs about two and a half times a second while an agent is talking, and a drag
    takes longer than that.

    The column's band (#203) owned three classes and rewrote the attribute that also holds
    `is-dragging` -- and with `is-dragging` goes the `pointer-events: none` that makes
    `elementFromPoint` answer with what is *underneath* the band being dragged. A draw landing
    mid-drag therefore left the gesture hit-testing only itself, and no drop target could ever light
    again. On a fast machine the drag finishes between two draws; it took the slowest runner in CI
    to show it, and two wrong guesses before it was read as the render contract's own rule being
    broken one component over. The band is gone (#233); a rail is a pane, drawn by `drawTile` and
    `drawPaneRail` together, and the same rule is asserted of both.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_function(f"() => ({RAILS})().length >= 3", timeout=15000)

            held = page.evaluate("""() => {
              const rail = document.querySelector('#grid .tile[data-tier="rail"]');
              rail.classList.add('is-dragging');
              // Twenty passes of exactly what the stream does while an agent talks.
              for (let i = 0; i < 20; i++) redrawAll();
              return {
                dragging: rail.classList.contains('is-dragging'),
                events: getComputedStyle(rail).pointerEvents,
              };
            }""")
            assert not errors, errors
            assert held["dragging"], "a draw put the gesture down"
            assert held["events"] == "none", \
                "the rail is hit-testable again, so the drag can only find itself"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_open_pane_drags_by_its_head_along_the_same_row(fleet_home, tmp_path):
    """The column was the same arrangement seen from the other side, so it was the same gesture,
    measured down the page. The row has one side (#233): an open pane is dragged by its head and a
    rail by its face, both across, and both write the one `order`. Here the open pane is carried
    past two rails and lands before the third, still open."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange(order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="full"]', timeout=15000)
            page.wait_for_function(f"() => ({RAILS})().length >= 3", timeout=15000)

            _drag(page, '.tile[data-repo="alpha"] .head .grip', '.tile[data-repo="delta"]')
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')]
                          .map(t => t.dataset.repo).join(',') === 'beta,gamma,alpha,delta'""",
                timeout=15000)
            assert page.evaluate("() => document.querySelector('.tile.is-solo').dataset.repo") \
                == "alpha"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_no_control_in_the_head_is_clipped_however_narrow_the_tile(fleet_home, tmp_path):
    """The head is a title bar with seven things on it and `overflow: hidden` to stop them lying
    over the neighbouring tile. Clipping is the right answer for a *name*; for a button it is a
    control the operator can see the edge of and never press.

    Three open tiles across 1140px is the narrowest the glass draws them: two pinned beside the
    open one, split evenly, which is what the grid's 360px tracks were before it went (#232)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "rdsd-pbi-reporting", "backlog-health", "arl-usage")
    S.arrange(order=["rdsd-pbi-reporting", "backlog-health", "arl-usage"],
              pinned=["rdsd-pbi-reporting", "backlog-health"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1140, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile .head .maxtoggle", timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('.tile.is-solo').length === 3", timeout=15000)
            widest = page.evaluate(
                "() => Math.max(...[...document.querySelectorAll('.tile')]"
                ".map(t => t.getBoundingClientRect().width))")
            assert widest < 420, f"the tiles are not narrow, so this proves nothing: {widest}"

            # Both axes. `overflow: hidden` clips sideways when a control does not fit on the
            # line, and downwards when the whole row wraps past the head's height -- and the
            # second was the one that got through the first version of this assertion.
            clipped = page.evaluate("""() => {
              const bad = [];
              document.querySelectorAll('.tile').forEach(tile => {
                const box = tile.getBoundingClientRect();
                const head = tile.querySelector('.head').getBoundingClientRect();
                tile.querySelectorAll('.head button').forEach(b => {
                  const r = b.getBoundingClientRect();
                  if (r.width < 8 || r.height < 8 ||
                      r.right > box.right + 0.5 || r.left < box.left - 0.5 ||
                      r.bottom > head.bottom + 0.5 || r.top < head.top - 0.5) {
                    bad.push(tile.dataset.repo + ':' + b.className.split(' ')[0]);
                  }
                });
              });
              return bad;
            }""")
            assert not errors, errors
            assert clipped == [], f"clipped out of reach: {clipped}"
            # And the name is not what gives: it is which agent this is.
            names = page.evaluate(
                "() => [...document.querySelectorAll('.tile .head .repo')].map(n => n.textContent)")
            assert "rdsd-pbi-reporting" in names, names
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
