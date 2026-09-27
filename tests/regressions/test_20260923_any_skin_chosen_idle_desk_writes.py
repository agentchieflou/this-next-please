"""2026-09-23, the desk in Chromium: with any skin but glass chosen, an idle desk kept writing.

Symptom:

    AssertionError: an idle graph desk wrote to the page: {'n': 56, 'seen': ['attributes
    data-theme HTML', 'attributes data-skin BODY', 'attributes data-skin-variant BODY',
    'attributes data-waiting LINK', 'attributes data-waiting LINK', ...], 'renders': 8}

Seen building the graph paper skin (#253), the first test to hold an idle desk with a skin chosen
to the render contract. Every snapshot applied the palette and the skin again, and set
`data-theme`, `data-skin` and `data-skin-variant` to the values they already had -- a mutation
all the same, and the ink layer repainted on each. And `startGround` waited for the skin's
stylesheet to hand it a ground mesh that only glass has: for farmstead, voxel and every paper
skin the retry re-armed itself every 150ms, writing `data-waiting` on the link, for as long as the
page was open.

Issue: https://github.com/agentchieflou/this-next-please/issues/253
"""
from __future__ import annotations

import pytest

from desk_harness import close_pages, desk_page
from desk_waits import observe_quiet
from test_fleet_ink import _desk_of, _serve, _stop, fleet_home  # noqa: F401 - fixtures


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["farmstead:cave", "voxel"])
def test_an_idle_desk_with_a_skin_chosen_writes_nothing(fleet_home, tmp_path, skin, desk_browser):
    _desk_of(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    server, token, port = _serve()
    try:
        browser = desk_browser
        page = desk_page(browser, width=1400, height=900)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        family = skin.split(":")[0]
        page.wait_for_function(
            f"""() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                 && document.body.dataset.skin === {family!r}
                 && !!document.head.querySelector('link[data-skin]')
                 && !document.body.classList.contains('is-stale')""", timeout=15000)
        count = observe_quiet(page, passes=8)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert count["mutations"] == 0, f"an idle desk with {skin} chosen wrote to the page: {count}"
