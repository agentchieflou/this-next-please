"""2026-09-23, measured in headless Chromium at 8557b2b, 1400x900: the done check and the error bang
were written over the pane number and the agent's name.

Symptom (`Ink.inspect().layer.marks[].bounds` against the text's `Range` rects, in glass, voxel,
farmstead, napkin and graph):

    green check: over "4" and "delta", 54-144 px²
    error bang:  over "gamma", 22-45 px²

`shapes.js` `margin()` writes a check or a bang 14px in from the left of its anchor. Glass, voxel,
napkin and farmstead anchored those rows on `.tile ... .head`, whose box starts at the pane's
content edge, so the mark landed on `.head .n` and the name; graph anchored on the pane, but a pane
had only 10px of left padding. Now every check and bang row anchors on the pane, and an open pane
under ink has a 26px left padding (each drawing skin's sheet), the margin the marks are written in.

Issue: https://github.com/agentchieflou/this-next-please/issues/330
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _open, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401 - fixtures
from test_fleet_ink_margin import (OPEN, SUPERVISED, alive, check_on, choose_on, desk_states,  # noqa: F401
                                   finished, margin_desk, measure_on)


@pytest.mark.browser
def test_the_check_and_the_bang_stay_off_the_pane_number_and_the_name(fleet_home, tmp_path, alive, finished):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(SUPERVISED)
    finished.add(SUPERVISED)
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(OPEN), width=1400, reduced=True)
            desk_states(page)
            for look in ("glass:smoke", "graph:engineering"):
                choose_on(page, look)
                seen[look] = measure_on(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for look, marks in seen.items():
        check_on(look, 1400, marks)
