"""The tile as a window (issue #217).

The grid had HTML5 drag on the tile's head and one width toggle: one column or two. The browser
drew its own translucent copy of the tile during a drag and the tile itself stayed where it was,
which is the gesture reading as "nothing is happening"; on a trackpad it needed a press-and-hold
nobody discovers; and a tile could be made wider but never taller.

What a window manager does instead is what this file asserts: the thing under the hand moves,
what will happen is shown before the hand comes up, every pointer gesture has a keyboard
equivalent, `Esc` leaves the arrangement alone, and a footprint written by an older build still
reads.
"""
from __future__ import annotations
import json
import os
import threading

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
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"column": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "grid": {"order": [], "size": {}, "pinned": [], "hidden": []}},
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
    S.arrange("grid", order=["alpha", "beta"])
    path = S._desk_file()
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data["arrangement"]["grid"]["size"] = {"alpha": 2}        # what an older build wrote
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle)

    S._desk_loaded = False
    S._selection["arrangement"] = {}
    state = S.desk_state()
    assert state["arrangement"]["grid"]["size"] == {"alpha": {"cols": 2, "rows": 1}}, \
        "an old size did not come forward"

    # And the file itself is migrated the next time the arrangement changes, not before.
    S.arrange("grid", order=["beta", "alpha"])
    with open(path, encoding="utf-8") as handle:
        again = json.load(handle)
    assert again["arrangement"]["grid"]["size"] == {"alpha": {"cols": 2, "rows": 1}}


def test_the_api_takes_either_shape(fleet_home, tmp_path):
    _repos(tmp_path, "alpha")
    S.arrange("grid", size={"alpha": 2})
    assert S.desk_state()["arrangement"]["grid"]["size"] == {"alpha": {"cols": 2, "rows": 1}}
    S.arrange("grid", size={"alpha": {"cols": 3, "rows": 2}})
    assert S.desk_state()["arrangement"]["grid"]["size"] == {"alpha": {"cols": 3, "rows": 2}}


def test_the_page_reads_the_same_two_numbers_the_server_writes():
    """One arithmetic, on both sides of the wire -- the bug this repository keeps relearning."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function sizeOf(sizes, name)" in js
    assert "var SIZE_MAX_COLS = 4;" in js and "var SIZE_MAX_ROWS = 3;" in js
    assert "function setTileSize(repo, cols, rows)" in js
    assert "function resizeTile(repo, dCols, dRows)" in js


def test_the_footprint_has_one_owner():
    """`grid-column` was set by a class and is now set by a custom property. Both at once is the
    two-owners bug the render contract is named after, so there is exactly one rule."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    assert css.count("grid-column: span") == 1
    assert "grid-column: span var(--cols, 1)" in css
    assert "grid-row: span var(--rows, 1)" in css
    assert ".tile.size-2 { grid-column: span 2; }" not in css
    # And the width toggle's button went with it: the edge handles and Alt+Shift+arrows answer
    # that question with more than two answers, and the head was already crowded.
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
    for hook in ("rsz-x", "rsz-y", "rszghost", "maxtoggle"):
        assert hook in html, hook


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
    # The target's top-left corner, which is "before it" on both axes -- across in the grid, down
    # in the column. Aiming at the middle means "after it" in whichever direction the list runs.
    page.mouse.move(b["x"] + 8, b["y"] + 8, steps=steps)
    if cancel:
        page.keyboard.press("Escape")
    else:
        # And that it found somewhere to land, for the same reason.
        page.wait_for_selector(".drop-before, .drop-after", timeout=8000)
    page.mouse.up()


@pytest.mark.browser
def test_dragging_a_tile_onto_another_reorders_and_escape_leaves_it_alone(fleet_home, tmp_path):
    """Both halves of the acceptance criterion in one gesture each, on the same page."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="gamma"]', timeout=15000)

            order = lambda: page.evaluate(                                    # noqa: E731
                "() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)")
            assert order() == ["alpha", "beta", "gamma"]

            # Cancelled mid-flight: the order is exactly what it was.
            _drag(page, '.tile[data-repo="gamma"] .grip', '.tile[data-repo="alpha"]', cancel=True)
            page.wait_for_timeout(500)
            assert order() == ["alpha", "beta", "gamma"], "Esc did not cancel the drag"
            assert page.evaluate("() => document.querySelectorAll('.tile.is-dragging').length") == 0

            # And carried through: gamma lands before alpha, and the server agrees.
            _drag(page, '.tile[data-repo="gamma"] .grip', '.tile[data-repo="alpha"]')
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')]
                          .map(t => t.dataset.repo)[0] === 'gamma'""", timeout=15000)
            page.wait_for_timeout(400)
            assert order() == ["gamma", "alpha", "beta"]
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    # Every other window agrees, because the arrangement is the fleet's and not the page's.
    assert S.desk_state()["arrangement"]["grid"]["order"] == ["gamma", "alpha", "beta"]


@pytest.mark.browser
def test_the_edge_shows_the_snap_before_the_hand_comes_up_and_writes_two_numbers(
        fleet_home, tmp_path):
    """HIG *Drag and drop*: show what will happen. The ghost is that sentence, drawn."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"] .rsz-x', timeout=15000)

            grip = page.locator('.tile[data-repo="alpha"] .rsz-x').bounding_box()
            box = page.locator('.tile[data-repo="alpha"]').bounding_box()
            page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
            page.mouse.down()
            # Out to somewhere inside the second track.
            page.mouse.move(box["x"] + box["width"] * 1.7, grip["y"] + grip["height"] / 2,
                            steps=10)
            ghost = page.evaluate("""() => {
              const g = document.getElementById('rszghost');
              return { shown: !g.hidden, says: g.querySelector('.rsz-says').textContent,
                       width: Math.round(g.getBoundingClientRect().width) };
            }""")
            assert ghost["shown"], "nothing said what would happen"
            assert ghost["says"].startswith("2 "), ghost
            assert ghost["width"] > box["width"] * 1.5, ghost

            page.mouse.up()
            page.wait_for_function(
                """() => getComputedStyle(document.querySelector('.tile[data-repo="alpha"]'))
                           .getPropertyValue('--cols').trim() === '2'""", timeout=8000)
            assert page.evaluate("() => document.getElementById('rszghost').hidden") is True
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert S.desk_state()["arrangement"]["grid"]["size"]["alpha"] == {"cols": 2, "rows": 1}


@pytest.mark.browser
def test_every_pointer_gesture_has_a_keyboard_equivalent(fleet_home, tmp_path):
    """The rule this desk has kept since #5, applied to two new gestures. Alt+arrows still moves;
    the resize is the shifted pair, because a gesture somebody has learned is not one to take
    away for a new one."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"]', timeout=15000)

            tile = page.locator('.tile[data-repo="alpha"]')
            tile.click(position={"x": 6, "y": 60})       # into the tile, not onto a control
            page.evaluate("""() => document.querySelector('.tile[data-repo="alpha"]').focus()""")
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_function(
                """() => getComputedStyle(document.querySelector('.tile[data-repo="alpha"]'))
                           .getPropertyValue('--cols').trim() === '2'""", timeout=8000)
            page.keyboard.press("Alt+Shift+ArrowDown")
            page.wait_for_function(
                """() => getComputedStyle(document.querySelector('.tile[data-repo="alpha"]'))
                           .getPropertyValue('--rows').trim() === '2'""", timeout=8000)
            # And back, so the keys are a pair and not a ratchet.
            page.keyboard.press("Alt+Shift+ArrowLeft")
            page.keyboard.press("Alt+Shift+ArrowUp")
            page.wait_for_function(
                """() => {
                  const s = getComputedStyle(document.querySelector('.tile[data-repo="alpha"]'));
                  return s.getPropertyValue('--cols').trim() === '1'
                      && s.getPropertyValue('--rows').trim() === '1';
                }""", timeout=8000)

            # Alt+arrows is still the move it has always been.
            page.keyboard.press("Alt+ArrowRight")
            page.wait_for_function(
                """() => [...document.querySelectorAll('#grid .tile')]
                          .map(t => t.dataset.repo)[0] === 'beta'""", timeout=8000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_minimise_takes_it_off_the_glass_and_maximise_opens_it(fleet_home, tmp_path):
    """Two gestures the desk already had, under the names everybody already knows."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="beta"]', timeout=15000)

            page.locator('.tile[data-repo="beta"] .maxtoggle').click()
            page.wait_for_function(
                "() => document.body.classList.contains('focused')", timeout=8000)
            assert page.evaluate(
                """() => document.querySelector('.tile[data-repo="beta"]')
                           .classList.contains('is-focused')""")

            page.evaluate("() => backAgent()")
            page.wait_for_function(
                "() => !document.body.classList.contains('focused')", timeout=8000)

            page.locator('.tile[data-repo="beta"] .hidetoggle').click()
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="beta"]')
                           .classList.contains('is-hidden')""", timeout=8000)
            # It keeps its place: minimise is not "remove", and the dock is one click back.
            assert page.evaluate(
                "() => [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo)") \
                == ["alpha", "beta", "gamma"]
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert S.desk_state()["arrangement"]["grid"]["hidden"] == ["beta"]


@pytest.mark.browser
def test_a_band_in_the_column_drags_the_same_way(fleet_home, tmp_path):
    """The column is the same arrangement seen from the other side, so it is the same gesture --
    measured down the page rather than across it, because that is the axis the list runs on."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange("column", order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('#bands .band:not([hidden])').length >= 3",
                timeout=15000)

            bands = lambda: page.evaluate(                                    # noqa: E731
                """() => [...document.querySelectorAll('#bands .band:not([hidden])')]
                          .map(b => b.dataset.repo)""")
            was = bands()
            assert len(was) >= 3, was
            _drag(page, f'.band[data-repo="{was[2]}"]', f'.band[data-repo="{was[0]}"]')
            page.wait_for_function(
                """(want) => [...document.querySelectorAll('#bands .band:not([hidden])')]
                              .map(b => b.dataset.repo)[0] === want""",
                arg=was[2], timeout=15000)
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
    control the operator can see the edge of and never press."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "rdsd-pbi-reporting", "backlog-health", "arl-usage")
    S.arrange("grid", order=["rdsd-pbi-reporting", "backlog-health", "arl-usage"])

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
