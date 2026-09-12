"""Skins for the Desk, and the palettes each one is drawn against (#154-#157, #4).

A skin is one more stylesheet over the same DOM: the approved grid with CSS and hand-drawn SVG
swapped in. A skin that needs a page change is not a skin.

**Skins drive palettes, not the other way round.** Every skin has variants and every variant names
the palette it is drawn against; no palette has to know that any skin exists. That asymmetry is the
whole model: a texture is designed for a ground, so `voxel`'s nether is red because the art is red,
and the palette follows. The operator picks one thing -- "Voxel · Nether" -- and the ground, the
chips, the terminal beside it and the composited panel all move together. Picking a skin and a
palette separately is how you get frosted glass designed for a dark ground rendered on a light one,
which is unreadable rather than merely wrong.

A palette on its own is still a palette: choosing one with no skin is the plain HIG page, which is
why `list_skins()` leads with `none`.

**Every variant is checked, not eyeballed.** `theme.check` is run against each variant's base
palette *through its composited panel* -- the colour the panel actually resolves to once the skin's
translucency and texture are painted, which is not the palette's own ground. A variant whose text
falls under 4.5:1 there is refused by the test suite, so the failure is a red build rather than a
dashboard somebody cannot read.

Glass is the one skin whose panel is not one colour (#182): a translucent fill over a mesh of
coloured blobs composites to something different wherever the blobs are and are not. So a glass
variant declares its `mesh` (the blobs, colour and peak alpha) and its `fill`, and its
`composited_panel` is a **pair** -- the darkest and the lightest colour the fill can resolve to
over that mesh -- computed by `composited_range` and checked at both ends. A string still means
"both ends are this", which is what every other skin's panel is.

Contract:
- `theme.skin` in `~/.agentdata/config.json`, `'none'` by default, spelled `<skin>` or
  `<skin>:<variant>`. A bare skin name means its default variant.
- No rasters: 100% original hand-authored vector SVG pixel art.
- Fallbacks: `prefers-reduced-transparency`, and `prefers-reduced-motion` for any skin that moves.
"""
from __future__ import annotations
import os

SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "skins")

# Each variant is (base palette, composited panel). The panel is what the text is actually read on
# once the skin has painted its texture over the palette's ground, so it -- and not the ground -- is
# what the contrast rule is applied to. `tests/test_fleet_skins.py` runs every one of these.
SKINS = {
    "glass": {
        "name": "glass",
        "title": "Glass",
        "why": "frosted acrylic translucent panels with a subtle accent glow",
        "default": "smoke",
        "variants": {
            "smoke": {"title": "Smoke", "base": "dark",
                      "mesh": [("#58A6FF", 0.35), ("#3FB950", 0.35), ("#D29922", 0.30)],
                      "fill": ("#1F2836", 0.36),
                      "composited_panel": {"darkest": "#181D24", "lightest": "#273D57"},
                      "why": "neutral graphite behind the frost"},
            "azure": {"title": "Azure", "base": "blues",
                      "mesh": [("#4DA3FF", 0.30), ("#5EE1E6", 0.25), ("#3FB950", 0.30)],
                      "fill": ("#1A2A48", 0.40),
                      "composited_panel": {"darkest": "#11213B", "lightest": "#1D3F56"},
                      "why": "cold blue depth, the darkest of the three"},
            "noir": {"title": "Noir", "base": "vanta-black",
                      "mesh": [("#E6E6E6", 0.16), ("#58A6FF", 0.18), ("#9A9A9A", 0.12)],
                      "fill": ("#1A1A1A", 0.40),
                      "composited_panel": {"darkest": "#0A0A0A", "lightest": "#202020"},
                      "why": "near-black, for a room with the lights off"},
            "frost": {"title": "Frost", "base": "eye-relief-day",
                      "mesh": [("#8A6D1F", 0.30), ("#2A5F9E", 0.25), ("#2A733E", 0.25)],
                      "fill": ("#F4EEE0", 0.34),
                      "composited_panel": {"darkest": "#DED4B8", "lightest": "#F3EDDD"},
                      "why": "the light one: warm paper under the same frost"},
        },
    },
    "voxel": {
        "name": "voxel",
        "title": "Voxel",
        "why": "chunky bevelled slab controls and pixel status blocks inspired by voxel worlds",
        "default": "overworld",
        "variants": {
            "overworld": {"title": "Overworld", "base": "matrix", "composited_panel": "#1E221E",
                          "why": "grass, stone and daylight"},
            "nether": {"title": "Nether", "base": "reds", "composited_panel": "#2A1512",
                       "why": "netherrack and firelight"},
            "end": {"title": "The End", "base": "vanta-black", "composited_panel": "#16121C",
                    "why": "endstone and void"},
        },
    },
    "farmstead": {
        "name": "farmstead",
        "title": "Farmstead",
        "why": "warm paper, wood trim and rustic crop-stage markers inspired by pixel farming",
        "default": "daytime",
        "variants": {
            "daytime": {"title": "Daytime", "base": "sand", "composited_panel": "#E8DDC3",
                        "why": "sunlight on paper and wood"},
            "cave": {"title": "Cave", "base": "eye-relief", "composited_panel": "#33302A",
                     "why": "lamplight underground"},
            "rainy": {"title": "Rainy day", "base": "blues", "composited_panel": "#16243D",
                      "why": "a wet afternoon indoors"},
        },
    },
}


def _over(top: tuple, alpha: float, under: tuple) -> tuple:
    """`top` at `alpha` painted over an opaque `under`, in linear 0-1 rgb."""
    return tuple(t * alpha + u * (1 - alpha) for t, u in zip(top, under))


def composited_range(ground: str, mesh: list, fill: tuple) -> tuple[str, str]:
    """The darkest and lightest colour a translucent `fill` composites to over `ground` + `mesh`.

    A blob is a radial gradient at its peak alpha in the centre and nothing at its edge, and the
    stylesheet never puts two centres in one place -- so a point on the page sees at most one blob
    near its peak and a neighbour at its tail. The model is that: each blob alone at full alpha,
    and each pair at half. It is a bound the rendered page is then measured against
    (`tests/test_fleet_desk_glass.py` samples real pixels), not a description of every pixel.
    """
    from itertools import combinations
    from .. import theme as T

    unders = [T.hex_to_rgb(ground)] + [_over(T.hex_to_rgb(c), a, T.hex_to_rgb(ground)) for c, a in mesh]
    for (c1, a1), (c2, a2) in combinations(mesh, 2):
        unders.append(_over(T.hex_to_rgb(c2), a2 / 2, _over(T.hex_to_rgb(c1), a1 / 2, T.hex_to_rgb(ground))))
    outs = sorted((_over(T.hex_to_rgb(fill[0]), fill[1], u) for u in unders), key=T.rel_luminance)
    return T.rgb_to_hex(outs[0]), T.rgb_to_hex(outs[-1])


def composited_panels(spec: dict) -> list[str]:
    """The colour(s) a variant's text is read on: one for a textured skin, two for glass."""
    panel = spec.get("composited_panel")
    if isinstance(panel, dict):
        return [panel["darkest"], panel["lightest"]]
    return [panel] if panel else []


def split(name: str) -> tuple[str, str]:
    """`"voxel:nether"` -> `("voxel", "nether")`; `"voxel"` -> `("voxel", "overworld")`.

    An unknown variant falls back to the skin's default rather than raising. The name comes from a
    hand-edited config file and from a URL, and a renamed variant must not be able to take the
    dashboard down -- the same reasoning that put `theme_or_none` in front of `theme.get`.
    """
    skin_name, _, variant = str(name or "").partition(":")
    skin = SKINS.get(skin_name)
    if not skin:
        return skin_name, ""
    if variant not in skin["variants"]:
        variant = skin["default"]
    return skin_name, variant


def get_skin(name: str) -> dict | None:
    """The skin, resolved through its variant, flattened for callers that want one dict.

    `base` and `composited_panel` are the *variant's*, which is what every existing reader of this
    function already meant by them -- so a caller that knows nothing about variants keeps working
    and gets the right answer for the chosen one.
    """
    skin_name, variant = split(name)
    skin = SKINS.get(skin_name)
    if not skin:
        return None
    chosen = skin["variants"][variant]
    return {
        "name": skin_name,
        "title": skin["title"],
        "why": skin["why"],
        "variant": variant,
        "variant_title": chosen["title"],
        "variant_why": chosen["why"],
        "base": chosen["base"],
        "composited_panel": chosen["composited_panel"],
        "full": f"{skin_name}:{variant}",
    }


def variants(skin_name: str) -> list[dict]:
    """Every variant of one skin, default first, as the picker lists them."""
    skin = SKINS.get(skin_name)
    if not skin:
        return []
    names = [skin["default"]] + [v for v in skin["variants"] if v != skin["default"]]
    return [{"name": v, "full": f"{skin_name}:{v}", **skin["variants"][v]} for v in names]


def list_skins() -> list[dict]:
    """Every skin with its variants, base palettes and stylesheet size.

    `base` and `composited_panel` at the top level are the default variant's, so the shape callers
    had before variants existed still answers the question they were asking.
    """
    out = [{
        "name": "none",
        "title": "Standard",
        "base": "system",
        "why": "the default clean HIG interface",
        "size_bytes": 0,
        "variants": [],
    }]
    for name, skin in SKINS.items():
        css_file = os.path.join(SKINS_DIR, name, "skin.css")
        size = os.path.getsize(css_file) if os.path.isfile(css_file) else 0
        fallback = skin["variants"][skin["default"]]
        out.append({
            "name": name,
            "title": skin["title"],
            "why": skin["why"],
            "size_bytes": size,
            "default": skin["default"],
            "base": fallback["base"],
            "composited_panel": fallback["composited_panel"],
            "variants": variants(name),
        })
    return out


def every_variant() -> list[tuple[str, str, dict]]:
    """(skin, variant, variant dict) for all of them. What the contrast test iterates."""
    return [(name, v, skin["variants"][v])
            for name, skin in SKINS.items()
            for v in skin["variants"]]
