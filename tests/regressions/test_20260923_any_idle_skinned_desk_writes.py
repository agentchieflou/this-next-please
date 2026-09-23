"""2026-09-23, the desk in Chromium: an idle desk with a skin chosen made DOM mutations.

Symptom:

    AssertionError: an idle glass desk wrote to the page: {'n': 40, 'seen': ['attributes data-theme
    HTML', 'attributes data-skin has-ground', 'attributes data-skin-variant has-ground',
    'attributes class has-ground', 'attributes class has-ground', ...], 'renders': 8}

Seen building glass on three.js (#254). Every `/api/fleet` answer carries the theme, and the page
applied it whole each time: `applyTheme` and `applySkin` set `data-theme`, `data-skin` and
`data-skin-variant` to the values they already had, and the glass ground (#218) re-read its mesh by
taking `has-ground` off `<body>` and putting it back. Five mutations a refresh on a desk where
nothing had changed -- against the render contract's zero -- and, with the ink layer on, a repaint
of every ink for each one, because the layer follows the theme's attributes. Idle with no skin was
zero all along, which is why nothing caught it: the idle tests never chose one.

Issue: https://github.com/agentchieflou/this-next-please/issues/254
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import COUNT_FETCHES, IDLE_LOOP, _desk_of, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401 - fixtures


@pytest.mark.browser
def test_an_idle_desk_with_a_skin_writes_nothing(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "glass:azure"}}',
                                                encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(COUNT_FETCHES)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                     && document.body.dataset.skinVariant === 'azure'
                     // The skin's stylesheet is painting its ground (`has-ground` went with
                     // the 2D ground, #257).
                     && /radial-gradient/.test(getComputedStyle(document.body).backgroundImage)
                     && !document.body.classList.contains('is-stale')""", timeout=15000)
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle skinned desk wrote to the page: {count}"
