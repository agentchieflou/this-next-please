"""2026-09-23, /settings in Chromium: the settings page cannot scroll.

Symptom:

    the settings page currently can't be scrolled, so some settings can't be seen
    scrollHeight == innerHeight == 600; a 5000px wheel leaves scrollY at 0; .footnote at y=2124

The desk's row layout was written as a bare `main` selector in app.css, which clamped
and clipped `main.settings` to the viewport height.

Issue: https://github.com/agentchieflou/this-next-please/issues/357
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_settings_page import _own_desk_globals, _repos, _serve, fleet_home  # noqa: F401 - fixtures


@pytest.mark.browser
def test_settings_page_scrolls_at_every_window_size(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for width, height in [(1400, 900), (1280, 720), (900, 600)]:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")

                # wait until #denylist li exists and #cfgrows .setrow count > 5
                page.wait_for_function("() => document.querySelectorAll('#denylist li').length > 0", timeout=15000)
                page.wait_for_function("() => document.querySelectorAll('#cfgrows .setrow').length > 5", timeout=15000)

                # assert document.scrollingElement.scrollHeight > innerHeight
                scroll_height = page.evaluate("() => document.scrollingElement.scrollHeight")
                inner_height = page.evaluate("() => window.innerHeight")
                assert scroll_height > inner_height, f"at {width}x{height}, scrollHeight ({scroll_height}) <= innerHeight ({inner_height})"

                # move mouse to centre, wheel 5000px, wait until .footnote bottom <= innerHeight
                page.mouse.move(width / 2, height / 2)
                page.mouse.wheel(0, 5000)
                page.wait_for_function("() => { const r = document.querySelector('.footnote').getBoundingClientRect(); return r.bottom <= window.innerHeight; }", timeout=10000)

                # scrollTo(0,0)
                page.evaluate("() => window.scrollTo(0, 0)")

                # count focusables in main.settings
                focusables_count = page.evaluate("""() => {
                    const els = Array.from(document.querySelectorAll('main.settings input, main.settings select, main.settings button, main.settings a[href]'));
                    return els.filter(el => el.offsetParent !== null || el.getClientRects().length > 0).length;
                }""")
                assert focusables_count > 0

                # press Tab focusables_count + 2 times, checking activeElement rect
                for _ in range(focusables_count + 2):
                    page.keyboard.press("Tab")
                    page.wait_for_function("""() => {
                        const a = document.activeElement;
                        if (!a || a === document.body) return true;
                        const r = a.getBoundingClientRect();
                        return r.top >= 0 && r.bottom <= window.innerHeight + 1;
                    }""", timeout=5000)

                assert not errors, f"errors at {width}x{height}: {errors}"
                page.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
