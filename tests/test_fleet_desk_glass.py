"""Sitting: C — glass that is glass (issue #182).

The contrast test proves the numbers and `test_fleet_skins.py` proves the stylesheet carries them.
This proves the *material*: a screenshot of the page in each glass variant, decoded here, whose
panel pixels sit inside the declared `[darkest, lightest]` range and -- the thing a flat skin
cannot do -- vary across the page, because a translucent pane over a mesh is a different colour
wherever the mesh is and is not. `getComputedStyle` would only echo the `rgba()` back; the pixels
are what the operator sees.
"""
from __future__ import annotations
import struct
import threading
import zlib

import pytest

from agentdata import theme
from agentdata.fleet import registry, serve as S, skins as K
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


def _png_pixels(data: bytes):
    """A PNG as (width, height, bytes-per-pixel, rows). Enough of the format for a screenshot:
    8-bit RGB or RGBA, one IDAT stream, the five filters. No image library in the test venv."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h, ctype = 8, b"", 0, 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6), (depth, ctype)
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        f, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return w, h, bpp, rows


def _lum(rgb):
    return theme.rel_luminance(tuple(c / 255 for c in rgb)) * 255


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


TOLERANCE = 14      # in luminance, 0-255: the blur and the antialiasing at a pane's edge


@pytest.mark.browser
def test_the_pane_is_a_different_colour_wherever_the_mesh_is_and_stays_inside_the_range(fleet_home, tmp_path):
    """Acceptance criterion. Three tiles with empty transcripts -- a pane with nothing written on
    it -- sampled on a grid, in every glass variant. Every sample is inside the declared range
    (the contrast test's numbers bound what the operator actually sees), and the samples are not
    all one colour (the mesh shows through, which is the material)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    for name in ("alpha", "beta", "gamma"):
        Registry().add(make_project(tmp_path / name), name=name)       # no events: an empty pane

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            # The first poll tick sends a `polls` frame and the page redraws its tiles with their
            # cells (#184), which moves every transcript down a row. Sample after that, not
            # across it: a rect measured before the redraw and a screenshot taken after it would
            # put a sample on the ground between two tiles.
            page.wait_for_selector(".tile .cells .cell", timeout=15000)
            page.wait_for_timeout(400)

            for variant, spec in K.SKINS["glass"]["variants"].items():
                page.evaluate("(name) => post('theme', { skin: name })", f"glass:{variant}")
                page.wait_for_function(
                    "(v) => document.body.getAttribute('data-skin-variant') === v", arg=variant, timeout=5000)
                page.wait_for_timeout(500)
                assert "blur" in page.evaluate("() => getComputedStyle(document.querySelector('.tile')).backdropFilter"), \
                    f"glass:{variant} did not apply"

                # An empty transcript is a band, not a box -- the tile is content-sized -- so the
                # samples run along its midline, five per tile, fifteen across the page's width,
                # which is the axis the mesh varies most along.
                rects = page.eval_on_selector_all(".tile .transcript", """els => els.map(e => {
                    const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; })""")
                assert len(rects) == 3 and all(r["w"] > 100 and r["h"] >= 12 for r in rects), rects

                w, h, bpp, rows = _png_pixels(page.screenshot(type="png"))
                lo = tuple(int(c * 255) for c in theme.hex_to_rgb(spec["composited_panel"]["darkest"]))
                hi = tuple(int(c * 255) for c in theme.hex_to_rgb(spec["composited_panel"]["lightest"]))
                # The range is declared in luminance -- `composited_range` picks its darkest and
                # lightest by it, and `theme.check` measures contrast by it -- so it is compared in
                # luminance. Per channel it would be wrong: the gold blob composites to a colour
                # redder than the blue one that is lightest overall, and is inside the range.
                samples = []
                for r in rects:
                    for fx in (0.1, 0.3, 0.5, 0.7, 0.9):
                        x, y = int(r["x"] + r["w"] * fx), int(r["y"] + r["h"] * 0.5)
                        px = tuple(rows[y][x * bpp:x * bpp + 3])
                        samples.append(px)
                        assert _lum(lo) - TOLERANCE <= _lum(px) <= _lum(hi) + TOLERANCE, \
                            (f"glass:{variant}", (x, y), px, "outside", lo, hi)

                # The floor is relative to the variant's own range: Noir's near-white blobs at low
                # alpha declare a narrow range on purpose (a black room stays a black room), and a
                # flat number would either fail it or say nothing about Smoke. A quarter of the
                # declared spread, seen across three tiles, is the mesh showing through.
                lums = sorted(_lum(s) for s in samples)
                declared = _lum(hi) - _lum(lo)
                assert lums[-1] - lums[0] >= max(0.75, 0.25 * declared), \
                    (f"glass:{variant}", "the pane is one colour everywhere: that is paint, not glass",
                     lums[-1] - lums[0], declared)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_card_on_a_pane_is_a_layer_of_its_own(fleet_home, tmp_path):
    """Acceptance criterion. A card on a tile computes to a different background than the tile,
    and the tile to a different one than the ground -- the layers are measurable, not asserted by
    eye. And the chips stay solid."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    Registry().add(make_project(tmp_path / "alpha"), name="alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            for variant in K.SKINS["glass"]["variants"]:
                page.evaluate("(name) => post('theme', { skin: name })", f"glass:{variant}")
                page.wait_for_function(
                    "(v) => document.body.getAttribute('data-skin-variant') === v", arg=variant, timeout=5000)
                got = page.evaluate("""() => {
                    const g = s => getComputedStyle(document.querySelector(s));
                    return { ground: g('body').backgroundColor, tile: g('.tile').backgroundColor,
                             card: g('.tile .approval').backgroundColor, ask: g('.tile .asks').backgroundColor,
                             chip: g('.tile .chip').opacity };
                }""")
                assert got["card"] == got["ask"], (variant, got)
                assert len({got["ground"], got["tile"], got["card"]}) == 3, (variant, got)
                assert got["chip"] == "1", (variant, got)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
