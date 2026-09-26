"""The right skin on the first frame (#345): what the desk and /settings paint, frame by frame.

`SAMPLER` is an init script: on every animation frame on which anything it watches changed, it
pushes `{t, skin, bg, table, inkOff, h1, headerBg}` -- `body.dataset.skin` (null before there is a
<body>), the inline `--bg` on <html>, `Ink.inspect().table`, the `ink-off` class, and the computed
colour of `header h1` and background of `header` -- onto `window.__frames`, and keeps the buffered
`first-paint` time in `window.__firstPaint`. #346 imports it.

One browser for the module; a server per test. Every wait is on a condition.
"""
from __future__ import annotations

import json
import re

import pytest

from agentdata import theme as T
from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (_desk_of, _facts, _serve, _stop, fleet_home)  # noqa: F401

SAMPLER = """
(() => {
  window.__frames = [];
  window.__firstPaint = null;
  window.__writes = [];
  const t0 = performance.now();
  let last = "";
  function colour(sel, prop) {
    const el = document.querySelector(sel);
    return el ? getComputedStyle(el)[prop] : null;
  }
  function sample() {
    const body = document.body;
    let table = null;
    try { table = window.Ink ? window.Ink.inspect().table : null; } catch (e) { table = null; }
    const f = {
      skin: body ? (body.dataset.skin || "") : null,
      bg: document.documentElement ? document.documentElement.style.getPropertyValue("--bg") : "",
      table: table,
      inkOff: body ? body.classList.contains("ink-off") : null,
      h1: colour("header h1", "color"),
      headerBg: colour("header", "backgroundColor"),
    };
    const key = JSON.stringify(f);
    if (key !== last) {
      last = key;
      f.t = Math.round(performance.now() - t0);
      window.__frames.push(f);
    }
    requestAnimationFrame(sample);
  }
  requestAnimationFrame(sample);
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) if (e.name === "first-paint") window.__firstPaint = e.startTime;
    }).observe({ type: "paint", buffered: true });
  } catch (e) {}
  // Every write to what the theme is: <html>'s style and data-theme, <body>'s data-skin and
  // data-skin-variant, and the skin link's href. The parser's own attributes are not mutations.
  new MutationObserver(records => {
    for (const r of records) {
      const el = r.target;
      const theme = (el === document.documentElement && (r.attributeName === "style" || r.attributeName === "data-theme"))
        || (el === document.body && (r.attributeName === "data-skin" || r.attributeName === "data-skin-variant"))
        || (el.matches && el.matches("link[data-skin]") && r.attributeName === "href");
      if (theme) window.__writes.push({ el: el.tagName, name: r.attributeName, t: Math.round(performance.now() - t0) });
    }
  }).observe(document, { subtree: true, attributes: true,
                         attributeFilter: ["style", "data-theme", "data-skin", "data-skin-variant", "href"] });
  addEventListener("pageshow", e => { if (e.persisted) window.__frames = []; });
})();
"""

# The desk has had its first `/api/fleet` answer and its stream's first `theme` frame.
SETTLED = """() => typeof lastFleet !== 'undefined' && !!lastFleet && themeEvents > 0
             && !document.body.classList.contains('is-stale') && !!window.Ink"""


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


def _config(fleet_home, **theme):
    (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": theme}), encoding="utf-8")


def _page(browser):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.add_init_script(SAMPLER)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page, errors


def _desk(page, port, token, extra=""):
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(SETTLED, timeout=15000)


def _frames(page):
    return page.evaluate("() => ({ frames: window.__frames, paint: window.__firstPaint })")


def _wrong(frames, skin, bg, old):
    """The frames with a <body> that do not wear `skin` and `bg`, or whose ink names `old`."""
    return [f for f in frames if f["skin"] is not None and
            (f["skin"] != skin or f["bg"] != bg or (f["table"] or "").startswith(old))]


def _setup(fleet_home, tmp_path, skin="voxel:nether"):
    PR.record(_facts(shell="browser"))
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    _config(fleet_home, skin=skin)


def _to_settings_and_choose(page, skin):
    page.locator("#setbtn").click()
    page.wait_for_function("() => document.querySelectorAll('#skin option').length > 3", timeout=15000)
    got = page.evaluate("s => post('theme', { skin: s })", skin)
    assert got.get("ok", True), got


def _farmstead_bg():
    return S.theme_state()["css"]["--bg"]


@pytest.mark.browser
def test_leaving_settings_paints_the_new_skin_from_the_first_frame(browser, fleet_home, tmp_path):
    _setup(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _desk(page, port, token)
        page.wait_for_function("() => Ink.inspect().table === 'voxel:nether'", timeout=15000)
        _to_settings_and_choose(page, "farmstead:daytime")
        bg = _farmstead_bg()
        page.locator("#backbtn").click()
        page.wait_for_url(re.compile(r"/\?"), timeout=15000)
        page.wait_for_function(SETTLED, timeout=15000)
        page.wait_for_function("() => Ink.inspect().table === 'farmstead:daytime'", timeout=15000)
        seen = _frames(page)
        print(f"\n  back from /settings: first paint {seen['paint']} ms, {len(seen['frames'])} frames")
        assert seen["frames"] and not _wrong(seen["frames"], "farmstead", bg, "voxel"), seen["frames"]
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_back_button_paints_the_new_skin_first(browser, fleet_home, tmp_path):
    _setup(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _desk(page, port, token)
        page.wait_for_function("() => Ink.inspect().table === 'voxel:nether'", timeout=15000)
        _to_settings_and_choose(page, "farmstead:daytime")
        bg = _farmstead_bg()
        page.go_back(wait_until="domcontentloaded")
        page.wait_for_function(SETTLED, timeout=15000)
        page.wait_for_function("() => document.body.dataset.skin === 'farmstead'"
                               " && Ink.inspect().table === 'farmstead:daytime'", timeout=15000)
        seen = _frames(page)
        print(f"\n  Back: first paint {seen['paint']} ms, {len(seen['frames'])} frames")
        assert seen["frames"] and not _wrong(seen["frames"], "farmstead", bg, "voxel"), seen["frames"]
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_reload_after_a_streamed_change_paints_the_new_skin_first(browser, fleet_home, tmp_path):
    _setup(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _desk(page, port, token)
        page.wait_for_function("() => Ink.inspect().table === 'voxel:nether'", timeout=15000)
        page.evaluate("s => post('theme', { skin: s })", "farmstead:daytime")
        # Reached this window down the stream, not by a fetch it asked for.
        page.wait_for_function("() => document.body.dataset.skin === 'farmstead'", timeout=15000)
        bg = _farmstead_bg()
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(SETTLED, timeout=15000)
        page.wait_for_function("() => Ink.inspect().table === 'farmstead:daytime'", timeout=15000)
        seen = _frames(page)
        print(f"\n  reload: first paint {seen['paint']} ms, {len(seen['frames'])} frames")
        assert seen["frames"] and not _wrong(seen["frames"], "farmstead", bg, "voxel"), seen["frames"]
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_settings_page_paints_the_chosen_skin_first(browser, fleet_home, tmp_path):
    _setup(fleet_home, tmp_path, skin="farmstead:daytime")
    bg = _farmstead_bg()
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
        page.wait_for_function("() => window.__firstPaint !== null"
                               " && window.__frames.some(f => f.skin !== null)", timeout=15000)
        seen = _frames(page)
        first = next(f for f in seen["frames"] if f["skin"] is not None)
        print(f"\n  /settings: first paint {seen['paint']} ms, first body frame at {first['t']} ms")
        assert first["skin"] == "farmstead" and first["bg"] == bg, first
        assert first["inkOff"] is True, first
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_loading_the_desk_rewrites_no_theme_attribute(browser, fleet_home, tmp_path):
    """The first `/api/fleet` answer and the stream's first `theme` frame find the served theme in
    place and write nothing: a palette, a skin with its variant, custom tiers -- and `example`, the
    skin module skins.py does not offer."""
    PR.record(_facts(shell="browser"))
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1})     # gamma is a rail
    server, token, port = _serve()
    try:
        for theme, fleet in (({"skin": "farmstead:daytime"}, {"tiers": {"rail_px": 56, "compact_px": 200}}),
                             ({"skin": "example"}, {})):
            (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": theme, "fleet": fleet}),
                                                        encoding="utf-8")
            page, errors = _page(browser)
            page.route("**/static/skins/example/skin.css*", lambda route: route.fulfill(
                status=200, content_type="text/css; charset=utf-8", body=""))
            _desk(page, port, token)
            family = theme["skin"].split(":")[0]
            got = page.evaluate("""() => ({ writes: window.__writes, skin: document.body.dataset.skin,
                variant: document.body.dataset.skinVariant || null,
                tiers: document.documentElement.dataset.tiers || null,
                rail: document.documentElement.style.getPropertyValue('--rail') })""")
            print(f"\n  {theme['skin']}: {len(got['writes'])} theme writes after load")
            assert got["skin"] == family, got
            assert got["writes"] == [], got
            if family == "example":
                assert got["variant"] is None and got["tiers"] is None, got
            else:
                assert got["variant"] == "daytime" and got["tiers"] == "56 200 360 8", got
                assert got["rail"] == "56px", got
                # The first pane is drawn at the configured tier: a rail 56px wide.
                width = page.evaluate("""() => document.querySelector('#grid .tile[data-tier="rail"]')
                                           .getBoundingClientRect().width""")
                assert round(width) == 56, width
            assert not errors, errors
            page.close()
    finally:
        _stop(server)


def _rgb(css: str):
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", css or "")
    if not m:
        return None, 0.0
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    return f"#{r:02x}{g:02x}{b:02x}", float(m.group(4)) if m.group(4) is not None else 1.0


@pytest.mark.browser
def test_a_skinned_page_is_legible_from_its_first_frame(browser, fleet_home, tmp_path):
    """farmstead:daytime, whose band text is keyed on `:not(.ink-off)`: every frame of /settings,
    of a desk no probe measured and of a `?ink=on` desk reads 4.5:1 while its header is opaque.
    Once the ink draws, the header is clear by design and the canvas is what it is read on."""
    _desk_of(tmp_path, ("alpha", "beta"))
    _config(fleet_home, skin="farmstead:daytime")
    server, token, port = _serve()
    try:
        for path, ready in (("/settings?t={t}", "() => window.__frames.some(f => f.h1 !== null)"
                                                " && document.readyState === 'complete'"),
                            ("/?t={t}&w=unmeasured", SETTLED),
                            ("/?t={t}&ink=on", SETTLED + " && !!document.querySelector('#ink[data-skin]')"
                                           " && !document.body.classList.contains('ink-off')")):
            page, errors = _page(browser)
            page.goto(f"http://127.0.0.1:{port}" + path.format(t=token), wait_until="domcontentloaded")
            page.wait_for_function(ready, timeout=15000)
            frames = _frames(page)["frames"]
            read = []
            for f in frames:
                text, _ = _rgb(f["h1"])
                ground, alpha = _rgb(f["headerBg"])
                if text and ground and alpha == 1.0:
                    read.append((f["t"], round(T.contrast_ratio(text, ground), 2), f["inkOff"]))
            print(f"\n  {path.split('?')[0]} {path.split('&')[-1]}: {read[:6]}")
            assert read, (path, frames)
            assert all(r[1] >= 4.5 for r in read), (path, read)
            assert not errors, errors
            page.close()
    finally:
        _stop(server)
