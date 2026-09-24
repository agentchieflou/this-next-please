"""2026-09-23, the desk in Chrome: back from /settings, the desk paints the system palette, then the
skin just replaced, then the chosen one.

Symptom:

    first paint ['', '#f6f7f8'] -> voxel #400000 (the replaced skin) -> farmstead at 130-344 ms

and, from the operator's laptop sitting (#354): "we will load up on a previous setting, but then
when we go to the settings page, it still shows the system theme before snapping back to the loaded
up theme. Similarly, when we switch themes and then go back to the desk, we still lag."

The served page carried no theme, so its first frame was the system palette; `restoreCached()` then
painted the snapshot's theme, taken before the change; only the `/api/fleet` answer brought the
chosen skin. The first frame of /settings must wear the skin in force, and every frame of the
returning desk that has a <body> the one just chosen.

Issue: https://github.com/agentchieflou/this-next-please/issues/345
"""
from __future__ import annotations

import re

import pytest

from test_fleet_ink import _serve, _stop, fleet_home, _own_desk_globals  # noqa: F401
from test_fleet_theme_switch import (SETTLED, _desk, _farmstead_bg, _frames, _page, _setup,  # noqa: F401
                                     _wrong, browser)


@pytest.mark.browser
def test_settings_and_the_desk_after_it_paint_the_chosen_skin_first(browser, fleet_home, tmp_path):
    _setup(fleet_home, tmp_path, skin="voxel:nether")
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _desk(page, port, token)
        page.wait_for_function("() => document.body.dataset.skin === 'voxel'", timeout=15000)
        nether = page.evaluate("() => document.documentElement.style.getPropertyValue('--bg')")

        page.locator("#setbtn").click()
        page.wait_for_url(re.compile(r"/settings"), timeout=15000)
        page.wait_for_function("() => document.querySelectorAll('#skin option').length > 3", timeout=15000)
        first = next(f for f in _frames(page)["frames"] if f["skin"] is not None)
        assert (first["skin"], first["bg"]) == ("voxel", nether), f"/settings first frame: {first}"

        page.evaluate("s => post('theme', { skin: s })", "farmstead:daytime")
        bg = _farmstead_bg()
        page.locator("#backbtn").click()
        page.wait_for_url(re.compile(r"/\?"), timeout=15000)
        page.wait_for_function(SETTLED + " && document.body.dataset.skin === 'farmstead'", timeout=15000)
        frames = _frames(page)["frames"]
        assert not _wrong(frames, "farmstead", bg, "voxel"), frames
        assert not errors, errors
        page.close()
    finally:
        _stop(server)
