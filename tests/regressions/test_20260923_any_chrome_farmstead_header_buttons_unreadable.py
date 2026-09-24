"""2026-09-23, the desk in headless Chromium at 8557b2b: farmstead's header and footer buttons were unreadable.

Symptom (farmstead:daytime, ink on, 1400x900, computed colour against computed background):

    "sidebar", "chime off", "0 new", "keys"  -> #FFFDF5 on #E8DFCB, 1.30:1
    the "?" key                              -> #FFFDF5 on #EFE6D2, 1.22:1

`skin.css` wrote `header, header h1, footer { color: var(--farm-band-ink) }`: the near-white ink for
words written on the dark planks. It cascaded into the buttons, the keys and the search field, which
keep the palette's own light backgrounds, so the controls were white on cream. The band ink is for
the words on the planks now, and every control keeps the palette's `--text` (#336).

Issue: https://github.com/agentchieflou/this-next-please/issues/336
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _serve, _stop, fleet_home, _own_desk_globals  # noqa: F401 - fixtures
from test_fleet_ink_farmstead import CONTROLS, _choose, _farm_desk, _inked, _page, _ratio


@pytest.mark.browser
def test_farmstead_daytime_header_and_footer_controls_read_at_4_5(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token)
            _choose(page, "farmstead:daytime")
            _inked(page, "farmstead:daytime")
            controls = page.evaluate(CONTROLS)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    named = {c["what"].split('"')[1] for c in controls}
    assert {"sidebar", "chime off", "0 new", "? keys", "?"} <= named, named
    for c in controls:
        assert c["ground"], f"{c['what']} has no background of its own"
        assert _ratio(c["color"], c["ground"]) >= 4.5, (c["what"], c["color"], c["ground"],
                                                        round(_ratio(c["color"], c["ground"]), 2))
