"""The Colors genre (docs/themes.md §Colors): three looks -- matte, glass, cyber -- built from any
colour the operator names, on either side, and the engine under them (`theme.from_hue`, `flip`,
`inks_on`, `glass_numbers`). What is asserted:

* a palette is built from any colour in every mode on both sides and passes `theme.check`; its
  name resolves by itself, so the terminal follows;
* the glass mode holds its inks, its muted text and its words on both ends of the frost it is
  drawn under, and its `--colors-*` tokens are ones the served page lets through;
* glass's `hue` variant is the default colour's numbers, hidden from the Screens looks, and its
  stylesheet fallbacks repeat them;
* the three looks resolve on either side, follow the system, and are the picker's Colors genre;
  the palettes folded into Colors are its presets and no longer plain looks;
* every built-in palette's flip is the other side and passes `check`;
* the server writes the colour, refuses one that is not six hex digits, serves the glass tokens
  with the palette, and names the colour and the presets on `/api/themes`;
* in a browser: the settings page shows the colour row for a Colors look, a preset seeds the
  colour, and the page wears the palette the server built.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request

import pytest

from agentdata import theme as T
from agentdata.fleet import serve as S, skins as K

from desk_harness import close_pages
from test_fleet_ink import _serve, _stop, fleet_home  # noqa: F401 - fixtures are used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLASS_CSS = os.path.join(ROOT, "agentdata", "fleet", "static", "skins", "glass", "skin.css")


def _post(port, token, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/theme?t={token}",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get(port, token, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?t={token}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# ============================================================================== without a browser


def test_a_palette_is_built_from_any_colour_in_every_mode_on_both_sides():
    """The engine's promise: `check` passes for any hue, at any saturation and lightness of the
    seed, in every mode, on both sides (`from_hue` runs `check` itself). The name is the address."""
    built = 0
    for mode in T.MODES:
        for side in T.SIDES:
            for h in range(0, 360, 20):
                for s_ in (0.0, 0.5, 1.0):
                    for l_ in (0.2, 0.5, 0.8):
                        seed = T._hsl(h, s_, l_)
                        t = T.from_hue(seed, mode, side)
                        built += 1
                        assert t.light == (side == "light"), t.name
                        assert t.name == f"colors:{mode}:{seed[1:].upper()}:{side}"
                        assert T.get(t.name).ground == t.ground, "the name resolves to the same palette"
                        assert T.parse_name(t.name) == {"mode": mode, "hex": seed[1:].upper(), "side": side}
    assert built == 3 * 2 * 18 * 9
    cyber = T.from_hue("#3A7BD5", "cyber", "dark")
    assert T.contrast_ratio(cyber.text, cyber.ground) >= 10, "cyber is the high-contrast mode"
    matte = T.from_hue("#3A7BD5", "matte", "dark")
    assert T.saturation(matte.ground) < T.saturation(cyber.ground), "matte is the muted one"
    with pytest.raises(T.ThemeError):
        T.from_hue("#12", "matte", "dark")
    with pytest.raises(T.ThemeError):
        T.from_hue("#3A7BD5", "neon", "dark")
    with pytest.raises(T.ThemeError):
        T.get("colors:matte:3A7BD5:dusk")


def test_the_glass_mode_holds_its_inks_and_words_on_both_ends_of_its_frost():
    """Rule 5 and #325 at both ends of the pair `composited_range` computes from the mesh the
    colour lights and the fill: the inks, the highlighter read through, the muted text; and every
    token the page is served for it passes `page_theme`'s filter."""
    for h in range(0, 360, 30):
        for side in T.SIDES:
            t = T.get(K.colors_theme_name("glass", T._hsl(h, 0.8, 0.5), side))
            g = K.colors_glass(t)
            ends = K.composited_panels(g)
            assert T.rel_luminance(T.hex_to_rgb(ends[0])) < T.rel_luminance(T.hex_to_rgb(ends[1]))
            for end in ends:
                T.check(t, composited_panel=end, skin=f"colors:glass:{h}:{side}", inks=g["inks"], dark=not t.light)
                assert T.contrast_ratio(T.to_css(t)["--muted"], end) >= 4.5, (t.name, end)
            assert set(g["inks"]) == set(K.GLASS_INKS)
            css = K.colors_css(t)
            assert set(css) == {"--colors-mesh-1", "--colors-mesh-2", "--colors-mesh-3", "--colors-fill", "--colors-card",
                                "--colors-edge", "--colors-card-edge", "--colors-glint", "--colors-shadow",
                                "--colors-ink", "--colors-ink-soft", "--colors-highlighter"}
            for name, value in css.items():
                assert S.CSS_TOKEN.match(name) and S.CSS_HEX.match(value), (name, value)


def test_the_hue_variant_of_glass_is_the_default_colours_numbers_and_hidden():
    """The one stylesheet block that draws every colour: `var(--colors-*)` with the default colour's
    numbers as the fallbacks, held to `check` as the `hue` variant of glass, which the picker never
    lists under Screens."""
    spec = K.SKINS["glass"]["variants"]["hue"]
    t = T.get(spec["base"])
    assert spec["base"] == K.colors_theme_name("glass", K.DEFAULT_COLOUR, "dark") and spec["hidden"]
    numbers = T.glass_numbers(t.ground, t.text, K.DEFAULT_COLOUR, t.light)
    assert spec["mesh"] == numbers["mesh"] and spec["fill"] == numbers["fill"]
    assert spec["composited_panel"] == K.colors_glass(t)["composited_panel"]
    assert "glass:hue" not in [l["value"] for l in K.looks("glass")]
    assert all(l["light"] != "hue" and l["dark"] != "hue" for l in K.looks("glass"))
    css = open(GLASS_CSS, encoding="utf-8").read()
    block = re.search(r'body\[data-skin="glass"\]\[data-skin-variant="hue"\]\s*\{(.*?)\}', css, re.S).group(1)
    served = K.colors_css(t)
    def as_rgba(h8):
        r, g, b = (int(h8[i:i + 2], 16) for i in (1, 3, 5))
        return f"rgba({r}, {g}, {b}, {int(h8[7:9], 16) / 255:.2f})"
    rows = re.findall(r"--([\w-]+):\s*var\((--colors-[\w-]+),\s*(.*?)\);", block)
    assert len(rows) == len(served), "every served token has a fallback in the block"
    for name, token, fallback in rows:
        want = served[token]
        assert fallback.upper() == (want.upper() if len(want) == 7 else as_rgba(want).upper()), (name, fallback, want)


def test_the_colors_looks_resolve_on_either_side_and_follow_the_system():
    for mode, spec in K.COLORS.items():
        for side in ("light", "dark"):
            got = K.resolve(f"colors:{mode}", side, colour="#FF5C5C")
            assert got["theme"] == f"colors:{mode}:FF5C5C:{side}" and got["skin"] == spec["skin"], got
            assert got["auto"] is None
        follow = K.resolve(f"colors:{mode}", "", colour="#3FB950", pick=True)
        assert follow["mode"] == "", "a Colors look has both sides of its own: nothing to pin"
        assert follow["skin"] == ("glass:auto" if mode == "glass" else "none")
        assert {s: v["theme"] for s, v in follow["auto"].items()} == {
            "light": f"colors:{mode}:3FB950:light", "dark": f"colors:{mode}:3FB950:dark"}
        assert K.look_of(f"colors:{mode}:AABBCC:dark", "none") == f"colors:{mode}"
    genre = next(g for g in K.genres("#4DA3FF") if g["name"] == "colors")
    assert [l["value"] for l in genre["looks"]] == ["colors:matte", "colors:glass", "colors:cyber"]
    assert genre["looks"][1]["sides"]["light"]["base"] == "colors:glass:4DA3FF:light"
    plain = next(g for g in K.genres() if g["name"] == "plain")
    assert not {l["value"] for l in plain["looks"]} & {f"palette:{n}" for n in K.PLAIN_HIDDEN}
    assert set(K.COLOUR_PRESETS) == K.PLAIN_HIDDEN and all(T.HEX6.match(c) for c in K.COLOUR_PRESETS.values())
    assert K.resolve("colors:neon", "dark")["theme"] == "none", "a mode nothing knows is the system's colours"


def test_a_flipped_palette_is_the_other_side_of_every_built_in():
    for t in T.list_themes():
        if t.name == "none":
            assert T.flip(t) is t
            continue
        f = T.flip(t)
        assert f.name == f"flip:{t.name}" and f.light != t.light, t.name
        T.check(f)
        assert T.get(f.name).ground == f.ground and T.flip(f).name == t.name


def test_the_server_writes_the_colour_and_serves_the_glass_tokens(fleet_home):
    from agentdata import config as C
    server, token, port = _serve()
    try:
        status, got = _post(port, token, {"look": "colors:glass", "mode": "dark"})
        assert status == 200 and got["ok"] and got["look"] == "colors:glass" and got["mode"] == "dark", got
        assert got["theme"] == f"colors:glass:{K.DEFAULT_COLOUR[1:]}:dark" and got["skin"] == "glass:hue"
        assert "--colors-mesh-1" in got["css"] and got["colour"] == K.DEFAULT_COLOUR
        status, got = _post(port, token, {"colour": "#ff5c5c"})
        assert status == 200 and got["theme"] == "colors:glass:FF5C5C:dark", got
        t = T.get("colors:glass:FF5C5C:dark")
        assert got["css"]["--bg"] == t.ground and got["css"]["--colors-highlighter"] == K.colors_glass(t)["inks"]["highlighter"]
        assert C.load()["theme"] == {**C.load()["theme"], "colour": "#FF5C5C", "look": "colors:glass",
                                     "mode": "dark", "skin": "glass:hue", "default": "colors:glass:FF5C5C:dark"}
        status, got = _post(port, token, {"colour": "red"})
        assert status >= 400 and got["ok"] is False and got["code"] == "bad_request", (status, got)
        status, got = _post(port, token, {"look": "colors:cyber", "mode": ""})
        assert got["skin"] == "none" and got["theme"] == "colors:cyber:FF5C5C:dark" and got["auto"]["light"]["theme"] == "colors:cyber:FF5C5C:light"
        assert "--colors-mesh-1" not in got["css"], "the tokens ride with the glass mode only"
        themes = _get(port, token, "/api/themes")
        assert themes["colour"] == "#FF5C5C" and themes["colour_presets"] == K.COLOUR_PRESETS
        assert themes["genres"] == K.genres("#FF5C5C")
    finally:
        _stop(server)


# ================================================================================ with a browser


@pytest.mark.browser
def test_the_settings_page_shows_the_colour_for_a_colors_look_and_a_preset_seeds_it(fleet_home, tmp_path, desk_browser):
    from test_fleet_settings_page import _repos, _settings
    _repos(tmp_path, "alpha")
    (tmp_path / "cfg.json").write_text(json.dumps({"theme": {"look": "colors:glass", "mode": "dark",
                                                              "colour": "#3A7BD5"}}), encoding="utf-8")
    server, token, port = _serve()
    try:
        browser, page, errors = _settings(desk_browser, port, token)
        page.wait_for_function("() => document.getElementById('look').value === 'colors:glass'", timeout=10000)
        try:
            page.wait_for_function("() => document.body.dataset.skinVariant === 'hue'", timeout=10000)
        except Exception as e:
            raise AssertionError(page.evaluate("""() => ({ skin: document.body.dataset.skin, variant: document.body.dataset.skinVariant,
                now: window.themeNow, bg: document.documentElement.style.getPropertyValue('--bg') })""")) from e
        assert page.evaluate("() => !document.getElementById('colour-row').hidden")
        assert page.evaluate("() => document.getElementById('colour-hex').value") == "#3A7BD5"
        want = T.get("colors:glass:3FB950:dark")
        with page.expect_response(lambda r: r.request.method == "POST" and "/api/theme" in r.url):
            page.click("#colour-presets button[data-colour='#3FB950']")
        page.wait_for_function("bg => document.documentElement.style.getPropertyValue('--bg') === bg", arg=want.ground, timeout=10000)
        assert page.evaluate("() => document.getElementById('colour').value").upper() == "#3FB950"
        assert page.evaluate("() => getComputedStyle(document.body).getPropertyValue('--glass-mesh-1').trim()") \
            == K.colors_css(want)["--colors-mesh-1"], "the hue block reads the served tokens"
        assert S.theme_state()["colour"] == "#3FB950"
        page.select_option("#look", "palette:sand")
        page.wait_for_function("() => document.getElementById('colour-row').hidden", timeout=10000)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
