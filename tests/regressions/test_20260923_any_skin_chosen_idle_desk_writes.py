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

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import COUNT_FETCHES, IDLE_LOOP, _desk_of, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401 - fixtures

#: The mutation count of `IDLE_LOOP` without the layer: it reads the layer's renders, and with no
#: skin drawing ink there is no layer.
WATCH = IDLE_LOOP.replace("Ink.inspect().layer", "null")


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["farmstead:cave", "voxel"])
def test_an_idle_desk_with_a_skin_chosen_writes_nothing(fleet_home, tmp_path, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script(COUNT_FETCHES)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            family = skin.split(":")[0]
            page.wait_for_function(
                f"""() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                     && document.body.dataset.skin === {family!r}
                     && !!document.head.querySelector('link[data-skin]')
                     && !document.body.classList.contains('is-stale')""", timeout=15000)
            count = page.evaluate(WATCH)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle desk with {skin} chosen wrote to the page: {count}"
