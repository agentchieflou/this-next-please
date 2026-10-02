"""The map's scene (#409, docs/fleet-map.md §The scene): `static/map/scene.js`.

On a shell whose probe measured hardware WebGL (or with `?ink=on`, the test override: CI draws on
SwiftShader, which the probe calls `software`), `/map` draws its tree as a three.js scene --
islands, lanes, network nodes and links, in at most four draw calls -- and draws a frame only when
the tree, the stage's size or the palette changed.

The first two tests read the sources. The five browser tests share the worker's Chromium
(`desk_browser`), a fresh context per page; every wait is a condition, and "nothing happens" is
counted over animation frames, never over a duration.
"""
from __future__ import annotations

import json
import math
import os
import re

import pytest

from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S

from desk_waits import record_mutations
from test_fleet_demo_ownership import SKIN_ON
from test_fleet_ink import SWIFTSHADER, _facts, _serve, _stop
from test_fleet_map import fleet_home  # noqa: F401 - fixture
from test_fleet_map_layout import COLOUR
from test_fleet_map_page import _fleet, _get

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(S.STATIC, "map")
SCENE = os.path.join(MAP, "scene.js")
LAYER = os.path.join(S.STATIC, "ink", "layer.js")
THREE = "/static/vendor/three/three.module.min.js"
#: The draw calls the scene may make on its own: islands, lanes, nodes, links (the map's 6 is #410's to fill).
CALLS = 4
#: Every probe class `probe.classify` gives (docs/desk-engines.md §WebGL).
PROBES = ("hardware", "software", "none", "unknown", "incomplete", "unmeasured")

READY = "() => !!window.FleetMap && FleetMap.graph !== null"
#: The scene has drawn at least `n` frames.
DRAWN = "n => !!FleetMap.scene && FleetMap.scene.inspect().frames >= n"
#: `n` animation frames, counted in the page.
FRAMES = "async n => { for (let i = 0; i < n; i++) await new Promise(requestAnimationFrame); }"


def _body(src: str, name: str) -> str:
    """`function name(...) {...}` as written, to its closing brace at the start of a line."""
    at = src.index(f"function {name}(")
    return src[at:src.index("\n}\n", at) + 2]


def test_the_scene_copies_the_layers_context_and_colour_reader_verbatim():
    """Context first, as the layer and the probe do, and the palette read the layer's way: the two
    copies stay the layer's own (#409 Build 2), so a fix to one is a fix to both or a red test."""
    layer = open(LAYER, encoding="utf-8").read()
    scene = open(SCENE, encoding="utf-8").read()
    for name in ("context", "parseColour"):
        assert _body(scene, name) == _body(layer, name), f"map/scene.js's {name} is not ink/layer.js's"
    clamp = re.compile(r"(?m)^const clamp = .*$")
    assert clamp.search(scene).group(0) == clamp.search(layer).group(0)
    # Context before three.js: the import comes after `context(canvas)`.
    assert scene.index("const gl = context(canvas);") < scene.index("import(q(VENDOR))")


def test_the_maps_scripts_carry_no_colour_no_markup_no_2d_context_and_no_bare_import():
    """The map's ground rule 4 over every `static/map/**/*.js`: no colour literal (the palette is the
    page's tokens), no `innerHTML`, no 2D context, no static import, and every import through `q()`.
    three.js is named by the scene alone, from the vendored copy."""
    found = []
    for root, _dirs, files in os.walk(MAP):
        for n in sorted(files):
            if not n.endswith(".js"):
                continue
            rel = os.path.relpath(os.path.join(root, n), S.STATIC).replace(os.sep, "/")
            body = open(os.path.join(root, n), encoding="utf-8").read()
            found.append(rel)
            assert not re.search(COLOUR, body), f"a colour written in {rel}"
            for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
                assert banned not in body, f"{rel} uses {banned}"
            assert not re.search(r"getContext\(\s*['\"]2d['\"]|['\"]2d['\"]", body), f"{rel} names a 2D context"
            assert not re.search(r"(?m)^\s*import\s[^(]", body), f"{rel} has a static import"
            for spec in re.findall(r"import\(([^)]*\))", body):
                assert spec.startswith("q("), f"{rel} imports {spec} without the token"
            if rel != "map/scene.js":
                assert "vendor/three" not in body and "three.module" not in body, rel
    assert {"map/map.js", "map/layout.js", "map/scene.js"} <= set(found), found
    scene = open(SCENE, encoding="utf-8").read()
    assert f'const VENDOR = "{THREE}";' in scene and "import(q(VENDOR))" in scene
    assert re.search(r"(?m)^export function use\(plugin\) \{", scene)
    assert re.search(r"(?m)^export async function start\(host\) \{", scene)
    # The scene draws on demand: no loop that asks for a frame whatever happened.
    assert scene.count("requestAnimationFrame(") == 1 and "setInterval" not in scene


# -------------------------------------------------------------------------------- the browser


@pytest.fixture()
def browser(desk_browser):
    """The worker's shared Chromium (tests/desk_harness.py); this test's contexts close when it ends."""
    return desk_browser


def _open(browser, port, token, extra="", viewport=(1400, 900), init=None):
    """`/map` in a fresh context: the page, its page errors, and every URL it asked for."""
    page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
    errors, asked = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: asked.append(r.url))
    if init:
        page.add_init_script(init)
    page.goto(f"http://127.0.0.1:{port}/map?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(READY, timeout=15000)
    return page, errors, asked


def _gate_table() -> dict:
    """docs/desk-ink.md §The gate, read as `{(probe, asked): on}`: each class's row without a
    parameter, and the `?ink=off` and `?ink=on` rows for every class."""
    doc = open(os.path.join(ROOT, "docs", "desk-ink.md"), encoding="utf-8").read()
    gate = doc[doc.index("## The gate"):doc.index("### The test override")]
    rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in gate.splitlines()
            if ln.startswith("| ") and not ln.startswith("| ---") and "Probe says" not in ln]
    plain = {m.group(1): r[2].startswith("yes") for r in rows if (m := re.fullmatch(r"`(\w+)`", r[1]))}
    assert set(plain) == set(PROBES), plain
    off = next(r for r in rows if "?ink=off" in r[0])
    on = next(r for r in rows if "?ink=on" in r[0])
    table = {(p, ""): plain[p] for p in PROBES}
    table.update({(p, "off"): off[2].startswith("yes") for p in PROBES})
    table.update({(p, "on"): on[2].startswith("yes") for p in PROBES})
    return table


#: Every treeitem's id, and every id the graph names that the tree draws.
TREE_IDS = "() => [...document.querySelectorAll('#maptree [data-node]')].map(li => li.dataset.node)"
#: What the page shows of the scene: the class, the canvas, `ink-off`, the verdict.
LOOK = """() => ({ scene: document.body.classList.contains('map-scene'), inkOff: document.body.classList.contains('ink-off'),
  canvas: document.querySelectorAll('canvas').length, verdict: FleetMap.verdict, surface: FleetMap.scene !== null })"""


def _graph_ids(port, token) -> set:
    g = json.loads(_get(port, "/api/map", token))
    return ({p["id"] for p in g["projects"]} | {c["id"] for c in g["checkouts"]}
            | {c["agent"]["id"] for c in g["checkouts"] if c.get("agent")})


@pytest.mark.browser
def test_the_gate_is_the_ink_gate_and_without_it_the_map_is_the_tree_alone(browser, fleet_home, tmp_path):
    """`FleetMap.gate` is docs/desk-ink.md §The gate for every probe class and parameter. `?ink=off`,
    a `software` probe without `?ink=on`, and a shell with no WebGL get no canvas, no `map-scene`,
    no three.js, and the whole tree."""
    _fleet(tmp_path)
    PR.record(_facts(shell="vscode", renderer=SWIFTSHADER))
    server, token, port = _serve()
    try:
        page, errors, asked = _open(browser, port, token, "&ink=off")
        cases = [[p, a, n] for p in PROBES for a in ("on", "off", "") for n in (False, True)]
        got = page.evaluate("cs => cs.map(([p, a, n]) => FleetMap.gate(p, a, n))", cases)
        table = _gate_table()
        for (probe, ask, narrow), v in zip(cases, got):
            want = table[(probe, ask)] and not (narrow and ask == "")
            assert v["on"] is want, (probe, ask, narrow, v)
            assert v["source"] == {"on": "override", "off": "param"}.get(ask, "narrow" if narrow else "probe"), v
            assert v["why"], v
        want_ids = _graph_ids(port, token)
        assert want_ids and want_ids <= set(page.evaluate(TREE_IDS))
        look = page.evaluate(LOOK)
        assert look == {"scene": False, "inkOff": True, "canvas": 0, "surface": False,
                        "verdict": {"on": False, "source": "param", "why": "?ink=off"}}, look
        page.close()

        # A shell the probe measured as software: the tree alone, and three.js never asked for.
        page, more, asked2 = _open(browser, port, token, "&w=vscode")
        page.wait_for_function("() => document.querySelectorAll('#maptree [data-node^=\"a:\"]').length > 0",
                               timeout=15000)
        look = page.evaluate(LOOK)
        assert look["verdict"]["on"] is False and look["verdict"]["source"] == "probe", look
        assert "software" in look["verdict"]["why"], look
        assert (look["scene"], look["canvas"], look["inkOff"]) == (False, 0, True), look
        errors += more
        page.close()

        # No WebGL at all, with the override on: the scene is fetched, asks for a context, gets none,
        # and turns itself off before three.js is asked for.
        nogl = """(() => { const real = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function (kind) {
            return /webgl/i.test(String(kind)) ? null : real.apply(this, arguments); }; })();"""
        page, more, asked3 = _open(browser, port, token, "&ink=on", init=nogl)
        page.wait_for_function("() => FleetMap.verdict.source === 'runtime'", timeout=15000)
        look = page.evaluate(LOOK)
        assert (look["scene"], look["canvas"], look["inkOff"], look["surface"]) == (False, 0, True, False), look
        assert "no WebGL context" in look["verdict"]["why"], look
        assert want_ids <= set(page.evaluate(TREE_IDS))
        assert any("/static/map/scene.js" in u for u in asked3), asked3
        errors += more
        page.close()

        for urls in (asked, asked2, asked3):
            assert not [u for u in urls if "vendor/three" in u or "/static/ink/" in u], urls
        assert not [u for u in asked + asked2 if "/static/map/scene.js" in u]
        assert not errors, errors
    finally:
        _stop(server)


def _big(projects=10, per=2, branches=40) -> dict:
    """`projects` projects of `branches` lanes each (the graph's cap), `per` checkouts each, every
    one with an agent, and the network: a graph of the shape `/api/map` answers."""
    g = {"says": "a big fleet", "as_of": None, "projects": [], "checkouts": []}
    for i in range(projects):
        name = f"p{i:02d}"
        names = ["main"] + [f"feature/f{k:02d}" for k in range(1, branches)]
        g["projects"].append({
            "id": f"p:{name}", "name": name, "says": name, "default": "main",
            "branches_says": f"{branches} branches",
            "branches": [{"id": f"b:{name}:{n}", "name": n, "says": n, "unmerged": k % 3 == 1,
                          "carrying": False, "current_in": []} for k, n in enumerate(names)]})
        for j in range(per):
            repo = name if j == 0 else f"{name}-w{j}"
            g["checkouts"].append({
                "id": f"c:{repo}", "repo": repo, "project": name, "main": j == 0,
                "worktree_of": "" if j == 0 else f"c:{name}", "worktree_of_unregistered": False,
                "branch": "main" if j == 0 else "feature/f01", "dirty": False, "says": repo,
                "on": f"b:{name}:main" if j == 0 else f"b:{name}:feature/f01",
                "agent": {"id": f"a:{repo}", "kind": "headless", "state": "idle", "role": "idle",
                          "live": False, "needs_human": False, "stale": j == 1, "subagents": 0,
                          "says": "agent of " + repo}})
    g["network"] = {
        "says": "the network", "server": {"id": "n:server", "says": "the server"},
        "windows": [{"id": "w:main", "says": "window main", "connected": True},
                    {"id": "w:side", "says": "window side", "connected": False}],
        "sources": [{"id": "s:git", "says": "git", "cells": []}, {"id": "s:jira", "says": "jira", "cells": []}],
        "approvals": {"id": "n:approvals", "says": "no approvals waiting", "pending": 0},
        "install": {"id": "n:install", "says": "the install"}}
    return g


#: A plugin that writes down what it is told, handed to `use()` through the module the page loaded.
PLUGIN = """async () => {
  const m = await import(q('/static/map/scene.js'));
  window.__told = [];
  const unmerged = o => (o ? o.projects : []).flatMap(p => p.branches).filter(b => b.unmerged).map(b => b.id);
  return m.use({ attrs: ['data-scene-test'],
    attach: ctx => __told.push(['attach', Object.keys(ctx.meshes).sort().join(), typeof ctx.reserve]),
    rebuilt: (was, next, placed) => __told.push(['rebuilt', unmerged(next), placed.size]),
    inspect: () => ({ told: __told.length }) });
}"""


@pytest.mark.browser
def test_a_big_fleet_draws_in_four_calls_and_an_idle_map_draws_nothing(browser, fleet_home, tmp_path):
    """20 checkouts in 10 projects of 40 branches in at most four draw calls; 30 frames of nothing
    are 0 renders and 0 DOM mutations; one class toggled is one frame; a plugin is attached, told of
    the rebuild, and its `attrs` wake the scene."""
    server, token, port = _serve()
    try:
        page, errors, _ = _open(browser, port, token, "&ink=on")
        page.wait_for_function(DRAWN, arg=1, timeout=30000)
        assert page.evaluate(PLUGIN) is True
        page.wait_for_function("() => __told.some(t => t[0] === 'rebuilt')", timeout=15000)
        assert page.evaluate("() => __told[0]") == ["attach", "islands,lanes,links,nodes", "function"]

        g = _big()
        page.evaluate("g => FleetMap.draw(g)", g)
        drawn = 20 + 10 * 40 + 10 + 7                    # islands, lanes, gates, the network's nodes
        page.wait_for_function(f"() => FleetMap.scene.inspect().nodes === {drawn}", timeout=30000)
        seen = page.evaluate("() => FleetMap.scene.inspect()")
        print(f"\n  a 10x40 map: {seen['calls']} draw calls, {seen['triangles']} triangles, "
              f"first draw at {seen['first_draw_ms']} ms")
        assert 0 < seen["calls"] <= CALLS, seen
        assert seen["told"] >= 3 and seen["plugins"] == 1, seen
        assert page.evaluate("() => performance.getEntriesByName('map:first-draw').length") == 1

        # At rest: 30 animation frames with nothing changing are no render and no write. The stream
        # is open first, so its opening (`#maplink` says *live*) is not counted as the map's work.
        page.wait_for_function("() => FleetMap.stream.state === 'live'", timeout=15000)
        page.evaluate(FRAMES, 2)
        writes = record_mutations(page)
        before = page.evaluate("() => FleetMap.scene.inspect().frames")
        page.evaluate(FRAMES, 30)
        assert page.evaluate("() => FleetMap.scene.inspect().frames") == before
        assert writes.stop().count() == 0, writes.records()

        # One class on one tree item is one frame, and the plugin hears the outline it changed.
        lane = "b:p00:feature/f03"
        page.evaluate("id => document.querySelector(`[data-node=\"${id}\"]`).classList.add('unmerged')", lane)
        page.wait_for_function("n => FleetMap.scene.inspect().frames > n", arg=before, timeout=15000)
        page.evaluate(FRAMES, 10)
        assert page.evaluate("() => FleetMap.scene.inspect().frames") == before + 1
        last = page.evaluate("() => __told[__told.length - 1]")
        assert last[0] == "rebuilt" and lane in last[1] and last[2] == drawn, last[:1] + last[2:]

        # A plugin's attribute wakes the scene as a class does.
        page.evaluate("() => document.querySelector('[data-node=\"c:p00\"]').setAttribute('data-scene-test', '1')")
        page.wait_for_function("n => FleetMap.scene.inspect().frames === n + 2", arg=before, timeout=15000)
        assert page.evaluate("() => FleetMap.scene.inspect().calls") <= CALLS
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


def _small() -> dict:
    """One project: its trunk, an unmerged lane and a merged one; its main and a worktree; the hub."""
    g = _big(projects=1, per=2, branches=3)
    g["network"]["windows"], g["network"]["sources"] = [], []
    return g


def _hex(css: str) -> list:
    """A token as the stylesheet wrote it: `#rgb`, `#rrggbb`, or `rgb(r, g, b)`, as 0-1 floats."""
    s = css.strip().lower()
    if s.startswith("#"):
        h = s[1:]
        h = "".join(c * 2 for c in h) if len(h) == 3 else h[:6]
        return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+).*\)", s)
    assert m, f"a token this test cannot read: {css!r}"
    return [float(v) / 255 for v in m.groups()]


def _lum(c) -> float:
    f = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _ratio(a, b) -> float:
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _ink(text, bg) -> list:
    """The structural ink from the two tokens, by the WCAG formula: `--text` mixed toward `--bg` at
    the largest share of `--bg`, in hundredths, that keeps 3:1 on `--bg` (theme.py's `_muted` shape)."""
    for step in range(100, -1, -1):
        c = [math.floor((t + (b - t) * step / 100) * 255 + 0.5) / 255 for t, b in zip(text, bg)]
        if _ratio(c, bg) >= 3:
            return c
    return list(text)


#: The palette's two tokens as the page has them, the scene's ink and ground, and a readback of
#: the top faces of the trunk, an island and the hub, drawn for the purpose in the same task.
READ = """ids => { const cs = getComputedStyle(document.body), s = FleetMap.scene;
  const at = ids.map(id => s.screen(id));
  return { text: cs.getPropertyValue('--text').trim(), bg: cs.getPropertyValue('--bg').trim(),
           seen: s.inspect(), px: s.sample(at), at }; }"""


@pytest.mark.browser
def test_a_palette_change_draws_one_frame_and_structure_is_three_to_one_on_every_palette(
        browser, fleet_home, tmp_path):
    """Structure is one neutral ink, `--text` toward `--bg` until it would fall under 3:1 on `--bg`:
    computed here from the page's tokens in the default, `sand` and `eye-relief` palettes, drawn
    within 2/255 on the trunk, an island and the hub, and a palette change is one frame."""
    server, token, port = _serve()
    try:
        page, errors, _ = _open(browser, port, token, "&ink=on")
        page.wait_for_function(DRAWN, arg=1, timeout=30000)
        page.evaluate("g => FleetMap.draw(g)", _small())
        page.wait_for_function("() => FleetMap.scene.inspect().nodes === 2 + 3 + 1 + 3", timeout=30000)
        page.wait_for_function("() => FleetMap.stream.state === 'live'", timeout=15000)
        ids = ["b:p00:main", "c:p00", "n:server"]
        for palette in ("none", "sand", "eye-relief"):
            if palette != "none":
                before = page.evaluate("() => FleetMap.scene.inspect().frames")
                page.evaluate("""async name => { const u = new URL(location.href);
                  await fetch('/api/theme?t=' + u.searchParams.get('t'), { method: 'POST',
                    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: name }) }); }""",
                              palette)
                page.wait_for_function("n => FleetMap.scene.inspect().frames > n", arg=before, timeout=15000)
                page.evaluate(FRAMES, 10)
                assert page.evaluate("() => FleetMap.scene.inspect().frames") == before + 1, palette
            got = page.evaluate(READ, ids)
            text, bg = _hex(got["text"]), _hex(got["bg"])
            ink = _ink(text, bg)
            assert _ratio(ink, bg) >= 3, (palette, got["text"], got["bg"])
            want = [round(v * 255) for v in ink]
            have = _hex(got["seen"]["colours"]["ink"])
            assert [round(v * 255) for v in have] == want, (palette, got["seen"]["colours"], want)
            assert _hex(got["seen"]["colours"]["bg"]) == bg, (palette, got["seen"]["colours"])
            for at, px in zip(got["at"], got["px"]):
                assert px[3] == 255 and max(abs(a - b) for a, b in zip(px, want)) <= 2, (palette, at, px, want)
            print(f"\n  {palette}: ink {got['seen']['colours']['ink']} on {got['bg']}, "
                  f"{_ratio(ink, bg):.2f}:1, read back {got['px']}")
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


#: `header h1` and `#mapsays` against the header's background: the text and every background from the
#: header up, composited until one is opaque, and the WCAG ratio between them.
HEADER = """() => {
  const rgba = s => { const m = (s.match(/[\\d.]+/g) || ['0', '0', '0', '0']).map(Number);
                      return m.length > 3 ? m : m.concat([1]); };
  const over = (top, under) => top.slice(0, 3).map((v, i) => v * top[3] + under[i] * (1 - top[3])).concat([1]);
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                     return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const layers = [];
  for (let u = document.querySelector('header'); u; u = u.parentElement) {
    const c = rgba(getComputedStyle(u).backgroundColor);
    if (c[3] > 0) layers.push(c);
    if (c[3] >= 1) break;
  }
  const ground = layers.reverse().reduce((under, top) => over(top, under), [255, 255, 255, 1]);
  return ['header h1', '#mapsays'].map(sel => {
    const el = document.querySelector(sel), t = over(rgba(getComputedStyle(el).color), ground);
    const a = lum(t), b = lum(ground);
    return { what: sel, says: el.textContent, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
  });
}"""


@pytest.mark.browser
def test_the_header_reads_four_and_a_half_to_one_under_three_skins_with_the_scene_on(
        browser, fleet_home, tmp_path):
    _fleet(tmp_path)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(browser, port, token, "&ink=on")
        page.wait_for_function(DRAWN, arg=1, timeout=30000)
        page.wait_for_function("() => FleetMap.stream.state === 'live'", timeout=15000)
        for skin in ("farmstead:daytime", "glass:frost", "voxel:overworld"):
            page.evaluate("""async skin => { const u = new URL(location.href);
              await fetch('/api/theme?t=' + u.searchParams.get('t'), { method: 'POST',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ skin }) }); }""", skin)
            page.wait_for_function(SKIN_ON, arg=skin, timeout=15000)
            page.evaluate(FRAMES, 2)
            look = page.evaluate(LOOK)
            assert look["scene"] and look["canvas"] == 1 and look["inkOff"], (skin, look)
            seen = page.evaluate(HEADER)
            assert all(s["says"] for s in seen), (skin, seen)
            low = [s for s in seen if s["ratio"] < 4.5]
            assert low == [], (skin, low)
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


#: The page's width against its scroll width, the canvas's box against the stage's.
FILL = """() => { const d = document.documentElement, c = document.querySelector('#mapstage > canvas'),
  s = document.getElementById('mapstage').getBoundingClientRect(), r = c.getBoundingClientRect();
  return { sw: d.scrollWidth, cw: d.clientWidth, stage: [s.left, s.top, s.width, s.height],
           canvas: [r.left, r.top, r.width, r.height], buffer: [c.width, c.height] }; }"""


@pytest.mark.browser
def test_a_narrow_map_fills_its_stage_and_a_lost_context_leaves_the_tree(browser, fleet_home, tmp_path):
    _fleet(tmp_path)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(browser, port, token, "&ink=on", viewport=(480, 800))
        page.wait_for_function(DRAWN, arg=1, timeout=30000)
        box = page.evaluate(FILL)
        assert box["sw"] <= box["cw"], box
        assert box["stage"][2] >= 400 and box["stage"][3] >= 240, box
        assert all(abs(a - b) <= 1 for a, b in zip(box["canvas"], box["stage"])), box
        assert all(abs(a - b) <= 1 for a, b in zip(box["buffer"], box["stage"][2:])), box

        ids = page.evaluate(TREE_IDS)
        page.evaluate("""() => { const c = document.querySelector('#mapstage > canvas');
          (c.getContext('webgl2') || c.getContext('webgl')).getExtension('WEBGL_lose_context').loseContext(); }""")
        page.wait_for_function("() => !document.body.classList.contains('map-scene')", timeout=15000)
        look = page.evaluate(LOOK)
        assert (look["canvas"], look["inkOff"], look["surface"]) == (0, True, False), look
        assert look["verdict"]["source"] == "runtime" and "lost" in look["verdict"]["why"], look
        assert page.evaluate(TREE_IDS) == ids
        assert not errors, errors
        page.close()
    finally:
        _stop(server)
