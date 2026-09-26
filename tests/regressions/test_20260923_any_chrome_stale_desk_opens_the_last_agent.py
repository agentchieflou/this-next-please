"""2026-09-23, the Windows CI leg on #259: a reloaded desk opened the agent from a click before.

Symptom (`windows · python 3.14`, tests/test_fleet_demo_ownership.py):

    assert early["stale"], "the reconnect did not say the desk was the old one"
    E   AssertionError: the reconnect did not say the desk was the old one

The desk a window draws while its first `/api/fleet` is in flight is the snapshot it cached from
its LAST fleet answer. That answer was older than the window's last click: taken while luna was
open, it reopened luna on the reload, and the desk jumped to the agent actually left open only when
the fleet answered (#230's snap-back, on the reload path). The test then waited on the first tile,
which the column was hiding behind luna, until the stale desk had gone. (The column went with #233;
luna is opened here from its rail, and the stale desk is the same.)

The snapshot is now taken again as the window goes, with the agent it has open, and the stale desk
opens that one. Its version is not believed, so the first real answer always wins.

Issue: https://github.com/agentchieflou/this-next-please/issues/230
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S  # noqa: F401 - the desk the fixtures own

# The desk's globals are reset for every test by tests/conftest.py (#298): without that this runs on
# whatever desk the previous test in the worker left loaded, and never reads its own desk.json.
from test_fleet_demo_ownership import (_desk_of_five, _serve,  # noqa: F401
                                       fleet_home)
from test_fleet_desk_browser import launch_chromium

SOLO = "(document.querySelector('.tile.is-solo') || {dataset: {}}).dataset.repo"
SLOW_FLEET = """
  const real = window.fetch;
  window.fetch = function (url, opts) {
    if (String(url).indexOf('/api/fleet') >= 0) {
      return new Promise(go => setTimeout(() => go(real(url, opts)), 1500));
    }
    return real.apply(this, arguments);
  };
"""


@pytest.mark.browser
def test_a_reload_draws_the_agent_that_was_open_not_the_one_the_last_answer_saw(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of_five(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="rdsd-pbi-reporting"].is-solo', timeout=15000)

            # The fleet answers while luna is open, and then the operator goes back.
            page.locator('.tile[data-repo="luna"] .pane-rail').click()
            page.wait_for_selector('.tile[data-repo="luna"].is-solo', timeout=8000)
            page.evaluate("() => refresh()")
            page.wait_for_function(f"() => {SOLO} === 'luna' && !pendingRefresh", timeout=8000)
            page.evaluate("() => backToPrevious()")
            page.wait_for_selector('.tile[data-repo="rdsd-pbi-reporting"].is-solo', timeout=8000)
            page.wait_for_function("() => windowWrites === 0", timeout=8000)

            page.add_init_script(SLOW_FLEET)
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=5000)
            early = page.evaluate(f"""() => ({{
              stale: document.body.classList.contains('is-stale'),
              open: {SOLO},
            }})""")
            assert early["stale"], early
            assert early["open"] == "rdsd-pbi-reporting", \
                f"the stale desk opened {early['open']}, the agent from a click before"

            page.wait_for_function("() => !document.body.classList.contains('is-stale')", timeout=15000)
            assert page.evaluate(SOLO) == "rdsd-pbi-reporting"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
