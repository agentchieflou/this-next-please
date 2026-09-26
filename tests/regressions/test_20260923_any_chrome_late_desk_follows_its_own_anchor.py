"""2026-09-23, the Windows 3.14 leg of #270: a pane pressed before the desk loaded was opened twice.

Symptom (`windows · python 3.14`, tests/test_fleet_gutters.py):

    assert len(windows) == 1 and windows[0]["open"] == "gamma" and "widths" in windows[0], sent
    E   assert (4 == 1)
    E    +  where 4 = len([{'w': 'main', 'open': 'gamma', 'widths': {...}, 'version': 3},
    E                      {'w': 'main', 'section': ''}, {'w': 'main', 'open': 'gamma'},
    E                      {'w': 'main', 'read': {'gamma': 4}}])

The page answers a toast's `#tile=luna` once the desk has loaded (`loadDesk().then(followHash)`,
#173). The desk read is the slow one -- a catalogue, a Downloads scandir -- and a pane pressed
before it answers marks the address itself (`markTile`, `replaceState`). Followed then, the page's
own anchor opened that agent a second time through `openAgent`: `drawer(false)` shut whatever
sidebar the operator had opened in the meantime and wrote `section: ""`, then `open` and `read`
again. On a fast machine the desk answers before a hand can press anything; on the Windows runner
it did not.

Now the page follows only the anchor it was opened with, and only if nothing has moved it since.

Issue: https://github.com/agentchieflou/this-next-please/issues/234
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import (_repos, _serve, _stop,  # noqa: F401 - fixtures
                                _window_posts, fleet_home)

# `/api/desk` held until the test lets it go, and counted when it lands.
HOLD_THE_DESK = """
  window.__deskHeld = [];
  window.__deskDone = 0;
  const real = window.fetch;
  window.fetch = function (url, opts) {
    if (String(url).indexOf('/api/desk') >= 0 && !window.__deskFree) {
      return new Promise(go => window.__deskHeld.push(
        () => go(real(url, opts).then(r => { window.__deskDone += 1; return r; }))));
    }
    return real.apply(this, arguments);
  };
  window.__releaseDesk = () => {
    window.__deskFree = true;
    window.__deskHeld.splice(0).forEach(f => f());
  };
"""

SETTLED = """() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                 && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
                 && windowWrites === 0 && !document.body.classList.contains('is-stale')"""


@pytest.mark.browser
def test_a_pane_pressed_before_the_desk_loads_is_not_opened_again_when_it_does(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 2, "beta": 1, "gamma": 0})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            posts = []
            page.on("request", lambda r: posts.append((r.url, r.post_data or ""))
                    if r.method == "POST" else None)
            page.add_init_script(HOLD_THE_DESK)
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function(SETTLED, timeout=15000)
            assert page.evaluate("() => window.__deskDone") == 0, "the desk was not held"

            # The operator opens the inspector and presses a rail, all before the desk answers.
            page.evaluate("() => section('inspector', true)")
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            posts.clear()
            page.locator('.tile[data-repo="gamma"] .pane-rail').click()
            page.wait_for_selector('.tile[data-repo="alpha"][data-tier="rail"]', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            assert page.evaluate("() => location.hash") == "#tile=gamma"

            # Now it answers, and whatever it was going to do is done.
            page.evaluate("() => __releaseDesk()")
            page.wait_for_function("() => window.__deskDone >= 1 && pendingDesk === null",
                                   timeout=15000)
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            page.wait_for_function("() => windowWrites === 0", timeout=8000)
            inspector_shown = page.evaluate("() => !document.getElementById('inspector').hidden")
            open_now = page.evaluate("() => openName()")
            sent = list(posts)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    windows = _window_posts(sent)
    assert len(windows) == 1 and windows[0]["open"] == "gamma" and "widths" in windows[0], windows
    assert inspector_shown, "the desk's late answer shut the sidebar the operator had opened"
    assert open_now == "gamma"
    assert S.desk_state()["windows"]["main"]["section"] == "inspector"
