"""The map stays live (#406): its own stream, a live dot, deleted branches kept as words.

`/map` reads `/api/map`, then opens `/api/events` from the graph's `cursor` with `notify=0` (#356),
refetches the graph on `agent`, `polls` and `desk` frames through a 400 ms throttle, and says *live*
or *reconnecting* in `#maplink` (docs/fleet-map.md §Staying live).

The first two tests are plain HTTP. The one browser test walks the whole loop on one server, so
the slow tier grows by one. Every wait is on a condition; the one cadence is the fake agent's.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import _serve, _stop


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _say(name, i):
    return E.event(name, "assistant_text", {"text": f"{name} line {i}", "model": "m"},
                   ticket="RDSD-1")


def _luna(tmp_path, events=5):
    """One agent, `luna`, with `events` events already on disk. Returns its newest seq."""
    Registry().add(make_project(tmp_path / "luna", ticket="RDSD-1"), name="luna")
    evs = [E.event("luna", "started", {"pid": 1}, ticket="RDSD-1")]
    evs += [_say("luna", i) for i in range(events - 1)]
    return E.append("luna", evs)


def _get(port, path, token):
    sep = "&" if "?" in path else "?"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}{sep}t={token}", timeout=10) as r:
        return r.read().decode("utf-8")


# --------------------------------------------------------------------------------- plain HTTP


def test_the_header_says_live_or_reconnecting_in_a_dot_after_the_words(fleet_home):
    server, token, port = _serve()
    try:
        html = _get(port, "/map", token)
    finally:
        _stop(server)
    says = html.index('<p id="mapsays"')
    dot = html.index('<span id="maplink" class="dot"></span>')
    assert says < dot < html.index("</header>"), html


def test_a_stream_from_the_graphs_cursor_replays_nothing_and_sends_the_next_event(
        fleet_home, tmp_path):
    """What the map's stream relies on: `since=<graph.cursor>` starts after what the graph drew."""
    newest = _luna(tmp_path)
    server, token, port = _serve()
    try:
        cursor = json.loads(_get(port, "/api/map", token))["cursor"]
        at = int(cursor.split("luna:")[1])     # the snapshot's own fold may have added one
        assert cursor.startswith("luna:") and at >= newest, cursor
        url = (f"http://127.0.0.1:{port}/api/events?t={token}&since={cursor}"
               f"&w=main&page=map&notify=0")
        seen = []
        with urllib.request.urlopen(url, timeout=10) as r:
            def frame():
                kind = ""
                while True:
                    line = r.readline().decode("utf-8").rstrip("\n")
                    if line.startswith("event: "):
                        kind = line[7:]
                    elif line.startswith("data: "):
                        seen.append(kind)
                        return kind, json.loads(line[6:])
            while frame()[0] != "tick":
                pass
            assert "agent" not in seen, seen
            E.append("luna", [_say("luna", 99)])
            while True:
                kind, data = frame()
                if kind == "agent":
                    break
            assert data["seq"] == at + 1, data
        assert "notify" not in seen, seen
    finally:
        _stop(server)


# -------------------------------------------------------------------------------- the browser


RECORDER = """
(() => {
  window.__streams = [];
  const Real = window.EventSource;
  function Recorded(url, opts) {
    const es = new Real(url, opts);
    const rec = { url: String(url), agent: 0, tick: 0, notify: 0 };
    window.__streams.push(rec);
    es.addEventListener("agent", () => { rec.agent++; });
    es.addEventListener("tick", () => { rec.tick++; });
    es.addEventListener("notify", () => { rec.notify++; });
    return es;
  }
  Recorded.prototype = Real.prototype;
  Object.assign(Recorded, { CONNECTING: 0, OPEN: 1, CLOSED: 2 });
  window.EventSource = Recorded;
})();
"""

T0 = time.time()


class Lanes:
    """The git poll's branch cache for `luna`, as the test says it is: `S.current_poller()`'s stand-in."""

    def __init__(self, names):
        self.names = list(names)

    def branch_rows(self, name):
        if name != "luna":
            return None
        rows = [{"name": n, "current": n == "main", "unmerged": n != "main", "ticket": "",
                 "at": T0 - i} for i, n in enumerate(self.names)]
        rows.sort(key=lambda r: not r["unmerged"])
        return {"default": "main", "current": "main", "ticket": "", "carrying": [],
                "rows": rows, "more": False, "at": T0}


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


STREAM = "() => ({...FleetMap.stream, rec: window.__streams[window.__streams.length - 1] || null})"
OBSERVE_LINK = """() => { window.__linkMuts = 0;
  new MutationObserver(r => { window.__linkMuts += r.length; }).observe(
    document.getElementById('maplink'), { subtree: true, childList: true, attributes: true,
                                          characterData: true }); }"""


@pytest.mark.browser
def test_the_map_follows_the_fleet_from_its_cursor_and_keeps_deleted_branches_in_words(
        browser, fleet_home, tmp_path, monkeypatch):
    _luna(tmp_path, events=5)
    lanes = Lanes(["main", "feature/a", "feature/b"])
    monkeypatch.setattr(S, "current_poller", lambda: lanes)
    server, token, port = _serve()
    context = browser.new_context(viewport={"width": 1200, "height": 800})
    page = context.new_page()
    page.add_init_script(RECORDER)
    errors, maps = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: maps.append(r.url) if "/api/map" in r.url else None)
    stopped = False
    try:
        page.goto(f"http://127.0.0.1:{port}/map?t={token}&w=side", wait_until="domcontentloaded")
        # Drawn, open, and one pass ended by its tick: a replay would have arrived before that tick.
        page.wait_for_function("""() => !!window.FleetMap && FleetMap.graph !== null
            && FleetMap.stream.state === 'live' && window.__streams.length === 1
            && window.__streams[0].tick >= 1""", timeout=20000)
        seen = page.evaluate(STREAM)
        assert seen["frames"] == 0 and seen["rec"]["agent"] == 0, seen
        query = parse_qs(urlparse(seen["rec"]["url"]).query)
        cursor = page.evaluate("() => FleetMap.graph.cursor")
        assert query["since"] == [cursor] and cursor.startswith("luna:"), query
        assert query["notify"] == ["0"] and query["page"] == ["map"] and query["w"] == ["side"]
        assert page.text_content("#maplink") == "live"
        assert page.get_attribute("#maplink", "class") == "dot live"

        # One new event: one frame, and the pass's tick on a live map writes nothing to the dot.
        page.evaluate(OBSERVE_LINK)
        ticks = seen["rec"]["tick"]
        E.append("luna", [_say("luna", 100)])
        page.wait_for_function(f"""() => FleetMap.stream.frames === 1
            && window.__streams[0].tick > {ticks}""", timeout=15000)
        assert page.evaluate("() => window.__linkMuts") == 0

        # The operator opens the branches; a fake agent then talks every 100 ms for 3 s.
        group = '#maptree [data-node="bs:luna"]'
        page.click(group + " > .say")
        page.wait_for_function(
            f"() => document.querySelector('{group}').getAttribute('aria-expanded') === 'true'",
            timeout=5000)
        before = len(maps)
        done = threading.Event()

        def agent():
            for i in range(30):
                E.append("luna", [_say("luna", 200 + i)])
                done.wait(0.1)                  # the agent's cadence, not a wait for the page
        talker = threading.Thread(target=agent, daemon=True)
        talker.start()
        talker.join(timeout=30)
        page.wait_for_function("() => FleetMap.stream.frames === 31", timeout=15000)
        assert len(maps) - before >= 5, maps[before:]
        assert page.get_attribute(group, "aria-expanded") == "true"

        # A branch leaves the next graph: its item stays, in words, until the list changes again.
        lanes.names = ["main", "feature/a"]
        E.append("luna", [_say("luna", 300)])
        gone = '#maptree [data-node="b:luna:feature/b"]'
        page.wait_for_function(f"""() => {{ const li = document.querySelector('{gone}');
            return !!li && li.classList.contains('gone'); }}""", timeout=15000)
        assert page.text_content(gone + " > .say") == "feature/b · deleted"
        assert page.get_attribute(group, "aria-expanded") == "true"
        lanes.names = ["main", "feature/a", "feature/c"]
        E.append("luna", [_say("luna", 301)])
        page.wait_for_function(f"""() => !document.querySelector('{gone}')
            && !!document.querySelector('#maptree [data-node="b:luna:feature/c"]')""", timeout=15000)

        # A palette chosen elsewhere reaches the map as the stream's `theme` frame.
        assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") != "custom"
        page.evaluate("""async () => { const u = new URL(location.href);
            await fetch('/api/theme?t=' + u.searchParams.get('t'), { method: 'POST',
              headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: 'sand' }) }); }""")
        page.wait_for_function(
            "() => document.documentElement.getAttribute('data-theme') === 'custom'", timeout=15000)
        assert page.evaluate("() => window.__streams.reduce((n, s) => n + s.notify, 0)") == 0

        # The server goes: the dot says so.
        _stop(server)
        stopped = True
        page.wait_for_function("() => FleetMap.stream.state === 'reconnecting'", timeout=15000)
        assert page.text_content("#maplink") == "reconnecting"
        assert page.get_attribute("#maplink", "class") == "dot lost"
        assert not errors, errors
    finally:
        context.close()
        if not stopped:
            _stop(server)
