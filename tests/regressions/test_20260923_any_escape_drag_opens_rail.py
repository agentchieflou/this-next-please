"""2026-09-23, the desk in Chromium: a rail's drag put down with `Esc` opened the rail anyway.

Symptom:

    AssertionError: Esc did not cancel the drag
    assert ['alpha', 'beta', 'gamma'] == ['beta', 'gamma', 'delta']

Seen porting the column's drag test to the row (#233), one run in three. The drag took the pointer
capture on lift and gave it back on `Esc`, and the order was left alone -- but the button was still
down, and the release that followed was dispatched to the handle as a `click`. On a rail's face a
click is the swap, so the agent the operator had just put down opened, and the one they were
reading became a rail. (A head's click selects the project instead, which is quieter and just as
unasked for.) A real drag already swallowed its click; a cancelled one now does too.

Issue: https://github.com/agentchieflou/this-next-please/issues/233
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_window import RAILS, _own_desk_globals, _repos, _serve, fleet_home  # noqa: F401 - fixtures


@pytest.mark.browser
def test_a_drag_put_down_with_escape_opens_nothing(fleet_home, tmp_path):
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

            # It failed one run in three, so it is done six times over: lift delta's rail, carry it
            # over beta's, put it down with Esc, and let go.
            face = page.locator('.tile[data-repo="delta"] .pane-rail').bounding_box()
            onto = page.locator('.tile[data-repo="beta"]').bounding_box()
            for attempt in range(6):
                page.mouse.move(face["x"] + face["width"] / 2, face["y"] + face["height"] / 2)
                page.mouse.down()
                page.mouse.move(face["x"] + face["width"] / 2 + 10,
                                face["y"] + face["height"] / 2 + 10, steps=2)
                page.wait_for_function("() => !!dragging", timeout=8000)
                page.mouse.move(onto["x"] + onto["width"] * 0.25,
                                onto["y"] + onto["height"] * 0.25, steps=6)
                page.keyboard.press("Escape")
                page.mouse.up()
                # Put down, the rail glides back to its slot rather than jumping; the next press is
                # made where the rail IS, so it waits for the glide to finish.
                page.wait_for_function(
                    """() => getComputedStyle(document.querySelector('.tile[data-repo="delta"]'))
                               .transform === 'none'""", timeout=5000)
                page.wait_for_timeout(100)
                assert page.evaluate(RAILS) == ["beta", "gamma", "delta"], \
                    f"attempt {attempt + 1}: the drag was put down and the rail opened anyway"
                assert page.evaluate(
                    "() => document.querySelector('.tile.is-solo').dataset.repo") == "alpha"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert S.desk_state()["arrangement"]["order"] == ["alpha", "beta", "gamma", "delta"]
