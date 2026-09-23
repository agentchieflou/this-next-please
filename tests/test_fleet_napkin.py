"""Napkin notes (#252, slice F of the ink epic #246): the desk written on a quilted paper napkin.

The skin is `static/ink/skins/napkin.js` and `static/skins/napkin/skin.css`, and docs/skin-napkin.md
says what it draws. What is asserted here:

* it is a skin like any other: `skins.py` offers it, its numbers are the ones its stylesheet draws,
  and `theme.check` holds every ink it draws on both ends of its paper (the quilt's seam under a
  coffee ring at the dark end, the paper at the light);
* the paper state grammar, from real agents rather than classes set by hand: each state the desk
  can show draws its mark from the class the page sets, and a state that goes is erased (pencil) or
  struck (ink) -- and the agent's name is never struck;
* the coffee ring is under a pane idle a long time and no other, and goes when the agent wakes;
* the felt tip bleeds along the emboss: further into the seams than onto the pillows;
* reduced motion draws it all at once; the plain fallback draws the napkin and the same marks with
  no layer; an idle napkin writes nothing and draws nothing, and the ink settles in a bounded
  number of frames.

CI draws in SwiftShader, which the probe calls `software`, so every inked test opens the desk with
`?ink=on` (the override, never a measurement). The desk's own redraw owns the state classes, so the
states come from agents' streams: an error event, an open question, a live lock (`supervisor.live`
patched in-process, which is what makes a pane `running`), events three days old.
"""
from __future__ import annotations
import json
import math
import os
import re
import time

import pytest

from agentdata import theme
from agentdata.fleet import events as E, fingerprint as FP, skins, supervisor
from agentdata.fleet.registry import Registry
from agentdata.fleet import serve as S

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (AT_REST, COUNT_FETCHES, IDLE_LOOP, _marks, _serve, _stop,
                            catch_up_frames)
from test_fleet_ink import _own_desk_globals, fleet_home  # noqa: F401 - fixtures

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "napkin.js")
CSS = os.path.join(STATIC, "skins", "napkin", "skin.css")

#: What a session began on, and what is installed now (#240): a pane that began on OLD is stale.
NOW = {"version": "0.13.2", "commit": "bbbbbbbbbbbb", "skills": "222222222222"}
OLD = {"version": "0.13.1", "commit": "aaaaaaaaaaaa", "skills": "111111111111"}
#: Three days ago: an idle agent this old has a chip a day or more old, `.chip.stale`.
LONG_AGO = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3 * 86400))

#: What the napkin module has on the paper. `_napkin_page` puts the module the page loaded on
#: `window.__napkin` (the same URL, so the same instance), so a wait can read it synchronously.
NAPKIN = "__napkin.inspect()"


# ============================================================================== without a browser


def _block(css, variant):
    """The declarations of one variant's rule in skin.css."""
    sel = r'body\[data-skin="napkin"\]\[data-skin-variant="%s"\]' % variant
    m = re.search(sel + r"\s*\{(.*?)\}", css, re.S)
    assert m, f"napkin:{variant} is not drawn"
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(1)))


def _hex(rgba):
    r, g, b, a = [float(x) for x in re.findall(r"[\d.]+", rgba)]
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b)), round(a, 2)


def test_the_napkin_is_a_skin_and_its_stylesheet_draws_the_numbers_skins_py_checks():
    """Declared and drawn are one number: the paper, its seam, the coffee and every ink in skin.css
    are the ones `skins.py` declares -- and the panel pair is computed from them, not typed: the
    darkest the text is ever read on is the coffee's rim over the quilt's seam, the lightest the
    paper. `theme.check` holds text, status and every ink at both ends."""
    napkin = skins.SKINS["napkin"]
    assert napkin["default"] == "diner" and set(napkin["variants"]) == {"diner", "kraft"}
    assert "napkin" in S.ink_skins(), "the skin ships its module, so the desk draws it with ink"
    css = open(CSS, encoding="utf-8").read()
    for variant, spec in napkin["variants"].items():
        drawn = _block(css, variant)
        assert drawn["--paper"].upper() == spec["paper"] and drawn["--paper-seam"].upper() == spec["seam"]
        assert _hex(drawn["--coffee"]) == (spec["coffee"][0], spec["coffee"][1]), (variant, drawn)
        assert {t: drawn[f"--ink-{t}"].upper() for t in spec["inks"]} == spec["inks"], variant
        rim = skins._over(theme.hex_to_rgb(spec["coffee"][0]), spec["coffee"][1],
                          theme.hex_to_rgb(spec["seam"]))
        assert spec["composited_panel"] == {"darkest": theme.rgb_to_hex(rim), "lightest": spec["paper"]}
        for panel in skins.composited_panels(spec):
            theme.check(theme.get(spec["base"]), composited_panel=panel, skin=f"napkin:{variant}",
                        inks=spec["inks"])
    # The default is the stylesheet itself, as well as its own attribute.
    assert 'body[data-skin="napkin"],\nbody[data-skin="napkin"][data-skin-variant="diner"]' in css


def test_the_napkin_writes_no_colour_and_draws_only_classes_the_page_sets():
    """A palette colours the inks and a skin chooses the paper: the module reads every colour from
    skin.css, so it has no hex of its own. And the DOM is the truth: every class and attribute its
    mark table and its materials match on is one app.js or the page's markup already sets -- the
    skin adds no state."""
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", code), "a colour written in the module"
    assert not re.search(r"0x[0-9A-Fa-f]{6}\b", code), "a colour written in the module"
    page = (open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
            + open(os.path.join(STATIC, "index.html"), encoding="utf-8").read())
    selectors = re.findall(r'selector: "((?:[^"\\]|\\.)*)"', body)
    selectors += re.findall(r'const (?:IDLE|AGED|ERROR_ROW|RUNNING_ROW|FOUND) = "([^"]*)"', body)
    assert len(selectors) >= 14, selectors
    for sel in selectors:
        for cls in re.findall(r"\.([a-z][\w-]*)", sel):
            if cls in ("denied", "friction"):     # a transcript line's class is its event's kind
                assert f'setClass(li, ev.kind)' in page and f'case "{cls}":' in page, cls
            elif cls.startswith("state-"):
                assert '"state-" + ' in page and cls[6:] in ("idle", "running", "error", "done"), cls
            else:
                assert re.search(r'["\s]%s["\s]' % re.escape(cls), page), f"no page sets .{cls}"
        for attr in re.findall(r"\[([\w-]+)", sel):
            assert attr in page, f"no page sets [{attr}]"


# ================================================================================ in a browser


def _agent(tmp_path, name, *, install=NOW, ts=None, more=()):
    """An agent that began on `install`, said one thing and ended its turn, `ts` ago; `more` are
    events after that, as (kind, data). With `ts`, the whole stream is that old -- the phase the
    fleet reads from the project's `state.json` included, which `events.refresh` would otherwise
    stamp now, and the fold's age is its newest event's."""
    repo = Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    E.refresh(name, repo.path, repo_state=repo.state())
    evs = [E.event(name, "started", {"pid": 1, "install": install}, ticket="RDSD-1", ts=ts),
           E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1", ts=ts),
           E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1", ts=ts)]
    evs += [E.event(name, kind, data, ticket="RDSD-1", ts=ts) for kind, data in more]
    E.append(name, evs)
    if ts:
        path = E.normalized_path(name)
        lines = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for ev in lines:
                f.write(json.dumps(dict(ev, ts=E.stamp(ts)), ensure_ascii=False) + "\n")


def _desk(tmp_path, monkeypatch, agents, live=()):
    """A desk of `agents` ({name: kwargs for `_agent`}), every one a pane with a width; `live` is
    the set of agents with a process running (mutable: the test can start and stop them)."""
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    alive = set(live)
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 9, "kind": "headless"} if name in alive else {})
    for name, kw in agents.items():
        _agent(tmp_path, name, **kw)
    names = list(agents)
    S.arrange(order=names)
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    return alive


def _napkin_page(browser, port, token, fleet_home, panes, *, ink=True, reduced=False, count=False,
                 variant=""):
    """The desk in the napkin skin, waited on until every pane has its width and the skin's table
    is the one in force."""
    skin = "napkin" + (":" + variant if variant else "")
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    page = browser.new_page(viewport={"width": 1500, "height": 900},
                            reduced_motion="reduce" if reduced else "no-preference")
    if count:
        page.add_init_script(COUNT_FETCHES)
    errors, asked = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # A skin's mistake is said in the console as `ink: ...` (docs/desk-ink.md rule 8).
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and m.text.startswith("ink:") else None)
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"http://127.0.0.1:{port}/?t={token}" + ("&ink=on" if ink else ""),
              wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile.is-solo').length === {panes}
             && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
             && !!window.Ink && windowWrites === 0
             && (Ink.inspect().table || '').startsWith('napkin')
             && (!Ink.enabled || !!Ink.inspect().layer)""", timeout=20000)
    page.evaluate("async () => { window.__napkin = await import(q('/static/ink/skins/napkin.js')); }")
    return page, errors, asked


def _tile(repo):
    return f'.tile[data-repo="{repo}"]'


def _in(repo, marks):
    return [m for m in marks if m["lane"] == "pane:" + repo and not m["strikeOf"]]


def _kinds(marks):
    return sorted((m["selector"], m["tool"], m["shape"]) for m in marks)


#: The napkin has come to rest: the layer's lanes are empty and the felt tip has soaked in.
SETTLED = f"""() => ({AT_REST})() && Object.values({NAPKIN}).every(p => !p.bleed || p.tail === 1)"""


def _settle(page, also="true", timeout=30000):
    page.wait_for_function(f"() => ({SETTLED})() && ({also})", timeout=timeout)


@pytest.mark.browser
def test_each_state_draws_its_mark_from_the_class_the_page_sets(fleet_home, tmp_path, monkeypatch):
    """The paper state grammar (plan-ink), drawn from real agents: idle a pencil outline and its
    name underlined in pencil; running its name underlined in pen with the pen's tip at the end;
    needs you the name and the question highlighted and each choice looped in pencil; error the
    felt tip's box and a bang; stale (#240) its note written, an arrow to the run's line and a
    dashed outline; done a green check (the fold's `is-done`); a finding (a refused line) ringed, its
    kind highlighted and its words written; the header count handwritten."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    q = {"question": "which window should ask land in?", "id": "q1", "blocking": True,
         "choices": ["left", "right"]}
    _desk(tmp_path, monkeypatch, {
        "idle": {}, "run": {}, "ask": {"more": [("question_opened", q)]},
        "err": {"more": [("error", {"exit_code": 2})]}, "old": {"install": OLD},
        "done": {"more": [("phase_changed", {"from": "querying", "to": "done"})]},
        "found": {"more": [("denied", {"message": "rm -rf is not allowed"})]},
    }, live=("run",))
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 7)
            page.wait_for_selector(_tile("found") + " .transcript li.denied", timeout=15000)
            page.wait_for_selector(_tile("run") + ".state-running", timeout=15000)
            page.wait_for_selector(_tile("done") + ".is-done", timeout=15000)
            page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
            page.wait_for_selector(_tile("ask") + ".needs-human .ask-choice", timeout=15000)
            _settle(page, "Ink.inspect().layer.marks.some(m => m.shape === 'bang')"
                          " && Ink.inspect().layer.marks.some(m => m.tool === 'marker')")
            marks = _marks(page)
            napkin = page.evaluate(NAPKIN)
            tip = page.evaluate("""() => { const t = document.querySelector('.tile[data-repo="run"]');
              const r = t.getBoundingClientRect(), n = t.querySelector('.head .repo').getBoundingClientRect();
              const line = document.querySelector('.tile[data-repo="old"] .runline').getBoundingClientRect();
              return { x: n.right - r.left, y: n.bottom - r.top, runline: line.width > 0 }; }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    # An arrow with nothing to point at (the run's line is not shown at this width) has no strokes.
    drawing = [m for m in marks if not m["strikeOf"] and m["strokes"]]
    assert all(m["state"] == "drawn" and m["drawn"] == 1 for m in drawing), \
        [(m["lane"], m["selector"], m["state"], m["drawn"])
         for m in drawing if m["state"] != "drawn" or m["drawn"] != 1]
    assert _kinds(_in("idle", marks)) == [
        (".tile.state-idle", "pencil", "outline"), (".tile.state-idle .head .repo", "pencil", "underline")]
    assert _kinds(_in("run", marks)) == [(".tile.state-running .head .repo", "pen", "underline")]
    ask = _in("ask", marks)
    assert (".tile.needs-human .head .repo", "highlighter", "lines") in _kinds(ask)
    assert [m["tool"] for m in ask if m["selector"].endswith(".ask-q")] == ["highlighter"]
    assert [m["shape"] for m in ask if m["tool"] == "pencil"] == ["loop", "loop"], "one loop per choice"
    # An agent in error needs you (the page sets `needs-human` on it too), so its name is lit.
    assert _kinds(_in("err", marks)) == [(".tile.needs-human .head .repo", "highlighter", "lines"),
                                         (".tile.state-error", "marker", "loop"),
                                         (".tile.state-error .head", "red", "bang")]
    old = _kinds(_in("old", marks))
    assert (".tile .oldsession:not([hidden])", "pencil", "write") in old
    assert (".tile .oldsession:not([hidden])", "pencil", "arrow") in old
    arrow = next(m for m in marks if m["shape"] == "arrow")
    assert bool(arrow["strokes"]) == tip["runline"], (arrow, tip)
    assert (".tile:has(.oldsession:not([hidden]))", "pencil", "outline") in old
    assert not [m for m in marks if "oldsession" in m["selector"] and m["lane"] != "pane:old"]
    assert [(m["selector"], m["tool"], m["shape"]) for m in marks if m["lane"] == "header"] == \
        [("#bellcount", "pen", "write")]
    # A finding: the refused line ringed in red, its kind highlighted, its words written in pencil.
    found = _kinds(_in("found", marks))
    for row in ((".tile .transcript li:is(.denied, .friction)", "red", "ellipse"),
                (".tile .transcript li:is(.denied, .friction) .k", "highlighter", "lines"),
                (".tile .transcript li:is(.denied, .friction) .v", "pencil", "write")):
        assert row in found, found
    # Done is the fold's word, `is-done`, on a pane whose chip says idle: a check in the margin.
    done = _kinds(_in("done", marks))
    assert (".tile:is(.state-done, .is-done) .head", "green", "check") in done, done
    assert not [m for m in marks if m["shape"] == "check" and m["lane"] != "pane:done"], "only one pane is done"
    # The pen's tip rests at the end of the running line: 8px past the name, just under it.
    assert napkin["run"]["pentip"] and not any(v["pentip"] for k, v in napkin.items() if k != "run")
    assert abs(napkin["run"]["tip"]["x"] - (tip["x"] + 8)) < 2 and abs(napkin["run"]["tip"]["y"] - (tip["y"] + 2.2)) < 2
    # The felt tip's bleed is along the error box, drawn to its end and soaked in.
    assert napkin["err"]["bleed"] and napkin["err"]["tail"] == 1, napkin["err"]
    assert not any(v["bleed"] for k, v in napkin.items() if k != "err"), napkin


@pytest.mark.browser
def test_a_state_that_goes_is_erased_or_struck_and_the_name_is_never_struck(fleet_home, tmp_path,
                                                                             monkeypatch):
    """Drawn, never faded. Choosing an answer erases its pencil loop and circles it in pen; the
    answer arriving strikes the question's highlight through in pen and ERASES the name's -- a
    name struck through reads as an agent that has gone, the flaw both prototypes had (the row
    says `leaves: "erased"`, #252). An idle pane that starts running has its pencil erased, and a
    pane that leaves error has its felt tip's box and its bang struck, with the ink it soaked
    staying where it soaked."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    q = {"question": "which window should ask land in?", "id": "q1", "blocking": True,
         "choices": ["left", "right"]}
    alive = _desk(tmp_path, monkeypatch, {
        "ask": {"more": [("question_opened", q)]}, "idle": {},
        "err": {"more": [("error", {"exit_code": 2})]},
    })
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 3)
            page.wait_for_selector(_tile("ask") + ".needs-human .ask-choice", timeout=15000)
            page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
            _settle(page, "Ink.inspect().layer.marks.filter(m => m.lane === 'pane:ask').length === 4"
                          " && Ink.inspect().layer.marks.some(m => m.tool === 'marker')")
            before = _marks(page)

            # The operator picks an answer: the page's own button, the page's own aria-pressed.
            page.locator(_tile("ask") + " .ask-choice").nth(1).click()
            _settle(page, "Ink.inspect().layer.marks.some(m => m.shape === 'ellipse' && m.drawn === 1)"
                          " && Ink.inspect().layer.marks.filter(m => m.tool === 'pencil'"
                          " && m.lane === 'pane:ask').length === 1")
            chosen = _marks(page)

            # The answer arrives, the idle agent starts, and the failed one is started again.
            alive.update({"idle", "err"})
            E.append("ask", [E.event("ask", "question_answered", {"id": "q1", "answer": "right"},
                                     ticket="RDSD-1")])
            for name in ("idle", "err"):
                E.append(name, [E.event(name, "turn_started", {}, ticket="RDSD-1")])
            page.wait_for_selector(_tile("ask") + ":not(.needs-human)", timeout=15000)
            page.wait_for_selector(_tile("idle") + ".state-running", timeout=15000)
            page.wait_for_selector(_tile("err") + ".state-running", timeout=15000)
            _settle(page, "Ink.inspect().layer.marks.filter(m => m.strikeOf).length >= 3"
                          " && !Ink.inspect().layer.marks.some(m => m.tool === 'pencil'"
                          " && m.lane === 'pane:idle')")
            after = _marks(page)
            napkin = page.evaluate(NAPKIN)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    loops = [m for m in before if m["lane"] == "pane:ask" and m["tool"] == "pencil"]
    assert len(loops) == 2
    kept = [m for m in chosen if m["lane"] == "pane:ask" and m["tool"] == "pencil"]
    assert [m["id"] for m in kept] == [loops[0]["id"]], "the chosen answer's pencil loop is erased"
    assert [m["tool"] for m in chosen if m["shape"] == "ellipse"] == ["pen"], "the answer is circled"

    by = {m["id"]: m for m in after}
    struck_of = {m["strikeOf"] for m in after if m["strikeOf"]}
    name = next(m for m in before if m["selector"] == ".tile.needs-human .head .repo")
    question = next(m for m in before if m["selector"].endswith(".ask-q"))
    assert name["id"] not in by and name["id"] not in struck_of, "the agent's name was struck"
    assert by[question["id"]]["state"] == "struck" and question["id"] in struck_of, after
    assert all(by[s]["tool"] == "pen" for s in (m["id"] for m in after if m["strikeOf"])), after
    # Pencil is erased, and the running pen's line replaces it.
    assert not [m for m in after if m["lane"] == "pane:idle" and m["tool"] == "pencil"], after
    assert [m["selector"] for m in _in("idle", after)] == [".tile.state-running .head .repo"]
    # Ink is struck, and what the felt tip soaked stays with its struck box.
    err = {m["selector"]: m for m in after if m["lane"] == "pane:err" and not m["strikeOf"]}
    assert err[".tile.state-error"]["state"] == "struck" and err[".tile.state-error .head"]["state"] == "struck"
    assert napkin["err"]["bleed"] and napkin["err"]["tail"] == 1, napkin["err"]


#: Pixels of the ink canvas in a viewport box, read in the task that drew them (`Ink.sample` draws
#: a frame for the purpose): `[x, y, r, g, b]` per pixel, x and y in CSS px.
PIXELS = """(box) => {
  Ink.sample({ x: 0, y: 0, w: 1, h: 1 });
  const src = document.getElementById('ink'), dpr = src.width / innerWidth;
  const c = document.createElement('canvas');
  c.width = Math.round(box.w * dpr); c.height = Math.round(box.h * dpr);
  const g = c.getContext('2d');
  g.drawImage(src, box.x * dpr, box.y * dpr, c.width, c.height, 0, 0, c.width, c.height);
  const d = g.getImageData(0, 0, c.width, c.height).data, out = [];
  for (let i = 0; i < d.length; i += 4) {
    const p = i / 4;
    out.push([box.x + (p % c.width) / dpr, box.y + Math.floor(p / c.width) / dpr, d[i], d[i + 1], d[i + 2]]);
  }
  return out;
}"""


def _count(pixels, test):
    """How many of `pixels` pass `test(x, y, r, g, b)`, and how many there were."""
    return {"hit": sum(1 for p in pixels if test(*p)), "n": len(pixels)}


def _coffee(x, y, r, g, b):
    """Brown where the paper is neutral: the paper and its seam are within 8 of grey, the ring is not."""
    return r - b > 12 and r > g


def _to_seam(x, y):
    """napkin.js `toSeam`: 0 on a quilting seam, 0.5 in the middle of a pillow."""
    u, v = (x + y) / 26, (x - y) / 26
    f = lambda t: abs(t - math.floor(t) - 0.5)                      # noqa: E731
    return 0.5 - max(f(u), f(v))


@pytest.mark.browser
def test_a_coffee_ring_is_under_a_pane_idle_a_long_time_and_no_other(fleet_home, tmp_path, monkeypatch):
    """A pane that has been idle a long time -- idle, and its chip a day old -- has a coffee ring
    under it. A pane idle a moment has none, nor does a pane whose last word was days ago but which
    is in error: it is not idle, it needs you. The agent waking takes the cup away."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, monkeypatch, {
        "old": {"ts": LONG_AGO}, "fresh": {},
        "olderr": {"ts": LONG_AGO, "more": [("error", {"exit_code": 1})]},
    })
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 3)
            page.wait_for_selector(_tile("old") + ".state-idle .chip.stale", timeout=15000)
            page.wait_for_selector(_tile("olderr") + ".state-error .chip.stale", timeout=15000)
            _settle(page, f"({NAPKIN}).old.coffee")
            napkin = page.evaluate(NAPKIN)

            def ring_box(repo):
                r = page.evaluate(f"() => document.querySelector('{_tile(repo)}').getBoundingClientRect().toJSON()")
                c = napkin["old"]["ring"]           # the same place in every pane, for comparison
                return {"x": r["x"] + c["x"] - c["r"] - 4, "y": r["y"] + c["y"] - c["r"] - 4,
                        "w": 2 * c["r"] + 8, "h": 2 * c["r"] + 8}

            seen = {repo: _count(page.evaluate(PIXELS, ring_box(repo)), _coffee)
                    for repo in ("old", "fresh", "olderr")}

            E.append("old", [E.event("old", "assistant_text", {"text": "back"}, ticket="RDSD-1")])
            page.wait_for_selector(_tile("old") + " .chip:not(.stale)", timeout=15000)
            _settle(page, f"!({NAPKIN}).old.coffee")
            woke = _count(page.evaluate(PIXELS, ring_box("old")), _coffee)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert napkin["old"]["coffee"] and not napkin["fresh"]["coffee"] and not napkin["olderr"]["coffee"]
    assert seen["old"]["hit"] > 0.08 * seen["old"]["n"], seen
    assert seen["fresh"]["hit"] < 0.005 * seen["fresh"]["n"], seen
    assert seen["olderr"]["hit"] < 0.005 * seen["olderr"]["n"], seen
    assert woke["hit"] < 0.005 * woke["n"], woke


@pytest.mark.browser
def test_the_felt_tip_bleeds_along_the_emboss(fleet_home, tmp_path, monkeypatch):
    """The felt tip's ink runs down the quilting: just outside its stroke round an error pane,
    the paper is inked where a seam is pressed in, and hardly at all on the pillows between. The
    seams are the paper shader's lattice (`toSeam` in napkin.js), recomputed here per pixel."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, monkeypatch, {"err": {"more": [("error", {"exit_code": 2})]}, "idle": {}})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 2)
            page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
            _settle(page, "Ink.inspect().layer.marks.some(m => m.tool === 'marker' && m.drawn === 1)")
            r = page.evaluate(f"() => document.querySelector('{_tile('err')}').getBoundingClientRect().toJSON()")
            # A band 6-11px outside the loop (which runs 5px outside the pane) along its top,
            # clear of the corners: the stroke and its wobble end ~4px from the line.
            band = {"x": r["x"] + 40, "y": r["y"] - 5 - 11, "w": r["width"] - 80, "h": 5}
            pixels = page.evaluate(PIXELS, band)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    red = lambda r, g, b: r - (g + b) / 2 > 14                    # noqa: E731
    seams = _count(pixels, lambda x, y, r, g, b: _to_seam(x, y) < 0.03)
    on_seam = _count(pixels, lambda x, y, r, g, b: _to_seam(x, y) < 0.03 and red(r, g, b))
    pillows = _count(pixels, lambda x, y, r, g, b: _to_seam(x, y) > 0.15)
    on_pillow = _count(pixels, lambda x, y, r, g, b: _to_seam(x, y) > 0.15 and red(r, g, b))
    seam_share = on_seam["hit"] / max(1, seams["hit"])
    pillow_share = on_pillow["hit"] / max(1, pillows["hit"])
    print(f"\n  felt tip in the band: {seam_share:.2f} of seam pixels, {pillow_share:.2f} of pillow pixels")
    assert seams["hit"] > 20 and pillows["hit"] > 20, (seams, pillows)
    assert seam_share > 0.5, (on_seam, seams)
    assert pillow_share < 0.1, (on_pillow, pillows)


@pytest.mark.browser
def test_reduced_motion_draws_the_napkin_at_once(fleet_home, tmp_path, monkeypatch):
    """Under reduced motion every mark is on the paper at once, the felt tip has soaked in at once,
    the ring is down at once, and no pen travels."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, monkeypatch, {"err": {"more": [("error", {"exit_code": 2})]},
                                  "old": {"ts": LONG_AGO}})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 2, reduced=True)
            page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
            page.wait_for_selector(_tile("old") + ".state-idle .chip.stale", timeout=15000)
            page.wait_for_function("() => Ink.inspect().layer.marks.some(m => m.tool === 'marker')",
                                   timeout=15000)
            # The frame after the marker's mark exists: everything is already down.
            seen = page.evaluate(f"""async () => {{
              await new Promise(d => requestAnimationFrame(() => requestAnimationFrame(d)));
              const l = Ink.inspect().layer;
              return {{ marks: l.marks.map(m => [m.selector, m.drawn]), hands: l.hands,
                        reduced: l.reduced, napkin: {NAPKIN} }};
            }}""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert seen["reduced"] is True and seen["hands"] is False
    assert seen["marks"] and all(d == 1 for _, d in seen["marks"]), seen["marks"]
    assert seen["napkin"]["err"]["bleed"] and seen["napkin"]["err"]["tail"] == 1, seen["napkin"]
    assert seen["napkin"]["old"]["coffee"], seen["napkin"]


@pytest.mark.browser
def test_the_plain_fallback_is_the_plain_look_with_the_same_marks(fleet_home, tmp_path, monkeypatch):
    """Where the gate is off (every shell but a measured hardware one), the napkin is the one plain
    look every skin shares since #257 -- the palette's page and panes, no quilt and no ring, which
    are the module's to draw -- and the same mark table drawn plain by the layer's fallback: the
    error pane boxed, the name that needs you tinted. No layer, no three.js. Both variants."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    q = {"question": "which window?", "id": "q1", "blocking": True, "choices": ["left", "right"]}
    _desk(tmp_path, monkeypatch, {
        "old": {"ts": LONG_AGO}, "err": {"more": [("error", {"exit_code": 2})]},
        "ask": {"more": [("question_opened", q)]},
    })
    server, token, port = _serve()
    looks = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            for variant in ("", "kraft"):
                page, errors, asked = _napkin_page(browser, port, token, fleet_home, 3, ink=False,
                                                   variant=variant)
                page.wait_for_selector(_tile("old") + ".state-idle .chip.stale", timeout=15000)
                page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
                page.wait_for_selector(_tile("ask") + ".needs-human", timeout=15000)
                page.wait_for_function("() => getComputedStyle(document.body).getPropertyValue('--paper').trim() !== ''",
                                       timeout=10000)
                looks[variant or "diner"] = page.evaluate("""() => {
                  const t = r => document.querySelector(`.tile[data-repo="${r}"]`);
                  const cs = e => getComputedStyle(e);
                  return {
                    off: document.body.classList.contains('ink-off'), drawn: Ink.inspect().plain,
                    paper: cs(document.body).getPropertyValue('--paper').trim(),
                    page: cs(document.body).backgroundImage,
                    old: cs(t('old')).backgroundImage, err: cs(t('err')).backgroundImage,
                    panel: cs(t('err')).backgroundColor,
                    want: cs(document.body).getPropertyValue('--panel').trim(),
                    box: cs(t('err')).outlineStyle + ' ' + cs(t('err')).outlineWidth,
                    name: cs(t('ask').querySelector('.head .repo')).backgroundColor,
                    bare: cs(t('old').querySelector('.head .repo')).backgroundColor,
                    under: cs(t('old').querySelector('.head .repo')).textDecorationLine,
                  };
                }""")
                assert not [u for u in asked if "/static/ink/layer.js" in u or "vendor/three" in u]
                assert not errors, errors
                page.close()
            browser.close()
    finally:
        _stop(server)
    for variant, look in looks.items():
        spec = skins.SKINS["napkin"]["variants"][variant]
        assert look["off"] and look["drawn"], look
        assert look["paper"].upper() == spec["paper"], look
        assert look["page"] == "none" and look["old"] == "none" and look["err"] == "none", look
        want = tuple(round(c * 255) for c in theme.hex_to_rgb(look["want"]))
        assert look["panel"] == "rgb(%d, %d, %d)" % want, look
        assert look["box"].startswith("solid 2px"), look
        assert look["name"] != look["bare"] and look["under"] == "underline", look


@pytest.mark.browser
def test_an_idle_napkin_writes_nothing_draws_nothing_and_settled_in_bounded_frames(fleet_home,
                                                                                    tmp_path,
                                                                                    monkeypatch):
    """The render contract with the napkin on the paper: once the marks are drawn and the felt tip
    has soaked in, an idle desk is zero DOM mutations and zero WebGL frames -- and getting there
    took the frames a hand needs for the marks at the pen's speed, plus the soak (napkin.js
    `SOAK_S`), and never more."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, monkeypatch, {"err": {"more": [("error", {"exit_code": 2})]}, "idle": {},
                                  "old": {"ts": LONG_AGO}})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _napkin_page(browser, port, token, fleet_home, 3, count=True)
            page.wait_for_selector(_tile("err") + ".state-error", timeout=15000)
            _settle(page, "Ink.inspect().layer.marks.some(m => m.tool === 'marker')")
            # Settling again, from nothing: the table set afresh, counted in frames.
            rec = page.evaluate(f"""async () => {{
              const m = window.__napkin;
              await Ink.setSkin(null);
              const table = {{ name: 'napkin', paper: '--paper', marks: m.marks() }};
              const f0 = Ink.inspect().layer ? Ink.inspect().layer.frames : 0;
              await Ink.setSkin(table, m);
              for (let i = 0; i < 4000; i++) {{
                await new Promise(d => requestAnimationFrame(d));
                const l = Ink.inspect().layer;
                if (l.marks.length && !l.busy && !Object.values(l.lanes).some(x => x.hand)
                    && Object.values({NAPKIN}).every(p => !p.bleed || p.tail === 1)) {{
                  return {{ frames: l.frames - f0,
                            marks: l.marks.map(k => [k.id, k.lane, k.drawn, k.selector, k.len, k.strokes]) }};
                }}
              }}
              const l = Ink.inspect().layer;
              return {{ stuck: {{ busy: l.busy, lanes: l.lanes, napkin: {NAPKIN},
                                 marks: l.marks.filter(k => k.drawn !== 1).map(k => [k.selector, k.state, k.drawn]) }} }};
            }}""")
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert "stuck" not in rec, f"the napkin never came to rest: {rec}"
    bound = catch_up_frames(rec["marks"]) + math.ceil(0.7 * 60) + 2
    print(f"\n  the napkin settled in {rec['frames']} frames (bound {bound})")
    assert 3 <= rec["frames"] <= bound, (rec["frames"], bound)
    assert count["n"] == 0, f"an idle napkin wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle napkin was redrawn {count['renders']} times"
