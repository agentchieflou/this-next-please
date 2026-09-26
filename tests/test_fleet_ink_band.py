"""No band missing under the panes, and no opaque strip over the drawn page (#337).

With the renew strip showing (a session begun on older skills), headless Chromium composited the
canvas behind the page with a band missing along the foot of the panes -- about y 787-858 at
1400x900, the strip's own rectangle mirrored -- while the drawing buffer, read back, was whole.
Farmstead alone was right, because its sheet gave the clear header its own compositor layer. Now
every skin that draws does the same in its own sheet, and clears the renew and away strips there,
keyed on `body[data-skin="<skin>"]:not(.ink-off)` as #441 keyed the ink margin: a rule keyed on
`body:has(> #ink[data-skin])` that starts matching late is not re-applied to the page by Chromium
153.

What is asserted, per look, at 1400x900 under reduced motion, with ink on and the paper at rest:
points in each pane's lowest 80px that no text or control covers are sampled from a screenshot of
the page, then from one with everything but the canvas hidden; every pair is within 12 per RGB
channel. And the selection ring survives: a selected pane under glass:smoke still has a
box-shadow.
"""
from __future__ import annotations

import pytest

from agentdata.fleet import events as E, fingerprint as FP, serve as S
from agentdata.fleet.registry import Registry

from test_fleet_desk_browser import launch_chromium
from test_fleet_desk_glass import _png_pixels
from test_fleet_ink import AT_REST, _choose, _open, _serve, _stop, fleet_home  # noqa: F401
from test_fleet import make_project

LOOKS = ("glass:smoke", "legalpad:canary", "voxel:overworld", "napkin:diner")

#: What is installed now; three sessions began on it, and one began before the fleet recorded any.
NOW = {"version": "0.13.2", "commit": "bbbbbbbbbbbb", "skills": "222222222222"}
FRESH, STALE = ("alpha", "beta", "gamma"), "delta"
NAMES = FRESH + (STALE,)

WIDTH, HEIGHT = 1400, 900
TOLERANCE = 12

#: Points in each pane's lowest 80px, clear of every text rect and control (inflated by 6px) and
#: of the pane's own edges: what shows there is the canvas, through a clear pane.
POINTS = """() => {
  const inflate = (r, d) => ({ x: r.left - d, y: r.top - d, r: r.right + d, b: r.bottom + d });
  const covers = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (!n.data.trim() || !n.parentElement) continue;
    const r = document.createRange();
    r.selectNodeContents(n);
    for (const q of r.getClientRects()) if (q.width > 0 && q.height > 0) covers.push(inflate(q, 6));
  }
  for (const c of document.querySelectorAll('button, input, select, textarea, a, kbd, .chip, svg, img, canvas:not(#ink)')) {
    const q = c.getBoundingClientRect();
    if (q.width > 0 && q.height > 0) covers.push(inflate(q, 6));
  }
  const out = [];
  for (const pane of document.querySelectorAll('#grid .tile')) {
    const p = pane.getBoundingClientRect(), cs = getComputedStyle(pane);
    const x0 = p.left + parseFloat(cs.borderLeftWidth) + 12, x1 = p.right - 12;
    const y1 = Math.min(p.bottom, innerHeight) - 6, y0 = Math.min(p.bottom, innerHeight) - 80;
    for (let y = y0; y <= y1; y += 8) for (let x = x0; x <= x1; x += 24) {
      if (covers.some(c => x >= c.x && x <= c.r && y >= c.y && y <= c.b)) continue;
      out.push({ repo: pane.dataset.repo, x: Math.round(x), y: Math.round(y) });
    }
  }
  return out;
}"""

#: The page hidden but for its canvas, and the paper still at rest two frames later.
HIDE = """() => new Promise(done => {
  const s = document.createElement('style');
  s.id = 'band-hide';
  s.textContent = 'body > :not(#ink) { visibility: hidden !important; }';
  document.head.appendChild(s);
  requestAnimationFrame(() => requestAnimationFrame(() => done(true)));
})"""
SHOW = "() => { const s = document.getElementById('band-hide'); if (s) s.remove(); }"
TWO_FRAMES = "() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))"


def band_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    for name in NAMES:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        data = {"pid": 1} if name == STALE else {"pid": 1, "install": dict(NOW)}
        E.append(name, [E.event(name, "started", data, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    S.arrange(order=list(NAMES))
    S.update_window("main", open=NAMES[0], widths={n: 1 for n in NAMES})
    S.select(NAMES[0])


def _sheet(skin):
    return (f"[...document.querySelectorAll('link[data-skin]')].some(l => l.sheet"
            f" && l.href.includes('/static/skins/{skin}/skin.css'))")


def choose(page, look):
    skin = look.split(":")[0]
    _choose(page, look)
    page.wait_for_function(f"""() => (Ink.inspect().table === '{look}' || (refresh(), false))
      && ({_sheet(skin)}) && document.body.dataset.skin === '{skin}' && ({AT_REST})()""",
                           timeout=30000, polling=250)
    page.evaluate(TWO_FRAMES)
    page.wait_for_function(AT_REST, timeout=20000)


def sample(page, points):
    """Each point's RGB, from one screenshot of the whole viewport. Not a clip of the rows the points
    span: Chromium captures a clip through another path, and that path composited the page whole
    while the screen -- and a full screenshot -- showed the band."""
    w, h, bpp, rows = _png_pixels(page.screenshot())
    return [tuple(rows[p["y"]][p["x"] * bpp:p["x"] * bpp + 3]) for p in points]


@pytest.mark.browser
def test_the_drawn_page_reaches_the_foot_of_the_panes_with_the_renew_strip_showing(
        fleet_home, tmp_path, monkeypatch):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    band_desk(tmp_path, monkeypatch)
    server, token, port = _serve()
    seen, ring = {}, None
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(NAMES),
                                    width=WIDTH, height=HEIGHT, reduced=True)
            page.wait_for_function(
                "() => { const s = document.getElementById('renew-strip');"
                " if (s && !s.hidden && s.getBoundingClientRect().height > 0) return true; refresh(); return false; }",
                timeout=15000, polling=250)
            for look in LOOKS:
                choose(page, look)
                if look == "glass:smoke":
                    ring = page.evaluate("""() => { const t = document.querySelector('#grid .tile.is-selected');
                      return t ? getComputedStyle(t).boxShadow : null; }""")
                points = page.evaluate(POINTS)
                assert points, (look, "no point in the panes' lowest 80px is clear of words")
                shown = sample(page, points)
                page.evaluate(HIDE)
                page.wait_for_function(AT_REST, timeout=20000)
                canvas = sample(page, points)
                page.evaluate(SHOW)
                strips = page.evaluate("""() => ['renew-strip', 'away-strip'].map(id => {
                  const e = document.getElementById(id); return [id, getComputedStyle(e).backgroundColor]; })""")
                seen[look] = (points, shown, canvas, strips)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert ring is not None, "no pane is selected under glass:smoke"
    assert ring != "none", ("the selection ring is gone under glass:smoke", ring)
    for look, (points, shown, canvas, strips) in seen.items():
        off = [(pt["repo"], pt["x"], pt["y"], a, b) for pt, a, b in zip(points, shown, canvas)
               if max(abs(x - y) for x, y in zip(a, b)) > TOLERANCE]
        assert not off, (f"{look}: {len(off)} of {len(points)} points at the foot of the panes differ from "
                         f"the canvas alone by more than {TOLERANCE} (repo, x, y, page, canvas)", off[:12])
        for sid, bg in strips:
            assert bg in ("rgba(0, 0, 0, 0)", "transparent"), (look, sid, "is opaque over the drawing", bg)
