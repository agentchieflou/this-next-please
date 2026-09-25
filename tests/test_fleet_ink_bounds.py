"""A skin's own marks keep inside their pane and off other elements' words (#332).

#331 made the layer keep a mark in its pane (the clip, the outline snap, the underline's place);
this is the skins' half. Each skin's table used to anchor strokes where they landed on other
elements' words: napkin's pane outlines and error loop padded outside the pane, the stale outline
round `.oldsession` over the chip and its age, voxel's needs-you underline through the chip row,
farmstead's error loop round `.head` across the chip row, and the legal pad's running tail -- drawn
by the skin itself, so the layer never placed it -- through the chip and the age.

What is asserted, on one look per changed or affected module (the full sweep is #340's), at 1400px
and 700px, ink on, under reduced motion, with four agents put in their states by real events (a
blocking question, a supervised running turn, an error, and a supervised done whose session began
on no recorded install, so its stale note shows):

* every stroke's bound (`Ink.inspect().layer.marks[].bounds`, inflated by half its tool's width)
  is at most 2px outside its pane and inside the viewport, and no stroke of a mark on a pane is cut
  away whole by the pane's clip; statically, every `outline` and `loop` row on a pane has a pad of
  0 or less;
* no `outline`, `loop`, `ellipse`, `check`, `bang`, `arrow` or `divider` stroke overlaps another
  element's text by 6 px² or more -- loops and ellipses measured on their ring, arrows on their
  curve -- and an `underline` or `strike` overlaps no word but its own (under 1 px²);
* legalpad:canary: each running pane's `inspect().panes[].tailBox`, inflated by 1px, overlaps no
  text rect by 6 px² or more.
"""
from __future__ import annotations

import os
import re

import pytest

from agentdata.fleet import events as E, fingerprint as FP, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import AT_REST, _choose, _open, _own_desk_globals, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until, alive, finished  # noqa: F401 - fixtures are used by name

#: One variant per changed or affected module.
LOOKS = ("glass:smoke", "voxel:overworld", "napkin:diner", "farmstead:daytime", "legalpad:canary",
         "notebook:light", "graph:engineering")

WIDTHS = (1400, 700)

#: Each tool's base width (`pen.js` TOOLS): a stroke's bound is its centre line, inflated by half of it.
TOOL_W = {"pencil": 1.9, "pen": 1.45, "red": 1.8, "green": 2.6, "marker": 4.6, "highlighter": 18}

NOW = {"version": "0.14.0", "commit": "cccccccccccc", "skills": "333333333333"}

#: A blocking question, a running turn, an error, and a supervised done that is stale.
ASKS, RUNS, BROKE, FIN = "asks", "runs", "broke", "fin"
NAMES = (ASKS, RUNS, BROKE, FIN)

#: Lines the running turn writes on the legal pad: past `TAIL_MAX / GROW`, so the tail is at its longest.
TURN_LINES = 24

#: Every visible text rect of a root, in viewport px, with the element that holds it: cut to the
#: root and to every ancestor that scrolls, so a transcript line scrolled out of view is not a word
#: on the pane.
TEXTS = """(root) => {
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), out = [], p = root.getBoundingClientRect();
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const word = n.data.trim();
    if (!word || !n.parentElement || getComputedStyle(n.parentElement).visibility !== 'visible') continue;
    let v = { x: p.left, y: p.top, r: p.right, b: p.bottom };
    for (let a = n.parentElement; a && a !== root; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (!/(auto|scroll|hidden|clip)/.test(cs.overflowX + ' ' + cs.overflowY)) continue;
      const q = a.getBoundingClientRect();
      v = { x: Math.max(v.x, q.left), y: Math.max(v.y, q.top), r: Math.min(v.r, q.right), b: Math.min(v.b, q.bottom) };
    }
    const r = document.createRange();
    r.selectNodeContents(n);
    for (const q of r.getClientRects()) {
      const t = { x: Math.max(q.left, v.x), y: Math.max(q.top, v.y), r: Math.min(q.right, v.r), b: Math.min(q.bottom, v.b) };
      if (q.width > 0 && q.height > 0 && t.r > t.x && t.b > t.y)
        out.push(Object.assign(t, { word: word.slice(0, 32), node: n.parentElement,
                  el: n.parentElement.tagName.toLowerCase() + '.' + [...n.parentElement.classList].join('.') }));
    }
  }
  return out;
}"""

#: Every drawn mark in a pane: its bounds, its anchor, the pane, and every word of another element
#: it covers. Rings and curves are sampled on a half-pixel grid inside each text rect.
MEASURE = """(tw) => {
  const TEXTS = @TEXTS@;
  const box = (a, b) =>
    Math.max(0, Math.min(a.r, b.r) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.y, b.y));
  const seg = (p, a, b) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
    const t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0;
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  };
  // The area of `t` within `h` of the polyline `pts`, on a half-pixel grid.
  const near = (pts, h, t) => {
    let n = 0;
    for (let y = t.y + 0.25; y < t.b; y += 0.5) for (let x = t.x + 0.25; x < t.r; x += 0.5) {
      for (let i = 1; i < pts.length; i++) if (seg([x, y], pts[i - 1], pts[i]) <= h) { n++; break; }
    }
    return n / 4;
  };
  const ring = b => [[b.x, b.y], [b.r, b.y], [b.r, b.b], [b.x, b.b], [b.x, b.y]];
  const oval = b => {
    const cx = (b.x + b.r) / 2, cy = (b.y + b.b) / 2, rx = (b.r - b.x) / 2, ry = (b.b - b.y) / 2, pts = [];
    for (let i = 0; i <= 72; i++) pts.push([cx + Math.cos(i / 36 * Math.PI) * rx, cy + Math.sin(i / 36 * Math.PI) * ry]);
    return pts;
  };
  // shapes.js `arrow`, from the anchor's box to its target's: the curve as a polyline.
  const curve = (n, v) => {
    const x0 = n.x - 5, y0 = n.y + n.h * 0.5, vr = v.x + v.w;
    const x1 = Math.abs(v.x + v.w / 2 - x0) < 12 ? v.x + v.w / 2 : Math.min(Math.max(v.x + 8, x0 - 24), vr - 4);
    const y1 = v.y > y0 ? v.y - 3 : v.y + v.h + 3, mx = (x0 + x1) / 2 - 5, my = (y0 + y1) / 2 + 3, pts = [];
    for (let i = 0; i <= 24; i++) {
      const t = i / 24, u = 1 - t;
      pts.push([u * u * x0 + 2 * u * t * mx + t * t * x1, u * u * y0 + 2 * u * t * my + t * t * y1]);
    }
    return pts;
  };
  const out = [];
  for (const m of Ink.inspect().layer.marks) {
    if (m.strikeOf || m.state !== 'drawn' || !m.visible || !m.lane.startsWith('pane:')) continue;
    const repo = m.lane.slice(5), pane = document.querySelector(`.tile[data-repo="${repo}"]`);
    const p = pane.getBoundingClientRect(), h = (tw[m.tool] || 2) / 2;
    const anchor = [pane, ...pane.querySelectorAll('*')].find(e => e.matches(m.selector)
      && Math.abs(e.getBoundingClientRect().left - m.box.x) < 1 && Math.abs(e.getBoundingClientRect().top - m.box.y) < 1);
    const bounds = m.bounds.map(b => ({ x: b.x - h, y: b.y - h, r: b.r + h, b: b.b + h, c: b }));
    const hits = [];
    const words = TEXTS(pane).filter(t => !anchor || !anchor.contains(t.node));
    bounds.forEach((b, i) => {
      for (const t of words) {
        let a;
        if (m.shape === 'loop') a = near(ring(b.c), h, t);
        else if (m.shape === 'ellipse') a = near(oval(b.c), h, t);
        else if (m.shape === 'arrow' && i === 0) {
          const to = anchor && anchor.closest('.tile').querySelector(@TO@[m.selector] || '.runline');
          const v = to && to.getBoundingClientRect();
          a = v ? near(curve(m.box, { x: v.left, y: v.top, w: v.width, h: v.height }), h, t) : box(b, t);
        } else a = box(b, t);
        if (a > 0.5) hits.push({ word: t.word, el: t.el, area: Math.round(a * 10) / 10,
                                 text: [t.x, t.y, t.r, t.b].map(v => Math.round(v * 10) / 10),
                                 stroke: [b.x, b.y, b.r, b.b].map(v => Math.round(v * 10) / 10) });
      }
    });
    out.push({ repo, shape: m.shape, tool: m.tool, selector: m.selector, strokes: m.strokes, hw: h,
               anchored: !!anchor, onPane: anchor === pane,
               pane: { x: p.left, y: p.top, r: p.right, b: p.bottom },
               view: { r: innerWidth, b: innerHeight },
               bounds: bounds.map(b => ({ x: b.x, y: b.y, r: b.r, b: b.b, c: b.c })), hits });
  }
  return out;
}""".replace("@TEXTS@", TEXTS).replace("@TO@", '{".tile .oldsession:not([hidden])": ".runline"}')

#: The legal pad's running tails, each inflated by 1px, against every text rect of its pane.
TAILS = """() => {
  const TEXTS = @TEXTS@, out = [];
  for (const p of window.__legalpad.inspect().panes) {
    if (!p.running) continue;
    const pane = document.querySelector(`.tile[data-repo="${p.repo}"]`), b = p.tailBox;
    const t0 = b ? { x: b.x - 1, y: b.y - 1, r: b.x + b.w + 1, b: b.y + b.h + 1 } : null;
    const hits = t0 ? TEXTS(pane).map(t => ({ word: t.word, el: t.el,
      area: Math.max(0, Math.min(t0.r, t.r) - Math.max(t0.x, t.x)) * Math.max(0, Math.min(t0.b, t.b) - Math.max(t0.y, t.y)) }))
      .filter(h => h.area >= 6) : [];
    out.push({ repo: p.repo, lines: p.lines, tail: p.tail, tailBox: b, hits });
  }
  return out;
}""".replace("@TEXTS@", TEXTS)


SKINS = os.path.join(os.path.dirname(S.__file__), "static", "ink", "skins")

#: A row of a skin's mark table, as written: `{ selector: "...", ... }` on one level of braces.
ROW = re.compile(r"\{[^{}]*?selector:\s*\"((?:[^\"\\]|\\.)*)\"[^{}]*\}")


def on_the_pane(selector: str) -> bool:
    """`.tile.state-error`, `.tile:has(...)`: the pane itself, no descendant combinator outside a
    parenthesis."""
    flat = selector.replace('\\"', '"')
    while "(" in flat:
        flat = re.sub(r"\([^()]*\)", "", flat)
    return flat.startswith(".tile") and " " not in flat.strip() and "," not in flat


def test_every_outline_and_loop_on_a_pane_is_padded_inside_it():
    """A pane's `outline` or `loop` with a positive pad is drawn over the pane's border and in the
    gutter, where the layer's clip (#331) cuts it away: its pad is 0 or less, so the stroke and
    half its width are inside (napkin's idle outline, error loop and stale outline were not)."""
    seen, bad = 0, []
    for name in sorted(os.listdir(SKINS)):
        src = open(os.path.join(SKINS, name), encoding="utf-8").read()
        for m in ROW.finditer(src):
            row, selector = m.group(0), m.group(1)
            shape = re.search(r'shape:\s*"(\w+)"', row)
            if not shape or shape.group(1) not in ("outline", "loop") or not on_the_pane(selector):
                continue
            seen += 1
            pad = re.search(r"pad:\s*(-?[\d.]+)", row)
            if pad and float(pad.group(1)) > 0:
                bad.append((name, selector, shape.group(1), float(pad.group(1))))
    assert seen >= 6, seen
    assert not bad, bad


def bounds_desk(tmp_path, fleet_home, monkeypatch):
    """Four agents from real events. The installed skills are pinned, and every session but the
    finished one began on them; the finished one's `started` carries no install, so it is stale."""
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    FP.forget()
    for name in NAMES:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        begun = {"pid": 1} if name == FIN else {"pid": 1, "new": True, "session": "", "install": dict(NOW)}
        E.append(name, [E.event(name, "started", begun, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1")])
    E.append(ASKS, [E.event(ASKS, "question_opened", {"id": "q1", "question": "Which branch should I use?",
                                                      "choices": ["main", "dev"]}, ticket="RDSD-1"),
                    E.event(ASKS, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    E.append(RUNS, [E.event(RUNS, "turn_started", {}, ticket="RDSD-1")])
    E.append(BROKE, [E.event(BROKE, "error", {"exit_code": 2}, ticket="RDSD-1")])
    E.append(FIN, [E.event(FIN, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    S.arrange(order=list(NAMES))
    S.update_window("main", open=NAMES[0], widths={n: 1 for n in NAMES})


def desk_states(page):
    """The finished agent finishes once the page has the desk (the first fold writes each
    project's own phase into its stream), and then until the fold has put every state on its pane."""
    _until(page, f'.tile[data-repo="{BROKE}"].state-error')
    _emit(page, FIN, ("phase_changed", {"from": "build", "to": "done"}))
    _until(page, f'.tile[data-repo="{ASKS}"].needs-human')
    _until(page, f'.tile[data-repo="{RUNS}"].state-running')
    _until(page, f'.tile[data-repo="{BROKE}"].state-error')
    _until(page, f'.tile[data-repo="{FIN}"].state-done')
    _until(page, f'.tile[data-repo="{FIN}"] .oldsession:not([hidden])')


def _sheet(skin):
    return (f"[...document.querySelectorAll('link[data-skin]')].some(l => l.sheet"
            f" && l.href.includes('/static/skins/{skin}/skin.css'))")


SEEN = """() => ({ table: Ink.inspect().table, busy: Ink.inspect().layer && Ink.inspect().layer.busy,
  panes: [...document.querySelectorAll('#grid .tile')].map(t => t.dataset.repo + ' ' + t.className),
  marks: Ink.inspect().layer ? Ink.inspect().layer.marks.map(m => [m.lane, m.selector, m.shape, m.state, m.drawn]) : null })"""


def choose(page, look):
    """Choose a look and wait, on conditions only, for its table, its sheet, every pane marked and
    the paper at rest. While the table is not the look yet, the page is asked to look again: an
    answer already in flight when the choice was written carries the previous skin."""
    skin = look.split(":")[0]
    _choose(page, look)
    # Every skin marks an error and a done (voxel marks a running agent on its stack alone).
    panes = " && ".join(f"ms.some(m => m.lane === 'pane:{r}' && !m.strikeOf && m.state === 'drawn')"
                        for r in (BROKE, FIN))
    try:
        page.wait_for_function(f"""() => {{
      if (Ink.inspect().table !== '{look}') {{ refresh(); return false; }}
      if (!({_sheet(skin)}) || !({AT_REST})()) return false;
      const ms = Ink.inspect().layer.marks;
      return {panes};
    }}""", timeout=30000, polling=250)
    except Exception as e:
        raise AssertionError((look, page.evaluate(SEEN))) from e
    # The sheet is in before its rules are always in force: a skin's head `row-gap` was seen at
    # app.css's 2px on the first read after the sheet loaded and at the skin's 8px on the next
    # (Chromium 153, farmstead after napkin). So the panes' heads, and the paper, hold still across
    # two looks first.
    page.evaluate("() => { window.__heads = ''; }")
    page.wait_for_function(f"""() => {{
      const sig = [...document.querySelectorAll('#grid .tile .head > *')].map(k => {{
        const q = k.getBoundingClientRect(); return [q.left, q.top, q.width, q.height].map(Math.round).join(','); }}).join(';');
      const same = sig === window.__heads;
      window.__heads = sig;
      return same && ({AT_REST})();
    }}""", timeout=15000, polling=250)
    if skin == "legalpad":
        page.evaluate("async () => { window.__legalpad = await import(q('/static/ink/skins/legalpad.js')); }")
        page.wait_for_function("() => window.__legalpad.inspect().panes.some(p => p.running && p.shown)",
                               timeout=15000)
        for i in range(TURN_LINES):
            E.append(RUNS, [E.event(RUNS, "assistant_text", {"text": f"step {i}"}, ticket="RDSD-1")])
        page.evaluate("() => refresh()")
        page.wait_for_function(f"""() => {{ const p = window.__legalpad.inspect().panes.find(p => p.repo === '{RUNS}');
          if (p && p.lines >= {TURN_LINES}) return ({AT_REST})(); refresh(); return false; }}""",
                               timeout=20000, polling=250)


def problems(look, width, marks):
    """Every way a look's marks leave their pane or land on another element's words, each naming
    the skin and variant, the row, the word and the area."""
    where, out = f"{look} @ {width}px", []
    if not marks:
        return [(where, "no marks drawn")]
    for m in marks:
        row = f"{where}: {m['shape']} {m['tool']} ({m['selector']}) on {m['repo']}"
        p, v = m["pane"], m["view"]
        for b in m["bounds"]:
            off = max(p["x"] - b["x"], p["y"] - b["y"], b["r"] - p["r"], b["b"] - p["b"])
            if off > 2:
                out.append((row, "more than 2px outside its pane", round(off, 1)))
            if b["x"] < -0.5 or b["y"] < -0.5 or b["r"] > v["r"] + 0.5 or b["b"] > v["b"] + 0.5:
                out.append((row, "outside the viewport", b, v))
        if m["onPane"] and len(m["bounds"]) != m["strokes"]:
            # The pane's clip is its border box inset 1px (#331): a stroke drawn wholly outside it
            # is on the page's gutter, where nobody sees it.
            out.append((row, "a stroke cut away whole by the pane's clip", len(m["bounds"]), m["strokes"]))
        if m["shape"] in ("lines", "write"):
            continue
        limit = 1 if m["shape"] in ("underline", "strike") else 6
        for h in m["hits"]:
            if h["area"] >= limit:
                out.append((row, "covers", h["word"], h["el"], h["area"]))
    return out


def tail_problems(width, tails):
    where = f"legalpad:canary @ {width}px"
    if not tails:
        return [(where, "no running pane")]
    out = []
    for t in tails:
        if not t["tailBox"] or t["lines"] < TURN_LINES:
            out.append((where, "no tail at its length", t))
        for h in t["hits"]:
            out.append((where, f"the running tail on {t['repo']} covers", h["word"], h["el"],
                        round(h["area"], 1), t["tailBox"]))
    return out


@pytest.mark.browser
@pytest.mark.parametrize("width", WIDTHS)
def test_skin_marks_keep_inside_their_pane_and_off_other_words(fleet_home, tmp_path, monkeypatch, alive,
                                                               finished, width):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    alive.update({RUNS, FIN})
    finished.add(FIN)
    bounds_desk(tmp_path, fleet_home, monkeypatch)
    server, token, port = _serve()
    seen, tails = {}, None
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(NAMES), width=width, reduced=True)
            desk_states(page)
            for look in LOOKS:
                choose(page, look)
                seen[look] = page.evaluate(MEASURE, TOOL_W)
                if look.startswith("legalpad"):
                    tails = page.evaluate(TAILS)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    found = [x for look, marks in seen.items() for x in problems(look, width, marks)]
    found += tail_problems(width, tails)
    assert not found, "\n".join(map(str, found))
