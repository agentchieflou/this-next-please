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
        assert "title" in s and "why" in s and "base" in s and "variants" in s
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


def test_every_skin_variant_passes_the_contrast_rule_on_its_own_ground():
    """The whole reachable combination set, checked -- not a sample of it (#4).

    Skins drive palettes, so a variant *is* a (skin, palette, composited panel) triple and the set
    of combinations the operator can reach is exactly the set of variants. That is what makes an
    exhaustive check possible at all: with the two pickers independent there were eleven palettes
    times four skins of pairings and nothing had measured most of them.

    The panel, not the palette's ground, is what the text is read on once the skin has painted its
    texture or its frost over it -- so that is what the ratio is taken against.
    """
    every = skins.every_variant()
    assert len(every) >= 10, "every skin has variants; this test is the reason they can be trusted"
    for skin_name, variant, spec in every:
        base_palette = theme.get(spec["base"])
        # One colour for a textured skin; both ends of the range for glass (#182), whose pane is
        # a different colour wherever the mesh behind it is and is not.
        panels = skins.composited_panels(spec)
        assert panels, f"{skin_name}:{variant} declares no composited panel"
        for panel in panels:
            theme.check(base_palette, composited_panel=panel, skin=f"{skin_name}:{variant}")


def test_glass_declares_the_range_its_own_mesh_composites_to():
    """The pair in `skins.py` is not typed in: it is what `composited_range` computes from the
    variant's own `mesh` and `fill`, and this is what stops the two from drifting apart."""
    glass = skins.SKINS["glass"]
    for variant, spec in glass["variants"].items():
        ground = theme.get(spec["base"]).ground
        assert isinstance(spec["composited_panel"], dict), variant
        darkest, lightest = skins.composited_range(ground, spec["mesh"], spec["fill"])
        assert (darkest, lightest) == (spec["composited_panel"]["darkest"], spec["composited_panel"]["lightest"]), \
            f"glass:{variant} declares a range its mesh does not composite to"
        assert theme.rel_luminance(theme.hex_to_rgb(darkest)) < theme.rel_luminance(theme.hex_to_rgb(lightest))


def _rgba(m):
    return ("#{:02X}{:02X}{:02X}".format(int(m[0]), int(m[1]), int(m[2])), round(float(m[3]), 2))


def test_the_glass_stylesheet_paints_the_numbers_skins_py_declares():
    """Acceptance criterion. The blobs and the fill in `skin.css` are the ones `skins.py` measured
    -- read back from the stylesheet, per variant, so declared and rendered are one number by
    construction rather than by somebody remembering to update both."""
    import re

    css = open(os.path.join(SKINS_DIR, "glass", "skin.css"), encoding="utf-8").read()
    for variant, spec in skins.SKINS["glass"]["variants"].items():
        block = re.search(r'body\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant, css, re.S)
        assert block, f"glass:{variant} is not drawn"
        body = block.group(1)
        blobs = [_rgba(m) for m in re.findall(
            r"radial-gradient\([^,]+,\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)\s*0%", body)]
        assert blobs == [(c, round(a, 2)) for c, a in spec["mesh"]], (variant, blobs, spec["mesh"])
        fill = re.search(r"--glass-fill:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", body)
        assert fill and _rgba(fill.groups()) == (spec["fill"][0], round(spec["fill"][1], 2)), (variant, spec["fill"])
        # A card on the pane is one step more opaque than the pane -- layer 2 is measurable.
        card = re.search(r"--glass-card:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", body)
        assert card and float(card.group(4)) > float(fill.group(4)), variant


def test_every_palette_on_its_own_passes_too():
    """A palette with no skin is the plain page, and it is read on the palette's own ground."""
    for t in theme.list_themes():
        theme.check(t)


def test_a_variant_names_a_palette_that_exists():
    """A variant whose base was renamed out from under it would fall back to an unthemed page
    silently, which is the failure `theme_or_none` was added to survive -- survivable is not the
    same as correct, so it is caught here instead."""
    known = {t.name for t in theme.list_themes()}
    for skin_name, variant, spec in skins.every_variant():
        assert spec["base"] in known, f"{skin_name}:{variant} names an unknown palette {spec['base']!r}"


def test_a_skins_default_variant_is_one_of_its_variants():
    for name, skin in skins.SKINS.items():
        assert skin["default"] in skin["variants"], name


def test_a_bare_skin_name_resolves_to_its_default_and_an_unknown_variant_does_not_raise():
    """The name comes from a hand-edited config file and from a URL. A renamed variant must not be
    able to take the dashboard down -- the same reasoning that put `theme_or_none` in front of
    `theme.get`."""
    assert skins.split("voxel") == ("voxel", "overworld")
    assert skins.split("voxel:nether") == ("voxel", "nether")
    assert skins.split("voxel:atlantis") == ("voxel", "overworld")
    assert skins.get_skin("voxel:atlantis")["variant"] == "overworld"
    assert skins.get_skin("nosuchskin") is None


def test_every_variant_is_actually_drawn_by_its_stylesheet():
    """A variant declared in Python and not written in CSS renders as the default one, and the
    operator gets the palette they chose with somebody else's texture on it."""
    for name, skin in skins.SKINS.items():
        css = open(os.path.join(SKINS_DIR, name, "skin.css"), encoding="utf-8").read()
        for variant in skin["variants"]:
            if variant == skin["default"]:
                continue                # the default is the stylesheet itself, with no attribute
            assert f'[data-skin-variant="{variant}"]' in css, f"{name}:{variant} is not drawn"


def test_broken_composited_panel_refused_with_skin_hint():
    """A composited panel that drops text contrast below 4.5:1 is refused with a hint naming the skin."""
    glass = skins.get_skin("glass")
    base = theme.get(glass["base"])  # smoke's base: dark (#14171A, text #E3E7EA)
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
