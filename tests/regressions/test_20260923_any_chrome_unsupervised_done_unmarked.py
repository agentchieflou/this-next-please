"""2026-09-23, headless Chromium at 8557b2b: on glass and voxel, an agent that finished while nothing
supervised it had no green check, no green rim and no full stack.

Symptom (this test on main, an agent whose phase is done and whose process is gone; the pane's
classes, the green checks in its lane, then glass's rim or voxel's `stack.state`):

    [glass:smoke]      AssertionError: ('not marked done', 'tile state-idle is-done is-solo', 0, None)
    [voxel:overworld]  AssertionError: ('not marked done', 'tile state-idle is-done is-solo', 0, 'idle')

The fold calls an agent done only once nothing supervises it, and the chip draws every quiet
unsupervised agent as idle, so the page says it finished with `is-done` (#253). The paper skins key
done on `:is(.state-done, .is-done)`; glass and voxel keyed on `.state-done` alone -- the mark row,
glass's `rimOf` and voxel's `read()` -- so a finished agent nobody supervised was drawn as idle.

Now both key on either class.

Issue: https://github.com/agentchieflou/this-next-please/issues/333
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink_glass import (_finished_desk, _open, _serve, _stop,  # noqa: F401 - fixtures
                                  alive, fleet_home)

#: The skin's module, the very instance `ink.js` imported (the same URL), kept as `window.__skin`.
IMPORT = """async (skin) => { window.__skin = await import(q('/static/ink/skins/' + skin + '.js')); }"""
#: What the module says of beta: glass's rim, voxel's stack.
STATE = """(skin) => { const p = window.__skin.inspect().panes.find(x => x.repo === 'beta');
  return p ? (skin === 'glass' ? p.rim : p.stack.state) : null; }"""

CHECKS = """() => (Ink.inspect().layer ? Ink.inspect().layer.marks : []).filter(m => m.lane === 'pane:beta' && m.tool === 'green'
  && m.shape === 'check' && !m.strikeOf && m.state === 'drawn').length"""


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["glass:smoke", "voxel:overworld"])
def test_a_finished_agent_nothing_supervises_is_marked_done(fleet_home, tmp_path, alive, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    family = skin.split(":")[0]
    _finished_desk(tmp_path, fleet_home, skin=skin)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, reduced=True)
            page.wait_for_function(f"() => Ink.inspect().table === '{skin}'", timeout=20000)
            page.evaluate(IMPORT, family)
            try:
                page.wait_for_function(f"() => ({CHECKS})() === 1 && ({STATE})('{family}') === 'done'",
                                       timeout=20000)
            except Exception:
                raise AssertionError(("not marked done", page.evaluate(
                    """() => document.querySelector('.tile[data-repo="beta"]').className"""),
                    page.evaluate(f"({CHECKS})"),
                    page.evaluate(STATE, family)))
            cls = page.evaluate("""() => document.querySelector('.tile[data-repo="beta"]').className""").split()
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert "state-idle" in cls and "is-done" in cls, cls
