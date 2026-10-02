"""2026-10-02, reported by the operator: the green checkmark and the red X overlap, occasionally.

Symptom: a pane that went blocked -> done (the normal flow: asked, answered, finished) showed the
green check drawn over a struck red cross, and done -> error the marker bang over a struck check.

Cause: the check, the bang and the cross are all drawn at one anchor in the pane's margin
(`shapes.margin`). A mark that leaves is struck and kept as history (`layer.js`, one struck mark per
row and element), so the cross stayed, struck, at exactly the spot the check was then drawn on.
"Occasionally" because it takes a pane passing through two margin states.

Fix: a margin mark that starts drawing takes up any struck margin mark on its element, and a margin
mark struck while another is already drawn there is dropped (`Layer.clearMargin`, `marginTaken`).
History is kept for every other mark, and for a margin mark nothing replaces.

Issue: https://github.com/agentchieflou/this-next-please/issues/624 (the operator's report, fixed in that PR)
"""
from __future__ import annotations

import pytest

from desk_harness import close_pages
from test_fleet_ink import _marks, _open, _rest, _serve, _stop, fleet_home  # noqa: F401 - fixtures
from test_fleet_ink_margin import alive, finished  # noqa: F401 - fixtures
from test_fleet_ink_playbook import _desk, _emit, _of, _playbook, _until_class

MARGIN = ("check", "bang", "cross")


def _margin(marks, lane):
    return [m for m in marks if m["lane"] == lane and m["shape"] in MARGIN and not m["strikeOf"]]


@pytest.mark.browser
def test_one_margin_mark_per_pane_never_a_check_over_a_cross(fleet_home, tmp_path, alive, finished, desk_browser):
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(desk_browser, port, token, "&ink=on", reduced=True)
        _playbook(page)
        A, B = "pane:alpha", "pane:beta"

        # blocked -> done: the X, then the check in its place
        _emit(page, "alpha", ("phase_changed", {"from": "build", "to": "blocked"}))
        _until_class(page, "alpha", "state-blocked")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'cross' && m.lane === 'pane:alpha' && m.state === 'drawn')")
        assert [m["shape"] for m in _margin(_marks(page), A)] == ["cross"]
        alive.add("alpha")
        finished.add("alpha")
        _emit(page, "alpha", ("phase_changed", {"from": "blocked", "to": "done"}))
        _until_class(page, "alpha", "is-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:alpha' && m.state === 'drawn')")
        marks = _marks(page)
        assert [(m["shape"], m["state"]) for m in _margin(marks, A)] == [("check", "drawn")], _margin(marks, A)
        assert _of(marks, A, "is-done", "green", "check")

        # done -> error: the check, then the bang in its place
        _emit(page, "beta", ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "beta", "is-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:beta' && m.state === 'drawn')")
        _emit(page, "beta", ("error", {"exit_code": 2}))
        _until_class(page, "beta", "state-error")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'bang' && m.lane === 'pane:beta' && m.state === 'drawn')")
        marks = _marks(page)
        assert [(m["shape"], m["state"]) for m in _margin(marks, B)] == [("bang", "drawn")], _margin(marks, B)
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        _stop(server)
