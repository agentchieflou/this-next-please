"""Skins for the Desk, and the palettes each one is drawn against (#154-#157, #4).

A skin is drawn over the same DOM and never changes it. Since #257 a skin that draws with ink is its
module (`static/ink/skins/<name>.js`, three.js) plus a stylesheet that keeps only its layout, its
typography and the colours the module reads -- nothing it paints, which a test guards -- and under
`body.ink-off` every skin is the one plain look. A skin with no module yet (voxel) is a stylesheet
over the page, as every skin once was. A skin that needs a page change is not a skin.

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
- `theme.skin` in `~/.agentdata/config.json`, `'none'` by default, spelled `<skin>`,
  `<skin>:<variant>` or `<skin>:auto`. A bare skin name means its default variant. `auto` follows the
  system's light or dark appearance (#342) on a skin that declares an `auto` pair, one light and one
  dark variant; on any other skin it means the default variant, as an unknown variant does.
- No rasters: 100% original hand-authored vector SVG pixel art.
- Fallbacks: `prefers-reduced-transparency`, and `prefers-reduced-motion` for any skin that moves.
"""
from __future__ import annotations
import os

#: The variant name that follows the system's appearance (#342), on a skin with an `auto` pair.
AUTO = "auto"

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
        "auto": {"light": "frost", "dark": "smoke"},
        "variants": {
            "smoke": {"title": "Smoke", "base": "dark",
                      "mesh": [("#58A6FF", 0.35), ("#3FB950", 0.35), ("#D29922", 0.30)],
                      "fill": ("#1F2836", 0.36),
                      "inks": {"highlighter": "#A97B1B"},
                      "composited_panel": {"darkest": "#181D24", "lightest": "#273D57"},
                      "why": "neutral graphite behind the frost"},
            "azure": {"title": "Azure", "base": "blues",
                      "mesh": [("#4DA3FF", 0.30), ("#5EE1E6", 0.25), ("#3FB950", 0.30)],
                      "fill": ("#1A2A48", 0.40),
                      "inks": {"highlighter": "#3979BE"},
                      "composited_panel": {"darkest": "#11213B", "lightest": "#1D3F56"},
                      "why": "cold blue depth, the darkest of the three"},
            "noir": {"title": "Noir", "base": "vanta-black",
                      "mesh": [("#E6E6E6", 0.16), ("#58A6FF", 0.18), ("#9A9A9A", 0.12)],
                      "fill": ("#1A1A1A", 0.40),
                      "inks": {"highlighter": "#AC7D1C"},
                      "composited_panel": {"darkest": "#0A0A0A", "lightest": "#202020"},
                      "why": "near-black, for a room with the lights off"},
            "frost": {"title": "Frost", "base": "eye-relief-day",
                      "mesh": [("#8A6D1F", 0.30), ("#2A5F9E", 0.25), ("#2A733E", 0.25)],
                      "fill": ("#F4EEE0", 0.34),
                      "inks": {"highlighter": "#F0DC7A"},
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
            # `inks` (#256): the voxel's mark table drawn on its slab, whose face is the composited
            # panel. Each is the palette's own token (`theme.to_css` of `base`) -- marker and red
            # `--human`, green `--done`, pencil `--muted` -- and `tests/test_fleet_voxel_ink.py`
            # holds them to it, so a palette change cannot leave a stale ink here unchecked. The
            # highlighter and the pen (#334: the state grammar's needs-you and running) are the
            # world's own, the literal its skin.css writes as `--ink-<tool>`: a highlighter the
            # name keeps 4.5:1 through on the slab (`theme.highlight_under`), a pen the world's
            # running blue.
            "overworld": {"title": "Overworld", "base": "matrix", "composited_panel": "#1E221E",
                          "why": "grass, stone and daylight",
                          "inks": {"marker": "#FF3B3B", "red": "#FF3B3B", "green": "#A8FFC0",
                                   "pencil": "#2CAD57", "highlighter": "#BF9637", "pen": "#5EF0FF"}},
            "nether": {"title": "Nether", "base": "reds", "composited_panel": "#2A1512",
                       "why": "netherrack and firelight",
                       "inks": {"marker": "#FFD166", "red": "#FFD166", "green": "#7EE787",
                                "pencil": "#B79191", "highlighter": "#FAA355", "pen": "#79C0FF"}},
            "end": {"title": "The End", "base": "vanta-black", "composited_panel": "#16121C",
                    "why": "endstone and void",
                    "inks": {"marker": "#F85149", "red": "#F85149", "green": "#3FB950",
                             "pencil": "#929292", "highlighter": "#C59020", "pen": "#58A6FF"}},
        },
    },
    "farmstead": {
        "name": "farmstead",
        "title": "Farmstead",
        "why": "warm paper, wood trim and rustic crop-stage markers inspired by pixel farming",
        "default": "daytime",
        "auto": {"light": "daytime", "dark": "cave"},
        "variants": {
            "daytime": {"title": "Daytime", "base": "sand", "composited_panel": "#E8DDC3",
                        "inks": {"pencil": "#74695A", "highlighter": "#E2B45C"},
                        "why": "sunlight on paper and wood"},
            "cave": {"title": "Cave", "base": "eye-relief", "composited_panel": "#33302A",
                     "inks": {"pencil": "#968F82", "highlighter": "#816718"},
                     "why": "lamplight underground"},
            "rainy": {"title": "Rainy day", "base": "blues", "composited_panel": "#16243D",
                      "inks": {"pencil": "#8A97AB", "highlighter": "#D4A73D"},
                      "why": "a wet afternoon indoors"},
        },
    },
    # #253, the ink epic's slice G: drawn by the ink layer (`static/ink/skins/graph.js`). The pane
    # is the paper itself, so the panel is `--paper`; `inks` are the skin's `--ink-<tool>` (and the
    # plotted trace's), each checked on that paper; `grid` is the major line text has to cross.
    # `skin.css` carries the same numbers and `tests/test_fleet_ink_graph.py` holds them together.
    "graph": {
        "name": "graph",
        "title": "Graph paper",
        "why": "a 28px grid, a mechanical pencil, ruled marks and every agent's hour plotted on it",
        "default": "engineering",
        "auto": {"light": "engineering", "dark": "blueprint"},
        "variants": {
            "engineering": {"title": "Engineering", "base": "eye-relief-day",
                            "composited_panel": "#F3F6EC", "grid": "#A8C3A0",
                            "inks": {"pencil": "#4F555C", "pen": "#1D4E89", "red": "#B42318",
                                     "green": "#2A733E", "marker": "#B42318",
                                     "highlighter": "#E6DE5A", "trace": "#1D4E89"},
                            "why": "green quad-ruled pad, graphite and a blue pen"},
            "blueprint": {"title": "Blueprint", "base": "blues",
                          "composited_panel": "#123A66", "grid": "#2F6096",
                          "inks": {"pencil": "#C4D3E6", "pen": "#EAF2FF", "red": "#FF8B7E",
                                   "green": "#7BE38B", "marker": "#FF8B7E",
                                   "highlighter": "#958225", "trace": "#EAF2FF"},
                          "why": "white lines on a cyanotype"},
        },
    },
    # #251: drawn by the ink layer (`static/ink/skins/legalpad.js`). The panel is the canary stock
    # itself, and `inks` are the colours `skin.css` writes as `--ink-<tool>` or leaves to the
    # palette (red, green and the marker are eye-relief-day's own), each checked on that paper.
    "legalpad": {
        "name": "legalpad",
        "title": "Legal pad",
        "why": "a yellow legal pad: canary stock, blue rules, a double red margin and a glued top, "
               "drawn on in pencil, pen and highlighter",
        "default": "canary",
        "variants": {
            "canary": {"title": "Canary", "base": "eye-relief-day", "composited_panel": "#FCF3A6",
                       "inks": {"pencil": "#5E5A52", "pen": "#1F3F9A", "red": "#A82D2D",
                                "green": "#2A733E", "marker": "#A82D2D", "highlighter": "#FF8FA3"},
                       "why": "canary stock, and an orange-pink highlighter that still reads on it"},
        },
    },
    # #252: drawn by the ink layer (`static/ink/skins/napkin.js`). The text is read on the quilted
    # stock, which is never darker than its `seam`, and on a coffee ring's rim at the coffee's alpha
    # over that seam -- so the panel is a pair, `composited_range`-style: the ring over the seam at
    # the dark end, the paper at the light one. `tests/test_fleet_napkin.py` recomputes the pair and
    # reads skin.css back, so declared and drawn are one number. `inks` are the ones skin.css sets.
    "napkin": {
        "name": "napkin",
        "title": "Napkin notes",
        "why": "quilted two-ply napkin, a felt tip that bleeds along the emboss, and a coffee ring",
        "default": "diner",
        "variants": {
            "diner": {"title": "Diner", "base": "eye-relief-day",
                      "paper": "#FBF9F4", "seam": "#F1EFEA", "coffee": ("#8A5A2E", 0.14),
                      "composited_panel": {"darkest": "#E3DAD0", "lightest": "#FBF9F4"},
                      "inks": {"pencil": "#5B5E66", "pen": "#1E3A8A", "red": "#B42318",
                               "green": "#256B45", "marker": "#B3261E", "highlighter": "#F4DC52"},
                      "why": "a white napkin from the counter, and a blue ballpoint"},
            "kraft": {"title": "Kraft", "base": "sand",
                      "paper": "#F2EADA", "seam": "#EBE3D3", "coffee": ("#7A4E2A", 0.10),
                      "composited_panel": {"darkest": "#E0D4C2", "lightest": "#F2EADA"},
                      "inks": {"pencil": "#57524A", "pen": "#243F86", "red": "#A3271C",
                               "green": "#2A6A3F", "marker": "#9E2A1E", "highlighter": "#F5D94A"},
                      "why": "an unbleached napkin, for a warmer page"},
        },
    },
    # The first skin drawn with ink (#249, #250; docs/desk-ink.md §The notebook). Its panel is the
    # paper itself: under ink the panes are transparent and the page is the stock. `inks` are the
    # tools' colours on that paper (the prototype's), `text` and `muted` the words written on it --
    # the skin's own, set in its skin.css, and held to the same floors by tests/test_fleet_ink_notebook.py.
    # Dark is a variant rather than a `notebook-dark` family: skins drive palettes, so the night
    # page's ground is named by the variant like Voxel's Nether, and one module draws both.
    "notebook": {
        "name": "notebook",
        "title": "Notebook",
        "why": "a graph-ruled notebook drawn live in pencil, pen, marker and highlighter",
        "default": "light",
        "auto": {"light": "light", "dark": "dark"},
        "variants": {
            "light": {"title": "Notebook", "base": "eye-relief-day", "composited_panel": "#FBFBF6",
                      "inks": {"pencil": "#50545C", "pen": "#22398F", "red": "#C8352B",
                               "green": "#2E7A4D", "marker": "#C8352B", "highlighter": "#F3DF4B"},
                      "why": "white stock, blue rules, a red margin"},
            "dark": {"title": "Night notebook", "base": "dark", "composited_panel": "#1B1E25",
                     "inks": {"pencil": "#B5BAC4", "pen": "#94B4FF", "red": "#FF6A5E",
                              "green": "#6FD39A", "marker": "#FF6A5E", "highlighter": "#CEBF40"},
                     "why": "charcoal stock and gel inks, the highlighter screened"},
        },
    },
    # #389 (epic #294): a coach's chalkboard, drawn by the ink layer (`static/ink/skins/playbook.js`)
    # on `nfl-browns`. The board is a pair like napkin's: `--paper` at the dark end, `--board-max` the
    # lightest any pixel of it may be (#390), which the text's contrast is held at. `inks` are the ones
    # its skin.css sets. Neither the skin nor a variant names a team or a league (#318's names
    # decision, `tests/test_fleet_ink_playbook.py`'s trademark guard); the palette keeps its own.
    "playbook": {
        "name": "playbook",
        "title": "Playbook",
        "why": "a coach's chalkboard: X's and O's, each agent's route in orange chalk",
        "default": "chalkboard",
        "variants": {
            "chalkboard": {"title": "Chalkboard", "base": "nfl-browns",
                           "composited_panel": {"darkest": "#2B1B08", "lightest": "#40301D"},
                           "inks": {"pencil": "#D9CBB3", "pen": "#FF3C00", "red": "#FF5A8A",
                                    "green": "#56D364", "marker": "#FF5A8A", "highlighter": "#BF9637"},
                           "why": "brown slate, cream and orange chalk"},
            # #392: the bright-room playbook, on sand (a light skin names a light palette). Here
            # the board's darker end is its yard lines' stock and `--paper` is the lighter one.
            "playsheet": {"title": "Play sheet", "base": "sand",
                          "composited_panel": {"darkest": "#E9DFC9", "lightest": "#F7F1E3"},
                          "inks": {"pencil": "#57524A", "pen": "#9A4F12", "red": "#A01A4F",
                                   "green": "#2A6A3F", "marker": "#A01A4F", "highlighter": "#F5D94A"},
                          "why": "a printed play sheet: graphite and a burnt-orange pen"},
        },
    },
    # #394: drawn by the ink layer (`static/ink/skins/phosphor.js`). The pane is the glass itself,
    # between its near-black and its scanline, so the panel is that pair, checked at both ends;
    # `inks` are the ones skin.css writes as `--ink-<tool>`, and `tests/test_fleet_ink_phosphor.py`
    # holds the two to one number. The highlighter is the palette's amber, a shade darker than its
    # `--waiting`, so the text keeps 4.5:1 through it on the scanline.
    "phosphor": {
        "name": "phosphor",
        "title": "Phosphor",
        "why": "a green phosphor screen: scanlines and a beam that draws",
        "default": "green",
        "variants": {
            "green": {"title": "Green", "base": "matrix",
                      "composited_panel": {"darkest": "#010603", "lightest": "#0A1F10"},
                      "inks": {"pencil": "#3FA866", "pen": "#00FF41", "red": "#FF3B3B",
                               "green": "#A8FFC0", "marker": "#FF3B3B", "highlighter": "#CCA13B"},
                      "why": "phosphor on glass"},
        },
    },
    # #396: drawn by the ink layer (`static/ink/skins/circuit.js`). The pane is the board, so the
    # panel is the solder mask, a pair `composited_range`-style: the mask (`--paper`) at the dark end
    # and its fibreglass weave at the light one, never brighter than `--board-max`. `inks` are the
    # ones skin.css sets as `--ink-<tool>`; `tests/test_fleet_ink_circuit.py` reads them back. The
    # copper (`--copper`) is decoration only, never under a word, so it is in no check. The
    # highlighter is #D29922 darkened to keep the text 4.5:1 through its screen at the light end.
    "circuit": {
        "name": "circuit",
        "title": "Circuit board",
        "why": "solder mask, silkscreen and copper: each agent a component on the board",
        "default": "solder",
        "variants": {
            "solder": {"title": "Solder", "base": "greens",
                       "composited_panel": {"darkest": "#0D2618", "lightest": "#1C3A28"},
                       "inks": {"pencil": "#E4EDE6", "pen": "#D9A066", "red": "#F85149",
                                "green": "#7EE787", "marker": "#F85149", "highlighter": "#B7851E"},
                       "why": "green solder mask, white silkscreen and bare copper"},
            "matte": {"title": "Matte", "base": "vanta-black",
                      "composited_panel": {"darkest": "#0A0A0A", "lightest": "#1A1A1A"},
                      "inks": {"pencil": "#D8D8D8", "pen": "#D9A066", "red": "#F85149",
                               "green": "#3FB950", "marker": "#F85149", "highlighter": "#B7851E"},
                      "why": "a matte-black board, for a room with the lights off"},
        },
    },
    # The weather genre (docs/themes.md §Genres): one sky per variant, drawn by the ink layer
    # (`static/ink/skins/weather.js`), and the pane a sheet of paper laid on it. The rain is the one
    # weather that falls across the paper (the streaks are drawn over the sheet, under the words),
    # so its panel is a pair: the paper at the dark end and the paper under a streak at its peak
    # alpha at the light end, `theme.mix(paper, --wx-drop, --wx-drop-alpha)`; the sun, the cloud
    # and the stars stay behind an opaque sheet, so theirs is one colour. `inks` are the ones its
    # skin.css writes as `--ink-<tool>`; `tests/test_fleet_ink_weather.py` holds the two together
    # and recomputes the pair. Each weather is drawn on the palette that is its light: the rain on
    # `slate`, the sun on `sand`, the cloud cover on `overcast`, the night on `vanta-black`.
    "weather": {
        "name": "weather",
        "title": "Weather",
        "why": "a sky over the desk: rain that falls across the panes, sun, cloud cover or stars",
        "default": "rainy",
        "auto": {"light": "sunny", "dark": "starry"},
        "variants": {
            "rainy": {"title": "Rainy day", "base": "slate",
                      "composited_panel": {"darkest": "#2B3037", "lightest": "#3B434D"},
                      "drop": ("#8FA9C2", 0.16),
                      "inks": {"pencil": "#AAB6C4", "pen": "#8FB3D1", "red": "#F0645C",
                               "green": "#5FC77A", "marker": "#F0645C", "highlighter": "#635618"},
                      "why": "grey sky, rain falling across the panes, a flash of lightning on an error"},
            "sunny": {"title": "Sunny day", "base": "sand", "composited_panel": "#F6EEDC",
                      "inks": {"pencil": "#5A5247", "pen": "#B9631E", "red": "#B3261E",
                               "green": "#2E7D4F", "marker": "#B3261E", "highlighter": "#F2D24E"},
                      "why": "a warm sky, the sun's rays turning slowly behind the panes"},
            "cloudy": {"title": "Cloudy", "base": "overcast", "composited_panel": "#F2F4F6",
                       "inks": {"pencil": "#555C64", "pen": "#3E5F80", "red": "#B3261E",
                                "green": "#2A733E", "marker": "#B3261E", "highlighter": "#E9D64F"},
                       "why": "grey-white cloud cover drifting behind the panes"},
            "starry": {"title": "Starry night", "base": "vanta-black", "composited_panel": "#0B0E16",
                       "inks": {"pencil": "#B9BCC4", "pen": "#9FC4F0", "red": "#F85149",
                                "green": "#3FB950", "marker": "#F85149", "highlighter": "#B59A2A"},
                       "why": "a night sky: stars that twinkle, a meteor now and then"},
        },
    },
}


# The palettes no variant above is drawn on yet, each with the reason (#393). Every built-in palette
# but `none` is a variant's `base` or is listed here, never both (`tests/test_fleet_skins.py`), so
# /settings can say of every palette which looks are drawn on it -- or that it is the plain page
# only, and still one to choose. It empties as the skins land: #389 removes `nfl-browns`, #396 `greens`.
PALETTE_ONLY: dict[str, str] = {
}


# Glass's inks (#254): the palette token each tool of its mark table (`static/ink/skins/glass.js`)
# is drawn in, unless a variant's `ink_tokens` names another -- which its skin.css says again as
# `--ink-<tool>`. Resolved against the variant's own palette, so `theme.check` holds every mark on
# both ends of the frost, and the text through the highlighter, like any paper skin's inks. A
# variant's own `inks` (a literal its skin.css writes as `--ink-<tool>`, #329) win over the tokens.
GLASS_INKS = {"pen": "--accent", "red": "--human", "green": "--done", "marker": "--human",
              "highlighter": "--waiting"}


def _glass_inks() -> None:
    from .. import theme as T
    for spec in SKINS["glass"]["variants"].values():
        css = T.to_css(T.get(spec["base"]))
        tokens = dict(GLASS_INKS, **spec.get("ink_tokens", {}))
        spec["inks"] = dict({tool: css[token] for tool, token in tokens.items()}, **spec.get("inks", {}))


_glass_inks()


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
    if variant == AUTO and skin.get("auto"):
        return skin_name, AUTO
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
    if variant == AUTO:
        # `base` and `composited_panel` are the default variant's: what the terminal gets, since it
        # cannot follow the system, and what a reader that knows nothing of `auto` falls back to.
        chosen = skin["variants"][skin["default"]]
        return {
            "name": skin_name,
            "title": skin["title"],
            "why": skin["why"],
            "variant": AUTO,
            "variant_title": "Auto",
            "variant_why": "follows the system's light or dark appearance",
            "base": chosen["base"],
            "composited_panel": chosen["composited_panel"],
            "full": f"{skin_name}:{AUTO}",
            "auto": {side: {"variant": v, "base": skin["variants"][v]["base"], "full": f"{skin_name}:{v}"}
                     for side, v in skin["auto"].items()},
        }
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
            # The light and dark variant `<skin>:auto` follows (#342), or absent: the picker offers
            # "Auto" only where it is there.
            **({"auto": dict(skin["auto"])} if skin.get("auto") else {}),
        })
    return out


def every_variant() -> list[tuple[str, str, dict]]:
    """(skin, variant, variant dict) for all of them. What the contrast test iterates."""
    return [(name, v, skin["variants"][v])
            for name, skin in SKINS.items()
            for v in skin["variants"]]


def panels_on(base: str) -> list[str]:
    """Every composited panel of every variant drawn on the palette `base` -- both ends of glass's
    frost -- each once, in `every_variant` order (#328). A word written in a state colour is read
    on all of them, so they are what its `-text` token is chosen against
    (`theme.to_css(t, panels=panels_on(t.name))`): one set per palette, the same under every skin
    drawn on it. Pure data; `theme` never imports the fleet, so the caller passes these."""
    out: list[str] = []
    for _, _, spec in every_variant():
        if spec["base"] != base:
            continue
        for panel in composited_panels(spec):
            if panel not in out:
                out.append(panel)
    return out


# ---------- Genres: the one picker (docs/themes.md §Genres) ----------
#
# The settings page offers ONE control, "look", grouped by genre. A look is a skin variant (which
# brings its palette with it, as above) or, in the `plain` genre, a palette on its own -- the plain
# HIG page in that palette, which is what choosing a palette with no skin always was. A genre is
# what its looks have in common: the weather genre's looks are skies and its animation is weather;
# the football genre's are a coach's board and its animation is routes. Every skin names its genre
# here, once; a skin in no genre is not offered (`tests/test_fleet_skins.py`).
GENRES: dict[str, dict] = {
    "weather": {"title": "Weather", "why": "a sky over the desk, and weather that moves",
                "skins": ["weather"]},
    "paper": {"title": "Paper", "why": "stock, rules and a hand that writes",
              "skins": ["notebook", "legalpad", "napkin", "graph"]},
    "football": {"title": "Football", "why": "a coach's board: routes, X's and O's",
                 "skins": ["playbook"]},
    "worlds": {"title": "Worlds", "why": "a place with its own hour and weather",
               "skins": ["farmstead", "voxel"]},
    "screens": {"title": "Screens", "why": "glass, phosphor and a circuit board",
                "skins": ["glass", "phosphor", "circuit"]},
    "plain": {"title": "Plain", "why": "a palette alone: the plain page, shared with the terminal",
              "skins": []},
}

#: The value of a plain-genre look: `palette:<name>`; `palette:none` is the system's own colours.
PALETTE_LOOK = "palette:"


def genre_of(skin_name: str) -> str:
    """The genre a skin is listed in, or `""`."""
    for name, genre in GENRES.items():
        if skin_name in genre["skins"]:
            return name
    return ""


def look_title(skin_name: str, variant: str | None) -> str:
    """How a look is named in the picker: the variant's title alone when its skin is the only one
    of its genre (Weather · Rainy day would say weather twice) or when the two titles are one
    word (Notebook · Notebook), else `skin · variant`; the skin's title alone when it has one
    variant; `skin · Auto` for the pair that follows the system."""
    skin = SKINS[skin_name]
    alone = len(GENRES.get(genre_of(skin_name), {}).get("skins", [])) == 1
    if variant == AUTO:
        return ("Auto" if alone else f"{skin['title']} · Auto")
    if variant is None or len(skin["variants"]) == 1:
        return skin["title"]
    title = skin["variants"][variant]["title"]
    return title if alone or title == skin["title"] else f"{skin['title']} · {title}"


def parse_look(value: str) -> dict:
    """What `/api/theme` is posted for a look the picker chose: `{"skin": full}` for a skin
    variant, `{"theme": name, "skin": "none"}` for a plain palette. Pure, so the page and the
    tests agree on it."""
    v = str(value or "").strip()
    if v.startswith(PALETTE_LOOK):
        return {"theme": v[len(PALETTE_LOOK):] or "none", "skin": "none"}
    return {"skin": v or "none"}


def genres() -> list[dict]:
    """The picker, as data: every genre in `GENRES` order with its looks, each a value the page
    posts back (`parse_look`), its title, its why and the palette it brings. The default variant
    of a skin leads its skin's looks, `Auto` closes them. The plain genre's looks are the palettes
    by title, `none` (the system's colours) first."""
    from .. import theme as T
    out = []
    for name, genre in GENRES.items():
        looks = []
        for skin_name in genre["skins"]:
            skin = SKINS.get(skin_name)
            if not skin:
                continue
            for v in variants(skin_name):
                looks.append({"value": v["full"], "title": look_title(skin_name, v["name"]),
                              "why": v["why"], "skin": skin_name, "variant": v["name"], "base": v["base"]})
            if skin.get("auto"):
                looks.append({"value": f"{skin_name}:{AUTO}", "title": look_title(skin_name, AUTO),
                              "why": f"follows the system: {skin['auto']['light']} when light, "
                                     f"{skin['auto']['dark']} when dark",
                              "skin": skin_name, "variant": AUTO, "base": skin["variants"][skin["default"]]["base"]})
        if name == "plain":
            for t in sorted(T.list_themes(), key=lambda t: t.name != "none"):
                looks.append({"value": PALETTE_LOOK + t.name, "title": t.title if t.name != "none" else "System",
                              "why": t.why, "skin": "", "variant": "", "base": t.name})
        out.append({"name": name, "title": genre["title"], "why": genre["why"], "looks": looks})
    return out


def look_of(theme_name: str, skin_name: str) -> str:
    """The picker value that shows what is worn: the skin's full name while one is on, else the
    palette as a plain look."""
    if skin_name and skin_name != "none":
        return skin_name
    return PALETTE_LOOK + (theme_name or "none")
