"""Phosphor (#394): a green phosphor screen drawn by the ink layer, the state grammar traced by a thin,
even beam.

The skin is a module (`static/ink/skins/phosphor.js`) whose mark table is the notebook's, unchanged,
with one tool tune for every drawing tool (a beam: even width, no pressure, no wobble), and a
stylesheet (`static/skins/phosphor/skin.css`) that holds the glass and its inks as custom
properties. What is asserted:

* `skins.py` offers it by name with its default, and the stylesheet paints the numbers `skins.py`
  declares, which `theme.check` holds at both ends of the glass and plain; every ink the stylesheet
  colours words with keeps 4.5:1 at both ends;
* the module carries no colour, no markup and no static import, and fits its budget;
* the names are our own: no film's names in the module, the stylesheet, their notes or the titles;
* with ink on, each state's mark is drawn when the fold puts the state on the pane and leaves by
  erase or strike; the glass read back from the canvas stays between its two colours; and an idle
  desk makes zero DOM mutations and zero WebGL frames; with `?ink=off` the page is the plain palette
  page with the same table drawn plain, no canvas and no three.js. One browser test (#587's time
  budget is shared by the wave's three new skins);
* the rain (#395), in one browser test more: one glyph per transcript line that arrives in a running
  pane, falling into a stack in the pane's margin within 320 ms, in one draw call for any number of
  panes, and draining within 320 ms of elapsed time when the turn ends; settled at once while the
  stream replays or the page is stale; none on a rail; and under reduced motion it settles and
  drains at once, with no tear.
"""
from __future__ import annotations
import gzip
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import events as E, serve as S, skins

from desk_waits import observe_quiet
from test_fleet_ink import (  # noqa: F401 - fixtures are used by name
    SKIN_BUDGET, _layer, _marks, _open, _repos, _rest, _serve, _stop, fleet_home)
from test_fleet_ink_notebook import (  # noqa: F401 - fixtures are used by name
    _emit, _of, _struck, _until, _until_class, alive, finished)
from desk_harness import close_pages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "phosphor.js")
CSS = os.path.join(STATIC, "skins", "phosphor", "skin.css")
SKINS_PY = os.path.join(ROOT, "agentdata", "fleet", "skins.py")

TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

#: Names that are not ours to use (#318): the film the look recalls, its people and its studio.
NOT_OURS = re.compile(r"\bmatrix\b|\bneo\b|\bzion\b|\bmorpheus\b|\btrinity\b|nebuchadnezzar|wachowski|warner",
                      re.I)


# ============================================================================== without a browser


def _props(css: str) -> dict:
    body = re.search(r'body\[data-skin="phosphor"\]\s*\{(.*?)\}', css, re.S).group(1)
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", body)}


def test_phosphor_is_offered_by_name_with_its_default():
    ph = skins.SKINS["phosphor"]
    assert ph["title"] == "Phosphor" and ph["default"] == "green" and set(ph["variants"]) == {"green", "paper"}
    assert ph["sides"] == {"light": "paper", "dark": "green"}, "the screen turned to paper is its light side"
    assert skins.split("phosphor") == ("phosphor", "green")
    got = skins.get_skin("phosphor")
    assert got["base"] == "matrix" and got["variant_title"] == "Green" and got["full"] == "phosphor:green"
    assert "phosphor" in [s["name"] for s in skins.list_skins()]
    assert "phosphor" in S.ink_skins()


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The glass (its near-black and its scanline, the panel's two ends) and every ink, declared once
    in skins.py and named by skin.css. The words are the palette's own: skin.css sets neither."""
    css = _read(CSS)
    props = _props(css)
    spec = skins.SKINS["phosphor"]["variants"]["green"]
    panel = spec["composited_panel"]
    assert props["paper"].upper() == panel["darkest"].upper()
    assert props["scan"].upper() == panel["lightest"].upper() == props["board-max"].upper()
    assert "text" not in props and "muted" not in props and "hand" not in props
    for tool in TOOLS:
        assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), tool
    assert re.search(r'body\[data-skin="phosphor"\]\s*\{[^}]*color-scheme:\s*dark', css)
    assert "'" not in css, "the stylesheet's strings are in double quotes"
    # The scanline is a faint one on the glass.
    assert 1.1 <= theme.contrast_ratio(props["scan"], props["paper"]) <= 1.25


def test_theme_check_holds_the_glass_at_both_ends_and_plain():
    """Every ink 3:1 at both ends of the glass, the text 4.5:1 through the highlighter, the palette's
    `--muted` 4.5:1 (#325) -- and plain, on the palette's own panel. And any word skin.css colours
    with an ink keeps 4.5:1 at both ends."""
    spec = skins.SKINS["phosphor"]["variants"]["green"]
    palette = theme.get(spec["base"])
    ends = skins.composited_panels(spec)
    assert len(ends) == 2
    for panel in ends:
        theme.check(palette, composited_panel=panel, skin="phosphor:green", inks=spec["inks"], dark=True)
        assert theme.contrast_ratio(theme.to_css(palette)["--muted"], panel) >= 4.5, panel
    theme.check(palette, composited_panel=theme.to_css(palette)["--panel"], skin="phosphor:green (plain)",
                inks=spec["inks"], plain=True)
    css = _read(CSS)
    coloured = set(re.findall(r"(?<![\w-])color:\s*var\(--ink-(\w+)\)", css))
    assert coloured, "the stylesheet writes a word in an ink"
    for tool in coloured:
        for panel in ends:
            assert theme.contrast_ratio(spec["inks"][tool], panel) >= 4.5, (tool, panel)


def test_the_module_carries_no_colour_no_markup_and_fits_its_budget():
    body = _read(MODULE)
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the phosphor module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList.add",
                   "classList.remove", "classList.toggle", ".className ="):
        assert banned not in code, banned
    size = len(gzip.compress(body.encode("utf-8"), 6, mtime=0))
    assert size < SKIN_BUDGET, size


def _phosphor_source_in_skins_py() -> str:
    """The `"phosphor"` entry of skins.py as written, with the comment above it."""
    src = _read(SKINS_PY)
    start = src.index('    "phosphor": {')
    lines = src[:start].splitlines()
    i = len(lines)
    while i and lines[i - 1].strip().startswith("#"):
        i -= 1
    head = len("\n".join(lines[:i]))
    depth, j = 0, src.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
        if not depth:
            return src[head:j]


def test_the_names_are_our_own():
    """#318: the module, the stylesheet, their notes, and the skin's and each variant's title and why
    use names of our own. The palette's slug appears only as the variant's `base`."""
    files = [MODULE, CSS, MODULE + ".md", CSS + ".md"]
    for path in files:
        text = _read(path)
        hits = NOT_OURS.findall(text)
        assert not hits, (os.path.relpath(path, ROOT), hits)
    ph = skins.SKINS["phosphor"]
    for words in [ph["title"], ph["why"]] + [s[k] for s in ph["variants"].values() for k in ("title", "why")]:
        assert not NOT_OURS.search(words), words
    entry = _phosphor_source_in_skins_py()
    assert entry.count('"base": "matrix"') == sum(v["base"] == "matrix" for v in ph["variants"].values())
    assert not NOT_OURS.search(entry.replace('"base": "matrix"', "")), entry


# ================================================================================ in a browser


def _desk(tmp_path, fleet_home, names=("alpha", "beta"), skin="phosphor"):
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


def _phosphor(page):
    page.wait_for_function("() => Ink.inspect().table === 'phosphor:green'", timeout=15000)


def _hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


@pytest.mark.browser
def test_the_beam_draws_the_state_grammar_on_the_glass_and_without_ink_the_page_is_plain(fleet_home, tmp_path, alive,
                                                                                        finished, desk_browser):
    """idle, running, error and done, each drawn when the fold puts it on the pane: pencil erased as
    the state goes, ink struck through. The glass under the transcripts, read back from the canvas,
    stays between its near-black and its scanline (plus or minus 1). At rest, before anything
    happens, the idle desk writes nothing and draws nothing, and the glass is not built again. And
    with `?ink=off`: `body.ink-off`, the palette's own page (its ground, its panel), no canvas, no
    three.js and no layer fetched -- and the same table drawn as the layer's plain CSS."""
    from test_fleet_ink_glass import GRID, READ, TRANSCRIPTS   # here: that module holds glass's tests
    names = ("alpha", "beta", "gamma")
    _desk(tmp_path, fleet_home, names=names)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", panes=3, reduced=True)
        _phosphor(page)
        A = "pane:alpha"
        IDLE = "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 6"

        _rest(page, IDLE)
        marks = _marks(page)
        for lane in (A, "pane:beta"):
            assert _of(marks, lane, ".tile.state-idle", "pencil", "outline")
            assert _of(marks, lane, "state-idle .head .repo", "pencil", "underline")
        layer = _layer(page)
        # The glass and the rain (#395), both made in `paper`, once; the pane groups stay empty.
        assert layer["skin"]["hooks"] == ["paper", "frame", "tick", "dispose"], layer["skin"]
        assert layer["skin"]["paper"] == 2 and layer["skin"]["frames"] == 0, layer["skin"]
        assert layer["skin"]["errors"] == [] and layer["hands"] is False, layer
        assert layer["dark"] and layer["mode"] == 2, "near-black glass: the highlighter screens"
        spec = skins.SKINS["phosphor"]["variants"]["green"]
        assert layer["inks"]["pen"] == spec["inks"]["pen"].upper(), layer["inks"]

        # The glass: every point read under the transcripts is between its two colours.
        lo, hi = _hex_rgb(spec["composited_panel"]["darkest"]), _hex_rgb(spec["composited_panel"]["lightest"])
        boxes = [dict(b, at=GRID) for b in page.evaluate(TRANSCRIPTS)]
        assert boxes and all(b["w"] > 20 and b["h"] > 20 for b in boxes), boxes
        seen = [px for box in page.evaluate(READ, boxes) for px in box]
        out = [px for px in seen if any(not (lo[i] - 1 <= px[i] <= hi[i] + 1) for i in range(3))]
        assert not out, ("off the glass", lo, hi, out[:5])
        assert len({tuple(px[:3]) for px in seen}) > 1, "the glass is one flat colour: no scanlines"

        # At rest, before anything happens: an idle screen writes nothing and draws nothing, and the
        # glass is not built again.
        built = page.evaluate("() => Ink.inspect().layer.skin.paper")
        count = observe_quiet(page, passes=8)
        assert count["mutations"] == 0, f"an idle phosphor desk wrote to the page: {count}"
        assert count["renders"] == 0, f"an idle phosphor desk was redrawn {count['renders']} times"
        assert page.evaluate("() => Ink.inspect().layer.skin.paper") == built
        assert not errors, errors
        page.close()

        # A page of its own for the states: the idle check above replays the page's last answer.
        page, errors, _ = _open(browser, port, token, "&ink=on", panes=3, reduced=True)
        _phosphor(page)
        _rest(page, IDLE)

        # running: the pencil goes (erased), the pen underline comes, with the beam's spot at its end.
        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _until_class(page, "alpha", "state-running")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-running') && m.state === 'drawn')")
        marks = _marks(page)
        assert not [m for m in marks if m["lane"] == A and "state-idle" in m["selector"]], \
            "the idle pencil is erased, not kept"
        run = _of(marks, A, "state-running", "pen", "underline")
        assert len(run) == 1 and run[0]["strokes"] == 2 and run[0]["drawn"] == 1, run
        before = run[0]["len"]
        _emit(page, "alpha", ("assistant_text", {"text": "reading the view"}),
              ("assistant_text", {"text": "and its grain"}))
        _until(page, '.tile[data-repo="alpha"] .transcript > li:nth-child(3)')
        _rest(page, f"Ink.inspect().layer.marks.some(m => m.selector.includes('state-running')"
                    f" && m.state === 'drawn' && m.len > {before} + 10)")

        # Without ink, while alpha runs and gamma needs you: the plain palette page, the table plain.
        _emit(page, "gamma", ("question_opened", {"question": "which one?", "id": "q1", "blocking": True,
                                                  "choices": ["this", "that"]}))
        plain, perrors, asked = _open(browser, port, token, "&ink=off", panes=3)
        plain.wait_for_function("() => Ink.inspect().table === 'phosphor:green' && Ink.inspect().plain", timeout=15000)
        _until_class(plain, "alpha", "state-running")
        _until_class(plain, "gamma", "needs-human")
        plain.wait_for_selector('.tile[data-repo="gamma"] .ask:not([hidden]) .ask-choice', timeout=15000)
        look = plain.evaluate("""() => {
          const cs = el => getComputedStyle(el);
          const a = document.querySelector('.tile[data-repo="alpha"]'), g = document.querySelector('.tile[data-repo="gamma"]');
          const root = cs(document.documentElement);
          return { off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink'),
                   text: root.getPropertyValue('--text').trim().toUpperCase(),
                   bodyBg: cs(document.body).backgroundColor, tileBg: cs(a).backgroundColor,
                   running: cs(a.querySelector('.head .repo')).textDecorationLine,
                   needs: cs(g.querySelector('.head .repo')).backgroundColor,
                   question: cs(g.querySelector('.ask:not([hidden]) .ask-q')).backgroundColor,
                   loop: cs(g.querySelector('.ask:not([hidden]) .ask-choice')).outlineStyle }; }""")
        palette = theme.to_css(theme.get("matrix"))
        rgb = lambda h: "rgb(%d, %d, %d)" % _hex_rgb(h)  # noqa: E731
        assert look["off"] and not look["canvas"], look
        assert look["text"] == palette["--text"].upper(), look
        assert look["bodyBg"] == rgb(palette["--bg"]) and look["tileBg"] == rgb(palette["--panel"]), look
        assert look["running"] == "underline", look
        assert look["needs"] not in ("", "rgba(0, 0, 0, 0)") and look["question"] == look["needs"], look
        assert look["loop"] == "solid", look
        assert not [u for u in asked if "three.module" in u or "/ink/layer.js" in u], "no layer without ink"
        assert not perrors, perrors
        plain.close()

        # error: the pen line is struck, a marker loop round the why and a bang.
        alive.discard("alpha")
        _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("error", {"exit_code": 2}))
        _until_class(page, "alpha", "state-error")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-error') && m.state === 'drawn').length === 2")
        marks = _marks(page)
        gone = [m for m in marks if m["lane"] == A and "state-running" in m["selector"] and not m["strikeOf"]]
        assert len(gone) == 1 and gone[0]["state"] == "struck", "the running line is struck"
        assert _struck(marks, {gone[0]["id"]}) == {gone[0]["id"]}
        assert _of(marks, A, "state-error .why", "marker", "loop")
        assert _of(marks, A, "state-error", "marker", "bang")

        # done: a green check, on the other pane.
        alive.add("beta")
        finished.add("beta")
        _emit(page, "beta", ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "beta", "state-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:beta' && m.state === 'drawn')")
        marks = _marks(page)
        assert _of(marks, "pane:beta", "is-done", "green", "check")
        assert not [m for m in marks if m["lane"] == "pane:beta" and "state-idle" in m["selector"]]
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


# ================================================================================ the rain (#395)

#: The skin's module, the same instance the layer imported (`q` puts the same token on the URL).
IMPORT = "async () => { window.__ph = await import(q('/static/ink/skins/phosphor.js')); return true; }"

#: Append `n` transcript lines to pane `repo`, then record, a frame at a time, the skin's count of
#: settled and falling glyphs there until `want` are settled and none falls.
FALL = """async ([repo, n, want]) => {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`);
  for (let i = 0; i < n; i++) {
    const li = document.createElement('li'); li.className = 'assistant_text';
    const k = document.createElement('span'); k.className = 'k'; k.textContent = 'assistant text';
    const v = document.createElement('span'); v.className = 'v'; v.textContent = 'line ' + i;
    li.append(k, v); list.appendChild(li);
  }
  const out = [];
  return await new Promise(done => {
    const step = () => {
      const p = window.__ph.inspect().panes[repo];
      out.push([p.settled, p.falling]);
      if ((p.settled === want && !p.falling) || out.length > 600) return done(out);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}"""

#: Append `n` transcript lines to each pane of `repos`, in one task.
APPEND = """([repos, n]) => { for (const repo of repos) {
  const list = document.querySelector(`.tile[data-repo="${repo}"] .transcript`);
  for (let i = 0; i < n; i++) { const li = document.createElement('li'); li.className = 'assistant_text';
    li.textContent = 'line ' + i; list.appendChild(li); } } }"""

#: The `RECORD` pattern (tests/test_fleet_ink.py) for a drain: ask the page to look, then a frame at
#: a time, from the first frame pane `repo` is no longer running, its settled count, until it is 0.
DRAIN = """async ([repo]) => {
  const t = document.querySelector(`.tile[data-repo="${repo}"]`), out = [];
  let from = -1;
  refresh();
  return await new Promise(done => {
    const step = () => {
      const p = window.__ph.inspect().panes[repo];
      if (from < 0 && !t.classList.contains('state-running')) from = out.length;
      out.push([p.settled, p.falling, p.draining]);
      if (from >= 0 && p.settled === 0) return done({ frames: out.length - from, out: out.slice(Math.max(0, from - 1)) });
      if (out.length > 1200) return done({ frames: -1, out: out.slice(-5) });
      if (from < 0 && out.length % 20 === 0) refresh();
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}"""

#: From the page's first script on: every frame, the most glyphs seen falling while the stream
#: replays or the page is stale (`window.__hushFalls`), and how many frames were that.
HUSH = """(() => {
  window.__hushFalls = { most: 0, frames: 0, settled: 0 };
  const step = () => {
    const b = document.body && document.body.classList;
    const ink = window.Ink && typeof Ink.inspect === 'function' ? Ink.inspect() : null;
    if (!window.__ph && window.q && ink && ink.table === 'phosphor:green') {
      window.__ph = {};
      import(q('/static/ink/skins/phosphor.js')).then(m => { window.__ph = m; });
    }
    if (b && window.__ph && window.__ph.inspect && (b.contains('is-replaying') || b.contains('is-stale'))) {
      const panes = window.__ph.inspect().panes;
      const falling = Object.values(panes).reduce((n, p) => n + p.falling, 0);
      window.__hushFalls.most = Math.max(window.__hushFalls.most, falling);
      window.__hushFalls.frames += 1;
    }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
})()"""

#: The frames a 320 ms fall needs at 60 Hz (19.2), plus 4; and a drain's, plus 2.
FALL_FRAMES = 23
DRAIN_FRAMES = 22


def _rain(page, repo):
    return page.evaluate("r => window.__ph.inspect().panes[r]", repo)


def _running(page, alive, *repos):
    for repo in repos:
        alive.add(repo)
        _emit(page, repo, ("turn_started", {}))
    for repo in repos:
        _until_class(page, repo, "state-running")


#: The window the rain is watched in: eight panes of at least 90px, and less to shade in software.
SMALL = {"width": 1000, "height": 620}

NAMES = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")

#: A pane's cap: its height less 60px, in 10px cells.
CAP = "r => Math.floor((document.querySelector(`.tile[data-repo=\"${r}\"]`).getBoundingClientRect().height - 60) / 10)"


@pytest.mark.browser
def test_the_rain_is_one_glyph_per_line_in_one_draw_call_drains_in_320_ms_and_never_falls_unasked(
        fleet_home, tmp_path, alive, desk_browser):
    """#395, one test for the wave's shared time budget.
    1. Three lines appended to a running pane settle three glyphs within the frames a 320 ms fall
       needs, plus 4; the rain is one draw call with one pane raining and with eight; a stack filled
       past its cap keeps the cap; when the turn ends it drains to nothing within 22 frames; and
       once settled the screen writes nothing and draws nothing.
    2. A reload with a 30-line backlog: nothing falls while the stream replays or the page is stale,
       and lines that arrive then are settled.
       A rail that receives lines while running keeps no rain.
    3. Under reduced motion lines settle at once, an error tears nothing (its band is drawn), and
       the stack drains at once."""
    _desk(tmp_path, fleet_home, names=NAMES)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", panes=len(NAMES), **SMALL)
        _phosphor(page)
        _rest(page, "Ink.inspect().layer.skin.paper === 2")
        assert page.evaluate(IMPORT)
        _running(page, alive, "alpha")
        _rest(page)

        seen = page.evaluate(FALL, ["alpha", 3, 3])
        assert seen[-1] == [3, 0] and len(seen) <= FALL_FRAMES, (len(seen), seen)
        assert max(f for _, f in seen) >= 1, f"nothing fell: {seen}"
        _rest(page)
        assert page.evaluate("() => window.__ph.inspect().drawCalls") == 1

        # Eight panes raining: still one draw call.
        _running(page, alive, *NAMES[1:])
        page.evaluate(APPEND, [list(NAMES[1:]), 2])
        page.wait_for_function("names => { const p = window.__ph.inspect().panes;"
                               " return names.every(n => p[n] && p[n].settled === 2 && !p[n].falling); }",
                               arg=list(NAMES[1:]), timeout=15000)
        _rest(page)
        rain = page.evaluate("() => window.__ph.inspect()")
        assert all(rain["panes"][r]["settled"] >= 2 for r in NAMES), rain
        assert rain["drawCalls"] == 1, rain

        # Past the cap, the oldest glyph is erased.
        cap = page.evaluate(CAP, "alpha")
        assert cap > 10, cap
        seen = page.evaluate(FALL, ["alpha", cap + 5, cap])
        assert seen[-1] == [cap, 0], seen[-3:]

        # The turn ends: the stack drains top to bottom within 320 ms of elapsed time.
        alive.discard("alpha")
        E.append("alpha", [E.event("alpha", "turn_ended", {"turn": "1"}, ticket="RDSD-1")])
        drained = page.evaluate(DRAIN, ["alpha"])
        assert 0 < drained["frames"] <= DRAIN_FRAMES, drained
        assert any(d for _, _, d in drained["out"]), drained

        _rest(page)
        count = observe_quiet(page, passes=3)
        assert count["mutations"] == 0, f"a settled rain wrote to the page: {count}"
        assert count["renders"] == 0, f"a settled rain was redrawn {count['renders']} times"
        assert not errors, errors
        page.close()

        # 2. A reload with a 30-line backlog, recorded from the page's first script. Only alpha is
        # open now, so the others are rails.
        S.update_window("main", open="alpha", widths={"alpha": 1})
        alive.add("alpha")
        E.append("alpha", [E.event("alpha", "turn_started", {}, ticket="RDSD-1")]
                 + [E.event("alpha", "assistant_text", {"text": f"backlog {i}"}, ticket="RDSD-1") for i in range(30)])
        page, errors, _ = _open(browser, port, token, "&ink=on", panes=1, **SMALL)
        page.add_init_script(HUSH)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.__ph && !!window.__ph.inspect && !!window.__ph.inspect().panes.alpha"
                               " && !document.body.classList.contains('is-replaying')"
                               " && !document.body.classList.contains('is-stale')"
                               " && document.querySelectorAll('.tile[data-repo=\"alpha\"] .transcript > li').length >= 30"
                               " && document.querySelector('.tile[data-repo=\"alpha\"]').classList.contains('state-running')",
                               timeout=15000)
        _rest(page)
        hush = page.evaluate("() => window.__hushFalls")
        assert hush["most"] == 0 and hush["frames"] > 0, hush
        assert _rain(page, "alpha")["falling"] == 0
        # Lines that arrive while the stream replays settle where they land.
        before = _rain(page, "alpha")["settled"]
        page.evaluate("() => document.body.classList.add('is-replaying')")
        page.evaluate(FALL, ["alpha", 5, min(before + 5, page.evaluate(CAP, "alpha"))])
        page.evaluate("() => document.body.classList.remove('is-replaying')")
        hush = page.evaluate("() => window.__hushFalls")
        assert hush["most"] == 0, hush

        # 3. A rail: beta, running since part 1, is under 90px wide; its lines rain nothing.
        assert page.evaluate("() => document.querySelector('.tile[data-repo=\"beta\"]').getBoundingClientRect().width") < 90
        _until_class(page, "beta", "state-running")
        page.evaluate(APPEND, [["beta"], 4])
        _rest(page)
        assert {k: _rain(page, "beta")[k] for k in ("settled", "falling")} == {"settled": 0, "falling": 0}
        assert not errors, errors
        page.close()

        # Reduced motion: at once, and no tear.
        still, errors, _ = _open(browser, port, token, "&ink=on", panes=1, reduced=True, **SMALL)
        _phosphor(still)
        _rest(still, "Ink.inspect().layer.skin.paper === 2")
        assert still.evaluate(IMPORT)
        _until_class(still, "alpha", "state-running")
        start = _rain(still, "alpha")["settled"]
        seen = still.evaluate(FALL, ["alpha", 3, min(start + 3, still.evaluate(CAP, "alpha"))])
        assert len(seen) <= 2 and not any(f for _, f in seen), seen
        alive.discard("alpha")
        E.append("alpha", [E.event("alpha", "error", {"exit_code": 2}, ticket="RDSD-1")])
        drained = still.evaluate(DRAIN, ["alpha"])
        assert 0 < drained["frames"] <= 2, drained
        _until_class(still, "alpha", "state-error")
        _rest(still)
        got = _rain(still, "alpha")
        assert got["tear"] is False and got["band"] is True and got["settled"] == 0, got
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
