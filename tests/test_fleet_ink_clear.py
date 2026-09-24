"""The page stands aside for a skin's canvas on every load, the reload included (#457).

app.css clears the header, the footer, the panes and the cards on a pane wherever a skin draws with
ink (#257), and hides the trace's SVG where the layer draws the trace. No browser test asserted it,
and #458 made the reload -- the chosen skin served in the page, `ink-off` until the layer draws --
the path every desk load takes. This asserts it on both paths.

It is measured at rest. The reduced-motion block gives every element a 0.01ms transition of `all`,
so when ink.js lifts `ink-off` the header's and each pane's background start a transition from the
skin's opaque `--panel` to transparent. Until the next animation frame starts it, the computed style
is the opaque start value, with the rule applied. #457 read that first frame on Chromium 153 and
took it for rules left unapplied (19 looks in 28 after a reload). Two frames later every look is
clear, with the rules keyed as they are (`body:has(> #ink[data-skin])`). The same first frame is
what #451 measured with ink off. `tests/regressions/test_20260924_any_chrome_ink_clear_measured_mid_transition.py`
holds it on purpose.

What is asserted, for one variant of every skin that draws, at 1400x900 under reduced motion, with
ink on and the paper at rest, switched in place and again after a reload: `header`, `footer` and
every `.tile` compute a transparent `background-color`, every `.tile` a transparent
`border-top-color`, and every `.trace > *` is `hidden`.
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import AT_REST, _choose, _open, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until, alive, finished  # noqa: F401 - fixtures are used by name
from test_fleet_ink_margin import OPEN, _sheet, desk_states, margin_desk

#: One variant of every skin that draws.
LOOKS = ("glass:smoke", "voxel:overworld", "napkin:diner", "farmstead:daytime", "graph:engineering",
         "notebook:light", "legalpad:canary")

#: What stands over the canvas: the header, the footer and every pane.
OVER = "[document.querySelector('header'), document.querySelector('footer'), ...document.querySelectorAll('#grid .tile')]"

#: Nothing over the canvas, and no trace SVG, is in a transition: what it computes now is where it
#: comes to rest. A transition not yet started by a frame says `running` too.
CLEAR_AT_REST = f"""() => ![...{OVER}, ...document.querySelectorAll('.trace > *')]
  .some(el => el.getAnimations().some(a => a.playState === 'running'))"""

PROBE = f"""() => {{
  const out = [];
  for (const el of {OVER}) {{ const s = getComputedStyle(el);
    out.push([el.matches('.tile') ? 'tile:' + el.dataset.repo : el.tagName.toLowerCase(),
              {{ bg: s.backgroundColor, top: s.borderTopColor }}]); }}
  return {{ panes: out, traces: [...document.querySelectorAll('.trace > *')].map(t => getComputedStyle(t).visibility) }};
}}"""

CLEAR = ("rgba(0, 0, 0, 0)", "transparent")


def opaque(seen):
    """What is still drawn over the canvas: a background, a pane's top border, or a trace SVG that
    did not step aside."""
    bad = [f"{name} background {v['bg']}" for name, v in seen["panes"] if v["bg"] not in CLEAR]
    bad += [f"{name} border-top {v['top']}" for name, v in seen["panes"]
            if name.startswith("tile:") and v["top"] not in CLEAR]
    bad += [f"trace {v}" for v in seen["traces"] if v != "hidden"]
    return bad


def drawn(page, look, rest=CLEAR_AT_REST):
    """The look's table and sheet in force, `ink-off` lifted, the paper at rest and, unless `rest`
    says otherwise, nothing over it mid-transition. While the table is not the look yet the page is
    asked to look again: a `/api/fleet` answer in flight can carry the skin before."""
    skin = look.split(":")[0]
    page.wait_for_function(f"""() => (window.Ink && Ink.inspect().table === '{look}' || (window.refresh && refresh(), false))
      && ({_sheet(skin)}) && !document.body.classList.contains('ink-off') && ({AT_REST})()
      && document.querySelectorAll('#grid .tile').length === {len(OPEN) + 1} && ({rest})()""",
                           timeout=30000, polling=100)


@pytest.mark.browser
def test_the_page_stands_aside_for_every_skin_that_draws_in_place_and_after_a_reload(fleet_home, tmp_path,
                                                                                    alive, finished):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(OPEN[1])
    finished.add(OPEN[1])
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    stale = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(OPEN), width=1400, reduced=True)
            desk_states(page)
            for look in LOOKS:
                _choose(page, look)
                drawn(page, look)
                in_place = opaque(page.evaluate(PROBE))
                page.reload(wait_until="domcontentloaded")
                drawn(page, look)
                reloaded = opaque(page.evaluate(PROBE))
                if in_place or reloaded:
                    stale[look] = {"in place": in_place, "after a reload": reloaded}
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # Which looks, and on which path, first: the elements follow.
    assert not stale, ([f"{look} {path}" for look, paths in stale.items() for path, bad in paths.items() if bad], stale)
