"""Instant (issue #219).

The desk did the right things in the wrong order. A tile was hidden by posting `arrange` and
waiting for the answer before anything moved, which reads as a form rather than a desk. Every
action fetched the whole fleet afterwards -- so replying to one agent carried nine tiles across
the wire to redraw one of them. And a window reopened on an empty grid with a sentence about
having no projects, for as long as the first fold took.

None of that was slow code. It was a page asking permission to draw what it already knew. What is
asserted here is the other order: paint, then post, then reconcile -- and say so out loud when the
server disagrees.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")

#: The budget, in milliseconds, for a gesture the page can answer out of what it already has.
LOCAL_BUDGET_MS = 50.0


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"column": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "grid": {"order": [], "size": {}, "pinned": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})


def _repos(tmp_path, *names):
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name,
                                                         "model": "claude-haiku-4.5"},
                                ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# ---------------------------------------------------------------------------- the shape of it


def test_every_action_that_changes_a_row_answers_with_it(fleet_home, tmp_path):
    """The round trip that is not made. `send` cost two -- the act, then a whole `/api/fleet` to
    find out what it did -- and the second carried every tile on the desk."""
    _repos(tmp_path, "alpha", "beta")
    assert "refresh" in S.ROW_ACTIONS and "send" in S.ROW_ACTIONS
    # The arrangement is not a row: it reaches every window down the stream instead.
    assert "arrange" not in S.ROW_ACTIONS and "window" not in S.ROW_ACTIONS
    for what in S.ROW_ACTIONS:
        assert isinstance(what, str) and what


def test_the_page_patches_one_row_and_does_not_fetch_the_fleet_again():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function patchRow(row, index)" in js
    door = js[js.index("function action(el, what, body)"):]
    door = door[:door.index("\n}\n")]
    assert "if (r.row) { patchRow(r.row); place(); }" in door
    assert "else refresh();" in door, "an older server, or an action with no row, still works"


def test_one_optimistic_writer_owns_the_arrangement_and_can_put_it_back():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function arrangeNow(patch, apply, what)" in js
    # Everything that moves a tile goes through it, and nothing posts `arrange` by hand.
    assert js.count('post("arrange"') == 1, "a second writer of the arrangement"
    assert js.count("arrangeNow(") >= 4, js.count("arrangeNow(")
    door = js[js.index("function arrangeNow(patch, apply, what)"):]
    door = door[:door.index("\n}\n")]
    assert "undo()" in door and "say(" in door, "a refusal must undo and be said out loud"


def test_every_local_gesture_is_marked_at_both_ends():
    common = open(os.path.join(STATIC, "common.js"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function gesture(name)" in common and "function settle(mark)" in common
    assert "performance.mark" in common and "performance.measure" in common
    assert js.count("gesture(") >= 4 and js.count("settle(") >= 4


def test_nothing_on_the_page_is_a_spinner():
    """The acceptance criterion, and the reason for all of the above: a page that has something to
    show never shows a spinner instead, and a page that does not have something to show has not
    been written to wait.

    Comments are stripped before looking -- the stylesheet and the script both say *why* there is
    no spinner, at some length, and a test that could not tell the word from the thing would make
    the explanation unwritable."""
    def _no_comments(text, kind):
        if kind == "html":
            return re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)

    bad = re.compile(r"\b(spinner|loading-?(bar|dots?|ring)|loader|busy-?overlay|throbber)\b", re.I)
    pages = [("index.html", "html"), ("settings.html", "html"),
             ("app.css", "css"), ("app.js", "css"), ("common.js", "css"), ("settings.js", "css")]
    for name, kind in pages:
        body = _no_comments(open(os.path.join(STATIC, name), encoding="utf-8").read(), kind)
        hits = sorted({m.group(0) for m in bad.finditer(body)})
        assert hits == [], f"{name}: {hits}"
    # `aria-busy` and `role="progressbar"` are the accessible ways to say the same thing, and
    # neither is used either.
    for name in ("index.html", "settings.html"):
        markup = open(os.path.join(STATIC, name), encoding="utf-8").read()
        assert "aria-busy" not in markup, name
        assert "progressbar" not in markup, name


def test_the_cached_desk_is_the_rows_without_the_transcripts():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "function cacheSnapshot(data)" in js and "function restoreCached()" in js
    door = js[js.index("function cacheSnapshot(data)"):]
    door = door[:door.index("\n}\n")]
    assert "recent: []" in door, "the transcripts are the big part and the part that rots"
    assert "SNAP_GOOD_FOR_MS" in js


# ------------------------------------------------------------------------------- in a browser


@pytest.mark.browser
def test_hiding_a_tile_paints_before_the_server_answers(fleet_home, tmp_path):
    """Asserted by making the server slow. Anything that only passes against a fast local server
    is asserting that the network was quick, not that the page was."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="beta"]', timeout=15000)

            took = page.evaluate("""() => {
              // Two whole seconds before `arrange` is allowed to answer. Delayed in the page
              // rather than in the driver: a sleep inside a route handler blocks Playwright's
              // own thread, and then the test is measuring itself.
              let settled = false;
              const real = window.fetch;
              window.fetch = function (url, opts) {
                if (String(url).indexOf('/api/arrange') >= 0) {
                  return new Promise(go => setTimeout(() => {
                    settled = true;
                    go(real(url, opts));
                  }, 2000));
                }
                return real.apply(this, arguments);
              };
              const began = performance.now();
              setHidden('beta', true);
              // Polled by frame rather than counted in frames: a layout change goes through a
              // view transition (#216), which applies it on the frame *after* the browser has
              // taken its "before" snapshot. What matters is that it does not wait for the wire.
              return new Promise(resolve => {
                const look = () => {
                  const hidden = document.querySelector('.tile[data-repo="beta"]')
                                   .classList.contains('is-hidden');
                  const ms = performance.now() - began;
                  if (hidden || ms > 1000) {
                    window.fetch = real;
                    resolve({ ms: ms, hidden: hidden, posted: settled });
                  } else {
                    requestAnimationFrame(look);
                  }
                };
                requestAnimationFrame(look);
              });
            }""")
            assert not errors, errors
            assert took["hidden"], "the tile waited for the server before it moved"
            assert not took["posted"], "the server answered first, so this proves nothing"
            assert took["ms"] < LOCAL_BUDGET_MS, \
                f"the tile took {took['ms']:.0f}ms to move, against a two-second server"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_refused_arrangement_goes_back_and_says_why(fleet_home, tmp_path):
    """The other half of optimistic. A tile that silently returns to where it was is a page the
    operator stops trusting -- so the refusal arrives in the server's own words."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="beta"]', timeout=15000)

            page.route("**/api/arrange*", lambda route: route.fulfill(
                status=409, content_type="application/json",
                body=json.dumps({"ok": False, "error": "that arrangement was refused",
                                 "hint": "the desk is held by another window",
                                 "code": "desk_locked"})))

            page.evaluate("() => setHidden('beta', true)")
            page.wait_for_function(
                """() => !document.querySelector('.tile[data-repo="beta"]')
                           .classList.contains('is-hidden')""", timeout=8000)
            said = page.evaluate("() => document.getElementById('notice').textContent")
            assert "refused" in said, said
            assert "another window" in said, "the server's own hint, not a shrug"
            assert page.evaluate(
                "() => (getLayoutArrangement().hidden || []).indexOf('beta')") == -1
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_action_patches_its_tile_without_a_second_snapshot(fleet_home, tmp_path):
    """Counted, not assumed."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="beta"]', timeout=15000)
            page.wait_for_timeout(400)

            # Only the fetches this gesture caused. The stream's own tick refreshes on its own
            # clock, and counting those would be counting the server's heartbeat.
            out = page.evaluate("""async () => {
              /* The stream refreshes on its own clock -- and `refreshSoon` arms a timer 400ms
                 out -- so with either still live this would be counting the server's heartbeat
                 rather than what the gesture decided. Closed, then given long enough for any
                 armed timer to have fired. */
              if (source) { source.close(); source = null; }
              await new Promise(go => setTimeout(go, 700));
              const seen = [];
              const real = window.fetch;
              window.fetch = function (url) {
                // The stack with it: a count that fails tells you a fetch happened, and the
                // stack tells you who asked for it.
                seen.push(String(url) + ' <- ' +
                          (new Error().stack || '').split(String.fromCharCode(10)).slice(1, 4).join(' | '));
                return real.apply(this, arguments);
              };
              const tile = document.querySelector('.tile[data-repo="beta"]');
              const r = await action(tile, 'refresh', { repo: 'beta' });
              window.fetch = real;
              return { ok: !!(r && r.ok), row: !!(r && r.row),
                       repo: r && r.row && r.row.repo,
                       calls: seen,
                       fleet: seen.filter(u => u.indexOf('/api/fleet') >= 0) };
            }""")
            assert not errors, errors
            assert out["ok"] and out["row"], out
            assert out["repo"] == "beta"
            assert out["fleet"] == [], f"the action fetched the whole fleet as well: {out['calls']}"
            assert len(out["calls"]) == 1, f"one round trip, not two: {out['calls']}"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_every_local_gesture_is_inside_the_budget(fleet_home, tmp_path):
    """Fifty milliseconds, per gesture, measured by the page's own marks. What is timed is the
    part the page decides: painting what it already knows. The round trip after it is the
    server's business and has its own numbers."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma", "delta", "epsilon")
    S.arrange("grid", order=["alpha", "beta", "gamma", "delta", "epsilon"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="epsilon"]', timeout=15000)
            page.wait_for_timeout(400)

            marks = page.evaluate("""() => {
              performance.clearMeasures();
              setHidden('beta', true);
              setHidden('beta', false);
              moveTile('gamma', 1);
              moveTile('gamma', -1);
              saveWindow({ read: {} });
              return performance.getEntriesByType('measure')
                .map(m => ({ name: m.name.split(':')[0] + ':' + m.name.split(':')[1],
                             ms: m.duration }));
            }""")
            assert not errors, errors
            assert len(marks) >= 4, f"the gestures were not marked at all: {marks}"
            over = [m for m in marks if m["ms"] > LOCAL_BUDGET_MS]
            worst = max(m["ms"] for m in marks)
            print(f"\nlocal gestures: {len(marks)} marked, worst {worst:.1f}ms "
                  f"against a {LOCAL_BUDGET_MS:.0f}ms budget")
            assert over == [], f"over the budget: {over}"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_reopened_window_shows_the_desk_it_had_while_the_new_one_loads(fleet_home, tmp_path):
    """Stale, then right, and honest about which. The first `/api/fleet` on a nine-project fleet
    is a catalogue read, a fold per agent and a ledger per agent; until it answered, the window
    said "no projects", which is the wrong answer given confidently."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta", "gamma")
    S.arrange("grid", order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="gamma"]', timeout=15000)
            page.wait_for_function(
                "() => { try { return !!sessionStorage.getItem(SNAP_KEY); } catch (e) "
                "{ return false; } }", timeout=8000)

            # Reload with the fleet held up for a second and a half. Without the cache this is a
            # second and a half of "no projects yet". An init script, because it has to be in
            # place before the page's own scripts run on the reload.
            page.add_init_script("""
              const real = window.fetch;
              window.fetch = function (url, opts) {
                if (String(url).indexOf('/api/fleet') >= 0) {
                  return new Promise(go => setTimeout(() => go(real(url, opts)), 1500));
                }
                return real.apply(this, arguments);
              };
            """)
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile", timeout=5000)
            early = page.evaluate("""() => ({
              tiles: document.querySelectorAll('#grid .tile').length,
              stale: document.body.classList.contains('is-stale'),
              empty: !document.getElementById('empty').hidden,
            })""")
            assert early["tiles"] == 3, early
            assert early["stale"], "a stale desk that does not admit it is a desk that lies"
            assert not early["empty"], "it said there were no projects over three of them"

            page.wait_for_function(
                "() => !document.body.classList.contains('is-stale')", timeout=15000)
            assert page.evaluate("() => document.querySelectorAll('#grid .tile').length") == 3
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
