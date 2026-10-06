"""Page speed (the operator, 2026-10-06: "work on optimizing the load time when clicking between chat,
desk, and world. We're aiming for ~200ms loads. Right now we're at several seconds").

What is held here is what a test can hold of it: that the desk asks the browser to prerender the
world while the pointer rests on its link, and never under test automation. The server's half
(static files kept and revalidated, a poll that finds nothing writes nothing, the store read once
per change) is in `test_fleet_serve.py`, `test_fleet_events.py` and `test_fleet_sessions.py`; the
world's boot (compiling for its own target, the warm-up by time, the warm-up while prerendered) is
measured, not tested, and docs/fleet-world.md says how.
"""
from __future__ import annotations
import json

import pytest

from test_fleet_ink import _repos, _serve, _stop, fleet_home  # noqa: F401 - fixture


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


@pytest.mark.browser
def test_the_desk_prerenders_the_world_on_a_hover_but_never_under_automation(fleet_home, tmp_path, browser):
    """The operator, 2026-10-06: "We're aiming for ~200ms loads" between the chat, the desk and the
    world. The world takes a second to build and compile; the desk asks Chrome to prerender it while
    the pointer rests on its link (`prerender("#worldbtn")`, a `moderate` document rule), so the click
    shows a world that is already drawn. Only the world's link, never under test automation (a test
    that rests the pointer on a link must not build a second world), and only in a browser with
    speculation rules."""
    _repos(tmp_path, ["alpha"])
    server, token, port = _serve()
    try:
        rules = []
        for automated in (True, False):
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            if not automated:
                page.add_init_script("Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => false })")
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function("() => !!document.getElementById('worldbtn').getAttribute('href')", timeout=15000)
            supported = page.evaluate("() => !!(HTMLScriptElement.supports && HTMLScriptElement.supports('speculationrules'))")
            rules.append(page.evaluate("() => [...document.querySelectorAll('script[type=speculationrules]')].map(s => s.textContent)"))
            page.close()
        assert rules[0] == [], "a rule was written under test automation"
        if supported:
            assert len(rules[1]) == 1, rules
            assert json.loads(rules[1][0]) == {"prerender": [{"source": "document", "where": {"selector_matches": "#worldbtn"},
                                                               "eagerness": "moderate"}]}, rules
    finally:
        _stop(server)
