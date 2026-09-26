"""A restored desk resumes the stream (#347).

Coming back to the desk -- from /settings, with Back, or on a reload -- draws the tiles from the
window's snapshot first (#219). The snapshot keeps no transcript, so those tiles were made with
`seq: 0`, and the real `/api/fleet` row that followed took the existing-tile path, which neither
appended its `recent` nor moved the cursor. `connect()` then asked for `since=<repo>:0,...` and the
server replayed every agent's whole history: 3,627 frames on a nine-agent desk, 2-3 s long tasks,
and the previous skin's ink for five to seven seconds.

A restored tile now treats its first real row the way a new tile does: it appends the row's
`recent` and takes its cursor from it, so the stream opens after the rows it was given.

`RECORDER` is an init script: it wraps `EventSource` to keep each stream's URL and to count its
`agent` and `tick` frames, and keeps every long task's duration. The regression imports it.

One browser for the module; a server per test. Every wait is on a condition.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from agentdata.fleet import events as E, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_instant import _serve, fleet_home  # noqa: F401 - fixtures

REPOS = ("proj0", "proj1", "proj2")
EVENTS = 150

RECORDER = """
(() => {
  window.__streams = [];
  window.__long = [];
  const Real = window.EventSource;
  function Recorded(url, opts) {
    const es = new Real(url, opts);
    const rec = { url: String(url), open: false, agent: 0, tick: 0 };
    window.__streams.push(rec);
    es.addEventListener("open", () => { rec.open = true; });
    es.addEventListener("agent", () => { rec.agent++; });
    es.addEventListener("tick", () => { if (rec.open) rec.tick++; });
    return es;
  }
  Recorded.prototype = Real.prototype;
  Object.assign(Recorded, { CONNECTING: 0, OPEN: 1, CLOSED: 2 });
  window.EventSource = Recorded;
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) window.__long.push(Math.round(e.duration));
    }).observe({ type: "longtask", buffered: true });
  } catch (e) {}
})();
"""

# The desk has had its first answer, is no longer marked stale, and its stream has opened and sent
# a tick. The server writes a pass's agent frames before that pass's tick, so every frame a replay
# would send has arrived by then.
RESUMED = """() => {
  const s = window.__streams || [];
  const last = s[s.length - 1];
  return !!lastFleet && !document.body.classList.contains('is-stale') && !!last && last.tick >= 1;
}"""

SNAPPED = "() => { try { return !!sessionStorage.getItem(SNAP_KEY); } catch (e) { return false; } }"

TRANSCRIPTS = """() => Object.fromEntries([...document.querySelectorAll('#grid .tile')].map(t =>
  [t.dataset.repo, [...t.querySelectorAll('.transcript li')].map(li => li.textContent)]))"""

STREAM = """() => { const s = window.__streams[window.__streams.length - 1];
                   const answered = Object.fromEntries(lastFleet.repos.map(r =>
                     [r.repo, (r.recent || []).length ? r.recent[r.recent.length - 1].seq : 0]));
                   return { url: s.url, agent: s.agent, tick: s.tick, streams: window.__streams.length,
                            answered: answered, long: window.__long.slice() }; }"""


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        b = launch_chromium(p)
        yield b
        b.close()


def busy_fleet(tmp_path, names=REPOS, events=EVENTS):
    """`names` agents with `events` events each, every one of them a transcript line after the two
    that open a session. Returns each agent's newest seq."""
    newest = {}
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        evs = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
               E.event(name, "session_id", {"session": "s-" + name}, ticket="RDSD-1")]
        evs += [E.event(name, "assistant_text", {"text": f"{name} line {i}", "model": "m"},
                        ticket="RDSD-1") for i in range(events - 2)]
        newest[name] = E.append(name, evs)
    return newest


def since(url):
    """`{repo: seq}` from a stream URL's `since=repo:seq,...`."""
    raw = parse_qs(urlparse(url).query).get("since", [""])[0]
    return {part.rsplit(":", 1)[0]: int(part.rsplit(":", 1)[1]) for part in raw.split(",") if part}


def open_desk(context, port, token):
    page = context.new_page()
    page.add_init_script(RECORDER)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
    page.wait_for_function(RESUMED, timeout=20000)
    return page, errors


def restored(browser, port, token):
    """A desk opened, snapshotted, then reloaded: what its stream asked for and was sent, and its
    transcripts once the stream has resumed."""
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    try:
        page, errors = open_desk(context, port, token)
        page.wait_for_function(SNAPPED, timeout=8000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(RESUMED, timeout=20000)
        seen = page.evaluate(STREAM)
        seen["transcripts"] = page.evaluate(TRANSCRIPTS)
        seen["errors"] = errors
        return seen
    finally:
        context.close()


@pytest.mark.browser
def test_a_restored_desk_resumes_the_stream_from_the_rows_it_was_given(browser, fleet_home, tmp_path):
    newest = busy_fleet(tmp_path)
    S.arrange(order=list(REPOS))
    server, token, port = _serve()
    try:
        back = restored(browser, port, token)
        print(f"\nrestored: since={urlparse(back['url']).query.split('since=')[-1]} "
              f"agentFrames={back['agent']} longest longtask={max(back['long'] or [0])}ms "
              f"longtasks={back['long']}")
        assert not back["errors"], back["errors"]
        assert back["streams"] == 1, back
        cursors = since(back["url"])
        assert cursors == back["answered"], f"the stream did not open after the rows it was given: {cursors}"
        assert all(cursors[name] >= newest[name] > 0 for name in REPOS), (cursors, newest)
        assert back["agent"] == 0, f"{back['agent']} agent frames replayed after the stream opened"

        # A tile made from a live row, in a window with no snapshot: as it always was.
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        try:
            fresh, errors = open_desk(context, port, token)
            live = fresh.evaluate(STREAM)
            transcripts = fresh.evaluate(TRANSCRIPTS)
            assert not errors, errors
        finally:
            context.close()
        assert since(live["url"]) == live["answered"], live["url"]
        assert live["agent"] == 0, live

        assert set(transcripts) == set(REPOS), transcripts.keys()
        for name in REPOS:
            assert len(transcripts[name]) == 40, (name, len(transcripts[name]))
            assert any(l.endswith(f"{name} line {EVENTS - 3}") for l in transcripts[name][-3:]), transcripts[name][-3:]
        assert back["transcripts"] == transcripts, "a restored tile's transcript differs from a fresh one's"
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_restored_tile_still_takes_what_arrives_after_the_answer(browser, fleet_home, tmp_path):
    """Resuming is not ignoring: an event appended after the desk came back reaches its tile once,
    down the stream, after the forty the first answer brought."""
    busy_fleet(tmp_path)
    S.arrange(order=list(REPOS))
    server, token, port = _serve()
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    try:
        page, errors = open_desk(context, port, token)
        page.wait_for_function(SNAPPED, timeout=8000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(RESUMED, timeout=20000)
        before = page.evaluate(TRANSCRIPTS)["proj1"]
        E.append("proj1", [E.event("proj1", "assistant_text", {"text": "proj1 after the answer",
                                                               "model": "m"}, ticket="RDSD-1")])
        page.wait_for_function(
            """() => [...document.querySelectorAll('.tile[data-repo="proj1"] .transcript li')]
                     .some(li => li.textContent.endsWith('proj1 after the answer'))""", timeout=20000)
        lines = page.evaluate(TRANSCRIPTS)["proj1"]
        assert len(before) == 40, len(before)
        assert lines[:len(before)] == before, "the forty the answer brought were drawn again"
        new = lines[len(before):]
        assert sum(1 for l in new if l.endswith("proj1 after the answer")) == 1, new
        assert not any(" line " in l for l in new), f"old lines replayed: {new}"
        assert not errors, errors
    finally:
        context.close()
        server.stopping.set()
        server.shutdown()
        server.server_close()
