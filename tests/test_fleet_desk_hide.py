"""Sessions: C — hide and reopen, and never hide what needs you (issue #173).

Five `display:none` rules and one `.remove()` used to take tiles away as side effects of modes --
zoom, focus mode, a solo window, the laptop view, and a repository leaving the registry -- and
nothing said where they went. A tile that is not on the glass has a dock chip now, and a chip is
one click from being back.
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
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
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
    S.arrange("grid", order=["alpha", "beta"], hidden=["beta"])
    assert S.desk_state()["arrangement"]["grid"]["hidden"] == ["beta"]

    # A clean shutdown keeps the desk (#172), so the hidden tile is still hidden next time.
    S.drop_handles()
    S._desk_loaded = False
    S._selection["arrangement"] = {}
    assert S.desk_state()["arrangement"]["grid"]["hidden"] == ["beta"]


def test_a_desk_written_before_this_slice_loads_without_a_hidden_key(fleet_home, tmp_path):
    """`hidden` is additive: an arrangement saved by an older build has none, and must not raise."""
    _repos(tmp_path, "alpha")
    S.arrange("grid", order=["alpha"])
    del S._selection["arrangement"]["grid"]["hidden"]
    S.arrange("grid", hidden=["alpha"])
    assert S.desk_state()["arrangement"]["grid"]["hidden"] == ["alpha"]


# ---------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_a_hidden_tile_is_off_the_glass_and_the_dock_brings_it_back(fleet_home, tmp_path):
    """Acceptance criterion: hide a tile, reload, read it in the dock, reopen it, and read it back
    in its old slot."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            assert page.locator(".tile:visible").count() == 3

            page.locator('.tile[data-repo="beta"] .hidetoggle').click()
            page.wait_for_function(
                """() => document.querySelectorAll('.tile:not(.is-hidden)').length === 2""",
                timeout=5000)
            assert not page.locator('.tile[data-repo="beta"]').is_visible()

            # It is in the dock, saying what it is, and the dock says how many are off the glass.
            dock = page.locator("#dock")
            assert dock.is_visible()
            assert "beta" in dock.inner_text()
            assert "not on the glass" in dock.inner_text()

            # ...and still there after a reload, because the arrangement is the server's.
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.wait_for_function(
                """() => document.querySelectorAll('.tile:not(.is-hidden)').length === 2""",
                timeout=5000)

            # One click puts it back where it was -- between alpha and gamma, not at the end.
            page.locator('#dock .dock-chip:not([hidden]) .dock-open').first.click()
            page.wait_for_function(
                """() => document.querySelectorAll('.tile:not(.is-hidden)').length === 3""",
                timeout=5000)
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
def test_a_hidden_tile_that_needs_a_person_is_on_the_glass_anyway(fleet_home, tmp_path):
    """The one rule the operator's own choice cannot override: hiding a demand is how a demand
    gets missed."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", needs=("beta",))
    S.arrange("grid", order=["alpha", "beta"], hidden=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            beta = page.locator('.tile[data-repo="beta"]')
            assert beta.is_visible(), "it is hidden and it needs somebody, so it is on the glass"
            assert "needs-human" in (beta.get_attribute("class") or "")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_digit_can_no_longer_blank_the_window(fleet_home, tmp_path):
    """Acceptance criterion: pressing a digit for a tile focus mode is hiding no longer leaves an
    empty grid. `1`-`9` read the *visible* order now."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", needs=("alpha",))
    S.arrange("grid", order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            page.keyboard.press("f")          # focus mode: only alpha needs anybody
            page.wait_for_function(
                """() => document.body.classList.contains('needs-only')""", timeout=5000)
            # `2` used to be beta, which focus mode is hiding -- and zooming it hid alpha too.
            page.keyboard.press("2")
            page.wait_for_timeout(300)
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
    S.arrange("grid", order=["alpha", "beta"], hidden=["beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}#tile=beta", wait_until="domcontentloaded")
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
