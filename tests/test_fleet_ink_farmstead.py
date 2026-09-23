"""Farmstead on three.js (#255, slice I of the ink epic #246): the sprite sheet as nearest-neighbour
textures at whole device pixels, lit wooden frames round every pane, and a crop that grows a stage
when the agent's phase advances. docs/skin-farmstead.md is the page this holds to.

CI draws in SwiftShader, which the probe calls `software`, so the tests that need the layer drawing
open the desk with `?ink=on` -- the override, never a measurement -- and choose the skin the way the
settings page does. What is read back is the canvas's own drawing buffer, copied in the task that
drew it: the ink's pixels, not a composited screenshot.

What is asserted:

* every variant is drawn by the ink layer with `?ink=on`, and drawn plain -- the stylesheet's own
  farm, and the same mark table as CSS -- under `body.ink-off`;
* the sprites are NearestFilter textures rasterised on the art's own grid, drawn at a whole number
  of device pixels: at a device pixel ratio of 2 every art pixel is a 2x2 (crop) or 4x4 (soil) block
  of one of the art's own colours, and nothing between two;
* each pane's frame follows a gutter drag, and its paper is the variant's composited panel;
* a crop grows exactly one stage when the phase advances, drawn up from the soil, never faded;
* the state grammar's marks and materials come and go with the classes `app.js` sets;
* `theme.check` holds every pair the skin puts behind text or on paper;
* the idle desk writes nothing and draws nothing; the ink settles in a bounded number of frames;
  and `dispose` frees the textures when the skin changes.
"""
from __future__ import annotations
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, skins, supervisor

from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import _gutter_point
from test_fleet_ink import (IDLE_LOOP, COUNT_FETCHES, _desk_of, _serve, _stop, catch_up_frames,  # noqa: F401
                            fleet_home, _own_desk_globals)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "farmstead.js")
SKIN_CSS = os.path.join(STATIC, "skins", "farmstead", "skin.css")
SPRITES = os.path.join(STATIC, "skins", "farmstead", "sprites.svg")
VARIANTS = tuple(skins.SKINS["farmstead"]["variants"])
#: The done row: the chip's own `done`, or the fold's (`is-done`, #253).
DONE = ".tile:is(.state-done, .is-done) .head"
#: The palette colour each tool is drawn in unless the skin names its own (`ink.js` TOOLS).
TOOL_TOKENS = {"pencil": "--muted", "pen": "--accent", "red": "--human", "green": "--done",
               "marker": "--human", "highlighter": "--waiting"}
#: The text the header and the footer carry, per variant: skin.css's own colours for them.
BAND_TEXT = {"daytime": ("#FFFDF5", "#F0DCC0"), "cave": ("#F0E9D8", "#CFC6AE"),
             "rainy": ("#E4EDFA", "#B9CBE4")}


def _read(path):
    return open(path, encoding="utf-8").read()


def _props(variant):
    """The `--farm-*` and `--ink-*` custom properties skin.css gives a variant: the base block,
    then the variant's own over it."""
    css = _read(SKIN_CSS)
    blocks = re.findall(r'body\[data-skin="farmstead"\]\s*\{(.*?)\}', css, re.S)
    blocks += re.findall(r'body\[data-skin="farmstead"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant,
                         css, re.S)
    out = {}
    for block in blocks:
        out.update(dict(re.findall(r"(--(?:farm|ink)-[\w-]+):\s*([^;]+);", block)))
    return out


def _table_tools():
    return sorted(set(re.findall(r'tool: "(\w+)"', _read(MODULE))))


# ------------------------------------------------------------------------ colour arithmetic

def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb(c):
    c = max(c, 0.0)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb(hexs):
    return [int(hexs[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def _lum(lin):
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _sprite(name):
    """A sprite's colours, from the sheet: [(hex, pixel count)], its fill first."""
    body = re.search(r'<svg id="%s"[^>]*>(.*?)</svg>' % name, _read(SPRITES), re.S).group(1)
    return re.findall(r'<rect[^>]*fill="(#[0-9A-Fa-f]{6})"', body)


def _band(variant, texel):
    """A plank texel as the band shader lights it: recoloured by the weather, times the sun and the
    band light, in linear light (farmstead.js FLAT_FRAG)."""
    p = _props(variant)
    c = [_lin(v) for v in _rgb(texel)]
    wood = p.get("--farm-wood")
    if wood:
        ref = _lum([_lin(v) for v in _rgb(_sprite("plank")[0])])
        c = [_lin(v) * _lum(c) / ref for v in _rgb(wood)]
    sun = [_lin(v) for v in _rgb(p["--farm-sun"])]
    light = float(p["--farm-band-light"])
    return "#%02X%02X%02X" % tuple(round(_srgb(ci * light * si) * 255) for ci, si in zip(c, sun))


# ============================================================================ without a browser


def test_the_module_carries_no_colour_of_its_own():
    """A palette colours the inks and a skin chooses the material (plan-ink): every colour the
    module draws comes from the art, the palette's tokens or skin.css, read at paint time."""
    body = _read(MODULE)
    assert not re.search(r"[\"'`]#[0-9A-Fa-f]{3,8}\b|\b0x[0-9A-Fa-f]{6}\b|\brgba?\(\s*\d", body), \
        "a colour written in farmstead.js"
    assert "NearestFilter" in body and "import(" not in body


def test_the_mark_table_names_only_what_the_page_already_sets():
    """Ground rule 2: marks come from classes the page sets -- never one the skin invents."""
    app = _read(os.path.join(STATIC, "app.js"))
    html = _read(os.path.join(STATIC, "index.html"))
    selectors = re.findall(r'selector: "((?:[^"\\]|\\.)*)"', _read(MODULE))
    assert len(selectors) == 7, selectors
    for sel in selectors:
        for cls in re.findall(r"\.([\w-]+)", sel):
            if cls.startswith("state-"):
                assert '"state-" + state' in app and cls[6:] in agentstate.STATES, (sel, cls)
            else:
                assert (f'"{cls}"' in app or f"'{cls}'" in app or f'class="{cls}' in html
                        or re.search(r'class="[^"]*\b%s\b' % re.escape(cls), html)
                        or f": 1, {cls}: 1" in app or f" {cls}: 1" in app), (sel, cls)
        for attr in re.findall(r"\[([\w-]+)", sel):
            assert attr in app or attr in html, (sel, attr)


def test_the_paper_is_each_variants_composited_panel_and_every_ink_passes_theme_check():
    """What the frames put behind the pane's text is `--farm-paper`, and that is the variant's
    `composited_panel` -- declared and drawn are one number -- so `theme.check` on it is the check
    of what the operator reads. Every ink the table draws with is a mark on that paper (3:1), and
    the text read through the highlighter keeps 4.5:1."""
    for variant in VARIANTS:
        spec = skins.SKINS["farmstead"]["variants"][variant]
        props = _props(variant)
        assert props["--farm-paper"].upper() == spec["composited_panel"].upper(), variant
        base = theme.get(spec["base"])
        palette = theme.to_css(base)
        inks = {tool: props.get("--ink-" + tool, palette[TOOL_TOKENS[tool]]) for tool in _table_tools()}
        theme.check(base, composited_panel=props["--farm-paper"], skin=f"farmstead:{variant}", inks=inks)


def test_the_header_and_footer_text_reads_on_every_lit_plank():
    """The bands are planks lit by the band light, and their text is skin.css's own colour -- so
    the pair is checked here: every texel of the plank, recoloured for the weather and lit as the
    shader lights it, keeps 4.5:1 under every colour the header and the footer are written in."""
    css = _read(SKIN_CSS).upper()
    for variant in VARIANTS:
        for text in BAND_TEXT[variant]:
            assert text in css, f"{text} is not a band colour of farmstead:{variant} any more"
            for texel in set(_sprite("plank")):
                lit = _band(variant, texel)
                ratio = theme.contrast_ratio(text, lit)
                assert ratio >= 4.5, f"farmstead:{variant}: {text} on plank {texel} lit to {lit} is {ratio:.2f}:1"


# ================================================================================ in a browser

#: The drawing buffer, copied in the task that drew it (`Ink.sample` draws a frame for the
#: purpose): device pixels of a CSS box, as [r, g, b] rows.
PIXELS = """(box) => {
  Ink.sample({ x: 0, y: 0, w: 1, h: 1 });
  const src = document.getElementById('ink');
  const dpr = src.width / innerWidth;
  const x = Math.round(box.x * dpr), y = Math.round(box.y * dpr);
  const w = Math.max(1, Math.round(box.w * dpr)), h = Math.max(1, Math.round(box.h * dpr));
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  g.drawImage(src, x, y, w, h, 0, 0, w, h);
  const d = g.getImageData(0, 0, w, h).data;
  const rows = [];
  for (let j = 0; j < h; j++) {
    const row = [];
    for (let i = 0; i < w; i++) { const k = (j * w + i) * 4; row.push([d[k], d[k + 1], d[k + 2]]); }
    rows.push(row);
  }
  return rows;
}"""

#: The skin's own account of what it has on the paper (`inspect` in farmstead.js).
FARM = "() => window.__farm ? window.__farm.inspect() : null"

LOAD_FARM = """async () => { window.__farm = await import(q('/static/ink/skins/farmstead.js')); }"""

#: At rest: the layer has nothing queued or lifting, the sheet has been drawn into its textures,
#: no crop is still growing, and every pane on the glass has its frame.
AT_REST = """() => { const l = Ink.inspect().layer; const f = window.__farm && window.__farm.inspect();
  if (!l || l.busy || Object.values(l.lanes).some(x => x.hand) || !f || !f.loaded) return false;
  const panes = document.querySelectorAll('#grid .tile[data-repo]').length;
  return l.skin && l.skin.frames === panes && Object.values(f.panes).every(p => !p.growing.length); }"""


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(rgb)


def _near(a, b, tol=2):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _page(browser, port, token, extra="&ink=on", *, panes=2, width=1400, height=900, dpr=1,
          reduced=False, count=False):
    """The desk, waited on until every pane has its width and the ink module has run."""
    page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=dpr,
                            reduced_motion="reduce" if reduced else "no-preference")
    if count:
        page.add_init_script(COUNT_FETCHES)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "farmstead" in m.text else None)
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile.is-solo').length === {panes}
             && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
             && !!window.Ink && windowWrites === 0
             && !document.body.classList.contains('is-stale')""", timeout=20000)
    return page, errors


def _farm_desk(fleet_home, tmp_path, names=("alpha", "beta"), skin="farmstead"):
    _desk_of(tmp_path, names)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


def _choose(page, skin):
    """As the settings page does: `POST /api/theme {skin}`, down the stream as `applySkin`."""
    page.evaluate("s => post('theme', { skin: s })", skin)


def _settle(page, also="true", timeout=30000):
    page.wait_for_function(f"() => ({AT_REST})() && ({also})", timeout=timeout)


def _inked(page, name, panes=2):
    """The farmstead table `name` in force, its module inspected, and the paper at rest."""
    page.wait_for_function(f"() => Ink.inspect().table === '{name}'", timeout=20000)
    page.evaluate(LOAD_FARM)
    _settle(page)
    return page.evaluate(FARM)


def _rect(page, repo):
    return page.evaluate(f"""() => {{ const r = document.querySelector('.tile[data-repo="{repo}"]')
      .getBoundingClientRect(); return {{ x: r.left, y: r.top, w: r.width, h: r.height }}; }}""")


def _paper(page):
    return page.evaluate("() => getComputedStyle(document.body).getPropertyValue('--farm-paper').trim()")


@pytest.mark.browser
def test_every_variant_is_drawn_in_ink_and_plain(fleet_home, tmp_path):
    """plan-ink: *a skin ships switched on only for shells measured as hardware; until then it is
    selectable and falls back.* With `?ink=on` every variant is the ink layer's -- ground, bands,
    a frame per pane, the pane's paper the variant's composited panel, the chip's glyph box left
    for the crop -- and with the gate off it is the stylesheet's farm, with the same marks drawn
    plain (the pencil ring round a stale session is a CSS outline)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for extra in ("&ink=on", ""):
                page, errors = _page(browser, port, token, extra)
                for variant in VARIANTS:
                    _choose(page, f"farmstead:{variant}")
                    name = f"farmstead:{variant}"
                    if extra:
                        farm = _inked(page, name)
                        alpha = _rect(page, "alpha")
                        mid = page.evaluate(PIXELS, {"x": alpha["x"] + alpha["w"] / 2, "y": alpha["y"] + alpha["h"] - 40,
                                                     "w": 1, "h": 1})[0][0]
                        head = page.evaluate(PIXELS, {"x": 300, "y": 10, "w": 1, "h": 1})[0][0]
                        seen[("ink", variant)] = {
                            "layer": page.evaluate("() => Ink.inspect().layer.skin"), "farm": farm,
                            "paper": _paper(page), "mid": _hex(mid), "head": head,
                            "look": page.evaluate("""() => { const t = document.querySelector('.tile[data-repo="alpha"]');
                              const chip = t.querySelector('.chip');
                              return { tile: getComputedStyle(t).backgroundColor,
                                       glyph: getComputedStyle(chip, '::before').backgroundImage,
                                       off: document.body.classList.contains('ink-off') }; }""")}
                    else:
                        page.wait_for_function(f"() => Ink.inspect().table === '{name}' && Ink.inspect().plain",
                                               timeout=20000)
                        page.wait_for_function("""() => getComputedStyle(document.querySelector(
                          '.tile[data-repo="alpha"] .oldsession')).outlineStyle === 'solid'""", timeout=20000)
                        seen[("plain", variant)] = page.evaluate("""() => { const t = document.querySelector('.tile[data-repo="alpha"]');
                          return { tile: getComputedStyle(t).backgroundColor,
                                   glyph: getComputedStyle(t.querySelector('.chip'), '::before').backgroundImage,
                                   canvas: !!document.getElementById('ink'), layer: Ink.inspect().layer,
                                   off: document.body.classList.contains('ink-off') }; }""")
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        _stop(server)
    for variant in VARIANTS:
        spec = skins.SKINS["farmstead"]["variants"][variant]
        on = seen[("ink", variant)]
        assert on["layer"]["hooks"] == ["ground", "paper", "frame", "tick", "dispose"], on
        assert on["layer"]["ground"] == 1 and on["layer"]["paper"] == 2 and on["layer"]["frames"] == 2, on
        assert on["layer"]["errors"] == [], on
        assert on["paper"].upper() == spec["composited_panel"].upper(), (variant, on["paper"])
        assert _near(_rgb_255(on["paper"]), _rgb_255(on["mid"])), (variant, on["paper"], on["mid"])
        assert on["head"] != list(_rgb_255(on["paper"])), "the header is laid with planks, not paper"
        assert set(on["farm"]["panes"]) == {"alpha", "beta"} and on["farm"]["loaded"], on["farm"]
        assert on["look"]["tile"] == "rgba(0, 0, 0, 0)" and on["look"]["glyph"] == "none", on["look"]
        assert not on["look"]["off"]
        off = seen[("plain", variant)]
        assert off["off"] and not off["canvas"] and off["layer"] is None, off
        assert off["tile"] != "rgba(0, 0, 0, 0)" and "sprites.svg" in off["glyph"], off


def _rgb_255(hexs):
    return tuple(int(hexs.strip()[i:i + 2], 16) for i in (1, 3, 5))


@pytest.mark.browser
def test_the_chip_glyph_is_one_sprite_of_the_sheet_and_not_all_of_them(fleet_home, tmp_path):
    """Under `body.ink-off` the chip carries its crop as `url("sprites.svg#crop-*")`. Every sprite in
    the sheet sits at 0,0, so a fragment that did not hide the others drew all seven on top of each
    other, squeezed into 16px. The sheet is a stack now: a fragment is that sprite alone, the
    sheet's own size, and no fragment is nothing. Read as the page reads it -- an image of the
    sheet by fragment, drawn at 16px."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, "")
            drawn = page.evaluate("""async (ids) => {
              const out = {};
              for (const id of ids) {
                const img = new Image();
                img.src = q('/static/skins/farmstead/sprites.svg') + (id ? '#' + id : '');
                await img.decode();
                const c = document.createElement('canvas');
                c.width = c.height = 16;
                const g = c.getContext('2d');
                g.imageSmoothingEnabled = false;
                g.drawImage(img, 0, 0, 16, 16);
                const d = g.getImageData(0, 0, 16, 16).data, seen = new Set();
                for (let i = 0; i < d.length; i += 4) {
                  if (d[i + 3]) seen.add('#' + [d[i], d[i + 1], d[i + 2]].map(v => v.toString(16)
                    .padStart(2, '0')).join('').toUpperCase() + (d[i + 3] < 255 ? '~' : ''));
                }
                out[id || 'none'] = [...seen].sort();
                out[(id || 'none') + ':size'] = [img.naturalWidth, img.naturalHeight];
              }
              return out;
            }""", ["crop-seed", "crop-sprout", "crop-sun", "crop-bloom", "crop-wilted", ""])
            glyph = page.evaluate("""() => getComputedStyle(document.querySelector(
              '.tile[data-repo="alpha"] .chip'), '::before').backgroundImage""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert re.search(r"sprites\.svg(\?[^#\"]*)?#crop-seed", glyph), glyph
    for sprite in ("crop-seed", "crop-sprout", "crop-sun", "crop-bloom", "crop-wilted"):
        assert drawn[sprite] == sorted({c.upper() for c in _sprite(sprite)}), (sprite, drawn[sprite])
        assert drawn[sprite + ":size"] == [16, 16], drawn[sprite + ":size"]
    assert drawn["none"] == [], "the sheet with no fragment draws nothing"


@pytest.mark.browser
def test_the_sprites_are_nearest_neighbour_textures_at_a_whole_number_of_device_pixels(fleet_home, tmp_path):
    """The art is rasterised on its own grid -- one texel per art pixel -- and every enlargement is
    NearestFilter's at a whole number of DEVICE pixels. At a device pixel ratio of 2 an art pixel of
    the crop is a 2x2 block and one of the soil a 4x4 block, each block one colour, and every colour
    one the sheet has (or the paper round the crop): crisp, never a blend of two texels."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, dpr=2)
            farm = _inked(page, "farmstead:daytime")
            crop = farm["panes"]["alpha"]["crop"]
            crop_px = page.evaluate(PIXELS, {"x": crop["x"], "y": crop["y"], "w": crop["size"], "h": crop["size"]})
            paper = _paper(page)
            # The soil, on its own: the skin's ground and nothing over it, for a block that is soil
            # wherever the desk's own layout puts the panes.
            page.evaluate("""async () => { const m = window.__farm;
              await Ink.setSkin({ name: 'soil', marks: [] }, { ground: m.ground, dispose: m.dispose }); }""")
            page.wait_for_function("() => window.__farm.inspect().loaded && !Ink.inspect().layer.busy", timeout=20000)
            soil_px = page.evaluate(PIXELS, {"x": 16, "y": 200, "w": 32, "h": 16})
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert farm["nearest"] and farm["raster"] == 1, farm
    assert farm["sizes"]["plank"] == [16, 8] and all(farm["sizes"][c] == [16, 16] for c in
                                                     ("soil", "crop-seed", "crop-bloom")), farm["sizes"]
    assert farm["units"] == {"soil": 2, "board": 1, "crop": 1, "dpr": 2}, farm["units"]
    assert crop["size"] == 16 and len(crop_px) == 32 and len(crop_px[0]) == 32, crop

    def blocks(px, n):
        for j in range(0, len(px) - n + 1, n):
            for i in range(0, len(px[0]) - n + 1, n):
                cell = {tuple(px[j + b][i + a]) for b in range(n) for a in range(n)}
                assert len(cell) == 1, f"a {n}x{n} art pixel at ({i}, {j}) is blended: {cell}"
    blocks(crop_px, 2)
    allowed = {_rgb_255(c) for c in _sprite("crop-seed")} | {_rgb_255(paper)}
    got = {tuple(c) for row in crop_px for c in row}
    assert all(any(_near(c, a, 1) for a in allowed) for c in got), (got, allowed)
    assert len(got) >= 3, "the seed is drawn: its own colours and the paper round it"
    # The soil: 4x4 blocks from the viewport's top-left, recoloured by nothing (daylight) and lit by
    # the sun -- so a handful of colours, each a whole block.
    blocks(soil_px, 4)
    assert 2 <= len({tuple(c) for row in soil_px for c in row}) <= len(set(_sprite("soil")))


@pytest.mark.browser
def test_each_frame_follows_a_gutter_drag(fleet_home, tmp_path):
    """A frame is built at its pane's size and moves with it; a gutter drag changes the size, and
    the frame is built again in the frame the browser laid out -- so at rest every pane's frame is
    the pane, the right-hand board is where the pane now ends, and paper fills what it grew into."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path, ("alpha", "beta", "gamma"))
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, panes=3)
            _inked(page, "farmstead:daytime", panes=3)
            before = _rect(page, "alpha")
            mid_y = before["y"] + before["h"] / 2
            board_before = page.evaluate(PIXELS, {"x": before["x"] + before["w"] + 1, "y": mid_y, "w": 1, "h": 1})[0][0]
            x, y = _gutter_point(page, "alpha")
            page.mouse.move(x, y)
            page.mouse.down()
            page.wait_for_function("() => !!gutterHeld", timeout=8000)
            page.mouse.move(x + 120, y, steps=24)
            page.mouse.up()
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            _settle(page, f"""(() => {{ const r = document.querySelector('.tile[data-repo="alpha"]').getBoundingClientRect();
              const f = window.__farm.inspect().panes.alpha.box; return r.width > {before['w'] + 60}
                && Math.abs(f.w - r.width) < 0.5 && Math.abs(f.h - r.height) < 0.5; }})()""")
            after = _rect(page, "alpha")
            farm = page.evaluate(FARM)
            board_after = page.evaluate(PIXELS, {"x": after["x"] + after["w"] + 1, "y": mid_y, "w": 1, "h": 1})[0][0]
            grown = page.evaluate(PIXELS, {"x": before["x"] + before["w"] + 1, "y": mid_y, "w": 1, "h": 1})[0][0]
            paper = _paper(page)
            layer = page.evaluate("() => Ink.inspect().layer.skin")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert after["w"] > before["w"] + 60, (before, after)
    for repo, pane in farm["panes"].items():
        assert pane["frame"]["w"] > pane["box"]["w"] and pane["frame"]["thick"] == 8, (repo, pane)
    assert abs(farm["panes"]["alpha"]["box"]["w"] - after["w"]) < 0.5, (farm["panes"]["alpha"], after)
    assert layer["frames"] == 3 and layer["errors"] == [], layer
    assert board_after == board_before, "the right-hand board is where the pane now ends, lit the same"
    assert _near(grown, _rgb_255(paper)), f"paper fills what the pane grew into, not {grown}"
    assert board_before != list(_rgb_255(paper))


def _force(monkeypatch):
    """What the fold says, decided by the test: `live` agents are supervised (a process and a pid),
    and `state` overrides the fold's state for a repo. The page is not touched -- it draws the
    classes `app.js` sets from what the server sends, as it always does."""
    forced = {"live": set(), "state": {}}
    real_status, real_derive = supervisor.status, agentstate.derive

    def status(*a, **k):
        rows = real_status(*a, **k)
        for row in rows:
            if row["repo"] in forced["live"]:
                row["pid"] = os.getpid()
        return rows

    def derive(events, *a, **k):
        out = real_derive(events, *a, **k)
        repo = next((ev.get("repo") for ev in events or [] if ev.get("repo")), "")
        if repo in forced["state"]:
            out = dict(out, state=forced["state"][repo])
        return out

    monkeypatch.setattr(supervisor, "status", status)
    # `live` answers the lock of a running process, or `{}` -- the shape every caller reads.
    monkeypatch.setattr(supervisor, "live", lambda name, *a, **k: (
        {"pid": os.getpid(), "ticket": "RDSD-1"} if name in forced["live"] else {}))
    monkeypatch.setattr(agentstate, "derive", derive)
    return forced


def _state(page, repo, cls, timeout=30000):
    """Wait for the PAGE to set `cls` on a pane, from what the server now says. Asked for again
    until it does: a `refresh()` joins one already in flight, and that one may have left before
    the server's answer changed -- on a slow Windows runner, often enough to fail a run."""
    import time
    deadline = time.monotonic() + timeout / 1000
    has = f"""() => document.querySelector('.tile[data-repo="{repo}"]').classList.contains('{cls}')"""
    while True:
        page.evaluate("async () => { await refresh(); }")
        try:
            page.wait_for_function(has, timeout=2000)
            return
        except Exception:                                   # noqa: BLE001 - asked again below
            assert time.monotonic() < deadline, f"{repo} never became {cls}"


#: Every frame from now until the paper is at rest: the crop's rows as the skin reports them.
GROWTH = """async (repo) => {
  const out = [];
  for (let i = 0; i < 600; i++) {
    await new Promise(r => requestAnimationFrame(r));
    const f = window.__farm.inspect().panes[repo];
    out.push({ frames: Ink.inspect().layer.frames, shown: f.shown, growing: f.growing, rows: f.rows,
               grows: f.grows, stage: f.stage });
    if (i > 4 && !f.growing.length && !Ink.inspect().layer.busy) break;
  }
  return out;
}"""


@pytest.mark.browser
@pytest.mark.parametrize("reduced", [False, True], ids=["drawn", "reduced-motion"])
def test_a_crop_grows_exactly_one_stage_when_the_phase_advances(fleet_home, tmp_path, monkeypatch, reduced):
    """The phase's DOM signal is the tile's `state-*`, which the fold derives from the phase and the
    turn. An idle agent's seed becomes a sprout when a turn begins, and the sprout a bloom when the
    phase reaches done: one stage each, drawn up from the soil a row at a time over the stage
    before, never cross-faded. Under reduced motion the stage is simply there."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    forced = _force(monkeypatch)
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, reduced=reduced)
            farm = _inked(page, "farmstead:daytime")
            start = farm["panes"]["alpha"]
            forced["live"].add("alpha")
            _state(page, "alpha", "state-running")
            to_sprout = page.evaluate(GROWTH, "alpha")
            _settle(page)
            forced["state"]["alpha"] = "done"
            _state(page, "alpha", "state-done")
            to_bloom = page.evaluate(GROWTH, "alpha")
            _settle(page)
            end = page.evaluate(FARM)["panes"]
            crop = end["alpha"]["crop"]
            px = page.evaluate(PIXELS, {"x": crop["x"], "y": crop["y"], "w": crop["size"], "h": crop["size"]})
            paper = _paper(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert start["shown"] == "crop-seed" and start["stage"] == 0 and start["grows"] == 0, start
    for steps, stage, sprite in ((to_sprout, 1, "crop-sprout"), (to_bloom, 2, "crop-bloom")):
        assert steps[-1]["shown"] == sprite and steps[-1]["stage"] == stage, steps[-1]
        assert steps[-1]["grows"] == stage, f"grew {steps[-1]['grows']} stages, not {stage}"
        rows = [s["rows"] for s in steps if s["growing"]]
        if reduced:
            assert rows == [], f"reduced motion drew the stage over frames: {rows}"
        else:
            assert rows == sorted(rows) and all(0 <= r < 16 for r in rows), rows
    assert end["beta"]["grows"] == 0 and end["beta"]["shown"] == "crop-seed", end["beta"]
    allowed = {_rgb_255(c) for c in _sprite("crop-bloom")} | {_rgb_255(paper)}
    got = {tuple(c) for row in px for c in row}
    assert all(any(_near(c, a, 1) for a in allowed) for c in got), (got, allowed)


@pytest.mark.browser
def test_a_finished_agent_blooms_from_the_folds_own_word(fleet_home, tmp_path):
    """The fold calls an agent done only once nothing supervises it, and the chip draws every quiet
    unsupervised agent as idle -- so the page says it finished with `is-done` (#253). Farmstead
    reads that: a phase reaching done ticks the head in green and grows the seed to a bloom,
    through the sprout, from the fold's own events and nothing forced."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token)
            _inked(page, "farmstead:daytime")
            E.append("beta", [E.event("beta", "phase_changed", {"from": "querying", "to": "done"},
                                      ticket="RDSD-1")])
            _state(page, "beta", "is-done")
            chip = page.evaluate("""() => document.querySelector('.tile[data-repo="beta"]').className""")
            _settle(page, f"Ink.inspect().layer.marks.some(m => m.selector === '{DONE}' && m.drawn === 1)")
            marks = page.evaluate("() => Ink.inspect().layer.marks")
            farm = page.evaluate(FARM)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert "state-idle" in chip.split(), f"the chip still says idle: {chip}"
    ticks = [m for m in marks if m["selector"] == DONE and not m["strikeOf"]]
    assert [m["lane"] for m in ticks] == ["pane:beta"] and ticks[0]["tool"] == "green", ticks
    beta = farm["panes"]["beta"]
    assert beta["shown"] == "crop-bloom" and beta["stage"] == 2 and beta["grows"] == 2, beta
    assert farm["panes"]["alpha"]["shown"] == "crop-seed", farm["panes"]["alpha"]


@pytest.mark.browser
def test_each_state_draws_its_mark_or_material_and_takes_it_away(fleet_home, tmp_path, monkeypatch):
    """The grammar (docs/skin-farmstead.md), every row from the fold's own events: an agent that was
    refused a tool needs you (its name highlighted, its crop wilted); one that asked a question and
    had a choice picked is answered (the choice circled); a friction line is a finding (ringed in
    red); an error boxes the head in marker, wilts the crop and scorches the frame; a live turn is
    running (the name underlined, a sprout); done is ticked. A new run takes them away -- ink
    struck, never faded -- and the crop is replanted."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    forced = _force(monkeypatch)
    _farm_desk(fleet_home, tmp_path, ("alpha", "beta", "gamma"))
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, panes=3, width=1600)
            _inked(page, "farmstead:daytime", panes=3)
            E.append("alpha", [E.event("alpha", "error", {"exit_code": 2}, ticket="RDSD-1")])
            E.append("beta", [E.event("beta", "friction", {"severity": "nit", "file": "notes.md"}, ticket="RDSD-1"),
                              E.event("beta", "question_opened", {"id": "q1", "question": "Which way?",
                                                                  "choices": ["left", "right"]}, ticket="RDSD-1")])
            forced["live"].add("gamma")
            _state(page, "alpha", "state-error")
            _state(page, "beta", "needs-human")
            _state(page, "gamma", "state-running")
            page.wait_for_selector('.tile[data-repo="beta"] .transcript li.friction', timeout=20000)
            choice = '.tile[data-repo="beta"] .asks:not([hidden]) .ask-choice'
            page.wait_for_selector(choice, timeout=20000)
            page.wait_for_function("() => windowWrites === 0 && !document.body.classList.contains('is-stale')",
                                   timeout=20000)
            page.locator(choice).first.click()
            page.wait_for_selector(choice + '[aria-pressed="true"]', timeout=20000)
            _settle(page, """Ink.inspect().layer.marks.filter(m => !m.strikeOf && m.state === 'drawn').length >= 8
                             && Ink.inspect().layer.marks.some(m => m.selector.includes('ask-choice') && m.drawn === 1)""")
            on = {"marks": page.evaluate("() => Ink.inspect().layer.marks"), "farm": page.evaluate(FARM)}
            # Done: the fold says so for a supervised agent.
            forced["state"]["gamma"] = "done"
            _state(page, "gamma", "state-done")
            _settle(page, "Ink.inspect().layer.marks.some(m => m.selector === '.tile:is(.state-done, .is-done) .head' && m.drawn === 1)")
            done = {"marks": page.evaluate("() => Ink.inspect().layer.marks"), "farm": page.evaluate(FARM)}
            # A new run for every one of them: nothing outstanding.
            forced["live"].clear()
            forced["state"].clear()
            for repo in ("alpha", "beta", "gamma"):
                E.append(repo, [E.event(repo, "started", {"pid": 1}, ticket="RDSD-1")])
            for repo in ("alpha", "beta", "gamma"):
                _state(page, repo, "state-idle")
            page.wait_for_function("""() => !document.querySelector('.tile.needs-human')""", timeout=20000)
            _settle(page, """Ink.inspect().layer.marks.filter(m => !m.strikeOf && m.state === 'drawn'
                             && !m.selector.includes('oldsession') && !m.selector.includes('friction')).length === 0""")
            off = {"marks": page.evaluate("() => Ink.inspect().layer.marks"), "farm": page.evaluate(FARM)}
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    def live(snapshot, lane, selector):
        return [m for m in snapshot["marks"] if m["lane"] == "pane:" + lane and m["selector"] == selector
                and not m["strikeOf"] and m["state"] == "drawn"]
    assert live(on, "beta", ".tile.needs-human .head .repo")[0]["tool"] == "highlighter"
    assert live(on, "beta", '.tile .asks:not([hidden]) .ask-choice[aria-pressed="true"]')[0]["shape"] == "loop"
    assert live(on, "beta", ".tile .transcript li.friction")[0]["tool"] == "red"
    assert live(on, "alpha", ".tile.state-error .head")[0]["tool"] == "marker"
    assert live(on, "gamma", ".tile.state-running .head .repo")[0]["tool"] == "pen"
    panes = on["farm"]["panes"]
    assert panes["alpha"]["shown"] == "crop-wilted" and panes["alpha"]["scorched"], panes["alpha"]
    assert panes["beta"]["shown"] == "crop-wilted" and not panes["beta"]["scorched"], panes["beta"]
    assert panes["gamma"]["shown"] == "crop-sprout" and panes["gamma"]["grows"] == 1, panes["gamma"]
    assert live(done, "gamma", ".tile:is(.state-done, .is-done) .head")[0]["tool"] == "green"
    assert done["farm"]["panes"]["gamma"]["shown"] == "crop-bloom", done["farm"]["panes"]["gamma"]
    # Gone: ink is struck (a strike is a mark of its own), and nothing is simply removed. The
    # friction line is history and stays in the transcript, so its ring stays with it.
    struck = {m["strikeOf"] for m in off["marks"] if m["strikeOf"]}
    for m in on["marks"] + done["marks"]:
        if m["strikeOf"] or "oldsession" in m["selector"] or "friction" in m["selector"]:
            continue
        if m["selector"] == ".tile.state-running .head .repo" and m in done["marks"]:
            continue
        assert m["id"] in struck, f"{m['selector']} in {m['lane']} left without being struck"
    for repo in ("alpha", "beta", "gamma"):
        pane = off["farm"]["panes"][repo]
        assert pane["shown"] == "crop-seed" and not pane["scorched"], (repo, pane)


@pytest.mark.browser
def test_the_farm_settles_in_a_bounded_number_of_frames(fleet_home, tmp_path, monkeypatch):
    """Ground rule 5, counted in frames: from the class changing to the paper at rest is the marks'
    own catch-up (the layer's bound) plus at most sixteen frames of a crop growing -- whatever the
    frame rate, because a slow frame grows it further."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    forced = _force(monkeypatch)
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token)
            _inked(page, "farmstead:daytime")
            first = page.evaluate("() => Ink.inspect().layer.frames")
            forced["live"].add("alpha")
            _state(page, "alpha", "state-running")
            steps = page.evaluate(GROWTH, "alpha")
            _settle(page)
            last = page.evaluate("() => Ink.inspect().layer")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    drawn = [m for m in last["marks"] if m["selector"] == ".tile.state-running .head .repo"]
    assert drawn and drawn[0]["drawn"] == 1, last["marks"]
    frames = last["frames"] - first
    bound = catch_up_frames([[m["id"], m["lane"], 1, m["selector"], m["len"], m["strokes"]] for m in drawn]) + 16
    print(f"\n  farmstead settled in {frames} frames (bound {bound})")
    assert steps[-1]["shown"] == "crop-sprout"
    assert frames <= bound, (frames, bound)


@pytest.mark.browser
def test_an_idle_farm_writes_nothing_and_draws_nothing(fleet_home, tmp_path):
    """desk-ink §Budgets: an idle desk with ink on it is zero DOM mutations and zero WebGL frames --
    the frames, the crops and the bands included."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token, count=True)
            _inked(page, "farmstead:daytime")
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle farm wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle farm drew {count['renders']} frames"


@pytest.mark.browser
def test_dispose_frees_the_textures_when_the_skin_changes(fleet_home, tmp_path):
    """The layer frees what is in the scenes it handed out; the sprite textures are the skin's, and
    `dispose` frees them -- when the weather changes (the next one loads its own) and when the skin
    goes. The renderer's own count of textures says they are gone from the GPU."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _farm_desk(fleet_home, tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _page(browser, port, token)
            day = _inked(page, "farmstead:daytime")
            _choose(page, "farmstead:rainy")
            rainy = _inked(page, "farmstead:rainy")
            _choose(page, "none")
            page.wait_for_function("() => Ink.inspect().table === null", timeout=20000)
            gone = page.evaluate(FARM)
            _choose(page, "glass")
            page.wait_for_function("() => document.body.dataset.skin === 'glass'", timeout=20000)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert day["textures"] == 7 and day["freed"] == 0, day
    assert rainy["textures"] == 7 and rainy["made"] == 14 and rainy["freed"] == 7, rainy
    assert gone["textures"] == 0 and gone["freed"] == gone["made"] == 14, gone
    assert gone["panes"] == {} and gone["bands"] == [], gone
    # The GPU holds a texture once it has been drawn with: the soil, the plank and the seed.
    assert gone["gpuTextures"] <= rainy["gpuTextures"] - 3, (rainy["gpuTextures"], gone["gpuTextures"])
