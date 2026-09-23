"""2026-09-23, found building the notebook (#249): an idle desk with a skin on it wrote to the page.

Symptom (tests/test_fleet_ink_notebook.py, the idle desk with the notebook chosen):

    AssertionError: an idle notebook wrote to the page: {'n': 56, 'seen': ['attributes data-theme
    HTML', 'attributes data-skin BODY', 'attributes data-skin-variant BODY', 'attributes
    data-waiting LINK', 'attributes data-waiting LINK', ...

Two writers, neither under the render contract (#215). Every snapshot applies the theme, and
`applyTheme`/`applySkin` set `data-theme`, `data-skin` and `data-skin-variant` whether or not they
had changed -- an attribute set to the value it already has is still a mutation. And the ground's
retry for a stylesheet that had not arrived yet (#218) ran for every skin, though only glass has a
ground in its stylesheet: for farmstead, voxel or the notebook the mesh never came, so the timed
retry set and cleared `data-waiting` every 150ms for as long as the page was open. The idle-desk
tests never chose a skin through the config, so neither showed.

Now the three attributes are written through `attr`, which writes only a change, and the retry is
glass's alone.

Issue: https://github.com/agentchieflou/this-next-please/issues/249
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, _open, _own_desk_globals, _repos, _serve,  # noqa: F401 - fixtures
                            _stop, fleet_home)


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["farmstead:cave", "voxel"])
def test_an_idle_desk_with_a_skin_on_it_writes_nothing(fleet_home, tmp_path, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, ("alpha", "beta"))
    S.arrange(order=["alpha", "beta"])
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, count=True)
            page.wait_for_function(f"() => document.body.dataset.skin === '{skin.split(':')[0]}'",
                                   timeout=15000)
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle desk with {skin} on it wrote to the page: {count}"
