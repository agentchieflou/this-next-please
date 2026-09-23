"""The tier boundaries are the operator's to set (issue #235, slice F of #229).

plan-panes §The pane drew three widths -- a 48px rail, compact from 160px, full from 360px, with
8px of slack between the last two -- and called them *starting values, which the laptop sets in F*.
They were constants in app.js. They are settings now, `fleet.tiers.*` in config.json, set on the
settings page after trying them on the real monitors, with CI's numbers as the defaults.
`docs/desk-window.md` §The tiers records the laptop's beside CI's. What is asserted here:

* the defaults are CI's, everywhere they are written down, and a desk on them draws exactly what it
  drew before -- nothing written on the root for them;
* a value outside its bounds, or four that do not go together, is refused with the fix in the hint,
  and the file does not move; two that only go together can be written together;
* a four in the file that does not go together (a hand edit) is drawn at the defaults and said;
* the page draws the configured numbers: the rail's width, the tier at a width, and the floor a
  gutter settles on -- and a change to the file reaches an open desk with no reload and no write;
* the settings page puts them under Appearance and says a refusal where it happened.
"""
from __future__ import annotations
import json
import os
import re

import pytest

from agentdata import config as C
from agentdata.fleet import registry, serve as S, settings as SET

from test_fleet_column import _until
from test_fleet_desk_browser import launch_chromium
from test_fleet_gutters import _drag_gutter, _page, _read_settled, _repos, _serve, _stop
from test_fleet_gutters import _own_desk_globals  # noqa: F401 - the desk's globals, autouse
from test_fleet_probe import cli, table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
DESK_WINDOW = os.path.join(ROOT, "docs", "desk-window.md")

#: CI's numbers: what every browser test in the suite draws against, and the defaults.
CI = {"rail": 48, "compact": 160, "full": 360, "slack": 8}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _set(**values) -> dict:
    """The `fleet.tiers` block of a config, from `rail=40, compact=200, ...`."""
    return {"fleet": {"tiers": {f"{name}_px": px for name, px in values.items()}}}


def _desk_window_tiers() -> dict:
    """The numbers' table in `docs/desk-window.md` §The tiers -- the one with a *Setting* column --
    as {tier: {column: cell}}."""
    doc = open(DESK_WINDOW, encoding="utf-8").read()
    body = doc.split("\n## The tiers\n", 1)
    assert len(body) == 2, "no section '## The tiers' in docs/desk-window.md"
    out, header = {}, None
    for line in body[1].split("\n## ", 1)[0].splitlines():
        if not line.startswith("| "):
            if header is not None and out:
                break                                  # the table has ended
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            if "Setting" in cells:
                header = cells
            continue
        if set("".join(cells)) <= set("- :"):
            continue
        out[cells[0].strip("*")] = dict(zip(header[1:], cells[1:]))
    assert header, "no table with a Setting column under §The tiers"
    return out


# ------------------------------------------------------------------------------ the defaults


def test_the_defaults_are_cis_wherever_they_are_written_down(fleet_home):
    """One set of numbers, in five places that each need it: the settings table, the page's own
    constants, the stylesheet's root, what the server sends, and the doc's CI column."""
    assert SET.TIER_DEFAULTS == CI
    assert SET.tiers({}) == {**CI, "invalid": ""}
    assert S.theme_state()["tiers"] == {**CI, "invalid": ""}, "an unset file draws CI's numbers"

    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    for line in ("var TIER_COMPACT_FROM = 160;", "var TIER_FULL_FROM = 360;",
                 "var TIER_SLACK = 8;", "var RAIL_PX = 48;"):
        assert line in js, line
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    assert ":root { --rail: 48px; --compact-from: 160px; }" in css
    # The two the stylesheet needs are read from the root and nowhere else.
    assert "flex: 0 0 var(--rail); min-width: 0; min-height: 0;" in css
    assert ".tile.is-solo { flex: var(--w, 1) 1 0; min-width: var(--compact-from); }" in css
    assert not re.search(r"min-width:\s*160px", css), "a compact floor the setting does not move"

    rows = _desk_window_tiers()
    assert set(rows) == {"rail", "compact from", "full from", "slack"}, rows
    ci_column = next(c for c in next(iter(rows.values())) if c.startswith("CI"))
    laptop = next(c for c in next(iter(rows.values())) if c.startswith("Laptop"))
    names = {"rail": "rail", "compact from": "compact", "full from": "full", "slack": "slack"}
    for row, name in names.items():
        assert rows[row][ci_column] == f"{CI[name]} px", (row, rows[row])
        # The laptop's is a number the runbook's P16 pasted back, or it says what it is.
        cell = rows[row][laptop].strip("_* ")
        assert cell == "not yet measured" or re.fullmatch(r"\d+ px", cell), (row, cell)
        key = SET.TIER_KEYS[name]
        bounds = f"{SET.EDITABLE[key]['min']}–{SET.EDITABLE[key]['max']}"
        assert f"`{key}`, {bounds}" == rows[row]["Setting"], (row, rows[row])


def test_every_tier_key_is_on_the_page_under_appearance_with_its_bounds(fleet_home):
    rows = {r["key"]: r for r in S.settings_snapshot()["editable"]}
    for name, key in SET.TIER_KEYS.items():
        row = rows[key]
        assert row["section"] == "appearance" and row["type"] == "int", row
        assert row["default"] == CI[name] and row["scope"] == SET.NOW, row
        assert row["min"] <= CI[name] <= row["max"], row
    assert rows["fleet.approval_timeout"]["section"] == "copilot"
    assert "min" not in rows["fleet.approval_timeout"], "a bound nobody set"


# ------------------------------------------------------------------------------ the refusals


@pytest.mark.parametrize("key,value,code", [
    ("fleet.tiers.rail_px", 20, "out_of_range"),
    ("fleet.tiers.rail_px", 120, "out_of_range"),
    ("fleet.tiers.compact_px", 100, "out_of_range"),
    ("fleet.tiers.full_px", 2000, "out_of_range"),
    ("fleet.tiers.slack_px", 30, "out_of_range"),
    ("fleet.tiers.full_px", "wide", "bad_type"),
    ("fleet.tiers.slack_px", "", "bad_type"),
])
def test_a_value_outside_its_bounds_is_refused_with_a_hint(fleet_home, key, value, code):
    C.save(_set(compact=180))
    before = open(C.path(), "rb").read()
    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"set": [{"key": key, "value": value}]})
    assert e.value.code == code, e.value.msg
    assert e.value.hint, f"{key}={value!r} was refused with no hint"
    assert open(C.path(), "rb").read() == before, "a refused value still changed the file"


@pytest.mark.parametrize("have,key,value,fix", [
    # A compact pane within 64px of the rail is a wide rail.
    ({"rail": 96}, "fleet.tiers.compact_px", 150, "160px or more"),
    ({"compact": 150}, "fleet.tiers.rail_px", 96, "160px or more"),
    # The compact tier needs room to land in: full at least 80px past it.
    ({}, "fleet.tiers.full_px", 220, "240px or more"),
    ({}, "fleet.tiers.compact_px", 300, "set full from to 380px or more first"),
])
def test_boundaries_that_do_not_go_together_are_refused_with_the_fix(fleet_home, have, key, value,
                                                                      fix):
    C.save(_set(**have) if have else {"fleet": {"max_restarts": 1}})
    before = open(C.path(), "rb").read()
    with pytest.raises(S.ServeError) as e:
        S.act("settings", {"set": [{"key": key, "value": value}]})
    assert e.value.code == "bad_tiers", e.value.msg
    assert fix in e.value.hint, (e.value.msg, e.value.hint)
    assert open(C.path(), "rb").read() == before, "a refused four still changed the file"


def test_two_boundaries_that_only_go_together_are_written_together(fleet_home):
    """Compact from 400 needs full from 480 or more, so on its own it is refused; in one write with
    full from 600 it is not. Written one at a time, the order the hint names works too."""
    C.save({"fleet": {}})
    with pytest.raises(S.ServeError):
        S.act("settings", {"set": [{"key": "fleet.tiers.compact_px", "value": 400}]})
    answer = S.act("settings", {"set": [{"key": "fleet.tiers.compact_px", "value": 400},
                                        {"key": "fleet.tiers.full_px", "value": 600}]})
    assert answer["tiers"] == {"rail": 48, "compact": 400, "full": 600, "slack": 8, "invalid": ""}
    assert answer["current"]["fleet.tiers.full_px"] == 600

    C.save({"fleet": {}})
    S.act("settings", {"set": [{"key": "fleet.tiers.full_px", "value": 600}]})
    S.act("settings", {"set": [{"key": "fleet.tiers.compact_px", "value": 400}]})
    assert SET.tiers(C.load())["compact"] == 400


def test_an_unrelated_write_is_not_refused_over_a_four_already_in_the_file(fleet_home):
    """The cross-key check runs on the keys a write touches. A hand-edited four already in the file
    is the desk's to say (below), not a reason to refuse the approval window."""
    C.save(_set(compact=400))
    S.act("settings", {"set": [{"key": "fleet.approval_timeout", "value": 90}]})
    assert C.get(C.load(), "fleet.approval_timeout") == 90


def test_a_four_in_the_file_that_does_not_go_together_is_drawn_at_the_defaults_and_said(fleet_home):
    C.save(_set(compact=400))                      # full from is still 360
    got = SET.tiers(C.load())
    assert {k: got[k] for k in CI} == CI, "a four that does not go together is not drawn"
    assert "full from 360px" in got["invalid"] and "compact from 400px" in got["invalid"], got
    assert S.theme_state()["tiers"] == got
    assert S.settings_snapshot()["tiers"] == got
    # And a value of the wrong type in the file, which no page wrote.
    C.save({"fleet": {"tiers": {"rail_px": "wide"}}})
    assert SET.tiers(C.load())["invalid"].startswith("fleet.tiers.rail_px"), SET.tiers(C.load())


def test_ad_fleet_engines_prints_the_tiers_in_effect(fleet_home):
    """The laptop's numbers come back in the same paste as the engine rows (runbook P16)."""
    C.save(_set(compact=180, full=420))
    rc, out = cli("engines")
    assert rc == 0 and "tiers_invalid: \"\"" in out, out
    rows = {r["tier"]: r for r in table(out, "tiers")}
    assert rows["compact"] == {"tier": "compact", "px": "180", "default": "160", "set": "true",
                               "key": "fleet.tiers.compact_px"}, rows
    assert rows["full"]["px"] == "420" and rows["rail"]["set"] == "false", rows
    assert rows["rail"]["px"] == "48" and rows["slack"]["px"] == "8", rows


# ---------------------------------------------------------------------------------- the page


#: What the page is drawing with: its own constants, the root's two properties, and every pane.
DRAWN = """() => ({
  rail: RAIL_PX, compact: TIER_COMPACT_FROM, full: TIER_FULL_FROM, slack: TIER_SLACK,
  railVar: document.documentElement.style.getPropertyValue('--rail'),
  compactVar: document.documentElement.style.getPropertyValue('--compact-from'),
  panes: Object.fromEntries([...document.querySelectorAll('#grid .tile')].map(t =>
    [t.dataset.repo, { tier: t.dataset.tier || '', wide: t.classList.contains('is-solo'),
                       width: t.getBoundingClientRect().width }])),
})"""


@pytest.mark.browser
def test_the_desk_draws_the_configured_tiers_and_follows_a_change_without_a_reload(fleet_home,
                                                                                   tmp_path):
    """Rail 40, compact from 200, full from 500. Three even panes on a 1400px window are about
    440px each: full at CI's numbers, compact at these. The rail is 40px wide, a gutter pulled
    under the compact minimum settles at 200 and not 160, and the file put back to the defaults
    reaches the open desk on its next tick -- no reload, and nothing written by the page."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma", "delta"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    S.update_window("main", open="alpha", widths={"alpha": 1, "beta": 1, "gamma": 1, "delta": 0})
    C.save(_set(rail=40, compact=200, full=500, slack=8))

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, posts = _page(browser, port, token, wide=3)
            page.wait_for_function("() => TIER_FULL_FROM === 500", timeout=10000)
            _read_settled(page)
            configured = page.evaluate(DRAWN)

            # A gutter pulled well under the compact minimum lands on the configured one.
            posts.clear()
            _drag_gutter(page, "alpha", 160 - configured["panes"]["alpha"]["width"], steps=16)
            page.wait_for_function("() => windowWrites === 0 && !gutterHeld", timeout=8000)
            landed = _read_settled(page)

            # The file goes back to the defaults; the open desk follows it on the next tick.
            page.evaluate("() => { window.__sameDocument = true; }")
            posts.clear()
            C.save({"fleet": {}})
            page.wait_for_function("() => TIER_FULL_FROM === 360 && RAIL_PX === 48", timeout=10000)
            page.wait_for_function(
                "() => document.querySelector('.tile[data-repo=\"delta\"]')"
                ".getBoundingClientRect().width === 48", timeout=8000)
            _read_settled(page)
            defaults = page.evaluate(DRAWN)
            same = page.evaluate("() => window.__sameDocument === true")
            written = [url for url, body in posts
                       if "/api/arrange" in url or ("/api/window" in url and "widths" in body)]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert {k: configured[k] for k in CI} == {"rail": 40, "compact": 200, "full": 500, "slack": 8}
    assert (configured["railVar"], configured["compactVar"]) == ("40px", "200px"), configured
    panes = configured["panes"]
    assert round(panes["delta"]["width"]) == 40 and panes["delta"]["tier"] == "rail", panes
    for name in ("alpha", "beta", "gamma"):
        assert 400 < panes[name]["width"] < 500, (name, panes[name])
        assert panes[name]["tier"] == "compact", (name, panes[name], "full at CI's numbers")

    assert abs(landed["alpha"]["width"] - 200) <= 1.5, landed["alpha"]
    assert landed["alpha"]["tier"] == "compact" and landed["alpha"]["wide"], landed["alpha"]

    assert same, "the desk reloaded to take the change"
    assert written == [], f"a change of tiers is drawn, never written: {written}"
    assert {k: defaults[k] for k in CI} == CI, defaults
    assert (defaults["railVar"], defaults["compactVar"]) == ("", ""), \
        "a desk back on the defaults still carries them on its root"
    back = defaults["panes"]
    assert round(back["delta"]["width"]) == 48, back
    # alpha kept its 200px; the widest of the other two is past 360 now, which is full again.
    assert back["alpha"]["tier"] == "compact", back
    assert max((back[n]["width"], back[n]["tier"]) for n in ("beta", "gamma"))[1] == "full", back


@pytest.mark.browser
def test_a_desk_on_the_defaults_writes_nothing_for_the_tiers(fleet_home, tmp_path):
    """The root carries no tier property on CI's numbers, and a file that sets CI's numbers in so
    many words draws the same desk: nothing about the defaults is a write."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    names = ["alpha", "beta", "gamma"]
    _repos(tmp_path, names)
    S.arrange(order=names)
    C.save(_set(**CI))

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _posts = _page(browser, port, token, wide=1)
            drawn = page.evaluate(DRAWN)
            style = page.evaluate("() => document.documentElement.getAttribute('style') || ''")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert {k: drawn[k] for k in CI} == CI, drawn
    assert "--rail" not in style and "--compact-from" not in style, style


@pytest.mark.browser
def test_the_settings_page_sets_a_tier_and_refuses_one_that_does_not_fit(fleet_home, tmp_path):
    """Under Appearance, with the server's bounds on the box, and a refusal said on the box that
    was refused -- the file untouched -- while a value that fits is saved and read back."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, ["alpha"])
    C.save({"fleet": {}})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.querySelectorAll('#tierrows .setrow').length === 4", timeout=15000)
            section = page.evaluate("""() => document.getElementById('cfg-fleet-tiers-full_px')
                                               .closest('section').querySelector('h2').textContent""")
            bounds = page.evaluate("""() => { const el = document.getElementById('cfg-fleet-tiers-full_px');
                                              return [el.min, el.max, el.value]; }""")
            before = open(C.path(), "rb").read()

            box = page.locator("#cfg-fleet-tiers-full_px")
            box.fill("220")
            box.dispatch_event("change")
            page.wait_for_function(
                "() => document.getElementById('cfg-fleet-tiers-full_px').classList.contains('bad')",
                timeout=8000)
            said = box.get_attribute("title") or ""
            refused_file = open(C.path(), "rb").read()

            box.fill("420")
            box.dispatch_event("change")
            _until(lambda: C.get(C.load(), "fleet.tiers.full_px") == 420)
            page.wait_for_function(
                "() => !document.getElementById('cfg-fleet-tiers-full_px').classList.contains('bad')",
                timeout=8000)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    assert section == "Appearance", section
    assert bounds == ["200", "1600", "360"], bounds
    assert "240px or more" in said, said
    assert refused_file == before, "a refused tier still changed the file"
    assert json.loads(open(C.path(), encoding="utf-8").read())["fleet"]["tiers"] == {"full_px": 420}
