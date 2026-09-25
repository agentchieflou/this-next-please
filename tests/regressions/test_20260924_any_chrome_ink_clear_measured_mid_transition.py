"""2026-09-24, Chrome for Testing 153 headless shell, reduced motion (#457): with ink on, the header,
the footer and the panes read as opaque over the drawn page, most often right after a reload.

Symptom (a scratch probe, at `main` 153145b and at #458's d859410): for 19 of 28 looks after a
reload, and about one in seven switched in place, `document.body.matches(':has(> #ink[data-skin])')`
was true while `header`, `footer` and every `.tile` still computed the skin's opaque `--panel`
(glass:smoke `rgb(28, 31, 34)`). It was reported as Chromium 153 leaving the #257 rules unapplied.

They were applied. Every element carrying the stale value had a `background-color` transition with
`playState` `running`, `startTime` null and a 0.01ms duration: the reduced-motion block in app.css
gives every element `transition-duration: 0.01ms`, and `transition-property` is `all` by default.
When the clear starts to match -- ink.js lifting the served `ink-off` in the task in which the layer
first sets `#ink[data-skin]` -- each background starts a transition from the opaque panel to
transparent, and until an animation frame starts it the computed style is its start value. The
probe read it in the same task. Two `requestAnimationFrame`s later every look was clear. Rules
keyed on the body instead (`body[data-skin="x"]:not(.ink-off)`, as #441 and #454 did) read exactly
as stale on the same probe, so the key was never the cause. This is #451's first frame, with ink on.

Here the first frame is held on purpose. The page's animation clock is stopped (CDP
`Animation.setPlaybackRate` 0), a look is chosen with ink on, and the header's transition sits at
its start: it reads opaque, and `CLEAR_AT_REST` must say "not yet". Once the clock runs again, the
header, the footer and every pane must be clear when it says yes.

Issue: https://github.com/agentchieflou/this-next-please/issues/457
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _choose, _open, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until, alive, finished  # noqa: F401
from test_fleet_ink_clear import CLEAR_AT_REST, PROBE, drawn, opaque
from test_fleet_ink_margin import OPEN, desk_states, margin_desk

LOOK = "glass:smoke"


@pytest.mark.browser
def test_the_ink_clear_is_measured_at_rest_not_on_its_transitions_first_frame(fleet_home, tmp_path, alive,
                                                                             finished):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(OPEN[1])
    finished.add(OPEN[1])
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(OPEN), width=1400, reduced=True)
            desk_states(page)
            cdp = page.context.new_cdp_session(page)
            cdp.send("Animation.enable")
            cdp.send("Animation.setPlaybackRate", {"playbackRate": 0})
            _choose(page, LOOK)
            drawn(page, LOOK, rest="() => document.querySelector('header').getAnimations().length > 0")
            held = page.evaluate(f"() => ({{ probe: ({PROBE})(), ready: ({CLEAR_AT_REST})() }})")
            cdp.send("Animation.setPlaybackRate", {"playbackRate": 1})
            page.wait_for_function(CLEAR_AT_REST, timeout=10000, polling=100)
            rest = page.evaluate(PROBE)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # the first frame: the rule matches, and the header still reads as the opaque panel
    assert any(bad.startswith("header background") for bad in opaque(held["probe"])), held
    assert held["ready"] is False, ("CLEAR_AT_REST took a transition's first frame for the clear", held)
    assert opaque(rest) == [], rest
