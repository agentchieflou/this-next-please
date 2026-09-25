"""The effects seam (#370, epic #293): `ink/fx.js`, fetched by the layer only for a table with effects.

docs/desk-ink.md §The files and §Budgets. What is asserted, with the layer drawing (`?ink=on`):

* a table without `fx` never asks for fx.js; a table with it asks exactly once, with the run token,
  and the same table set twice does not ask again;
* every detach path -- a table without `fx`, `Ink.setSkin(null)`, `Ink.off()` -- leaves no effects
  attached (`attached() === 0`) and no `fx` in `Ink.inspect().layer`;
* with effects attached and the desk at rest, the idle loop makes 0 DOM mutations and 0 renders.

The budgets (`FX_BUDGET`, `INK_BUDGET`) are held in tests/test_fleet_ink.py.
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, TABLE, _desk_of, _serve, _stop, _open, _rest,  # noqa: F401
                            fleet_home)

#: The test table with effects, and hooks shaped like a skin module's (`cue` is #372's hook).
SET_FX = """t => Ink.setSkin(Object.assign({}, t, { fx: { cues: [] } }),
                             { cue() {}, tick() { return false; } })"""
#: How many layers have effects attached, and whether the layer lists any. The import reaches the
#: module the layer already fetched, so it adds no request.
ATTACHED = """async () => {
  const l = Ink.inspect().layer;
  return { attached: (await import(q('/static/ink/fx.js'))).attached(), fx: !!(l && l.fx),
           layer: !!l };
}"""
FX_UP = "!!Ink.inspect().layer && !!Ink.inspect().layer.fx && Ink.inspect().layer.fx.loaded"


def _fx(asked):
    return [u for u in asked if "/static/ink/fx.js" in u]


@pytest.mark.browser
def test_fx_js_is_fetched_only_by_a_table_with_effects(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, "&ink=on", count=True)

            # A table without effects: fx.js is never asked for.
            assert page.evaluate("t => Ink.setSkin(t)", TABLE)["drawn"] == "ink"
            _rest(page)
            assert _fx(asked) == [], asked
            assert page.evaluate("() => Ink.inspect().layer.fx") is None

            # A table with effects, set twice: fetched once, with the token.
            for _ in range(2):
                assert page.evaluate(SET_FX, TABLE)["drawn"] == "ink"
            _rest(page, FX_UP)
            fx = page.evaluate("() => Ink.inspect().layer.fx")
            assert fx == {"loaded": True, "rows": 0, "children": 0}, fx
            assert page.evaluate(ATTACHED) == {"attached": 1, "fx": True, "layer": True}
            assert len(_fx(asked)) == 1 and f"?t={token}" in _fx(asked)[0], _fx(asked)
            assert page.evaluate("() => Object.keys(Ink.inspect().layer).includes('fx')")

            # At rest with effects attached: nothing written, nothing drawn.
            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk with effects attached wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle paper with effects was redrawn {count['renders']} times"

            # Detached by a table without effects.
            page.evaluate("t => Ink.setSkin(t)", TABLE)
            _rest(page)
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": True}

            # Attached again (the module is already here), then detached by no table at all.
            page.evaluate(SET_FX, TABLE)
            _rest(page, FX_UP)
            assert page.evaluate(ATTACHED)["attached"] == 1
            page.evaluate("() => Ink.setSkin(null)")
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": True}
            assert len(_fx(asked)) == 1, _fx(asked)
            assert not errors, errors
            page.close()

            # Detached by the layer going: a fresh page, so the module's count is its own.
            page, errors, asked = _open(browser, port, token, "&ink=on")
            page.evaluate(SET_FX, TABLE)
            _rest(page, FX_UP)
            assert page.evaluate(ATTACHED)["attached"] == 1
            page.evaluate("() => Ink.off()")
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": False}
            assert len(_fx(asked)) == 1, _fx(asked)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
