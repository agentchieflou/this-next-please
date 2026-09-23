"""Sessions: C — hide and reopen, and never hide what needs you (issue #173).

Five `display:none` rules and one `.remove()` used to take tiles away as side effects of modes --
zoom, focus mode, a solo window, the laptop view, and a repository leaving the registry -- and
nothing said where they went. #173 gave each one a chip in a dock under the grid. The grid and its
dock went in #232, and the column answers the same question: a hidden agent is counted at its foot
with *show all* beside the count, a departed one is a band naming what restores it, and an agent
that needs a person is a red band whatever the arrangement says.
"""
from __future__ import annotations
import os
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
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


def _repos(tmp_path, *names, needs=()):
    for name in names:
        path = make_project(tmp_path / name, ticket="RDSD-1")
        Registry().add(path, name=name)
        events = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                  E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
        if name in needs:
            events.append(E.event(name, "question_opened",
                                  {"question": "which window?", "id": "q1", "blocking": True},
                                  ticket="RDSD-1"))
        E.append(name, events)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# --------------------------------------------------------------------------------- the server


def test_hidden_is_part_of_the_arrangement_and_survives_a_restart(fleet_home, tmp_path):
    _repos(tmp_path, "alpha", "beta")
    S.arrange(order=["alpha", "beta"], hidden=["beta"])
    assert S.desk_state()["arrangement"]["hidden"] == ["beta"]

    # A clean shutdown keeps the desk (#172), so the hidden tile is still hidden next time.
    S.drop_handles()
    S._desk_loaded = False
    S._selection["arrangement"] = {}
    assert S.desk_state()["arrangement"]["hidden"] == ["beta"]


def test_a_desk_written_before_this_slice_loads_without_a_hidden_key(fleet_home, tmp_path):
    """`hidden` is additive: an arrangement saved by an older build has none, and must not raise."""
    _repos(tmp_path, "alpha")
    S.arrange(order=["alpha"])
    del S._selection["arrangement"]["hidden"]
    S.arrange(hidden=["alpha"])
    assert S.desk_state()["arrangement"]["hidden"] == ["alpha"]


# ---------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_a_hidden_agent_is_off_the_glass_and_show_all_brings_it_back_to_its_slot(fleet_home,
                                                                                 tmp_path):
    """Acceptance criterion: hide an agent, reload, read that it is put away, bring it back, and
    read it back in its old slot. It was the dock's chip; it is the column's foot now (#232)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"])
    bands = """() => [...document.querySelectorAll('#bands .band:not([hidden])')]
                      .map(b => b.dataset.repo).join(',')"""

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.wait_for_function(f"() => ({bands})() === 'beta,gamma'", timeout=5000)

            page.locator('#bands .band[data-repo="beta"] [data-tool="hide"]').click()
            page.wait_for_function(f"() => ({bands})() === 'gamma'", timeout=5000)
            assert page.locator('.tile[data-repo="beta"]').evaluate(
                "t => t.classList.contains('is-hidden')")
            # The foot says how many are put away, and offers them back.
            assert page.inner_text("#column-hidden") == "1 hidden"
            assert page.locator("#column-showall").is_visible()

            # ...and still there after a reload, because the arrangement is the server's.
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.wait_for_function(
                "() => document.getElementById('column-hidden').textContent === '1 hidden'",
                timeout=5000)

            # One click puts it back where it was -- between alpha and gamma, not at the end.
            page.click("#column-showall")
            page.wait_for_function(f"() => ({bands})() === 'beta,gamma'", timeout=5000)
            order = page.eval_on_selector_all(
                "#grid .tile:not(.is-hidden)", "els => els.map(e => e.dataset.repo)")
            assert order == ["alpha", "beta", "gamma"], "it kept its slot, it did not go to the end"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_hidden_agent_that_needs_a_person_is_on_the_glass_anyway(fleet_home, tmp_path):
    """The one rule the operator's own choice cannot override: hiding a demand is how a demand
    gets missed. On the glass means its band is drawn, red, while another agent is open."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", needs=("beta",))
    S.arrange(order=["alpha", "beta"], hidden=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)

            beta = page.locator('#bands .band[data-repo="beta"]')
            beta.wait_for(state="visible", timeout=5000)
            assert beta.is_visible(), "it is hidden and it needs somebody, so it is on the glass"
            assert "needs-human" in (beta.get_attribute("class") or "")
            assert page.inner_text("#column-hidden") == "", "it is not counted as put away"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_digit_can_no_longer_blank_the_window(fleet_home, tmp_path):
    """Acceptance criterion: pressing a digit for an agent focus mode is quieting no longer leaves an
    empty window. It used to zoom that tile, which hid every other one while the mode hid that
    one. The zoom went with the grid (#232); a digit opens the band printed with it, and a quiet
    band is folded, never gone, so what it opens is on the glass."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", needs=("alpha",))
    S.arrange(order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)

            page.keyboard.press("f")          # focus mode: only alpha needs anybody
            page.wait_for_function(
                """() => document.body.classList.contains('needs-only')""", timeout=5000)
            # `1` is beta's band, which focus mode has folded to a sliver.
            page.keyboard.press("1")
            # Wait for the open to have happened rather than for a clock: it goes through a view
            # transition (#216) and applies on the frame after the browser has taken its "before"
            # snapshot, which on a loaded machine is past any fixed sleep.
            page.wait_for_selector('.tile[data-repo="beta"].is-solo', timeout=8000)
            assert page.locator(".tile:visible").count() >= 1, "the window is not blank"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_anchor_reopens_a_hidden_tile_and_names_one_that_does_not_exist(fleet_home, tmp_path):
    """Acceptance criterion: `#tile=` reopens a hidden tile and says so; for an unregistered name
    the footer says so. Neither is silent -- a toast for a tile that is not there used to do
    nothing at all."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    S.arrange(order=["alpha", "beta"], hidden=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid#tile=beta", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.wait_for_function(
                """() => /reopened/.test(document.getElementById('notice').textContent)""",
                timeout=5000)
            # Reopening is a round trip: the arrangement is the server's, so the tile comes back
            # when the answer does rather than the instant the footer says so.
            page.locator('.tile[data-repo="beta"]').wait_for(state="visible", timeout=5000)

            page.evaluate("() => { location.hash = '#tile=nowhere'; }")
            page.wait_for_function(
                """() => /no tile for/.test(document.getElementById('notice').textContent)""",
                timeout=5000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_repository_that_leaves_the_registry_keeps_a_band_naming_what_restores_it(
        fleet_home, tmp_path):
    """Acceptance criterion: removing a repository while the page is open used to make a tile --
    and a transcript -- disappear with nothing said. It leaves a band, and the band names the
    command. (It was a dock chip until the dock went with the grid, #232.)"""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")
    S.arrange(order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"].is-solo', timeout=15000)
            assert page.locator('#bands .band[data-repo="beta"]').is_visible()

            Registry().remove("beta")
            # The registry is not an agent event, so nothing is pushed: the page notices on the
            # desk's own fifteen-second clock, and the wait is generous enough to cross one.
            page.wait_for_function(
                """() => document.querySelectorAll('#bands .band:not([hidden]).departed').length === 1""",
                timeout=30000)
            band = page.locator("#bands .band.departed").first
            assert "beta" in band.inner_text()
            assert "removed from the registry" in band.inner_text()
            assert "repo add" in (band.locator(".band-open").get_attribute("title") or "")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_alt_arrow_steps_over_a_hidden_tile_rather_than_swapping_with_it(fleet_home, tmp_path):
    """A hidden tile keeps its slot in `order`, so a move that steps one index swapped the tile
    with something nobody can see and read as the key having done nothing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange(order=["alpha", "beta", "gamma"], hidden=["beta"])
    # Gamma is the one open, so its head and its keys are on the glass.
    S.update_window("main", open="gamma")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="gamma"].is-solo', timeout=15000)
            page.wait_for_function(
                """() => document.querySelectorAll('.tile:not(.is-hidden)').length === 2""",
                timeout=5000)

            # The Alt+arrow listener is the tile's, so the keyboard has to be somewhere inside it.
            page.locator('.tile[data-repo="gamma"] .hidetoggle').focus()
            page.keyboard.press("Alt+ArrowLeft")
            page.wait_for_function(
                """() => { var v = [].slice.call(document.querySelectorAll('#grid .tile:not(.is-hidden)'));
                           return v.map(function (e) { return e.dataset.repo; }).join(',') === 'gamma,alpha'; }""",
                timeout=5000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
