"""2026-09-23, found building the panes (#233): the tab never said how many agents need you.

Symptom (the page's own console, on every refresh):

    TypeError: el.getAttribute is not a function
        at attr (common.js)
        at title (app.js)
        at refresh (app.js)

`title()` wrote the tab's title with `attr(document, "title", ...)` since the render contract
(#215) made every write go through `attr`. `document` is not an element, so the call threw: the tab
never read "(2) fleet", and every `refresh()` ended in its own `catch` -- after the desk had
drawn, which is why nothing on the page looked wrong.

Issue: https://github.com/agentchieflou/this-next-please/issues/262
"""
from __future__ import annotations

import pytest

from desk_harness import close_pages
from test_fleet_column import _repos, _serve, fleet_home  # noqa: F401 - fixtures


@pytest.mark.browser
def test_the_tab_says_how_many_agents_need_you_and_refresh_resolves(fleet_home, tmp_path, desk_browser):
    _repos(tmp_path, "alpha", "beta", "gamma", needs=("beta",))
    server, token, port = _serve()
    try:
        browser = desk_browser
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        page.wait_for_selector(".tile.is-solo", timeout=15000)
        got = page.evaluate("() => refresh().then(d => ({ok: !!(d && d.ok), title: document.title}))")
        assert got["ok"], "refresh() ended in its catch instead of answering with the fleet"
        assert got["title"].startswith("(1) fleet"), got["title"]
        close_pages(browser)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
