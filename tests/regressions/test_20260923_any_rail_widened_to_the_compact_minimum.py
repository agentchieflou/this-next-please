"""2026-09-23, the desk in Chromium: a rail pulled out to the compact minimum stayed a rail.

Symptom:

    playwright._impl._errors.TimeoutError: Page.wait_for_selector: Timeout 8000ms exceeded.
      - waiting for locator(".tile[data-repo=\\"alpha\\"][data-tier=\\"compact\\"]") to be visible
    {'alpha': {'width': 160, 'wide': True, 'tier': 'rail'}, ...}

Seen building the gutters (#234): `Alt+Shift+→` on a rail widens it straight to 160px, the compact
minimum, and the pane was 160px wide with a width of its own and still drawn as a rail -- its face
stretched across 160px, no head, no reply box. The tiers had 8px of slack at every boundary (#233),
so a pane coming from the rail tier had to reach 168px to leave it. Nothing ever sits on that
boundary to flicker across it -- a pane is a 48px rail or at least 160px wide -- so the slack there
only ever did this. The same was reachable before the gutters: a rail swapped into a row crowded
enough to hold the open panes at their 160px floor.

Issue: https://github.com/agentchieflou/this-next-please/issues/234
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import (_page, _repos, _serve, _stop,  # noqa: F401
                                fleet_home)


@pytest.mark.browser
def test_a_rail_widened_to_the_compact_minimum_is_drawn_compact(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, ["alpha", "beta", "gamma"])
    S.arrange(order=["alpha", "beta", "gamma"])
    S.update_window("main", open="beta", widths={"alpha": 0, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=1)
            tiers = page.evaluate("() => [paneTier(160, 'rail'), paneTier(167, 'rail'), "
                                  "paneTier(155, 'compact'), paneTier(365, 'compact')]")
            page.focus('.tile[data-repo="alpha"] .pane-rail')
            page.keyboard.press("Alt+Shift+ArrowRight")
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="compact"]', timeout=8000)
            out = page.evaluate("""() => {
              const t = document.querySelector('.tile[data-repo="alpha"]');
              const shown = el => getComputedStyle(el).display !== 'none';
              return { width: Math.round(t.getBoundingClientRect().width),
                       head: shown(t.querySelector('.head')),
                       face: shown(t.querySelector('.pane-rail')),
                       say: shown(t.querySelector('.say')) };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # Out of the rail at the boundary itself, and still 8px of slack between compact and full.
    assert tiers == ["compact", "compact", "rail", "compact"], tiers
    assert out == {"width": 160, "head": True, "face": False, "say": True}, out
