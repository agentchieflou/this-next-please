"""The weather genre (docs/themes.md §Genres, [skin-weather.md](../docs/skin-weather.md)): a sky per
look, drawn by the ink layer, and the pane a sheet of paper laid on it.

The skin is a module (`static/ink/skins/weather.js`) whose sky is one shader with a weather per
variant -- rain that falls across the panes, the sun's rays turning, cloud cover drifting, stars
that twinkle and a meteor now and then -- and a stylesheet (`static/skins/weather/skin.css`) that
holds each weather's colours as custom properties. What is asserted:

* `skins.py` offers it, in the weather genre, on the two greyed palettes it brought (`slate`,
  `overcast`) and two it shares (`sand`, `vanta-black`); the picker names its looks by the
  weather alone;
* the stylesheet sets the numbers `skins.py` declares: the paper, every ink, the kind the module
  switches its sky on; the rain's panel is a pair, its light end the paper under a streak at the
  streak's peak alpha, recomputed here;
* `theme.check` holds every variant on every end of its paper;
* the two palettes are greyer than the blue the rainy day was first drawn on;
* the module carries no colour, no markup, no static import, and fits `SKIN_BUDGET`;
* the rain's own signs (`expresses`, docs/skin-weather.md §The rain's own signs) are on the two
  rainy variants alone;
* in a browser (`?ink=on`, from `test_fleet_ink.py`'s grammar test, which calls
  `weather_in_a_browser` here): the rain ticks on its own and stops under reduced motion, an
  error's arrival is a flash of lightning on the rainy day only, with thunder once the chime is
  on, a running pane's rain ripples and a done pane's dries, and another weather puts the rain
  away.
"""
from __future__ import annotations
import gzip
import os
import re

from agentdata import theme
from agentdata.fleet import serve as S, skins

from test_fleet_ink import SKIN_BUDGET, _choose, _mark, _open
from test_fleet_ink_cues import expresses_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "weather.js")
CSS = os.path.join(STATIC, "skins", "weather", "skin.css")

TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")

#: Each variant's sky, the number the module's `--wx-kind` switches its shader on: rain 0, sun 1,
#: cloud 2, stars 3. Showers is the rain's light side and dusk the cloud's dark one.
KINDS = {"rainy": 0, "sunny": 1, "cloudy": 2, "starry": 3, "showers": 0, "dusk": 2}

LOAD = "async () => { window.__wx = await import(q('/static/ink/skins/weather.js')); }"
WX = "() => window.__wx ? window.__wx.inspect() : null"


# ============================================================================== without a browser


def _css_block(variant: str) -> dict:
    css = open(CSS, encoding="utf-8").read()
    out = {}
    for pattern in (r'body\[data-skin="weather"\]\s*\{(.*?)\}',
                    r'body\[data-skin="weather"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant):
        m = re.search(pattern, css, re.S)
        if m:
            out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1))))
    return out


def test_the_weather_is_a_skin_of_the_weather_genre_the_settings_page_offers():
    assert skins.split("weather") == ("weather", "rainy")
    assert skins.split("weather:starry") == ("weather", "starry")
    assert skins.split("weather:auto") == ("weather", "auto")
    assert "weather" in S.ink_skins()
    assert skins.genre_of("weather") == "weather"
    assert [v["name"] for v in skins.variants("weather")] == list(KINDS)
    assert {v: skins.SKINS["weather"]["variants"][v]["base"] for v in KINDS} == {
        "rainy": "slate", "sunny": "sand", "cloudy": "overcast", "starry": "vanta-black",
        "showers": "overcast", "dusk": "slate"}
    assert skins.get_skin("weather:auto")["auto"]["light"]["full"] == "weather:sunny"
    assert skins.get_skin("weather:auto")["auto"]["dark"]["full"] == "weather:starry"
    # Three looks, each with a light and a dark side of its own weather (docs/themes.md §Genres).
    genre = next(g for g in skins.genres() if g["name"] == "weather")
    assert [l["title"] for l in genre["looks"]] == ["Rainy day", "Clear sky", "Cloudy"]
    assert [l["value"] for l in genre["looks"]] == ["weather:rain", "weather:clear", "weather:cloud"]
    assert {l["value"]: (l["sides"]["light"]["variant"], l["sides"]["dark"]["variant"]) for l in genre["looks"]} == {
        "weather:rain": ("showers", "rainy"), "weather:clear": ("sunny", "starry"), "weather:cloud": ("cloudy", "dusk")}
    assert skins.resolve("weather:rain", "light")["skin"] == "weather:showers"
    assert skins.resolve("weather:cloud", "dark")["skin"] == "weather:dusk"
    for name in ("slate", "overcast"):
        assert name not in skins.PALETTE_ONLY


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """Each weather's paper and inks, declared once in skins.py (where `theme.check` reads them)
    and named by skin.css (where the page and the module read them); `--wx-kind` is the variant's
    place in the module's order. The rain's light end is the paper under a streak."""
    for variant, kind in KINDS.items():
        spec = skins.SKINS["weather"]["variants"][variant]
        props = _css_block(variant)
        assert int(props["wx-kind"]) == kind, variant
        panel = spec["composited_panel"]
        if isinstance(panel, dict):
            # The rain's pair: the paper at one end, the paper under a streak at its peak alpha at
            # the other -- the light end on the dark rainy day, the dark end on the bright showers.
            drop, alpha = spec["drop"]
            assert props["wx-drop"].upper() == drop.upper() and float(props["wx-drop-alpha"]) == alpha, variant
            paper, streaked = (panel["darkest"], panel["lightest"]) if theme.is_dark(props["paper"]) \
                else (panel["lightest"], panel["darkest"])
            assert props["paper"].upper() == paper.upper(), variant
            assert theme.mix(paper, drop, alpha).upper() == streaked.upper(), variant
        else:
            assert props["paper"].upper() == panel.upper(), variant
            assert "drop" not in spec, (variant, "only the rain falls across the paper")
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), (variant, tool)
        for token in ("text", "muted", "bg", "panel", "line"):
            assert token not in props, (variant, "the palette's own token, recoloured", token)


def test_theme_check_holds_every_variant_on_every_end_of_its_paper():
    for variant, spec in skins.SKINS["weather"]["variants"].items():
        base = theme.get(spec["base"])
        dark = theme.is_dark(_css_block(variant)["paper"])
        assert dark == (not base.light), (variant, "a light sky on a light palette")
        for end in skins.composited_panels(spec):
            theme.check(base, composited_panel=end, skin=f"weather:{variant}", inks=spec["inks"], dark=dark)
            assert theme.contrast_ratio(theme.to_css(base)["--muted"], end) >= 4.5, (variant, end)


def test_the_rainy_and_cloudy_palettes_are_greyer_than_the_blue_the_rain_first_fell_on():
    """The operator's ask: a rainy day on a greyed ground, so the rain reads as weather rather than
    as a tint. Saturation is HSV's, `theme.saturation`."""
    blues = theme.get("blues")
    for name in ("slate", "overcast"):
        t = theme.get(name)
        assert theme.saturation(t.ground) < theme.saturation(blues.ground), (name, t.ground)
        assert theme.saturation(t.ground) <= theme.ACHROMATIC, (name, "a sky is grey, not a colour")
    assert theme.get("slate").light is False and theme.get("overcast").light is True


def test_the_rain_alone_expresses_the_grammar_with_weather():
    signs = {"needs_name": "squall", "needs_q": "squall", "needs_card": "squall", "running": "puddle",
             "error_bang": "lightning", "done": "drying"}
    assert expresses_of(MODULE) == {"rainy": signs, "showers": signs}
    assert {v for v, k in KINDS.items() if k == 0} == set(expresses_of(MODULE)), "every rainy kind, no other"


def test_the_module_carries_no_colour_no_markup_and_fits_its_budget():
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the weather module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList"):
        assert banned not in code, banned
    size = len(gzip.compress(body.replace("\r\n", "\n").encode("utf-8"), 6, mtime=0))
    assert size < SKIN_BUDGET, size


def test_the_module_reads_every_colour_it_draws_from_the_stylesheet():
    """Every `--wx-*` the module reads is one some variant's block sets, and the reverse: a
    property the stylesheet sets and nothing reads is a knob that turns nothing."""
    read = set(re.findall(r'"(--wx-[\w-]+)"', open(MODULE, encoding="utf-8").read()))
    css = open(CSS, encoding="utf-8").read()
    written = set("--" + p for p in re.findall(r"--(wx-[\w-]+):", css))
    assert read == written, (sorted(read - written), sorted(written - read))


# ================================================================================ with a browser
#
# Folded into `tests/test_fleet_ink.py::test_a_skin_is_a_module_the_page_loads_when_it_is_chosen`
# rather than a browser test of its own, as #397 folded the circuit board's: the browser tier's
# time budget (decision 20, `tests/test_suite_hygiene.py`) is the operator's number, and the tier
# stood 0.1 s under it with one more test. The checks are this file's; the page is that test's.


def weather_in_a_browser(browser, port, token) -> dict:
    """On a served desk with the ink on: the rain ticks on its own, an error's arrival is
    lightning on the rainy day only, another weather puts the rain away, and under reduced motion
    the weather is drawn once and holds still. Returns what it saw, for the caller's assert."""
    seen = {}
    page, errors, _ = _open(browser, port, token, "&ink=on")
    _choose(page, "weather:rainy")
    page.wait_for_function("() => Ink.inspect().table === 'weather:rainy'", timeout=10000)
    page.evaluate(LOAD)
    page.wait_for_function("() => window.__wx.inspect().ticks > 5 && window.__wx.inspect().time > 0", timeout=15000)
    first = page.evaluate(WX)
    assert first["kind"] == "rainy" and first["rain"] and first["over"] == 2, first
    assert first["time"] > 0 and not first["reduced"], first
    layer = page.evaluate("() => Ink.inspect().layer")
    assert layer["skin"]["hooks"] == ["ground", "paper", "frame", "tick", "dispose"], layer["skin"]
    assert layer["skin"]["errors"] == [] and layer["mode"] == 2, "a dark paper under the marks: screen"
    # The rain's own signs: with the ink on, the rainy table has no highlighter, bang or check row.
    rows = page.evaluate("() => Ink.inspect().layer.marks.map(m => [m.tool, m.shape])")
    assert rows and not [r for r in rows if r[0] == "highlighter" or r[1] in ("bang", "check")], rows
    # A running pane's rain ripples; a done pane's dries; a pane that needs you gets a squall.
    _mark(page, "beta", "state-running")
    page.wait_for_function("() => (window.__wx.inspect().panes.beta || {}).ripple === 1", timeout=10000)
    _mark(page, "beta", "state-done")
    page.wait_for_function("() => (window.__wx.inspect().panes.beta || {}).dry === 1", timeout=10000)
    _mark(page, "alpha", "needs-human")
    page.wait_for_function("() => (window.__wx.inspect().panes.alpha || {}).squall === 1", timeout=10000)
    # An error's arrival is lightning: a flash that is gone within the event's 320 ms; no thunder
    # while the chime is off.
    _mark(page, "alpha", "state-error")
    page.wait_for_function("() => window.__wx.inspect().played.lightning === 1", timeout=10000)
    page.wait_for_function("() => window.__wx.inspect().flash === 0", timeout=10000)
    assert "thunder" not in page.evaluate(WX)["played"], "thunder is the chime's"
    # The chime on: the next lightning rolls thunder.
    page.click("#chime")
    page.wait_for_function("() => window.__wx.inspect().chime === true", timeout=5000)
    _mark(page, "beta", "state-error")
    page.wait_for_function("() => window.__wx.inspect().played.lightning === 2", timeout=10000)
    assert page.evaluate(WX)["played"].get("thunder") == 1, page.evaluate(WX)["played"]
    page.click("#chime")
    # Another weather puts the rain away and keeps the sky moving.
    _choose(page, "weather:starry")
    page.wait_for_function("() => Ink.inspect().table === 'weather:starry'", timeout=10000)
    page.evaluate(LOAD)
    page.wait_for_function("() => window.__wx.inspect().kind === 'starry'", timeout=10000)
    starry = page.evaluate(WX)
    assert not starry["rain"] and starry["over"] == 0, starry
    _mark(page, "alpha", "state-error")
    page.wait_for_function("() => (window.__wx.inspect().played.lightning || 0) >= 1", timeout=10000)
    assert page.evaluate(WX)["flash"] == 0, "lightning is the rainy day's alone"
    seen["errors"] = list(errors)
    page.close()

    # Reduced motion: the weather is drawn once and holds still.
    page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
    page.wait_for_function("() => Ink.inspect().table === 'weather:starry'", timeout=10000)
    page.evaluate(LOAD)
    page.wait_for_function("() => window.__wx.inspect().ticks >= 1", timeout=10000)
    held = page.evaluate(WX)
    assert held["reduced"] and held["time"] == 0, held
    assert page.evaluate("() => Ink.inspect().layer.reduced") is True
    seen["errors"] += errors
    seen["held"] = held
    _choose(page, "none")
    page.wait_for_function("() => Ink.inspect().table === null", timeout=10000)
    page.close()
    return seen
