"""The shape of the hour, and the ground it is drawn on (issue #218).

A tile says what an agent is doing now and carries forty events for its transcript. What it could
not say is the shape of the hour: whether this quiet minute follows fifty busy ones or four
hundred quiet ones, and whether the operator has already been asked something in that time. Those
are the two questions somebody scanning nine tiles is actually asking, and `idle · 3m` answers
neither.

The rules a picture on this page keeps are in `docs/desk-rendering.md`. What is asserted here is
that they hold: the colours come from the stylesheet, the picture has a text twin, nothing is
drawn that the row does not carry, and the ground costs a frame a second. Since #257 neither is a
canvas: the ink layer draws both where a shell draws ink, from the data the page writes, and the
page's own SVG and the stylesheet's gradients are what every other shell shows.
"""
from __future__ import annotations
import calendar
import json
import os
import re
import threading
import time

import pytest

from agentdata.fleet import events as E, registry, serve as S, trace as T
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})


def _at(now: float, minutes_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - minutes_ago * 60))


def _busy_hour(now: float):
    """Forty events in forty different minutes, two of which stopped for a person."""
    rows = []
    for i in range(38):
        rows.append({"ts": _at(now, i + 1), "kind": "tool_call"})
    rows.append({"ts": _at(now, 41), "kind": "question_opened"})
    rows.append({"ts": _at(now, 45), "kind": "question_opened"})
    return rows


def _agent(tmp_path, name, rows):
    Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    E.append(name, [E.event(name, r["kind"], {}, ticket="RDSD-1", ts=r["ts"]) for r in rows])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


# ------------------------------------------------------------------------------ sixty numbers


def test_an_hour_is_sixty_buckets_oldest_first():
    now = time.time()
    out = T.trace(_busy_hour(now), now=now)
    assert out["minutes"] == 60
    assert len(out["n"]) == 60 and len(out["needs"]) == 60
    assert sum(out["n"]) == out["total"] == 40
    assert out["needed"] == 2
    assert sum(out["needs"]) == 2
    # Oldest first: the two questions are 41 and 45 minutes back, so they land in the older half.
    red = [i for i, v in enumerate(out["needs"]) if v]
    assert all(i < 30 for i in red), red


def test_the_sentence_is_the_picture_in_words():
    now = time.time()
    assert T.trace(_busy_hour(now), now=now)["says"] == \
        "40 events in the last hour, needed you twice"
    assert T.trace([], now=now)["says"] == "nothing in the last hour"
    assert T.trace([{"ts": _at(now, 2), "kind": "tool_call"}], now=now)["says"] == \
        "1 event in the last hour"
    said = [{"ts": _at(now, 2), "kind": "assistant_text"},
            {"ts": _at(now, 3), "kind": "question_opened"}]
    assert T.trace(said, now=now)["says"] == \
        "2 events in the last hour, said something once, needed you once"
    assert T.blank()["says"] == "nothing in the last hour"


def test_what_fell_outside_the_hour_is_not_in_it():
    now = time.time()
    rows = [{"ts": _at(now, 3), "kind": "tool_call"},
            {"ts": _at(now, 61), "kind": "tool_call"},        # an hour and a minute ago
            {"ts": _at(now, 600), "kind": "question_opened"},  # yesterday's shift
            {"ts": "", "kind": "tool_call"},                   # no stamp at all
            {"ts": "not a date", "kind": "tool_call"}]
    out = T.trace(rows, now=now)
    assert out["total"] == 1 and out["needed"] == 0


def test_the_trace_carries_no_text_and_costs_almost_nothing(fleet_home, tmp_path):
    """It is on every row of every window several times a minute. A transcript on that path is the
    payload problem this repository keeps having, one field further along."""
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now) +
           [{"ts": _at(now, 2), "kind": "assistant_text"}])
    row = S.row_for("alpha")
    assert "trace" in row
    blob = json.dumps(row["trace"])
    assert len(blob) < 700, f"the trace is {len(blob)} bytes"
    # Nothing but numbers and the one sentence.
    assert set(row["trace"]) == {"minutes", "n", "needs", "total", "needed", "said", "peak", "says"}
    assert all(isinstance(v, int) for v in row["trace"]["n"])


@pytest.mark.scale
@pytest.mark.measured
def test_a_day_long_stream_is_folded_from_its_tail_and_not_from_its_head():
    """This runs on every row of every snapshot, several times a second, and an agent that has
    been going all day has tens of thousands of events. Parsing every stamp in all of them to find
    the last sixty minutes would be the most expensive thing the server does."""
    import random
    import time as _t

    now = _t.time()
    rng = random.Random(217)
    old_events = sorted(({"ts": _at(now, rng.uniform(61, 1440)), "kind": "tool_call"}
                         for _ in range(40000)), key=lambda e: e["ts"])
    recent = sorted(({"ts": _at(now, rng.uniform(0, 58)), "kind": "tool_call"}
                     for _ in range(300)), key=lambda e: e["ts"])
    stream = old_events + recent

    began = _t.perf_counter()
    out = T.trace(stream, now=now)
    took = _t.perf_counter() - began
    assert out["total"] == 300, out["total"]
    # Generous by an order of magnitude against the 0.2ms this measures, because the number that
    # matters is "not proportional to the day" and a CI runner under load is not a stopwatch.
    assert took < 0.05, f"{took * 1000:.1f}ms to fold {len(stream)} events"


def test_a_few_stamps_out_of_order_do_not_end_the_scan():
    """A stream is chronological in *arrival* order, and a Copilot log replayed out of a file can
    carry a handful of stamps that step backwards. A scan that stopped at the first one would
    lose the hour behind it."""
    now = time.time()
    stream = ([{"ts": _at(now, 30), "kind": "tool_call"}] +
              [{"ts": _at(now, 200 + i), "kind": "tool_call"} for i in range(T.STOP_AFTER - 1)] +
              [{"ts": _at(now, 5), "kind": "tool_call"}])
    assert T.trace(stream, now=now)["total"] == 2, "the older run swallowed what was behind it"

    # And a stream that really is older than the hour does end the scan.
    ancient = [{"ts": _at(now, 500 + i), "kind": "tool_call"} for i in range(T.STOP_AFTER + 40)]
    assert T.trace(ancient + [{"ts": _at(now, 3), "kind": "tool_call"}], now=now)["total"] == 1


def test_the_sliced_stamp_and_the_parser_agree():
    """`_seconds` slices the fixed-width form rather than calling `strptime`, which is where the
    speed above comes from. The two have to give the same answer, including for the shapes that
    do not fit and fall back."""
    now = time.time()
    for minutes in (0, 1, 59, 60, 1440):
        stamp = _at(now, minutes)
        assert T._seconds(stamp) == float(
            calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))), stamp
    assert T._seconds("") == -1.0
    assert T._seconds("not a date at all") == -1.0
    assert T._seconds("2026-13-99T99:99:99") == -1.0
    # A trailing Z or fraction is sliced off by `events.stamp()` before it gets here, but the
    # reader must not be the thing that breaks if one arrives.
    assert T._seconds("2026-09-22T15:04:05Z") == T._seconds("2026-09-22T15:04:05")


def test_the_trace_rules_are_written_down_and_followed():
    """#257 took the canvas away; the rules it kept are the trace's now. It reads the palette through
    the stylesheet rather than carrying one, it has its text twin, and nothing in `app.js` touches
    WebGL or a 2D context -- the ink layer is the only thing on the page that draws."""
    doc = open(os.path.join(ROOT, "docs", "desk-rendering.md"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    for rule in ("text twin", "getContext", "WebGL", "data-ink-series"):
        assert rule in doc, rule
    # No canvas in the markup at all, and every trace has its twin.
    assert "<canvas" not in html, "a canvas came back into the desk's markup"
    traces = re.findall(r"<svg class=\"trace\"[^>]*>", html)
    assert traces, "the trace is gone from the pane's head"
    for svg in traces:
        assert 'role="img"' in svg and "aria-label" in svg, svg
    # The trace reads the palette in the stylesheet, and `drawTrace` carries no colour of its own.
    for part, var in ((".trace .tr-line", "var(--running)"), (".trace .tr-ticks", "var(--human)")):
        assert var in css.split(part, 1)[1][:200], (part, var)
    body = js.split("function drawTrace(", 1)[1].split("\n}\n", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), "drawTrace carries a colour"
    assert "webgl" not in js.lower() and "getContext" not in js


def _two_d(text: str, script: bool = True) -> list[str]:
    """Every ask for a 2D context in `text` -- and, in a script, every bare `'2d'` that could be
    handed to one. A stylesheet cannot call anything, and its `"2d"` is two days (an age)."""
    pattern = r"getContext\(\s*['\"]2d['\"]" + (r"|['\"]2d['\"]" if script else "")
    return re.findall(pattern, text)


def test_nothing_under_static_asks_for_a_2d_context():
    """#257: one platform. The desk's own files -- the page, its scripts, the ink layer and every
    skin -- never ask for a 2D context, and never so much as name one. The vendored three.js is
    pinned by its sha256 (#247) and is not ours to edit; its own 2D paths are image utilities the
    layer never calls, and `test_nothing_on_the_page_asks_for_a_2d_context` holds that at run time."""
    found = {}
    for root, dirs, files in os.walk(STATIC):
        dirs[:] = [d for d in dirs if os.path.join(root, d) != os.path.join(STATIC, "vendor")]
        for name in files:
            if not name.endswith((".js", ".mjs", ".html", ".css", ".svg")):
                continue
            path = os.path.join(root, name)
            hits = _two_d(open(path, encoding="utf-8").read(), script=not name.endswith(".css"))
            if hits:
                found[os.path.relpath(path, STATIC)] = hits
    assert found == {}, f"a 2D context is asked for under static/: {found}"
    # And the scan is not blind: it finds what it is looking for.
    assert _two_d("c.getContext('2d')") and _two_d('x.getContext( "2d" )') and _two_d("k = '2d'")
    assert _two_d("a { b: c.getContext('2d') }", script=False) and not _two_d('"2d" ago', script=False)


# --------------------------------------------------------------------------------- in a browser


def _theme_rgb(page, token):
    """A palette token as the browser resolves it, `rgb(...)`: what a stroke of it computes to."""
    return page.evaluate("""t => {
      const probe = document.createElement('span');
      probe.style.color = getComputedStyle(document.documentElement).getPropertyValue(t).trim();
      document.body.appendChild(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return c;
    }""", token)


#: The trace of one pane, as the page wrote it: its words, its series, and its own SVG.
READ_TRACE = """repo => {
  const svg = document.querySelector(`.tile[data-repo="${repo}"] .trace`);
  const line = svg.querySelector('.tr-line'), ticks = svg.querySelector('.tr-ticks');
  const points = (line.getAttribute('points') || '').trim().split(/\\s+/).filter(Boolean)
                   .map(p => p.split(',').map(Number));
  const d = ticks.getAttribute('d') || '';
  return { label: svg.getAttribute('aria-label'), title: svg.querySelector('title').textContent,
           series: svg.getAttribute('data-ink-series'),
           ticks: svg.getAttribute('data-ink-ticks'), viewBox: svg.getAttribute('viewBox'),
           points, tickXs: [...d.matchAll(/M([\\d.]+)/g)].map(m => Number(m[1])),
           lineStroke: getComputedStyle(line).stroke, tickStroke: getComputedStyle(ticks).stroke,
           shown: getComputedStyle(line).visibility, display: getComputedStyle(svg).display };
}"""


@pytest.mark.browser
def test_the_drawn_trace_has_a_point_a_minute_and_the_red_ones_are_the_palettes(
        fleet_home, tmp_path):
    """Read back off what the page drew -- its own SVG, which is what every shell without ink shows
    (#257; it was a canvas read with `getImageData`). Anything less is asserting that a function was
    called."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    _agent(tmp_path, "beta", [{"ts": _at(now, 5), "kind": "tool_call"}])
    S.arrange(order=["alpha", "beta"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"]', timeout=15000)
            page.wait_for_function(
                """() => { const e = tiles.get('alpha');
                           return e && e.row.trace && e.row.trace.total >= 40
                                  && !!e.el.querySelector('.trace').getAttribute('aria-label'); }""",
                timeout=15000)
            out = page.evaluate(READ_TRACE, "alpha")
            got = page.evaluate("() => tiles.get('alpha').row.trace")
            human = _theme_rgb(page, "--human")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    # The fixture's forty events, in forty minutes. The current minute is left out of the count
    # because reading a repository's state appends its own housekeeping there, and a test that
    # pinned the total would be asserting when the server last looked at a `.agent/` directory
    # rather than anything about the hour.
    assert sum(got["n"][:-1]) == 40, got["n"]
    assert got["needed"] == 2
    # A point a minute, oldest on the left, and every minute with something in it off the floor.
    assert len(out["points"]) == 60 and out["viewBox"] == "0 0 60 18", out
    floor = max(y for _, y in out["points"])
    raised = [i for i, (_, y) in enumerate(out["points"]) if y < floor]
    assert raised == [i for i, n in enumerate(got["n"]) if n], (raised, got["n"])
    # The minutes that stopped for a person are the palette's own `--human`, which is how they are
    # told apart -- the height cannot say, because a quiet hour's busiest minute is one event.
    red = [i for i, v in enumerate(got["needs"]) if v]
    assert len(red) == 2 and out["tickXs"] == [i + 0.5 for i in red], (out["tickXs"], red)
    assert out["tickStroke"] == human, (out["tickStroke"], human)
    # The series the ink layer reads is the same hour.
    series = [float(v) for v in out["series"].split()]
    assert [i for i, v in enumerate(series) if v] == raised
    assert out["ticks"] == " ".join(str(i) for i in red)
    assert out["label"] == got["says"] and "needed you twice" in out["label"], out["label"]
    assert out["title"] == out["label"], "the tooltip is the same sentence"
    assert out["shown"] == "visible", "no ink on this page, so the SVG is the trace"


@pytest.mark.browser
def test_the_trace_follows_the_palette_with_nothing_drawn_again(fleet_home, tmp_path):
    """A canvas held pixels, not rules, and had to be repainted when the palette changed (#218; the
    accent stripe was the same bug in CSS, #215). The trace is the stylesheet's colours now (#257):
    the palette changes and it is already the new colour, with no script run to draw it again."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="alpha"]', timeout=15000)
            page.wait_for_function(
                """() => { const e = tiles.get('alpha');
                           return e && e.row.trace && e.row.trace.total >= 40
                                  && !!e.el.querySelector('.trace').getAttribute('data-ink-ticks'); }""",
                timeout=15000)
            before = page.evaluate(READ_TRACE, "alpha")
            assert before["tickStroke"] == _theme_rgb(page, "--human")

            S.act("theme", {"skin": "glass:noir"})
            page.wait_for_function(
                """() => document.body.dataset.skin === 'glass'
                         && document.body.dataset.skinVariant === 'noir'""", timeout=8000)
            page.wait_for_function(
                """() => { const probe = document.createElement('span');
                   probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--human').trim();
                   document.body.appendChild(probe); const c = getComputedStyle(probe).color; probe.remove();
                   return getComputedStyle(document.querySelector('.tile[data-repo="alpha"] .tr-ticks')).stroke === c; }""",
                timeout=8000)
            after = page.evaluate(READ_TRACE, "alpha")
            human = _theme_rgb(page, "--human")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert after["tickStroke"] == human, "the trace is a colour the stylesheet no longer has"
    assert after["tickStroke"] != before["tickStroke"], "noir has a --human of its own"
    assert after["tickXs"] == before["tickXs"]


@pytest.mark.browser
@pytest.mark.measured
def test_the_ground_drifts_under_glass_and_holds_still_when_asked_to(fleet_home, tmp_path):
    """A pixel a second is the difference between a still image and a room with a window in it.
    Reduced motion stops it (and reduced transparency, which Chromium cannot emulate yet) -- the
    second is the one people forget, and it is the setting somebody turns on *because* a moving
    translucent ground is what they cannot read over.

    #257: the ground is the ink layer's, drawn in its `ground` slot from the stylesheet's own
    gradients, so this reads `Ink.inspect()` with `?ink=on`. It costs a frame a second, counted in
    frames rather than milliseconds because CI draws in software (plan-ink ground rule 5)."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])
    S.act("theme", {"skin": "glass:smoke"})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for reduced in (False, True):
                page = browser.new_page(viewport={"width": 1400, "height": 900},
                                        reduced_motion="reduce" if reduced else "no-preference")
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid&ink=on",
                          wait_until="domcontentloaded")
                page.wait_for_selector(".tile.is-solo", timeout=15000)
                page.wait_for_function(
                    "() => { const l = window.Ink && Ink.inspect().layer; return !!l && l.ground.drawn; }",
                    timeout=20000)

                state = page.evaluate("() => Ink.inspect().layer.ground")
                assert state["blobs"] == 3, "the mesh is read from the stylesheet, and there are 3"
                assert state["moving"] is not reduced, state
                assert state["still"] is reduced, state

                # What it costs: a frame a second, and not sixty -- two seconds of drift, counted.
                if reduced:
                    cost = page.evaluate("""async () => {
                      // From rest: the frames the page's arrival asked for (its stylesheet, its
                      // palette) are drawn, and 600ms have passed without one.
                      const pause = ms => new Promise(done => setTimeout(done, ms));
                      let last = Ink.inspect().layer.renders, quiet = performance.now();
                      while (performance.now() - quiet < 600) {
                        await pause(50);
                        const n = Ink.inspect().layer.renders;
                        if (n !== last) { last = n; quiet = performance.now(); }
                      }
                      const l0 = Ink.inspect().layer;
                      await new Promise(done => setTimeout(done, 2200));
                      const l1 = Ink.inspect().layer;
                      return { renders: l1.renders - l0.renders, at: l1.ground.at - l0.ground.at }; }""")
                    assert cost == {"renders": 0, "at": 0}, f"a still ground drew {cost}"
                else:
                    r0 = page.evaluate("() => { const l = Ink.inspect().layer; return [l.renders, l.ground.at]; }")
                    page.wait_for_function(f"() => Ink.inspect().layer.ground.at >= {r0[1] + 2}", timeout=10000)
                    r1 = page.evaluate("() => { const l = Ink.inspect().layer; return [l.renders, l.ground.at]; }")
                    frames = r1[0] - r0[0]
                    print(f"ground: {frames} frames for {r1[1] - r0[1]}s of drift")
                    assert 1 <= frames <= 2 * (r1[1] - r0[1]) + 2, f"the ground drew {frames} frames"
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _pixel(page, x, y):
    shot = page.screenshot(clip={"x": x, "y": y, "width": 1, "height": 1})
    import struct
    import zlib
    # A 1x1 PNG: the one IDAT row, a filter byte and then RGB(A).
    data = shot[8:]
    raw = b""
    while data:
        n = struct.unpack(">I", data[:4])[0]
        kind = data[4:8]
        if kind == b"IDAT":
            raw += data[8:8 + n]
        data = data[12 + n:]
    px = zlib.decompress(raw)
    return tuple(px[1:4])


@pytest.mark.browser
def test_with_ink_the_ground_on_the_glass_is_the_layers(fleet_home, tmp_path):
    """#257: under glass with ink on, the ground the panes frost is drawn by the ink layer -- take
    the stylesheet's own gradients away and the blobs are still there; take the layer's canvas away
    as well and they are gone. Without ink, the stylesheet's gradients are the ground, still."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])
    S.act("theme", {"skin": "glass:smoke"})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid&ink=on",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_function(
                "() => { const l = window.Ink && Ink.inspect().layer; return !!l && l.ground.drawn && !l.busy; }",
                timeout=20000)
            # The centre of the blue blob (16% 10%), with everything on the page but the layer's
            # canvas out of sight, so the pixel is the ground's and nobody's text or card.
            x, y = int(1400 * 0.16), int(900 * 0.10)
            page.add_style_tag(content="body > *:not(#ink) { visibility: hidden !important; }")
            page.evaluate("() => { document.body.style.backgroundImage = 'none'; }")
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            inked = _pixel(page, x, y)
            page.evaluate("() => { document.getElementById('ink').style.visibility = 'hidden'; }")
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            flat = _pixel(page, x, y)
            page.evaluate("() => { document.getElementById('ink').style.removeProperty('visibility');"
                          " document.body.style.removeProperty('background-image'); }")
            assert not errors, errors
            page.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    diff = sum(abs(a - b) for a, b in zip(inked, flat))
    assert diff > 12, f"the layer drew no ground at the blob: {inked} against flat {flat}"


@pytest.mark.browser
def test_without_ink_the_trace_and_the_ground_are_the_pages_own(fleet_home, tmp_path):
    """#257, the fallback: a shell the gate turned off -- every shell nothing has measured as
    hardware -- has no canvas on the page at all. The trace is its SVG, with its minutes and its
    red ticks, and the ground is the stylesheet's gradients, standing still."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])
    S.act("theme", {"skin": "glass:smoke"})

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for extra in ("", "&ink=off"):
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid{extra}",
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    """() => !!window.Ink && document.body.dataset.skin === 'glass'
                             && !!document.querySelector('.tile.is-solo .trace[data-ink-ticks]')
                             && /radial-gradient/.test(getComputedStyle(document.body).backgroundImage)""",
                    timeout=15000)
                out = page.evaluate(READ_TRACE, "alpha")
                page_state = page.evaluate("""() => ({
                  off: document.body.classList.contains('ink-off'),
                  canvases: document.querySelectorAll('canvas').length, layer: Ink.inspect().layer,
                  ground: (getComputedStyle(document.body).backgroundImage.match(/radial-gradient/g) || []).length,
                  moving: getComputedStyle(document.body).animationName })""")
                assert not errors, errors
                page.close()
                assert page_state["off"] and page_state["canvases"] == 0 and page_state["layer"] is None, page_state
                assert page_state["ground"] == 3 and page_state["moving"] == "none", page_state
                assert out["shown"] == "visible" and out["display"] != "none", out
                assert len(out["points"]) == 60 and len(out["tickXs"]) == 2, out
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_with_ink_the_trace_is_a_mark_in_its_panes_lane_and_follows_its_data(fleet_home, tmp_path):
    """#257: where a skin draws with ink, the trace is the layer's -- a line in pen and a red tick
    through each minute that needed somebody, drawn in the pane's own lane from the series `drawTrace`
    wrote on the element, while the SVG steps aside. New numbers are a new line where it stands; a
    minute that no longer needs anybody loses its tick; an hour that empties is erased."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from test_fleet_ink import AT_REST, _choose, _no_skin_css
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            _no_skin_css(page)
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid&ink=on",
                      wait_until="domcontentloaded")
            page.wait_for_function(
                """() => !!window.Ink && !!Ink.inspect().layer
                         && !!document.querySelector('.tile.is-solo .trace[data-ink-ticks]')""",
                timeout=20000)
            assert page.evaluate("() => Ink.inspect().layer.series") == [], \
                "no skin draws with ink yet, so the SVG is the trace"
            _choose(page, "example")
            page.wait_for_function(
                f"""() => ({AT_REST})() && Ink.inspect().table === 'example'
                         && Ink.inspect().layer.series.length === 2""", timeout=20000)
            first = page.evaluate("() => Ink.inspect().layer.series")
            el = page.evaluate(READ_TRACE, "alpha")
            inked = page.evaluate("s => Ink.sample({x: s.x - 2, y: s.y - 2, w: s.w + 4, h: s.h + 4})",
                                  first[0]["box"])

            # New numbers: the row's hour, a minute on, with nobody asked for anything.
            page.evaluate("""() => { const e = tiles.get('alpha');
              const row = JSON.parse(JSON.stringify(e.row));
              row.trace.n = row.trace.n.slice(1).concat([3]);
              row.trace.needs = row.trace.n.map(() => 0);
              drawTrace(e.el.querySelector('.trace'), row); }""")
            page.wait_for_function(
                f"""() => ({AT_REST})() && Ink.inspect().layer.series.length === 1
                         && Ink.inspect().layer.series[0].series.endsWith(' 1')""", timeout=20000)
            moved = page.evaluate("() => Ink.inspect().layer.series")

            # An hour with nothing in it: there is no line to draw, and the one there was is erased.
            page.evaluate("""() => { const e = tiles.get('alpha');
              const row = JSON.parse(JSON.stringify(e.row));
              row.trace.n = row.trace.n.map(() => 0); row.trace.needs = row.trace.n.map(() => 0);
              row.trace.says = 'nothing in the last hour';
              drawTrace(e.el.querySelector('.trace'), row); }""")
            page.wait_for_function(f"() => ({AT_REST})() && Ink.inspect().layer.series.length === 0",
                                   timeout=20000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    by = {m["shape"]: m for m in first}
    line, ticks = by["series"], by["ticks"]
    assert (line["lane"], line["tool"], line["state"], line["drawn"]) == ("pane:alpha", "pen", "drawn", 1), line
    assert (ticks["lane"], ticks["tool"], ticks["strokes"]) == ("pane:alpha", "red", 2), ticks
    assert line["series"] == el["series"] and ticks["ticks"] == el["ticks"], (line, el)
    assert el["shown"] == "hidden", "a skin draws with ink: the SVG steps aside for the layer's trace"
    assert inked > 20, f"no ink in the trace's box: {inked}"
    assert len(moved) == 1 and moved[0]["shape"] == "series" and moved[0]["drawn"] == 1, moved
    assert moved[0]["series"] != line["series"], "the line did not follow its data"


@pytest.mark.browser
def test_nothing_on_the_page_asks_for_a_2d_context(fleet_home, tmp_path):
    """#257, at run time: every call to `getContext` on the desk, with ink on under glass (the
    layer's ground) and an ink skin (its traces), and with ink off. No canvas on the page is ever
    asked for a 2D context: the layer's is WebGL, and with ink off there is none. This is the half
    the file scan cannot see -- the vendored three.js included, whose `WebGLRenderer` makes exactly
    one ask of its own: a 1x1 `OffscreenCanvas`, never on the page, to learn whether it could
    resize a texture off-screen. It draws nothing with it, and the file is pinned by its sha256
    (#247), so that one ask is named here rather than patched out."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from test_fleet_ink import AT_REST, _choose, _no_skin_css
    now = time.time()
    _agent(tmp_path, "alpha", _busy_hour(now))
    S.arrange(order=["alpha"])
    S.act("theme", {"skin": "glass:smoke"})

    asked = {}
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for extra in ("&ink=on", ""):
                context = browser.new_context(viewport={"width": 1400, "height": 900})
                context.add_init_script("""
                  window.__contexts = [];
                  for (const C of [window.HTMLCanvasElement, window.OffscreenCanvas]) {
                    if (!C) continue;
                    const real = C.prototype.getContext;
                    C.prototype.getContext = function (kind) {
                      window.__contexts.push({ kind: String(kind), on: C.name, size: [this.width, this.height],
                                               three: /three\.module\.min\.js/.test(String(new Error().stack)) });
                      return real.apply(this, arguments);
                    };
                  }""")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                _no_skin_css(page)
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid{extra}",
                          wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => !!window.Ink && !!document.querySelector('.tile.is-solo .trace[data-ink-ticks]')",
                    timeout=20000)
                if extra:
                    page.wait_for_function(
                        "() => { const l = Ink.inspect().layer; return !!l && l.ground.drawn; }", timeout=20000)
                    _choose(page, "example")
                    page.wait_for_function(
                        f"() => ({AT_REST})() && Ink.inspect().layer.series.length === 2", timeout=20000)
                    page.evaluate("() => Ink.sample({x: 0, y: 0, w: 40, h: 40})")
                asked[extra or "off"] = page.evaluate("() => window.__contexts")
                assert not errors, errors
                context.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    on = asked["&ink=on"]
    page_asks = [a for a in on if a["on"] == "HTMLCanvasElement"]
    assert page_asks and {a["kind"] for a in page_asks} <= {"webgl2", "webgl"}, on
    three = [a for a in on if a["kind"].lower() == "2d"]
    assert three == [{"kind": "2d", "on": "OffscreenCanvas", "size": [1, 1], "three": True}], on
    assert asked["off"] == [], asked


@pytest.mark.browser
def test_the_trace_never_costs_the_head_a_second_line(fleet_home, tmp_path):
    """The head carries the trace only where there is room for it. A title bar that wrapped to two
    lines to fit a picture is a picture that cost more than it is worth -- and `flex-wrap` wraps
    before it shrinks, so the trace has to be gone by the width at which it *would* wrap, not by
    the width at which it stops fitting."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    now = time.time()
    for name in ("alpha", "beta", "gamma"):
        _agent(tmp_path, name, _busy_hour(now))
    S.arrange(order=["alpha", "beta", "gamma"])

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile .head", timeout=15000)

            seen = []
            for width in (1100, 1440, 1600, 2000, 2560):
                page.set_viewport_size({"width": width, "height": 950})
                page.wait_for_timeout(200)
                seen.append(page.evaluate("""() => {
                  const tile = document.querySelector('.tile');
                  const head = tile.querySelector('.head');
                  return { tile: Math.round(tile.getBoundingClientRect().width),
                           head: Math.round(head.getBoundingClientRect().height),
                           trace: getComputedStyle(head.querySelector('.trace')).display };
                }""")) 
            assert not errors, errors
            for row in seen:
                assert row["head"] <= 34, f"the head wrapped at {row['tile']}px: {row}"
            assert any(r["trace"] != "none" for r in seen), \
                f"the trace is never on a tile at all: {seen}"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
