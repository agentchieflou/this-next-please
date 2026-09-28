"""What the HIG guard reads off a desk page, and how it judges it (#340). A helper module, not a
test file: `tests/test_fleet_ink_bounds.py` is the guard, and #341's pixel pass reads the same runs.

Ink on, the bounds test measures each drawn mark on its own pane (`MEASURE` there). Ink off there is
no canvas: the skin's table is the plain sheet (`ink.js` `PLAIN`), and a row whose plain rule is an
outline (`outline`, `loop`, `ellipse`) draws a ring `outline-offset` out from its anchor's border
box, `outline-width` thick. `PLAIN_RINGS` reads those rings off the page's own adopted sheet and
computed styles, `TEXT_RUNS` every word a person can see, and `ring_collisions` is where a ring
lands on words, by 6 px² or more.
"""
from __future__ import annotations

from agentdata.fleet import skins

#: A ring or a stroke on a word by this much area is on it (#340: never raised to get green).
AREA = 6


def every_look() -> list[str]:
    """`<skin>:<variant>` for every variant skins.py gives every skin: the full sweep."""
    return [f"{name}:{variant}" for name, variant, _ in skins.every_variant()]


#: Every run of visible text on the page, one per client rect: skipping `script`, `style`, the ink
#: canvas, `[hidden]` and anything `checkVisibility` says is not shown; rects under 3x6px or off
#: the viewport dropped; kept only where the word is what is on top at its centre (its element, an
#: ancestor or a descendant). `label` is `[repo] tag.class`.
TEXT_RUNS = """() => {
  const out = [], vw = innerWidth, vh = innerHeight;
  const skip = el => el.closest('script, style, #ink, [hidden]')
    || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const el = n.parentElement, text = n.data.trim();
    if (!text || !el || skip(el)) continue;
    const r = document.createRange();
    r.selectNodeContents(n);
    for (const q of r.getClientRects()) {
      if (q.width < 3 || q.height < 6 || q.right <= 0 || q.bottom <= 0 || q.left >= vw || q.top >= vh) continue;
      const top = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
      if (!top || !(top === el || top.contains(el) || el.contains(top))) continue;
      const tile = el.closest('.tile');
      out.push({ text: text.slice(0, 32), x: q.left, y: q.top, w: q.width, h: q.height,
                 label: (tile ? '[' + tile.dataset.repo + '] ' : '') + el.tagName.toLowerCase()
                        + [...el.classList].map(c => '.' + c).join('') });
    }
  }
  return out;
}"""

#: Ink off: every element a rule of the plain sheet outlines, with its box and its outline's offset
#: and width as computed. A rule is the table's row, `body.ink-off :is(<selector>)`; the sheet is
#: adopted, or a `<style data-ink="plain">` where constructed sheets are missing (ink.js). The rule
#: is read from its text: `outline: 2px solid var(...)` is a shorthand with a `var()`, whose
#: longhands (`style.outlineStyle`) read empty until the element computes them.
PLAIN_RINGS = """() => {
  const out = [], plain = document.querySelector('style[data-ink="plain"]');
  const sheets = [...document.adoptedStyleSheets].concat(plain && plain.sheet ? [plain.sheet] : []);
  for (const sheet of sheets) for (const rule of sheet.cssRules) {
    if (!rule.selectorText || !rule.style || !/(^|[;\\s])outline\\s*:/.test(rule.style.cssText)) continue;
    for (const el of document.querySelectorAll(rule.selectorText)) {
      const cs = getComputedStyle(el), b = el.getBoundingClientRect();
      if (cs.outlineStyle === 'none' || !(b.width || b.height)) continue;
      const tile = el.closest('.tile');
      out.push({ selector: rule.selectorText, repo: tile ? tile.dataset.repo : '',
                 box: { x: b.left, y: b.top, r: b.right, b: b.bottom },
                 offset: parseFloat(cs.outlineOffset) || 0, width: parseFloat(cs.outlineWidth) || 0 });
    }
  }
  return out;
}"""


#: Ink off, the plain sheet is in force once nothing on the page is still transitioning: a row's
#: outline arriving mid-transition reads its initial width and offset (`medium`, 0) in between.
PLAIN_AT_REST = """() => !document.getAnimations().some(a => a.playState === 'running')"""


def inter(a, b):
    """The area two (x, y, r, b) rects share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def ring_strips(ring):
    """A plain ring's four sides, as rects: `offset` out from the box, `width` thick."""
    b, o, w = ring["box"], ring["offset"], ring["width"]
    x0, y0, x1, y1 = b["x"] - o - w, b["y"] - o - w, b["r"] + o + w, b["b"] + o + w
    return [(x0, y0, x1, y0 + w), (x0, y1 - w, x1, y1),
            (x0, y0 + w, x0 + w, y1 - w), (x1 - w, y0 + w, x1, y1 - w)]


def ring_collisions(rings, runs):
    """(ring, run, area) for every plain ring on a word by `AREA` px² or more. The ring is outside
    its anchor's box, so the anchor's own words are never under it; any word it covers is another's."""
    for ring in rings:
        strips = ring_strips(ring)
        for t in runs:
            rr = (t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"])
            area = sum(inter(rr, s) for s in strips)
            if area >= AREA:
                yield ring, t, round(area, 1)
