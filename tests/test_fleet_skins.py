"""Tests for Desk on Windows skin tier (Issues #154, #155, #156, #157).

Contracts:
- list_skins() returns none, glass, voxel, farmstead with metadata and sizes.
- Size budget: each skin is under 150 KB.
- Pixel art rule: 100% original hand-authored vector SVG pixel art; zero rasters (<image>, base64, png, jpg).
- Composited panel check passes WCAG contrast floors for all skins.
- Deliberately broken composited panel is refused with a hint naming the skin.
- Fallbacks for prefers-reduced-transparency and prefers-reduced-motion are present.
"""
from __future__ import annotations

import os
import re
import pytest

from agentdata import theme
from agentdata.fleet import skins

SKINS_DIR = skins.SKINS_DIR


def test_list_skins_returns_all_skins_with_budgets():
    """list_skins() returns standard none plus glass, voxel, farmstead under 150 KB budget."""
    available = skins.list_skins()
    names = [s["name"] for s in available]
    assert names == ["none", "glass", "voxel", "farmstead"]

    for s in available:
        assert "title" in s and "why" in s and "base" in s
        if s["name"] != "none":
            assert s["size_bytes"] > 0, f"Skin {s['name']} stylesheet missing or empty"
            # 150 KB budget
            assert s["size_bytes"] < 150 * 1024, f"Skin {s['name']} exceeded 150 KB budget: {s['size_bytes']} bytes"


def test_zero_raster_bitmaps_in_skins():
    """Every skin asset is hand-authored vector/CSS; zero rasters (<image>, base64, png, jpg)."""
    assert os.path.isdir(SKINS_DIR)
    for root, _, files in os.walk(SKINS_DIR):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            assert ext in (".css", ".svg", ".txt", ".md", ""), f"Disallowed asset format in skin: {f}"
            full_path = os.path.join(root, f)
            content = open(full_path, "r", encoding="utf-8").read()
            # Assert no raster tags or encodings
            assert "<image" not in content, f"Raster <image> tag found in {f}"
            assert "base64" not in content, f"Base64 encoded bitmap found in {f}"
            assert not re.search(r'\.(png|jpg|jpeg|gif|webp)', content, re.IGNORECASE), f"Raster reference in {f}"


def test_all_svg_sprites_use_rect_pixel_art_with_named_comments():
    """All SVG sprites are hand-drawn with <rect> elements and named comments."""
    for skin_name in ("voxel", "farmstead"):
        svg_path = os.path.join(SKINS_DIR, skin_name, "sprites.svg")
        assert os.path.isfile(svg_path), f"Missing sprites.svg for {skin_name}"
        content = open(svg_path, "r", encoding="utf-8").read()
        assert "<rect" in content, f"No <rect> pixel art found in {svg_path}"
        assert "shape-rendering=\"crispEdges\"" in content or "shape-rendering='crispEdges'" in content
        # Check comments naming textures and states
        assert "<!--" in content and "-->" in content
        if skin_name == "voxel":
            assert "dirt tile" in content
            assert "stone tile" in content
            assert "status block" in content
        elif skin_name == "farmstead":
            assert "soil tile" in content
            assert "wood plank" in content
            assert "crop stage" in content


def test_composited_panel_check_passes_for_all_skins():
    """Each skin's composited panel passes text and status contrast on its base palette."""
    for skin_name, s in skins.SKINS.items():
        base_palette = theme.get(s["base"])
        composited = s["composited_panel"]
        theme.check(base_palette, composited_panel=composited, skin=skin_name)


def test_broken_composited_panel_refused_with_skin_hint():
    """A composited panel that drops text contrast below 4.5:1 is refused with a hint naming the skin."""
    glass = skins.get_skin("glass")
    base = theme.get(glass["base"])  # dark (#14171A, text #E3E7EA)
    # Using a panel too close in luminance to text drops contrast below 4.5:1
    with pytest.raises(theme.ThemeError) as exc_info:
        theme.check(base, composited_panel="#D0D5DA", skin="glass")
    
    assert "below 4.5:1 floor" in str(exc_info.value)
    assert "skin 'glass'" in exc_info.value.hint


def test_accessibility_fallbacks_present_in_skin_stylesheets():
    """Reduced transparency and reduced motion fallbacks are present in skin stylesheets."""
    glass_css = open(os.path.join(SKINS_DIR, "glass", "skin.css"), encoding="utf-8").read()
    assert "prefers-reduced-transparency: reduce" in glass_css
    assert "backdrop-filter: none" in glass_css

    farm_css = open(os.path.join(SKINS_DIR, "farmstead", "skin.css"), encoding="utf-8").read()
    assert "prefers-reduced-motion" in farm_css
    assert "animation: none" in farm_css


def test_every_skin_writes_the_accessibility_fallbacks_it_promised():
    """A source check, on purpose, and the docstring is the reason.

    Reduced MOTION is exercised in the browser. Reduced TRANSPARENCY cannot be: Chromium did not
    ship `prefers-reduced-transparency` until well after the build these tests drive, so the query
    never matches and the fallback never fires there -- and it will not fire in an older Edge or
    JCEF either. The behaviour is therefore unobservable on every engine we have, and the only
    honest thing left to assert is that the rule is written and points at elements that exist.
    `docs/themes.md` carries the limitation so nobody reads this test as proof it works.
    """
    base = open(os.path.join(os.path.dirname(SKINS_DIR), "app.css"), encoding="utf-8").read()
    assert "prefers-reduced-motion" in base, "the page itself must honour reduced motion"

    for name in ("glass", "voxel", "farmstead"):
        css = open(os.path.join(SKINS_DIR, name, "skin.css"), encoding="utf-8").read()
        # A skin that introduces movement has to be able to stop it. One that does not introduce
        # any is covered by the base stylesheet's global rule, and a per-skin block there would be
        # boilerplate asserting itself.
        if "animation:" in css or "@keyframes" in css or "transition:" in css:
            assert "prefers-reduced-motion" in css, f"{name} animates and never stops"
        assert ".sidebars" not in css and "aside#inspector" not in css, \
            f"{name} styles a sidebar that no longer exists"
    glass = open(os.path.join(SKINS_DIR, "glass", "skin.css"), encoding="utf-8").read()
    assert "prefers-reduced-transparency" in glass
    block = glass[glass.index("prefers-reduced-transparency"):]
    assert "#side" in block, "the opaque fallback must cover the sidebar too"
    assert "backdrop-filter: none" in block
