"""The check and the bang are written in the pane's margin, never on its number or its name (#330).

`shapes.js` `margin()` writes a check or a bang 14px in from the left of its anchor. Glass, voxel,
napkin and farmstead anchored those rows on `.tile ... .head`, whose box starts at the pane's content
edge, so the tick landed on `.head .n` and the agent's name; graph anchored on the pane, but a pane
had 10px of left padding. Now every check and bang row anchors on the pane, and each skin that
draws gives an open pane under ink a 26px left padding -- the margin -- in its own sheet (the legal
pad and the notebook pad further).
What is asserted, on one variant per changed module, at 1400px and 700px, under reduced motion:

* ink on: every check and bang stroke's bound (`Ink.inspect().layer.marks[].bounds`, inflated by
  half its tool's width) overlaps no text rect of its pane (`Range.getClientRects()`) by 6 px² or
  more, and the mark's anchor is the pane itself;
* a rail keeps the mid-rail mark;
* ink off: the plain bar (`box-shadow: inset 3px 0 0`) is on the pane, inside its 3px border, and
  crosses no text; the pane's first text starts at least 4px right of the bar.

The agents are put in their states by real events through the real server: an error
(`{"exit_code": 2}`), a supervised done and an unsupervised done, plus a rail that is done.
"""
from __future__ import annotations

import pytest

from agentdata.fleet import events as E, serve as S
from agentdata.fleet.registry import Registry

from test_fleet_desk_browser import launch_chromium
# The ink layer's own fixtures and helpers: the fleet directory, the desk's globals (autouse), the
# page, and the paper at rest; the notebook's supervised agents and its waits on the fold.
from test_fleet_ink import AT_REST, _choose, _open, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until, alive, finished  # noqa: F401 - fixtures are used by name
from test_fleet import make_project

#: One variant per module whose check or bang rows changed (the full sweep is #340's).
LOOKS = ("glass:smoke", "voxel:overworld", "napkin:diner", "farmstead:daytime", "graph:engineering")

#: The skins with no bang row: farmstead marks an error with a loop round the head (#332 moves it).
NO_BANG = {"farmstead"}

#: Each tool's base width (`pen.js` TOOLS): a stroke's bound is inflated by half of it.
TOOL_W = {"pencil": 1.9, "pen": 1.45, "red": 1.8, "green": 2.6, "marker": 4.6}

#: The error, the supervised done, the unsupervised done (open panes), and a rail that is done.
ERROR, SUPERVISED, UNSUPERVISED, RAIL = "alpha", "beta", "gamma", "delta"
OPEN = (ERROR, SUPERVISED, UNSUPERVISED)

WIDTHS = (1400, 700)

#: Every visible text rect of a pane, in viewport px, with the words it holds. Text parked off the
#: pane (a screen reader's words at left -9999px) is not on the pane, so it is not counted.
TEXTS = """(pane) => {
  const w = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT), out = [], p = pane.getBoundingClientRect();
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const word = n.data.trim();
    if (!word || !n.parentElement || getComputedStyle(n.parentElement).visibility !== 'visible') continue;
    const r = document.createRange();
    r.selectNodeContents(n);
    for (const q of r.getClientRects())
      if (q.width > 0 && q.height > 0 && q.right > p.left && q.left < p.right && q.bottom > p.top && q.top < p.bottom)
        out.push({ x: q.left, y: q.top, r: q.right, b: q.bottom, word: word.slice(0, 32),
                  el: n.parentElement.tagName.toLowerCase() + '.' + [...n.parentElement.classList].join('.') });
  }
  return out;
}"""

#: Ink on: each drawn check and bang, its anchor against its pane, and every text rect it covers.
MEASURE_ON = """(tw) => {
  const TEXTS = @TEXTS@, area = (a, b) =>
    Math.max(0, Math.min(a.r, b.r) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.y, b.y));
  const out = [];
  for (const m of Ink.inspect().layer.marks) {
    if (m.strikeOf || m.state !== 'drawn' || !['check', 'bang'].includes(m.shape) || !m.lane.startsWith('pane:')) continue;
    const repo = m.lane.slice(5), pane = document.querySelector(`.tile[data-repo="${repo}"]`);
    const p = pane.getBoundingClientRect(), h = (tw[m.tool] || 0) / 2, hits = [];
    const bounds = m.bounds.map(b => ({ x: b.x - h, y: b.y - h, r: b.r + h, b: b.b + h }));
    for (const t of TEXTS(pane)) for (const b of bounds) {
      const a = area(b, t);
      if (a >= 6) hits.push({ pad: getComputedStyle(pane).paddingLeft, word: t.word, el: t.el, area: Math.round(a * 10) / 10,
                             text: [t.x, t.y, t.r, t.b].map(v => Math.round(v * 10) / 10),
                             stroke: [b.x, b.y, b.r, b.b].map(v => Math.round(v * 10) / 10),
                             pane: [p.left, p.top].map(v => Math.round(v * 10) / 10) });
    }
    out.push({ repo, shape: m.shape, tool: m.tool, selector: m.selector, rail: pane.dataset.tier === 'rail',
               pad: parseFloat(getComputedStyle(pane).paddingLeft),
               box: m.box, pane: { x: p.left, y: p.top, w: p.width, h: p.height }, bounds, hits });
  }
  return out;
}""".replace("@TEXTS@", TEXTS)

#: Ink off: every element carrying a plain margin bar, and for each pane that has one, the bar's
#: strip (the padding box's first 3px) against the pane's text.
MEASURE_OFF = """() => {
  const TEXTS = @TEXTS@, bar = e => /inset/.test(getComputedStyle(e).boxShadow)
    && /\\b3px 0px 0px/.test(getComputedStyle(e).boxShadow);
  const carriers = [...document.querySelectorAll('#grid *')].filter(bar);
  const out = [];
  for (const pane of carriers) {
    if (!pane.matches('.tile')) { out.push({ stray: pane.className || pane.tagName }); continue; }
    const cs = getComputedStyle(pane), p = pane.getBoundingClientRect();
    const left = p.left + parseFloat(cs.borderLeftWidth);
    const strip = { x: left, y: p.top + parseFloat(cs.borderTopWidth), r: left + 3,
                    b: p.bottom - parseFloat(cs.borderBottomWidth) };
    const rects = TEXTS(pane);
    const hits = rects.filter(t => Math.min(strip.r, t.r) > Math.max(strip.x, t.x)
                                   && Math.min(strip.b, t.b) > Math.max(strip.y, t.y)).map(t => t.word);
    out.push({ repo: pane.dataset.repo, rail: pane.dataset.tier === 'rail', left, border: cs.borderLeftWidth,
               first: rects.length ? Math.min(...rects.map(t => t.x)) : null, hits });
  }
  return out;
}""".replace("@TEXTS@", TEXTS)


def margin_desk(tmp_path, fleet_home):
    """Four agents from real events: an error, and three that finish (`desk_states`): a supervised
    done, an unsupervised done (the chip says idle, the fold says done: `is-done`), and a rail."""
    names = OPEN + (RAIL,)
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    E.append(ERROR, [E.event(ERROR, "turn_started", {}, ticket="RDSD-1"),
                     E.event(ERROR, "turn_ended", {"turn": "1"}, ticket="RDSD-1"),
                     E.event(ERROR, "error", {"exit_code": 2}, ticket="RDSD-1")])
    S.arrange(order=list(names))
    # The rail is the one with no width.
    S.update_window("main", open=names[0], widths={n: 1 for n in OPEN})


def desk_states(page):
    """The three finish, once the page has the desk (the first fold writes each project's own phase
    into its stream), and then until the fold has put every state on its pane."""
    _until(page, f'.tile[data-repo="{ERROR}"].state-error')
    for name in (SUPERVISED, UNSUPERVISED, RAIL):
        _emit(page, name, ("phase_changed", {"from": "build", "to": "done"}))
    _until(page, f'.tile[data-repo="{SUPERVISED}"].state-done')
    _until(page, f'.tile[data-repo="{UNSUPERVISED}"].is-done:not(.state-done)')
    _until(page, f'.tile[data-repo="{RAIL}"][data-tier="rail"].is-done')


def _sheet(skin):
    return (f"[...document.querySelectorAll('link[data-skin]')].some(l => l.sheet"
            f" && l.href.includes('/static/skins/{skin}/skin.css'))")


#: What a look that did not come to rest shows: its table, the panes' classes and the marks.
SEEN = """() => ({ table: Ink.inspect().table, busy: Ink.inspect().layer && Ink.inspect().layer.busy,
  panes: [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo + ' ' + (t.dataset.tier || '') + ' ' + t.className),
  marks: Ink.inspect().layer ? Ink.inspect().layer.marks.filter(m => ['check', 'bang'].includes(m.shape))
    .map(m => [m.lane, m.shape, m.state, m.drawn, m.strikeOf]) : null })"""


def choose_on(page, look):
    """Choose a look and wait, on conditions only, for its sheet, its table and its checks and bang
    drawn, with the paper at rest. While the table is not the look yet, the page is asked to look
    again, as `_until` does: a `/api/fleet` answer already in flight when the choice was written
    carries the previous skin, and puts it back after the stream's `theme` event (seen once at 700px)."""
    skin = look.split(":")[0]
    _choose(page, look)
    checks = " && ".join(f"ok('check', '{r}')" for r in (SUPERVISED, UNSUPERVISED, RAIL))
    bang = "true" if skin in NO_BANG else f"ok('bang', '{ERROR}')"
    try:
        page.wait_for_function(f"""() => {{
      if (Ink.inspect().table !== '{look}') {{ refresh(); return false; }}
      if (!({_sheet(skin)}) || !({AT_REST})()) return false;
      const ms = Ink.inspect().layer.marks;
      const ok = (shape, repo) => ms.some(m => m.shape === shape && m.lane === 'pane:' + repo
                                             && !m.strikeOf && m.state === 'drawn' && m.drawn === 1);
      return {checks} && {bang};
    }}""", timeout=30000, polling=250)
    except Exception as e:           # say what was missing: the look, its table and its marks
        raise AssertionError((look, page.evaluate(SEEN))) from e


#: Ink off, the bars at rest (#451): the unsupervised pane wears the whole 3px bar, and no pane is
#: part-way through a transition. The reduced-motion block gives every element a 0.01ms transition
#: of `all` (tests/test_fleet_gutters.py says the same of widths), so when the fallback sheet puts a
#: bar on, a pane's computed box-shadow starts at `rgba(0, 0, 0, 0) 0px 0px 0px 0px inset`. That is
#: the transition's first frame, not the bar, and it held for a whole measurement on a loaded runner.
#: `/inset/` alone accepted it.
OFF_AT_REST = f"""() => {{
  const panes = [...document.querySelectorAll('#grid .tile')];
  const moving = panes.some(t => t.getAnimations().some(a => a.playState === 'running'));
  const cs = getComputedStyle(document.querySelector('.tile[data-repo="{UNSUPERVISED}"]'));
  return !moving && /inset/.test(cs.boxShadow) && /\\b3px 0px 0px/.test(cs.boxShadow);
}}"""


def choose_off(page, look):
    skin = look.split(":")[0]
    _choose(page, look)
    page.wait_for_function(f"""() => (Ink.inspect().table === '{look}' || (refresh(), false)) && Ink.inspect().plain
      && ({_sheet(skin)}) && document.body.classList.contains('ink-off') && ({OFF_AT_REST})()""",
                           timeout=30000, polling=250)


def measure_on(page):
    return page.evaluate(MEASURE_ON, TOOL_W)


#: Ink off, for a failure message only: every pane's classes, tier and computed box-shadow, so a
#: pane with no bar says what it was wearing when it was measured.
PANES_OFF = """() => [...document.querySelectorAll('#grid .tile')].map(t => ({
  repo: t.dataset.repo, tier: t.dataset.tier || '', cls: t.className, shadow: getComputedStyle(t).boxShadow }))"""


def measure_off(page):
    return page.evaluate(MEASURE_OFF)


def check_on(look, width, marks):
    """What the margin promises with ink on: nothing written over the pane's words, the anchor the
    pane, and a rail's mark down its middle."""
    skin = look.split(":")[0]
    where = f"{look} @ {width}px"
    shown = {(m["shape"], m["repo"]) for m in marks}
    want = {("check", r) for r in (SUPERVISED, UNSUPERVISED, RAIL)}
    if skin not in NO_BANG:
        want.add(("bang", ERROR))
    assert want <= shown, (where, sorted(shown))
    for m in marks:
        row = f"{where}: {m['shape']} ({m['selector']}) on {m['repo']}"
        box, pane = m["box"], m["pane"]
        assert abs(box["x"] - pane["x"]) < 1 and abs(box["w"] - pane["w"]) < 1, \
            (row, "anchored on the pane", box, pane)
        if m["rail"]:
            xs = [b["x"] for b in m["bounds"]] + [b["r"] for b in m["bounds"]]
            mid = (min(xs) + max(xs)) / 2
            assert abs(mid - (pane["x"] + pane["w"] / 2)) <= 3, (row, "mid-rail", mid, pane)
            continue
        assert m["pad"] >= 26, (row, "the pane's margin under ink is at least 26px", m["pad"])
        assert not m["hits"], (row, "covers", m["hits"])


def check_off(look, width, bars, panes=()):
    where = f"{look} @ {width}px, ink off"
    skin = look.split(":")[0]
    assert not [b for b in bars if "stray" in b], (where, "a margin bar off the pane", bars)
    got = {b["repo"] for b in bars}
    want = {SUPERVISED, UNSUPERVISED, RAIL} | (set() if skin in NO_BANG else {ERROR})
    assert want <= got, (where, sorted(got), panes)
    for b in bars:
        if b["rail"]:
            continue
        assert b["border"] == "3px", (where, b)
        assert not b["hits"], (where, b["repo"], "the bar crosses", b["hits"])
        assert b["first"] is not None and b["first"] >= b["left"] + 3 + 4, (where, b)


@pytest.mark.browser
@pytest.mark.parametrize("width", WIDTHS)
def test_check_and_bang_are_written_in_the_panes_margin_with_ink_on(fleet_home, tmp_path, alive, finished, width):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(SUPERVISED)
    finished.add(SUPERVISED)
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(OPEN), width=width, reduced=True)
            desk_states(page)
            for look in LOOKS:
                choose_on(page, look)
                seen[look] = measure_on(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for look, marks in seen.items():
        check_on(look, width, marks)


@pytest.mark.browser
@pytest.mark.parametrize("width", WIDTHS)
def test_the_plain_margin_bar_is_on_the_pane_and_off_the_words_with_ink_off(fleet_home, tmp_path, alive, finished, width):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.add(SUPERVISED)
    finished.add(SUPERVISED)
    margin_desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=off", panes=len(OPEN), width=width, reduced=True)
            desk_states(page)
            for look in LOOKS:
                choose_off(page, look)
                seen[look] = (measure_off(page), page.evaluate(PANES_OFF))
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for look, (bars, panes) in seen.items():
        check_off(look, width, bars, panes)
