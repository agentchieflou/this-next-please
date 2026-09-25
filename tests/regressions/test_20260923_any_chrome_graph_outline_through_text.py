"""2026-09-23, measured in headless Chromium at 8557b2b: on the graph paper the ruled outlines left
their panes and went through the words, and the running agent's underline went through the chip
row beside its name.

Symptom (`Ink.inspect().layer.marks[].bounds` against the text's `Range` rects, graph:engineering):

    stale dashed outline: left edge at x=1064, through the first letter of every transcript line;
                          right edge 12px past the viewport
    error outline:        8.8px outside its pane at 1400px, 19.3px at 700px, where it crosses the
                          neighbour's name (253 px²)
    running underline:    snapped down onto the next 28px line, through the chip row at 700px
                          (119-139 px²)

`shapes.snap` rounded each outline edge to the *nearest* grid line, in or out of the pane, and an
underline *down* to the next one, whatever was on it; `layer.js` `clipOf` cut a mark to the
viewport and its scrolling ancestors, never to its pane. Now a mark in a pane's lane is clipped to
the pane's border box (inset 1px); a ruled outline's edges go onto a grid line inside the pane's
padding band, or down the band's middle where it is narrower than a square; and an underline sits
2px under the tallest box on its name's line, ruled only onto a grid line that fits between that
and the next row.

Issue: https://github.com/agentchieflou/this-next-please/issues/331
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink_graph import (_desk, _open, _rest, _run, _serve,  # noqa: F401 - fixtures
                                  _stop, _tile_has, fleet_home)

#: Every drawn outline and underline's strokes, as drawn (the tool's width included), against its
#: pane, the viewport, and the words it may not cross: an outline, the pane's transcript; an
#: underline, every word in its pane but its own.
MEASURE = """async () => {
  const pen = await import(q('/static/ink/pen.js'));
  const words = root => {
    const out = [];
    if (!root) return out;
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim() || !n.parentElement.checkVisibility()) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const b of range.getClientRects()) {
        if (b.width > 0 && b.height > 0) out.push({ el: n.parentElement, x: b.left, y: b.top, r: b.right, b: b.bottom });
      }
    }
    return out;
  };
  const area = (a, b) => Math.max(0, Math.min(a.r, b.r) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.y, b.y));
  const out = [];
  for (const m of Ink.inspect().layer.marks) {
    if (m.state !== 'drawn' || (m.shape !== 'outline' && m.shape !== 'underline')) continue;
    const tile = document.querySelector(`.tile[data-repo="${m.lane.slice(5)}"]`), p = tile.getBoundingClientRect();
    const anchor = [...document.querySelectorAll(m.selector)].find(e => tile.contains(e));
    const ws = m.shape === 'outline' ? words(tile.querySelector('.transcript'))
                                     : words(tile).filter(w => !anchor.contains(w.el));
    const hw = pen.TOOLS[m.tool].w / 2;
    for (const s of m.bounds) {
      const b = { x: s.x - hw, y: s.y - hw, r: s.r + hw, b: s.b + hw };
      out.push({ lane: m.lane, shape: m.shape, tool: m.tool, sel: m.selector, b,
                 out: Math.max(p.left - b.x, p.top - b.y, b.r - p.right, b.b - p.bottom),
                 off: Math.max(-b.x, -b.y, b.r - innerWidth, b.b - innerHeight),
                 hit: Math.max(0, ...ws.map(w => area(b, w))),
                 words: ws.filter(w => area(b, w) > 0).map(w => w.el.textContent.trim().slice(0, 24)) });
    }
  }
  return out;
}"""


@pytest.mark.browser
@pytest.mark.parametrize("width", [1400, 700])
def test_graph_outlines_stay_in_their_panes_and_off_the_words(fleet_home, tmp_path, width):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "error", "beta": "stale"})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token, width=width)
            _tile_has(page, "alpha", "state-error")
            page.wait_for_selector('.tile[data-repo="beta"] .oldsession:not([hidden])', timeout=20000)
            _run("beta")
            _tile_has(page, "beta", "state-running")
            _rest(page, "['pane:alpha', 'pane:beta'].every(l => Ink.inspect().layer.marks.some(m => m.lane === l"
                        " && m.shape === 'outline' && m.state === 'drawn'))"
                        " && Ink.inspect().layer.marks.some(m => m.lane === 'pane:beta' && m.shape === 'underline'"
                        " && m.tool === 'pen' && m.state === 'drawn')")
            got = page.evaluate(MEASURE)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    outlines = [s for s in got if s["shape"] == "outline"]
    running = [s for s in got if s["shape"] == "underline" and s["tool"] == "pen"]
    assert {s["lane"] for s in outlines} == {"pane:alpha", "pane:beta"} and running, got
    for s in outlines:
        assert s["out"] <= 2 and s["off"] <= 2, ("an outline stroke left its pane or the viewport", s)
        assert s["hit"] < 6, ("an outline stroke crossed the transcript", s)
    for s in running:
        assert s["hit"] == 0, ("the running underline crossed a word not its own", s)


@pytest.mark.browser
def test_the_running_underline_keeps_off_a_pill_whose_words_stand_high(fleet_home, tmp_path):
    """Windows, Python 3.14, at 674ce1f and 700px: `the running underline crossed a word not its
    own`, hit 41.97 px². The name wraps onto a row of its own there; the chip is the first element
    after it in the markup, but `.oldsession` starts higher, and under a font whose line box is
    taller than the pill's line-height its words stand above its box. `under()` took the first
    element in the markup for the next row. The pill's words are put where such a font puts them,
    and the underline still keeps off them (before the fix: hit 35.0)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "error", "beta": "stale"})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token, width=700)
            page.add_style_tag(content=".head .oldsession { padding-top: 0 !important;"
                                       " padding-bottom: 6px !important; line-height: 0.9 !important; }")
            page.wait_for_selector('.tile[data-repo="beta"] .oldsession:not([hidden])', timeout=20000)
            _run("beta")
            _tile_has(page, "beta", "state-running")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:beta' && m.shape === 'underline'"
                        " && m.tool === 'pen' && m.state === 'drawn')")
            got = page.evaluate(MEASURE)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    running = [s for s in got if s["shape"] == "underline" and s["tool"] == "pen"]
    assert running, got
    for s in running:
        assert s["hit"] == 0, ("the running underline crossed a word not its own", s["words"], s)
