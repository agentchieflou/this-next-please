"""2026-09-23, the desk in Chromium: with any skin chosen, a desk at rest wrote to the page on every refresh.

Symptom:

    AssertionError: an idle napkin wrote to the page: {'n': 56, 'seen': ['attributes data-theme HTML',
    'attributes data-skin BODY', 'attributes data-skin-variant BODY', 'attributes data-waiting LINK',
    'attributes data-waiting LINK', ...], 'renders': 8}

Seen building the napkin skin (#252), whose test holds an idle desk to zero DOM writes with ink on
the paper. Every refresh applies the theme again, and `applyTheme` and `applySkin` set `data-theme`,
`data-skin` and `data-skin-variant` whether or not they had changed. A skin with no ground mesh (the
farmstead, the voxel, every paper skin) also had `startGround` flag its stylesheet link
`data-waiting` and take the flag off 150ms later, on every refresh, for as long as the page was
open. The desk with no skin writes none of these, which is why the idle-desk tests never saw it; and
the ink layer redraws on `data-skin`, so the napkin's paper was drawn again eight times over a desk
where nothing happened.

Issue: https://github.com/agentchieflou/this-next-please/issues/252
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, _desk_of, _open, _serve, _stop,  # noqa: F401
                            _own_desk_globals, fleet_home)


@pytest.mark.browser
def test_a_desk_at_rest_with_a_skin_writes_nothing(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    # A skin with no ground mesh: the one `startGround` kept waiting for.
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "farmstead:cave"}}', encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, count=True)
            page.wait_for_function("() => document.body.dataset.skinVariant === 'cave'", timeout=10000)
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"a desk at rest with a skin wrote to the page: {count}"
