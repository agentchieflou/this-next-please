"""2026-09-23, the desk in Chromium: a desk with a skin chosen was never idle.

Symptom:

    AssertionError: an idle voxel desk wrote to the page: {'n': 60, 'seen': ['attributes data-theme HTML',
    'attributes data-skin BODY', 'attributes data-skin-variant BODY', 'attributes data-waiting LINK',
    'attributes data-waiting LINK', ...], 'renders': 14}

Seen building voxel on three.js (#256). Every refresh applies the theme and the skin again, and
`applyTheme` and `applySkin` wrote their attributes whether or not they had changed, so every refresh
was a DOM mutation. A write of the same value is still a mutation, and it woke everything observing
the page, the ink layer among them: 14 WebGL frames for nothing. `startGround` also waited for the
skin's stylesheet to give it a mesh only glass has, so under any other skin it set `data-waiting` on
the link again on every refresh. The render contract says an idle desk is zero DOM mutations. That held
with no skin chosen and broke with any chosen, ink or not.

Issue: https://github.com/agentchieflou/this-next-please/issues/256
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import IDLE_LOOP
from test_fleet_voxel_ink import (_desk_of, _open, _serve, _skin, _stop,  # noqa: F401
                                  fleet_home)


@pytest.mark.browser
# Not glass: its ground reads the mesh by taking `has-ground` off and putting it back on every
# refresh (`groundColours`), a write of its own that belongs to the ground's move to the ink layer
# (#254, #257), not to this.
@pytest.mark.parametrize("skin", ["voxel:nether", "farmstead"])
def test_an_idle_desk_with_a_skin_chosen_writes_nothing(fleet_home, tmp_path, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _skin(fleet_home, skin)
    _desk_of(tmp_path, ("alpha", "beta"))
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            # The gate as it is in CI with no probe recorded: off. No ink draws; the page alone.
            page, errors = _open(browser, port, token, "", panes=2, count=True,
                                 family=skin.split(":")[0])
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle {skin} desk wrote to the page: {count}"
