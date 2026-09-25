"""2026-09-24, windows · python 3.14 on PR #432 (4dd3cf9): the desk was switched to another glass
variant and went back to the one before.

Symptom (`tests/test_fleet_ink_glass.py::test_a_finished_agent_nothing_supervises_is_ticked_and_rimmed_on_every_variant`):

    AssertionError: ('glass not ready', 'noir', 'at rest', {'on': True, ..., 'table': 'glass:azure',
     ..., 'busy': False, 'frames': 16, 'drawing': [], 'fill': 'rgba(26, 42, 72, 0.40)', ...})

`_choose(page, 'glass:noir')` had posted the skin, and the stream's `theme` event drew it. But a
`/api/fleet` request that was already in flight carried the theme as it was when the server
answered, and `refresh()` applied it when it landed: azure again, with nothing left to correct it.
It needs only a slow answer, which the Windows 3.14 runner gives, and an operator switching skins
while the desk refreshes hits it the same way. `refresh()` now keeps an answer's theme only if no
theme event arrived while it was in flight.

Here the late answer is made on purpose: the page holds one `/api/fleet` answer until the test lets
it go, after the switch has been drawn.

Issue: https://github.com/agentchieflou/this-next-please/issues/437
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink_glass import (_choose, _finished_desk, _open, _serve,  # noqa: F401 - fixtures
                                  _stop, alive, fleet_home)

#: The next `/api/fleet` answer is asked for at once and held until `__release()`.
HOLD_ONE_ANSWER = """() => {
  const real = window.fetch;
  window.__held = false;
  window.fetch = function (url, opts) {
    if (String(url).indexOf('/api/fleet') < 0 || window.__held) return real.apply(this, arguments);
    window.__held = true;
    const answer = real.apply(this, arguments);
    return new Promise(go => { window.__release = () => { window.__held = 'released'; go(answer); }; });
  };
}"""


@pytest.mark.browser
def test_a_fleet_answer_asked_before_a_skin_change_does_not_put_the_old_skin_back(fleet_home, tmp_path, alive):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _finished_desk(tmp_path, fleet_home, skin="glass:azure")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, reduced=True)
            page.wait_for_function("() => Ink.inspect().table === 'glass:azure' && pendingRefresh === null",
                                   timeout=20000)
            page.evaluate(HOLD_ONE_ANSWER)
            # Asked again until an answer is held: a `refreshSoon()` timer can start a refresh with
            # the real fetch between the wait above and the hold, and `refresh()` then hands back
            # that one (#349).
            page.wait_for_function("() => { if (pendingRefresh === null) refresh(); return window.__held === true; }",
                                   timeout=10000)
            _choose(page, "glass:noir")
            page.wait_for_function("() => Ink.inspect().table === 'glass:noir'", timeout=20000)
            page.evaluate("() => window.__release()")
            page.wait_for_function("() => window.__held === 'released' && pendingRefresh === null", timeout=20000)
            table = page.evaluate("() => Ink.inspect().table")
            skin = page.evaluate("() => document.body.dataset.skinVariant")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert (table, skin) == ("glass:noir", "noir"), \
        f"a fleet answer asked before the switch put {table} ({skin}) back"
