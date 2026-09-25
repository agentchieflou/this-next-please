"""Ruled paper and the transcript keep one rhythm (#338): on the notebook and the legal pad, every
transcript line sits on a rule, never under one that reads as a strike.

The paper's rules are 28px apart and the transcript's rows were 25px, so the rules drifted through
the middle of text lines. Now, under ink, a transcript row is 28px with no divider of its own, the
rows end at the transcript's bottom, and the skin's `frame` hook covers the transcript's box with
plain stock and rules it every 28px up from that bottom edge. The layer's frame signature carries
the transcript's box in its pane, so a card shown above it redraws its rules. What is asserted, on
notebook light and dark and the legal pad, at 1400x900 and 700x900:

* every transcript text line's glyph box (`Range.getClientRects`) ends 2-6px above a rule, and no
  rule crosses the middle third of a line -- the rules found in a screenshot of the transcript
  clipped to its box with its text hidden, decoded with `_png_pixels`;
* consecutive rows are exactly 28px apart; the same with a two-row transcript that does not
  overflow, and after the wheel scrolls a long one up by 100px and it settles on a row;
* showing and hiding the question card rebuilds the pane's frame once each time, and the lines
  still sit on the rules; a scroll adds no frame build;
* under ink no row draws a divider; with `?ink=off` the plain look keeps its dividers and 25px rows.
"""
from __future__ import annotations

import pytest

from agentdata.fleet import events as E, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_desk_glass import _png_pixels
from test_fleet_ink import AT_REST, _choose, _open, _repos, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_ink_notebook import _emit, _until_class

#: The long transcript and the short one.
LONG, SHORT = "alpha", "beta"
LOOKS = ("notebook:light", "notebook:dark", "legalpad:canary")
WIDTHS = (1400, 700)
PITCH = 28

#: Where the skin module keeps what it built: the same instance the layer runs, imported again by
#: its URL and kept on `window` so a wait can ask it synchronously.
IMPORT = "async (s) => { window.__rules = await import(q('/static/ink/skins/' + s + '.js')); }"
BUILDS = "() => window.__rules.inspect().builds"

#: Hides the words so the screenshot holds only the paper, and shows them again.
HIDE = """(on) => { let s = document.getElementById('rules-hide');
  if (on && !s) { s = document.createElement('style'); s.id = 'rules-hide';
    s.textContent = '.transcript, .transcript * { color: transparent !important; }';
    document.head.appendChild(s); }
  if (!on && s) s.remove(); }"""

#: A pane's transcript: its box, its scroll, each row's rect and each visible text line's glyph box.
MEASURE = """(repo) => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`);
  const b = list.getBoundingClientRect(), top = b.top + list.clientTop;
  const rows = [...list.children].map(li => { const r = li.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, h: r.height, border: getComputedStyle(li).borderBottomWidth }; });
  const lines = [];
  for (const li of list.children) {
    const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (!n.data.trim()) continue;
      const g = document.createRange();
      g.selectNodeContents(n);
      for (const q of g.getClientRects())
        if (q.height > 0 && q.width > 0 && q.top >= top && q.bottom <= b.bottom)
          lines.push({ top: q.top, bottom: q.bottom, text: n.data.slice(0, 24) });
    }
  }
  return { box: { x: b.left, y: top, w: list.clientWidth, h: b.bottom - top, bottom: b.bottom },
           scroll: list.scrollTop, max: list.scrollHeight - list.clientHeight, rows, lines };
}"""

#: The transcript's scroll has settled: the same `scrollTop` across two animation frames.
SETTLE = """(repo) => new Promise(done => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`);
  let was = -1, same = 0;
  const look = () => { const now = list.scrollTop;
    same = now === was ? same + 1 : 0; was = now;
    same >= 2 ? done(now) : requestAnimationFrame(look); };
  requestAnimationFrame(look);
})"""


#: The long pane has stopped moving: its box and its transcript's box the same for three frames in
#: a row, nothing on the page in a transition, and the fonts loaded (#461). On the Windows 3.14 leg
#: the watch below began while the pane was still settling -- the transcript's top at 221.2, 238.2
#: or 249.2 before the card, where a settled pane reads 249.2 every time -- and the layer built a
#: frame for a box the watch never sampled.
STILL = """(repo) => new Promise(done => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`), pane = list.closest('.tile');
  let was = '', same = 0;
  const look = () => {
    const r = list.getBoundingClientRect(), p = pane.getBoundingClientRect();
    const now = [p.left, p.top, p.width, p.height, r.top, r.height].map(v => v.toFixed(1)).join(',');
    same = now === was ? same + 1 : 0; was = now;
    const moving = document.getAnimations().some(a => a.playState === 'running');
    if (same >= 3 && !moving && document.fonts.status === 'loaded') done(now); else requestAnimationFrame(look);
  };
  requestAnimationFrame(look);
})"""


def _desk(tmp_path):
    """Two panes: a long transcript that overflows -- one-line tool calls, and the agent's words,
    whose `assistant text` label wraps to a second line -- and a short one of two rows."""
    _repos(tmp_path, (LONG,))
    E.append(LONG, [E.event(LONG, "tool_call", {"tool": "read", "arguments": {"step": i}}, ticket="RDSD-1")
                    if i % 3 else E.event(LONG, "assistant_text", {"text": f"step {i} of the plan"}, ticket="RDSD-1")
                    for i in range(40)])
    Registry().add(make_project(tmp_path / SHORT, ticket="RDSD-1"), name=SHORT)
    # Started, and the fold's own `phase changed` to idle for an agent no process holds.
    E.append(SHORT, [E.event(SHORT, "started", {"pid": 1}, ticket="RDSD-1")])
    S.arrange(order=[LONG, SHORT])
    S.update_window("main", open=LONG, widths={LONG: 1, SHORT: 1})


def _look(page, look):
    """Choose a look and wait, on conditions, for its table, its rows at 28px and the paper at rest,
    with the long transcript at its bottom, as the live desk keeps it."""
    _choose(page, look)
    skin = look.split(":")[0]
    page.wait_for_function(f"""() => Ink.inspect().table === '{look}'
      && [...document.querySelectorAll('link[data-skin]')].some(l => l.sheet && l.href.includes('/skins/{skin}/skin.css'))
      && getComputedStyle(document.querySelector('.transcript > li')).lineHeight === '28px'
      && ({AT_REST})()""", timeout=30000, polling=100)
    page.evaluate(IMPORT, skin)
    page.evaluate(f"() => {{ const l = document.querySelector('.tile[data-repo=\"{LONG}\"] .transcript');"
                  " l.scrollTop = l.scrollHeight; }")
    page.evaluate(SETTLE, LONG)
    page.evaluate(STILL, LONG)
    page.wait_for_function(AT_REST, timeout=20000)


def _rules(page, box):
    """The rules under a transcript, as the viewport y of each rule's top edge: its box screenshotted
    with its words hidden, and a pixel row that stands off the paper around it (the median of its
    neighbours) is ink. A rule that lands between two pixel rows inks both, so its top is found
    from the centre of its ink. The right 20px (the scrollbar) are left out."""
    page.evaluate(HIDE, True)
    page.wait_for_function("() => getComputedStyle(document.querySelector('.transcript > li')).color"
                           " === 'rgba(0, 0, 0, 0)'", timeout=5000)
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    x, y = int(box["x"]) + 2, int(box["y"]) + 1
    w, h = int(box["w"]) - 24, int(box["bottom"]) - y
    _, _, bpp, rows = _png_pixels(page.screenshot(type="png", clip={"x": x, "y": y, "width": w, "height": h}))
    page.evaluate(HIDE, False)
    means = []
    for row in rows:
        n = len(row) // bpp
        means.append(tuple(sum(row[i * bpp + c] for i in range(n)) / n for c in range(3)))
    off = []
    for i, m in enumerate(means):
        near = sorted(means[max(0, i - 8):i + 9], key=sum)
        paper = near[len(near) // 2]
        off.append(sum((a - b) ** 2 for a, b in zip(m, paper)) ** 0.5)
    out, i = [], 0
    while i < len(off):
        if off[i] <= 4:
            i += 1
            continue
        j = i
        while j < len(off) and off[j] > 4:
            j += 1
        weight = sum(off[i:j])
        centre = sum((k + 0.5) * off[k] for k in range(i, j)) / weight
        out.append(round(y + centre - 0.5, 2))
        i = j
    return out


def _check(where, m, rules):
    """Rows 28px apart, and each line 2-6px above a rule with no rule through its middle third."""
    rows = m["rows"]
    # A row is a whole number of rules: one line, or a label that wraps (`assistant text` in its
    # 96px column) and takes two. The next row starts exactly where it ends.
    assert all(r["h"] % PITCH == 0 and r["h"] > 0 for r in rows), (where, "row heights", [r["h"] for r in rows])
    assert all(b["top"] - a["top"] == a["h"] for a, b in zip(rows, rows[1:])), (where, "rows touch", rows)
    ones = [(a, b) for a, b in zip(rows, rows[1:]) if a["h"] == PITCH]
    assert all(b["top"] - a["top"] == PITCH for a, b in ones), (where, "one-line rows 28px apart", ones)
    assert all(r["border"] == "0px" for r in m["rows"]), (where, "a row draws a divider", m["rows"])
    assert m["lines"], (where, "no line of text in view", m)
    for g in m["lines"]:
        below = [r for r in rules if 2 <= r - g["bottom"] <= 6]
        assert below, (where, "no rule 2-6px under", g, rules)
        third = (g["bottom"] - g["top"]) / 3
        through = [r for r in rules if g["top"] + third <= r + 0.5 <= g["bottom"] - third]
        assert not through, (where, "a rule through the line", g, through)


def _both(page, where):
    out = {}
    for repo in (LONG, SHORT):
        m = page.evaluate(MEASURE, repo)
        out[repo] = (m, _rules(page, m["box"]))
    long_, short = out[LONG][0], out[SHORT][0]
    assert long_["max"] > 0 and abs(long_["scroll"] - long_["max"]) <= 1, (where, "long is at its bottom", long_["scroll"], long_["max"])
    assert short["max"] == 0 and len(short["rows"]) == 2, (where, "short has two rows and no overflow", short)
    # The short transcript's rows end at its bottom, where its rules are measured from.
    assert abs(short["rows"][-1]["bottom"] - short["box"]["bottom"]) < 0.01, (where, short)
    for repo, (m, rules) in out.items():
        _check(f"{where} {repo}", m, rules)


@pytest.mark.browser
@pytest.mark.parametrize("width", WIDTHS)
def test_every_transcript_line_sits_on_a_rule(fleet_home, tmp_path, width):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=2, width=width, reduced=True)
            for look in LOOKS:
                _look(page, look)
                _both(page, f"{look} @ {width}px")
                # The wheel scrolls the long transcript up by 100px: it settles on a row, and the
                # scroll builds no frame.
                before = page.evaluate(BUILDS)
                box = page.evaluate(MEASURE, LONG)["box"]
                page.mouse.move(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
                page.mouse.wheel(0, -100)
                page.wait_for_function(f"() => document.querySelector('.tile[data-repo=\"{LONG}\"] .transcript')"
                                       f".scrollTop < {page.evaluate(MEASURE, LONG)['max']}", timeout=5000)
                page.evaluate(SETTLE, LONG)
                page.wait_for_function(AT_REST, timeout=20000)
                m = page.evaluate(MEASURE, LONG)
                assert m["scroll"] < m["max"], (look, width, "the wheel scrolled", m["scroll"], m["max"])
                _check(f"{look} @ {width}px scrolled", m, _rules(page, m["box"]))
                assert page.evaluate(BUILDS) == before, (look, width, "a scroll built a frame")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


#: Every box the long pane's transcript takes in its pane, frame by frame, to the frame signature's
#: 0.1px: what the layer is asked to follow. `STOP` ends the watch and answers the boxes seen.
WATCH = """(repo) => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`), pane = list.closest('.tile');
  const seen = window.__boxes = [];
  const look = () => {
    if (window.__boxes !== seen) return;
    const r = list.getBoundingClientRect(), p = pane.getBoundingClientRect();
    const s = p.width.toFixed(1) + 'x' + p.height.toFixed(1) + '@' + (r.top - p.top).toFixed(1) + '+' + r.height.toFixed(1);
    if (seen[seen.length - 1] !== s) seen.push(s);
    requestAnimationFrame(look);
  };
  look();
}"""
STOP = "() => { const seen = window.__boxes; window.__boxes = null; return seen; }"
TO_BOTTOM = "(repo) => { const l = document.querySelector(`.tile[data-repo=\"${repo}\"] .transcript`); l.scrollTop = l.scrollHeight; }"
CARD = """([repo, on]) => { const c = document.querySelector(`.tile[data-repo="${repo}"] .asks`);
  if ((getComputedStyle(c).display !== 'none') === on) return true; refresh(); return false; }"""


@pytest.mark.browser
def test_the_question_card_redraws_the_rules_once_for_each_move(fleet_home, tmp_path):
    """The card shown above the transcript moves it in a pane of the same size: the frame is built
    again once, and the lines still sit on the rules. The card leaving builds it once for each box
    the transcript takes on the way (the name's highlight and the card go in separate refreshes),
    never more, and a pane whose transcript did not move is not built again."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=2, width=1400, reduced=True)
            _look(page, "notebook:light")
            for event, on in (
                    (("question_opened", {"question": "which window should this land in?", "id": "q1",
                                          "blocking": True, "choices": ["left", "right"]}), True),
                    (("question_answered", {"id": "q1", "question": "which window should this land in?"}), False)):
                # The watch starts from a pane at rest, so every box the layer builds for is one it sees.
                page.evaluate(STILL, LONG)
                page.wait_for_function(AT_REST, timeout=20000)
                before = page.evaluate(BUILDS)
                page.evaluate(WATCH, LONG)
                _emit(page, LONG, event)
                _until_class(page, LONG, "needs-human", on)
                page.wait_for_function(CARD, arg=[LONG, on], timeout=15000, polling=250)
                page.evaluate(SETTLE, LONG)
                page.wait_for_function(AT_REST, timeout=20000)
                boxes = page.evaluate(STOP)
                built = page.evaluate(BUILDS) - before
                where = f"question card {'shown' if on else 'hidden'}"
                assert len(boxes) >= 2 and built == len(boxes) - 1, (where, built, boxes)
                if on:
                    assert built == 1, (where, built, boxes)
                page.evaluate(TO_BOTTOM, LONG)
                page.evaluate(SETTLE, LONG)
                page.wait_for_function(AT_REST, timeout=20000)
                m = page.evaluate(MEASURE, LONG)
                _check(where, m, _rules(page, m["box"]))
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_without_ink_the_plain_transcript_keeps_its_dividers_and_25px_rows(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "notebook"}}', encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=off", panes=2, width=1400, reduced=True)
            seen = {}
            for look in LOOKS:
                _choose(page, look)
                page.wait_for_function(f"() => Ink.inspect().table === '{look}' && document.body.classList.contains('ink-off')",
                                       timeout=30000)
                seen[look] = page.evaluate(MEASURE, LONG)["rows"]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for look, rows in seen.items():
        # A one-line row is 3 + 18 + 3 and its 1px divider; the next starts where it ends.
        ones = [(a, b) for a, b in zip(rows, rows[1:]) if a["h"] == 25]
        assert ones and all(b["top"] - a["top"] == 25 for a, b in ones), (look, rows[:4])
        assert all(b["top"] - a["top"] == a["h"] for a, b in zip(rows, rows[1:])), (look, rows[:4])
        assert all(r["border"] == "1px" for r in rows[:-1]) and rows[-1]["border"] == "0px", (look, rows[:3])
