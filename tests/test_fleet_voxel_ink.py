"""Voxel on three.js (#256, slice J of the ink epic #246): the voxel skin's decoration drawn by the ink
layer -- the ground as voxels, every pane's frame as a lit slab, and a status stack per pane -- while
`skin.css` keeps the surfaces the module reads, and under `body.ink-off` voxel is the plain look (#257).

What is asserted (docs/skin-voxel.md is the page):

* every variant is drawn by the layer with `?ink=on`, and drawn plain -- the one plain look,
  #257 -- with it off;
* slabs and stacks are instanced, one draw call per material, counted by the renderer, at one agent
  and at twenty;
* each state's voxel response and mark appears with the class `app.js` sets and leaves with it
  (the grammar table), and nothing reads a class the page does not already set;
* the slabs follow a gutter drag in the frame that moves the panes, with no DOM write;
* `theme.check` holds the slab's face (the composited panel) and every ink drawn on it;
* an idle voxel desk writes nothing and draws nothing; the voxels settle in a bounded number of
  frames (one under reduced motion); `dispose` frees them when the skin changes.

The states are real: the server's fold is told what each agent is (`derive`, patched), so the page
draws them exactly as it would draw a real agent -- the tests never set a class `app.js` owns.
"""
from __future__ import annotations
import math
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, registry, serve as S, skins as SK
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from desk_harness import close_pages
from desk_waits import counted, observe_quiet, record_mutations, settle
from test_fleet_ink import _serve, _stop  # noqa: F401 - over the harness's serve_desk; re-exported
from test_fleet_gutters import _gutter_point
from test_fleet_ink import catch_up_frames
from test_fleet_ink_cues import mark_selectors
from test_fleet_ink_fx import _armed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "voxel.js")
SKIN_CSS = os.path.join(STATIC, "skins", "voxel", "skin.css")
DOC = os.path.join(ROOT, "docs", "skin-voxel.md")
VARIANTS = tuple(SK.SKINS["voxel"]["variants"])

#: The module's own view of its materials, read synchronously so a `wait_for_function` can poll it
#: (a predicate's promise is not awaited). `_open` imports it once as `window.__voxel`: the same URL
#: `ink.js` imported, so the same instance.
VOXEL = "() => window.__voxel.inspect()"
IMPORT = "async () => { window.__voxel = await import(q('/static/ink/skins/voxel.js')); }"
#: The voxel skin is on the paper: its predicate for `desk_waits.settle`, which waits for the rest.
ON_PAPER = """() => { const l = Ink.inspect().layer;
  return !!l && !!l.skin && (Ink.inspect().table || '').startsWith('voxel'); }"""


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


class World:
    """What the server's fold says of each agent, for the tests to decide: its state and whether
    its session is stale (#240). Everything downstream -- the row, the classes, the chip -- is the
    desk's own code, so a pane in this world is a pane as the operator would see it."""

    def __init__(self):
        self.states: dict[str, str] = {}
        self.stale: set[str] = set()

    def push(self, *names):
        """Something new on these agents' streams, so the desk folds and draws them again."""
        for name in names:
            E.append(name, [E.event(name, "assistant_text", {"text": "still " + name}, ticket="RDSD-1")])


def _name(events):
    return next((e.get("repo") for e in events if e.get("repo")), "")


@pytest.fixture()
def world(monkeypatch):
    w = World()
    real_derive, real_live, real_lock = S.agentstate.derive, S.supervisor.live, S.supervisor.read_lock
    real_stale = S._stale_cell

    def derive(events, **kw):
        d = real_derive(events, **kw)
        name = _name(events)
        return dict(d, state=w.states[name]) if name in w.states else d

    # A forced agent is a supervised one, so the desk shows its state rather than "nothing is
    # supervised now" (`shownState`), which is what a quiet unsupervised agent would read.
    monkeypatch.setattr(S.agentstate, "derive", derive)
    monkeypatch.setattr(S.supervisor, "live", lambda n: {"external": True} if n in w.states else real_live(n))
    monkeypatch.setattr(S.supervisor, "read_lock",
                        lambda n: {"external": True} if n in w.states else real_lock(n))

    def stale_cell(stream, installed):
        name = _name(stream)
        if name in w.stale:
            return {"stale": True, "unknown": False, "reason": "began on older skills", "skills_changed": []}
        return {"stale": False, "unknown": False, "reason": "", "skills_changed": []}
    monkeypatch.setattr(S, "_stale_cell", stale_cell)
    del real_stale
    return w


def _repos(tmp_path, names, extra=None):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
                 + list((extra or {}).get(name, [])))


def _desk_of(tmp_path, names, extra=None):
    _repos(tmp_path, names, extra)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})


def _skin(fleet_home, name):
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % name, encoding="utf-8")


def _open(browser, port, token, extra="&ink=on", *, panes, width=1600, height=900, reduced=False,
          count=False, family="voxel"):
    """A voxel desk, waited on until every pane has its tier, the skin is on the page and -- where
    the gate is on -- the voxels are on the paper."""
    page = browser.new_page(viewport={"width": width, "height": height},
                            reduced_motion="reduce" if reduced else "no-preference")
    counted(page)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile[data-repo]').length === {panes}
             && [...document.querySelectorAll('#grid .tile[data-repo]')].every(t => !!t.dataset.tier)
             && !!window.Ink && document.body.dataset.skin === '{family}' && windowWrites === 0
             && !document.body.classList.contains('is-stale')""", timeout=20000)
    if family != "voxel":
        return page, errors
    page.evaluate(IMPORT)
    if "ink=on" in extra:
        _rest(page, f"({VOXEL})().panes.length === {panes}")
    return page, errors


def _rest(page, also="true", timeout=20000):
    """Settled (`desk_waits.settle`) with the voxel skin on the paper, and `also` holds. `timeout`
    is kept for its callers; the one ceiling is `DESK_WAIT_MS`."""
    settle(page, also=f"({ON_PAPER})() && ({also})")


def _voxel(page):
    return page.evaluate(VOXEL)


def _stack(page, repo):
    return next(p for p in _voxel(page)["panes"] if p["repo"] == repo)["stack"]


def _marks(page, selector=None):
    got = page.evaluate("() => Ink.inspect().layer.marks")
    return [m for m in got if selector is None or m["selector"] == selector]


def _hex_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


# ============================================================================== without a browser


def _code(path):
    """A script with its comments taken out: what it does, not what it says about itself."""
    src = open(path, encoding="utf-8").read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", src)


def test_the_voxel_module_carries_no_colour_no_import_and_no_markup():
    """Rules 1-3 of docs/desk-ink.md §Writing a skin: no static import (the run token), colours
    from `tokens` and the skin's own custom properties, never a hex in the script; and the page's
    ban on markup."""
    code = _code(MODULE)
    assert not re.search(r"(?m)^\s*import\s", code), "a static import does not carry the run token"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a colour written in the module"
    assert not re.search(r"0x[0-9a-fA-F]{6}\b", code), "a colour written in the module"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "classList.add", "classList.remove",
                   "classList.toggle", "removeAttribute", ".style.", "appendChild"):
        assert banned not in code, f"the voxel skin writes the page: {banned}"
    # `setAttribute` is three.js's, on a geometry; never the page's.
    assert all(m == "g" for m in re.findall(r"\b(\w+)\.setAttribute\(", code)), "the voxel skin writes the page"
    assert not re.search(r"\.(className|textContent|hidden)\s*=[^=]|\.dataset\.\w+\s*=[^=]", code)
    assert "InstancedMesh" in code, "the voxels are instanced"


def _selectors():
    """The mark table's selectors: every `selector:` literal outside the module's `cues` (#373's
    `mark_selectors`; the cue rows are held to their own contract in test_fleet_ink_cues.py)."""
    return mark_selectors(MODULE)


def test_every_class_the_voxel_reads_is_one_the_page_already_sets():
    """Ground rule 2: marks and the stack come from classes `app.js` sets. A class nobody sets
    would be a state the page does not have -- so each one the mark table and the stack read is
    found in `app.js` or the tile's markup, a `state-<state>` is one of the fold's states, and a
    transcript line's class is an event kind the transcript shows."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    code = _code(MODULE)
    read = re.findall(r'classList\.contains\("([\w-]+)"\)|querySelector\("([^"]+)"\)', code)
    selectors = _selectors() + [a or b for a, b in read]
    shown = js[js.index("var SHOWN = {"):]
    shown = shown[:shown.index("};")]
    assert len(_selectors()) == 10, "one row per state the grammar marks"
    for sel in selectors:
        for cls in re.findall(r"\.([A-Za-z][\w-]*)", sel):
            if cls.startswith("state-"):
                assert cls[6:] in agentstate.STATES and '"state-" + state' in js, cls
            elif cls in ("friction", "denied"):
                assert re.search(rf"\b{cls}: 1", shown) and "setClass(li, ev.kind)" in js, cls
            else:
                assert (f'"{cls}"' in js or f'"{cls}' in js or re.search(rf'class="[^"]*\b{cls}\b', html)), cls
        for attr in re.findall(r"\[([\w-]+)", sel):
            # `hidden` is the render contract's `hide`; `aria-pressed` the question card's choice.
            assert attr in ("hidden", "aria-pressed"), attr
    assert 'attr(other, "aria-pressed", String(other === b))' in js, "the chosen answer is pressed"
    assert 'toggle(el, "needs-human"' in js
    # The stack's own reads, in the module's `read`.
    for used in ('"needs-human"', '".oldsession"', '"state-"', "li.friction", "li.denied"):
        assert used in code, used


def test_the_slab_face_is_the_variants_composited_panel():
    """The slab puts the panel behind the text, so the panel `theme.check` measures must be the
    colour the slab draws. The module reads `--voxel-panel`; skin.css sets it per world; skins.py
    declares the composited panel. The three are one number."""
    css = open(SKIN_CSS, encoding="utf-8").read()
    blocks = dict(re.findall(r'body\[data-skin="voxel"\](?:\[data-skin-variant="(\w+)"\])?\s*\{([^}]*)\}', css))
    for variant, spec in SK.SKINS["voxel"]["variants"].items():
        block = blocks.get("" if variant == SK.SKINS["voxel"]["default"] else variant)
        assert block, f"skin.css names no voxel surfaces for {variant}"
        panel = re.search(r"--voxel-panel:\s*(#[0-9A-Fa-f]{6})", block).group(1)
        assert panel.upper() == spec["composited_panel"].upper(), (variant, panel, spec["composited_panel"])
        for name in ("--voxel-ground", "--voxel-edge"):
            assert name in block, (variant, name)


def test_theme_check_holds_every_ink_the_voxel_draws_on_its_slab():
    """Rule 5 of `theme.check` with the voxel's pairs: every ink its table draws with, on the slab
    face (the composited panel) -- 3:1 each, and the text 4.5:1 through the highlighter -- and each
    ink the literal its world's skin.css block writes as `--ink-<tool>` (#334: the highlighter and
    the pen), or else the palette's own token, so the pair checked is the pair drawn."""
    used = set(re.findall(r'tool: "(\w+)"', open(MODULE, encoding="utf-8").read()))
    token = {"pencil": "--muted", "pen": "--accent", "red": "--human", "green": "--done",
             "marker": "--human", "highlighter": "--waiting"}
    css_text = open(SKIN_CSS, encoding="utf-8").read()
    blocks = dict(re.findall(r'body\[data-skin="voxel"\](?:\[data-skin-variant="(\w+)"\])?\s*\{([^}]*)\}', css_text))
    for variant, spec in SK.SKINS["voxel"]["variants"].items():
        inks = spec["inks"]
        assert set(inks) == used, (variant, sorted(inks), sorted(used))
        palette = theme.get(spec["base"])
        css = theme.to_css(palette)
        block = blocks["" if variant == SK.SKINS["voxel"]["default"] else variant]
        said = dict(re.findall(r"--ink-(\w+):\s*(#[0-9A-Fa-f]{6})", block))
        assert {"highlighter", "pen"} <= set(said), (variant, said)
        for tool, colour in inks.items():
            want = said.get(tool, css[token[tool]])
            assert colour.upper() == want.upper(), (variant, tool, colour, want)
        theme.check(palette, composited_panel=spec["composited_panel"], skin=f"voxel:{variant}", inks=inks)


def _shade(colour, k):
    """The module's `shade`: each sRGB channel times `k`, capped at 1."""
    return theme.rgb_to_hex(tuple(min(1.0, c * k) for c in theme.hex_to_rgb(colour)))


#: What an effect piece may wear (#377): the edge, or the panel at the ground's darker shades
#: (`jitter` capped at 1). Never the ground.
PIECE_SHADES = (0.84, 0.92, 1.0)
#: The ground flash's peak (#377): x1.35 would leave Overworld's text at 4.51:1, x1.25 keeps 5.01.
FLASH = 1.25


def test_every_colour_a_voxel_effect_draws_keeps_every_word_readable():
    """#377: a blast's pieces and a break's chips fly under the page's words -- the canvas is behind
    the page -- so every colour a piece may wear keeps each word colour as readable as the slab face
    does (4.5:1, or the panel's own figure where that is lower), in every world. And the ground's
    flash, where the pane was, keeps the text 4.5:1."""
    code = _code(MODULE)
    assert "shade(c.panel, Math.min(1, jitter(" in code and "c.edge" in code, "pieces wear panel and edge"
    assert f"FLASH_UP = {FLASH}" in code
    css_text = open(SKIN_CSS, encoding="utf-8").read()
    blocks = dict(re.findall(r'body\[data-skin="voxel"\](?:\[data-skin-variant="(\w+)"\])?\s*\{([^}]*)\}', css_text))
    low = []
    for variant, spec in SK.SKINS["voxel"]["variants"].items():
        block = blocks["" if variant == SK.SKINS["voxel"]["default"] else variant]
        own = dict(re.findall(r"(--voxel-\w+):\s*(#[0-9A-Fa-f]{6})", block))
        panel, edge, ground = own["--voxel-panel"], own["--voxel-edge"], own["--voxel-ground"]
        css = theme.to_css(theme.get(spec["base"]))
        pieces = [edge] + [_shade(panel, k) for k in PIECE_SHADES]
        for word in ("--text", "--muted", "--human", "--waiting", "--done", "--idle", "--accent"):
            need = min(4.5, theme.contrast_ratio(css[word], panel))
            low += [(variant, word, piece, round(theme.contrast_ratio(css[word], piece), 2))
                    for piece in pieces if theme.contrast_ratio(css[word], piece) < need - 1e-9]
        flash = theme.contrast_ratio(css["--text"], _shade(ground, FLASH))
        if flash < 4.5:
            low.append((variant, "--text", "flash", round(flash, 2)))
    assert low == [], low


def test_the_grammar_is_documented_for_every_state():
    """docs/skin-voxel.md carries the grammar table: every state, its voxel response and its mark."""
    doc = open(DOC, encoding="utf-8").read()
    table = doc[doc.index("## The grammar"):]
    for state in ("needs you", "running", "error", "done", "stale", "answered", "finding"):
        assert re.search(rf"(?mi)^\|\s*{state}\b", table), state
    for sel in _selectors():
        assert f"`{sel}`" in table, sel


# ============================================================================== in a browser


@pytest.mark.browser
def test_every_voxel_variant_is_drawn_by_the_layer_and_plain_without_it(fleet_home, tmp_path, desk_browser):
    """Every world: with the gate on, the ground, the slabs and the stacks are three instanced
    meshes drawn in three calls, the slab's face is the variant's panel, and the page stops
    painting what the slabs paint. With it off, `body.ink-off`: the one plain look every skin
    shares since #257 -- the palette's opaque panel, no texture, no sprite -- and the same mark
    table drawn plain."""
    _desk_of(tmp_path, ("alpha", "beta"))
    server, token, port = _serve()
    seen = {}
    try:
        browser = desk_browser
        for variant in VARIANTS:
            for extra in ("&ink=on", "&ink=off"):
                _skin(fleet_home, f"voxel:{variant}")
                page, errors = _open(browser, port, token, extra, panes=2)
                page.wait_for_function(f"() => Ink.inspect().table === 'voxel:{variant}'", timeout=10000)
                look = page.evaluate("""() => { const t = document.querySelector('.tile[data-repo]');
                  const cs = getComputedStyle(t), chip = getComputedStyle(t.querySelector('.chip'), '::before');
                  return { off: document.body.classList.contains('ink-off'), tile: cs.backgroundColor,
                           border: cs.borderLeftColor, ground: getComputedStyle(document.body).backgroundImage,
                           sprite: chip.display === 'none' || chip.backgroundImage === 'none' ? '' : chip.backgroundImage,
                           plain: Ink.inspect().plain, layer: !!Ink.inspect().layer }; }""")
                look["voxel"] = _voxel(page) if extra == "&ink=on" else None
                seen[(variant, extra)] = look
                assert not errors, errors
                page.close()
        close_pages(browser)
    finally:
        _stop(server)
    for variant in VARIANTS:
        spec = SK.SKINS["voxel"]["variants"][variant]
        on, off = seen[(variant, "&ink=on")], seen[(variant, "&ink=off")]
        v = on["voxel"]
        assert not on["off"] and on["layer"], on
        assert v["materials"] == 3 and all(m["instanced"] for m in v["meshes"]), v["meshes"]
        assert v["drawCalls"] == 3, f"{variant}: {v['drawCalls']} draw calls for three materials"
        assert v["instances"]["ground"] > 100 and v["instances"]["slabs"] > 10 and v["instances"]["stacks"] == 12, v
        assert [round(c * 255) for c in v["panel"]] == _hex_rgb(spec["composited_panel"]), (variant, v["panel"])
        assert on["tile"] == "rgba(0, 0, 0, 0)" and on["border"] == "rgba(0, 0, 0, 0)", on
        assert on["ground"] == "none" and on["sprite"] == "", on
        assert off["off"] and off["plain"] and not off["layer"], off
        plain = theme.to_css(theme.get(spec["base"]))["--panel"]
        assert off["tile"] == "rgb(%d, %d, %d)" % tuple(_hex_rgb(plain)), (variant, off, plain)
        assert off["ground"] == "none" and off["sprite"] == "", off


@pytest.mark.browser
def test_one_draw_call_per_material_at_one_agent_and_at_twenty(fleet_home, tmp_path, desk_browser):
    """#256: a fleet of twenty costs what one costs. The renderer's own count of the back pass
    (`renderer.info.render.calls`, read after the last voxel draw) is three -- ground, slabs,
    stacks -- with one agent on the desk and with twenty, while the instances grow with the panes."""
    names = tuple(f"agent{i:02d}" for i in range(20))
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, names[:1])
    got = []
    for n in (1, 20):
        if n == 20:
            _repos(tmp_path, names[1:])
            S.arrange(order=list(names))
            S.update_window("main", open=names[0], widths={x: 1 for x in names})
        server, token, port = _serve()
        try:
            browser = desk_browser
            page, errors = _open(browser, port, token, panes=n, width=1600)
            got.append(_voxel(page))
            assert not errors, errors
            close_pages(browser)
        finally:
            _stop(server)
    one, twenty = got
    assert one["drawCalls"] == 3 and twenty["drawCalls"] == 3, (one["drawCalls"], twenty["drawCalls"])
    assert one["materials"] == twenty["materials"] == 3
    assert len(twenty["panes"]) == 20 and all(p["at"][2] == 1 for p in twenty["panes"]), twenty["panes"]
    assert twenty["instances"]["stacks"] == 20 * one["instances"]["stacks"], (one["instances"], twenty["instances"])
    assert twenty["instances"]["slabs"] > 10 * one["instances"]["slabs"] / 2, (one["instances"], twenty["instances"])


#: #377's effects, played out: `start(act)` records every layer frame from now until an effect the
#: skin played has ended -- no piece live and no ground voxel flashed -- with the voxel skin's `fx`
#: and draw calls each frame; `act` (a script, or '' when the test acts from Python) runs first.
#: `window.__play` is the promise the test reads once, afterwards.
PLAY = """(act) => { window.__play = (async () => {
  const v = window.__voxel, frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const sum = p => p.blast + p.break + p.place, first = v.inspect();
  const before = first.fx.played, memory = first.memory.geometries;
  if (act) (new Function(act))();
  const samples = [];
  let cuedAt = null, endAt = null;
  for (let i = 0; i < 900 && endAt === null; i++) {
    await frame();
    const x = v.inspect(), f = x.fx, frames = Ink.inspect().layer.frames;
    if (cuedAt === null && sum(f.played) > sum(before)) cuedAt = frames;
    if (cuedAt !== null) samples.push({ frames, live: f.live, flashes: f.flashes, dest: f.dest,
                                        drawCalls: x.drawCalls, pieces: f.pieces });
    if (cuedAt !== null && !f.live && !f.flashes) endAt = frames;
  }
  const x = v.inspect();
  return { before, played: x.fx.played, ends: x.fx.ends, cuedAt, endAt, samples,
           memory: [memory, x.memory.geometries] };
})(); }"""
#: A pane hidden while it is `is-grouped` (folded into its project's rail: `display: none`, and still
#: `:not(.is-hidden)`): the class and the hide in one task, and the arrange write held until the cue
#: has been delivered -- its answer runs `place()`, which takes a class the arrangement does not
#: call for back off, and on a quick server that could land before the layer's next frame.
GROUPED = """async () => {
  const frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const fx = () => Ink.inspect().layer.fx, before = window.__voxel.inspect().fx.played, d0 = fx().delivered;
  let release;
  const hold = new Promise(done => { release = done; });
  arrangeChain = arrangeChain.then(() => hold);
  setHidden('delta', true);
  toggle(tiles.get('delta').el, 'is-grouped', true);
  for (let i = 0; i < 300 && fx().delivered === d0; i++) await frame();
  const grouped = tiles.get('delta').el.classList.contains('is-grouped');
  release();
  return { before, grouped, delivered: fx().delivered - d0 };
}"""
#: The centre of the first element a selector matches, in viewport px.
CENTRE = """(sel) => { const r = document.querySelector(sel).getBoundingClientRect();
  return [r.left + r.width / 2, r.top + r.height / 2]; }"""
#: The ceiling a voxel effect ends within, in layer frames of its cue (#377: 0.8 s at 60 Hz, and 4).
FX_FRAMES = math.ceil(0.8 * 60) + 4


def _play(page, act=""):
    page.evaluate(PLAY, act)


def _played(page):
    return page.evaluate("() => window.__play")


def _worn(page, variant="overworld"):
    """The colours a piece may wear in this world: the edge, or the panel x0.84..1.0 (#377)."""
    css_text = open(SKIN_CSS, encoding="utf-8").read()
    blocks = dict(re.findall(r'body\[data-skin="voxel"\](?:\[data-skin-variant="(\w+)"\])?\s*\{([^}]*)\}',
                             css_text))
    block = blocks["" if variant == SK.SKINS["voxel"]["default"] else variant]
    edge = [c / 255 for c in _hex_rgb(re.search(r"--voxel-edge:\s*(#[0-9A-Fa-f]{6})", block).group(1))]
    panel = _voxel(page)["panel"]
    return [edge] + [[min(1.0, c * k) for c in panel] for k in PIECE_SHADES]


def _pieces_problems(run, worn):
    """Every piece seen mid-effect: flat (bevel 0), spinning about z, in a colour it may wear; and
    the effect drawn in the skin's three draw calls."""
    wrong = []
    for s in run["samples"]:
        if s["live"] and s["drawCalls"] != 3:
            wrong.append(("drawCalls", s["frames"], s["drawCalls"]))
        for q in s["pieces"]:
            if q["bevel"] != 0 or q["spin"] != "z":
                wrong.append(("shape", q))
            if not any(all(abs(a - b) < 1e-6 for a, b in zip(q["c"], w)) for w in worn):
                wrong.append(("colour", q))
    return wrong[:5]


#: Each state and what the grammar (docs/skin-voxel.md) says the voxel and the ink do.
MARK = {
    "needs": ".tile.needs-human .head .repo",
    "question": ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q",
    "card": ".tile.needs-human .asks:not([hidden])",
    "running": ".tile.state-running .head .repo",
    "error": ".tile.state-error",
    "why": ".tile.state-error .why",
    "done": ".tile:is(.state-done, .is-done)",
    "stale": ".tile .oldsession:not([hidden])",
    "answered": '.tile .ask-choice[aria-pressed="true"]',
    "finding": ".tile .transcript li.friction .v, .tile .transcript li.denied .v",
}


def _live(page, selector, lane):
    return [m for m in _marks(page, selector) if m["lane"] == lane and not m["strikeOf"]
            and m["state"] == "drawn"]


@pytest.mark.browser
def test_each_state_has_its_voxel_response_and_its_mark_and_both_leave_with_it(fleet_home, tmp_path, world, desk_browser):
    """The grammar, state by state, driven from the server's fold as a real agent would drive it:
    needs you raises the block and highlights the name and the question; an error cracks it, loops
    the pane and bangs the margin; done sets the stack full and ticks it; running turns the block a
    quarter at a time and underlines the name in pen (#334's grammar); a stale
    session leaves a pebble and a dashed pencil box; a finding puts ore in the stack and a red line
    under the line; an answer chosen is looped. When the state goes, so does its response: the
    block drops, mends, empties; pencil is erased and ink is struck."""
    names = ("alpha", "beta", "gamma", "delta")
    extra = {
        "alpha": [E.event("alpha", "question_opened", {"question": "which window?", "id": "q1",
                                                        "choices": ["left", "right"], "blocking": True},
                          ticket="RDSD-1")],
        "beta": [E.event("beta", "denied", {"message": "a tool it may not run"}, ticket="RDSD-1")],
    }
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, names, extra)
    world.states.update({"alpha": "idle", "beta": "idle", "gamma": "idle", "delta": "idle"})
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _open(browser, port, token, panes=4)
        _armed(page)
        quiet = {n: _stack(page, n) for n in names}

        world.states.update({"alpha": "needs_human", "beta": "error", "gamma": "done", "delta": "running"})
        world.stale.add("alpha")
        world.push(*names)
        page.wait_for_function("""() => ['alpha.state-needs_human.needs-human', 'beta.state-error',
            'gamma.state-done', 'delta.state-running'].every(s => { const [r, ...c] = s.split('.');
            return document.querySelector(`.tile[data-repo="${r}"].` + c.join('.')); })""", timeout=20000)
        page.click('.tile[data-repo="alpha"] .ask-choice')
        _rest(page, f"""(() => {{ const v = ({VOXEL})();
          const s = Object.fromEntries(v.panes.map(p => [p.repo, p.stack]));
          return s.alpha.lift === 5 && s.alpha.stale && s.beta.state === 'error' && s.gamma.level === 3
                 && Ink.inspect().layer.marks.filter(m => m.state === 'drawn').length >= 6; }})()""")
        on = {n: _stack(page, n) for n in names}
        # The next quarter is one timer, re-armed on the frame after it fires; a separate read
        # could land in that one-frame gap on a slow runner (#296). Wait for it to be armed.
        timer = page.wait_for_function(f"() => ({VOXEL})().timer", timeout=10000).json_value()
        marks_on ={k: {n: len(_live(page, sel, "pane:" + n)) for n in names} for k, sel in MARK.items()}
        on_error = _live(page, MARK["error"], "pane:beta")
        # A running block turns: the next quarter comes from a timer, and is drawn.
        page.wait_for_function(f"""() => ({VOXEL})().panes
            .find(p => p.repo === 'delta').stack.turning > 0""", timeout=10000)

        world.states.update({"alpha": "idle", "beta": "idle", "gamma": "idle", "delta": "idle"})
        world.stale.clear()
        world.push(*names)
        second = '.tile[data-repo="alpha"] .ask-choice:nth-child(2)'
        page.click(second)
        # The rest is read once the second answer is on the page and the layer has matched the
        # page since (#517). The layer matches on the animation frame after a mutation, and it
        # queues the new loop and the old mark's strike in that frame: until then it is not
        # busy, and a rest checked in between -- the push above already landed, so the stacks
        # are idle -- passed with the strike not yet begun, and `left` read it under way.
        page.wait_for_function(f"() => document.querySelector({second!r}).getAttribute('aria-pressed') === 'true'",
                               timeout=10000)
        seen = page.evaluate("() => Ink.inspect().layer.frames")
        _rest(page, f"""(() => {{ const v = ({VOXEL})();
          return v.panes.every(p => p.stack.state === 'idle' && p.stack.lift === 0 && !p.stack.stale)
                 && !v.timer && Ink.inspect().layer.frames > {seen}; }})()""")
        off = {n: _stack(page, n) for n in names}
        left = {k: [(m["lane"], m["state"], bool(m["strikeOf"]), m["erased"]) for m in _marks(page, sel)]
                for k, sel in MARK.items()}

        # #377: a pane put away bursts, and its pieces fly to where it went. Hide gamma with its button.
        worn = _worn(page)
        box = page.evaluate("""() => { const r = tiles.get('gamma').el.getBoundingClientRect();
          return { w: r.width, h: r.height }; }""")
        _play(page, "tiles.get('gamma').el.querySelector('[data-tool=\"hide\"]').click();")
        hid = _played(page)
        hid["count"] = page.evaluate(CENTRE, "#hiddencount")
        _rest(page)
        # A pane folded into its project's rail (`is-grouped`, `display: none`) when its cue arrives
        # plays nothing.
        grouped = page.evaluate(GROUPED)
        _rest(page, "document.querySelector('.tile[data-repo=\"delta\"]').classList.contains('is-hidden')")
        grouped_after = _voxel(page)["fx"]["played"]
        # Gone from the registry: to its gone rail.
        Registry().remove("beta")
        _play(page, "refresh();")
        removed = _played(page)
        removed["rail"] = page.evaluate(CENTRE, '#gone .gone-rail[data-repo="beta"]')
        _rest(page)
        # A card closed: the model card, by Escape.
        page.evaluate("() => openModelCard('alpha', null)")
        page.wait_for_selector("#modelcard:not([hidden])", timeout=5000)
        _rest(page)
        _play(page)
        page.keyboard.press("Escape")
        broke = _played(page)
        _rest(page)
        # The hidden count's "show all": one place per pane brought back.
        _play(page)
        page.click("#hiddencount")
        shown = _played(page)
        _rest(page, "document.querySelectorAll('#grid > .tile.is-hidden').length === 0")
        idle_played = _voxel(page)["fx"]["played"]
        idle = observe_quiet(page, passes=3)
        idle["played"] = _voxel(page)["fx"]["played"]
        assert not errors, errors
        page.close()

        # Reduced motion: the slab goes at once, and nothing bursts.
        page, errors = _open(browser, port, token, panes=3, reduced=True)
        _armed(page)
        page.evaluate("() => tiles.get('gamma').el.querySelector('[data-tool=\"hide\"]').click()")
        _rest(page, f"""document.querySelector('.tile[data-repo="gamma"]').classList.contains('is-hidden')
                        && ({VOXEL})().panes.find(p => p.repo === 'gamma').at[2] === 0""")
        still = _voxel(page)["fx"]
        page.evaluate("() => setHidden('gamma', false)")
        _rest(page, "document.querySelectorAll('#grid > .tile.is-hidden').length === 0")
        assert not errors, errors
        page.close()

        # Without the layer: the hide works, and nothing throws.
        page, errors = _open(browser, port, token, "&ink=off", panes=3)
        page.evaluate("() => tiles.get('gamma').el.querySelector('[data-tool=\"hide\"]').click()")
        page.wait_for_function("() => document.querySelector('.tile[data-repo=\"gamma\"]').classList.contains('is-hidden')",
                               timeout=10000)
        settle(page)
        page.evaluate("() => setHidden('gamma', false)")
        settle(page, also="document.querySelectorAll('#grid > .tile.is-hidden').length === 0")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert all(s["level"] == 1 and s["lift"] == 0 and not s["needs"] for s in quiet.values()), quiet
    # the voxel response, per state
    assert on["alpha"]["needs"] and on["alpha"]["lift"] == 5 and on["alpha"]["level"] == 2, on["alpha"]
    assert on["alpha"]["stale"] and not on["gamma"]["stale"], "a stale session wears a pebble"
    assert on["beta"]["state"] == "error" and on["beta"]["finding"], on["beta"]
    assert on["gamma"]["state"] == "done" and on["gamma"]["level"] == 3 and on["gamma"]["lift"] == 0, on["gamma"]
    assert on["delta"]["state"] == "running" and timer, "a running block turns on a timer"
    # the marks, per state, each on its own pane
    assert marks_on["needs"]["alpha"] == 1 and marks_on["needs"]["gamma"] == 0, marks_on["needs"]
    # #335: the pane waiting on the operator is the loudest -- its question card looped in marker --
    # and the error's marker loop is round its why, the bang on the pane.
    assert marks_on["card"] == {"alpha": 1, "beta": 0, "gamma": 0, "delta": 0}, marks_on["card"]
    assert marks_on["error"] == {"alpha": 0, "beta": 1, "gamma": 0, "delta": 0}, marks_on["error"]
    assert marks_on["why"] == {"alpha": 0, "beta": 1, "gamma": 0, "delta": 0}, marks_on["why"]
    assert [m["shape"] for m in on_error] == ["bang"], on_error
    assert marks_on["question"]["alpha"] == 1 and marks_on["question"]["beta"] == 0, marks_on["question"]
    assert marks_on["running"] == {"alpha": 0, "beta": 0, "gamma": 0, "delta": 1}, marks_on["running"]
    assert marks_on["done"] == {"alpha": 0, "beta": 0, "gamma": 1, "delta": 0}, marks_on["done"]
    assert marks_on["stale"]["alpha"] == 1 and marks_on["stale"]["beta"] == 0, marks_on["stale"]
    assert marks_on["answered"]["alpha"] == 1, marks_on["answered"]
    assert marks_on["finding"]["beta"] == 1, marks_on["finding"]
    # and they leave with the state
    assert all(s["level"] == 1 and s["lift"] == 0 and s["state"] == "idle" for s in off.values()), off
    assert not off["alpha"]["stale"] and off["beta"]["finding"], "a finding stays while its line does"
    for key, lane in (("needs", "pane:alpha"), ("question", "pane:alpha"), ("card", "pane:alpha"),
                      ("error", "pane:beta"), ("why", "pane:beta"),
                      ("done", "pane:gamma"), ("running", "pane:delta")):
        assert (lane, "struck") in [m[:2] for m in left[key]], f"{key}: ink leaves by a strike ({left[key]})"
        assert (lane, "drawn") not in [m[:2] for m in left[key]], f"{key}: still drawn ({left[key]})"
    assert not [m for m in left["stale"] if m[1] == "drawn" and not m[3]], f"pencil is erased: {left['stale']}"
    states = [m[1] for m in left["answered"] if m[0] == "pane:alpha"]
    assert "struck" in states and "drawn" in states, f"the first answer struck, the second looped: {left['answered']}"

    # #377, the effects. The hide: exactly one blast, its chunks the pane's box cut into at most
    # 140, each ending within 12px of the hidden count's centre before it pops.
    side = max(12, math.ceil(math.sqrt(box["w"] * box["h"] / 140)))
    chunks = max(1, math.floor(box["w"] / side)) * max(1, math.floor(box["h"] / side))
    print(f"\n  a {box['w']:.0f}x{box['h']:.0f} pane burst into {chunks} pieces; the blast took "
          f"{hid['endAt'] - hid['cuedAt']} frames, the break {broke['endAt'] - broke['cuedAt']}, "
          f"the place {shown['endAt'] - shown['cuedAt']} (ceiling {FX_FRAMES})")
    assert {k: hid["played"][k] - hid["before"][k] for k in hid["played"]} == {"blast": 1, "break": 0, "place": 0}, hid
    assert chunks <= 140 and hid["samples"][0]["live"] == chunks, (chunks, hid["samples"][0]["live"])
    assert hid["ends"]["far"] == 0 and hid["ends"]["near"] == chunks, hid["ends"]
    dest = next(s["dest"] for s in hid["samples"] if s["live"])
    assert max(abs(a - b) for a, b in zip(dest, hid["count"])) <= 1, (dest, hid["count"])
    # A grouped pane plays nothing.
    assert grouped["delivered"] == 1 and grouped["grouped"], grouped
    assert grouped_after == grouped["before"], (grouped, grouped_after)
    # Removed from the registry: to its gone rail.
    assert removed["played"]["blast"] - removed["before"]["blast"] == 1, removed
    dest = next(s["dest"] for s in removed["samples"] if s["live"])
    assert dest and max(abs(a - b) for a, b in zip(dest, removed["rail"])) <= 1, (dest, removed["rail"])
    assert removed["ends"]["far"] == hid["ends"]["far"] == 0, removed["ends"]
    # Escape on the model card: one break. Show all: one place per pane brought back (gamma, delta).
    assert {k: broke["played"][k] - broke["before"][k] for k in broke["played"]} == {"blast": 0, "break": 1, "place": 0}, broke
    assert {k: shown["played"][k] - shown["before"][k] for k in shown["played"]} == {"blast": 0, "break": 0, "place": 2}, shown
    for name, run in (("hide", hid), ("remove", removed), ("break", broke), ("place", shown)):
        # Each ends within the ceiling, in the skin's three draw calls, leaves the GPU's geometry
        # count where it found it, and every piece is flat, spins about z and wears the edge or the panel.
        assert run["endAt"] is not None and run["endAt"] - run["cuedAt"] <= FX_FRAMES, (name, run["cuedAt"], run["endAt"])
        # (A pane removed frees its own frame's geometry as well, so there it may only go down.)
        assert run["memory"][1] == run["memory"][0] or (name == "remove" and run["memory"][1] < run["memory"][0]), \
            (name, run["memory"])
        assert any(s["live"] for s in run["samples"]), name
        assert _pieces_problems(run, worn) == [], (name, _pieces_problems(run, worn))
    # Then the desk is idle again: nothing written, nothing drawn, nothing played.
    assert idle["mutations"] == 0 and idle["renders"] == 0, idle
    assert idle["played"] == idle_played, (idle_played, idle["played"])
    # Reduced motion: the slab went at once, and nothing burst.
    assert still["played"]["blast"] == 0 and still["live"] == 0, still


@pytest.fixture()
def alive(monkeypatch):
    """The agents a process is holding; every other agent is one nothing supervises (#147)."""
    names: set = set()
    real = S.supervisor.live
    monkeypatch.setattr(S.supervisor, "live",
                        lambda name: {"pid": 777, "repo": name} if name in names else real(name))
    return names


#: `R`'s green check, as the layer has it: in `R`'s lane, not a strike, and in what state.
CHECKS = """(r) => Ink.inspect().layer.marks.filter(m => m.lane === 'pane:' + r && m.tool === 'green'
  && m.shape === 'check' && !m.strikeOf).map(m => m.state)"""


@pytest.mark.browser
def test_a_finished_agent_nothing_supervises_is_ticked_and_stacked_full_on_every_variant(fleet_home, tmp_path,
                                                                                       alive, desk_browser):
    """#333: the fold calls an agent done only once nothing supervises it, and the chip draws every
    quiet unsupervised agent as idle -- so the pane is `state-idle is-done` (#253). Voxel keys done
    on both classes, as the paper skins do: a green check in the margin and the stack set full, in
    every world, from the fold's own events. Reduced motion, so the stack is set at once. When the
    agent starts again the check is struck and the stack leaves done."""
    names = ("alpha", "beta")
    finished = [E.event("beta", "phase_changed", {"from": "build", "to": "done"}, ticket="RDSD-1")]
    for name in names:
        Registry().add(make_project(tmp_path / name, phase="done" if name == "beta" else "idle",
                                    ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")]
                 + (finished if name == "beta" else []))
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    server, token, port = _serve()
    seen = {}
    try:
        browser = desk_browser
        for variant in VARIANTS:
            _skin(fleet_home, f"voxel:{variant}")
            page, errors = _open(browser, port, token, panes=2, reduced=True)
            _rest(page, f"""Ink.inspect().table === 'voxel:{variant}' && ({CHECKS})('beta').includes('drawn')
                            && ({VOXEL})().panes.find(p => p.repo === 'beta').stack.state === 'done'""")
            seen[variant] = {"cls": page.evaluate("""() => document.querySelector('.tile[data-repo="beta"]').className"""),
                             "checks": page.evaluate(CHECKS, "beta"),
                             "beta": _stack(page, "beta"), "alpha": _stack(page, "alpha")}
            assert not errors, errors
            if variant != VARIANTS[-1]:
                page.close()
        alive.add("beta")
        E.append("beta", [E.event("beta", "turn_started", {"turn": "1"}, ticket="RDSD-1")])
        page.wait_for_function(
            """() => { if (document.querySelector('.tile[data-repo="beta"].state-running:not(.is-done)'))
                         return true; refresh(); return false; }""", timeout=20000, polling=250)
        _rest(page, f"""!({CHECKS})('beta').includes('drawn')
                        && ({VOXEL})().panes.find(p => p.repo === 'beta').stack.state !== 'done'""")
        again = {"checks": page.evaluate(CHECKS, "beta"), "beta": _stack(page, "beta")}
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    for variant, got in seen.items():
        cls = got["cls"].split()
        assert "state-idle" in cls and "is-done" in cls, (variant, got["cls"])
        assert got["checks"] == ["drawn"], (variant, got["checks"])
        assert got["beta"]["state"] == "done" and got["beta"]["level"] == 3 and got["beta"]["lift"] == 0, \
            (variant, got["beta"])
        assert got["alpha"]["state"] == "idle" and got["alpha"]["level"] == 1, (variant, got["alpha"])
    assert again["checks"] == ["struck"], again
    assert again["beta"]["state"] == "running" and again["beta"]["level"] == 2, again


#: Where each pane is on the page now, against where the voxel skin has put its slab.
SLAB_DRIFT = """(voxel) => { const out = [];
  for (const p of voxel.panes) {
    const r = document.querySelector(`.tile[data-repo="${p.repo}"]`).getBoundingClientRect();
    out.push(Math.max(Math.abs(r.left - p.at[0]), Math.abs(r.top - p.at[1]),
                      Math.abs(r.width - p.w), Math.abs(r.height - p.h)));
  }
  return out; }"""


@pytest.mark.browser
def test_the_slabs_follow_a_gutter_drag_in_the_frame_that_moves_the_panes(fleet_home, tmp_path, desk_browser):
    """While the hand holds a gutter, every frame that moves a pane has its slab where the pane is:
    checked by a ResizeObserver that runs after the layer's, in the same frame, reading where the
    voxel skin last drew each pane. The skin writes nothing to the page to do it."""
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _open(browser, port, token, panes=3, width=1400)
        page.evaluate("""([drift]) => {
          const m = window.__voxel;
          const check = new Function('v', 'return (' + drift + ')(v);');
          window.__follow = { frames: 0, worst: 0 };
          new ResizeObserver(() => {
            const d = check(m.inspect());
            window.__follow.frames += 1;
            window.__follow.worst = Math.max(window.__follow.worst, ...d, 0);
          }).observe(document.querySelector('.tile[data-repo="beta"]'));
        }""", [SLAB_DRIFT])
        writes = record_mutations(page, where="r => r.target.id === 'ink'")
        before = page.evaluate(f"() => ({SLAB_DRIFT})(({VOXEL})())")
        x, y = _gutter_point(page, "alpha")
        page.mouse.move(x, y)
        page.mouse.down()
        page.wait_for_function("() => !!gutterHeld", timeout=8000)
        page.mouse.move(x + 120, y, steps=24)
        page.wait_for_function("() => window.__follow.frames >= 3", timeout=8000)
        page.mouse.up()
        page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
        _rest(page)
        after = page.evaluate(f"() => ({SLAB_DRIFT})(({VOXEL})())")
        follow = page.evaluate("() => window.__follow")
        follow["writes"] = writes.stop().records()
        calls = _voxel(page)["drawCalls"]
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert max(before) < 0.5 and max(after) < 0.5, (before, after)
    assert follow["frames"] >= 3 and follow["worst"] < 0.5, follow
    assert follow["writes"] == [], follow
    assert calls == 3, "a drag moves uniforms, not draw calls"


@pytest.mark.browser
def test_an_idle_voxel_desk_writes_nothing_and_draws_nothing(fleet_home, tmp_path, world, desk_browser):
    """The render contract with the voxels on the paper: an idle desk -- no agent running, so no
    block turning -- is zero DOM mutations and zero WebGL frames."""
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, ("alpha", "beta"))
    world.states.update({"alpha": "needs_human", "beta": "error"})
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _open(browser, port, token, panes=2, count=True)
        _rest(page, f"({VOXEL})().panes.every(p => p.stack.lift === 5)")
        count = observe_quiet(page, passes=8)
        timer = _voxel(page)["timer"]
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert count["mutations"] == 0, f"an idle voxel desk wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle voxel desk was drawn {count['renders']} times"
    assert not timer, "nothing is running, so nothing is scheduled"


#: From the state arriving until the paper is at rest: the layer's frame count at each.
SETTLE = """async () => {
  const m = window.__voxel;
  const up = () => m.inspect().panes.find(p => p.repo === 'alpha').stack;
  return await new Promise(done => {
    let first = null, n = 0;
    const tick = () => {
      const l = Ink.inspect().layer, s = up();
      n += 1;
      if (first === null && s.needs) first = l.frames;
      const rest = !l.busy && !Object.values(l.lanes).some(x => x.hand) && s.lift === 5;
      if ((first !== null && rest) || n > 3000)
        return done({ frames: first === null ? -1 : l.frames - first + 1,
                      marks: l.marks.map(k => [k.id, k.lane, k.drawn, k.selector, k.len, k.strokes]) });
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}"""


@pytest.mark.browser
def test_the_voxels_settle_in_a_bounded_number_of_frames(fleet_home, tmp_path, world, desk_browser):
    """Ground rule 5: counted in frames, not milliseconds. From "needs you" arriving, the block is
    up and the mark drawn within the frames the pen needs for the mark (the layer's own bound) plus
    the block's rise at 60 Hz; and more than one, because it rises. Under reduced motion it is where
    it ends up at once, and nothing is scheduled."""
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, ("alpha", "beta"))
    world.states.update({"alpha": "idle", "beta": "idle"})
    server, token, port = _serve()
    got = {}
    try:
        browser = desk_browser
        for reduced in (False, True):
            world.states["alpha"] = "idle"
            page, errors = _open(browser, port, token, panes=2, reduced=reduced)
            world.states.update({"alpha": "needs_human", "beta": "running" if reduced else "idle"})
            page.evaluate(f"() => {{ window.__settle = ({SETTLE})(); }}")
            world.push("alpha", "beta")
            got[reduced] = page.evaluate("() => window.__settle", )
            got[reduced]["timer"] = _voxel(page)["timer"]
            assert not errors, errors
            page.close()
            world.states.update({"alpha": "idle", "beta": "idle"})
            world.push("alpha", "beta")
        close_pages(browser)
    finally:
        _stop(server)
    moving, still = got[False], got[True]
    rise = math.ceil(5 / 40 * 60) + 2
    bound = catch_up_frames(moving["marks"]) + rise
    print(f"\n  voxels settled in {moving['frames']} frames (bound {bound})")
    assert 3 <= moving["frames"] <= bound, (moving, bound)
    assert 1 <= still["frames"] <= 2, still
    assert not still["timer"], "reduced motion: a running block is not turned"


@pytest.mark.browser
def test_dispose_frees_the_voxels_when_the_skin_changes(fleet_home, tmp_path, desk_browser):
    """The skin going takes its voxels with it: the three meshes' geometry freed on the GPU, no
    timer left behind, and choosing it again builds them afresh -- still three draw calls."""
    _skin(fleet_home, "voxel")
    _desk_of(tmp_path, ("alpha", "beta"))
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors = _open(browser, port, token, panes=2)
        before = _voxel(page)
        page.evaluate("() => post('theme', { skin: 'none' })")
        page.wait_for_function("() => Ink.inspect().table === null", timeout=10000)
        gone = _voxel(page)
        page.evaluate("() => post('theme', { skin: 'voxel:nether' })")
        _rest(page, f"({VOXEL})().panes.length === 2")
        again = _voxel(page)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert before["on"] and not gone["on"] and not gone["timer"], gone
    assert gone["instances"] == {"ground": 0, "slabs": 0, "stacks": 0} and gone["panes"] == [], gone
    assert gone["memory"]["geometries"] <= before["memory"]["geometries"] - 3, (before["memory"], gone["memory"])
    assert again["drawCalls"] == 3 and [p["slot"] for p in again["panes"]] == [1, 2], again
