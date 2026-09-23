"""2026-09-23, the Windows 3.14 leg of #278: a running agent's line, struck when it errored, was
drawn again after its strike.

Symptom (`windows · python 3.14`, tests/test_fleet_ink_notebook.py):

    >   assert len(gone) == 1 and gone[0]["state"] == "struck" and gone[0]["strokes"] == 1, \\
    E   AssertionError: the running line is struck, and its tip lifted
    E   assert (1 == 1 and 'drawn' == 'struck'

The notebook's running line grows with the transcript (`grow`, #249). The refresh that takes
`state-running` off a pane often brings the line that ends the turn, and the layer handled both in
the same frame: the row's match had gone, so the mark's strike was queued; then the mark was
measured, the new line made it longer, and the rest of it was queued to be drawn -- after the
strike. That draw set the mark back to `drawn` and extended a line that had been struck. On a fast
machine the transcript line usually lands a frame apart from the class; on the Windows runner they
landed together.

Now a mark that is leaving does not grow, and a draw queued for it is not run.

Issue: https://github.com/agentchieflou/this-next-please/issues/249
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (_desk_of, _marks, _open, _own_desk_globals, _rest, _serve,  # noqa: F401 - fixtures
                            _stop, fleet_home)

TABLE = {"name": "grow", "marks": [
    {"selector": ".tile.ink-run .repo", "tool": "pen", "shape": "underline",
     "grow": ".transcript > li", "step": 12, "tip": True},
]}

#: In one task, as a refresh does it: the class goes and a transcript line arrives.
BOTH_AT_ONCE = """() => {
  const tile = document.querySelector('.tile[data-repo="alpha"]');
  tile.classList.remove('ink-run');
  const li = document.createElement('li');
  li.textContent = 'exit 2';
  tile.querySelector('.transcript').appendChild(li);
}"""


@pytest.mark.browser
@pytest.mark.parametrize("reduced", [True, False])
def test_a_growing_line_that_leaves_as_its_pane_grows_is_struck_and_stays_struck(fleet_home, tmp_path, reduced):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=reduced)
            page.evaluate("t => Ink.setSkin(t)", dict(TABLE, speed=4))
            page.evaluate("() => document.querySelector('.tile[data-repo=\"alpha\"]').classList.add('ink-run')")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.state === 'drawn')")
            page.evaluate(BOTH_AT_ONCE)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.strikeOf && m.state === 'drawn')")
            marks = _marks(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    line = [m for m in marks if not m["strikeOf"]]
    assert len(line) == 1 and line[0]["state"] == "struck", line
    assert line[0]["strokes"] == 1, "the tip is lifted before the strike"
    assert line[0]["drawn"] == 1, "struck at the length it had, never drawn on after its strike"
