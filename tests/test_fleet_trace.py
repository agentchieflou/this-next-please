"""The shape of the hour, and the ground it is drawn on (issue #218).

A tile says what an agent is doing now and carries forty events for its transcript. What it could
not say is the shape of the hour: whether this quiet minute follows fifty busy ones or four
hundred quiet ones, and whether the operator has already been asked something in that time. Those
are the two questions somebody scanning nine tiles is actually asking, and `idle · 3m` answers
neither.

The rules a canvas on this page keeps are in `docs/desk-rendering.md`. What is asserted here is
that they hold: the colours come from the stylesheet, the picture has a text twin, nothing is
drawn that the row does not carry, and the ground costs a millisecond a second.
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


def test_the_canvas_rules_are_written_down_and_followed():
    doc = open(os.path.join(ROOT, "docs", "desk-rendering.md"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    for rule in ("text twin", "devicePixelRatio", "WebGL"):
        assert rule in doc, rule
    # A canvas reads the palette rather than carrying one.
    assert "function token(name, fallback)" in js
    assert "function forgetTokens()" in js
    # And every canvas on the page has its twin.
    for canvas in re.findall(r"<canvas[^>]*>", html):
        if 'id="ground"' in canvas:
            assert 'aria-hidden="true"' in canvas, "the ground says nothing, so it says so"
            continue
        assert 'role="img"' in canvas and "aria-label" in canvas, canvas
    # No WebGL until slice F's engine rows say the shells run it.
    assert "webgl" not in js.lower()


# --------------------------------------------------------------------------------- in a browser


@pytest.mark.browser
def test_the_drawn_trace_has_a_mark_a_minute_and_the_red_ones_are_the_palettes(
        fleet_home, tmp_path):
    """Read back off the canvas. Anything less is asserting that a function was called."""
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
                           return e && e.row.trace && e.row.trace.total >= 40; }""",
                timeout=15000)

            out = page.evaluate("""() => {
              // Widened first: sixty buckets in sixty-four pixels is a bucket a pixel, and a test
              // that reads columns back needs a column it can point at.
              const canvas = document.querySelector('.tile[data-repo="alpha"] .trace');
              canvas.style.display = 'block';
              canvas.style.width = '300px';
              drawTrace(canvas, tiles.get('alpha').row);
              const ctx = canvas.getContext('2d');
              const w = canvas.width, h = canvas.height;
              const slot = w / 60;
              const marks = [];
              const red = [];
              const want = getComputedStyle(document.documentElement)
                             .getPropertyValue('--human').trim();
              const probe = document.createElement('span');
              probe.style.color = want;
              document.body.appendChild(probe);
              const humanRgb = getComputedStyle(probe).color;
              probe.remove();
              for (let i = 0; i < 60; i++) {
                // The bottom row: every bar is drawn up from the floor, whatever its height. A
                // minute that stopped for a person is the palette's own `--human`, which is how
                // it is told apart -- the height cannot say, because a quiet hour's busiest
                // minute is one event and then every bar is full height.
                const px = ctx.getImageData(Math.round(i * slot) + 1, h - 2, 1, 1).data;
                if (px[3] === 0) continue;
                const rgb = `rgb(${px[0]}, ${px[1]}, ${px[2]})`;
                marks.push(i);
                if (rgb === humanRgb) red.push(i);
              }
              return { marks: marks.length, red: red, humanRgb,
                       label: canvas.getAttribute('aria-label') };
            }""")
            assert not errors, errors
            # The fixture's forty events, in forty minutes. The current minute is left out of the
            # count because reading a repository's state appends its own housekeeping there, and a
            # test that pinned the total would be asserting when the server last looked at a
            # `.agent/` directory rather than anything about the hour.
            got = page.evaluate("() => tiles.get('alpha').row.trace")
            assert sum(got["n"][:-1]) == 40, got["n"]
            assert got["needed"] == 2
            assert out["marks"] == sum(1 for n in got["n"] if n), (out["marks"], got["n"])
            assert len(out["red"]) == 2, out["red"]
            # And they are the minutes the row says they are.
            assert out["red"] == [i for i, v in enumerate(got["needs"]) if v], out["red"]
            assert out["label"] == got["says"]
            assert "needed you twice" in out["label"], out["label"]
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_trace_is_repainted_when_the_palette_changes(fleet_home, tmp_path):
    """A canvas holds pixels, not rules. The accent stripe was the same bug in CSS (#215); this is
    it in a bitmap, and the answer is the same -- one owner, and it repaints."""
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
                           return e && e.row.trace && e.row.trace.total >= 40; }""",
                timeout=15000)

            read = """() => {
              const canvas = document.querySelector('.tile[data-repo="alpha"] .trace');
              canvas.style.display = 'block';
              canvas.style.width = '300px';
              drawTrace(canvas, tiles.get('alpha').row);
              const ctx = canvas.getContext('2d');
              const w = canvas.width, h = canvas.height, slot = w / 60;
              for (let i = 0; i < 60; i++) {
                const px = ctx.getImageData(Math.round(i * slot) + 1, 1, 1, 1).data;
                if (px[3] > 0) return `rgb(${px[0]}, ${px[1]}, ${px[2]})`;
              }
              return '';
            }"""
            before = page.evaluate(read)
            assert before, "nothing red was drawn at all"

            S.act("theme", {"skin": "glass:noir"})
            page.wait_for_function(
                "() => document.body.dataset.skin === 'glass'", timeout=8000)
            page.wait_for_timeout(500)
            after = page.evaluate(read)
            token_now = page.evaluate("""() => {
              const probe = document.createElement('span');
              probe.style.color = getComputedStyle(document.documentElement)
                                    .getPropertyValue('--human').trim();
              document.body.appendChild(probe);
              const c = getComputedStyle(probe).color;
              probe.remove();
              return c;
            }""")
            assert not errors, errors
            assert after == token_now, "the canvas is a colour the stylesheet no longer has"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
@pytest.mark.measured
def test_the_ground_drifts_under_glass_and_holds_still_when_asked_to(fleet_home, tmp_path):
    """A pixel a second is the difference between a still image and a room with a window in it.
    Reduced motion and reduced transparency each stop it -- the second is the one people forget,
    and it is the setting somebody turns on *because* a moving translucent ground is what they
    cannot read over."""
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
                page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid",
                          wait_until="domcontentloaded")
                page.wait_for_selector(".tile", timeout=15000)
                page.wait_for_function(
                    "() => !document.getElementById('ground').hidden", timeout=15000)

                state = page.evaluate("""() => ({
                  mesh: (groundMesh || []).length,
                  blanked: getComputedStyle(document.body).backgroundImage === 'none',
                  timer: !!groundTimer,
                })""")
                assert state["mesh"] == 3, "the mesh is read from the stylesheet, and there are 3"
                assert state["blanked"], "the canvas and the gradients are both painting"
                assert state["timer"] is not reduced, state

                # And it costs what it claims to: three soft blobs at half resolution.
                cost = page.evaluate("""() => {
                  const runs = [];
                  for (let i = 0; i < 12; i++) {
                    const t = performance.now();
                    groundAt += 1;
                    drawGround();
                    runs.push(performance.now() - t);
                  }
                  runs.sort((a, b) => a - b);
                  return runs[Math.floor(runs.length / 2)];
                }""")
                print(f"ground repaint: {cost:.2f}ms (reduced={reduced})")
                assert cost < 4.0, f"the ground costs {cost:.2f}ms a second"
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


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
