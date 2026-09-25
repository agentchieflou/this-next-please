"""The desk preloads the ink modules its served skin will import (#349).

The modules loaded as a waterfall that began only once `body[data-skin]` was set: ink.js imported
the skin module, then (with the gate on) `layer.js`, which imported three.js, `shapes.js` and
`pen.js`. The served page (#345) already knows the skin family and the gate, so `_page` names what
will be imported as `<link rel="modulepreload">`, at the URL `q()` builds, and the browser fetches
it in parallel with the page. The module map dedupes, so each module is still fetched once.

One browser for the module; a server per test. Every wait is on a condition.
"""
from __future__ import annotations

import json
import re
import urllib.request

import pytest

from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _desk_of, _facts, _serve, _stop, fleet_home  # noqa: F401

LAYER = ("ink/layer.js", "ink/shapes.js", "ink/pen.js", "vendor/three/three.module.min.js")
PRELOAD = re.compile(r'<link rel="modulepreload" href="/static/([^"?]+)\?t=([^"]+)">')


def _config(fleet_home, skin):
    (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": {"skin": skin}}), encoding="utf-8")


def _get(port, path, token, extra=""):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?t={token}{extra}", timeout=10) as r:
        return r.read().decode("utf-8")


def _preloads(html, token):
    found = PRELOAD.findall(html)
    assert all(t == token for _, t in found), found
    head = html[:html.index("</head>")]
    assert all(f'/static/{p}?t={token}' in head for p, _ in found), "a preload outside <head>"
    return [p for p, _ in found]


# ---------------------------------------------------------------------------- the served markup


def test_the_gate_on_preloads_the_skin_and_the_layer(fleet_home):
    _config(fleet_home, "voxel:nether")
    PR.record(_facts(shell="browser"))
    server, token, port = _serve()
    try:
        html = _get(port, "/", token)
        assert _preloads(html, token) == ["ink/skins/voxel.js", *LAYER]
        # After the skin's stylesheet, which stays the last thing before </head> (#345).
        assert html.index('rel="modulepreload"') < html.index('data-skin="true"')
        assert re.search(r'skin\.css\?t=[^"]+"></head>', html)
    finally:
        _stop(server)


def test_ink_on_in_the_address_is_the_gate_on(fleet_home):
    _config(fleet_home, "voxel:nether")
    server, token, port = _serve()
    try:
        assert _preloads(_get(port, "/", token, "&ink=on"), token) == ["ink/skins/voxel.js", *LAYER]
    finally:
        _stop(server)


def test_the_gate_off_preloads_the_skin_module_alone(fleet_home):
    _config(fleet_home, "voxel:nether")
    server, token, port = _serve()
    try:
        assert _preloads(_get(port, "/", token), token) == ["ink/skins/voxel.js"], "no probe: gate off"
        PR.record(_facts(shell="browser"))
        assert _preloads(_get(port, "/", token, "&ink=off"), token) == ["ink/skins/voxel.js"]
    finally:
        _stop(server)


def test_no_skin_preloads_nothing(fleet_home):
    PR.record(_facts(shell="browser"))
    server, token, port = _serve()
    try:
        assert "modulepreload" not in _get(port, "/", token)
        assert "modulepreload" not in _get(port, "/", token, "&ink=on")
    finally:
        _stop(server)


def test_a_skin_that_does_not_draw_with_ink_preloads_nothing(fleet_home, monkeypatch):
    monkeypatch.setattr(S, "ink_skins", lambda: ["farmstead"])
    _config(fleet_home, "voxel:nether")
    server, token, port = _serve()
    try:
        assert "modulepreload" not in _get(port, "/", token, "&ink=on")
    finally:
        _stop(server)


def test_settings_and_probe_carry_no_preload(fleet_home):
    _config(fleet_home, "voxel:nether")
    PR.record(_facts(shell="browser"))
    server, token, port = _serve()
    try:
        for route in ("/settings", "/probe"):
            assert "modulepreload" not in _get(port, route, token, "&ink=on"), route
    finally:
        _stop(server)


def test_two_gates_are_two_gzipped_desks():
    """The preload set is in the gzip cache key, so a gate-on desk is never served a gate-off one."""
    ts = {"theme": "none", "skin": "voxel:nether", "css": {}, "tiers": {}}
    on, off = S.ink_preload(ts, "tok", gate_on=True), S.ink_preload(ts, "tok", gate_on=False)
    assert on != off and off in on


# ---------------------------------------------------------------------------- in the browser

#: Every static request and the time the first ink frame was drawn.
FIRST_FRAME = """
(() => {
  window.__firstInk = null;
  const t0 = performance.now();
  function look() {
    try {
      const l = window.Ink && window.Ink.inspect().layer;
      if (l && l.renders > 0) { window.__firstInk = Math.round(performance.now() - t0); return; }
    } catch (e) {}
    requestAnimationFrame(look);
  }
  requestAnimationFrame(look);
})();
"""


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


def _open(browser, port, token, extra):
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.add_init_script(FIRST_FRAME)
    asked, errors = [], []
    page.on("request", lambda r: asked.append(r.url))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    return context, page, asked, errors


def _count(asked, port, path, token):
    return asked.count(f"http://127.0.0.1:{port}/static/{path}?t={token}")


@pytest.mark.browser
def test_the_page_preloads_what_its_skin_will_import_and_nothing_else(browser, fleet_home, tmp_path):
    _desk_of(tmp_path)
    _config(fleet_home, "voxel:nether")
    PR.record(_facts(shell="browser"))
    server, token, port = _serve()
    try:
        context, page, asked, errors = _open(browser, port, token, "")
        try:
            page.wait_for_function("() => window.__firstInk !== null", timeout=30000)
            timing = page.evaluate("""() => {
              const nav = performance.getEntriesByType('navigation')[0];
              const at = part => { const e = performance.getEntriesByType('resource').find(r => r.name.includes(part));
                                   return e ? Math.round(e.startTime * 10) / 10 : null; };
              return { dcl: nav.domContentLoadedEventStart, skin: at('/ink/skins/voxel.js'),
                       layer: at('/ink/layer.js'), shapes: at('/ink/shapes.js'), pen: at('/ink/pen.js'),
                       three: at('/vendor/three/'), first: window.__firstInk };
            }""")
            print(f"\ngate on: first ink frame {timing['first']} ms; requests start (ms): {timing}")
            assert timing["skin"] is not None and timing["skin"] < timing["dcl"], timing
            # All five in parallel with the page, not one after another once it has run.
            for name in ("layer", "shapes", "pen", "three"):
                assert timing[name] is not None and timing[name] < timing["dcl"], (name, timing)
            for path in ("ink/skins/voxel.js", *LAYER):
                assert _count(asked, port, path, token) == 1, (path, [u for u in asked if "/static/" in u])
            assert not errors, errors
        finally:
            context.close()

        context, page, asked, errors = _open(browser, port, token, "&ink=off")
        try:
            page.wait_for_function("() => window.Ink && Ink.inspect().table === 'voxel:nether'", timeout=30000)
            assert _count(asked, port, "ink/skins/voxel.js", token) == 1, asked
            for path in LAYER:
                assert _count(asked, port, path, token) == 0, (path, asked)
            assert not errors, errors
        finally:
            context.close()
    finally:
        _stop(server)
