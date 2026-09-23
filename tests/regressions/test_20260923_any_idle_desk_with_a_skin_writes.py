"""2026-09-23, the desk in Chromium: an idle desk with a skin chosen wrote to the page on every pass.

Symptom:

    AssertionError: an idle farm wrote to the page: {'n': 56, 'seen': ['attributes data-theme HTML',
    'attributes data-skin BODY', 'attributes data-skin-variant BODY', 'attributes data-waiting LINK', ...

Seen building farmstead on three.js (#255). Every refresh applies the palette and the skin again,
and `applyTheme` / `applySkin` set `data-theme`, `data-skin` and `data-skin-variant` whether or not
they had changed -- a mutation record each, twice a pass. And `startGround` waited again for the
skin's stylesheet to load, writing `data-waiting` on its link, for every skin with no ground mesh
(farmstead, voxel), although the sheet had loaded long before. The desk's own idle test chooses no
skin, so nothing saw it; the ink layer, which follows `data-skin`, drew a frame for each write. The
render contract (`attr`) is what they use now, and a loaded sheet is not waited for.

Issue: https://github.com/agentchieflou/this-next-please/issues/255
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, _desk_of, _open, _serve, _stop,  # noqa: F401 - fixtures
                            fleet_home, _own_desk_globals)


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["voxel:nether", "farmstead:cave"])
def test_an_idle_desk_with_a_skin_writes_nothing(fleet_home, tmp_path, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, count=True)
            family, variant = skin.split(":")
            page.wait_for_function(f"""() => document.body.dataset.skin === '{family}'
                                     && document.body.dataset.skinVariant === '{variant}'
                                     && !!document.head.querySelector('link[data-skin]').sheet""",
                                   timeout=15000)
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle desk with {skin} wrote to the page: {count}"
