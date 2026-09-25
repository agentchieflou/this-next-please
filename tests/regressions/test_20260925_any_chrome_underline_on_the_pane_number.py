"""2026-09-25, CI on train 2 (#478) at 6fb46c3, ubuntu-latest, Python 3.12 and 3.14, Chrome for
Testing 153; reproduced on `main` @ e5fb269 in 6 of 10 runs of the test under `-n auto`:

Symptom (`test_skin_marks_keep_inside_their_pane_and_off_other_words[700]`):

    ('napkin:diner @ 700px: underline pen (.tile.state-running .head .repo) on runs', 'covers',
     '2', 'span.n', 5)

At 700px the panes are `compact`, where app.css gives the name `order: -1` and a row of its own, so
the pane number (`.n`), which comes *before* the name in the markup, is laid out on the row under
it. `layer.js` `under()` looked for the next row only among the elements *after* the anchor in the
markup. While the chip sat on the number's row it found the chip, and the underline kept 3.4px
over it. Once the running turn's age made the chip too wide to share that row and it wrapped to
a third, the only row `under()` saw was the chip's. The underline went down to the name's foot +
2px, over the top of the number. Now every sibling that starts below the anchor counts, in any
markup order.

The chip is put on a row of its own here, so the number is alone under the name on every run.

Issue: https://github.com/agentchieflou/this-next-please/issues/332
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _open, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401 - fixtures
from test_fleet_ink_bounds import MEASURE, NAMES, RUNS, FIN, TOOL_W, bounds_desk, choose, desk_states, problems
from test_fleet_ink_notebook import alive, finished  # noqa: F401 - fixtures are used by name


@pytest.mark.browser
def test_the_running_underline_keeps_off_the_pane_number_under_the_name(fleet_home, tmp_path, monkeypatch,
                                                                         alive, finished):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.update({RUNS, FIN})
    finished.add(FIN)
    bounds_desk(tmp_path, fleet_home, monkeypatch)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(NAMES), width=700, reduced=True)
            desk_states(page)
            # The chip on a row of its own, as a long enough age puts it: the number is alone under the name.
            page.add_style_tag(content=f'.tile[data-repo="{RUNS}"] .head .chip {{ flex: 0 0 100% !important; }}')
            choose(page, "napkin:diner")
            laid = page.evaluate(f"""() => {{
              const h = document.querySelector('.tile[data-repo="{RUNS}"] .head'), r = h.querySelector('.repo'),
                    n = h.querySelector('.n'), c = h.querySelector('.chip');
              const [rq, nq, cq] = [r, n, c].map(e => e.getBoundingClientRect());
              return {{ tier: h.closest('.tile').dataset.tier, numberUnderName: nq.top >= rq.bottom,
                        chipUnderNumber: cq.top >= nq.bottom }};
            }}""")
            marks = page.evaluate(MEASURE, TOOL_W)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert laid == {"tier": "compact", "numberUnderName": True, "chipUnderNumber": True}, laid
    running = [m for m in marks if m["repo"] == RUNS and m["shape"] == "underline"]
    assert running, marks
    found = problems("napkin:diner", 700, running)
    assert not found, "\n".join(map(str, found))
