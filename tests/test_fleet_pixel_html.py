"""Pixel-level HTML, measured (#384): the three routes docs/desk-engines.md §Pixel-level HTML weighs.

The operator asked for "full html awareness on what seems to be a pixel level". There are three ways
to get the desk's HTML into a WebGL scene, and this file measures each one in CI's Chromium rather
than taking a blog post's word for it:

1. **HTML-in-Canvas** (the WICG proposal): an element that is a child of a `<canvas layoutsubtree>`
   is uploaded as a texture. No shell ships it; Chromium has it behind a Blink flag, under one of
   three generations of names. The browser here is launched *with* that flag, so the probe page's
   `hic_api` and an actual upload can be held to each other.
2. **An SVG snapshot**: a pane cloned with its computed styles, serialised into a `foreignObject`,
   decoded as a `data:` image and uploaded with `texImage2D`. Works today; approximate and slow.
3. **DOM-synced geometry**: the line boxes and glyph boxes a `Range` reports. What the effects
   actually use (#375).

Every measured outcome of (1) passes -- found and uploaded, found and the renderer crashed in the
upload's own page (the operator's ruling on #446: the crash is the verdict), or not found and the
row falls back -- and the test prints which it saw and every timing. Nothing here asks for a 2D context, and the desk's own
DOM is left as it was found: the one canvas the test adds is its own, and it takes it away again.
"""
from __future__ import annotations

import pytest

from agentdata.fleet import probe as PR, registry, serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _desk_of, _serve, _stop

#: The switch that turns on Chromium's HTML-in-Canvas behind its flag. For this test only: no shell
#: is ever launched with it, and no origin-trial token is committed (#384's Decision).
HIC_FLAG = "--enable-blink-features=CanvasDrawElement"

#: Every call to `getContext`, on any canvas, recorded before the page's own scripts run.
WATCH_CONTEXTS = """
  window.__contexts = [];
  for (const C of [window.HTMLCanvasElement, window.OffscreenCanvas]) {
    if (!C) continue;
    const real = C.prototype.getContext;
    C.prototype.getContext = function (kind) {
      window.__contexts.push({ kind: String(kind), on: C.name });
      return real.apply(this, arguments);
    };
  }"""

#: (a) The upload, with whichever generation of the API the prototype has. Each form is the one its
#: engine takes, not a guess from the arity:
#:
#: - `texElement2D/6` (Chromium 141) and `texElementImage2D/6` (Chromium 138-149):
#:   (target, level, internalformat, format, type, element), with an unsized `RGBA`;
#: - `texElementImage2D/3` (Chromium 150+): (target, internalformat, element), and the format must
#:   be sized (`RGBA8`): three.js dev calls `texElementImage2D(TEXTURE_2D, RGBA8, element)`;
#: - `texElementSubImage2D/5` (the explainer): (target, level, xoffset, yoffset, element), into
#:   storage allocated first.
#:
#: Any other name or arity is a form this test has not met, and it says so rather than guessing.
#: The pane's clone is marked `drawable` and laid out inside a `<canvas layoutsubtree>` the test
#: adds and removes. Where the engine has the canvas `paint` event (the explainer: an element's
#: snapshot exists only once it has been painted), the upload happens inside it, after
#: `requestPaint()`; an engine without it (Chromium 141) uploads after two frames. The texture is
#: read back through a framebuffer.
UPLOAD = """async ([name, arity]) => {
  const pane = document.querySelector('#grid .tile.is-solo');
  const r = pane.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  const canvas = document.createElement('canvas');
  canvas.setAttribute('layoutsubtree', '');
  canvas.width = w; canvas.height = h;
  const child = pane.cloneNode(true);
  child.setAttribute('drawable', '');
  canvas.appendChild(child);
  document.body.appendChild(canvas);
  const painted = 'onpaint' in canvas || typeof canvas.requestPaint === 'function';
  const out = { name, arity, w, h, error: '', lit: 0, ms: null, via: painted ? 'paint' : 'frames' };
  try {
    const gl = canvas.getContext('webgl2');
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    const form = name + '/' + arity;
    const call = () => {
      const t0 = performance.now();
      if (form === 'texElement2D/6' || form === 'texElementImage2D/6') {
        gl[name](gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, child);
      } else if (form === 'texElementImage2D/3') {
        gl.texElementImage2D(gl.TEXTURE_2D, gl.RGBA8, child);
      } else if (form === 'texElementSubImage2D/5') {
        gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA8, w, h);
        gl.texElementSubImage2D(gl.TEXTURE_2D, 0, 0, 0, child);
      } else {
        throw new Error('a form this test has not met: ' + form);
      }
      gl.finish();
      out.ms = performance.now() - t0;
    };
    if (painted) {
      await new Promise((resolve, reject) => {
        const late = setTimeout(() => reject(new Error('the canvas never fired paint')), 10000);
        canvas.addEventListener('paint', () => {
          clearTimeout(late);
          try { call(); resolve(); } catch (e) { reject(e); }
        }, { once: true });
        if (typeof canvas.requestPaint === 'function') canvas.requestPaint();
      });
    } else {
      await new Promise(res => requestAnimationFrame(() => requestAnimationFrame(res)));
      call();
    }
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    for (let i = 3; i < px.length; i += 4) if (px[i]) out.lit += 1;
    out.gl_error = gl.getError();
    const lose = gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  } catch (e) {
    out.error = (e && e.name ? e.name + ': ' : '') + String(e && e.message || e);
  } finally {
    canvas.remove();
  }
  return out;
}"""

#: (b) The SVG snapshot of a real pane: styles inlined on a clone (never on the pane), comment nodes
#: dropped (a comment holding `--` makes the XML invalid), serialised, decoded as a `data:` image --
#: which the desk's CSP allows (`img-src 'self' data:`) -- and uploaded to a WebGL2 texture.
SNAPSHOT = """async () => {
  const pane = document.querySelector('#grid .tile.is-solo');
  const r = pane.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
  const out = { w, h, error: '', lit: 0, comments: 0 };
  let t = performance.now();
  const clone = pane.cloneNode(true);
  const from = [pane, ...pane.querySelectorAll('*')], to = [clone, ...clone.querySelectorAll('*')];
  for (let i = 0; i < from.length; i++) {
    const cs = getComputedStyle(from[i]);
    for (let j = 0; j < cs.length; j++) {
      to[i].style.setProperty(cs[j], cs.getPropertyValue(cs[j]));
    }
  }
  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_COMMENT);
  const drop = [];
  while (walker.nextNode()) drop.push(walker.currentNode);
  drop.forEach(n => n.remove());
  out.comments = drop.length;
  out.styles_ms = performance.now() - t;
  t = performance.now();
  const xhtml = new XMLSerializer().serializeToString(clone);
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '">' +
              '<foreignObject width="100%" height="100%">' + xhtml + '</foreignObject></svg>';
  const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  out.bytes = svg.length;
  out.serialise_ms = performance.now() - t;
  t = performance.now();
  const img = new Image();
  img.src = url;
  try { await img.decode(); } catch (e) { out.error = 'decode: ' + String(e && e.message || e); return out; }
  out.decode_ms = performance.now() - t;
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const gl = canvas.getContext('webgl2');
  try {
    t = performance.now();
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.finish();
    out.upload_ms = performance.now() - t;
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    for (let i = 3; i < px.length; i += 4) if (px[i]) out.lit += 1;
  } catch (e) {
    out.error = (e && e.name ? e.name + ': ' : '') + String(e && e.message || e);
  } finally {
    const lose = gl && gl.getExtension('WEBGL_lose_context');
    if (lose) lose.loseContext();
  }
  return out;
}"""

#: (c) DOM-synced geometry: every line box in a pane from one `Range`, and every glyph box from one
#: `Range` per character. Read only; nothing on the page is touched.
GEOMETRY = """() => {
  const pane = document.querySelector('#grid .tile.is-solo');
  let t = performance.now();
  const range = document.createRange();
  range.selectNodeContents(pane);
  const lines = [...range.getClientRects()].filter(b => b.width > 0 && b.height > 0).length;
  const lines_ms = performance.now() - t;
  t = performance.now();
  const walker = document.createTreeWalker(pane, NodeFilter.SHOW_TEXT);
  const one = document.createRange();
  let glyphs = 0;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    for (let i = 0; i < node.length; i++) {
      one.setStart(node, i); one.setEnd(node, i + 1);
      const b = one.getBoundingClientRect();
      if (b.width > 0 && b.height > 0) glyphs += 1;
    }
  }
  return { lines, lines_ms, glyphs, glyphs_ms: performance.now() - t };
}"""


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide; each test gets a fresh fleet directory."""
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


def _ms(value) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


#: The HTML-in-canvas method this engine has, found the way probe.js finds it: the same names in the
#: same order, read off the prototype, `name/arity` or "".
HIC_OF_ENGINE = """() => {
  if (typeof WebGL2RenderingContext === 'undefined') return '';
  const proto = WebGL2RenderingContext.prototype;
  for (const n of ['texElementImage2D', 'texElementSubImage2D', 'texElement2D']) {
    if (typeof proto[n] === 'function') return n + '/' + proto[n].length;
  }
  return '';
}"""

#: A desk page is ready: three panes, each with its tier, the ink module run, nothing in flight.
DESK_READY = """() => document.querySelectorAll('#grid .tile.is-solo').length === 3
     && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
     && !!window.Ink && windowWrites === 0
     && !document.body.classList.contains('is-stale')"""


def _desk_page(browser, port, token):
    """A desk page in a context of its own, every getContext call watched from before its scripts
    run, and its page errors collected."""
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    context.add_init_script(WATCH_CONTEXTS)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
    page.wait_for_function(DESK_READY, timeout=15000)
    return context, page, errors


def _isolated_upload(browser, port, token, hic):
    """(a) in a context and page of its own, opened last, so that a renderer crash inside the
    flagged upload is that page's alone. The operator's ruling on #446: a crash there is the
    verdict, recorded and printed, not a red suite. Anything else this page raises still fails."""
    from playwright.sync_api import Error as PlaywrightError

    context, page, errors = _desk_page(browser, port, token)
    crashed = []
    page.on("crash", lambda _page: crashed.append(True))
    name, arity = hic.split("/")
    try:
        upload = page.evaluate(UPLOAD, [name, int(arity)])
    except PlaywrightError as e:
        if not crashed and "target crashed" not in str(e).lower():
            raise
        context.close()
        return {"name": name, "arity": int(arity), "crashed": True,
                "detail": str(e).splitlines()[0]}
    upload["crashed"] = False
    upload["asked"] = page.evaluate("() => window.__contexts")
    upload["left"] = page.evaluate("() => document.querySelectorAll('canvas').length")
    upload["errors"] = errors
    context.close()
    return upload


@pytest.mark.browser
def test_html_in_canvas_is_what_the_probe_recorded_and_the_other_routes_are_measured(fleet_home,
                                                                                    tmp_path):
    """The probe's `hic_api` is what the engine has, in a Chromium launched with the Blink flag.

    Found: the recorded method uploads a cloned pane from a `<canvas layoutsubtree>` in a page of its
    own. Either it reads back lit pixels with no `SecurityError`, or the renderer crashes, which the
    operator ruled is the measured verdict (#446): recorded and printed, and the page is the upload's
    alone. Not found: `hic_api` is empty and the row falls back. The SVG snapshot and the Range
    geometry are measured on the desk page beside it, and hold whatever the upload did."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, args=(HIC_FLAG,))
            version = browser.version

            # The probe page, as tests/test_fleet_engines.py opens it.
            probe = browser.new_page(viewport={"width": 1280, "height": 720})
            probe.goto(f"http://127.0.0.1:{port}/probe?t={token}&shell=chromium",
                       wait_until="domcontentloaded")
            probe.wait_for_function(
                "() => /saved|not saved/.test(document.getElementById('state').textContent)",
                timeout=30000)
            shown = probe.text_content("#features")
            probe.close()

            # (b) and (c) on the desk page, first, and closed before the upload's page opens.
            context, page, errors = _desk_page(browser, port, token)
            engine = page.evaluate(HIC_OF_ENGINE)
            snapshot = page.evaluate(SNAPSHOT)
            geometry = page.evaluate(GEOMETRY)
            left = page.evaluate("() => document.querySelectorAll('canvas').length")
            asked = page.evaluate("() => window.__contexts")
            context.close()

            rec = PR.attempts()["chromium"]
            hic = rec.get("hic_api", "")
            upload = _isolated_upload(browser, port, token, hic) if hic else None
            browser.close()
    finally:
        _stop(server)

    print(f"\n  Chromium {version}, launched with {HIC_FLAG}")
    print(f"  probe row     HTML-in-canvas: {PR.feature_cell(rec, 'HTML-in-canvas')}"
          f" (hic_api {hic!r}, the engine has {engine!r})")
    if upload is None:
        print("  (a) upload    none found: the row falls back, effects follow element rects "
              "and line boxes")
    elif upload["crashed"]:
        print(f"  (a) upload    {upload['name']}/{upload['arity']}: crashed (Chromium {version}, "
              f"SwiftShader): {upload['detail']}")
    else:
        print(f"  (a) upload    {upload['name']}/{upload['arity']} of a {upload['w']}x{upload['h']} "
              f"pane: {upload['lit']} lit pixels in {_ms(upload['ms'])} (after {upload['via']})"
              f"{', ' + upload['error'] if upload['error'] else ''}")
    print(f"  (b) snapshot  {snapshot['w']}x{snapshot['h']} pane, {snapshot.get('bytes', 0)} B of SVG, "
          f"{snapshot['comments']} comments dropped: styles {_ms(snapshot.get('styles_ms'))}, "
          f"serialise {_ms(snapshot.get('serialise_ms'))}, decode {_ms(snapshot.get('decode_ms'))}, "
          f"upload {_ms(snapshot.get('upload_ms'))}; {snapshot['lit']} lit pixels"
          f"{', ' + snapshot['error'] if snapshot['error'] else ''}")
    print(f"  (c) geometry  {geometry['lines']} line boxes in {_ms(geometry['lines_ms'])}; "
          f"{geometry['glyphs']} glyph boxes in {_ms(geometry['glyphs_ms'])}")

    assert errors == [], errors
    # The probe asked the prototype and recorded what it found; the engine agrees.
    assert hic == engine, (hic, engine)
    assert rec["features"]["HTML-in-canvas"] is bool(hic), (rec["features"], hic)
    if hic:
        assert "HTML-in-canvas" not in shown, shown
        if not upload["crashed"]:
            assert upload["errors"] == [], upload["errors"]
            assert upload["error"] == "", upload
            assert upload["lit"] > 0, f"{hic} uploaded nothing: {upload}"
            assert {a["kind"] for a in upload["asked"]} <= {"webgl2"}, upload["asked"]
            assert upload["left"] == 0, f"{upload['left']} canvas left on a desk that had none"
    else:
        assert PR.feature_cell(rec, "HTML-in-canvas") == PR.FEATURES["HTML-in-canvas"]
        assert f"HTML-in-canvas: {PR.FEATURES['HTML-in-canvas']}" in shown, shown
    # The SVG route works in this engine with no taint: the upload read back the pane.
    assert snapshot["error"] == "", snapshot
    assert snapshot["lit"] > 0, snapshot
    assert geometry["lines"] > 0 and geometry["glyphs"] > 0, geometry
    # No 2D context was asked for, by the desk or by the snapshot; the snapshot's canvas was never
    # on the page.
    assert {a["kind"] for a in asked} <= {"webgl2"}, asked
    assert left == 0, f"{left} canvas left on a desk that had none"
