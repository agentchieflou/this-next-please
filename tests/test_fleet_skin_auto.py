"""`<skin>:auto`: a skin with a light and a dark variant follows the system's appearance (#342).

What is saved, what `theme_state` serves for each side, and what the served page carries so its
first frame is right in either appearance. The browser half (Playwright's `color_scheme`, a live
`emulate_media` switch, and the idle desk after it) is folded into
`tests/test_fleet_settings_page.py::test_a_palette_set_elsewhere_repaints_this_page` (decision 13).
"""
from __future__ import annotations

import json
import re
import urllib.request

from agentdata import config as C
from agentdata.fleet import serve as S
from agentdata.fleet import skins as K

from test_fleet_ink import _serve, _stop, fleet_home  # noqa: F401

PAIRS = {"notebook": ("light", "dark"), "glass": ("frost", "smoke"),
         "graph": ("engineering", "blueprint"), "farmstead": ("daytime", "cave")}


def _post(port, token, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/theme?t={token}",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def _page(port, token, name="/"):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{name}?t={token}", timeout=10) as r:
        return r.read().decode("utf-8")


def _choose(skin):
    cfg = C.load()
    cfg.setdefault("theme", {})["skin"] = skin
    C.save(cfg)


def test_posting_auto_saves_it_verbatim_and_gives_the_terminal_the_default_variants_palette(fleet_home):
    server, token, port = _serve()
    try:
        status, res = _post(port, token, {"skin": "notebook:auto"})
        assert status == 200
        cfg = C.load()["theme"]
        assert cfg["skin"] == "notebook:auto" and cfg["default"] == "eye-relief-day", cfg
        assert res["skin"] == "notebook:auto" and set(res["auto"]) == {"light", "dark"}, res

        # a skin with one appearance cannot follow: its default variant, as an unknown variant is
        _post(port, token, {"skin": "legalpad:auto"})
        cfg = C.load()["theme"]
        assert cfg["skin"] == "legalpad:canary" and cfg["default"] == "eye-relief-day", cfg

        # a fixed choice saves exactly as before
        _post(port, token, {"skin": "notebook:dark"})
        assert C.load()["theme"] == {"skin": "notebook:dark", "default": "dark"}
        _post(port, token, {"skin": "glass"})
        assert C.load()["theme"] == {"skin": "glass:smoke", "default": "dark"}
    finally:
        _stop(server)


def test_each_side_of_auto_serves_exactly_what_choosing_that_variant_serves(fleet_home):
    for family, (light, dark) in PAIRS.items():
        _choose(f"{family}:auto")
        ts = S.theme_state()
        assert ts["skin"] == f"{family}:auto" and ts["skin_variant"] == "auto", ts
        default = K.get_skin(family)
        assert ts["theme"] == default["base"], "the terminal gets the default variant's palette"
        for side, variant in (("light", light), ("dark", dark)):
            _choose(f"{family}:{variant}")
            fixed = S.theme_state()
            got = ts["auto"][side]
            assert got == {"variant": variant, "skin": f"{family}:{variant}", "theme": fixed["theme"],
                           "css": fixed["css"]}, (family, side)
            assert any(k.startswith("--on-") for k in got["css"]), "#327's --on-* tokens come with it"
            assert any(k.endswith("-text") for k in got["css"]), "#328's -text tokens come with it"
        assert K.get_skin(f"{family}:{light}")["base"] != K.get_skin(f"{family}:{dark}")["base"], family


def test_a_fixed_choice_serves_no_auto_and_nothing_else_changes(fleet_home):
    _choose("notebook:dark")
    ts = S.theme_state()
    assert "auto" not in ts and ts["skin"] == "notebook:dark"
    worn = S.page_theme(ts, "tok", desk=True, gate_on=False)
    assert "data-skin-auto" not in worn["body"] and "<style" not in worn["link"]


def test_the_served_page_carries_both_sides_and_the_browser_picks(fleet_home):
    """#345's first frame, in either appearance: the tokens by `prefers-color-scheme`, and the two
    variants for common.js to pick from before the page first paints."""
    _choose("notebook:auto")
    ts = S.theme_state()
    server, token, port = _serve()
    try:
        for name in ("/", "/settings"):
            html = _page(port, token, name)
            assert '<html lang="en" data-theme="custom"' in html and "--bg:" not in \
                re.search(r"<html[^>]*>", html).group(0), "no fixed side inline"
            sheet = re.search(r'<style data-skin-auto="true">(.*?)</style>', html).group(1)
            light, _, dark = sheet.partition("@media (prefers-color-scheme: dark)")
            assert f"--bg:{ts['auto']['light']['css']['--bg']}" in light
            assert f"--bg:{ts['auto']['dark']['css']['--bg']}" in dark
            assert f"--done-text:{ts['auto']['dark']['css']['--done-text']}" in dark
            body = re.search(r"<body[^>]*>", html).group(0)
            assert 'data-skin="notebook"' in body and 'data-skin-auto="light dark"' in body, body
            assert 'data-skin-variant="light"' in body, "never `auto`, which no stylesheet knows"
            assert html.index("data-skin-auto") < html.index('<link rel="stylesheet" data-skin="true"')
    finally:
        _stop(server)


def test_themes_lists_the_pair_only_where_a_skin_has_one(fleet_home):
    listed = {k["name"]: k for k in K.list_skins()}
    for family, (light, dark) in PAIRS.items():
        assert listed[family]["auto"] == {"light": light, "dark": dark}
        # each side is a real variant with a light and a dark palette respectively
        assert {light, dark} <= {v["name"] for v in listed[family]["variants"]}
    for family in ("legalpad", "napkin", "voxel", "none"):
        assert "auto" not in listed[family], family
