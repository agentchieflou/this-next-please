"""2026-09-23, the Windows 3.14 leg of main: a session handed back went on reading as adopted.

Symptom (`windows · python 3.14`, tests/test_fleet_desk_actions.py, green on the re-run):

    page.click('.tile[data-repo="busy"] .adopt')            # hand it back
>   page.wait_for_function(
        \"\"\"() => /the fleet did not start/.test(
               document.querySelector('.tile[data-repo="busy"] .outside').textContent)\"\"\",
        timeout=15000)
E   playwright._impl._errors.TimeoutError: Page.wait_for_function: Timeout 15000ms exceeded.

A tile's row reaches the page by two roads: an action's own answer (#219), and `/api/fleet`, which
the page asks for whenever the stream says something happened. It drew whichever *arrived* last.
Adopting appends a `started` event, so a snapshot is asked for within the second; on the Windows
runner that snapshot was read while the session was still adopted and landed after the hand-back's
answer, and the tile went back to "a session outside the fleet is driving this repo". Nothing drew it
again: a hand-back only removes a lock, which is not an event, so no frame came to say so -- the desk
showed an adoption that had been handed back until the agent next wrote something. The adopt's own
answer loses the same way when it is the slow one, as it is on Windows since #282: it takes a process
listing of its own.

Now every row says when the server began reading it, and a tile keeps the row it has over one that
was read before it.

Issue: https://github.com/agentchieflou/this-next-please/issues/235
"""
from __future__ import annotations
import json

import pytest

from test_fleet_desk_actions import outside_desk               # noqa: F401 - fixture
from test_fleet_desk_browser import launch_chromium
from test_fleet_events import fleet_home                        # noqa: F401 - fixture

# The answers from one route that still show `busy` adopted, held until the test lets them go. The
# request goes out when the page makes it, so the server *reads* the row then; only its arrival is
# late. `__read` counts the held answers the page has taken the body of, which is the moment its own
# handler runs: the next thing on the queue after that `.then`.
HOLD_THE_ADOPTED = """
  window.__late = %s;
  window.__held = [];
  window.__read = 0;
  const real = window.fetch;
  const adopted = (data) => (data.repos || []).concat([data.row || {}])
      .some(r => r && r.repo === 'busy' && r.external);
  window.fetch = function (url, opts) {
    if (String(url).indexOf(window.__late) < 0) return real.apply(this, arguments);
    return real(url, opts).then(r => r.text().then(body => {
      let data = {};
      try { data = JSON.parse(body); } catch (e) { /* not ours to judge */ }
      const answer = () => new Response(body, { status: r.status, headers: r.headers });
      if (!adopted(data)) return answer();
      return new Promise(go => window.__held.push(() => {
        const late = answer();
        const json = late.json.bind(late);
        late.json = () => json().then(d => { window.__read += 1; return d; });
        go(late);
      }));
    }));
  };
  window.__letGo = () => window.__held.splice(0).forEach(f => f());
"""

# Null-safe: the first predicate runs before the page has drawn its first tile.
OUTSIDE = "((document.querySelector('.tile[data-repo=\"busy\"] .outside') || {}).textContent || '')"
OFFERED = f"() => /the fleet did not start/.test({OUTSIDE})"


def test_an_actions_row_is_numbered_after_every_snapshot_begun_before_it(fleet_home, tmp_path):  # noqa: F811
    """The server's half, without a browser: the order the page keeps rows in is the order they
    were read in, and an action's answer is read after the action."""
    from agentdata.fleet import adopt as A
    from agentdata.fleet import serve as S
    from agentdata.fleet.registry import Registry

    from test_fleet import make_project

    busy = make_project(tmp_path / "busy", phase="working")
    Registry().add(busy, name="busy")
    before = S.fleet_snapshot()["repos"][0]["as_of"]
    A.adopt("busy")
    answer = S.row_for("busy")
    assert answer["external"] and answer["as_of"]["run"] == before["run"]
    assert answer["as_of"]["n"] > before["n"], (before, answer["as_of"])


@pytest.mark.browser
@pytest.mark.parametrize("late", ["/api/fleet", "/api/adopt"],
                         ids=["the-streams-snapshot", "the-adopts-own-answer"])
def test_an_answer_read_before_the_hand_back_does_not_undo_it(outside_desk, late):  # noqa: F811
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(HOLD_THE_ADOPTED % json.dumps(late))
        page.goto(outside_desk, wait_until="domcontentloaded")
        page.wait_for_function(OFFERED, timeout=15000)

        page.click('.tile[data-repo="busy"] .adopt')
        # The tile shows the adoption from whichever answer was not held, and one that was is on its
        # way. The page is asked for a snapshot here rather than left to the stream's frame, which
        # may have come and gone already: this is the same call that frame makes.
        page.wait_for_function(
            f"""() => {{ if (!pendingRefresh) refresh();
                        return window.__held.length > 0 && /is driving this repo/.test({OUTSIDE}); }}""",
            polling=100, timeout=15000)

        page.click('.tile[data-repo="busy"] .adopt')            # hand it back
        page.wait_for_function(OFFERED, timeout=15000)           # the hand-back's own answer

        # And now the answer that was read while it was still adopted arrives.
        page.evaluate("() => __letGo()")
        page.wait_for_function("() => window.__read > 0", timeout=15000)
        shown = page.evaluate(f"() => {OUTSIDE}")
        button = page.inner_text('.tile[data-repo="busy"] .adopt').strip()
        assert not errors, errors
        browser.close()

    assert "the fleet did not start" in shown, shown
    assert button == "adopt it", button
