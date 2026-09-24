"""/settings wears the palette it says is chosen, repaints the moment one is picked, and waits for the
write before it leaves (#346).

Two faults. `/api/themes` answered `current` with no css, and `loadThemes()` painted that as "no
palette" -- so whenever the stream's first `theme` frame landed first, the page stayed in the
system palette under the chosen skin. And a pick painted nothing until the stream's next tick,
because `POST /api/theme` answered with names only; leaving in that window could take the old skin
back to the desk.

The order of the two answers is forced in the page by an init script, never by a sleep. Expected
colours come from `S.theme_state()`. One browser for the module; a server per test.
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urlparse

import pytest

from agentdata import theme as T
from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S

from test_fleet_ink import (_desk_of, _facts, _serve, _stop, fleet_home,  # noqa: F401
                            _own_desk_globals)
from test_fleet_theme_switch import (SAMPLER, SETTLED, _desk, _frames, _rgb, _wrong,  # noqa: F401
                                     browser)

# Forces which of `/api/themes` and the stream's first `theme` frame the page hears first.
# `stream`: `/api/themes` is held until the page has heard its first frame.
# `themes`: the page's own `theme` listener is held until `loadThemes` has filled the pickers.
# Either way `window.__applied` turns true once the page has acted on both.
ORDER = """
(() => {
  const ORDER = "%s";
  window.__applied = false;
  let heard; const first = new Promise(r => heard = r);
  function filled() {
    return new Promise(r => { (function look() {
      const t = document.getElementById('theme');
      if (t && t.options.length > 1) r(); else requestAnimationFrame(look);
    })(); });
  }
  const ES = window.EventSource;
  window.EventSource = function (u, o) {
    const s = new ES(u, o);
    s.addEventListener('theme', () => setTimeout(heard, 0));
    if (ORDER === 'themes') {
      const add = s.addEventListener.bind(s);
      s.addEventListener = function (type, fn, opt) {
        if (type !== 'theme') return add(type, fn, opt);
        return add(type, function (m) {
          filled().then(() => { fn.call(s, m); window.__applied = true; });
        }, opt);
      };
    }
    return s;
  };
  window.EventSource.prototype = ES.prototype;
  const f = window.fetch;
  window.fetch = function (u, o) {
    const p = f.apply(this, arguments);
    if (ORDER === 'stream' && String(u).includes('/api/themes')) {
      return first.then(() => p).then(r => { filled().then(() => { window.__applied = true; }); return r; });
    }
    return p;
  };
})();
"""

# Holds every `POST /api/theme` in the page until `window.__release()`; `window.__held` counts them.
HOLD = """
(() => {
  const f = window.fetch;
  window.__held = 0;
  window.fetch = function (u, o) {
    const self = this, args = arguments;
    if (o && o.method === 'POST' && new URL(String(u), location.href).pathname === '/api/theme') {
      window.__held++;
      return new Promise(r => { window.__release = r; }).then(() => f.apply(self, args));
    }
    return f.apply(this, arguments);
  };
})();
"""

# Holds the page's own `theme` listener until a `POST /api/theme` is held (HOLD's `__held`), so
# the stream's first frame -- the config as it was before the pick -- lands in the middle of the
# write. `window.__late` turns true once the page has acted on it.
LATE_FRAME = """
(() => {
  window.__late = false;
  function held() {
    return new Promise(r => { (function look() {
      if (window.__held >= 1) r(); else requestAnimationFrame(look);
    })(); });
  }
  const ES = window.EventSource;
  window.EventSource = function (u, o) {
    const s = new ES(u, o);
    const add = s.addEventListener.bind(s);
    s.addEventListener = function (type, fn, opt) {
      if (type !== 'theme') return add(type, fn, opt);
      return add(type, function (m) { held().then(() => { fn.call(s, m); window.__late = true; }); }, opt);
    };
    return s;
  };
  window.EventSource.prototype = ES.prototype;
})();
"""

FILLED = "() => document.querySelectorAll('#skin option').length > 3"
BG = "() => document.documentElement.style.getPropertyValue('--bg')"


def _config(fleet_home, **theme):
    (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": theme}), encoding="utf-8")


def _state_of(fleet_home, **theme) -> dict:
    """`theme_state()` as it would be with `theme` configured; the caller writes the real config."""
    _config(fleet_home, **theme)
    return S.theme_state()


def _page(browser, *scripts):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.add_init_script(SAMPLER)
    for s in scripts:
        page.add_init_script(s)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return page, errors


def _settings(page, port, token):
    page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
    page.wait_for_function(FILLED, timeout=15000)


def _get(port, token, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}?t={token}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(port, token, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}?t={token}",
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


# ----------------------------------------------------------------------------- the two answers


@pytest.mark.parametrize("theme", [{"default": "nfl-browns"}, {"skin": "voxel:nether"},
                                   {"default": "none", "skin": "none"}],
                         ids=["palette", "skin", "none"])
def test_api_themes_current_is_the_streams_theme_payload(fleet_home, tmp_path, theme):
    _config(fleet_home, **theme)
    want = S.theme_state()
    server, token, port = _serve()
    try:
        got = _get(port, token, "/api/themes")["current"]
    finally:
        _stop(server)
    assert got["css"] == want["css"], got
    assert (got["theme"], got["skin"]) == (want["theme"], want["skin"]), got
    for key in ("skin_family", "skin_variant", "tiers", "accents"):
        assert got[key] == want[key], (key, got)
    if theme.get("default") == "none":
        assert got["css"] == {} and got["theme"] == "none", got


def test_post_theme_answers_with_the_css_it_wrote(fleet_home, tmp_path):
    _config(fleet_home)
    server, token, port = _serve()
    try:
        skin = _post(port, token, "/api/theme", {"skin": "voxel:nether"})
        want = S.theme_state()
        palette = _post(port, token, "/api/theme", {"skin": "none", "theme": "nfl-browns"})
        want_palette = S.theme_state()
    finally:
        _stop(server)
    assert skin["ok"] and skin["css"] == want["css"] and skin["css"], skin
    assert (skin["theme"], skin["skin"], skin["skin_family"]) == (want["theme"], "voxel:nether", "voxel")
    assert palette["css"] == want_palette["css"] and palette["theme"] == "nfl-browns", palette


@pytest.mark.browser
@pytest.mark.parametrize("order", ["stream", "themes"])
@pytest.mark.parametrize("theme", [{"default": "nfl-browns"}, {"skin": "voxel:nether"}],
                         ids=["palette", "skin"])
def test_the_settings_page_keeps_its_palette_whichever_answer_lands_first(browser, fleet_home,
                                                                          tmp_path, order, theme):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, **theme)
    want = S.theme_state()
    server, token, port = _serve()
    try:
        page, errors = _page(browser, ORDER % order)
        _settings(page, port, token)
        page.wait_for_function("() => window.__applied === true", timeout=15000)
        got = page.evaluate("""() => ({ bg: document.documentElement.style.getPropertyValue('--bg'),
            skin: document.body.dataset.skin || '', theme: document.getElementById('theme').value,
            picked: document.getElementById('skin').value })""")
        print(f"\n  {order} first, {theme}: {got}")
        assert got["bg"] == want["css"]["--bg"], (order, got)
        assert got["skin"] == want["skin_family"] and got["picked"] == want["skin"], got
        assert got["theme"] == want["theme"], got
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


# ------------------------------------------------------------------------------------ a pick


@pytest.mark.browser
@pytest.mark.measured
def test_choosing_a_skin_repaints_settings_before_the_server_answers(browser, fleet_home, tmp_path):
    _desk_of(tmp_path, ("alpha",))
    want = _state_of(fleet_home, skin="voxel:nether")
    _config(fleet_home)
    server, token, port = _serve()
    try:
        page, errors = _page(browser, HOLD)
        _settings(page, port, token)
        page.select_option("#skin", "voxel:nether")
        page.wait_for_function("() => window.__held === 1", timeout=15000)
        got = page.evaluate("""() => ({ skin: document.body.dataset.skin || '',
            variant: document.body.dataset.skinVariant || '',
            bg: document.documentElement.style.getPropertyValue('--bg'),
            theme: document.getElementById('theme').value,
            took: performance.getEntriesByType('measure').filter(m => m.name.startsWith('theme:skin'))
                              .map(m => m.duration) })""")
        print(f"\n  painted while the POST is held: {got}")
        assert (got["skin"], got["variant"]) == ("voxel", "nether"), got
        assert got["bg"] == want["css"]["--bg"] and got["theme"] == want["theme"], got
        assert len(got["took"]) == 1 and got["took"][0] < 50, got
        assert S.theme_state()["skin"] == "none", "nothing was written yet"

        page.evaluate("() => window.__release()")
        page.wait_for_function("() => document.getElementById('theme').disabled === true", timeout=15000)
        page.wait_for_function("() => !!document.getElementById('saved') "
                               "&& !document.getElementById('saved').hidden", timeout=15000)
        assert S.theme_state()["skin"] == "voxel:nether"
        assert page.evaluate(BG) == want["css"]["--bg"]
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
@pytest.mark.parametrize("answer", ["ok", "refused"])
def test_a_frame_heard_while_the_write_is_held_does_not_undo_the_pick(browser, fleet_home, tmp_path,
                                                                       answer):
    """CI's Chromium heard the stream's first `theme` frame (no skin) after the pick had painted and
    while its POST was in flight, and that frame put the old theme back over the pick. A frame
    heard during a write is the server's word from before it: kept for a refusal to go back to,
    never painted over the pick. Here that frame is made late on purpose."""
    _desk_of(tmp_path, ("alpha",))
    want = _state_of(fleet_home, skin="voxel:nether")
    _config(fleet_home)
    server, token, port = _serve()
    try:
        page, errors = _page(browser, HOLD, LATE_FRAME)
        if answer == "refused":
            page.route(_is_theme_post, _refuse)
        _settings(page, port, token)
        page.select_option("#skin", "voxel:nether")
        page.wait_for_function("() => window.__held === 1 && window.__late === true", timeout=15000)
        got = page.evaluate("""() => ({ skin: document.body.dataset.skin || '',
            bg: document.documentElement.style.getPropertyValue('--bg'),
            picked: document.getElementById('skin').value })""")
        print(f"\n  {answer}: after the late frame, POST held: {got}")
        assert got == {"skin": "voxel", "bg": want["css"]["--bg"], "picked": "voxel:nether"}, got

        page.evaluate("() => window.__release()")
        if answer == "ok":
            page.wait_for_function("() => document.getElementById('saved').hidden === false", timeout=15000)
            end = ("voxel", want["css"]["--bg"], "voxel:nether")
        else:
            page.wait_for_function("() => document.getElementById('skin').classList.contains('bad')",
                                   timeout=15000)
            end = ("", "", "none")
        got = page.evaluate("""() => [document.body.dataset.skin || '',
            document.documentElement.style.getPropertyValue('--bg'), document.getElementById('skin').value]""")
        assert tuple(got) == end, (answer, got)
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


def _refuse(route):
    if route.request.method != "POST":
        return route.continue_()
    route.fulfill(status=409, content_type="application/json",
                  body=json.dumps({"ok": False, "error": "config.json is locked",
                                   "hint": "close the editor holding it"}))


def _is_theme_post(url: str) -> bool:
    return urlparse(url).path == "/api/theme"


@pytest.mark.browser
def test_a_refused_skin_goes_back_and_says_why(browser, fleet_home, tmp_path):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, skin="voxel:nether")
    was = S.theme_state()
    server, token, port = _serve()
    try:
        page, errors = _page(browser, HOLD)
        page.route(_is_theme_post, _refuse)
        _settings(page, port, token)
        page.wait_for_function("() => document.getElementById('skin').value === 'voxel:nether'",
                               timeout=15000)
        page.select_option("#skin", "farmstead:daytime")
        page.wait_for_function("() => window.__held === 1 && document.body.dataset.skin === 'farmstead'",
                               timeout=15000)
        page.evaluate("() => window.__release()")
        page.wait_for_function("() => document.body.dataset.skin === 'voxel'", timeout=15000)
        got = page.evaluate("""() => { const s = document.getElementById('skin');
            return { variant: document.body.dataset.skinVariant || '',
                     bg: document.documentElement.style.getPropertyValue('--bg'),
                     picked: s.value, theme: document.getElementById('theme').value,
                     bad: s.classList.contains('bad'), said: s.title }; }""")
        print(f"\n  refused: {got}")
        assert got["variant"] == "nether" and got["bg"] == was["css"]["--bg"], got
        assert got["picked"] == "voxel:nether" and got["theme"] == was["theme"], got
        assert got["bad"] and "config.json is locked" in got["said"] \
            and "close the editor holding it" in got["said"], got
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
@pytest.mark.parametrize("answer", ["ok", "refused"])
def test_leaving_settings_waits_for_the_write(browser, fleet_home, tmp_path, answer):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, skin="voxel:nether")
    server, token, port = _serve()
    try:
        page, errors = _page(browser, HOLD)
        if answer == "refused":
            page.route(_is_theme_post, _refuse)
        _settings(page, port, token)
        seen = []
        page.on("request", lambda r: seen.append((r.method, urlparse(r.url).path, r.resource_type)))
        page.select_option("#skin", "farmstead:daytime")
        page.wait_for_function("() => window.__held === 1", timeout=15000)
        page.locator("#backbtn").click()
        page.evaluate("() => window.__release && window.__release()")
        page.wait_for_url(re.compile(r"/\?"), timeout=15000)
        page.wait_for_function("() => typeof lastFleet !== 'undefined' && !!lastFleet", timeout=15000)
        wrote = [i for i, r in enumerate(seen) if r[:2] == ("POST", "/api/theme")]
        desk = [i for i, r in enumerate(seen) if r[1] == "/" and r[2] == "document"]
        print(f"\n  {answer}: {seen[:6]}")
        assert wrote and desk and wrote[0] < desk[0], seen
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_settings_page_stays_legible_through_a_pick(browser, fleet_home, tmp_path):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, skin="voxel:nether")
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _settings(page, port, token)
        page.select_option("#skin", "farmstead:daytime")
        page.wait_for_function("() => document.getElementById('saved').hidden === false", timeout=15000)
        page.wait_for_function("() => document.readyState === 'complete'", timeout=15000)
        frames = _frames(page)["frames"]
        read = []
        for f in frames:
            if f["skin"] != "farmstead":
                continue
            text, _ = _rgb(f["h1"])
            ground, alpha = _rgb(f["headerBg"])
            if text and ground and alpha == 1.0:
                read.append((f["t"], round(T.contrast_ratio(text, ground), 2), f["inkOff"]))
        print(f"\n  farmstead:daytime frames after the pick: {read[:8]}")
        assert read, frames
        assert all(r[1] >= 4.5 for r in read), read
        assert all(f["inkOff"] for f in frames if f["inkOff"] is not None), "ink-off stays on /settings"
        assert not errors, errors
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_choosing_and_leaving_at_once_never_paints_the_old_skin(browser, fleet_home, tmp_path):
    PR.record(_facts(shell="browser"))
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    run = ["farmstead:daytime", "glass:smoke", "voxel:overworld"]
    bgs = {s: _state_of(fleet_home, skin=s)["css"]["--bg"] for s in run}
    _config(fleet_home, skin="voxel:nether")
    server, token, port = _serve()
    try:
        page, errors = _page(browser)
        _desk(page, port, token)
        old = "voxel"
        for skin in run:
            family = skin.split(":")[0]
            page.wait_for_function("() => !!Ink.inspect().table", timeout=15000)
            page.locator("#setbtn").click()
            page.wait_for_url(re.compile(r"/settings"), timeout=15000)
            page.wait_for_function(FILLED, timeout=15000)
            page.select_option("#skin", skin)
            page.locator("#backbtn").click()
            page.wait_for_url(re.compile(r"/\?"), timeout=15000)
            page.wait_for_function(SETTLED, timeout=15000)
            page.wait_for_function("s => Ink.inspect().table === s", arg=skin, timeout=15000)
            frames = _frames(page)["frames"]
            print(f"\n  {old} -> {skin}: {len(frames)} frames")
            assert frames and not _wrong(frames, family, bgs[skin], old), (skin, frames)
            old = family
        assert not errors, errors
        page.close()
    finally:
        _stop(server)
