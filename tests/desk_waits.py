"""One way to wait for the desk, and one way to say it wrote nothing (#304).

Every idle test and render-contract test waits for the same thing: a desk with no fetch in flight,
no short timer pending, no DOM write, its fonts loaded, no animation running but the live `.dot`,
the ink layer at rest and not drawing. `settle` waits for that, counted in frames, and fails
loudly -- naming what was still moving -- when the desk never gets there. The negative
assertions (`assert_idle`, `observe_quiet`) are observed over page work, never over a duration:
a pass ends when the work it started is done, not when some milliseconds have gone by.

* `DESK_WAIT_MS` -- the one ceiling for a desk condition wait. `AGENTDATA_DESK_WAIT_SCALE` scales
  it for a local throttled run; CI never sets it.
* `COUNT_TIMERS` -- an init script (every `desk_harness.desk_page` has it, with `COUNT_FETCHES`):
  pending `setTimeout` callbacks of 1000 ms or less as `window.__timers`, and
  `window.__noFetchInFlight(ms)`. It also puts this module's page side, `window.__deskWaits`, on
  the page.
* `settle(page, *, quiet_frames=6, also=None, allow_ground=False)` -- waits for the desk to be
  still for `quiet_frames` frames running; raises `AssertionError("the desk never settled: ...")`.
* `assert_idle(page, *, passes=8, ground_moves=False)` -- settle, then replay `/api/fleet` byte
  for byte and drive `refresh(); place(); redrawAll(); bell();` `passes` times under one
  observer: zero writes, and zero ink renders unless the ground moves.
* `observe_quiet(page, *, passes=3, drive=True, also=None)` -- the same window, returned rather
  than asserted; `drive=False` leaves the page alone and counts its own work (a refresh it starts
  itself, `COUNT_REFRESHES`; a retry it arms) as the passes.
* `animations_done(page, selector=None)` -- no animation running (the `.dot` excepted).
* `record_mutations(page, ...)` -- one observer, installed now or at page load, read back later.
* `WATCH` -- the page side as source, for page code that watches a node inside one evaluate.

`new MutationObserver` is written here and nowhere else under `tests/` (`tests/test_desk_waits.py`
keeps it so).
"""
from __future__ import annotations

import itertools
import json
import os

#: The one ceiling for desk condition waits, in ms. The scale is for local throttled runs.
DESK_WAIT_MS = 30000 * float(os.environ.get("AGENTDATA_DESK_WAIT_SCALE", "1"))

#: The paper has come to rest: nothing queued or drawing in any lane, and no hand still lifting off.
AT_REST = """() => { const l = Ink.inspect().layer;
  return !!l && !l.busy && !Object.values(l.lanes).some(x => x.hand); }"""

#: The page side: `window.__deskWaits` with `watch`, `settle`, `quiet`, `drained` and `running`.
#: Idempotent.
#: Its own waits use the page's setTimeout from before `COUNT_TIMERS` wrapped it, so they are never
#: counted as the page's work.
WATCH = """;(() => {
  if (window.__deskWaits) return;
  const later = window.__realSetTimeout || window.setTimeout.bind(window);
  const say = r => r.type + ' ' + (r.attributeName || '') + ' ' +
    (r.target.id || (typeof r.target.className === 'string' && r.target.className) || r.target.nodeName);
  const ALL = { subtree: true, childList: true, attributes: true, characterData: true };
  // One observer: every record counted (or those `where` keeps), the first 50 kept as words, and
  // `on` handed each batch as the observer delivers it.
  const watch = (target, options, how) => {
    const on = typeof how === 'function' ? how : (how && how.on);
    const where = how && typeof how === 'object' && how.where;
    const h = { n: 0, seen: [], mark: 0 };
    const take = rs => {
      if (on) on(rs);
      for (const r of rs) {
        if (where && !where(r)) continue;
        h.n += 1;
        if (h.seen.length < 50) h.seen.push(say(r));
      }
    };
    const obs = new MutationObserver(take);
    obs.observe(target || document.documentElement || document, Object.assign({}, ALL, options || {}));
    h.flush = () => { const rs = obs.takeRecords(); if (rs.length) take(rs); return h; };
    h.count = () => h.flush().n;
    h.records = () => h.flush().seen.slice();
    h.fresh = () => { h.flush(); const n = h.n - h.mark, from = h.mark; h.mark = h.n;
                      return { n, seen: h.seen.slice(from, from + 5) }; };
    h.stop = () => { h.flush(); obs.disconnect(); return h; };
    return h;
  };
  const tick = () => new Promise(done => {
    let went = false; const go = () => { if (!went) { went = true; done(); } };
    requestAnimationFrame(go); later(go, 100);
  });
  const layer = () => { try { return window.Ink ? Ink.inspect().layer : null; } catch (e) { return null; } };
  const renders = () => { const l = layer(); return l ? l.renders : 0; };
  const pending = ground => (window.__timerList ? window.__timerList() : [])
    .filter(t => !(ground && t.ink));
  const running = selector => {
    const on = selector ? [...document.querySelectorAll(selector)].flatMap(e => e.getAnimations({ subtree: true }))
                        : document.getAnimations();
    return on.filter(a => a.playState === 'running' && !(a.effect && a.effect.target &&
      a.effect.target.closest && a.effect.target.closest('.dot')))
      .map(a => (a.animationName || a.transitionProperty || a.id || 'animation') + ' on ' +
        ((a.effect && a.effect.target && (a.effect.target.id || a.effect.target.className)) || '?'));
  };
  const counted = () => typeof window.__inflight === 'number' && typeof window.__timerList === 'function';
  const UNCOUNTED = 'the page counts no fetches or timers: open it with desk_harness.desk_page ' +
                    '(COUNT_FETCHES and desk_waits.COUNT_TIMERS)';
  // What is still moving on the page this frame, as sentences; empty when it is still.
  const moving = (o, w, was) => {
    const now = [];
    if (window.__inflight > 0) now.push(window.__inflight + ' fetch(es) in flight');
    const ts = pending(o.ground);
    if (ts.length) now.push(ts.length + ' short timer(s) pending: ' +
                            ts.slice(0, 3).map(t => t.delay + 'ms from ' + t.from).join('; '));
    if (w) { const f = w.fresh(); if (f.n) now.push(f.n + ' DOM mutation(s): ' + f.seen.join('; ')); }
    if (document.fonts && document.fonts.status !== 'loaded') now.push('fonts ' + document.fonts.status);
    const an = running();
    if (an.length) now.push(an.length + ' animation(s) running: ' + an.slice(0, 3).join('; '));
    const l = layer();
    if (l && (l.busy || Object.values(l.lanes).some(x => x.hand)))
      now.push('the ink layer is not at rest: ' + (l.busy ? 'busy' : 'a hand is lifting off'));
    if (!o.ground && was !== undefined && renders() !== was.renders)
      now.push("the ink layer's renders went " + was.renders + ' -> ' + renders());
    if (was !== undefined) was.renders = renders();
    if (o.also) {
      let ok = false;
      try { ok = !!o.also(); } catch (e) { now.push('also threw ' + e.message); }
      if (!ok) now.push('also is false: ' + o.alsoSays);
    }
    return now;
  };
  // Still for `quiet` frames running, or `{settled: false, moving}` once nothing has moved it on
  // for `ms`. The ink layer drawing its way to rest is moving on: a pen keeps time in frames, and
  // in SwiftShader a frame costs a tenth of a second idle and more than one on a loaded runner (a
  // felt tip's desk rests in about 57 frames: 5 s idle, 40 s at a load of 45 -- #479, #254). So
  // the clock restarts at each frame the layer draws, and a layer that draws the frames `ms` is at
  // 60 Hz without resting -- a pen that never lifts -- fails too.
  const settle = async o => {
    if (!counted()) return { settled: false, moving: [UNCOUNTED] };
    const t0 = performance.now(), w = watch(document.documentElement), was = { renders: renders() };
    const drawn = () => { const l = layer(); return l && typeof l.frames === 'number' ? l.frames : 0; };
    const f0 = drawn();
    let calm = 0, frames = 0, why = [], last = t0, seen = f0;
    try {
      for (;;) {
        await tick();
        frames += 1;
        const now = moving(o, w, was);
        if (now.length) { calm = 0; why = now; }
        else if (++calm >= o.quiet) return { settled: true, frames, ms: Math.round(performance.now() - t0) };
        if (drawn() > seen) { seen = drawn(); last = performance.now(); }
        if (performance.now() - last > o.ms) return { settled: false, moving: why, frames };
        if (seen - f0 > o.ms * 60 / 1000)
          return { settled: false, moving: ['the ink layer drew ' + (seen - f0) + ' frames without resting'].concat(why), frames };
      }
    } finally { w.stop(); }
  };
  // The work a pass started is done: no fetch in flight and no short timer pending, then two frames.
  const drained = async o => {
    const t0 = performance.now();
    for (;;) {
      await tick();
      const ts = pending(o.ground);
      if (!(window.__inflight > 0) && !ts.length && (!o.also || o.also())) break;
      if (performance.now() - t0 > o.ms)
        throw new Error('a pass never went quiet: ' + (window.__inflight || 0) + ' fetch(es) in flight, ' +
                        ts.map(t => t.delay + 'ms from ' + t.from).join('; '));
    }
    await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame);
  };
  // `/api/fleet` answered with one body, byte for byte: a live answer carries ages that are MEANT
  // to move a chip once a second, and idle means the same answer.
  const replay = async () => {
    if (window.__deskWaitsReplay) return;
    const real = window.fetch;
    const body = await (await real.call(window, q('/api/fleet'))).text();
    window.__deskWaitsReplay = true;
    window.fetch = function (url, opts) {
      if (String(url).indexOf('/api/fleet') >= 0) {
        return Promise.resolve(new Response(body, {
          status: 200, headers: { 'Content-Type': 'application/json' } }));
      }
      return real.apply(this, arguments);
    };
  };
  const pass = async o => { await refresh(); place(); redrawAll(); bell(); await drained(o); };
  // The idle window: `passes` passes of page work under one observer over the whole document.
  // `drive` makes each pass (after two warm-up passes and a settle). Otherwise the page is left
  // alone and each pass is its own work: what it has in flight or pending -- a refresh it started
  // itself (`COUNT_REFRESHES`), a retry it armed -- run out, then two frames.
  const quiet = async o => {
    if (!counted()) return { error: UNCOUNTED };
    if (typeof window.__deskRefreshes !== 'number') return { error: 'the page counts no refreshes: ' + UNCOUNTED };
    if (o.drive) {
      let s = await settle({ quiet: 6, ms: o.ms, ground: o.ground });
      if (!s.settled) return { error: 'the desk never settled', moving: s.moving };
      await replay();
      // Two: the first can be a refresh that began before the replay, and hands back its promise.
      // Then settle again: a trace that moved on since the page's last poll is drawn by the
      // layer (#257), a frame that can land after the pass on a slow runner.
      await pass(o); await pass(o);
      s = await settle({ quiet: 6, ms: o.ms, ground: o.ground });
      if (!s.settled) return { error: 'the desk never settled after the warm-up passes', moving: s.moving };
    }
    const before = renders(), w = watch(document.documentElement), own = window.__deskRefreshes;
    try {
      for (let i = 0; i < o.passes; i++) {
        if (o.drive) await pass(o);
        else { await tick(); await drained(o); }
      }
    } catch (e) {
      return { error: e.message };
    } finally { w.stop(); }
    return { mutations: w.n, records: w.seen.slice(0, 5), renders: renders() - before,
             refreshes: window.__deskRefreshes - own };
  };
  window.__deskWaits = { watch, settle, quiet, drained, tick, running, say, recorders: {} };
})();
"""

#: The refreshes the page starts itself, as `window.__deskRefreshes`: `refresh` wrapped once the page
#: has defined it (app.js's calls go through the global binding). Part of `COUNT_TIMERS`.
COUNT_REFRESHES = """;(() => {
  if (typeof window.__deskRefreshes === 'number') return;
  window.__deskRefreshes = 0;
  const wrap = () => {
    const real = window.refresh;
    if (typeof real !== 'function' || real.__counted) return;
    const counted = function () { window.__deskRefreshes += 1; return real.apply(this, arguments); };
    counted.__counted = true;
    window.refresh = counted;
  };
  addEventListener('DOMContentLoaded', wrap);
  addEventListener('load', wrap);
})();
"""

#: The page's short timers (a delay of 1000 ms or less) counted while pending, as `window.__timers`
#: (and `window.__timerList()`, each with where it was set from), and `window.__noFetchInFlight(ms)`:
#: resolves once `window.__inflight` (`COUNT_FETCHES`) is 0, rejects with an `Error` after `ms`.
#: A timer set from an ink module (`/static/ink/`) is marked `ink`: a ground that moves on its own
#: clock is allowed its timer where the test allows the ground (`allow_ground`, `ground_moves`).
COUNT_TIMERS = """;(() => {
  if (window.__timerList) return;
  const set = window.setTimeout.bind(window), clear = window.clearTimeout.bind(window);
  const live = new Map();
  window.__realSetTimeout = set;
  window.setTimeout = function (fn, delay) {
    const d = Number(delay) || 0;
    if (d > 1000) return set.apply(null, arguments);
    const from = ((new Error()).stack || '').split('\\n').slice(2, 3).join('').trim()
      .replace(/^at /, '').replace(location.origin, '');
    const rest = Array.prototype.slice.call(arguments, 2);
    const id = set(function () {
      live.delete(id);
      return typeof fn === 'function' ? fn.apply(this, rest) : (0, eval)(String(fn));
    }, delay);
    live.set(id, { delay: d, from, ink: from.indexOf('/static/ink/') >= 0 });
    return id;
  };
  window.clearTimeout = function (id) { live.delete(id); return clear(id); };
  Object.defineProperty(window, '__timers', { get: () => live.size, configurable: true });
  window.__timerList = () => [...live.values()];
  window.__noFetchInFlight = ms => new Promise((ok, no) => {
    const t0 = performance.now();
    const look = () => {
      if (!(window.__inflight > 0)) return ok(true);
      if (performance.now() - t0 > ms) return no(new Error(window.__inflight + ' fetch(es) still in flight after ' + ms + 'ms'));
      set(look, 25);
    };
    look();
  });
})();
""" + COUNT_REFRESHES + WATCH



def counted(page):
    """Count `page`'s fetches, timers and refreshes from its next load (`COUNT_FETCHES`,
    `COUNT_TIMERS`), as every `desk_harness.desk_page` does: for a page a test opened itself."""
    from desk_harness import COUNT_FETCHES

    for script in (COUNT_FETCHES, COUNT_TIMERS):
        page.add_init_script(script)
    return page


def install(page) -> None:
    """Put the page side (`WATCH`) on a page that was not opened with `COUNT_TIMERS`."""
    page.evaluate(f"() => {{ {WATCH} }}")


def _explain(page, what: str) -> None:
    from conftest import _explain_the_page

    _explain_the_page(page, what)


def _also(also) -> str:
    return "null" if also is None else f"() => ({also})"


def settle(page, *, quiet_frames: int = 6, also=None, allow_ground: bool = False) -> dict:
    """Wait until `quiet_frames` frames in a row pass with nothing moving on the page: no fetch in
    flight, no short timer pending, no DOM mutation, the fonts loaded, no animation running but
    `.dot`, the ink layer off or at rest (`AT_REST`) and -- unless `allow_ground` -- not rendering,
    and `also` (a JS expression) true. When nothing has moved it on for `DESK_WAIT_MS` -- the
    ink layer drawing a frame is moving on; a layer that draws the frames `DESK_WAIT_MS` is at 60 Hz
    without resting is not -- it prints the page and raises, naming what was still moving.
    Returns `{settled, frames, ms}`."""
    install(page)
    out = page.evaluate(
        f"""(o) => __deskWaits.settle(Object.assign(o, {{ also: {_also(also)} }}))""",
        {"quiet": int(quiet_frames), "ms": DESK_WAIT_MS, "ground": bool(allow_ground),
         "alsoSays": "" if also is None else str(also)[:200]})
    if not out.get("settled"):
        _explain(page, "settle")
        raise AssertionError("the desk never settled: " + "; ".join(out.get("moving") or ["?"]))
    return out


def observe_quiet(page, *, passes: int = 3, drive: bool = True, also=None,
                  ground_moves: bool = False) -> dict:
    """What the page wrote over `passes` passes of page work: with `drive`, the page settled, then
    `/api/fleet` replayed byte for byte, two warm-up passes and a settle again, and each pass is
    `refresh(); place(); redrawAll(); bell();`; without, the
    page is left alone and each pass is its own work -- a refresh it started itself, a retry it
    armed -- run out. A pass ends when that work is done -- no fetch in flight, no short timer
    pending (and `also` true) -- plus two frames; a page whose work never runs out fails at
    `DESK_WAIT_MS`. Returns `{"mutations", "records" (the first 5), "renders", "refreshes"}`, the
    last the refreshes the page started itself in the window (`COUNT_REFRESHES`)."""
    install(page)
    out = page.evaluate(
        f"""(o) => __deskWaits.quiet(Object.assign(o, {{ also: {_also(also)} }}))""",
        {"passes": int(passes), "drive": bool(drive), "ms": DESK_WAIT_MS, "ground": bool(ground_moves)})
    if out.get("error"):
        _explain(page, "observe_quiet")
        raise AssertionError(out["error"] + (": " + "; ".join(out["moving"]) if out.get("moving") else ""))
    return out


def assert_idle(page, *, passes: int = 8, ground_moves: bool = False) -> dict:
    """The render contract: settled, then `passes` driven passes (`observe_quiet`) write nothing
    to the page, and -- unless the ground moves -- the ink layer renders no frame."""
    out = observe_quiet(page, passes=passes, drive=True, ground_moves=ground_moves)
    assert out["mutations"] == 0, f"an idle desk wrote to the page: {out}"
    if not ground_moves:
        assert out["renders"] == 0, f"an idle desk drew {out['renders']} ink frames: {out}"
    return out


def animations_done(page, selector=None) -> None:
    """Wait until no animation runs -- on the elements `selector` matches, or the whole document --
    the `.dot` excepted. Raises at `DESK_WAIT_MS`, naming what still runs."""
    install(page)
    try:
        page.wait_for_function("s => __deskWaits.running(s).length === 0", arg=selector,
                               timeout=DESK_WAIT_MS)
    except Exception:
        still = page.evaluate("s => __deskWaits.running(s)", selector)
        raise AssertionError(f"animations still running: {still}") from None


_names = itertools.count()


class Mutations:
    """One observer on a page (`record_mutations`): what it saw, read back when asked."""

    def __init__(self, page, name: str):
        self.page, self.name = page, name

    def _call(self, what: str):
        return self.page.evaluate(f"n => __deskWaits.recorders[n].{what}()", self.name)

    def records(self) -> list:
        """The first 50 records, as `type attribute target` words."""
        return self._call("records")

    def count(self) -> int:
        return self._call("count")

    def stop(self) -> "Mutations":
        self._call("stop")
        return self


def _options(attribute_filter) -> dict:
    """Every kind of mutation, or with `attribute_filter` only writes of those attributes."""
    if not attribute_filter:
        return {}
    return {"attributeFilter": list(attribute_filter), "childList": False, "characterData": False}


def record_mutations(page, *, target: str = "documentElement", attribute_filter=None,
                     init: bool = False, where: str | None = None) -> Mutations:
    """One observer over `target` (`documentElement`, `body`, or a selector), every kind of
    mutation (only `attribute_filter`'s attributes, when given), counting the records `where` (a JS
    predicate on a record) keeps. With `init` it is installed as an init script, so it sees the
    page's load; call it before `goto`."""
    name = f"r{next(_names)}"
    node = (f"document.{target}" if target in ("documentElement", "body")
            else f"document.querySelector({json.dumps(target)})")
    start = (f"window.__deskWaits.recorders[{json.dumps(name)}] = window.__deskWaits.watch("
             f"{'document' if init and target == 'documentElement' else node}, "
             f"{json.dumps(_options(attribute_filter))}, {{ where: {where or 'null'} }});")
    if init:
        page.add_init_script(WATCH + start)
    else:
        install(page)
        page.evaluate(f"() => {{ {start} }}")
    return Mutations(page, name)
