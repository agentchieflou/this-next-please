"""2026-09-23, the desk in Chromium: a skin's chip glyph was every sprite in its sheet at once.

Symptom (farmstead, and voxel the same, read back from the page):

    sprites.svg#crop-sprout  -> the seed, the sprout, the sun, the bloom and the wilt, over each other
    sprites.svg#running-block, #waiting-block, #human-block, #done-block
                             -> ['#25282B', '#8B949E', '#B1BAC4', '#F0F6FC'], the idle block, all four

Seen building farmstead on three.js (#255). The chips carry their state as
`url("sprites.svg#<sprite>")`, and every sprite in a sheet sits at 0,0 -- but nothing hid the ones
not named, and the sheet's root had no size. So the fragment chose nothing: the whole sheet was
drawn, squeezed into the glyph box, and on voxel the last block drawn (idle) covered the rest, so
every chip said idle whatever its word said. The sheets are stacks now: a root the size of a glyph,
the sprites hidden, and `:target` showing the one a fragment names.

Issue: https://github.com/agentchieflou/this-next-please/issues/255
"""
from __future__ import annotations

import os
import re

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _desk_of, _open, _serve, _stop, fleet_home, _own_desk_globals  # noqa: F401 - fixtures

SKINS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "agentdata", "fleet", "static", "skins")


def _named(skin, sheet):
    """The sprites a skin names: by fragment in its stylesheet, or -- since #257, where the crop is
    drawn by the skin's ink module and never by CSS -- by id in its module, which reads each one out
    of the same sheet."""
    css_path = os.path.join(SKINS_DIR, skin, "skin.css")
    names = set(re.findall(r'url\("sprites\.svg#([\w-]+)"\)', open(css_path, encoding="utf-8").read()))
    module = os.path.join(os.path.dirname(SKINS_DIR), "ink", "skins", skin + ".js")
    if os.path.isfile(module):
        js = open(module, encoding="utf-8").read()
        names |= {i for i in re.findall(r'<svg id="([\w-]+)"', sheet) if '"' + i + '"' in js}
    return sorted(names)


def _glyphs():
    """(skin, sprite, size, the sprite's own colours) for every sprite a skin names."""
    out = []
    for skin in sorted(os.listdir(SKINS_DIR)):
        css_path = os.path.join(SKINS_DIR, skin, "skin.css")
        sheet_path = os.path.join(SKINS_DIR, skin, "sprites.svg")
        if not (os.path.isfile(css_path) and os.path.isfile(sheet_path)):
            continue
        sheet = open(sheet_path, encoding="utf-8").read()
        for sprite in _named(skin, sheet):
            head, body = re.search(r'<svg id="%s"([^>]*)>(.*?)</svg>' % sprite, sheet, re.S).groups()
            size = int(re.search(r'width="(\d+)"', head).group(1))
            colours = sorted({c.upper() for c in re.findall(r'fill="(#[0-9A-Fa-f]{6})"', body)})
            out.append((skin, sprite, size, colours))
    return out


GLYPHS = _glyphs()


def test_every_skin_that_names_a_sprite_is_checked():
    # Voxel's sheet went with its CSS look (#257): its status is the stack its module builds.
    assert {g[0] for g in GLYPHS} >= {"farmstead"}, GLYPHS


@pytest.mark.browser
def test_a_chip_glyph_is_its_one_sprite(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token)
            drawn = page.evaluate("""async (glyphs) => {
              const read = async (skin, sprite, size) => {
                const img = new Image();
                img.src = q('/static/skins/' + skin + '/sprites.svg') + (sprite ? '#' + sprite : '');
                await img.decode();
                const c = document.createElement('canvas');
                c.width = c.height = size;
                const g = c.getContext('2d');
                g.imageSmoothingEnabled = false;
                g.drawImage(img, 0, 0, size, size);
                const d = g.getImageData(0, 0, size, size).data, seen = new Set();
                for (let i = 0; i < d.length; i += 4) {
                  if (d[i + 3]) seen.add('#' + [d[i], d[i + 1], d[i + 2]].map(v => v.toString(16)
                    .padStart(2, '0')).join('').toUpperCase() + (d[i + 3] < 255 ? '~' : ''));
                }
                return { colours: [...seen].sort(), size: [img.naturalWidth, img.naturalHeight] };
              };
              const out = {};
              for (const [skin, sprite, size] of glyphs) {
                out[skin + '#' + sprite] = await read(skin, sprite, size);
                out[skin + '#'] = await read(skin, '', size);
              }
              return out;
            }""", [[s, n, z] for s, n, z, _ in GLYPHS])
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    for skin, sprite, size, colours in GLYPHS:
        got = drawn[f"{skin}#{sprite}"]
        assert got["colours"] == colours, f"{skin}: sprites.svg#{sprite} drew {got['colours']}, not {colours}"
        assert got["size"] == [size, size], (skin, sprite, got["size"])
        assert drawn[f"{skin}#"]["colours"] == [], f"{skin}: the sheet with no fragment drew something"
