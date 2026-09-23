"""Glass on three.js (#254, slice H of the ink epic #246): a lit mesh ground, frosted panes that
sample it through a blur, lit glints and shadows, and the state grammar in marks and in the pane.

The skin is `static/ink/skins/glass.js` beside `static/skins/glass/skin.css`, which keeps the
layout, the typography and the whole look under `body.ink-off`. CI draws in SwiftShader, which the
probe calls `software`, so the tests that need glass drawn open the desk with `?ink=on` -- the
layer's override, never a measurement. States are the page's own: `/api/fleet` is answered with
rows in the state wanted, and `app.js` sets every class from them, as it does for a real fleet
(the idle-desk replay in `test_fleet_ink.py`, with rows changed). What is asserted:

* every variant is drawn by the layer (a ground, a frame per pane, the ground sampled) with the
  page's panes transparent over it, and drawn plain -- the CSS glass -- under `body.ink-off`;
* the composited panel `theme.check` measures is READ BACK FROM THE FRAME: the pixels three.js drew
  behind each pane's transcript, their darkest and lightest, checked with the variant's inks;
* the frost samples the ground: a ground split in two shows through each pane on its own side,
  and blurred across the line;
* the ground drifts only when motion is allowed; an idle desk is still zero DOM mutations, and
  under reduced motion zero WebGL frames too;
* each state's marks arrive drawn and leave struck, the pane's rim is drawn round and runs back,
  and the ink settles in a bounded number of frames;
* `dispose` frees the ground's render target when the skin changes.
"""
from __future__ import annotations
import os
import re
import threading

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, registry, serve as S, skins as K
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import AT_REST, COUNT_FETCHES, IDLE_LOOP, catch_up_frames

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
GLASS_JS = os.path.join(STATIC, "ink", "skins", "glass.js")
VARIANTS = tuple(K.SKINS["glass"]["variants"])
NAMES = ("alpha", "beta", "gamma")
#: Luminance, 0-255: the frost's blur at a pane's edge, and the light on the mesh.
TOLERANCE = 14


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a suite
    that gives every test a fresh fleet directory."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})
    monkeypatch.setattr(S, "_measure_asks", {})


def _desk(tmp_path, fleet_home, skin="glass:smoke"):
    """Three panes side by side, each an agent that said one thing, with `skin` chosen."""
    for name in NAMES:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    S.arrange(order=list(NAMES))
    S.update_window("main", open=NAMES[0], widths={n: 1 for n in NAMES})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


def _serve():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _open(browser, port, token, extra="&ink=on", *, reduced=False, count=False):
    page = browser.new_page(viewport={"width": 1400, "height": 900},
                            reduced_motion="reduce" if reduced else "no-preference")
    page.add_init_script(COUNT_FETCHES)
    errors, asked = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(
        """() => document.querySelectorAll('#grid .tile.is-solo').length === 3
             && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
             && !!window.Ink && windowWrites === 0
             && !document.body.classList.contains('is-stale')""", timeout=30000)
    return page, errors, asked


#: The glass skin drawn for `variant`: its table in force, a ground, a frame per pane, and every
#: pane's uniforms painted from the stylesheet (which can land after the module does).
READY = """(v) => { const i = Ink.inspect(), l = i.layer;
  if (i.table !== 'glass:' + v || !l || !l.skin || l.skin.ground !== 1 || l.skin.frames !== 3) return false;
  return window.__glass && window.__glass.inspect().panes.length === 3
    && getComputedStyle(document.body).getPropertyValue('--glass-mesh-1').trim() !== ''
    && window.__glass.inspect().panes.every(p => p.fill.join() === window.__glass.rgba(
         getComputedStyle(document.body).getPropertyValue('--glass-fill')).join()); }"""

#: The skin's module in the page -- the very instance `ink.js` imported, because it is the same URL.
MODULE = """async () => { window.__glass = await import(q('/static/ink/skins/glass.js')); return true; }"""


#: What the page had when it was not ready: the gate, the table, the layer's skin and lanes, the
#: marks still being drawn, and each pane's fill beside the stylesheet's.
WHY = """() => { const i = Ink.inspect(), l = i.layer, cs = getComputedStyle(document.body);
  return { on: i.verdict.on, why: i.verdict.why, table: i.table, skin: l && l.skin, busy: l && l.busy,
           frames: l && l.frames, drawing: l && l.marks.filter(m => m.state === 'queued' || m.state === 'drawing')
             .map(m => m.lane + ' ' + m.selector + ' ' + m.drawn),
           fill: cs.getPropertyValue('--glass-fill').trim(),
           panes: window.__glass ? window.__glass.inspect().panes.map(p => p.repo + ' ' + p.fill.join()) : null }; }"""


def _ready(page, variant, also="true", timeout=30000, rest=True):
    """Glass drawn for `variant` (`READY`), and with `rest` the ink at rest as well: every mark on
    the page drawn. With motion allowed that is a hand's pace counted in frames -- a frame's `dt`
    is held to 0.1s, and the dashed outline round each pane's `old skills` note takes four or five
    -- and in SwiftShader one frame of glass (the ground drawn twice, three panes of frost at
    twenty-one taps a pixel) costs from half a second to several. So `rest` is those frames' cost
    on top of the layer's start, and a test that needs only the glass -- its ground target, its
    panes, their colours -- passes `rest=False`. The dispose test waited for the ink, and on the
    Windows leg the ink's frames ran its first wait past 30s (#254)."""
    page.evaluate(MODULE)
    want = f"(v) => ({READY})(v) && ({AT_REST if rest else '() => true'})() && ({also})"
    try:
        page.wait_for_function(want, arg=variant, timeout=timeout)
    except Exception:
        raise AssertionError(("glass not ready", variant, "at rest" if rest else "drawn", page.evaluate(WHY)))


def _choose(page, skin):
    """The settings page's way: `POST /api/theme {skin}`, which reaches the page as `applySkin`."""
    page.evaluate("s => post('theme', { skin: s })", skin)


#: `/api/fleet` answered from one copy the test can change: `app.js` draws every row from it and
#: sets every class itself, as it would for a fleet whose agents were in those states.
STUB = """async () => {
  if (window.__fleet) return true;
  const real = window.fetch.bind(window);
  window.__fleet = await (await real(q('/api/fleet'))).json();
  // The rows only. The theme in this snapshot is the one chosen when it was taken, and a refresh
  // that replayed it would put an old skin variant back after the test chose another; the page
  // still hears a new theme down its stream.
  delete window.__fleet.theme;
  window.fetch = function (url, opts) {
    if (String(url).indexOf('/api/fleet') >= 0) {
      return Promise.resolve(new Response(JSON.stringify(window.__fleet), {
        status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return real(url, opts);
  };
  return true;
}"""

#: Rows changed, and the page redrawn from them: `{repo: {field: value}}`. A fetch of the real
#: rows still in flight would land after them and put the old states back, so the page's own
#: fetches are waited out first (`COUNT_FETCHES`), and `refresh` is asked twice: the first can be
#: one that began before the stub, and hands back its promise.
PATCH = """async (patches) => {
  for (const row of window.__fleet.repos) Object.assign(row, patches[row.repo] || {});
  for (let i = 0; i < 400 && (window.__inflight || 0) > 0; i++) await new Promise(d => setTimeout(d, 25));
  await refresh(); await refresh(); place(); redrawAll();
  return true;
}"""


def _states(page, patches):
    page.evaluate(STUB)
    page.evaluate(PATCH, patches)


#: A supervised agent in a quiet or busy state: the chip says the state, not "idle".
def _live(state, **more):
    return dict({"state": state, "supervised": True, "not_supervised_sentence": "", "needs_human": False,
                 "asked": []}, **more)


ASKED = [{"id": "q1", "q": "which window should it land in?", "choices": ["left", "right"],
          "default": "", "want": "decision", "assume": "", "blocking": True}]


#: The pixels three.js drew, read back from a frame drawn for the purpose (`Ink.sample` draws one)
#: in the same task, before the browser takes the drawing buffer to the screen. `boxes` are
#: viewport boxes with the points to read in each, as fractions of the box.
READ = """(boxes) => {
  Ink.sample({ x: 0, y: 0, w: 1, h: 1 });
  const c = document.getElementById('ink');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  const k = c.width / innerWidth, px = new Uint8Array(4);
  return boxes.map(b => b.at.map(([fx, fy]) => {
    const x = Math.floor((b.x + b.w * fx) * k), y = c.height - 1 - Math.floor((b.y + b.h * fy) * k);
    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return [px[0], px[1], px[2], px[3]];
  }));
}"""

#: Each pane's transcript: the part of a pane with nothing drawn on it by the page or the ink.
TRANSCRIPTS = """() => [...document.querySelectorAll('#grid .tile .transcript')].map(e => {
  const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; })"""

GRID = [(fx, fy) for fy in (0.2, 0.5, 0.8) for fx in (0.1, 0.3, 0.5, 0.7, 0.9)]


def _lum(rgb):
    return theme.rel_luminance(tuple(c / 255 for c in rgb[:3])) * 255


def _hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


#: Each pane's classes and its chip's, for a failure to say what the page had.
TILES = """() => [...document.querySelectorAll('#grid .tile')].map(t =>
  t.dataset.repo + ': ' + t.className + ' | ' + t.querySelector('.chip').className)"""


def _by(page):
    """The marks on the paper as `(selector, lane, state, is a strike)`."""
    marks = page.evaluate("() => Ink.inspect().layer.marks")
    return [(m["selector"], m["lane"], m["state"], bool(m["strikeOf"])) for m in marks]


def _drawn(marks, selector, lane):
    return any(s == selector and ln == lane and st == "drawn" and not k for s, ln, st, k in marks)


def _struck(marks, selector, lane):
    return any(s == selector and ln == lane and st == "struck" for s, ln, st, k in marks)


def _glass(page):
    return page.evaluate("() => window.__glass.inspect()")


def _rims(page):
    return {p["repo"]: (p["rim"], p["k"]) for p in _glass(page)["panes"]}


# ============================================================================== without a browser


def test_the_glass_module_keeps_the_skin_rules():
    """docs/desk-ink.md §Writing a skin: no static import, no colour written in the module (they come
    from `tokens` and the stylesheet's custom properties), nothing written to the page, and marks
    only on classes the page already sets -- a `state-<x>` for a state the fold has, or a class
    `app.js` or `index.html` names. Glass never adds a state class of its own."""
    js = open(GLASS_JS, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    assert not re.search(r"^\s*import\s", code, re.M), "a static import does not carry the token"
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", code), "a colour written in the module"
    assert not re.search(r"\b0x[0-9A-Fa-f]{6}\b", code), "a colour written in the module"
    for banned in ("classList.add", "classList.remove", "classList.toggle", "setAttribute", ".className",
                   "style.setProperty", "innerHTML", "appendChild", "insertBefore"):
        assert banned not in code, f"the skin writes the page: {banned}"
    page = (open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
            + open(os.path.join(STATIC, "index.html"), encoding="utf-8").read())
    selectors = re.findall(r'selector: "((?:[^"\\]|\\.)*)"', js)
    assert len(selectors) >= 8, selectors
    for sel in selectors:
        for cls in re.findall(r"\.([A-Za-z][\w-]*)", sel):
            if cls.startswith("state-"):
                assert cls[len("state-"):] in agentstate.STATES, (sel, cls)
            else:
                assert re.search(r"\b%s\b" % re.escape(cls), page), (sel, cls, "a class the page does not set")


# ================================================================================ in a browser


@pytest.mark.browser
def test_every_variant_is_drawn_by_the_layer_and_its_panel_is_measured_from_the_frame(fleet_home, tmp_path):
    """Acceptance criterion. Each variant with `?ink=on`: the layer draws a ground and a frame per
    pane from the glass module, samples the ground, and the page's panes go transparent over it.
    Then the composited panel is READ BACK FROM THE FRAME -- the pixels three.js drew behind every
    pane's transcript, twice, the ground having drifted between -- and its darkest and lightest are
    what `theme.check` is run against, with the variant's inks. They sit inside the range skins.py
    declares for the CSS glass (the same mesh, the same fill), and vary across it: the mesh shows
    through, which is the material."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token)
            for variant in VARIANTS:
                _choose(page, f"glass:{variant}")
                # The glass drawn: what is read back is behind each transcript, where no mark is.
                _ready(page, variant, rest=False)
                look = page.evaluate("""() => { const t = getComputedStyle(document.querySelector('#grid .tile'));
                  return { bg: t.backgroundColor, filter: t.backdropFilter, off: document.body.classList.contains('ink-off'),
                           canvas: !!document.getElementById('ink'), skin: Ink.inspect().layer.skin }; }""")
                boxes = [dict(b, at=GRID) for b in page.evaluate(TRANSCRIPTS)]
                assert len(boxes) == 3 and all(b["w"] > 100 and b["h"] > 100 for b in boxes), boxes
                first = page.evaluate(READ, boxes)
                ticks = _glass(page)["frames"]
                page.wait_for_function("n => window.__glass.inspect().frames >= n + 2", arg=ticks, timeout=30000)
                again = page.evaluate(READ, boxes)
                seen[variant] = dict(look=look, px=[c for pane in first + again for c in pane],
                                     moved=first != again)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for variant, got in seen.items():
        spec = K.SKINS["glass"]["variants"][variant]
        look = got["look"]
        assert not look["off"] and look["canvas"], (variant, look)
        assert look["bg"] == "rgba(0, 0, 0, 0)" and look["filter"] == "none", (variant, look)
        skin = look["skin"]
        assert skin["hooks"] == ["ground", "frame", "tick", "dispose"] and skin["sampleGround"], (variant, skin)
        assert skin["ground"] == 1 and skin["frames"] == 3 and skin["errors"] == [], (variant, skin)
        px = got["px"]
        assert all(c[3] == 255 for c in px), (variant, "the ground is opaque under every pane")
        assert got["moved"], (variant, "the ground did not drift between two frames")
        lums = sorted(px, key=_lum)
        darkest, lightest = _hex(lums[0]), _hex(lums[-1])
        lo, hi = (tuple(int(c * 255) for c in theme.hex_to_rgb(spec["composited_panel"][k]))
                  for k in ("darkest", "lightest"))
        print(f"\n  glass:{variant} measured {darkest} .. {lightest}"
              f" (declared {spec['composited_panel']['darkest']} .. {spec['composited_panel']['lightest']})")
        assert _lum(lo) - TOLERANCE <= _lum(lums[0]) and _lum(lums[-1]) <= _lum(hi) + TOLERANCE, \
            (variant, darkest, lightest, "outside the declared range")
        declared = _lum(hi) - _lum(lo)
        assert _lum(lums[-1]) - _lum(lums[0]) >= max(0.75, 0.25 * declared), \
            (variant, "the pane is one colour everywhere: that is paint, not glass")
        base = theme.get(spec["base"])
        for panel in (darkest, lightest):
            theme.check(base, composited_panel=panel, skin=f"glass:{variant} (drawn)", inks=spec["inks"])


@pytest.mark.browser
def test_the_frost_samples_the_ground_through_a_blur(fleet_home, tmp_path):
    """The pane reads `api.groundTexture`, blurred. The glass module's frames over a test ground
    split down the middle, red on the left and blue on the right: the left pane is red, the right
    one blue, and the middle one -- which the line crosses -- is both near the line, because the
    blur reaches across it, and one or the other a blur's width away."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, reduced=True)
            _ready(page, "smoke")
            page.evaluate("""async () => {
              const split = ({ THREE, scene, api }) => {
                const { w, h } = api.viewport;
                [[0xff0000, w / 4], [0x0000ff, 3 * w / 4]].forEach(([c, x]) => {
                  const m = new THREE.Mesh(new THREE.PlaneGeometry(w / 2, h), new THREE.MeshBasicMaterial({ color: c }));
                  m.position.set(x, -h / 2, 0);
                  scene.add(m);
                });
              };
              await Ink.setSkin({ name: 'split', marks: [] }, Object.assign({}, window.__glass, { ground: split }));
            }""")
            page.wait_for_function("""() => { const l = Ink.inspect().layer;
              return Ink.inspect().table === 'split' && l.skin.frames === 3 && l.skin.ground === 2
                && window.__glass.inspect().panes.length === 3; }""", timeout=30000)
            w = page.evaluate("() => innerWidth")
            t = page.evaluate(TRANSCRIPTS)
            mid = t[1]
            line = (w / 2 - mid["x"]) / mid["w"]
            near = 4 / mid["w"]
            far = 60 / mid["w"]
            got = page.evaluate(READ, [dict(t[0], at=[(0.5, 0.5)]), dict(t[2], at=[(0.5, 0.5)]),
                                       dict(mid, at=[(line - near, 0.5), (line + near, 0.5),
                                                     (line - far, 0.5), (line + far, 0.5)])])
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    (left,), (right,), (in_l, in_r, out_l, out_r) = got
    assert left[0] > 3 * left[2] and right[2] > 3 * right[0], (left, right)
    for c in (in_l, in_r):
        assert min(c[0], c[2]) > 0.5 * max(c[0], c[2]), (c, "no blur across the line")
    assert out_l[0] > 2 * out_l[2] and out_r[2] > 2 * out_r[0], (out_l, out_r, "the blur is wider than 18px")


@pytest.mark.browser
def test_the_ground_drifts_only_when_motion_is_allowed_and_the_idle_desk_writes_nothing(fleet_home, tmp_path):
    """The ground is a material and may move (ground rule 1 is about marks): with motion allowed
    its clock runs and the layer draws it, on the ground's own timer, while the page's idle loop
    makes zero DOM mutations. Under reduced motion it stands still, and the idle desk is zero
    mutations and zero WebGL frames, as the layer promises for any skin."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for reduced in (False, True):
                page, errors, _ = _open(browser, port, token, reduced=reduced)
                _ready(page, "smoke")
                before = _glass(page)
                count = page.evaluate(IDLE_LOOP)
                after = _glass(page)
                # And it goes on: the ground's own timer asks for the next frame, and the next.
                # Read as the clock moving again, not as the timer being set -- between its firing
                # and the frame it asked for, it is not.
                if not reduced:
                    page.wait_for_function("c => window.__glass.inspect().clock > c", arg=after["clock"],
                                           timeout=30000)
                seen[reduced] = dict(before=before, after=after, count=count)
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        _stop(server)
    moving, still = seen[False], seen[True]
    assert moving["count"]["n"] == 0, f"an idle glass desk wrote to the page: {moving['count']}"
    assert moving["after"]["clock"] > moving["before"]["clock"] and moving["count"]["renders"] > 0, moving
    assert still["count"]["n"] == 0, f"an idle glass desk wrote to the page: {still['count']}"
    assert still["count"]["renders"] == 0, f"a still ground was redrawn {still['count']['renders']} times"
    assert still["after"]["clock"] == 0 and not still["after"]["timer"], still["after"]


@pytest.mark.browser
def test_each_state_is_marked_on_the_glass_and_leaves_drawn_never_faded(fleet_home, tmp_path):
    """The grammar (docs/skin-glass.md), from the classes app.js sets for the rows it is given.
    needs you: the name and the question highlighted, the rim lit in the human colour. answered:
    the choice circled in pen, and struck when another is chosen. error: a bang, the rim lit.
    done: a green tick, the rim in green. running: the chip underlined, the top glint running.
    stale: the note outlined in dashed pen. A finding: the scope report ringed in red. A state that
    goes is struck (an ink never fades), and the rim that went with it is off. Reduced motion, so
    every step is at rest at once."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    steps = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, reduced=True)
            _ready(page, "smoke")

            def at_rest(also="true"):
                try:
                    page.wait_for_function(f"() => ({AT_REST})() && ({also})", timeout=30000)
                except Exception:
                    raise AssertionError(("not at rest with", also, _by(page), page.evaluate(TILES)))
                return _by(page), _rims(page)

            _states(page, {"alpha": dict(_live("needs_human"), needs_human=True, asked=ASKED),
                           "beta": dict(_live("error"), needs_human=True),
                           "gamma": _live("done", stale={"stale": True})})
            steps["set"] = at_rest("document.querySelectorAll('.tile.state-done').length === 1"
                                   " && Ink.inspect().layer.marks.some(m => m.shape === 'check')")
            page.click('.tile[data-repo="alpha"] .ask-choice >> nth=0')
            steps["picked"] = at_rest("Ink.inspect().layer.marks.some(m => m.shape === 'loop')")
            page.click('.tile[data-repo="alpha"] .ask-choice >> nth=1')
            steps["picked again"] = at_rest("Ink.inspect().layer.marks.filter(m => m.shape === 'loop').length === 2")
            _states(page, {"alpha": _live("idle", stale={"stale": False}),
                           "beta": _live("idle", scope_report={"edited": 3, "outside": ["docs/x.md"]}),
                           "gamma": _live("running")})
            steps["moved on"] = at_rest("document.querySelectorAll('.tile.state-running').length === 1"
                                        " && Ink.inspect().layer.marks.some(m => m.shape === 'ellipse')")
            steps["run"] = page.evaluate("() => window.__glass.inspect().panes.map(p => [p.repo, p.run])")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    marks, rims = steps["set"]
    hl, q = ".tile.needs-human .repo", ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q"
    assert _drawn(marks, hl, "pane:alpha") and _drawn(marks, q, "pane:alpha"), marks
    assert _drawn(marks, ".tile.state-error .head", "pane:beta"), marks
    assert _drawn(marks, ".tile.state-done .head", "pane:gamma"), marks
    assert _drawn(marks, ".tile .oldsession:not([hidden])", "pane:gamma"), marks
    assert rims == {"alpha": ("human", 1), "beta": ("human", 1), "gamma": ("done", 1)}, rims

    choice = '.tile .ask-choice[aria-pressed="true"]'
    marks, _ = steps["picked"]
    assert _drawn(marks, choice, "pane:alpha"), marks
    marks, _ = steps["picked again"]
    assert _struck(marks, choice, "pane:alpha") and _drawn(marks, choice, "pane:alpha"), marks

    marks, rims = steps["moved on"]
    assert _struck(marks, hl, "pane:alpha") and _struck(marks, q, "pane:alpha"), marks
    assert _struck(marks, ".tile.state-error .head", "pane:beta"), marks
    assert _struck(marks, ".tile.state-done .head", "pane:gamma"), marks
    assert _struck(marks, ".tile .oldsession:not([hidden])", "pane:alpha"), marks
    assert _drawn(marks, ".tile .scopereport.outside:not([hidden])", "pane:beta"), marks
    assert _drawn(marks, ".tile.state-running .chip", "pane:gamma"), marks
    assert rims == {"alpha": (None, 0), "beta": (None, 0), "gamma": (None, 0)}, rims
    assert dict(steps["run"]) == {"alpha": 0, "beta": 0, "gamma": 1}, steps["run"]


#: Every frame, until the paper is at rest and alpha's rim has settled: the layer's frame count,
#: whether it is busy, alpha's rim and how far round it is drawn, and the marks' progress.
RIM_RECORD = """async ([want]) => {
  const frames = [];
  return await new Promise(done => {
    const tick = () => {
      const l = Ink.inspect().layer, p = window.__glass.inspect().panes.find(x => x.repo === 'alpha');
      frames.push({ frames: l.frames, busy: l.busy, rim: p.rim, k: p.k,
                    marks: l.marks.filter(m => m.lane === 'pane:alpha' && !m.strikeOf)
                                  .map(m => [m.id, m.lane, m.drawn, m.selector, m.len, m.strokes, m.state]) });
      const settled = want ? p.rim === want && p.k === 1 : p.rim === null;
      if ((frames.length > 3 && !l.busy && settled) || frames.length > 3000) return done(frames);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}"""


@pytest.mark.browser
def test_the_rim_is_drawn_round_and_runs_back_and_the_ink_settles_in_frames(fleet_home, tmp_path):
    """With motion: a pane that comes to need you has its rim drawn round it over several frames,
    never jumping back, and its marks drawn within the frames a hand at the pen's speed needs
    (ground rule 5, counted in frames, not milliseconds). When the state goes the rim runs back
    the way it came -- a material that is taken away the way it was drawn, not faded out."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token)
            _ready(page, "smoke")
            page.evaluate(STUB)
            # The rows changed and the frames recorded from the same task, so the first frame of
            # the rim being drawn is in the record.
            came = page.evaluate("""async (patch) => { (%s)(patch); return await (%s)(['human']); }"""
                                 % (PATCH, RIM_RECORD), {"alpha": dict(_live("needs_human"), needs_human=True)})
            went = page.evaluate("""async (patch) => { (%s)(patch); return await (%s)([null]); }"""
                                 % (PATCH, RIM_RECORD), {"alpha": _live("idle")})
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    ks = [f["k"] for f in came if f["rim"] == "human"]
    assert ks and ks[-1] == 1 and any(0 < k < 1 for k in ks), ks
    assert all(b >= a for a, b in zip(ks, ks[1:])), ("the rim went back while it was drawn", ks)
    last = came[-1]
    drawn = [m for m in last["marks"] if m[6] == "drawn"]
    assert drawn and all(m[2] == 1 for m in drawn), last
    first = next(f for f in came if f["marks"])
    frames = last["frames"] - first["frames"] + 1
    bound = catch_up_frames(drawn)
    print(f"\n  glass ink caught up in {frames} frames (bound {bound})")
    assert 3 <= frames <= bound, (frames, bound, drawn)
    back = [f["k"] for f in went if f["rim"] == "human"]
    assert back and any(0 < k < 1 for k in back), back
    assert all(b <= a for a, b in zip(back, back[1:])), ("the rim ran back unevenly", back)
    assert went[-1]["rim"] is None, went[-1]


@pytest.mark.browser
def test_under_ink_off_every_variant_is_the_css_glass_with_the_same_marks_plain(fleet_home, tmp_path):
    """The gate off (nothing measured): no canvas, no three.js, and the desk is the CSS glass --
    the frost is `backdrop-filter`, the panel its `--glass-fill` -- in every variant, with the
    same mark table drawn plain by the layer's fallback: the name that needs you tinted, the done
    pane's margin barred."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, extra="")
            _states(page, {"alpha": dict(_live("needs_human"), needs_human=True),
                           "gamma": _live("done")})
            for variant in VARIANTS:
                _choose(page, f"glass:{variant}")
                page.wait_for_function("v => Ink.inspect().table === 'glass:' + v && Ink.inspect().plain", arg=variant,
                                       timeout=20000)
                page.wait_for_function("() => getComputedStyle(document.querySelector('#grid .tile')).backdropFilter"
                                       ".includes('blur')", timeout=20000)
                seen[variant] = page.evaluate("""() => {
                  const g = s => getComputedStyle(document.querySelector(s));
                  return { off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink'),
                           layer: Ink.inspect().layer, tile: g('#grid .tile').backgroundColor,
                           fill: getComputedStyle(document.body).getPropertyValue('--glass-fill').trim(),
                           hl: g('.tile[data-repo="alpha"] .repo').backgroundColor,
                           done: g('.tile[data-repo="gamma"] .head').boxShadow }; }""")
            assert not errors, errors
            three = [u for u in asked if "/vendor/three/" in u or "/static/ink/layer.js" in u]
            browser.close()
    finally:
        _stop(server)
    assert not three, three
    for variant, got in seen.items():
        assert got["off"] and not got["canvas"] and got["layer"] is None, (variant, got)
        r, g, b, a = (float(x) for x in re.findall(r"[\d.]+", got["fill"]))
        assert got["tile"] == f"rgba({int(r)}, {int(g)}, {int(b)}, {a:g})", (variant, got)
        assert got["hl"] not in ("rgba(0, 0, 0, 0)", "transparent"), (variant, got)
        assert "inset" in got["done"], (variant, got)


#: A caller's table whose one frame hook reports what the renderer holds and whether a ground
#: texture is still handed out.
PROBE = """async () => {
  window.__after = null;
  await Ink.setSkin({ name: 'probe', marks: [] }, {
    frame({ api }) { window.__after = { textures: api.renderer.info.memory.textures, ground: !!api.groundTexture }; },
  });
}"""


@pytest.mark.browser
def test_dispose_frees_the_ground_target_when_the_skin_changes(fleet_home, tmp_path):
    """The ground texture the frost samples is a render target. When the skin changes, glass's
    `dispose` lets go of everything it kept (its panes, its ground, its timer) and the target is
    freed: the renderer holds fewer textures than it did under glass, no ground texture is handed
    to the next skin, and glass chosen and left again leaves the count where it was."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token)
            for variant in ("smoke", "azure"):
                _choose(page, f"glass:{variant}")
                # The glass drawn, not the ink at rest: what is measured is the ground's target,
                # and no mark holds a texture. Motion stays allowed, so glass keeps a ground timer
                # for `dispose` to clear.
                _ready(page, variant, rest=False)
                on = _glass(page)
                page.evaluate("() => Ink.setSkin(null).then(() => true)")
                gone = _glass(page)
                page.evaluate(PROBE)
                page.wait_for_function("() => !!window.__after", timeout=20000)
                seen[variant] = dict(on=on, gone=gone, after=page.evaluate("() => window.__after"))
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for variant, got in seen.items():
        assert got["gone"] == dict(got["gone"], ground=False, panes=[], timer=False, textures=0), got
        assert got["after"]["ground"] is False, got
        assert got["after"]["textures"] < got["on"]["textures"], ("the ground's target was kept", got)
    assert seen["azure"]["after"]["textures"] == seen["smoke"]["after"]["textures"], seen
