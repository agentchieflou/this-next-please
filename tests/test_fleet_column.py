"""The column: one agent open, every other one a band that shares the page's height (issue #203).

The operator's two sentences, and what each one is asserted by here:

* *non-open sessions show vertically rather than horizontally* -- the bands are one above another in
  a box beside the glass, and the dock is not drawn at all in this arrangement;
* *each slice that isn't being actively looked at should auto size to take up the page so there
  isn't so much negative space* -- the bands SUM to the column's height, measured at three viewport
  heights, which is the one thing a `flex-wrap: wrap` row of chips could never do.

The failure this replaces is in `docs/plan-column.md` §Why this exists: `.workspace` is a flex row,
`.dock` had no flex basis, so a chip carrying a long question was laid out beside the grid and took
a third of the window off the tiles.
"""
from __future__ import annotations
import os
import re
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
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a suite
    that gives every test a fresh fleet directory."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"column": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
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


def _open(page, port, token, extra=""):
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column{extra}",
              wait_until="domcontentloaded")
    page.wait_for_selector(".tile", timeout=10000)
    page.wait_for_function(
        "() => document.querySelectorAll('#bands .band:not([hidden])').length > 0", timeout=10000)


# ----------------------------------------------------------------------------------- the server


def test_the_column_is_the_default_everywhere_it_is_named(fleet_home, tmp_path):
    """The operator's decision, in the three files a test already keeps in step. A default that is
    right in two of them and wrong in the third is a window that opens on a layout nobody chose."""
    from agentdata import cli_fleet

    assert S.LAYOUTS[0] == "column"
    assert cli_fleet.LAYOUTS[0] == "column"
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'var LAYOUTS = ["column", "grid", "roles", "screens"];' in js


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
def test_the_bands_fill_the_column_at_every_viewport_height(fleet_home, tmp_path, height):
    """The acceptance criterion, and the whole reason this arrangement exists: *so there isn't so
    much negative space.* Five agents, one open, four bands -- and the four bands between them
    account for the column's height rather than sitting in a clump at the top of it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon")
    S.arrange("column", order=["alpha", "beta", "gamma", "delta", "epsilon"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": height})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            measured = page.evaluate("""() => {
              const list = document.getElementById('bands');
              const bands = [...list.querySelectorAll('.band:not([hidden])')];
              const box = list.getBoundingClientRect();
              const tile = document.querySelector('.tile.is-solo').getBoundingClientRect();
              const gap = parseFloat(getComputedStyle(list).rowGap || '0') * (bands.length - 1);
              return {
                bands: bands.length,
                sum: bands.reduce((n, b) => n + b.getBoundingClientRect().height, 0) + gap,
                list: box.height,
                tileBottom: tile.bottom,
                page: window.innerHeight,
                shortest: Math.min(...bands.map(b => b.getBoundingClientRect().height)),
              };
            }""")
            assert not errors, errors
            assert measured["bands"] == 4, "one of five is open; the other four are bands"
            # Within a pixel: the bands share the column's whole height.
            assert abs(measured["sum"] - measured["list"]) < 1.5, measured
            assert measured["shortest"] >= 56, "no band is squeezed under its minimum"
            # And the open tile reaches the bottom of the page rather than stopping at 60vh.
            assert measured["tileBottom"] > measured["page"] * 0.75, measured
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_many_agents_make_the_column_scroll_and_the_head_counts_them(fleet_home, tmp_path):
    """Past the minimums the column scrolls rather than crushing every band to nothing, and the
    head says how many there are and how many want a person."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["r%02d" % n for n in range(12)]
    _repos(tmp_path, *names, needs=("r03", "r07"))
    S.arrange("column", order=names)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": 720})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            page.wait_for_function(
                "() => document.querySelectorAll('#bands .band:not([hidden])').length >= 11",
                timeout=10000)

            out = page.evaluate("""() => {
              const list = document.getElementById('bands');
              const bands = [...list.querySelectorAll('.band:not([hidden])')];
              return {
                n: bands.length,
                scrolls: list.scrollHeight > list.clientHeight + 1,
                shortest: Math.min(...bands.map(b => b.getBoundingClientRect().height)),
                head: document.getElementById('column-count').textContent,
                red: document.querySelectorAll('#bands .band.needs-human').length,
                jump: !document.getElementById('column-jump').hidden,
              };
            }""")
            assert not errors, errors
            assert out["n"] == 11 and out["scrolls"], out
            assert out["shortest"] >= 56, "a crushed band is not a band"
            assert "11 others" in out["head"] and "2 need you" in out["head"], out["head"]
            assert out["red"] == 2 and out["jump"] is True, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_one_checkout_draws_no_column_and_its_tile_fills_the_page(fleet_home, tmp_path):
    """A column with nothing in it is a strip of empty panel down the side of the one thing you are
    reading -- the negative space this arrangement was asked to remove, on the other edge."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile", timeout=10000)

            out = page.evaluate("""() => {
              const tile = document.querySelector('.tile').getBoundingClientRect();
              return {
                column: !document.getElementById('column').hidden,
                dock: !document.getElementById('dock').hidden,
                width: tile.width, page: window.innerWidth,
              };
            }""")
            assert not errors, errors
            assert out["column"] is False, "no other agent, so no column"
            assert out["dock"] is False, "the column is the dock here; never both"
            assert out["width"] > out["page"] * 0.9, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_clicking_a_band_opens_it_and_the_tile_that_was_open_takes_its_slot(fleet_home, tmp_path):
    """The swap, and `Esc` back again -- "show me the other one for a second" is the gesture the
    column is for, and it has to be two keystrokes rather than a hunt."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("column", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            first = page.evaluate("document.querySelector('.tile.is-solo').dataset.repo")
            page.click("#bands .band:not([hidden]) .band-open")
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo !== '{first}'",
                timeout=5000)
            second = page.evaluate("document.querySelector('.tile.is-solo').dataset.repo")
            assert second != first

            # The one that was open is a band now, in the column, not gone.
            assert page.evaluate(
                f"[...document.querySelectorAll('#bands .band:not([hidden])')]"
                f".some(b => b.dataset.repo === '{first}')")

            page.keyboard.press("Escape")
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo === '{first}'",
                timeout=5000)
            assert not errors, errors

            # And the server was told, so a reload opens on the same agent.
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=10000)
            assert page.evaluate("document.querySelector('.tile.is-solo').dataset.repo") == first
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_pinned_agent_is_open_too_and_the_two_split_the_glass(fleet_home, tmp_path):
    """Pinning already meant *first, always* in the grid. In the column the first thing is the open
    thing, so a pinned agent is one that is always on the glass -- and two of them share it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("column", order=["alpha", "beta", "gamma"], pinned=["gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate("""() => {
              const open = [...document.querySelectorAll('.tile.is-solo')].map(t => t.dataset.repo);
              const widths = [...document.querySelectorAll('.tile.is-solo')]
                .map(t => Math.round(t.getBoundingClientRect().width));
              const bands = [...document.querySelectorAll('#bands .band:not([hidden])')]
                .map(b => b.dataset.repo);
              return { open, widths, bands };
            }""")
            assert not errors, errors
            assert "gamma" in out["open"], "a pinned agent is always open"
            assert len(out["open"]) == 2, out
            assert abs(out["widths"][0] - out["widths"][1]) <= 2, "pins split the glass evenly"
            assert "gamma" not in out["bands"], "and it is not also a band"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_digits_and_j_k_reach_every_band_without_a_mouse(fleet_home, tmp_path):
    """A desk that can only be arranged with a mouse cannot be arranged by somebody typing, which is
    the rule every gesture on this page already keeps."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta")
    S.arrange("column", order=["alpha", "beta", "gamma", "delta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            page.keyboard.press("j")
            assert page.evaluate("document.activeElement.classList.contains('band-open')")
            page.keyboard.press("j")
            page.keyboard.press("k")
            first_band = page.evaluate(
                "document.activeElement.closest('.band').dataset.repo")
            page.keyboard.press("Enter")
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo === '{first_band}'",
                timeout=5000)

            # And a digit opens the Nth band, which is the number printed on it.
            second = page.evaluate(
                "document.querySelectorAll('#bands .band:not([hidden])')[1].dataset.repo")
            page.keyboard.press("2")
            page.wait_for_function(
                f"() => document.querySelector('.tile.is-solo').dataset.repo === '{second}'",
                timeout=5000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ------------------------------------------------------------------------ the band (#204)


def test_one_age_formatter_dates_the_agent_everywhere_it_is_dated():
    """The same tile read `6d` in its chip and `160h` in its tab, three centimetres apart: `age()`
    stops at hours and `ageChip()` does not. `age()` still dates DURATIONS -- how long an approval
    has waited, how old a poll is -- and `agentAge` dates the agent, on all four surfaces."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function agentAge(seconds) { return ageChip(seconds).text; }" in js
    assert "age(row.last_event_age_s)" not in js, "the strip is back on the short formatter"
    assert "age(ageOf(row))" not in js, "the dock or the rail is back on the short formatter"
    # The three surfaces that used to disagree with the chip now call it: the strip's main tab,
    # the dock chip and the rail chip. The chip and the band read `ageChip` straight, because they
    # want the `stale` flag beside the text -- the same formatter either way, which is the point.
    assert js.count("agentAge(") >= 4, js.count("agentAge(")
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
def test_every_band_says_what_its_agent_last_said_and_the_dock_still_does_not(fleet_home, tmp_path):
    """The dock can fit a state and an age, which is how an agent that spoke an hour ago and went
    quiet became unreadable from it. The band has the room, so it uses it -- and the dock, which is
    answering a different question in the other three arrangements, is left exactly as it was."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    E.append("beta", [E.event("beta", "assistant_text",
                              {"text": "rebuilt the semantic model and pushed the branch"},
                              ticket="RDSD-1")])
    S.arrange("column", order=["alpha", "beta"])
    S.arrange("grid", order=["alpha", "beta"], hidden=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            band = page.inner_text('#bands .band[data-repo="beta"]')
            assert "rebuilt the semantic model" in band, band

            # The same agent, in the grid, is the dock's business and says what it always said.
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector("#dock:not([hidden]) .dock-chip:not([hidden])", timeout=10000)
            chip = page.inner_text("#dock .dock-chip:not([hidden])")
            assert "beta" in chip and "idle" in chip, chip
            assert "rebuilt the semantic model" not in chip, chip
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_bands_node_survives_every_tick_so_the_keyboard_and_the_hover_do(fleet_home, tmp_path):
    """`place()` runs about two and a half times a second while an agent is talking. A column that
    cloned its rows on every pass would take the keyboard off the band `j` had just reached."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("column", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate("""() => {
              const one = document.querySelector('#bands .band[data-repo="beta"]');
              one.__marker = 'still me';
              one.querySelector('.band-open').focus();
              for (let i = 0; i < 20; i++) place();
              const after = document.querySelector('#bands .band[data-repo="beta"]');
              return {
                same: after.__marker === 'still me',
                keyboard: document.activeElement === after.querySelector('.band-open'),
                bands: document.querySelectorAll('#bands .band:not([hidden])').length,
              };
            }""")
            assert not errors, errors
            assert out["same"], "the band was torn down and cloned again"
            assert out["keyboard"], "twenty draws took the keyboard off the band"
            assert out["bands"] == 2, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_hidden_agent_is_counted_at_the_foot_and_show_all_brings_it_back(fleet_home, tmp_path):
    """A band never simply disappears: hiding one is the operator's own arrangement, and the foot
    says how many they have put away. One press brings them all back."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("column", order=["alpha", "beta", "gamma"], hidden=["gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            assert "1 hidden" in page.inner_text("#column-hidden")
            assert page.evaluate(
                "() => !document.querySelector('#bands .band[data-repo=\\\"gamma\\\"]')")
            page.click("#column-showall")
            page.wait_for_function(
                "() => !!document.querySelector('#bands .band[data-repo=\\\"gamma\\\"]')",
                timeout=5000)
            assert page.inner_text("#column-hidden") == ""
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_agent_that_needs_a_person_keeps_its_slot_and_shows_its_ask_in_full(fleet_home, tmp_path):
    """Nothing reorders itself under the operator's hand, so a band that turns red stays where they
    put it -- and the head counts it and jumps to it instead. Its question is never clipped."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", needs=("gamma",))
    S.arrange("column", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate("""() => {
              const bands = [...document.querySelectorAll('#bands .band:not([hidden])')];
              const red = document.querySelector('#bands .band.needs-human');
              const last = red.querySelector('.b-last');
              return {
                order: bands.map(b => b.dataset.repo),
                redIsLast: bands[bands.length - 1] === red,
                ask: last.textContent,
                clipped: last.scrollHeight > last.clientHeight + 1,
                head: document.getElementById('column-count').textContent,
              };
            }""")
            assert not errors, errors
            assert out["redIsLast"], "the red band moved; nothing reorders itself here"
            assert "which window should this land in?" in out["ask"], out["ask"]
            assert not out["clipped"], "an ask the operator cannot read is one they must open a tile for"
            assert "1 need you" in out["head"], out["head"]
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
def test_the_same_three_controls_are_on_the_band_and_on_the_tile(fleet_home, tmp_path):
    """The operator's sentence was *active and inactive both*. One test over both surfaces, because
    a control that exists on one and not the other is exactly what it was asked to stop."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    S.arrange("column", order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)

            out = page.evaluate("""() => {
              const read = root => [...root.querySelectorAll('[data-tool]')].map(b => ({
                tool: b.dataset.tool, title: b.title,
                tall: Math.round(b.getBoundingClientRect().height),
              }));
              return {
                band: read(document.querySelector('#bands .band:not([hidden])')),
                tile: read(document.querySelector('.tile.is-solo .head')),
              };
            }""")
            assert not errors, errors
            assert [b["tool"] for b in out["band"]] == ["hide", "refresh", "model"], out["band"]
            assert [b["tool"] for b in out["tile"]] == ["hide", "refresh", "model"], out["tile"]
            for band, tile in zip(out["band"], out["tile"]):
                assert band["title"] == tile["title"], (band, tile)
                assert band["tall"] >= 28 and tile["tall"] >= 28, "the HIG desktop hit-target floor"
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
        S.arrange("column", order=["beta", "rdsd.pbi"])

        server, token, port = _serve()
        try:
            with sync_playwright() as p:
                browser = launch_chromium(p)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                _open(page, port, token)

                page.click('#bands .band[data-repo="rdsd.pbi"] [data-tool="model"]')
                page.wait_for_selector("#modelcard:not([hidden])", timeout=5000)

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
    modes named alike, and the toolbar's *back to grid* undid only the first. The old names stay
    as aliases, because the page globals the regression tests call keep their names -- and neither
    new name is `open`, which in a non-module script would replace `window.open` for the page."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function openAgent(name, skipPost) {" in js
    assert "function backAgent(skipPost) {" in js
    assert "var focus = openAgent;" in js and "var unfocus = backAgent;" in js
    # A declaration, not the word in the comment that explains why there is not one.
    assert not re.search(r"(?m)^\s*function open\s*\(", js), \
        "a bare `open` declaration replaces window.open for the whole page"


@pytest.mark.browser
def test_needs_me_folds_a_quiet_band_rather_than_emptying_the_column(fleet_home, tmp_path):
    """Acceptance criterion: two red of five leaves five bands in the DOM, two full and three
    folded, and the head reads `2 need you`. A mode that removed nine rows of ten would be the
    *where did it go* this arrangement exists to answer, one level up."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon", needs=("delta", "epsilon"))
    S.arrange("column", order=["alpha", "beta", "gamma", "delta", "epsilon"])

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
                "() => document.body.classList.contains('needs-only')", timeout=5000)
            out = page.evaluate("""() => {
              const bands = [...document.querySelectorAll('#bands .band:not([hidden])')];
              return {
                n: bands.length,
                quiet: bands.filter(b => b.classList.contains('is-quiet')).length,
                slivers: bands.filter(b => b.getBoundingClientRect().height <= 30).length,
                named: bands.every(b => b.querySelector('.b-name').textContent.length > 0),
                head: document.getElementById('column-count').textContent,
                backBtn: !document.getElementById('unfocus').hidden,
              };
            }""")
            assert not errors, errors
            assert out["n"] == 4, "one of five is open; none of the other four leaves"
            assert out["quiet"] == 2 and out["slivers"] == 2, out
            assert out["named"], "a folded band still says who it is"
            assert "2 need you" in out["head"], out["head"]
            assert out["backBtn"] is False, "there is no zoom in the column to go back from"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_back_to_grid_is_drawn_where_a_zoom_exists_and_not_where_it_does_not(fleet_home, tmp_path):
    """The toolbar button undoes the zoom, so it is drawn in the arrangements that have one."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    S.arrange("grid", order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile", timeout=10000)
            assert page.evaluate("() => document.getElementById('unfocus').hidden") is True

            page.click('.tile[data-repo="alpha"] .repo')
            page.wait_for_function(
                "() => document.body.classList.contains('focused')", timeout=5000)
            assert page.evaluate("() => !document.getElementById('unfocus').hidden"), \
                "the grid has a zoom, so it has a way out of one"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
