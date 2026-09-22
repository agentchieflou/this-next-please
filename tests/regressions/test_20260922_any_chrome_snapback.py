"""2026-09-22, the desk in Chrome (`ad-fleet serve --open`): a click on another agent snapped back.

Symptom:

    "When I click on another agent, it automatically snaps back to the one I was previously on."

`applyWindow` runs on every `desk` frame and re-opened `win.zoomed` whenever it differed from
`focused`. The column never sets `focused` and never clears `zoomed`, and the laptop's `desk.json`
still held a zoom from the days the grid was the default -- so within one 0.4 s tick of every click,
the frame carrying `open: beta` also carried `zoomed: alpha`, and the page opened alpha again while
the server said beta. Reproduced headless: alpha -> beta at 0.11 s -> alpha at 0.33 s.

Issue: https://github.com/agentchieflou/this-next-please/issues/230
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_column import _open, _own_desk_globals, _repos, _serve, fleet_home  # noqa: F401 - fixtures
from test_fleet_desk_browser import launch_chromium

SOLO = "document.querySelector('.tile.is-solo').dataset.repo"


@pytest.mark.browser
def test_a_click_on_another_agent_stays_where_it_was_put(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("column", order=["alpha", "beta", "gamma"])
    # What the laptop's desk.json held: alpha open, and a zoom on alpha left by the grid.
    S.update_window("main", open="alpha", zoomed="alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _open(page, port, token)
            assert page.evaluate(SOLO) == "alpha"

            page.click('#bands .band[data-repo="beta"] .band-open')
            page.wait_for_function(f"() => {SOLO} === 'beta'", timeout=5000)
            page.wait_for_timeout(1500)               # three ticks and more: the frames that snapped it back
            assert page.evaluate(SOLO) == "beta", "the click was undone by the next desk frame"
            assert S.desk_state()["windows"]["main"]["open"] == "beta"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
