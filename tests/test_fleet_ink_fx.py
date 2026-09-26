"""The effects seam (#370, epic #293): `ink/fx.js`, fetched by the layer only for a table with effects.

docs/desk-ink.md §The files and §Budgets. What is asserted, with the layer drawing (`?ink=on`):

* a table without `fx` never asks for fx.js; a table with it asks exactly once, with the run token,
  and the same table set twice does not ask again;
* every detach path -- a table without `fx`, `Ink.setSkin(null)`, `Ink.off()` -- leaves no effects
  attached (`attached() === 0`) and no `fx` in `Ink.inspect().layer`;
* with effects attached and the desk at rest, the idle loop makes 0 DOM mutations and 0 renders.

The cues (#372, docs/desk-ink.md §Effects), driven through the real desk with the example skin: each
event is cued once with the box its element last had, nothing on a first match, during a replay or
on the match after one, nothing under reduced motion or with `?ink=off`, nothing written to the page
while a cue plays, and a bad row refuses the whole table while the marks draw on.

The budgets (`FX_BUDGET`, `INK_BUDGET`) are held in tests/test_fleet_ink.py.
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, TABLE, _desk_of, _serve, _stop, _open, _rest,  # noqa: F401
                            fleet_home)

#: The test table with effects, and hooks shaped like a skin module's (`cue` is #372's hook).
SET_FX = """t => Ink.setSkin(Object.assign({}, t, { fx: { cues: [] } }),
                             { cue() {}, tick() { return false; } })"""
#: How many layers have effects attached, and whether the layer lists any. The import reaches the
#: module the layer already fetched, so it adds no request.
ATTACHED = """async () => {
  const l = Ink.inspect().layer;
  return { attached: (await import(q('/static/ink/fx.js'))).attached(), fx: !!(l && l.fx),
           layer: !!l };
}"""
FX_UP = "!!Ink.inspect().layer && !!Ink.inspect().layer.fx && Ink.inspect().layer.fx.loaded"


def _fx(asked):
    return [u for u in asked if "/static/ink/fx.js" in u]


@pytest.mark.browser
def test_fx_js_is_fetched_only_by_a_table_with_effects(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, "&ink=on", count=True)

            # A table without effects: fx.js is never asked for.
            assert page.evaluate("t => Ink.setSkin(t)", TABLE)["drawn"] == "ink"
            _rest(page)
            assert _fx(asked) == [], asked
            assert page.evaluate("() => Ink.inspect().layer.fx") is None

            # A table with effects, set twice: fetched once, with the token.
            for _ in range(2):
                assert page.evaluate(SET_FX, TABLE)["drawn"] == "ink"
            _rest(page, FX_UP)
            _armed(page)
            fx = page.evaluate("() => Ink.inspect().layer.fx")
            assert fx == {"loaded": True, "rows": 0, "delivered": 0, "queued": 0, "dropped": 0, "armed": True,
                          "reaped": 0, "zero": 0, "children": 0, "refused": None}, fx
            assert page.evaluate(ATTACHED) == {"attached": 1, "fx": True, "layer": True}
            assert len(_fx(asked)) == 1 and f"?t={token}" in _fx(asked)[0], _fx(asked)
            assert page.evaluate("() => Object.keys(Ink.inspect().layer).includes('fx')")

            # At rest with effects attached: nothing written, nothing drawn.
            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk with effects attached wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle paper with effects was redrawn {count['renders']} times"

            # Detached by a table without effects.
            page.evaluate("t => Ink.setSkin(t)", TABLE)
            _rest(page)
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": True}

            # Attached again (the module is already here), then detached by no table at all.
            page.evaluate(SET_FX, TABLE)
            _rest(page, FX_UP)
            assert page.evaluate(ATTACHED)["attached"] == 1
            page.evaluate("() => Ink.setSkin(null)")
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": True}
            assert len(_fx(asked)) == 1, _fx(asked)
            assert not errors, errors
            page.close()

            # Detached by the layer going: a fresh page, so the module's count is its own.
            page, errors, asked = _open(browser, port, token, "&ink=on")
            page.evaluate(SET_FX, TABLE)
            _rest(page, FX_UP)
            assert page.evaluate(ATTACHED)["attached"] == 1
            page.evaluate("() => Ink.off()")
            assert page.evaluate(ATTACHED) == {"attached": 0, "fx": False, "layer": False}
            assert len(_fx(asked)) == 1, _fx(asked)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


# ================================================================================= the cues (#372)

#: Cues are armed by the first match after the stream's first pass, whose `tick` clears
#: `body.is-replaying` (#371); `_open` does not wait for that pass. Every cue test calls `_armed`
#: after opening and after every reload.
ARMED = ("() => { const l = Ink.inspect().layer; return !!(l && l.fx && l.fx.armed)"
         " && !document.body.classList.contains('is-replaying'); }")


def _armed(page):
    page.wait_for_function(ARMED, timeout=20000)


#: The example skin as the page runs it: the module `ink.js` imported, imported again by its URL (so
#: the same instance), for a wait to read its `inspect()` synchronously.
EXAMPLE = "async () => { window.__example = await import(q('/static/ink/skins/example.js')); }"
#: What the example has been cued with, the quads it is still playing, and the effects' own counts.
CUED = """() => { const e = window.__example.inspect(), l = Ink.inspect().layer;
  return { cues: e.cues, quads: e.quads, fx: l && l.fx }; }"""
#: The desk is still: the layer has drawn a frame since `after`, nothing is queued, drawing or
#: playing, no pane is moving, and no frame was drawn since the last poll -- which runs on every
#: animation frame, and a layer that is drawing draws on each of them.
STILL = """(after) => { const l = Ink.inspect().layer;
  if (!l || !l.fx || l.frames <= after || l.busy || l.fx.queued || l.fx.children) return false;
  if (window.__example.inspect().quads) return false;
  if ([...document.querySelectorAll('.tile')].some(t => t.getAnimations().length)) return false;
  const same = window.__stillAt === l.frames;
  window.__stillAt = l.frames;
  return same; }"""
#: A pane's box, read just before its hide button is pressed; and a pane's box, now.
HIDE = """(repo) => { const el = tiles.get(repo).el, r = el.getBoundingClientRect();
  el.querySelector('[data-tool="hide"]').click();
  return { x: r.left, y: r.top, w: r.width, h: r.height }; }"""
BOX = """(repo) => { const r = tiles.get(repo).el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height }; }"""
#: How many refusals a pane's transcript shows.
LINES = """(repo) => document.querySelectorAll(`.tile[data-repo="${repo}"] .transcript li.denied`).length"""
#: A pane `is-grouped` -- `display: none`, and still `:not(.is-hidden)` -- until the effects have
#: stamped its box empty and the layer has drawn two more frames, then hidden. `held` is false when
#: the page's own `place()` (its fifteen-second clock, a refresh the stream asked for) took the
#: class back first: then the pane never went, nothing was hidden, and the step is run again.
GROUPED = """async (repo) => {
  const frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const el = tiles.get(repo).el, layer = () => Ink.inspect().layer;
  toggle(el, 'is-grouped', true);
  for (let i = 0; i < 200 && layer().fx.zero < 1; i++) await frame();
  const at = layer().frames;
  for (let i = 0; i < 200 && layer().frames < at + 2; i++) { Ink.refresh(); await frame(); }
  const held = el.classList.contains('is-grouped') && layer().fx.zero >= 1 && layer().frames >= at + 2;
  if (held) setHidden(repo, true);
  return { held, zero: layer().fx.zero, frames: layer().frames - at };
}"""
#: An arrival the test makes (`ink-cue`), and every write to the page from then until its cue has
#: been delivered and played out: the layer, fx.js and the skin write none.
ARRIVE = """async ([repo, n]) => {
  const frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const el = tiles.get(repo).el, r = el.getBoundingClientRect();
  el.classList.add('ink-cue');
  const seen = [], obs = new MutationObserver(rs => rs.forEach(x => seen.push(x.type + ' ' +
    (x.attributeName || '') + ' ' + (x.target.id || x.target.className || x.target.nodeName))));
  obs.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  for (let i = 0; i < 600; i++) {
    const l = Ink.inspect().layer;
    if (l.fx.delivered > n && !l.fx.queued && !l.fx.children && !window.__example.inspect().quads) break;
    await frame();
  }
  obs.takeRecords().forEach(x => seen.push(x.type));
  obs.disconnect();
  return { box: { x: r.left, y: r.top, w: r.width, h: r.height }, seen };
}"""
#: A pane that arrives already matching the arrive row: made by the test, outside the grid.
ZETA = """() => { const z = document.createElement('div');
  z.className = 'tile ink-cue';
  z.dataset.repo = 'zeta';
  z.style.cssText = 'position: fixed; left: 16px; bottom: 16px; width: 160px; height: 48px';
  document.body.appendChild(z); }"""
#: A skin whose cue leaves a piece in the effects group and never frees it.
LEAK = """t => Ink.setSkin(Object.assign({}, t, { fx: { cues: [{ selector: '.tile.ink-cue', on: 'arrive', cue: 'leak' }] } }),
                     { cue({ THREE, scene }) { scene.add(new THREE.Group()); }, tick() { return false; } })"""
#: Each cue table in turn, and what the effects say of it once attached.
REFUSE = """async ([t, tables]) => {
  const frame = () => new Promise(done => requestAnimationFrame(() => done()));
  const out = [];
  for (const cues of tables) {
    await Ink.setSkin(Object.assign({}, t, { fx: { cues } }), { cue() {}, tick() { return false; } });
    let fx = null;
    for (let i = 0; i < 200 && !(fx = Ink.inspect().layer.fx); i++) await frame();
    out.push(fx && { refused: fx.refused, rows: fx.rows });
  }
  return out;
}"""
#: Cue tables with one bad row each: the words the refusal starts with, and a word of why.
_OK = {"selector": ".tile.ink-cue", "on": "arrive", "cue": "ok"}
BAD = (
    ([_OK, _OK, {"selector": "#x", "on": "arrive", "cue": "Loud"}], "cue 2 (#x): ", "`cue`"),
    ([{"selector": "#grid >", "on": "leave", "cue": "gone"}], "cue 0 (#grid >): ", "selector"),
    ([_OK, {"selector": ".tile", "on": "appear", "cue": "come"}], "cue 1 (.tile): ", "`on`"),
    ([{"selector": ".tile[data-nope]", "on": "arrive", "cue": "come"}], "cue 0 (.tile[data-nope]): ",
     "data-nope"),
    ([_OK] * 17, "cues: ", "16"),
)


def _frames(page):
    return page.evaluate("() => Ink.inspect().layer.frames")


def _still(page, after):
    """Until the desk is still (`STILL`) after the layer's frame `after`."""
    page.evaluate("() => { window.__stillAt = -1; }")
    page.wait_for_function(STILL, arg=after, timeout=20000)


def _delivered(page, more_than):
    page.wait_for_function("n => Ink.inspect().layer.fx.delivered > n", arg=more_than, timeout=20000)


def _new(page, before):
    """The cues played since `before`, as `(name, how)`, and their boxes."""
    cues = page.evaluate(CUED)["cues"][len(before["cues"]):]
    return [(c["name"], c["how"]) for c in cues], [c["box"] for c in cues]


def _near(box, rect):
    return max(abs(box[k] - rect[k]) for k in ("x", "y", "w", "h")) <= 1


@pytest.mark.browser
def test_cues_come_from_the_page_once_each_with_the_last_box(fleet_home, tmp_path):
    """#372, through the real desk, with the example skin chosen as the settings page chooses one.
    Three panes, and in turn: nothing is cued on the first match (alpha's history holds a refusal);
    a pane `is-grouped` for two layer frames and then hidden cues nothing; a hide cues the leave row
    once, with the box the pane had just before the click; a pane removed from the registry cues
    `removed`; an arrival cues once per new match and nothing is written to the page while it plays,
    and a pane that arrives already matching cues nothing; a forced replay, and a replay set and
    cleared inside one task, cue no line; a live refusal cues exactly one; the idle loop then writes
    nothing and draws nothing; a piece a skin leaves in the effects group is reaped; and a bad row
    refuses its whole table, naming the row, while the marks draw on. Then a page under reduced
    motion, where nothing is queued, and one with `?ink=off`, where nothing happens and nothing is
    fetched."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata.fleet import events as E
    from agentdata.fleet.registry import Registry
    from test_fleet_ink import _mark, _no_skin_css

    def refusal(repo, message):
        E.append(repo, [E.event(repo, "denied", {"message": message}, ticket="RDSD-1")])

    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    refusal("alpha", "rm -rf build")
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "example"}}', encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=3, count=True)
            said = []
            page.on("console", lambda m: said.append(m.text) if m.type == "error" else None)
            _no_skin_css(page)
            page.evaluate(EXAMPLE)
            _armed(page)
            _still(page, 0)

            # The first match: three panes, and a refusal in alpha's history. Nothing is cued.
            before = page.evaluate(CUED)
            fx = before["fx"]
            assert before["cues"] == [] and fx["rows"] == 3 and fx["refused"] is None, before
            assert (fx["delivered"], fx["queued"], fx["dropped"], fx["reaped"]) == (0, 0, 0, 0), fx

            # Grouped for two layer frames, then hidden: the box it last had is stale, so no cue.
            f = _frames(page)
            for _ in range(3):
                grouped = page.evaluate(GROUPED, "gamma")
                if grouped["held"]:
                    break
            assert grouped["held"] and grouped["zero"] >= 1 and grouped["frames"] >= 2, grouped
            _still(page, f)
            got = page.evaluate(CUED)
            assert got["cues"] == [] and got["fx"]["zero"] == 0, got

            # A hide: the leave row, once, with the box the pane had just before the click.
            f = _frames(page)
            rect = page.evaluate(HIDE, "beta")
            _delivered(page, 0)
            _still(page, f)
            cued, boxes = _new(page, before)
            assert cued == [("example-leave", "unmatched")], cued
            assert _near(boxes[0], rect), (boxes[0], rect)

            # Shown again, then removed from the registry: its pane goes, cued as `removed`.
            f = _frames(page)
            page.evaluate("() => setHidden('beta', false)")
            _still(page, f)
            before = page.evaluate(CUED)
            rect = page.evaluate(BOX, "beta")
            f = _frames(page)
            Registry().remove("beta")
            page.wait_for_function("() => { if (!tiles.has('beta')) return true; refresh(); return false; }",
                                   timeout=20000, polling=250)
            _still(page, f)
            cued, boxes = _new(page, before)
            assert cued == [("example-leave", "removed")], cued
            assert _near(boxes[0], rect), (boxes[0], rect)

            # An arrival: cued with the box it has, and nothing is written to the page while it plays.
            before = page.evaluate(CUED)
            played = page.evaluate(ARRIVE, ["alpha", before["fx"]["delivered"]])
            cued, boxes = _new(page, before)
            assert cued == [("example", "arrived")], cued
            assert _near(boxes[0], played["box"]), (boxes[0], played["box"])
            assert played["seen"] == [], f"the page was written while a cue played: {played['seen']}"
            # Once per new match: gone (an arrive row plays nothing then), and back.
            f = _frames(page)
            _mark(page, "alpha", "ink-cue", False)
            _still(page, f)
            f = _frames(page)
            _mark(page, "alpha", "ink-cue")
            _delivered(page, before["fx"]["delivered"] + 1)
            _still(page, f)
            assert _new(page, before)[0] == [("example", "arrived")] * 2
            # A pane that arrives already matching: it only just arrived, so nothing.
            before = page.evaluate(CUED)
            f = _frames(page)
            page.evaluate(ZETA)
            _still(page, f)
            f = _frames(page)
            page.evaluate("() => document.querySelector('.tile[data-repo=\"zeta\"]').remove()")
            _still(page, f)
            assert _new(page, before)[0] == [], "a pane that arrived already matching was cued"

            # A forced replay: alpha's history drawn again, its refusal with it. History, not news.
            lines = page.evaluate(LINES, "alpha")
            f = _frames(page)
            page.evaluate("() => { tiles.get('alpha').seq = 0; connect(); }")
            page.wait_for_function(f"() => ({LINES})('alpha') > {lines}", timeout=20000)
            _armed(page)
            _still(page, f)
            assert _new(page, before)[0] == [], "a replayed refusal was cued"

            # A replay said and unsaid inside one task, with a refusal drawn between: never seen by a
            # match, which reads the body once a frame, and still no cue.
            f = _frames(page)
            quiet = page.evaluate("""async () => {
              toggle(document.body, 'is-replaying', true);
              append(tiles.get('alpha').el, { kind: 'denied', data: { message: 'x' } });
              toggle(document.body, 'is-replaying', false);
              await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
              return Ink.inspect().layer.fx.delivered; }""")
            assert quiet == before["fx"]["delivered"], "a refusal drawn while the page said it replays was cued"
            _still(page, f)
            assert _new(page, before)[0] == []

            # A live refusal: exactly one line cue.
            f = _frames(page)
            refusal("alpha", "git push --force")
            _delivered(page, before["fx"]["delivered"])
            _still(page, f)
            assert _new(page, before)[0] == [("example-line", "arrived")]

            # At rest after them all: nothing written, nothing drawn, nothing delivered or left.
            before = page.evaluate(CUED)
            count = page.evaluate(IDLE_LOOP)
            after = page.evaluate(CUED)
            assert count["n"] == 0, f"an idle desk after its cues wrote to the page: {count}"
            assert count["renders"] == 0, f"an idle desk after its cues was redrawn {count['renders']} times"
            assert after["fx"]["delivered"] == before["fx"]["delivered"], (before["fx"], after["fx"])
            assert (after["quads"], after["fx"]["reaped"], after["fx"]["dropped"]) == (0, 0, 0), after
            assert len(after["cues"]) == after["fx"]["delivered"] == 5, after

            # The net: a skin that leaves a piece in the effects group has it taken out 90 frames on,
            # on a desk that is otherwise at rest.
            _mark(page, "alpha", "ink-cue", False)
            page.evaluate(LEAK, TABLE)
            _armed(page)
            _mark(page, "alpha", "ink-cue")
            page.wait_for_function("""() => { const fx = Ink.inspect().layer.fx;
              return fx.delivered === 1 && fx.reaped === 1 && fx.children === 0; }""", timeout=20000)

            # Refused rows, last: the whole table is refused, naming the row and why, and said in the
            # console; the marks draw on.
            refused = page.evaluate(REFUSE, [TABLE, [rows for rows, _, _ in BAD]])
            for (_, where, why), got in zip(BAD, refused):
                assert got and got["rows"] == 0 and got["refused"].startswith(where), (where, got)
                assert why in got["refused"], (why, got)
            assert [s for s in said if s.startswith("ink: cue")][0].startswith("ink: cue 2 (#x): "), said
            _mark(page, "alpha", "ink-loop")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector === '.tile.ink-loop .head'"
                        " && m.state === 'drawn')")
            assert not errors, errors
            page.evaluate("() => setHidden('gamma', false)")      # the next desk opens with it shown
            page.close()

            # Reduced motion: a hide, an arrival and a live refusal, and nothing is queued.
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=2, reduced=True)
            _no_skin_css(page)
            page.evaluate(EXAMPLE)
            _armed(page)
            lines = page.evaluate(LINES, "alpha")
            f = _frames(page)
            page.evaluate(HIDE, "gamma")
            _mark(page, "alpha", "ink-cue")
            refusal("alpha", "curl | sh")
            page.wait_for_function(f"() => ({LINES})('alpha') > {lines}", timeout=20000)
            _still(page, f)
            got = page.evaluate(CUED)
            fx = got["fx"]
            assert page.evaluate("() => Ink.inspect().layer.reduced") is True
            assert fx["rows"] == 3 and fx["armed"] is True, fx
            assert got["cues"] == [] and (fx["queued"], fx["delivered"], fx["dropped"]) == (0, 0, 0), got
            assert not errors, errors
            page.evaluate("() => setHidden('gamma', false)")
            page.close()

            # `?ink=off`: no layer, so no effects -- nothing fetched, nothing cued, no error.
            page, errors, asked = _open(browser, port, token, "&ink=off", panes=2)
            _no_skin_css(page)
            page.evaluate(EXAMPLE)
            page.evaluate(HIDE, "gamma")
            _mark(page, "alpha", "ink-cue")
            page.wait_for_function("() => tiles.get('gamma').el.classList.contains('is-hidden')", timeout=10000)
            off = page.evaluate("() => ({ layer: Ink.inspect().layer, cues: window.__example.inspect().cues })")
            assert off == {"layer": None, "cues": []}, off
            assert _fx(asked) == [], _fx(asked)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
