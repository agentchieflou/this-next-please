"""While measuring is on, each desk and /settings load posts one record at pagehide (#351).

* The server serves `data-measure="loads"` on `<html>` for `/` and `/settings` only while
  `fleet.loads.enabled` is on, never on `/probe`, and the flag is in the gzip entry's key.
* `common.js` reads that attribute at boot; with it absent nothing registers, observes or touches
  storage. With it on, one `pagehide` beacon per document to `/api/load`.
* /settings leaves `fleet.load.from` in sessionStorage as it goes, so the desk it opens files its
  record as `from=settings`; a cold open is `from=""`.
* The ink's first frame is read from the layer's own counter, never from an ink-module change.

One browser for the module; a server per test. Every wait is on a condition: a request caught with
`expect_request`, a page function, or `loads.load()` polled against a deadline.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request

import pytest

from agentdata import config as C
from agentdata.fleet import loads as L
from agentdata.fleet import serve as S

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _desk_of, _serve, _stop, fleet_home  # noqa: F401
from test_fleet_loads import cli, table

SKIN = "voxel"
MEASURE = re.compile(r'<html lang="en"[^>]* data-measure="loads">')


def _switch(on: bool, skin: str = SKIN):
    cfg = {"theme": {"skin": skin}}
    if on:
        cfg["fleet"] = {"loads": {"enabled": True}}
    C.save(cfg)


def _until(read, n: int, deadline_s: float = 10.0) -> list:
    """`read()`, once it holds at least `n` items or the deadline has passed."""
    end = time.monotonic() + deadline_s
    while True:
        got = list(read())
        if len(got) >= n or time.monotonic() > end:
            return got
        time.sleep(0.02)


def _records(n: int) -> list[dict]:
    """The kept records, once there are at least `n` of them."""
    return _until(L.load, n)


# ---------------------------------------------------------------------------------- the markup


def _get(port, path, token, gz=False):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}?t={token}",
                                 headers={"Accept-Encoding": "gzip"} if gz else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def test_the_pages_are_told_to_measure_only_while_the_switch_is_on(fleet_home):
    _switch(False)
    server, token, port = _serve()
    try:
        off = {p: _get(port, p, token).decode("utf-8") for p in ("/", "/settings", "/probe")}
        off_gz = _get(port, "/", token, gz=True)
        assert not any("data-measure" in html for html in off.values())
        _switch(True)
        on = {p: _get(port, p, token).decode("utf-8") for p in ("/", "/settings", "/probe")}
        on_gz = _get(port, "/", token, gz=True)
    finally:
        _stop(server)
    assert MEASURE.search(on["/"]) and MEASURE.search(on["/settings"])
    assert "data-measure" not in on["/probe"]
    # The flag is in the gzip entry's key: a page compressed before the switch is not served after.
    assert off_gz != on_gz
    assert MEASURE.search(gzip.decompress(on_gz).decode("utf-8"))
    assert not MEASURE.search(gzip.decompress(off_gz).decode("utf-8"))
    # And with it off, the markup is exactly what it was: only the attribute differs.
    assert on["/"].replace(' data-measure="loads"', "", 1) == off["/"]


def test_measure_attr_names_only_the_desk_and_settings(fleet_home):
    _switch(True)
    assert S.measure_attr("index.html") == ' data-measure="loads"'
    assert S.measure_attr("settings.html") == ' data-measure="loads"'
    assert S.measure_attr("probe.html") == ""
    _switch(False)
    assert S.measure_attr("index.html") == ""


# ---------------------------------------------------------------------------------- in a browser


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


@pytest.fixture()
def posts(monkeypatch):
    """Every `/api/load` the server is sent, switched on or off, as the body it carried.

    Counted at the server, because a beacon sent from a closing page's `pagehide` reaches the server
    but is never reported to Playwright as a request of that page."""
    got: list[dict] = []
    act = S.act

    def counting(what, body):
        if what == "load":
            got.append(dict(body))
        return act(what, body)
    monkeypatch.setattr(S, "act", counting)
    return got


def _context(browser):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    errors: list[str] = []
    ctx.on("weberror", lambda e: errors.append(str(e.error)))
    return ctx, errors


def _settled(page, skin=SKIN):
    """The page has booted and its first refresh (the desk) or theme list (settings) has settled."""
    page.wait_for_function(f"() => typeof LOAD !== 'undefined' && LOAD.settled === {json.dumps(skin)}",
                           timeout=15000)
    # The first-frame read of the skin runs in a rAF; two frames later it has run.
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _desk(page, port, token, extra=""):
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    _settled(page)


def _control(ctx, posts, port, token):
    """A desk opened and closed with measuring on: the beacon this test's instrument must hear."""
    _switch(True)
    page = ctx.new_page()
    _desk(page, port, token)
    before = len(posts)
    page.close()
    return _until(lambda: posts, before + 1)


def test_nothing_is_measured_unless_measuring_is_on(fleet_home, tmp_path, browser, posts):
    _desk_of(tmp_path)
    _switch(False)
    server, token, port = _serve()
    ctx, errors = _context(browser)
    try:
        page = ctx.new_page()
        _desk(page, port, token)
        assert page.evaluate("() => document.documentElement.hasAttribute('data-measure')") is False
        assert page.evaluate("() => LOAD.on === false && LOAD.page === null")
        page.locator("#setbtn").click()
        page.wait_for_url("**/settings?**")
        _settled(page)
        assert page.evaluate("() => LOAD.on === false && LOAD.page === null")
        page.locator("#backbtn").click()
        page.wait_for_url(lambda u: "/settings" not in u)
        _settled(page)
        assert page.evaluate("() => sessionStorage.getItem('fleet.load.from')") is None
        page.close()
        assert not (fleet_home / L.LOADS_FILE).exists()
        # The control: switched on, the same instrument hears the one beacon a desk sends. A beacon
        # the round trip above had sent would have been heard first.
        heard = _control(ctx, posts, port, token)
        assert [p["page"] for p in heard] == ["desk"]
        assert errors == []
    finally:
        ctx.close()
        _stop(server)


def test_every_page_load_leaves_one_record_when_it_goes(fleet_home, tmp_path, browser, posts):
    _desk_of(tmp_path)
    _switch(True)
    server, token, port = _serve()
    ctx, errors = _context(browser)
    try:
        page = ctx.new_page()
        _desk(page, port, token)
        assert page.evaluate("() => document.documentElement.getAttribute('data-measure')") == "loads"
        assert posts == []                      # nothing is sent before the page goes
        page.close()
        assert len(_until(lambda: posts, 1)) == 1
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
        _settled(page)
        page.close()
        kept = _records(2)
        # The control that closes the window on a late second beacon from either document.
        _control(ctx, posts, port, token)
        assert [p["page"] for p in posts] == ["desk", "settings", "desk"]
        assert errors == []
    finally:
        ctx.close()
        _stop(server)
    assert [r["page"] for r in kept] == ["desk", "settings"]
    for rec in kept:
        assert rec["from"] == "" and rec["shell"] == "browser" and rec["how"] == "navigate"
        assert rec["first_paint_ms"] and rec["first_paint_ms"] > 0
        # The desk served by #345 wears its skin on the first frame, and it is the one it settles on.
        assert rec["skin_first"] == rec["skin_settled"] == SKIN
    assert kept[0]["fleet_ms"] and kept[0]["fleet_ms"] > 0
    assert kept[1]["fleet_ms"] is None           # /settings does not read /api/fleet


def test_a_round_trip_is_filed_from_settings(fleet_home, tmp_path, browser, posts):
    _desk_of(tmp_path)
    _switch(True)
    server, token, port = _serve()
    ctx, errors = _context(browser)
    try:
        page = ctx.new_page()
        _desk(page, port, token)
        page.locator("#setbtn").click()
        page.wait_for_url("**/settings?**")
        _settled(page)
        page.locator("#backbtn").click()
        page.wait_for_url(lambda u: "/settings" not in u)
        _settled(page)
        page.close()
        kept = _records(3)
        assert len(posts) == 3, posts
        assert errors == []
        rc, out = cli("engines")
    finally:
        ctx.close()
        _stop(server)
    assert [(r["page"], r["from"]) for r in kept] == [("desk", ""), ("settings", ""),
                                                        ("desk", "settings")]
    assert rc == 0
    rows = {(r["page"], r["from"]) for r in table(out, "loads")}
    assert {("desk", ""), ("desk", "settings")} <= rows


def test_the_probe_page_posts_no_load(fleet_home, tmp_path, browser, posts):
    _desk_of(tmp_path)
    _switch(True)
    server, token, port = _serve()
    ctx, errors = _context(browser)
    try:
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{port}/probe?t={token}", wait_until="load")
        assert page.evaluate("() => document.documentElement.hasAttribute('data-measure')") is False
        assert page.evaluate("() => LOAD.page === null")
        page.close()
        # The control: a desk on the same server, switched on, is heard -- and only it.
        heard = _control(ctx, posts, port, token)
        assert [p["page"] for p in heard] == ["desk"]
        assert [r["page"] for r in _records(1)] == ["desk"]
    finally:
        ctx.close()
        _stop(server)


def test_the_first_ink_frame_is_read_without_the_ink_modules(fleet_home, tmp_path, browser, posts):
    _desk_of(tmp_path)
    _switch(True)
    server, token, port = _serve()
    ctx, errors = _context(browser)
    try:
        page = ctx.new_page()
        _desk(page, port, token, "&ink=on")
        page.wait_for_function("() => { const s = window.Ink && Ink.inspect();"
                               " return !!(s && s.layer && s.layer.renders >= 1); }", timeout=15000)
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        page.close()
        _until(lambda: posts, 1)
        page = ctx.new_page()
        _desk(page, port, token, "&ink=off")
        page.close()
        heard = _until(lambda: posts, 2)
        kept = _records(2)
        assert errors == []
    finally:
        ctx.close()
        _stop(server)
    on, off = heard
    assert on["ink_first_frame_ms"] > 0
    assert "ink_first_frame_ms" not in off
    assert kept[0]["ink_first_frame_ms"] > 0 and kept[1]["ink_first_frame_ms"] is None
