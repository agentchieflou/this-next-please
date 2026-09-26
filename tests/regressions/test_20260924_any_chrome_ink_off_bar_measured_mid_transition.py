"""2026-09-24, ubuntu-latest · python 3.12 (Chromium 153) on PR #460 (1f131e9): with ink off, no pane had
its plain margin bar when it was measured.

Symptom (`tests/test_fleet_ink_margin.py::test_the_plain_margin_bar_is_on_the_pane_and_off_the_words_with_ink_off[700]`):

    look = 'glass:smoke', width = 700, bars = []
    panes = [{'repo': 'alpha', 'tier': 'compact', 'cls': 'tile state-error needs-human is-solo', 'shadow': 'rgba(0, 0, 0, 0) 0px 0...
             {'repo': 'delta', 'tier': 'rail', 'cls': 'tile state-idle is-done', 'shadow': 'rgba(0, 0, 0, 0) 0px 0px 0px 0px inset'}]
    E       AssertionError: ('glass:smoke @ 700px, ink off', [], [...])

Every pane had the right classes. Every box-shadow was the first frame of a transition: the
reduced-motion block in app.css gives every element `transition-duration: 0.01ms`, and
`transition-property` is `all` by default. So when ink.js's fallback sheet put the bars on, each
pane's shadow started from `rgba(0, 0, 0, 0) 0px 0px 0px 0px inset`. That value lasts until the next
animation frame, which on a loaded runner came after the measurement. `choose_off` waited on
`/inset/`, which that first frame already matches. Reproduced locally on Chrome for Testing 153 with
8 workers on 4 cores: 11 of 96 looks, with the diagnostics showing every pane at rest two seconds
later. The page was right. The wait was wrong. It now waits for `OFF_AT_REST`: the whole 3px bar,
and no pane in a running transition.

Here the first frame is held on purpose. The page's animation clock is stopped (CDP
`Animation.setPlaybackRate` 0), a look is chosen with ink off, and the bars' transitions sit at
their start. `OFF_AT_REST` must say "not yet" while `/inset/` says yes. Once the clock runs again,
the bars must be there when it says yes.

Issue: https://github.com/agentchieflou/this-next-please/issues/451
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _choose, _open, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until, alive, finished  # noqa: F401
from test_fleet_ink_margin import (OFF_AT_REST, OPEN, SUPERVISED, UNSUPERVISED, _sheet, desk_states, margin_desk,
                                   measure_off)

LOOK = "glass:smoke"


@pytest.mark.browser
def test_ink_off_bars_are_measured_at_rest_not_on_their_transitions_first_frame(fleet_home, tmp_path, alive,
                                                                               finished):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(SUPERVISED)
    finished.add(SUPERVISED)
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=off", panes=len(OPEN), width=700, reduced=True)
            desk_states(page)
            cdp = page.context.new_cdp_session(page)
            cdp.send("Animation.enable")
            cdp.send("Animation.setPlaybackRate", {"playbackRate": 0})
            _choose(page, LOOK)
            page.wait_for_function(f"""() => (Ink.inspect().table === '{LOOK}' || (refresh(), false))
              && Ink.inspect().plain && ({_sheet('glass')}) && document.body.classList.contains('ink-off')
              && document.querySelector('.tile[data-repo="{UNSUPERVISED}"]').getAnimations().length > 0""",
                                   timeout=30000, polling=250)
            held = page.evaluate(f"""() => ({{
              shadow: getComputedStyle(document.querySelector('.tile[data-repo="{UNSUPERVISED}"]')).boxShadow,
              ready: ({OFF_AT_REST})() }})""")
            bars_held = measure_off(page)
            cdp.send("Animation.setPlaybackRate", {"playbackRate": 1})
            page.wait_for_function(OFF_AT_REST, timeout=10000, polling=100)
            bars = measure_off(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # the first frame: it reads as an inset shadow, and it is not a bar
    assert "inset" in held["shadow"] and not bars_held, (held, bars_held)
    assert held["ready"] is False, ("OFF_AT_REST took a transition's first frame for the bar", held)
    assert {b.get("repo") for b in bars} >= {SUPERVISED, UNSUPERVISED}, bars
