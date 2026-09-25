"""The chosen palette, skin and tiers in the served page (#345): `serve.page_theme` and `_page`.

The browser half -- what is painted, frame by frame -- is `tests/test_fleet_theme_switch.py`.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import urllib.request

from agentdata import textio
from agentdata import theme as T
from agentdata.fleet import serve as S
from agentdata.fleet import settings as SET

from test_fleet_ink import _serve, _stop, fleet_home  # noqa: F401

TOKEN = "tok"
DEFAULT_TIERS = dict(SET.TIER_DEFAULTS, invalid="")


def _ts(theme="none", skin="none", css=None, tiers=None):
    return {"theme": theme, "skin": skin, "css": css or {}, "accents": {},
            "tiers": tiers or DEFAULT_TIERS}


def test_no_skin_no_palette_default_tiers_serves_nothing():
    for desk in (True, False):
        assert S.page_theme(_ts(), TOKEN, desk=desk, gate_on=desk) == \
            {"html": "", "link": "", "body_class": "", "body": ""}


def test_a_palette_alone_is_the_root_style_applytheme_writes():
    css = T.to_css(T.get("dark"))
    got = S.page_theme(_ts("dark", css=css), TOKEN, desk=True, gate_on=False)
    want = ";".join(f"{k}:{v}" for k, v in css.items())
    assert got["html"] == f' data-theme="custom" style="{want}"'
    assert " " not in want and got["link"] == got["body"] == got["body_class"] == ""


def test_a_palette_named_none_is_no_palette():
    css = T.to_css(T.get("dark"))
    assert S.page_theme(_ts("none", css=css), TOKEN, desk=True, gate_on=False)["html"] == ""


def test_a_skin_with_its_variant():
    got = S.page_theme(_ts("dark", "farmstead:daytime", T.to_css(T.get("dark"))), TOKEN,
                       desk=False, gate_on=False)
    assert got["link"] == ('<link rel="stylesheet" data-skin="true" '
                           'href="/static/skins/farmstead/skin.css?t=tok">')
    assert got["body"] == ' data-skin="farmstead" data-skin-variant="daytime"'
    assert got["body_class"] == "ink-off"


def test_the_desk_is_served_ink_off_even_where_the_gate_is_on():
    """The epic's progressive decision: legible until the layer draws, then ink.js lifts it."""
    for gate_on in (True, False):
        got = S.page_theme(_ts(skin="voxel:nether"), TOKEN, desk=True, gate_on=gate_on)
        assert got["body_class"] == "ink-off", gate_on


def test_default_tiers_carry_no_data_tiers():
    assert "data-tiers" not in S.page_theme(_ts(), TOKEN, desk=True, gate_on=False)["html"]


def test_custom_tiers_are_on_the_desk_only_and_as_applytiers_writes_them():
    tiers = dict(DEFAULT_TIERS, rail=60, full=480)
    got = S.page_theme(_ts(tiers=tiers), TOKEN, desk=True, gate_on=False)
    # No palette: a style with no `data-theme`. `--compact-from` only when compact moved.
    assert got["html"] == ' data-tiers="60 160 480 8" style="--rail:60px"'
    tiers = dict(DEFAULT_TIERS, compact=200)
    got = S.page_theme(_ts(tiers=tiers), TOKEN, desk=True, gate_on=False)
    assert got["html"] == ' data-tiers="48 200 360 8" style="--compact-from:200px"'
    assert S.page_theme(_ts(tiers=tiers), TOKEN, desk=False, gate_on=False)["html"] == ""


def test_a_value_that_is_not_a_hex_colour_or_a_token_is_dropped():
    css = {"--bg": "#101010", "--text": "red;background:url(x)", "--panel": "#12", "Bad": "#fff",
           "--line": "#abcdef80"}
    got = S.page_theme(_ts("dark", css=css), TOKEN, desk=False, gate_on=False)
    assert got["html"] == ' data-theme="custom" style="--bg:#101010;--line:#abcdef80"'


def test_a_bad_family_serves_no_skin_and_a_bad_variant_is_dropped():
    for skin in ('"><script>', "Voxel", "../x"):
        got = S.page_theme(_ts(skin=skin), TOKEN, desk=True, gate_on=True)
        assert got["link"] == got["body"] == got["body_class"] == "", skin
    got = S.page_theme(_ts(skin='voxel:"x'), TOKEN, desk=True, gate_on=True)
    assert got["body"] == ' data-skin="voxel"'


def test_the_example_skin_is_worn_as_applyskin_splits_it():
    """`example` is a skin module skins.py does not offer: `applySkin` still wears it."""
    got = S.page_theme(_ts(skin="example"), TOKEN, desk=True, gate_on=True)
    assert got["body"] == ' data-skin="example"'
    assert "/static/skins/example/skin.css?t=tok" in got["link"]


def test_the_served_tokens_are_the_ones_applytheme_writes():
    """`to_css`, `applyTheme`'s list and what the page is served are one set: a new token (#327,
    #328) that reaches one and not the others fails here."""
    common = open(os.path.join(S.STATIC, "common.js"), encoding="utf-8").read()
    body = re.search(r"function applyTheme\(.*?var tokens = \[(.*?)\];", common, re.S).group(1)
    tokens = set(re.findall(r'"(--[a-z0-9-]+)"', body))
    seen = 0
    for name in T.BUILTINS:
        css = T.to_css(T.get(name))
        if not css:
            continue
        seen += 1
        assert set(css) == tokens, name
        style = re.search(r'style="([^"]*)"',
                          S.page_theme(_ts(name, css=css), TOKEN, desk=False, gate_on=False)["html"])
        assert {d.split(":")[0] for d in style.group(1).split(";")} == tokens, name
    assert seen > 3


def _get(port, path, token, gz=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}?t={token}",
                                 headers={"Accept-Encoding": "gzip"} if gz else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return gzip.decompress(raw) if r.headers.get("Content-Encoding") == "gzip" else raw


def test_every_page_but_the_probe_carries_the_theme(fleet_home):
    (fleet_home.parent / "cfg.json").write_text(
        json.dumps({"theme": {"skin": "farmstead:daytime"}}), encoding="utf-8")
    ts = S.theme_state()
    server, token, port = _serve()
    try:
        for route, name in S.PAGES.items():
            html = _get(port, route, token).decode("utf-8")
            body = re.search(r"<body[^>]*>", html).group(0)
            if name == "probe.html":
                assert "data-skin" not in html and "data-theme" not in html, route
                continue
            assert re.search(r'<html lang="en" data-theme="custom" style="--bg:', html), route
            assert f'--bg:{ts["css"]["--bg"]};' in html, route
            assert f'href="/static/skins/farmstead/skin.css?t={token}"></head>' in html, route
            assert 'data-skin="farmstead" data-skin-variant="daytime"' in body, route
            assert re.search(r'class="([^"]*\b)?ink-off"', body), route
        settings = re.search(r"<body[^>]*>", _get(port, "/settings", token).decode()).group(0)
        assert settings.startswith('<body class="settings-page ink-off" data-skin="farmstead"'), settings
        desk = re.search(r"<body[^>]*>", _get(port, "/", token).decode()).group(0)
        assert re.fullmatch(r'<body class="ink-off" data-skin="farmstead" data-skin-variant="daytime" '
                            r'data-ink-shell="[a-z]+" data-ink-probe="[a-z]+" data-ink-skins="[a-z ]+">',
                            desk), desk
    finally:
        _stop(server)


def test_with_nothing_chosen_the_pages_are_the_files_as_they_were(fleet_home):
    server, token, port = _serve()
    try:
        for route, name in S.PAGES.items():
            html = _get(port, route, token).decode("utf-8")
            raw = textio.read_text(os.path.join(S.STATIC, name))   # as `_page` reads it: CRLF kept
            for asset in S.ASSETS:
                raw = raw.replace(f'"/static/{asset}"', f'"/static/{asset}?t={token}"')
            if name == "index.html":
                html = re.sub(r"<body [^>]*>", "<body>", html, count=1)
            elif name in S.INKED_PAGES:
                # /map (#405): its own `ink-off` kept, then the gate's facts, exactly as the desk's.
                html = re.sub(r'(<body class="ink-off") data-ink-shell="[a-z]+" '
                              r'data-ink-probe="[a-z]+" data-ink-skins="[a-z ]*">', r"\1>",
                              html, count=1)
            assert html == raw, route
    finally:
        _stop(server)


def test_two_configs_are_two_gzipped_desks(fleet_home):
    cfg = fleet_home.parent / "cfg.json"
    server, token, port = _serve()
    try:
        cfg.write_text(json.dumps({"theme": {"skin": "voxel:nether"}}), encoding="utf-8")
        nether = _get(port, "/", token, gz=True)
        cfg.write_text(json.dumps({"theme": {"skin": "farmstead:daytime"}}), encoding="utf-8")
        daytime = _get(port, "/", token, gz=True)
        assert nether != daytime
        assert b'data-skin="voxel"' in nether and b'data-skin="farmstead"' in daytime
    finally:
        _stop(server)
