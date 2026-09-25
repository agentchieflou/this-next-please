"""The ink layer (#248, slice B of the ink epic #246): one canvas behind the desk, lanes of drawing,
and marks derived from the classes the page already sets.

B is "everything in plan-ink §The model, and nothing visible changes until a skin uses it". No
shipped skin uses it, so every test here hands the layer a test mark table (`Ink.setSkin`) and sets
classes on panes itself. CI draws in SwiftShader, which the probe classifies `software`, so the gate
would always say off: the tests that need the layer drawing open the desk with `?ink=on`, the
override that exists for exactly this and is never a measurement. What is asserted:

* the gate: only a shell whose probe says `hardware` gets ink, and the page is told by the server,
  from `probe.classify` -- everything else, `?ink=off`, a shell with no WebGL context and a lost
  context are `body.ink-off`, with the same table drawn as plain CSS;
* three.js is fetched from the vendored copy with the token, once, and only when the gate is on AND a
  table is set; the desk with no skin using ink fetches none of the layer and writes nothing;
* `window.Ink` is the whole surface;
* a mark is drawn when its selector starts matching and erased (pencil) or struck (ink) when it
  stops; lanes draw at once and one pane's marks never interleave;
* marks follow a gutter drag in the frame that moves the panes, and a window resize, without the
  layer writing to the page; reduced motion draws at once; an idle desk with ink on the paper is
  still zero DOM mutations;
* ink catches up in frames (ground rule 5), and a gesture keeps its 50ms budget while it draws.
"""
from __future__ import annotations
import gzip
import math
import os
import re
import threading
import urllib.request

import pytest

from agentdata import theme
from agentdata.fleet import events as E, probe as PR, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import _gutter_point

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
INK = os.path.join(STATIC, "ink")
THREE_PATH = "/static/vendor/three/three.module.min.js"
MODULES = ("ink.js", "layer.js", "shapes.js", "pen.js")
#: Ink modules the layer fetches only when a table asks for them: effects (#370), for a skin with them.
LAZY = ("fx.js",)
#: Skin modules (docs/desk-ink.md §Writing a skin): the example, and every skin that draws with ink.
SKINS = tuple(sorted(n for n in os.listdir(os.path.join(INK, "skins")) if n.endswith(".js")))
#: Every script in `static/ink/`, the skins' included, as paths under it.
SCRIPTS = MODULES + LAZY + tuple(f"skins/{n}" for n in SKINS)

#: The page's own budget for a gesture it can answer out of what it already has (#219).
LOCAL_BUDGET_MS = 50.0
#: The pen's speed in the layer (`layer.js` PEN), in CSS px a second at 1x.
PEN = 900
#: What the ink layer's own modules may weigh over the wire. three.js is not in it: 163 KB,
#: fetched only by a shell the gate turned on, once a skin draws. Raised once, from 40 KiB, by #331
#: on the operator's answer in the decisions register (#318, default yes): every later card that
#: grows `ink.js`, `layer.js`, `shapes.js` or `pen.js` fits under it, and one-shot effect code goes
#: to the lazily fetched `ink/fx.js` (#370). It is a figure for the modules as git stores them, LF:
#: a checkout with `core.autocrlf=true` (Windows) is measured with its line endings normalised to LF
#: first (operator decision, #331), so CRLF bytes alone never fail it (`_wire`).
INK_BUDGET = 44 * 1024
#: What the lazily fetched effects module (`ink/fx.js`, #370) may weigh over the wire: every
#: one-shot effect's code (#372-#376) is held to it, outside `INK_BUDGET`.
FX_BUDGET = 8 * 1024
#: What one skin's module may weigh over the wire (the legal pad's is 7 KB, #251).
SKIN_BUDGET = 16 * 1024

INTEL = "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00003EA0) Direct3D11 vs_5_0 ps_5_0, D3D11)"
SWIFTSHADER = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"

#: The test mark table. Nothing shipped uses the layer in slice B; these rows exercise it.
TABLE = {"name": "test", "marks": [
    {"selector": ".tile.ink-loop .head", "tool": "red", "shape": "loop"},
    {"selector": ".tile.ink-hl .repo", "tool": "highlighter", "shape": "lines"},
    {"selector": ".tile.ink-pencil .repo", "tool": "pencil", "shape": "underline"},
    {"selector": ".tile.ink-done .head", "tool": "green", "shape": "check"},
    {"selector": ".tile.ink-write .ticket", "tool": "pencil", "shape": "write"},
]}


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


def _repos(tmp_path, names):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name},
                                ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _desk_of(tmp_path, names=("alpha", "beta")):
    """A desk of `names`, every one of them a pane with a width."""
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})


def _serve():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _facts(**over) -> dict:
    """What `/probe` posts from a shell with a GPU; `over` makes it any other class."""
    body = {"shell": "pycharm", "ua": "Mozilla/5.0 (Windows NT 10.0) JCEF", "webgl": "webgl2",
            "renderer": INTEL, "vendor": "Google Inc. (Intel)", "caveat": False, "three": "160",
            "intervals": [16.6, 16.7, 16.7, 16.8, 16.6, 33.4, 16.7, 16.7, 16.6, 16.7],
            "first_stroke_ms": 131.0, "load_ms": 60.5, "drawn": True, "error": ""}
    body.update(over)
    return body


def _open(browser, port, token, extra="", *, panes=2, width=1400, height=900, reduced=False,
          count=False):
    """A desk page, waited on until every pane has its width and the ink module has run. `panes`
    is how many have a width. `count` counts its fetches in flight, for `IDLE_LOOP`."""
    page = browser.new_page(viewport={"width": width, "height": height},
                            reduced_motion="reduce" if reduced else "no-preference")
    if count:
        page.add_init_script(COUNT_FETCHES)
    errors, asked = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile.is-solo').length === {panes}
             && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
             && !!window.Ink && windowWrites === 0
             && !document.body.classList.contains('is-stale')""", timeout=15000)
    return page, errors, asked


def _set(page, table=None):
    """A test table, set and then waited on until the paper is at rest: with a table in force the
    layer also draws the page's own traces (#257), in the panes' lanes, and a test that times its
    own marks times them from there -- not from behind a trace still being drawn."""
    out = page.evaluate("t => Ink.setSkin(t)", table or TABLE)
    if out and out.get("drawn") == "ink":
        _rest(page)
    return out


def _mark(page, repo, cls, on=True):
    page.evaluate("([r, c, on]) => document.querySelector(`.tile[data-repo=\"${r}\"]`)"
                  ".classList.toggle(c, on)", [repo, cls, on])


def _layer(page):
    return page.evaluate("() => Ink.inspect().layer")


def _marks(page):
    return (_layer(page) or {"marks": []})["marks"]


#: The paper has come to rest: nothing queued or drawing in any lane, and no hand still lifting off.
AT_REST = """() => { const l = Ink.inspect().layer;
  return !!l && !l.busy && !Object.values(l.lanes).some(x => x.hand); }"""


def _rest(page, also="true", timeout=20000):
    page.wait_for_function(f"() => ({AT_REST})() && ({also})", timeout=timeout)


#: Where each mark's anchor is on the page now, against where the layer has its mesh.
DRIFT = """() => { const l = Ink.inspect().layer; const out = [];
  for (const m of l.marks) {
    if (m.strikeOf || !m.visible) continue;
    const els = [...document.querySelectorAll(m.selector)].filter(e =>
      m.lane === 'header' ? !e.closest('.tile') : e.closest('.tile').dataset.repo === m.lane.slice(5));
    const r = els[0].getBoundingClientRect();
    out.push(Math.max(Math.abs(r.left - m.box.x), Math.abs(r.top - m.box.y),
                      Math.abs(r.width - m.box.w), Math.abs(r.height - m.box.h)));
  }
  return out; }"""


# ============================================================================== without a browser


def test_the_ink_modules_write_no_markup():
    """Ground rule 4: the page's ban on `innerHTML` holds for the new code too -- skins included."""
    for name in SCRIPTS:
        body = open(os.path.join(INK, name), encoding="utf-8").read()
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert banned not in body, f"ink/{name} uses {banned}"


def test_the_layer_is_the_one_place_three_is_imported_and_every_import_carries_the_token():
    """A module specifier resolved against a file's URL does not carry the run token, and every
    route here wants it -- so nothing in `static/ink/` imports statically, and three.js is named by
    `layer.js` alone, through `q()`, from the vendored copy. A skin is handed three.js."""
    for name in SCRIPTS:
        body = open(os.path.join(INK, name), encoding="utf-8").read()
        assert not re.search(r"(?m)^\s*import\s[^(]", body), f"ink/{name} has a static import"
        for spec in re.findall(r"import\(([^)]*\))", body):
            assert spec.startswith("q("), f"ink/{name} imports {spec} without the token"
        if name == "layer.js":
            assert f'const VENDOR = "{THREE_PATH}";' in body and "import(q(VENDOR))" in body
        else:
            assert "vendor/three" not in body and "three.module" not in body, name
    # The desk names the front door and nothing else of the layer; the other pages not even that.
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert '<script type="module" src="/static/ink/ink.js"></script>' in html
    assert "ink/ink.js" in S.ASSETS
    for other in ("settings.html", "probe.html"):
        assert "/static/ink/" not in open(os.path.join(STATIC, other), encoding="utf-8").read()
    app = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    for needle in ("webgl", "vendor/three", "three.module", "ink/layer.js"):
        assert needle not in app.lower(), f"app.js names {needle}: the layer is `window.Ink` to it"


def _wire(body: bytes) -> int:
    """A module's gzipped size as `INK_BUDGET` counts it: line endings normalised to LF (what git
    stores) before gzip level 6 with `mtime=0`, so a CRLF checkout measures what an LF one does
    (operator decision, #331)."""
    return len(gzip.compress(body.replace(b"\r\n", b"\n"), 6, mtime=0))


def test_a_crlf_checkout_of_the_ink_modules_measures_what_an_lf_one_does():
    """A Windows checkout with `core.autocrlf=true` holds the modules with CRLF endings, about 190
    bytes more gzipped than LF. The budget measures what git stores, so the two are one figure
    (operator decision, #331), where a gzip of the raw CRLF bytes is not."""
    for n in MODULES:
        lf = open(os.path.join(INK, n), "rb").read().replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        assert b"\r\n" in crlf and _wire(crlf) == _wire(lf), n
        assert len(gzip.compress(crlf, 6, mtime=0)) > len(gzip.compress(lf, 6, mtime=0)), n


def test_the_ink_payload_is_inside_its_budget_and_three_is_not_in_it():
    """What the layer's own modules cost over the wire, every one of them, as a shell the gate
    turned on fetches them. three.js is 163 KB of its own and is outside the desk's budget, because
    no desk fetches it unless it draws. The lazy modules (`LAZY`: `fx.js`, #370) are fetched only
    by a table that asks for them, so each has a budget of its own and is not in `INK_BUDGET`."""
    sizes = {n: _wire(open(os.path.join(INK, n), "rb").read()) for n in MODULES}
    print(f"\n  ink modules over the wire: {sum(sizes.values())} bytes gzipped {sizes}")
    assert sum(sizes.values()) < INK_BUDGET, sizes
    fx = _wire(open(os.path.join(INK, "fx.js"), "rb").read())
    print(f"  fx.js over the wire: {fx} bytes gzipped")
    assert fx < FX_BUDGET, fx
    files = sorted(n for n in os.listdir(INK) if os.path.isfile(os.path.join(INK, n)))
    assert files == sorted(MODULES + LAZY), "a module no budget counts"
    assert sorted(os.listdir(INK)) == sorted(MODULES + LAZY + ("skins",))
    # A skin module is fetched only by the desk that chose it, one at a time: not the layer's cost.
    # Every one but the example is a skin skins.py offers (#249-#256 ship them).
    from agentdata.fleet import skins as K
    assert "example.js" in SKINS and all(n[:-3] in K.SKINS for n in SKINS if n != "example.js"), SKINS
    # And each is held to a budget of its own (#251).
    for name in SKINS:
        size = len(gzip.compress(open(os.path.join(INK, "skins", name), "rb").read(), 6, mtime=0))
        assert size < SKIN_BUDGET, (name, size)


def test_the_gate_is_the_probe_rule_and_nothing_else(fleet_home):
    """`probe.ink_gate` is `classify` of the shell's one record, and `works` of it. The page gets
    exactly that, so the four columns of desk-engines.md and the ink layer cannot disagree."""
    shells = {"pycharm": _facts(), "vscode": _facts(renderer=SWIFTSHADER),
              "edge": _facts(webgl="none", renderer=""), "chromium": _facts(renderer=""),
              "left": _facts(hidden=True)}
    for shell, body in shells.items():
        PR.record(dict(body, shell=shell))
    probes = PR.load()
    for shell in shells:
        gate = PR.ink_gate(shell)
        assert gate == {"shell": shell, "class": PR.classify(probes[shell]),
                        "works": PR.works(probes[shell])}, gate
    assert [s for s in shells if PR.ink_gate(s)["works"]] == ["pycharm"]
    assert PR.ink_gate("browser") == {"shell": "browser", "class": "unmeasured", "works": False}
    # Not a shell name: nothing measured it, and nothing of it reaches the page.
    assert PR.ink_gate("<b>x</b>") == {"shell": "", "class": "unmeasured", "works": False}


def test_the_server_writes_the_probe_class_on_the_desk_and_nowhere_else(fleet_home):
    """The verdict reaches the page before any script runs, as two words on `<body>`, and is the
    class of the record for this window's shell: `shell=`, else `w=`, else `browser` -- the name
    `probe.js` files it under."""
    PR.record(_facts(shell="pycharm"))
    PR.record(_facts(shell="vscode", renderer=SWIFTSHADER))
    server, token, port = _serve()
    try:
        def body_of(query):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/{query}&t={token}",
                                        timeout=10) as r:
                html = r.read().decode("utf-8")
            return re.search(r"<body[^>]*>", html).group(0)

        def gate(query):
            return re.search(r'data-ink-shell="([^"]*)" data-ink-probe="([^"]*)"',
                             body_of(query)).groups()
        assert gate("?w=pycharm") == ("pycharm", "hardware")
        assert gate("?w=vscode") == ("vscode", "software")
        assert gate("?w=left&shell=pycharm") == ("pycharm", "hardware")
        assert gate("?x=1") == ("browser", "unmeasured")
        assert gate('?w="><script>') == ("", "unmeasured")
        # And the skins that ship a module: the example, which skins.py does not offer, and every
        # skin that draws with ink (#249-#256).
        assert f'data-ink-skins="{" ".join(S.ink_skins())}">' in body_of("?x=1")
        assert S.ink_skins() == sorted(n[:-3] for n in SKINS), S.ink_skins()
        for other in ("settings?x=1", "probe?x=1"):
            assert "data-ink" not in body_of(other), other
        # The map (#405) is told the same facts, for its scene (#409), and keeps `ink-off`.
        mapped = body_of("map?w=pycharm")
        assert 'data-ink-shell="pycharm" data-ink-probe="hardware"' in mapped, mapped
        assert f'data-ink-skins="{" ".join(S.ink_skins())}"' in mapped, mapped
        assert mapped.startswith('<body class="ink-off"'), mapped
        # Compressed once per shell and class, not once for every window: two shells, two pages.
        asked = [urllib.request.Request(f"http://127.0.0.1:{port}/?w={w}&t={token}",
                                        headers={"Accept-Encoding": "gzip"})
                 for w in ("pycharm", "vscode")]
        pages = []
        for req in asked:
            with urllib.request.urlopen(req, timeout=10) as r:
                pages.append(gzip.decompress(r.read()).decode("utf-8"))
        assert 'data-ink-probe="hardware"' in pages[0] and 'data-ink-probe="software"' in pages[1]
    finally:
        _stop(server)


def test_theme_check_holds_ink_on_paper():
    """#248 brings the mechanism `theme.check` needs for the paper skins: every ink a skin draws is
    a mark on its paper (3:1), and the highlighter is read through (the text keeps 4.5:1 on its
    tint). The pairs themselves arrive with the skins (#249-#253)."""
    # The prototype's two notebooks: light paper with its inks, and the night one with its gel inks.
    light, paper = theme.get("sand"), "#FBFBF6"
    theme.check(light, composited_panel=paper, inks={
        "pencil": "#50545C", "pen": "#22398F", "red": "#C8352B", "green": "#2E7A4D",
        "highlighter": "#F3DF4B"})
    dark = theme.get("dark")
    theme.check(dark, inks={"pencil": "#B5BAC4", "pen": "#94B4FF", "red": "#FF6A5E",
                            "green": "#6FD39A", "highlighter": "#E6D548"})
    with pytest.raises(theme.ThemeError) as e:
        theme.check(light, composited_panel=paper, inks={"pencil": "#C9CCD0"})
    assert "ink 'pencil'" in e.value.args[0] and "below 3:1" in e.value.args[0]
    # A white highlighter on the night page washes the text out: 4.06:1 through it.
    with pytest.raises(theme.ThemeError) as e:
        theme.check(dark, inks={"highlighter": "#FFFFFF"})
    assert "through the highlighter" in e.value.args[0]
    # No inks is the check it always was.
    theme.check(light, composited_panel=paper)


# ================================================================================ in a browser


@pytest.mark.browser
def test_the_desk_with_no_skin_using_ink_is_unchanged(fleet_home, tmp_path):
    """Nothing visible changes in slice B. With the gate off (nothing measured) and with it forced
    on, a desk no skin draws on fetches none of the layer, puts no canvas on the page, adopts no
    stylesheet and -- idle -- writes nothing at all."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for extra, off in (("", True), ("&ink=on", False)):
                page, errors, asked = _open(browser, port, token, extra, count=True)
                state = page.evaluate("""() => ({
                  ink: !!document.getElementById('ink'), sheets: document.adoptedStyleSheets.length,
                  off: document.body.classList.contains('ink-off'), inspect: Ink.inspect(),
                  canvases: [...document.querySelectorAll('canvas')].map(c => c.id || c.className),
                  // What `body.ink-off` could change on its own: nothing, while no table is set.
                  keyed: [...document.styleSheets].flatMap(s => [...s.cssRules].map(r => r.cssText))
                           .filter(t => t.includes('ink-off')) })""")
                assert state["off"] is off, (extra, state)
                assert not state["ink"] and state["sheets"] == 0 and state["keyed"] == [], state
                assert state["inspect"]["layer"] is None and state["inspect"]["plain"] is False
                assert "ink" not in state["canvases"], state
                fetched = [u.split("?")[0].split(str(port))[1] for u in asked if "/static/" in u]
                assert [u for u in fetched if u.startswith("/static/ink/")] == ["/static/ink/ink.js"]
                assert not [u for u in fetched if "vendor/three" in u], fetched
                # And idle is idle: the panes test's loop, with the layer's module on the page.
                count = page.evaluate(IDLE_LOOP)
                assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        _stop(server)


#: Every fetch the page makes, counted while it is in flight -- so the idle loop below starts only
#: once no answer the page asked for before the replay can still land in the middle of it.
COUNT_FETCHES = """
  window.__inflight = 0;
  const realFetch = window.fetch;
  window.fetch = function () {
    window.__inflight += 1;
    return realFetch.apply(this, arguments).finally(() => { window.__inflight -= 1; });
  };
"""

#: The idle desk (`test_fleet_panes`): `/api/fleet` replayed byte for byte, every path drawn once,
#: then eight more passes watched by a MutationObserver over the whole document. Opened with
#: `COUNT_FETCHES`, it first waits for every live answer already asked for: a refresh the stream
#: started just before the replay would otherwise bring a newer age into the watched passes.
IDLE_LOOP = """async () => {
  const pause = ms => new Promise(done => setTimeout(done, ms));
  const frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const real = window.fetch.bind(window);
  const body = await (await real(q('/api/fleet'))).text();
  window.fetch = function (url, opts) {
    if (String(url).indexOf('/api/fleet') >= 0) {
      return Promise.resolve(new Response(body, {
        status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return real(url, opts);
  };
  for (let i = 0; i < 400 && (window.__inflight || 0) > 0; i++) await pause(25);
  await refresh(); place(); redrawAll(); bell();
  await frame(); await frame(); await pause(200);
  // The warm-up refresh above applies a body the server built just now, and a trace that moved on
  // a minute since the page's last poll is drawn by the layer (#257) -- a frame that can land after
  // two frames on a slow runner. Settle first: the layer at rest, and no render across a frame. A
  // ground that moves never settles, so this is bounded.
  for (let i = 0, was = -1; i < 40; i++) {
    const l = Ink.inspect().layer;
    if (!l || (!l.busy && l.renders === was)) break;
    was = l.renders;
    await frame(); await pause(50);
  }
  const before = Ink.inspect().layer;
  let n = 0;
  const seen = [];
  const obs = new MutationObserver(records => {
    n += records.length;
    records.slice(0, 5).forEach(r => seen.push(r.type + ' ' + (r.attributeName || '') + ' ' +
                                               (r.target.id || r.target.className || r.target.nodeName)));
  });
  obs.observe(document.documentElement, { subtree: true, childList: true, attributes: true,
                                          characterData: true });
  for (let i = 0; i < 8; i++) { await refresh(); place(); redrawAll(); bell(); await frame(); await pause(150); }
  obs.takeRecords().forEach(() => { n += 1; });
  obs.disconnect();
  const after = Ink.inspect().layer;
  return { n, seen, renders: before && after ? after.renders - before.renders : 0 };
}"""


@pytest.mark.browser
def test_the_layer_fetches_three_once_from_the_vendored_copy_with_the_token(fleet_home, tmp_path):
    """Only when the gate is on AND a skin draws: the layer's modules and the vendored three.js,
    each once, each with this run's token, and one canvas behind the page -- a second table does
    not make a second."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, "&ink=on")
            assert not [u for u in asked if "/static/ink/layer.js" in u or "vendor/three" in u]
            assert _set(page)["drawn"] == "ink"
            assert _set(page, dict(TABLE, name="again"))["drawn"] == "ink"
            canvas = page.evaluate("""() => { const c = document.querySelectorAll('canvas#ink');
              const s = getComputedStyle(c[0]);
              return { n: c.length, position: s.position, z: s.zIndex, events: s.pointerEvents,
                       hidden: c[0].getAttribute('aria-hidden'), last: document.body.lastElementChild.id,
                       width: c[0].width, inner: innerWidth * Math.min(2, devicePixelRatio || 1) }; }""")
            assert canvas["n"] == 1 and canvas["position"] == "fixed" and canvas["z"] == "-1", canvas
            assert canvas["events"] == "none" and canvas["hidden"] == "true", canvas
            assert canvas["width"] == canvas["inner"], canvas
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    fetched = [u.split(str(port))[1] for u in asked if "/static/" in u]
    three = [u for u in fetched if "three" in u]
    assert three == [f"{THREE_PATH}?t={token}"], three
    for name in MODULES:
        assert fetched.count(f"/static/ink/{name}?t={token}") == 1, (name, fetched)
    assert all(f"t={token}" in u for u in fetched), fetched
    assert all(u.startswith(f"http://127.0.0.1:{port}/") for u in asked), "fetched off the desk"


@pytest.mark.browser
def test_window_ink_is_the_only_surface_and_refuses_a_table_it_cannot_draw(fleet_home, tmp_path):
    """`app.js` will see the layer through `window.Ink` and nothing else. A mistake in a skin is an
    exception at the call that made it, naming the row -- never a mark that silently never comes."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            api = page.evaluate("""async () => {
              const shapes = await import(q('/static/ink/shapes.js'));
              const pen = await import(q('/static/ink/pen.js'));
              const bad = [];
              for (const row of [{selector: '.tile', tool: 'crayon', shape: 'loop'},
                                 {selector: '.tile', tool: 'pen', shape: 'star'},
                                 {selector: '.tile[', tool: 'pen', shape: 'loop'},
                                 {selector: '.tile', tool: 'eraser', shape: 'loop'},
                                 {selector: '.tile', tool: 'pen', shape: 'arrow'},
                                 {tool: 'pen', shape: 'loop'},
                                 {selector: '.tile', tool: 'pencil', ink: 'crayon', shape: 'loop'},
                                 {selector: '.tile', tool: 'pencil', shape: 'loop', cap: 'arrow'},
                                 {selector: '.tile', tool: 'pencil', shape: 'underline', cap: 'arrow', tip: true}]) {
                try { Ink.setSkin({ name: 'bad', marks: [{selector: '.x', tool: 'pen', shape: 'loop'}, row] }); bad.push('accepted'); }
                catch (e) { bad.push(e.message); }
              }
              // The hand is on, off or a stick of chalk (#387): a table's own option, not a row's.
              let hand = 'accepted';
              try { Ink.setSkin({ name: 'bad', hand: 'crayon', marks: [{selector: '.x', tool: 'pen', shape: 'loop'}] }); }
              catch (e) { hand = e.name + ': ' + e.message; }
              return { keys: Object.keys(Ink).sort(), frozen: Object.isFrozen(Ink),
                       ready: await Ink.ready, enabled: Ink.enabled, tools: Ink.tools, shapes: Ink.shapes,
                       layerShapes: shapes.SHAPE_NAMES, penTools: Object.keys(pen.TOOLS), bad, hand,
                       table: Ink.inspect().table };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert api["frozen"] and api["keys"] == sorted(["ready", "enabled", "verdict", "tools", "shapes",
                                                    "setSkin", "refresh", "off", "inspect", "sample"])
    assert api["ready"]["on"] is True and api["ready"]["source"] == "override" and api["enabled"]
    assert sorted(api["shapes"]) == sorted(api["layerShapes"]) == sorted(
        ["outline", "divider", "underline", "lines", "loop", "ellipse", "ring", "strike", "check", "bang",
         "cross", "arrow", "write"])
    assert sorted(api["tools"]) == sorted(["pencil", "pen", "red", "green", "marker", "highlighter"])
    assert set(api["penTools"]) == set(api["tools"]) | {"eraser"}
    assert all(m.startswith("ink: mark 1") for m in api["bad"]), api["bad"]
    assert "crayon" in api["bad"][0] and "star" in api["bad"][1] and "selector" in api["bad"][2]
    assert "eraser" in api["bad"][3] and "`to`" in api["bad"][4] and "no selector" in api["bad"][5]
    assert "crayon" in api["bad"][6] and "`ink`" in api["bad"][6] and "`cap`" in api["bad"][7] and "`cap`" in api["bad"][8]
    assert api["hand"].startswith("TypeError: ") and "`hand`" in api["hand"] and "crayon" in api["hand"], api["hand"]
    assert api["table"] is None, "a refused table replaced the one in force"


#: A row whose outline stands 20px off its pane, which only the pane's clip keeps inside it (#331).
CLIPPED = {"name": "clip", "marks": [
    {"selector": ".tile.ink-loop", "tool": "red", "shape": "outline", "pad": 20}]}


@pytest.mark.browser
def test_a_mark_is_clipped_to_its_pane(fleet_home, tmp_path):
    """#331: a mark in a pane's lane is cut to the pane's border box, inset 1px, as well as to the
    viewport and its scrolling ancestors -- a safety net under the shapes, which keep their own
    geometry inside. An outline padded 20px off the pane is drawn, and none of it outside."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page, CLIPPED)
            _mark(page, "alpha", "ink-loop")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'outline' && m.drawn === 1)")
            [mark] = _marks(page)
            pane = page.evaluate("""() => { const r = document.querySelector('.tile[data-repo="alpha"]')
              .getBoundingClientRect(); return { x: r.left, y: r.top, r: r.right, b: r.bottom }; }""")
            # The right-hand stroke stands 20px past the pane's right edge: where it would be drawn.
            outside = page.evaluate("b => Ink.sample(b)", {"x": pane["r"] + 2, "y": pane["y"] + 4,
                                                           "w": 28, "h": pane["b"] - pane["y"] - 8})
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # Drawn whole -- four strokes, their full length -- and every one of them is outside the pane,
    # so what is drawn of them, `bounds`, is nothing past its border box.
    assert (mark["lane"], mark["strokes"], mark["drawn"]) == ("pane:alpha", 4, 1) and mark["len"] > 0, mark
    for b in mark["bounds"]:
        assert pane["x"] - 1 <= b["x"] and b["r"] <= pane["r"] + 1, (b, pane)
        assert pane["y"] - 1 <= b["y"] and b["b"] <= pane["b"] + 1, (b, pane)
    assert outside == 0, "ink drawn past the pane's right edge"


@pytest.mark.browser
def test_snap_keeps_an_outline_in_the_padding_band_and_leaves_an_underline_with_no_line_alone(fleet_home, tmp_path):
    """#331, `shapes.snap` in the page: an outline's edges go onto a grid line inside the box's
    padding band, or down its middle where the band is narrower than a square -- never outside the
    border box, never over the content. An underline takes the first grid line in [its text's foot
    + 2, the next row's top - 2], and is left as it was when there is none."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            got = page.evaluate("""async () => {
              const S = await import(q('/static/ink/shapes.js'));
              const box = { x: 0, y: 0, w: 300, h: 200 }, at = { x: 13, y: 17 };
              const outline = band => S.snap(S.SHAPES.outline({ box, pad: 0, seed: 7 }), 'outline', box, at, 28,
                                             { band: [band, band, band, band] }).map(p => p.pts);
              const ubox = { x: 0, y: 0, w: 100, h: 16 };
              const under = S.SHAPES.underline({ box: ubox, base: 16, floor: 30 });
              return { narrow: outline(10), wide: outline(40), under,
                       none: S.snap(under, 'underline', ubox, { x: 0, y: 15 }, 28, { base: 16, floor: 30 }),
                       some: S.snap(under, 'underline', ubox, { x: 0, y: 0 }, 28, { base: 16, floor: 40 }) };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    L, T, R, B = 13, 17, 313, 217

    def edges(strokes, band):
        out = []
        for pts in strokes:
            vp = [(x + L, y + T) for x, y in pts]
            assert all(L <= x <= R and T <= y <= B for x, y in vp), ("outside the border box", vp)
            flat = abs(vp[-1][0] - vp[0][0]) >= abs(vp[-1][1] - vp[0][1])
            vals = {round(y if flat else x, 3) for x, y in vp}
            assert len(vals) == 1, ("not ruled straight", vp)
            v = vals.pop()
            lo, hi = (T, B) if flat else (L, R)
            assert lo <= v <= lo + band or hi - band <= v <= hi, ("outside the padding band", v, band)
            out.append(v)
        return out

    # A 10px band, a 28px pitch: every edge down its band's middle.
    assert sorted(edges(got["narrow"], 10)) == [18, 22, 212, 308], got["narrow"]
    # A 40px band holds a grid line: every edge on one.
    assert all(v % 28 == 0 for v in edges(got["wide"], 40)), got["wide"]
    # No grid line in [15 + 18, 15 + 28] = [33, 43]: the underline is left where it was.
    assert got["none"] == got["under"]
    # [18, 38] holds 28: the underline is ruled on it.
    assert all(q[1] == 28 for path in got["some"] for q in path["pts"]), got["some"]


@pytest.mark.browser
def test_a_mark_is_drawn_when_its_class_appears_and_erased_or_struck_when_it_goes(fleet_home, tmp_path):
    """Ground rules 1 and 2. The class is the truth: added, the mark is drawn -- there is ink in its
    box; removed, a pencil mark is erased (gone, and its box clean) and an ink mark is struck
    through with one pen line, which stays. Back before the eraser reached it, it simply stays."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page, dict(TABLE, speed=3))
            _mark(page, "alpha", "ink-pencil")
            _mark(page, "beta", "ink-hl")
            _rest(page, "Ink.inspect().layer.marks.length === 2")
            by = {m["tool"]: m for m in _marks(page)}
            pencil, hl = by["pencil"], by["highlighter"]
            assert (pencil["tool"], pencil["lane"], pencil["state"], pencil["drawn"]) == \
                ("pencil", "pane:alpha", "drawn", 1), pencil
            assert (hl["tool"], hl["lane"], hl["state"], hl["drawn"]) == \
                ("highlighter", "pane:beta", "drawn", 1), hl

            def ink_in(m, pad=6):
                b = m["box"]
                return page.evaluate("b => Ink.sample(b)", {"x": b["x"] - pad, "y": b["y"] - pad,
                                                            "w": b["w"] + 2 * pad, "h": b["h"] + 2 * pad})
            assert ink_in(pencil) > 20 and ink_in(hl) > 20

            _mark(page, "alpha", "ink-pencil", False)
            _mark(page, "beta", "ink-hl", False)
            _rest(page, "Ink.inspect().layer.marks.every(m => m.tool !== 'pencil')"
                        " && Ink.inspect().layer.marks.some(m => m.strikeOf)")
            left = _marks(page)
            assert ink_in(pencil) == 0, "the eraser left the pencil on the paper"
            struck = {m["id"]: m for m in left}
            assert struck[hl["id"]]["state"] == "struck", left
            strike = next(m for m in left if m["strikeOf"] == hl["id"])
            assert (strike["tool"], strike["shape"], strike["drawn"]) == ("pen", "strike", 1), strike

            # A mark that comes back before its eraser starts is not drawn twice.
            page.evaluate("""() => { const a = document.querySelector('.tile[data-repo="alpha"]');
              a.classList.add('ink-pencil', 'ink-loop'); }""")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.lane === 'pane:alpha').length === 2")
            page.evaluate("""() => new Promise(done => {
              const a = document.querySelector('.tile[data-repo="alpha"]');
              a.classList.remove('ink-loop', 'ink-pencil');      // both leave: the loop is struck first,
              requestAnimationFrame(() => requestAnimationFrame(() => {
                a.classList.add('ink-pencil');                    // and the pencil is back before its turn
                done();
              }));
            })""")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.strikeOf)"
                        " && Ink.inspect().layer.marks.filter(m => m.lane === 'pane:alpha').length === 3")
            alpha = [m for m in _marks(page) if m["lane"] == "pane:alpha"]
            kept = [m for m in alpha if m["tool"] == "pencil"]
            assert len(kept) == 1 and kept[0]["id"] == max(m["id"] for m in alpha
                                                           if m["tool"] == "pencil"), alpha
            assert kept[0]["state"] == "drawn" and not kept[0]["erased"], kept
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


#: Every frame from the class being set until the paper is at rest: each mark's lane and how much
#: of it is drawn. Registered after the layer's own frame callback, so each entry is that frame's.
RECORD = """async ([classes]) => {
  for (const [repo, cls] of classes) document.querySelector(`.tile[data-repo="${repo}"]`).classList.add(cls);
  const frames = [];
  return await new Promise(done => {
    const tick = () => {
      const l = Ink.inspect().layer;
      frames.push({ frames: l.frames,
                    marks: l.marks.map(m => [m.id, m.lane, m.drawn, m.selector, m.len, m.strokes]),
                    hands: Object.values(l.lanes).some(x => x.hand), busy: l.busy });
      if ((frames.length > 3 && !l.busy) || frames.length > 3000) return done(frames);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}"""


@pytest.mark.browser
def test_two_panes_draw_at_once_and_one_panes_marks_never_interleave(fleet_home, tmp_path):
    """Lanes: one queue per agent's pane. Two agents' marks are drawn in the same frames; one
    agent's second mark is not begun until its first is finished."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page, dict(TABLE, speed=2))
            frames = page.evaluate(RECORD, [[["alpha", "ink-loop"], ["alpha", "ink-pencil"],
                                             ["beta", "ink-loop"]]])
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    ids = {}
    for f in frames:
        for mid, lane, _drawn, sel, *_ in f["marks"]:
            ids[(lane, sel)] = mid
    first = ids[("pane:alpha", ".tile.ink-loop .head")]
    second = ids[("pane:alpha", ".tile.ink-pencil .repo")]
    other = ids[("pane:beta", ".tile.ink-loop .head")]
    assert first < second, "the table's order is the lane's order"
    drawn = [{m[0]: m[2] for m in f["marks"]} for f in frames]
    together = [d for d in drawn if 0 < d.get(first, 0) < 1 and 0 < d.get(other, 0) < 1]
    assert together, f"the two panes never drew in the same frame: {drawn[:12]}"
    interleaved = [d for d in drawn if d.get(second, 0) > 0 and d.get(first, 0) < 1]
    assert interleaved == [], f"alpha's second mark began before its first was done: {interleaved[:3]}"
    assert drawn[-1] == {first: 1, second: 1, other: 1}, drawn[-1]
    assert len([d for d in drawn if 0 < d.get(first, 0) < 1]) >= 2, "drawn, not appeared"


@pytest.mark.browser
def test_the_marks_follow_a_gutter_drag_in_the_frame_that_moves_the_panes(fleet_home, tmp_path):
    """plan-panes ground rule 4 and plan-ink's "a panes drag redraws them in place": while the hand
    holds a gutter, every frame that moves a pane has the marks where the pane is -- checked by a
    ResizeObserver that runs after the layer's, in the same frame -- and the layer writes nothing to
    the page to do it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=3)
            _set(page, dict(TABLE, speed=4))
            for repo, cls in (("alpha", "ink-hl"), ("beta", "ink-loop"), ("beta", "ink-pencil"),
                              ("gamma", "ink-done")):
                _mark(page, repo, cls)
            _rest(page, "Ink.inspect().layer.marks.length === 4")
            page.evaluate("""(drift) => {
              window.__follow = { frames: 0, worst: 0, writes: [] };
              const check = new Function('return (' + drift + ')();');
              new ResizeObserver(() => {
                const d = check();
                window.__follow.frames += 1;
                window.__follow.worst = Math.max(window.__follow.worst, ...d, 0);
              }).observe(document.querySelector('.tile[data-repo="beta"]'));
              new MutationObserver(rs => rs.forEach(r => {
                if (r.target.id === 'ink' || (r.attributeName === 'style' && r.target.style &&
                                              r.target.style.getPropertyValue('clip-path')))
                  window.__follow.writes.push(r.attributeName || r.type);
              })).observe(document.documentElement, { subtree: true, attributes: true, childList: true });
            }""", DRIFT)
            before = page.evaluate(DRIFT)
            x, y = _gutter_point(page, "alpha")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + 120, y, steps=24)
            page.wait_for_function("() => window.__follow.frames >= 3", timeout=8000)
            held = page.evaluate(DRIFT)
            page.mouse.up()
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            _rest(page)
            after = page.evaluate(DRIFT)
            follow = page.evaluate("() => window.__follow")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert max(before) < 0.5 and max(held) < 0.5 and max(after) < 0.5, (before, held, after)
    assert follow["frames"] >= 3 and follow["worst"] < 0.5, follow
    assert follow["writes"] == [], f"the layer wrote to the page during the drag: {follow['writes']}"


@pytest.mark.browser
def test_the_marks_follow_a_window_resize(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page, dict(TABLE, speed=4))
            _mark(page, "alpha", "ink-hl")
            _mark(page, "beta", "ink-loop")
            _rest(page, "Ink.inspect().layer.marks.length === 2")
            wide = {m["lane"]: m["box"] for m in _marks(page)}
            page.set_viewport_size({"width": 1000, "height": 700})
            page.wait_for_function(f"() => innerWidth === 1000 && ({DRIFT})().every(d => d < 0.5)"
                                   " && document.getElementById('ink').width === 1000 * "
                                   "Math.min(2, devicePixelRatio || 1)", timeout=10000)
            narrow = {m["lane"]: m["box"] for m in _marks(page)}
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    beta = "pane:beta"   # the right-hand pane: a narrower window moves it left and makes it narrower
    assert narrow[beta]["x"] < wide[beta]["x"] and narrow[beta]["w"] < wide[beta]["w"], (wide, narrow)


@pytest.mark.browser
def test_reduced_motion_draws_at_once_with_no_travelling_pen(fleet_home, tmp_path):
    """plan-ink: *reduced motion draws at once, with no travelling pen* -- and leaves at once."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            _set(page)
            came = page.evaluate(RECORD, [[["alpha", "ink-loop"], ["alpha", "ink-pencil"],
                                           ["beta", "ink-write"]]])
            went = page.evaluate("""async () => {
              const a = document.querySelector('.tile[data-repo="alpha"]');
              a.classList.remove('ink-loop', 'ink-pencil');
              const l0 = Ink.inspect().layer.frames;
              await new Promise(d => requestAnimationFrame(() => requestAnimationFrame(d)));
              const l = Ink.inspect().layer;
              return { frames: l.frames - l0, marks: l.marks.map(m => [m.selector, m.state, m.strikeOf, m.drawn]),
                       write: l.marks.find(m => m.shape === 'write').clip, reduced: l.reduced, hands: l.hands };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    whole = [f for f in came if f["marks"] and all(m[2] == 1 for m in f["marks"])
             and len(f["marks"]) == 3]
    assert whole and came.index(whole[0]) <= 1, f"not drawn at once: {[f['marks'] for f in came[:4]]}"
    assert not any(f["hands"] for f in came), "a pen travelled under reduced motion"
    assert went["reduced"] is True and went["hands"] is False
    assert [m for m in went["marks"] if m[0] == ".tile.ink-pencil .repo"] == [], went
    assert any(m[1] == "struck" for m in went["marks"]) and any(m[2] for m in went["marks"]), went
    assert went["write"] == "", "the handwriting was left covered"


#: A long pencil row and a pen row in one pane, drawn slowly, with the page's own traces left out so
#: that the pane's hand is only ever at these two (#387).
CHALK = {"name": "chalk", "speed": 0.5, "series": False, "marks": [
    {"selector": ".tile.ink-pencil .repo", "tool": "pencil", "shape": "underline"},
    {"selector": ".tile.ink-pen .head", "tool": "pen", "shape": "loop"}]}

#: `RECORD`'s pattern for the hand: each `[tool, class]` is put on alpha, and then, every frame until
#: those marks are drawn and the paper is at rest, the model of alpha's hand in the first frame where
#: that hand is shown and the mark on `tool` is part drawn -- read in the one frame, so a hand that
#: swaps tools in the next is not misread. Recorded in the page: the pencil's short row is drawn in
#: a fraction of a second, and a `wait_for_function` begun a round trip after the class went on
#: never saw it part drawn on a loaded machine (a 0.3 s late start failed it every time).
HANDS_AT = """async (tools) => {
  const tile = document.querySelector('.tile[data-repo="alpha"]');
  for (const [, cls] of tools) tile.classList.add(cls);
  const seen = {};
  let n = 0;
  return await new Promise(done => {
    const tick = () => {
      const l = Ink.inspect().layer;
      const lane = l.lanes['pane:alpha'];
      const mark = tool => l.marks.find(m => m.tool === tool && m.lane === 'pane:alpha');
      for (const [tool] of tools) {
        const m = mark(tool);
        if (!(tool in seen) && lane && lane.hand && m && m.drawn > 0 && m.drawn < 1) seen[tool] = l.handModel;
      }
      n += 1;
      const drawn = tools.every(([tool]) => mark(tool) && mark(tool).drawn === 1);
      if ((n > 3 && drawn && !l.busy) || n > 3000) return done(tools.map(([tool]) => seen[tool] ?? false));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}"""

#: `RECORD`'s pattern for a class taken away: every frame until alpha's pencil mark is gone, the
#: hand's model and whether alpha's hand is shown.
ERASE = """async () => {
  document.querySelector('.tile[data-repo="alpha"]').classList.remove('ink-pencil');
  const frames = [];
  return await new Promise(done => {
    const tick = () => {
      const l = Ink.inspect().layer;
      frames.push({ model: l.handModel, hand: !!(l.lanes['pane:alpha'] && l.lanes['pane:alpha'].hand),
                    erased: l.marks.filter(m => m.tool === 'pencil').map(m => m.erased) });
      if ((frames.length > 3 && !l.busy && !l.marks.some(m => m.tool === 'pencil')) || frames.length > 3000) {
        return done(frames);
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}"""


@pytest.mark.browser
def test_the_hand_can_be_a_stick_of_chalk(fleet_home, tmp_path):
    """#387: `hand: 'chalk'` puts a worn stick of chalk in every hand -- the pencil's, the pen's and
    the eraser's -- and `hand: true` keeps the lit pencil, the pen and the pencil's eraser end. A
    hand that is none of these is refused, naming `hand`, and the table in force stays."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for hand, pencil, pen, eraser in (("chalk", "chalk", "chalk", "chalk"),
                                              (True, "pencil", "pen:pen", "eraser")):
                page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
                _set(page, dict(CHALK, hand=hand))
                assert _layer(page)["handModel"] == "", "a hand was shown before a mark was drawn"
                refused = page.evaluate("""() => { try { Ink.setSkin({ name: 'bad', hand: 'crayon', marks: [] }); return ''; }
                                                   catch (e) { return e.message; } }""")
                assert "`hand`" in refused and page.evaluate("() => Ink.inspect().table") == "chalk", refused
                drew = page.evaluate(HANDS_AT, [["pencil", "ink-pencil"], ["pen", "ink-pen"]])
                _rest(page, "Ink.inspect().layer.marks.filter(m => m.drawn === 1).length === 2")
                frames = page.evaluate(ERASE)
                assert frames[-1]["erased"] == [], frames[-1]
                erasing = [f for f in frames if f["hand"] and f["erased"] == [True]]
                assert erasing, "no frame showed the eraser at the pencil"
                models = {f["model"] for f in frames}
                # The render contract holds with the chalk: at rest, nothing written, nothing drawn.
                count = page.evaluate(IDLE_LOOP)
                assert not errors, errors
                page.close()
                assert drew == [pencil, pen], (hand, drew)
                # Every sampled frame: the last hand shown is the pen that drew, or the eraser.
                assert models <= {pen, eraser}, (hand, models)
                assert {f["model"] for f in erasing} == {eraser}, (hand, erasing[:3])
                assert count["n"] == 0 and count["renders"] == 0, (hand, count)

            # Reduced motion: the marks are drawn at once, and no hand at all -- chalk or not.
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            _set(page, dict(CHALK, hand="chalk"))
            came = page.evaluate(RECORD, [[["alpha", "ink-pencil"], ["alpha", "ink-pen"]]])
            layer = _layer(page)
            assert not any(f["hands"] for f in came), "a hand travelled under reduced motion"
            assert layer["hands"] is False and layer["handModel"] == "", layer["handModel"]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_ink_catches_up_in_frames_not_milliseconds(fleet_home, tmp_path):
    """Ground rule 5. CI draws in software, so the ink's own budget is counted in frames: a mark is
    on the paper within the frames a hand at the layer's pen speed needs for its length at 60 Hz
    (plus the travel between strokes and a margin) -- a slower frame moves the pen further, so it
    is never more -- and over more than one frame, because it is drawn, not shown."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page)
            rec = page.evaluate(RECORD, [[["alpha", "ink-loop"], ["alpha", "ink-hl"]]])
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    last = rec[-1]
    assert len(last["marks"]) == 2 and all(m[2] == 1 for m in last["marks"]), last
    first = next(f for f in rec if f["marks"])
    frames = last["frames"] - first["frames"] + 1
    bound = catch_up_frames(last["marks"])
    print(f"\n  ink caught up in {frames} frames (bound {bound})")
    assert frames >= 3, "drawn at once: that is reduced motion's look, not this one's"
    assert frames <= bound, (frames, bound, last["marks"])


def catch_up_frames(marks, speed=1.0, hz=60):
    """The frames a hand needs for these marks at `hz`, from what the layer says it drew: each
    stroke's length at the pen's speed, 1.5x for its profile (it starts and ends slowly: the
    average is 1.01x, a stroke under 16px 1.43x), a travel of up to 0.45s before every stroke, and
    four frames of margin. Summed over every lane, so it bounds lanes drawing at once as well."""
    seconds = sum(1.5 * m[4] / (PEN * speed) + 0.45 * m[5] / math.sqrt(speed) for m in marks)
    return math.ceil(seconds * hz) + 4


@pytest.mark.browser
def test_the_gate_turns_ink_on_for_a_hardware_probe_and_nowhere_else(fleet_home, tmp_path):
    """The rule of the epic: only a shell whose probe says `hardware` gets ink. Software, no WebGL,
    an unnamed renderer, a probe that did not finish and a shell nobody measured all arrive at
    `body.ink-off` -- and so does a hardware shell opened with `?ink=off`. The hardware one draws."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    shells = {"pycharm": _facts(), "vscode": _facts(renderer=SWIFTSHADER),
              "edge": _facts(webgl="none", renderer=""), "chromium": _facts(renderer=""),
              "left": _facts(hidden=True)}
    for shell, body in shells.items():
        PR.record(dict(body, shell=shell))
    for w in list(shells) + ["browser"]:
        S.update_window(w, open="alpha", widths={"alpha": 1, "beta": 1})
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for w in ("pycharm", "vscode", "edge", "chromium", "left", "browser", "pycharm&ink=off"):
                page, errors, asked = _open(browser, port, token, f"&w={w}")
                got = page.evaluate("""async () => ({ verdict: Ink.verdict, enabled: Ink.enabled,
                  off: document.body.classList.contains('ink-off'),
                  drawn: (await Ink.setSkin({ name: 'gate', marks: [
                           { selector: '.tile .repo', tool: 'pen', shape: 'underline' }] })).drawn,
                  canvas: !!document.getElementById('ink') })""")
                got["three"] = any("vendor/three" in u for u in asked)
                seen[w] = got
                assert not errors, (w, errors)
                page.close()
            browser.close()
    finally:
        _stop(server)
    on = seen.pop("pycharm")
    assert on["enabled"] and not on["off"] and on["drawn"] == "ink" and on["canvas"] and on["three"]
    assert on["verdict"]["source"] == "probe" and on["verdict"]["probe"] == "hardware"
    want = {"vscode": "software", "edge": "none", "chromium": "unknown", "left": "incomplete",
            "browser": "unmeasured", "pycharm&ink=off": "hardware"}
    for w, got in seen.items():
        assert not got["enabled"] and got["off"] and got["drawn"] == "plain", (w, got)
        assert not got["canvas"] and not got["three"], (w, got)
        assert got["verdict"]["probe"] == want[w], (w, got)
    assert seen["pycharm&ink=off"]["verdict"]["source"] == "param"


def _no_skin_css(page):
    """What `applySkin` asks for besides the module is the skin's stylesheet. The example has none."""
    page.route("**/static/skins/example/skin.css*", lambda route: route.fulfill(
        status=200, content_type="text/css; charset=utf-8", body=""))


def _choose(page, skin):
    """Choose a skin the way the settings page does: `POST /api/theme {skin}`, which writes the
    config every window reads and reaches this one down the stream as `applySkin`."""
    page.evaluate("s => post('theme', { skin: s })", skin)


@pytest.mark.browser
def test_a_skin_is_a_module_the_page_loads_when_it_is_chosen(fleet_home, tmp_path):
    """How a skin registers (docs/desk-ink.md §Writing a skin): `static/ink/skins/<name>.js`. The
    server lists the names on <body>; the skin chosen in the config (the settings page, skins.py)
    reaches the page as `applySkin`, which writes it and its variant on <body>; and the ink layer
    follows that: the module fetched with the token, its marks per variant drawn in ink where the
    gate is on and as plain CSS where it is off, its materials run -- a ground, a paper, a frame
    per pane -- and all of it gone when the skin goes, the page's traces it drew beside them (#257)
    included. A skin with no module is asked for nothing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata.fleet import skins as K
    # A skin skins.py offers that ships no module yet, if one is left (#249-#256 ship them).
    plain_skin = next((n for n in K.SKINS if n not in S.ink_skins()), "")
    _desk_of(tmp_path)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for extra in ("&ink=on", ""):
                (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "example"}}',
                                                            encoding="utf-8")
                page, errors, asked = _open(browser, port, token, extra)
                _no_skin_css(page)
                assert page.evaluate("() => document.body.dataset.inkSkins") == " ".join(S.ink_skins())
                page.wait_for_function("() => Ink.inspect().table === 'example'", timeout=10000)
                _mark(page, "alpha", "ink-example")
                if extra:
                    _rest(page, "Ink.inspect().layer.marks.length === 1"
                                " && Ink.inspect().layer.skin.frames === 2")
                    seen["on"] = page.evaluate("""() => { const l = Ink.inspect().layer;
                      return { tool: l.marks[0].tool, skin: l.skin, mode: l.mode,
                               corner: Ink.sample({ x: 2, y: innerHeight - 30, w: 20, h: 20 }) }; }""")
                    _choose(page, "example:red")
                    _rest(page, "Ink.inspect().table === 'example:red'"
                                " && Ink.inspect().layer.marks.length === 1")
                    seen["red"] = _marks(page)[0]["tool"]
                else:
                    page.wait_for_function("""() => getComputedStyle(document.querySelector(
                      '.tile[data-repo="alpha"] .head')).textDecorationLine === 'underline'""",
                                           timeout=10000)
                    seen["plain"] = True
                _choose(page, "none")
                page.wait_for_function("() => Ink.inspect().table === null", timeout=10000)
                seen.setdefault("gone", []).append(page.evaluate(
                    "() => ({ canvas: !!document.getElementById('ink'), layer: Ink.inspect().layer })"))
                if plain_skin:                                  # a skin with no module
                    _choose(page, plain_skin)
                    page.wait_for_function("s => document.body.dataset.skin === s", arg=plain_skin,
                                           timeout=10000)
                seen.setdefault("asked", []).extend(
                    u.split(str(port))[1] for u in asked if "/static/ink/skins/" in u)
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        _stop(server)
    on = seen["on"]
    assert on["tool"] == "pen" and seen["red"] == "red", "each variant has its own table"
    assert on["skin"]["hooks"] == ["ground", "paper", "frame", "tick", "dispose"], on["skin"]
    assert on["skin"]["ground"] == 1 and on["skin"]["paper"] == 1 and on["skin"]["frames"] == 2, on
    assert on["skin"]["errors"] == [] and on["mode"] == 1, "a paper under the marks: multiply"
    assert on["corner"] == 400, "the skin's ground is under the whole page"
    assert seen["plain"], "the same marks, drawn plain where the gate is off"
    assert not seen["gone"][0]["canvas"], "a skin that goes takes the canvas with it"
    assert seen["asked"] and all(u.startswith(f"/static/ink/skins/example.js?t={token}")
                                 for u in seen["asked"]), seen["asked"]


@pytest.mark.browser
def test_a_skin_hook_that_throws_is_the_skins_problem_and_the_ground_can_be_sampled(fleet_home, tmp_path):
    """A skin's mistake is said once, in the console, and the desk goes on drawing its marks. And a
    skin that asks for `sampleGround` has its ground and paper as a texture while it frames."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            said = []
            page.on("console", lambda m: said.append(m.text) if m.type == "error" else None)
            page.evaluate("""async (table) => {
              window.__sampled = [];
              await Ink.setSkin(table, {
                sampleGround: true,
                ground({ THREE, scene, api }) {
                  const { w, h } = api.viewport;
                  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                                           new THREE.MeshBasicMaterial({ color: 0x336699 }));
                  m.position.set(w / 2, -h / 2, 0);
                  scene.add(m);
                },
                paper() { throw new Error('a skin bug'); },
                frame({ api }, el, box) {
                  window.__sampled.push(!!api.groundTexture && api.groundSize.x > 0 && box.w > 0);
                },
              });
              document.querySelector('.tile[data-repo="alpha"]').classList.add('ink-hl');
            }""", dict(TABLE, speed=4))
            _rest(page, "Ink.inspect().layer.marks.length === 1")
            state = page.evaluate("() => ({ skin: Ink.inspect().layer.skin, sampled: window.__sampled,"
                                  " drawn: Ink.inspect().layer.marks[0].drawn })")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert state["drawn"] == 1, state
    assert state["skin"]["errors"] == ["paper"] and state["skin"]["sampleGround"], state
    assert state["sampled"] and all(state["sampled"]), state
    assert len([t for t in said if "paper() threw" in t]) == 1, said


@pytest.mark.browser
def test_the_fallback_draws_the_same_table_as_plain_css(fleet_home, tmp_path):
    """Decision 3: no WebGL gets the same page with plain borders and highlights, and no animation.
    The same mark table, as a constructed stylesheet under `body.ink-off` -- so the browser matches
    the selectors, a mark comes and goes with the class, and the fallback writes nothing to the
    page to do it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token)
            out = page.evaluate("""async (table) => {
              // What the fallback could write: a stylesheet element, or a style on an element.
              // (app.js goes on drawing the desk meanwhile, and its writes are its own.)
              let n = 0;
              const obs = new MutationObserver(rs => { n += rs.filter(r => r.attributeName === 'style' ||
                [...r.addedNodes].some(a => a.nodeName === 'STYLE' || a.nodeName === 'LINK')).length; });
              obs.observe(document.documentElement, { subtree: true, attributes: true, childList: true });
              const drawn = (await Ink.setSkin(table)).drawn;
              const a = document.querySelector('.tile[data-repo="alpha"]');
              const b = document.querySelector('.tile[data-repo="beta"]');
              const look = () => {
                const head = getComputedStyle(a.querySelector('.head'));
                const name = getComputedStyle(b.querySelector('.repo'));
                const under = getComputedStyle(a.querySelector('.repo'));
                return { outline: head.outlineStyle + ' ' + head.outlineWidth,
                         highlight: name.backgroundColor,
                         underline: under.textDecorationLine,
                         margin: getComputedStyle(b.querySelector('.head')).boxShadow,
                         ring: getComputedStyle(a.querySelector('.head .n')).boxShadow,
                         cross: getComputedStyle(b).boxShadow };
              };
              const bare = look();
              a.classList.add('ink-loop', 'ink-pencil', 'ink-o');
              b.classList.add('ink-hl', 'ink-done', 'ink-x');
              const marked = look();
              a.classList.remove('ink-loop', 'ink-pencil', 'ink-o');
              b.classList.remove('ink-hl', 'ink-done', 'ink-x');
              const gone = look();
              await new Promise(d => requestAnimationFrame(() => requestAnimationFrame(d)));
              obs.disconnect();
              return { drawn, bare, marked, gone, writes: n, rules: document.adoptedStyleSheets
                         .flatMap(s => [...s.cssRules].map(r => r.cssText)).join('\\n') };
            }""", dict(TABLE, marks=TABLE["marks"] + OX["marks"]))
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert out["drawn"] == "plain"
    assert out["bare"] == out["gone"], out
    assert out["marked"]["outline"].startswith("solid 2px"), out["marked"]
    assert out["marked"]["highlight"] != out["bare"]["highlight"], out
    assert out["marked"]["underline"] == "underline", out["marked"]
    assert "inset" in out["marked"]["margin"] or "3px 0px 0px" in out["marked"]["margin"], out
    # #386: the O is a rounded 2px ring round the number, the X a bar in the pane's margin.
    assert out["marked"]["ring"].endswith("0px 0px 0px 2px") and out["bare"]["ring"] == "none", out
    assert "3px 0px 0px 0px inset" in out["marked"]["cross"], out
    assert out["writes"] == 0, "the fallback wrote to the page"
    assert "body.ink-off :is(.tile.ink-loop .head)" in out["rules"], out["rules"]
    assert not [u for u in asked if "/static/ink/layer.js" in u or "vendor/three" in u]


@pytest.mark.browser
def test_a_lost_context_turns_ink_off_and_the_same_table_falls_back(fleet_home, tmp_path):
    """A context the GPU takes back is the fallback for the rest of the page's life: the canvas
    goes, `body.ink-off` comes, and the table in force is drawn as plain CSS at once."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page, dict(TABLE, speed=4))
            _mark(page, "alpha", "ink-loop")
            _rest(page, "Ink.inspect().layer.marks.length === 1")
            page.evaluate("""() => { const c = document.getElementById('ink');
              const gl = c.getContext('webgl2') || c.getContext('webgl');
              gl.getExtension('WEBGL_lose_context').loseContext(); }""")
            page.wait_for_function("() => document.body.classList.contains('ink-off')", timeout=10000)
            out = page.evaluate("""() => ({ verdict: Ink.verdict, enabled: Ink.enabled,
              canvas: !!document.getElementById('ink'), layer: Ink.inspect().layer,
              outline: getComputedStyle(document.querySelector('.tile[data-repo="alpha"] .head')).outlineStyle })""")
            again = page.evaluate("async t => (await Ink.setSkin(t)).drawn", TABLE)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert out["enabled"] is False and out["canvas"] is False and out["layer"] is None, out
    assert out["verdict"]["source"] == "runtime" and "lost" in out["verdict"]["why"], out
    assert out["outline"] == "solid" and again == "plain", out


@pytest.mark.browser
def test_a_shell_that_will_not_give_a_webgl_context_falls_back_without_fetching_three(fleet_home, tmp_path):
    """Asked before three.js is fetched, the way the probe asks: a shell with no context costs the
    desk nothing but the front door."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            context = browser.new_context()
            context.add_init_script("""
              const real = HTMLCanvasElement.prototype.getContext;
              HTMLCanvasElement.prototype.getContext = function (kind, attrs) {
                if (/webgl/.test(String(kind))) return null;
                return real.call(this, kind, attrs);
              };""")
            page = context.new_page()
            errors, asked = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: asked.append(r.url))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&ink=on", wait_until="domcontentloaded")
            page.wait_for_function("() => !!window.Ink && document.querySelectorAll('.tile.is-solo').length === 2",
                                   timeout=15000)
            out = page.evaluate("""async t => ({ drawn: (await Ink.setSkin(t)).drawn, verdict: Ink.verdict,
              off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink') })""",
                                TABLE)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert out["drawn"] == "plain" and out["off"] and not out["canvas"], out
    assert "no WebGL context" in out["verdict"]["why"], out
    assert not [u for u in asked if "vendor/three" in u], "fetched three.js for a shell that cannot draw"


@pytest.mark.browser
def test_an_idle_desk_with_ink_on_the_paper_writes_nothing_and_draws_nothing(fleet_home, tmp_path):
    """The render contract with the layer running: once the marks are drawn, an idle desk is still
    zero DOM mutations -- and zero WebGL frames, because a paper with nothing new is not redrawn."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
            _set(page, dict(TABLE, speed=4))
            for repo, cls in (("alpha", "ink-loop"), ("alpha", "ink-write"), ("beta", "ink-hl")):
                _mark(page, repo, cls)
            _rest(page, "Ink.inspect().layer.marks.length === 3")
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle desk with ink on it wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle paper was redrawn {count['renders']} times"


@pytest.mark.browser
def test_the_handwriting_reveal_uncovers_the_text_and_leaves_the_page_as_it_found_it(fleet_home, tmp_path):
    """The one write the layer makes to the page: the `clip-path` of the element being written,
    while it is written. A pencil note that is erased is covered again; a table taken away takes
    every clip it wrote with it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _set(page)
            clips = page.evaluate("""async () => {
              const t = document.querySelector('.tile[data-repo="alpha"]');
              const el = t.querySelector('.ticket');
              const seen = new Set();
              t.classList.add('ink-write');
              await new Promise(done => {
                const tick = () => {
                  seen.add(el.style.getPropertyValue('clip-path') ? 'part' : 'none');
                  const l = Ink.inspect().layer;
                  if (l && l.marks.length && !l.busy) return done();
                  requestAnimationFrame(tick);
                };
                requestAnimationFrame(tick);
              });
              return { seen: [...seen], after: el.getAttribute('style') };
            }""")
            _mark(page, "alpha", "ink-write", False)
            _rest(page, "Ink.inspect().layer.marks.length === 0")
            erased = page.evaluate("() => document.querySelector('.tile[data-repo=\"alpha\"] .ticket')"
                                   ".style.getPropertyValue('clip-path')")
            page.evaluate("() => Ink.setSkin(null)")
            restored = page.evaluate("() => document.querySelector('.tile[data-repo=\"alpha\"] .ticket')"
                                     ".getAttribute('style')")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert "part" in clips["seen"], clips
    assert clips["after"] is None, f"the written line kept a style: {clips['after']}"
    assert erased == "inset(0px 100% 0px 0px)" or erased == "inset(0 100% 0 0)", erased
    assert restored is None, restored


@pytest.mark.browser
@pytest.mark.measured
def test_a_gesture_keeps_its_budget_while_the_ink_draws(fleet_home, tmp_path):
    """Ground rule 5's other half: the ink draws after the gesture, never inside it. The page's own
    gesture marks, taken while every pane has a long mark drawing, stay inside the 50ms budget."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ("alpha", "beta", "gamma", "delta")
    _desk_of(tmp_path, names)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=4, width=1600)
            _set(page, dict(TABLE, speed=0.25))
            for repo in names:
                _mark(page, repo, "ink-loop")
            page.wait_for_function("() => Ink.inspect().layer && Ink.inspect().layer.busy", timeout=10000)
            marks = page.evaluate("""() => {
              performance.clearMeasures();
              setHidden('beta', true);
              setHidden('beta', false);
              moveTile('gamma', 1);
              moveTile('gamma', -1);
              const alpha = document.querySelector('.tile[data-repo="alpha"]');
              stepGutter(alpha, -1);
              evenGutter(alpha);
              return { busy: Ink.inspect().layer.busy, measures: performance.getEntriesByType('measure')
                .map(m => ({ name: m.name.split(':')[0] + ':' + m.name.split(':')[1], ms: m.duration })) };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert marks["busy"], "the ink had finished before the gestures: nothing was measured against it"
    measures = marks["measures"]
    assert len(measures) >= 4, measures
    worst = max(m["ms"] for m in measures)
    print(f"\n  gestures while the ink draws: {len(measures)} marked, worst {worst:.1f}ms")
    assert [m for m in measures if m["ms"] > LOCAL_BUDGET_MS] == [], measures


#: The pixels three.js drew at points in viewport boxes, read back from a frame drawn for the
#: purpose (`READ` in test_fleet_ink_glass.py, which imports this module).
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

#: Some pixel READ finds in the first box is `want`'s channel alone (0 red, 1 green, 2 blue).
PURE = """([boxes, want]) => (%s)(boxes)[0].some(p =>
  p[want] > 120 && [0, 1, 2].every(k => k === want || p[k] < 60))""" % READ


@pytest.mark.browser
def test_a_row_borrows_an_ink_and_an_underline_ends_in_a_cap(fleet_home, tmp_path):
    """#385. A row draws with one tool's hand in another tool's ink: `{tool: 'pencil', ink: 'pen'}`
    is drawn in the pen's colour, recoloured with it, and erased (pencil's way of leaving), not
    struck. An underline ends in an arrowhead or a bar, one stroke more, which stays at the growing
    end. Plain, the borrowed ink is the underline's colour and a dashed underline stays dashed.
    Reduced motion draws the cap at once, and an idle desk is still idle."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    # Pure inks on <html>, which the layer observes. The pencil's is not the pen's, so a mark drawn
    # in its own tool's ink reads as the wrong colour.
    inks = """([pen, pencil]) => { const s = document.documentElement.style;
      s.setProperty('--ink-pen', pen); s.setProperty('--ink-pencil', pencil);
      s.setProperty('--ink-green', '#00ff00'); }"""
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)

            # Plain (the gate is off): the look is CSS in the borrowed ink.
            page, errors, _ = _open(browser, port, token)
            page.evaluate(inks, ["#ff0000", "#0000ff"])
            plain = page.evaluate("""async (t) => {
                await Ink.setSkin(t);
                const look = r => { const s = getComputedStyle(document.querySelector(
                  `.tile[data-repo="${r}"] .repo`));
                  return [s.textDecorationLine, s.textDecorationStyle, s.textDecorationColor]; };
                return { off: document.body.classList.contains('ink-off'),
                         alpha: look('alpha'), beta: look('beta') };
            }""", {"name": "plain", "marks": [
                {"selector": ".tile[data-repo=\"alpha\"] .repo", "tool": "pencil", "ink": "pen",
                 "shape": "underline", "dash": True},
                {"selector": ".tile[data-repo=\"beta\"] .repo", "tool": "pencil", "ink": "green",
                 "shape": "underline"}]})
            assert plain["off"], plain
            assert plain["alpha"] == ["underline", "dashed", "rgb(255, 0, 0)"], plain
            assert plain["beta"] == ["underline", "solid", "rgb(0, 255, 0)"], plain
            assert not errors, errors
            page.close()

            page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
            page.evaluate(inks, ["#ff0000", "#0000ff"])
            table = {"name": "caps", "speed": 4, "marks": [
                {"selector": ".tile.borrowed .repo", "tool": "pencil", "ink": "pen", "shape": "underline"},
                {"selector": ".tile.arrow-cap .repo", "tool": "pen", "shape": "underline",
                 "grow": ".transcript > li", "cap": "arrow"},
                {"selector": ".tile.bar-cap .repo", "tool": "pen", "shape": "underline", "cap": "bar"}]}
            _set(page, table)

            # The pencil's hand in the pen's ink, read where the line is.
            _mark(page, "alpha", "borrowed")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.state === 'drawn')")
            line = next(m for m in _marks(page) if m["lane"] == "pane:alpha")
            assert (line["tool"], line["ink"], line["cap"], line["strokes"]) == ("pencil", "pen", "", 1), line
            b = line["bounds"][0]
            at = [{"x": b["x"], "y": b["y"], "w": b["r"] - b["x"], "h": b["b"] - b["y"],
                   "at": [(fx, fy) for fx in (0.2, 0.35, 0.5, 0.65, 0.8) for fy in (0.4, 0.5, 0.6)]}]
            page.wait_for_function(PURE, arg=[at, 0], timeout=10000)
            assert not page.evaluate(PURE, [at, 2]), page.evaluate(READ, at)

            # A second pure colour, set the same way, recolours it.
            page.evaluate(inks, ["#0000ff", "#00ff00"])
            page.wait_for_function(PURE, arg=[at, 2], timeout=10000)
            assert not page.evaluate(PURE, [at, 1]), page.evaluate(READ, at)

            # It leaves the pencil's way: erased, never struck.
            _mark(page, "alpha", "borrowed", False)
            _rest(page, "!Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha')")
            assert not any(m["strikeOf"] for m in _marks(page)), _marks(page)

            # A bar is one stroke more, standing across the line's end.
            _mark(page, "beta", "bar-cap")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:beta' && m.state === 'drawn')")
            bar = next(m for m in _marks(page) if m["lane"] == "pane:beta")
            assert (bar["cap"], bar["ink"], bar["strokes"], bar["drawn"]) == ("bar", "pen", 2, 1), bar
            assert abs(bar["bounds"][1]["r"] - bar["bounds"][0]["r"]) <= 2, bar["bounds"]
            assert bar["bounds"][1]["b"] - bar["bounds"][1]["y"] >= 9, bar["bounds"]

            # An arrowhead at the end of a growing line: after two arrivals it is at the new end.
            _mark(page, "alpha", "arrow-cap")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.state === 'drawn')")
            arrow = next(m for m in _marks(page) if m["lane"] == "pane:alpha")
            assert (arrow["cap"], arrow["strokes"], arrow["drawn"]) == ("arrow", 2, 1), arrow
            line0, head0 = arrow["bounds"]
            assert abs(head0["r"] - line0["r"]) <= 2, arrow["bounds"]
            page.evaluate("""() => { const tr = document.querySelector('.tile[data-repo="alpha"] .transcript');
              for (const t of ['one', 'two']) { const li = document.createElement('li');
                                                li.textContent = t; tr.appendChild(li); } }""")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.drawn === 1"
                        f" && m.bounds[0].r > {line0['r']} + 15)")
            arrow = next(m for m in _marks(page) if m["lane"] == "pane:alpha")
            line1, head1 = arrow["bounds"]
            assert line1["r"] > line0["r"] + 15 and abs(head1["r"] - line1["r"]) <= 2, arrow["bounds"]
            assert head1["x"] > head0["x"] + 15, "the arrowhead stayed where the line was"

            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle desk rendered frames: {count}"
            assert not errors, errors
            page.close()

            # Reduced motion: the line and its cap are on the paper at once, and no pen travels.
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            _set(page, table)
            came = page.evaluate(RECORD, [[["alpha", "arrow-cap"]]])
            whole = [f for f in came if any(m[1] == "pane:alpha" and m[2] == 1 and m[5] == 2
                                            for m in f["marks"])]
            assert whole and came.index(whole[0]) <= 1, f"not drawn at once: {[f['marks'] for f in came[:4]]}"
            assert not any(f["hands"] for f in came), "a pen travelled under reduced motion"
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


#: #386: a tight O round a pane's number, and an X in a pane's margin.
OX = {"name": "ox", "speed": 4, "marks": [
    {"selector": ".tile.ink-o .head .n", "tool": "pencil", "shape": "ring"},
    {"selector": ".tile.ink-x", "tool": "red", "shape": "cross"}]}

#: The ring's mark on alpha with its strokes' bounds, `.n`'s box and `.repo`'s text rects, read at once.
RING = """() => {
  const a = document.querySelector('.tile[data-repo="alpha"]');
  const n = a.querySelector('.head .n').getBoundingClientRect();
  const rg = document.createRange(); rg.selectNodeContents(a.querySelector('.head .repo'));
  const text = [...rg.getClientRects()].filter(r => r.width > 0)
    .map(r => ({ x: r.left, y: r.top, r: r.right, b: r.bottom }));
  const m = Ink.inspect().layer.marks.find(k => k.shape === 'ring' && k.lane === 'pane:alpha');
  return { n: { x: n.left, y: n.top, r: n.right, b: n.bottom, w: n.width },
           digits: a.querySelector('.head .n').textContent, text, mark: m || null };
}"""


def _union(bounds):
    return {"x": min(b["x"] for b in bounds), "y": min(b["y"] for b in bounds),
            "r": max(b["r"] for b in bounds), "b": max(b["b"] for b in bounds)}


def _hugs(got):
    """The ring's strokes enclose `.n`'s box and cross none of `.repo`'s words."""
    m = got["mark"]
    assert m and m["state"] == "drawn" and m["drawn"] == 1 and m["bounds"], got
    u, n = _union(m["bounds"]), got["n"]
    assert u["x"] <= n["x"] and u["r"] >= n["r"] and u["y"] <= n["y"] and u["b"] >= n["b"], (u, n)
    assert got["text"], got
    for t in got["text"]:
        for b in m["bounds"]:
            apart = b["r"] <= t["x"] or t["r"] <= b["x"] or b["b"] <= t["y"] or t["b"] <= b["y"]
            assert apart, ("the O crosses the name", b, t, n)


@pytest.mark.browser
def test_the_o_and_the_x(fleet_home, tmp_path):
    """#386. `ring` is a tight O round a small box (a pane's number), close enough that it never
    crosses the name 8px away, for a one-digit and a two-digit number; `cross` is an X in the pane's
    margin, down the middle of a rail. Each is drawn when its class comes and leaves by its tool's
    rule: the pencil's O is erased, the red X struck. Plain, the O is a rounded 2px shadow in its
    ink and the X a margin bar beside a selected pane's focus ring. Reduced motion draws both at
    once, and an idle desk writes nothing and draws nothing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)

            # Plain: the same two rows as CSS, in their own inks.
            page, errors, _ = _open(browser, port, token)
            page.evaluate("""() => { const s = document.documentElement.style;
              s.setProperty('--ink-pencil', '#0000ff'); s.setProperty('--ink-red', '#ff0000'); }""")
            plain = page.evaluate("""async (t) => {
              const drawn = (await Ink.setSkin(t)).drawn;
              const a = document.querySelector('.tile[data-repo="alpha"]');
              const b = document.querySelector('.tile[data-repo="beta"]');
              const n = a.querySelector('.head .n');
              const bare = [getComputedStyle(n).boxShadow, getComputedStyle(b).boxShadow];
              a.classList.add('ink-o'); b.classList.add('ink-x');
              const ns = getComputedStyle(n), o = { shadow: ns.boxShadow, radius: ns.borderTopLeftRadius };
              const x = getComputedStyle(b).boxShadow;
              const was = b.classList.contains('is-selected');
              b.classList.add('is-selected');
              const sel = getComputedStyle(b).boxShadow;
              b.classList.toggle('is-selected', was);
              a.classList.remove('ink-o'); b.classList.remove('ink-x');
              return { drawn, bare, o, x, sel, shapes: Ink.shapes,
                       gone: [getComputedStyle(n).boxShadow, getComputedStyle(b).boxShadow] };
            }""", OX)
            assert not errors, errors
            page.close()
            assert plain["drawn"] == "plain" and {"ring", "cross"} <= set(plain["shapes"]), plain
            assert plain["o"]["shadow"] == "rgb(0, 0, 255) 0px 0px 0px 2px", plain
            assert plain["o"]["radius"] == "999px", plain
            assert plain["x"].startswith("rgb(255, 0, 0) 3px 0px 0px 0px inset"), plain
            assert "rgb(255, 0, 0) 3px 0px 0px 0px inset" in plain["sel"], plain
            assert "0px 0px 0px 2px" in plain["sel"], ("the selected pane lost its focus ring", plain)
            assert plain["gone"] == plain["bare"], plain

            # Drawn: the layer starts with both shapes, and each leaves by its tool's rule.
            page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
            assert {"ring", "cross"} <= set(page.evaluate("() => Ink.shapes"))
            assert _set(page, OX)["drawn"] == "ink"
            _mark(page, "alpha", "ink-o")
            _mark(page, "alpha", "ink-x")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.lane === 'pane:alpha'"
                        " && m.drawn === 1).length === 2")
            by = {m["shape"]: m for m in _marks(page)}
            assert (by["ring"]["tool"], by["ring"]["strokes"]) == ("pencil", 1), by
            assert (by["cross"]["tool"], by["cross"]["strokes"]) == ("red", 2), by
            _hugs(page.evaluate(RING))

            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle desk rendered frames: {count}"

            # A two-digit number: the O widens with it and still stays off the name.
            page.evaluate("""() => {
              document.querySelector('.tile[data-repo="alpha"] .head .n').textContent = '12';
              Ink.refresh(); }""")
            page.wait_for_function(f"""() => {{ const g = ({RING})(); return ({AT_REST})()
              && g.digits === '12' && !!g.mark && g.mark.drawn === 1
              && Math.abs(g.mark.box.w - g.n.w) < 0.5; }}""", timeout=20000)
            _hugs(page.evaluate(RING))

            _mark(page, "alpha", "ink-o", False)
            _mark(page, "alpha", "ink-x", False)
            _rest(page, "!Ink.inspect().layer.marks.some(m => m.shape === 'ring')"
                        " && Ink.inspect().layer.marks.some(m => m.strikeOf)")
            left = _marks(page)
            cross = next(m for m in left if m["shape"] == "cross")
            assert cross["state"] == "struck", left
            assert [m["strikeOf"] for m in left if m["strikeOf"]] == [cross["id"]], left
            assert not errors, errors
            page.close()

            # Reduced motion: both on the paper at once, and no pen travels.
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            _set(page, OX)
            came = page.evaluate(RECORD, [[["alpha", "ink-o"], ["alpha", "ink-x"]]])
            whole = [f for f in came
                     if sum(1 for m in f["marks"] if m[1] == "pane:alpha" and m[2] == 1) == 2]
            assert whole and came.index(whole[0]) <= 1, f"not drawn at once: {[f['marks'] for f in came[:4]]}"
            assert not any(f["hands"] for f in came), "a pen travelled under reduced motion"
            assert not errors, errors
            page.close()

            # A rail: only the first pane is open, so beta is 48px wide and the X goes down its middle.
            S.update_window("main", open="alpha", widths={"alpha": 1})
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=1)
            _set(page, OX)
            rail = page.evaluate("""() => { const r = document.querySelector('.tile[data-repo="beta"]')
              .getBoundingClientRect(); return { x: r.left, w: r.width }; }""")
            assert rail["w"] < 90, rail
            _mark(page, "beta", "ink-x")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'cross' && m.drawn === 1)")
            [cross] = [m for m in _marks(page) if m["shape"] == "cross"]
            assert (cross["lane"], cross["strokes"]) == ("pane:beta", 2), cross
            u = _union(cross["bounds"])
            assert abs((u["x"] + u["r"]) / 2 - (rail["x"] + rail["w"] / 2)) <= 3, (u, rail)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


#: #388: a skin's material drawn with a tool's own stroke. The `frame` hook keeps alpha's pane group,
#: counts its calls and asks for a frame, so that a group built again is ticked; `tick` draws a
#: 200px pencil line in the pen's ink into it, 70px down the pane, advancing its head at the pen's
#: speed (all of it at once under reduced motion), and draws it again whenever its handle is dead.
#: `hold` stops it. Each tick that advanced the head is `[tick, stroke, head, len, reduced]`.
MATERIAL = """() => {
  const s = window.__m = { frames: 0, group: null, h: null, pos: 0, made: 0, calls: 0, ticks: [], hold: false };
  return Ink.setSkin({ name: 'material', series: false, marks: [] }, {
    frame({ scene, api }, el) {
      if (el.dataset.repo !== 'alpha') return;
      s.frames += 1;
      s.group = scene;
      api.request();
    },
    tick({ api }, dt) {
      s.calls += 1;
      if (!s.group || s.hold) return false;
      if (!s.h || s.h.dead) {
        s.h = api.stroke(s.group, { pts: [[20, 70], [220, 70]], nobow: true }, 'pencil', { ink: 'pen', seed: 7 });
        s.made += 1;
        s.pos = 0;
      }
      if (s.pos >= s.h.len) return false;
      s.pos = api.reduced ? s.h.len : Math.min(s.h.len, s.pos + 900 * dt);
      s.h.head(s.pos);
      s.ticks.push([s.calls, s.made, s.pos, s.h.len, api.reduced]);
      return s.pos < s.h.len;
    },
  }).then(o => o.drawn);
}"""

#: The material line is on the paper whole, from a live handle.
DRAWN = "!!__m.h && !__m.h.dead && __m.h.len > 190 && __m.pos >= __m.h.len"

#: `READ`'s box over `w` px of the material line from `x0` px into the pane: its group is at the
#: pane's top-left, and the line is 70px down it.
LINE = """([x0, w]) => { const r = document.querySelector('.tile[data-repo="alpha"]').getBoundingClientRect();
  return [{ x: r.left + x0, y: r.top + 68, w, h: 4,
            at: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9].flatMap(fx => [[fx, 0.25], [fx, 0.5], [fx, 0.75]]) }]; }"""

#: The pen's ink, pure, on <html>, which the layer observes -- and first the pencil's, so a line
#: drawn in its own tool's ink reads as the wrong colour.
INK_PEN = """([pen, pencil]) => { const s = document.documentElement.style;
  s.setProperty('--ink-pen', pen); if (pencil) s.setProperty('--ink-pencil', pencil); }"""

#: A skin that draws nothing and hands the test the renderer from its hook.
PROBE = """() => Ink.setSkin({ name: 'probe', series: false, marks: [] },
  { frame({ api }) { window.__r = api.renderer; } }).then(o => o.drawn)"""

#: What `api.stroke` says, from a hook, to a tool and to an ink that are no tool.
REFUSE = """() => new Promise(done => Ink.setSkin({ name: 'refuse', series: false, marks: [] }, {
  frame({ scene, api }) {
    done([['crayon', {}], ['pencil', { ink: 'crayon' }]].map(([tool, opts]) => {
      try { api.stroke(scene, { pts: [[0, 0], [10, 0]] }, tool, opts); return ''; }
      catch (e) { return e.name + ': ' + e.message; } }));
  } }))"""


@pytest.mark.browser
def test_a_skin_draws_a_material_with_a_tools_stroke(fleet_home, tmp_path):
    """#388. `api.stroke` draws a skin's material with a tool's own stroke -- here the pencil's grain
    in the pen's ink -- into a group a hook was handed, from head 0: the skin advances the head in
    `tick`, and the line is on the paper in the pen's ink once complete and nowhere at head 0. At
    rest the desk writes nothing and draws nothing. The stroke dies with its group: a palette change
    and a resize build the pane's frame again, the old handle says `dead`, and the skin draws the
    line again, in the new ink, and the live strokes do not grow. Replacing the skin frees every
    geometry it made. A tool or an ink that is no tool is refused, naming it. Reduced motion draws
    the line whole on the first tick."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
            page.evaluate(INK_PEN, ["#ff0000", "#0000ff"])

            # The geometries on the GPU before the skin, read through `api.renderer` from a hook.
            assert page.evaluate(PROBE) == "ink"
            _rest(page, "!!window.__r")
            before = page.evaluate("() => window.__r.info.memory.geometries")

            # Drawn at the pen's speed, then on the paper in the pen's ink, never the pencil's.
            assert page.evaluate(MATERIAL) == "ink"
            _rest(page, DRAWN)
            at = page.evaluate(LINE, [20, 200])
            page.wait_for_function(PURE, arg=[at, 0], timeout=10000)
            assert not page.evaluate(PURE, [at, 2]), page.evaluate(READ, at)
            ticks = page.evaluate("() => __m.ticks")
            assert ticks[0][2] < ticks[0][3] / 2 and all(t[4] is False for t in ticks), ticks
            assert _layer(page)["skin"]["strokes"] == 1, _layer(page)["skin"]

            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle desk rendered frames: {count}"

            # At head 0 the line is nowhere.
            page.evaluate("() => { __m.hold = true; __m.h.head(0); }")
            bare = page.evaluate(READ, at)[0]
            assert not any(px[3] > 8 for px in bare), bare
            page.evaluate("() => { __m.h.head(__m.h.len); __m.hold = false; }")
            page.wait_for_function(PURE, arg=[at, 0], timeout=10000)

            # A palette change empties the group: the old handle is dead, `frame` is called again,
            # and the line drawn again in the new group reads in the new ink.
            page.evaluate("() => { window.__old = __m.h; window.__was = __m.frames; }")
            page.evaluate(INK_PEN, ["#00ff00", None])
            _rest(page, "__old.dead && __m.frames > __was && __m.h !== __old && " + DRAWN)
            page.wait_for_function(PURE, arg=[at, 1], timeout=10000)
            assert not page.evaluate(PURE, [at, 0]), page.evaluate(READ, at)

            # Five resizes of the window, and so of the pane: each builds its frame again, and the
            # live strokes stay one.
            live = []
            for i in range(5):
                page.evaluate("() => { window.__old = __m.h; window.__was = __m.frames; }")
                page.set_viewport_size({"width": 1340 - 60 * i, "height": 900})
                _rest(page, "__old.dead && __m.frames > __was && __m.h !== __old && " + DRAWN)
                live.append(_layer(page)["skin"]["strokes"])
            assert live == [1] * 5, live
            assert _layer(page)["skin"]["errors"] == [], _layer(page)["skin"]
            during = page.evaluate("() => window.__r.info.memory.geometries")
            assert during > before, (before, during)

            # Replacing the skin frees every geometry it made.
            assert page.evaluate(PROBE) == "ink"
            _rest(page, "Ink.inspect().table === 'probe'")
            after = page.evaluate("() => window.__r.info.memory.geometries")
            assert after == before, (before, during, after)
            assert _layer(page)["skin"]["strokes"] == 0, _layer(page)["skin"]

            # A tool, or an ink, that is no tool is refused, naming the argument.
            refused = page.evaluate(REFUSE)
            assert refused[0].startswith("TypeError: ") and "`tool` \"crayon\"" in refused[0], refused
            assert refused[1].startswith("TypeError: ") and "`ink` \"crayon\"" in refused[1], refused
            assert not errors, errors
            page.close()

            # Reduced motion: the whole line on the first tick, and on the paper to its end.
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            page.evaluate(INK_PEN, ["#ff0000", "#0000ff"])
            assert page.evaluate(MATERIAL) == "ink"
            _rest(page, DRAWN)
            ticks = page.evaluate("() => __m.ticks")
            assert len(ticks) == 1 and ticks[0][:2] == [1, 1] and ticks[0][2] == ticks[0][3], ticks
            assert ticks[0][4] is True, ticks
            page.wait_for_function(PURE, arg=[page.evaluate(LINE, [185, 20]), 0], timeout=10000)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
