"""The circuit board (#396): `greens`, the last built-in palette with no look, drawn as a board --
solder mask with a fibreglass weave, each pane a component with a copper pad and a trace along its
top edge, its number ringed as pin 1, and the state grammar in silkscreen and copper.

The skin is a module (`static/ink/skins/circuit.js`) and a stylesheet (`static/skins/circuit/skin.css`)
that holds its board and inks as custom properties. What is asserted:

* `skins.py` offers it with a `solder` (greens) and a `matte` (vanta-black) variant, `greens` is no
  longer palette-only, and the stylesheet sets the numbers `skins.py` declares;
* `theme.check` holds both ends of both boards, plain and in ink, with #325's `--muted` rule, and
  every ink the stylesheet colours a word with reads at 4.5:1 at both ends;
* the module carries no colour, no markup and no static import, and fits `SKIN_BUDGET`;
* with ink on, the grammar is drawn when the fold puts a state on the pane and leaves by erase or
  strike; pin 1 is ringed and a blocked pane crossed; `?ink=off` is the plain look;
* the board reads back inside [--paper, --board-max], no copper pixel is inside any word of a pane,
  the traces follow a gutter drag in the frame that moves the panes, and an idle board is zero
  mutations and zero frames.
"""
from __future__ import annotations
import gzip
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, serve as S, skins, supervisor

from desk_waits import assert_idle, record_mutations
from test_fleet_ink import (  # noqa: F401 - fixtures are used by name
    SKIN_BUDGET, _layer, _marks, _open, _repos, _rest, _serve, _stop, fleet_home)
from test_fleet_gutters import _gutter_point
from desk_harness import close_pages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "circuit.js")
CSS = os.path.join(STATIC, "skins", "circuit", "skin.css")

TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")


# ============================================================================== without a browser


def _css_block(variant: str) -> dict:
    """The custom properties the stylesheet sets for a variant: the base block, and its own over it."""
    css = open(CSS, encoding="utf-8").read()
    blocks = [r'body\[data-skin="circuit"\]\s*\{(.*?)\}']
    if variant != skins.SKINS["circuit"]["default"]:
        blocks.append(r'body\[data-skin="circuit"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant)
    out = {}
    for pattern in blocks:
        out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", re.search(pattern, css, re.S).group(1))))
    return out


def _rgb(hex_):
    return tuple(round(c * 255) for c in theme.hex_to_rgb(hex_))


def test_the_circuit_board_is_a_skin_and_greens_is_no_longer_palette_only():
    board = skins.SKINS["circuit"]
    assert board["title"] == "Circuit board" and board["default"] == "solder"
    assert board["why"] == "solder mask, silkscreen and copper: each agent a component on the board"
    assert {v: s["base"] for v, s in board["variants"].items()} == {"solder": "greens", "matte": "vanta-black"}
    assert skins.split("circuit") == ("circuit", "solder")
    assert skins.get_skin("circuit:matte")["base"] == "vanta-black"
    assert "circuit" in S.ink_skins() and "circuit" in [s["name"] for s in skins.list_skins()]
    assert "greens" not in skins.PALETTE_ONLY


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The mask is the dark end of the panel and `--board-max` its light end; the weave lies between
    them; each `--ink-<tool>` is the variant's ink; the copper is the one colour in no check."""
    for variant, spec in skins.SKINS["circuit"]["variants"].items():
        props = _css_block(variant)
        panel = spec["composited_panel"]
        assert props["paper"].upper() == panel["darkest"] and props["board-max"].upper() == panel["lightest"], variant
        lo, hi, weave = _rgb(panel["darkest"]), _rgb(panel["lightest"]), _rgb(props["weave"])
        assert all(a <= w <= b for a, w, b in zip(lo, weave, hi)), (variant, props["weave"])
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool], (variant, tool)
        assert props["copper"].upper() == "#6B4A2A", variant
        assert "text" not in props and "muted" not in props, (variant, "the palette's own words, recoloured")


def test_theme_check_holds_both_ends_of_both_boards_plain_and_in_ink():
    """Rule 5 with the board's inks at both ends of each variant's panel, in ink (the layer's
    `dark`, from `--paper`) and plain, and #325's `--muted` 4.5:1 at both ends."""
    for variant, spec in skins.SKINS["circuit"]["variants"].items():
        base = theme.get(spec["base"])
        dark = theme.is_dark(_css_block(variant)["paper"])
        assert dark, variant
        for panel in skins.composited_panels(spec):
            theme.check(base, composited_panel=panel, skin=f"circuit:{variant}", inks=spec["inks"], dark=dark)
            assert theme.contrast_ratio(theme.to_css(base)["--muted"], panel) >= 4.5, (variant, panel)
        theme.check(base, composited_panel=theme.to_css(base)["--panel"], skin=f"circuit:{variant} (plain)",
                    inks=spec["inks"], plain=True)


def test_every_ink_the_stylesheet_writes_words_in_reads_at_4_5_on_both_ends():
    """A word coloured with an ink is text: 4.5:1 at both ends of both variants, so red (3.72:1 at
    the solder's light end) never colours one."""
    css = open(CSS, encoding="utf-8").read()
    used = set(re.findall(r"(?<![-\w])color:\s*var\(--ink-(\w+)\)", css))
    assert used, "the silkscreen words are coloured with an ink"
    for variant, spec in skins.SKINS["circuit"]["variants"].items():
        for tool in used:
            for panel in skins.composited_panels(spec):
                ratio = theme.contrast_ratio(spec["inks"][tool], panel)
                assert ratio >= 4.5, (variant, tool, panel, round(ratio, 2))


def test_the_module_carries_no_colour_no_markup_and_fits_its_budget():
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the circuit module"
    assert not re.search(r"\b0x[0-9A-Fa-f]{6}\b", code), "a colour written in the module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList",
                   "setAttribute", "style.setProperty", "appendChild"):
        assert banned not in code, banned
    size = len(gzip.compress(open(MODULE, "rb").read(), 6, mtime=0))
    assert size < SKIN_BUDGET, size
    page = (open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
            + open(os.path.join(STATIC, "index.html"), encoding="utf-8").read())
    for sel in re.findall(r'selector: "((?:[^"\\]|\\.)*)"', body):
        for cls in re.findall(r"\.([A-Za-z][\w-]*)", sel):
            if cls.startswith("state-"):
                assert cls[len("state-"):] in agentstate.STATES, (sel, cls)
            else:
                assert re.search(r"\b%s\b" % re.escape(cls), page), (sel, cls, "a class the page does not set")


# ================================================================================ in a browser


def _desk(tmp_path, fleet_home, names=("alpha", "beta"), skin="circuit"):
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


@pytest.fixture()
def alive(monkeypatch):
    """The agents a process is holding: the pane shows running (and done) only for those (#147)."""
    names: set = set()
    real = supervisor.live
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 777, "repo": name} if name in names else real(name))
    return names


@pytest.fixture()
def finished(monkeypatch, alive):
    """Held agents whose turn is over: the fold says `done` for a terminal phase."""
    names: set = set()
    real = agentstate.derive

    def derive(events, *, live=False, open_questions=None):
        mine = bool(events) and events[0].get("repo") in names
        return real(events, live=False if mine else live, open_questions=open_questions)
    monkeypatch.setattr(agentstate, "derive", derive)
    return names


def _emit(page, repo, *events):
    E.append(repo, [E.event(repo, kind, data, ticket="RDSD-1") for kind, data in events])
    page.evaluate("() => refresh()")


def _until_class(page, repo, cls, on=True):
    page.wait_for_function(
        "([s, want]) => { if (!!document.querySelector(s) === want) return true; refresh(); return false; }",
        arg=[f'.tile[data-repo="{repo}"].{cls}', on], timeout=15000, polling=250)


def _board(page, variant="solder"):
    page.wait_for_function(f"() => Ink.inspect().table === 'circuit:{variant}'", timeout=15000)
    page.evaluate("async () => { window.__circuit = await import(q('/static/ink/skins/circuit.js')); }")


def _of(marks, lane, sel_part, tool=None, shape=None):
    return [m for m in marks if m["lane"] == lane and sel_part in m["selector"] and m["state"] == "drawn"
            and not m["strikeOf"] and m["visible"] and (tool is None or m["tool"] == tool)
            and (shape is None or m["shape"] == shape)]


@pytest.mark.browser
def test_the_board_draws_the_grammar_rings_pin_one_crosses_a_blocked_pane_and_ink_off_is_plain(
        fleet_home, tmp_path, alive, finished, desk_browser):
    """idle, running, error, blocked and done, each drawn when the fold puts it on the pane and
    leaving by erase (pencil) or strike (ink); pin 1 ringed on every open pane. Then the same desk
    with `?ink=off`: the plain look, the same table as CSS, and no canvas."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
        _board(page)
        A, B = "pane:alpha", "pane:beta"
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4"
                    " && Ink.inspect().layer.marks.filter(m => m.shape === 'ring').length === 2")
        marks = _marks(page)
        for lane in (A, B):
            assert _of(marks, lane, ".tile.state-idle", "pencil", "outline")
            assert _of(marks, lane, "state-idle .head .repo", "pencil", "underline")
            assert _of(marks, lane, ".head .n", "pencil", "ring")
        layer = _layer(page)
        assert layer["skin"]["hooks"] == ["paper", "frame", "dispose"] and layer["skin"]["paper"] == 1
        assert layer["skin"]["frames"] == 2 and layer["skin"]["errors"] == [] and layer["dark"], layer["skin"]

        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _until_class(page, "alpha", "state-running")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-running') && m.state === 'drawn')")
        marks = _marks(page)
        assert not [m for m in marks if m["lane"] == A and "state-idle" in m["selector"]], "the idle pencil is erased"
        run = _of(marks, A, "state-running", "pen", "underline")
        assert len(run) == 1 and run[0]["strokes"] == 2, "the pen line and its via"

        alive.discard("alpha")
        _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("error", {"exit_code": 2}))
        _until_class(page, "alpha", "state-error")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-error') && m.state === 'drawn').length === 2")
        marks = _marks(page)
        gone = [m for m in marks if m["lane"] == A and "state-running" in m["selector"] and not m["strikeOf"]]
        assert len(gone) == 1 and gone[0]["state"] == "struck", "the running line is struck"
        assert _of(marks, A, "state-error .why", "marker", "loop") and _of(marks, A, "state-error", "marker", "bang")

        _emit(page, "beta", ("phase_changed", {"from": "build", "to": "blocked"}))
        _until_class(page, "beta", "state-blocked")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'cross' && m.lane === 'pane:beta' && m.state === 'drawn')")
        cross = _of(_marks(page), B, "state-blocked", "red", "cross")
        assert len(cross) == 1, _marks(page)

        alive.add("beta")
        finished.add("beta")
        _emit(page, "beta", ("phase_changed", {"from": "blocked", "to": "done"}))
        _until_class(page, "beta", "state-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:beta' && m.state === 'drawn')")
        marks = _marks(page)
        assert _of(marks, B, "is-done", "green", "check")
        assert [m for m in marks if m["lane"] == B and m["shape"] == "cross" and not m["strikeOf"]
                and m["state"] == "struck"], "the cross is struck when the pane is no longer blocked"
        assert not errors, errors

        plain, perrors, asked = _open(browser, port, token, "&ink=off", reduced=True)
        # The plain page's own layout first: its panes open from the rail (`data-tier="rail"`, which
        # the ring's selector leaves out) with their flex and box-shadow transitions running, so the
        # ring is read once beta is off the rail and nothing is animating (train 25: read mid-layout,
        # beta was still `rail` and the ring `none`).
        plain.wait_for_function("""() => document.body.classList.contains('ink-off') && Ink.inspect().plain
            && Ink.inspect().table === 'circuit:solder'
            && document.querySelector('.tile[data-repo="alpha"]').classList.contains('state-error')
            && document.querySelector('.tile[data-repo="beta"]').dataset.tier !== 'rail'
            && !document.getAnimations().some(a => a.playState === 'running')""", timeout=20000)
        got = plain.evaluate("""() => {
          const cs = s => getComputedStyle(document.querySelector(s));
          return { why: cs('.tile[data-repo="alpha"] .why').outlineStyle,
                   ring: cs('.tile[data-repo="beta"] .head .n').boxShadow,
                   canvas: !!document.getElementById('ink'), tile: cs('.tile[data-repo="alpha"]').backgroundColor,
                   panel: getComputedStyle(document.documentElement).getPropertyValue('--panel').trim() }; }""")
        assert not perrors, perrors
        close_pages(browser)
    finally:
        _stop(server)
    assert got["why"] == "solid" and got["ring"] != "none" and not got["canvas"], got
    r, g, b = _rgb(got["panel"])
    assert got["tile"] == f"rgb({r}, {g}, {b})", ("the plain pane is the palette's panel", got)
    assert not [u for u in asked if "/static/ink/layer.js" in u or "three.module" in u], "ink off fetched the layer"


#: The board's pixels behind each pane's transcript, and every pixel inside every word of a pane
#: matching the copper, read back from a frame drawn for the purpose (`Ink.sample`) in one task.
READ_BOARD = """([copper, tol]) => {
  Ink.sample({ x: 0, y: 0, w: 1, h: 1 });
  const c = document.getElementById('ink');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  const k = c.width / innerWidth;
  const read = (x, y, w, h) => {
    const X = Math.max(0, Math.floor(x * k)), Y = Math.max(0, c.height - Math.ceil((y + h) * k));
    const W = Math.max(1, Math.min(c.width - X, Math.ceil(w * k))), H = Math.max(1, Math.min(c.height - Y, Math.ceil(h * k)));
    const px = new Uint8Array(W * H * 4);
    gl.readPixels(X, Y, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return px;
  };
  const near = (px, i) => Math.abs(px[i] - copper[0]) <= tol && Math.abs(px[i + 1] - copper[1]) <= tol
                          && Math.abs(px[i + 2] - copper[2]) <= tol;
  const ground = [], words = { rects: 0, hits: [] };
  for (const t of document.querySelectorAll('#grid .tile')) {
    const r = t.querySelector('.transcript').getBoundingClientRect();
    for (const fy of [0.2, 0.5, 0.8]) for (const fx of [0.1, 0.3, 0.5, 0.7, 0.9]) {
      const px = read(r.left + r.width * fx, r.top + r.height * fy, 1, 1);
      ground.push([px[0], px[1], px[2]]);
    }
    const walk = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      for (const b of range.getClientRects()) {
        if (b.width < 1 || b.height < 1) continue;
        words.rects += 1;
        const px = read(b.left, b.top, b.width, b.height);
        for (let i = 0; i < px.length; i += 4) if (near(px, i)) {
          words.hits.push([t.dataset.repo, n.textContent.slice(0, 20), b.left, b.top]); break; }
      }
    }
  }
  const pads = Object.values(window.__circuit.inspect().panes).map(p => {
    const px = read(p.pad.x + p.pad.w / 2, p.pad.y + p.pad.h / 2, 1, 1);
    return near(px, 0);
  });
  return { ground, words, pads };
}"""

#: How far each pane's board (its frame group, and its trace's far end) is from where the pane is.
BOARD_DRIFT = """() => Object.entries(window.__circuit.inspect().panes).map(([repo, p]) => {
  const r = document.querySelector(`.tile[data-repo="${repo}"]`).getBoundingClientRect();
  return Math.max(Math.abs(r.left - p.at.x), Math.abs(r.top - p.at.y),
                  Math.abs(r.right - 10 - (p.trace.x + p.trace.w)), Math.abs(r.top + 4.25 - p.trace.y));
})"""


@pytest.mark.browser
def test_the_board_reads_inside_its_panel_keeps_copper_off_the_words_follows_a_drag_and_rests(
        fleet_home, tmp_path, desk_browser):
    """The solder mask read back behind every transcript is within [--paper, --board-max]; every
    pad is copper and no pixel inside any word of a pane is; an idle board is zero mutations and
    zero frames; and while the hand holds a gutter every frame that moves a pane has its board where
    the pane is (the :725 pattern), rebuilt to its new width, with the layer writing nothing."""
    _desk(tmp_path, fleet_home, ("alpha", "beta", "gamma"))
    spec = skins.SKINS["circuit"]["variants"]["solder"]
    lo, hi = _rgb(spec["composited_panel"]["darkest"]), _rgb(spec["composited_panel"]["lightest"])
    copper = list(_rgb(_css_block("solder")["copper"]))
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", panes=3, reduced=True)
        _board(page)
        _rest(page, "Ink.inspect().layer.skin.frames === 3 && Object.keys(window.__circuit.inspect().panes).length === 3")
        board = page.evaluate(READ_BOARD, [copper, 8])
        idle = assert_idle(page)

        page.evaluate("""(drift) => {
          window.__follow = { frames: 0, worst: 0 };
          const check = new Function('return (' + drift + ')();');
          new ResizeObserver(() => {
            window.__follow.frames += 1;
            window.__follow.worst = Math.max(window.__follow.worst, ...check(), 0);
          }).observe(document.querySelector('.tile[data-repo="beta"]'));
        }""", BOARD_DRIFT)
        writes = record_mutations(page, where="""r => r.target.id === 'ink' || (r.attributeName === 'style'
          && r.target.style && r.target.style.getPropertyValue('clip-path'))""")
        before = page.evaluate(BOARD_DRIFT)
        x, y = _gutter_point(page, "alpha")
        page.mouse.move(x, y)
        page.mouse.down()
        page.wait_for_function("() => !!gutterHeld", timeout=8000)
        page.mouse.move(x + 120, y, steps=24)
        page.wait_for_function("() => window.__follow.frames >= 3", timeout=8000)
        held = page.evaluate(BOARD_DRIFT)
        page.mouse.up()
        page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
        _rest(page)
        after = page.evaluate(BOARD_DRIFT)
        follow = page.evaluate("() => window.__follow")
        follow["writes"] = writes.stop().records()
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    off = [px for px in board["ground"] if not all(a <= c <= b for a, c, b in zip(lo, px, hi))]
    assert board["ground"] and not off, ("the board reads outside [--paper, --board-max]", lo, hi, off)
    assert board["pads"] == [True] * 3, board["pads"]
    assert board["words"]["rects"] >= 6 and board["words"]["hits"] == [], board["words"]
    assert idle["mutations"] == 0 and idle["renders"] == 0, idle
    assert max(before) < 0.5 and max(held) < 0.5 and max(after) < 0.5, (before, held, after)
    assert follow["frames"] >= 3 and follow["worst"] < 0.5, follow
    assert follow["writes"] == [], f"the layer wrote to the page during the drag: {follow['writes']}"
