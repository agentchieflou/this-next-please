"""The legal pad (#251, slice E of the ink epic #246): the "yellow-page version" the operator asked
for, which is a yellow legal pad (plan-ink Decision 4) -- canary stock, blue rules on the page's
28px baseline, a double red margin and a glued top edge, with an orange-pink highlighter that still
reads on yellow.

What is asserted:

* it is a skin by name: `skins.py` registers it, the settings page offers it, choosing it fetches
  its module with the token, and the ink layer draws its pad -- the stock, the glue, the rules and
  the margins are on the canvas in the colours `skin.css` gives them;
* the paper state grammar (plan-ink §The state grammar) is exactly its mark table, and each state
  draws its mark from the class the page already sets, from real fleet data wherever the fold can
  produce the state: idle, running (its tail growing with the turn and its pen-tip dot), needs you,
  answered (the question struck, never the name, and the choice circled), error, done, stale, a
  finding and the header count, struck and rewritten;
* a mark leaves by being erased (pencil) or struck (ink), never faded; reduced motion draws at once;
* where the gate is off, the same table is drawn plain over the same pad in CSS;
* every ink it introduces is held to its paper by `theme.check`, the orange-pink highlighter first;
* an idle legal pad writes nothing and draws nothing, and the ink catches up in frames.

CI draws in SwiftShader, which the gate turns off, so the tests that need ink open the desk with
`?ink=on` (an override, never a measurement), as `test_fleet_ink.py` does.
"""
from __future__ import annotations
import json
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import events as E, fingerprint as FP, serve as S, skins, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, INK, STATIC, _layer, _marks, _open, _rest, _serve,
                            _stop, _own_desk_globals, catch_up_frames, fleet_home)

__all__ = ["_own_desk_globals", "fleet_home"]     # fixtures, used by name

MODULE = os.path.join(INK, "skins", "legalpad.js")
CSS = os.path.join(STATIC, "skins", "legalpad", "skin.css")
NOW = {"version": "0.14.0", "commit": "cccccccccccc", "skills": "333333333333"}
OLD = {"version": "0.13.1", "commit": "aaaaaaaaaaaa", "skills": "111111111111"}

OPEN = ':not(:has(.ask-choice[aria-pressed="true"]))'
FOUND = ".tile .transcript li:is(.denied, .friction)"
STALE = ".tile .oldsession:not([hidden])"
#: plan-ink §The state grammar, as the rows that draw it: (selector, tool, shape). The skin's own
#: table must be exactly this, in this order.
GRAMMAR = {
    "idle": [(".tile.state-idle", "pencil", "outline"),
             (".tile.state-idle .head .repo", "pencil", "underline")],
    "running": [(".tile.state-running .head .repo", "pen", "underline")],
    "needs you": [(".tile.needs-human .head .repo", "highlighter", "lines"),
                  (f".tile .ask:not([hidden]){OPEN} .ask-q", "highlighter", "lines"),
                  (f".tile .ask:not([hidden]){OPEN} .ask-choice", "pencil", "loop")],
    "answered": [('.tile .ask:not([hidden]) .ask-choice[aria-pressed="true"]', "pen", "ellipse")],
    "error": [(".tile.state-error", "marker", "loop"), (".tile.state-error", "red", "bang")],
    "done": [(".tile:is(.state-done, .is-done)", "green", "check")],
    "stale": [(STALE, "pencil", "write"), (STALE, "pencil", "outline"), (STALE, "pencil", "arrow")],
    "a finding": [(FOUND, "red", "ellipse"), (FOUND + " .k", "highlighter", "lines"),
                  (FOUND + " .v", "pencil", "write")],
    "the header count": [("#bellcount", "pen", "write")],
}
ROWS = [row for rows in GRAMMAR.values() for row in rows]
DONE = GRAMMAR["done"][0][0]

#: Tests of WHAT is drawn open the desk under reduced motion, which draws every mark at once: the
#: pen at a hand's speed is seconds of wall time per pane, and the Windows leg runs the suite
#: serially under a 20-minute cap. The drawing over time keeps its own tests (the catch-up in
#: frames, the answered strike, the header count's strike) at full motion.

#: The skin module, imported again by the page by its own URL: the same instance the layer runs.
#: `_desk` keeps it on `window.__legalpad`, so a wait can ask it synchronously -- `wait_for_function`
#: takes a predicate's value as it is, and an async predicate's Promise is always truthy.
SKIN = "window.__legalpad"


# ------------------------------------------------------------------------------------ the fleet


def _ev(name, kind, data=None):
    return E.event(name, kind, data or {}, ticket="RDSD-1")


def _begun(name, install=NOW):
    return _ev(name, "started", {"pid": 1, "new": True, "session": "", "install": install})


def _pad(tmp_path, monkeypatch, panes, live=()):
    """A desk of `panes` ({name: events after a fresh start}), every one a pane with a width, the
    installed skills pinned so a session is stale only where it says so, and `live` a set of the
    agents a process holds (mutable, so a test can end a turn)."""
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    FP.forget()
    live = set(live)
    real_live, real_lock = supervisor.live, supervisor.read_lock
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 777, "repo": name} if name in live else real_live(name))
    monkeypatch.setattr(supervisor, "read_lock",
                        lambda name: {"pid": 777, "external": True} if name in live else real_lock(name))
    for name, events in panes.items():
        # A finished agent is finished in its own `state.json` too, which the fold reads.
        phase = {"phase": "done"} if name == "fin" else {}
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1", **phase), name=name)
        install = OLD if name == "stale" else NOW
        E.append(name, [_begun(name, install)] + [dict(ev, repo=name) for ev in events])
    names = list(panes)
    S.arrange(order=names)
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    return live


def _said(name, text):
    return _ev(name, "assistant_text", {"text": text})


def _idle(name):
    return [_said(name, "working on " + name), _ev(name, "turn_ended", {"turn": "0"})]


def _asks(name):
    return [_said(name, "one thing first"),
            _ev(name, "question_opened", {"id": "q1", "question": "Which branch should I use?",
                                          "choices": ["main", "dev"]}),
            _ev(name, "turn_ended", {"turn": "0"})]


def _choose(page, skin="legalpad"):
    page.evaluate("s => post('theme', { skin: s })", skin)


def _config(fleet_home, skin="legalpad"):
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


def _desk(browser, port, token, extra="&ink=on", panes=1, **kw):
    """A desk on the legal pad, waited on until the skin's table is the one in force."""
    page, errors, asked = _open(browser, port, token, extra, panes=panes, **kw)
    page.wait_for_function("() => Ink.inspect().table === 'legalpad:canary'", timeout=15000)
    page.evaluate("async () => { window.__legalpad = await import(q('/static/ink/skins/legalpad.js')); }")
    return page, errors, asked


def _drawn(page, lane=None):
    """(state, selector, tool, shape) -> [mark state, ...] for every mark on the paper, not strikes."""
    out = {}
    for m in _marks(page):
        if m["strikeOf"] or (lane and m["lane"] != lane):
            continue
        out.setdefault((m["selector"], m["tool"], m["shape"]), []).append(m["state"])
    return out


def _skin(page):
    return page.evaluate(f"() => {SKIN}.inspect()")


#: Pixels of the ink canvas at viewport points, read back in the task that drew the frame (the
#: drawing buffer is not kept past it). [[r, g, b, a], ...].
PIXELS = """(pts) => {
  Ink.sample({ x: 0, y: 0, w: 1, h: 1 });
  const c = document.getElementById('ink');
  const k = document.createElement('canvas');
  k.width = c.width; k.height = c.height;
  const x = k.getContext('2d');
  x.drawImage(c, 0, 0);
  const dpr = c.width / innerWidth;
  return pts.map(([px, py]) => Array.from(x.getImageData(Math.floor(px * dpr), Math.floor(py * dpr), 1, 1).data));
}"""

#: The custom properties the pad is drawn in, as the page resolves them.
PROPS = """() => { const cs = getComputedStyle(document.body);
  const out = {};
  for (const n of ['--paper', '--rule', '--margin', '--glue', '--ink-pencil', '--ink-pen',
                   '--ink-highlighter', '--human', '--done', '--text'])
    out[n] = cs.getPropertyValue(n).trim();
  return out; }"""


def _rgb(hexa):
    h = hexa.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _near(px, hexa, tol=14):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], _rgb(hexa)))


def _css_props():
    body = open(CSS, encoding="utf-8").read()
    block = body[body.index('body[data-skin="legalpad"] {'):]
    block = block[:block.index("}")]
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", block))


# ================================================================================ without a browser


def test_the_legal_pad_is_a_skin_by_name():
    """Registered in skins.py, as every skin is, and shipped as an ink module: so the settings page
    offers it and the server lists it on the desk's <body> for the layer."""
    assert "legalpad" in [s["name"] for s in skins.list_skins()]
    assert skins.split("legalpad") == ("legalpad", "canary")
    got = skins.get_skin("legalpad")
    assert got["full"] == "legalpad:canary" and got["base"] == "eye-relief-day", got
    assert "legalpad" in S.ink_skins()
    assert os.path.isfile(MODULE) and os.path.isfile(CSS)


def test_the_grammar_is_the_skins_table_row_for_row():
    """plan-ink §The state grammar, one or more rows per state, and nothing else: the module's
    table is read out of its source here and must be exactly `GRAMMAR`, in its order."""
    body = open(MODULE, encoding="utf-8").read()
    consts = {"OPEN": OPEN, "FOUND": FOUND, "RUNNING": ".tile.state-running .head .repo"}
    table = body[body.index("export function marks()"):body.index("export const options")]
    rows = []
    for m in re.finditer(r'\{ selector: (.+?), tool: "(\w+)", shape: "(\w+)"', table):
        parts = [p.strip() for p in m.group(1).split(" + ")]
        sel = "".join(consts[p] if p in consts else p[1:-1] for p in parts)
        rows.append((sel, m.group(2), m.group(3)))
    assert rows == ROWS, rows


def test_every_ink_on_the_pad_is_held_to_its_paper():
    """`theme.check`'s rule 5 (#248) gets every pair the legal pad introduces: each ink 3:1 on the
    canary, and the text 4.5:1 through the highlighter's tint. `skins.py` declares the numbers and
    `skin.css` writes them -- the two must agree, or the check would be of a pad nobody draws. The
    orange-pink highlighter is the reason for the skin's override: it passes, on canary."""
    spec = skins.SKINS["legalpad"]["variants"]["canary"]
    base = theme.get(spec["base"])
    props = _css_props()
    palette = theme.to_css(base)
    assert props["--paper"].upper() == spec["composited_panel"].upper()
    inks = spec["inks"]
    assert set(inks) == {"pencil", "pen", "red", "green", "marker", "highlighter"}
    written = {"pencil": "--ink-pencil", "pen": "--ink-pen", "highlighter": "--ink-highlighter"}
    left = {"red": "--human", "green": "--done", "marker": "--human"}   # the palette's (ink.js TOOLS)
    for tool, prop in written.items():
        assert props[prop].upper() == inks[tool].upper(), (tool, props[prop], inks[tool])
    for tool, token in left.items():
        assert f"--ink-{tool}" not in props and palette[token].upper() == inks[tool].upper(), tool
    theme.check(base, composited_panel=spec["composited_panel"], skin="legalpad:canary", inks=inks)
    # The highlighter is orange-pink -- red-dominant, blue over green -- and it reads.
    r, g, b = _rgb(inks["highlighter"])
    assert r > b > g, inks["highlighter"]
    tint = theme.mix(spec["composited_panel"], inks["highlighter"], theme.INK_TINT)
    assert theme.contrast_ratio(base.text, tint) >= 4.5
    # And a highlighter that did not read on canary would be refused, naming the skin.
    with pytest.raises(theme.ThemeError) as refused:
        theme.check(base, composited_panel=spec["composited_panel"], skin="legalpad:canary",
                    inks={"highlighter": "#000000"})
    assert "highlighter" in str(refused.value) and "legalpad" in str(refused.value)


def test_the_legal_pad_module_carries_no_colour_of_its_own():
    """desk-ink.md §Writing a skin, rule 3: colours come from the page's custom properties, never
    from a hex in the module -- a palette change repaints the pad, and `skin.css` is the one place
    its colours are written."""
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", code)
    for prop in ("--paper", "--rule", "--margin", "--glue"):
        assert f'"{prop}"' in code, prop


# ============================================================================== with a browser


@pytest.mark.browser
def test_the_legal_pad_is_chosen_by_name_and_drawn_on_canary(fleet_home, tmp_path, monkeypatch):
    """Chosen as the settings page chooses a skin, `POST /api/theme {skin: "legalpad"}`: its module is
    fetched with the token, its table is in force, and the pad is on the canvas -- canary stock,
    the gummed band across the top, a blue rule every 28px, and a double red margin down a pane --
    in the colours `skin.css` gives them. The highlighter multiplies into it: the paper is light."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"alpha": _idle("alpha")})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, "&ink=on", panes=1, reduced=True)
            assert "legalpad" in page.evaluate("() => document.body.dataset.inkSkins").split()
            _choose(page)
            page.wait_for_function("() => Ink.inspect().table === 'legalpad:canary'", timeout=15000)
            _rest(page, "Ink.inspect().layer.skin && Ink.inspect().layer.skin.frames === 1"
                        " && getComputedStyle(document.body).getPropertyValue('--paper').trim() !== ''")
            page.evaluate("() => Ink.refresh()")
            _rest(page)
            layer = _layer(page)
            props = page.evaluate(PROPS)
            geo = page.evaluate("""() => { const t = document.querySelector('.tile[data-repo="alpha"]').getBoundingClientRect();
              const h = document.querySelector('header').getBoundingClientRect();
              return { tile: [t.left, t.top, t.width, t.height], head: h.bottom, w: innerWidth, h: innerHeight }; }""")
            tx, ty, tw, th = geo["tile"]
            rule_y = next(y for y in range(28, 900, 28) if y > geo["head"] + 4 and y > ty + 40)
            blank_y = rule_y + 14
            # A 1px line can land across two device pixels where a pane sits on a fractional x, so
            # each line is looked for in the pixels around where it is drawn.
            def near(x, y, axis):
                return [[x + d, y] if axis == "x" else [x, y + d] for d in (-1, 0, 1)]
            pts = ([[tx + tw - 40, blank_y]]                 # the stock, between two rules
                   + near(tx + tw - 40, rule_y - 1, "y")     # a rule
                   + near(tx + 25, blank_y, "x")             # the margin's first line
                   + near(tx + 29, blank_y, "x")             # and its second
                   + [[tx + 27.5, blank_y]]                  # the paper between them
                   + [[geo["w"] / 2, 3]])                    # the glue
            px = page.evaluate(PIXELS, pts)
            px = [px[0], px[1:4], px[4:7], px[7:10], px[10], px[11]]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    fetched = [u.split(str(port))[1] for u in asked if "/static/ink/skins/" in u]
    assert fetched and all(u == f"/static/ink/skins/legalpad.js?t={token}" for u in fetched), fetched
    skin = layer["skin"]
    assert skin["hooks"] == ["paper", "frame", "tick", "dispose"] and skin["errors"] == [], skin
    assert skin["paper"] > 3 and skin["frames"] == 1, skin
    assert layer["mode"] == 1 and layer["dark"] is False, "light stock: the highlighter multiplies"
    assert _near(px[0], props["--paper"]), (px[0], props)
    assert any(_near(c, props["--rule"], 24) for c in px[1]), (px[1], props)
    assert any(_near(c, props["--margin"], 24) for c in px[2]), (px[2], props)
    assert any(_near(c, props["--margin"], 24) for c in px[3]), (px[3], props)
    assert _near(px[4], props["--paper"]), "one margin line, then paper, then the other"
    assert _near(px[5], props["--glue"], 20), (px[5], props)


@pytest.mark.browser
def test_each_state_draws_its_mark_from_the_class_the_page_sets(fleet_home, tmp_path, monkeypatch):
    """The grammar on a desk the fleet drew from its own records -- idle, running, needs you, error,
    done, stale and a finding are all states the fold produces -- and each pane carries exactly its own
    state's marks, drawn: the table reads what app.js set and decides nothing."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    panes = {
        "idle": _idle("idle"),
        "run": [_ev("run", "turn_started"), _said("run", "reading the ticket")],
        "asks": _asks("asks"),
        "broke": [_said("broke", "trying"), _ev("broke", "error", {"exit_code": 2})],
        "stale": _idle("stale"),
        "found": [_said("found", "cleaning up"), _ev("found", "denied", {"message": "rm -rf is not allowed"}),
                  _ev("found", "turn_ended", {"turn": "0"})],
        "fin": [_said("fin", "merged"), _ev("fin", "phase_changed", {"from": "review", "to": "done"}),
                _ev("fin", "turn_ended", {"turn": "0"})],
    }
    _pad(tmp_path, monkeypatch, panes, live={"run"})
    _config(fleet_home)
    # An error and a refused tool need the human too (`agentstate.needs_the_human`), so those panes
    # carry the name's highlight beside their own marks.
    name = GRAMMAR["needs you"][:1]
    want = {"idle": GRAMMAR["idle"], "run": GRAMMAR["running"], "asks": GRAMMAR["needs you"],
            "broke": name + GRAMMAR["error"], "stale": GRAMMAR["idle"] + GRAMMAR["stale"],
            "found": name + GRAMMAR["a finding"],
            # Done, unsupervised: the chip says idle, and `is-done` says finished.
            "fin": GRAMMAR["idle"] + GRAMMAR["done"]}
    count = sum(len(rows) for rows in want.values()) + 1 + 1        # the second choice, the count
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, panes=len(panes), width=1900, height=1000, reduced=True)
            classes = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('.tile')]
              .map(t => [t.dataset.repo, t.className]))""")
            _rest(page, f"Ink.inspect().layer.marks.filter(m => !m.strikeOf).length >= {count}", timeout=60000)
            drawn = {repo: _drawn(page, "pane:" + repo) for repo in panes}
            header = _drawn(page, "header")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert "state-running" in classes["run"] and "state-error" in classes["broke"], classes
    assert "needs-human" in classes["asks"] and "needs-human" in classes["found"], classes
    assert "state-idle" in classes["stale"] and "state-idle" in classes["idle"], classes
    assert "is-done" in classes["fin"], classes
    for repo, rows in want.items():
        # A finding's line is the only one of its kind here; the question has two choices.
        expect = {row: ["drawn"] * (2 if row[2] == "loop" and row[1] == "pencil" else 1) for row in rows}
        assert drawn[repo] == expect, (repo, drawn[repo])
    assert header == {("#bellcount", "pen", "write"): ["drawn"]}, header


@pytest.mark.browser
def test_answering_strikes_the_question_and_circles_the_choice(fleet_home, tmp_path, monkeypatch):
    """*needs you* is the name and the question highlighted and each choice looped in pencil;
    *answered* is the question and its highlight struck through in pen -- the question, never the
    agent's name -- and the chosen answer circled. Pressing a choice is the page's own answer
    (`aria-pressed`), so the grammar follows the operator's hand, not a guess."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"asks": _asks("asks")})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.shape === 'loop').length === 2")
            before = _drawn(page, "pane:asks")
            question = next(m for m in _marks(page) if m["selector"].endswith(" .ask-q"))
            page.click('.tile[data-repo="asks"] .ask-choice:has-text("dev")')
            _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'ellipse' && m.state === 'drawn')"
                        " && !Ink.inspect().layer.marks.some(m => m.shape === 'loop')"
                        " && Ink.inspect().layer.marks.some(m => m.strikeOf)")
            after = _marks(page)
            circled = page.evaluate("""() => { const m = Ink.inspect().layer.marks.find(m => m.shape === 'ellipse');
              const b = document.querySelector('.tile[data-repo="asks"] .ask-choice[aria-pressed="true"]').getBoundingClientRect();
              return { mark: m.box, choice: [b.left, b.top, b.width, b.height], text: document.querySelector(
                '.ask-choice[aria-pressed="true"]').textContent }; }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    q = f".tile .ask:not([hidden]){OPEN} .ask-q"
    assert before[(q, "highlighter", "lines")] == ["drawn"]
    assert before[(f".tile .ask:not([hidden]){OPEN} .ask-choice", "pencil", "loop")] == ["drawn", "drawn"]
    by_id = {m["id"]: m for m in after}
    assert by_id[question["id"]]["state"] == "struck", "the question's highlight is struck, in pen"
    strike = next(m for m in after if m["strikeOf"] == question["id"])
    assert (strike["tool"], strike["shape"], strike["drawn"]) == ("pen", "strike", 1), strike
    name = [m for m in after if m["selector"] == ".tile.needs-human .head .repo"]
    assert [m["state"] for m in name] == ["drawn"], "the agent's name is never struck"
    assert not any(m["strikeOf"] == name[0]["id"] for m in after)
    assert not [m for m in after if m["tool"] == "pencil" and m["shape"] == "loop"], "the loops are erased"
    assert circled["text"].startswith("dev")
    mark, choice = circled["mark"], circled["choice"]
    assert (abs(mark["x"] - choice[0]) < 1 and abs(mark["w"] - choice[2]) < 1), circled


@pytest.mark.browser
def test_the_running_pen_grows_with_the_turn_and_is_struck_when_it_ends(fleet_home, tmp_path, monkeypatch):
    """*running* is a pen line under the name that grows with the turn, and the pen-tip dot at its
    end: the tail starts where the pen finished the underline and grows a step for each line the
    turn writes. When the turn ends the underline and its tail are struck, in pen -- and the idle
    pane's pencil marks, which were erased when the turn began, are drawn again."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    live = _pad(tmp_path, monkeypatch, {"run": _idle("run")})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, reduced=True)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.tool === 'pencil').length >= 2")
            idle = [m["id"] for m in _marks(page) if m["tool"] == "pencil"]

            # The turn begins: the fleet says so, and the page draws it.
            E.append("run", [_ev("run", "turn_started")])
            live.add("run")
            page.evaluate("() => refresh()")
            page.wait_for_function("() => document.querySelector('.tile[data-repo=\"run\"]')"
                                   ".classList.contains('state-running')", timeout=15000)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-running')"
                        " && m.state === 'drawn')")
            page.wait_for_function(f"() => {SKIN}.inspect().panes.some(p => p.shown)", timeout=10000)
            begun = _skin(page)["panes"][0]
            erased = [i for i in idle if i in {m["id"] for m in _marks(page)}]

            # The turn writes three lines: the tail grows three steps, and the dot is at its end.
            page.evaluate("""() => { const el = document.querySelector('.tile[data-repo="run"]');
              for (const t of ['one', 'two', 'three']) append(el, { kind: 'assistant_text', data: { text: t } }); }""")
            page.wait_for_function(f"() => {SKIN}.inspect().panes[0].lines === 3", timeout=10000)
            grown = _skin(page)["panes"][0]
            geo = page.evaluate("""() => { const r = document.querySelector('.tile[data-repo="run"] .head .repo').getBoundingClientRect();
              return [r.right, r.bottom]; }""")
            tip = [geo[0] + 8 + grown["tail"] + 1, geo[1] + 2.8]
            px = page.evaluate(PIXELS, [tip, [tip[0] + 30, tip[1]]])
            props = page.evaluate(PROPS)

            # The turn ends.
            E.append("run", [_ev("run", "turn_ended", {"turn": "1"})])
            live.discard("run")
            page.evaluate("() => refresh()")
            page.wait_for_function("() => document.querySelector('.tile[data-repo=\"run\"]')"
                                   ".classList.contains('state-idle')", timeout=15000)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.strikeOf)"
                        " && Ink.inspect().layer.marks.filter(m => m.tool === 'pencil' && m.state === 'drawn').length >= 2")
            page.wait_for_function(f"() => {SKIN}.inspect().panes[0].strike === 1", timeout=10000)
            ended = _skin(page)["panes"][0]
            marks = _marks(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert erased == [], "the idle pane's pencil marks are erased when the turn begins"
    assert begun["running"] and begun["shown"] and begun["lines"] == 0 and begun["pieces"] == 1, begun
    assert grown["lines"] == 3 and grown["tail"] == 18 and grown["pieces"] == 2, grown
    assert _near(px[0], props["--ink-pen"], 60), ("the pen-tip dot", px[0], props["--ink-pen"])
    assert _near(px[1], props["--paper"], 20), ("past the tip is paper", px[1])
    under = next(m for m in marks if m["selector"] == ".tile.state-running .head .repo")
    assert under["state"] == "struck", under
    assert any(m["strikeOf"] == under["id"] and m["tool"] == "pen" for m in marks)
    assert not ended["running"] and ended["strike"] == 1 and ended["pieces"] == 3, ended


@pytest.mark.browser
def test_error_and_done_are_drawn_and_struck_when_they_go(fleet_home, tmp_path, monkeypatch):
    """*error* is a red marker box inside the pane and a bang in its margin; *done* a green check in
    the margin. Both are ink, so a state that goes is struck through and the strike stays. (The
    fleet's records carry the pane from one to the other: an error, then a new run that finishes.)"""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"broke": [_said("broke", "trying"), _ev("broke", "error", {"exit_code": 2})]})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, reduced=True)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector === '.tile.state-error').length === 2")
            error = _drawn(page, "pane:broke")
            # The agent is run again and finishes: a new run leaves the old one's error behind, and
            # its own state.json says done. The page hears it as it hears any agent.
            state = tmp_path / "broke" / ".agent" / "state.json"
            state.write_text(json.dumps(dict(json.loads(state.read_text(encoding="utf-8")), phase="done")),
                             encoding="utf-8")
            E.append("broke", [_begun("broke"), _said("broke", "fixed"),
                               _ev("broke", "phase_changed", {"from": "querying", "to": "done"}),
                               _ev("broke", "turn_ended", {"turn": "0"})])
            page.evaluate("() => refresh()")
            page.wait_for_function("() => document.querySelector('.tile[data-repo=\"broke\"]')"
                                   ".classList.contains('is-done')", timeout=15000)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.state === 'drawn')"
                        " && Ink.inspect().layer.marks.filter(m => m.strikeOf).length === 3")
            done = _marks(page)
            box = next(m for m in done if m["shape"] == "check")["box"]
            ink = page.evaluate(PIXELS, [[box["x"] + 14 + dx, box["y"] + 14 + dy]
                                         for dx in range(-10, 11, 2) for dy in range(0, 21, 2)])
            props = page.evaluate(PROPS)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert error[(".tile.state-error", "marker", "loop")] == ["drawn"], error
    assert error[(".tile.state-error", "red", "bang")] == ["drawn"], error
    struck = [m for m in done if m["selector"] == ".tile.state-error"]
    assert sorted(m["state"] for m in struck) == ["struck", "struck"], struck
    assert all(any(s["strikeOf"] == m["id"] and s["tool"] == "pen" for s in done) for m in struck)
    name = [m for m in done if m["selector"] == ".tile.needs-human .head .repo"]
    assert [m["state"] for m in name] == ["struck"], "done no longer needs you: its highlight is struck"
    assert [m["tool"] for m in done if m["shape"] == "check"] == ["green"]
    assert any(_near(px, props["--done"], 70) for px in ink), "no green check in the margin"


@pytest.mark.browser
def test_the_header_count_is_handwritten_and_the_old_number_struck_beside_the_new(fleet_home, tmp_path,
                                                                                    monkeypatch):
    """*the header count*: handwritten, and when it changes the old number is struck where it
    stood and the new one is beside it. The count is the page's own (`bell()` from its unread
    map); the struck number is the pad's, drawn in pen left of the new one. The unread count is put
    on the pane that is not open, because opening a pane is what reads it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"alpha": _idle("alpha"), "beta": _idle("beta")})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, panes=2, count=True)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector === '#bellcount' && m.state === 'drawn')")
            first = _skin(page)["count"]
            page.evaluate("() => { unread.set('beta', 2); bell(); }")
            page.wait_for_function(f"() => {SKIN}.inspect().count.strike === 1", timeout=10000)
            _rest(page)
            struck = _skin(page)["count"]
            r = page.evaluate("() => { const b = document.getElementById('bellcount').getBoundingClientRect();"
                              " return [b.left, b.top, b.height]; }")
            left = page.evaluate(PIXELS, [[r[0] - dx, r[1] + dy] for dx in range(3, 16) for dy in range(0, int(r[2]))])
            props = page.evaluate(PROPS)
            idle = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert first == {"now": "0", "old": "", "strike": -1, "pieces": 0}, first
    assert struck["now"] == "2" and struck["old"] == "0" and struck["strike"] == 1, struck
    assert struck["pieces"] == 2, "the old digit and the pen line through it"
    assert sum(_near(px, props["--ink-pen"], 90) for px in left) >= 4, "no struck number beside the count"
    assert idle["n"] == 0 and idle["renders"] == 0, f"the count kept drawing: {idle}"


@pytest.mark.browser
def test_reduced_motion_draws_the_pad_and_its_marks_at_once(fleet_home, tmp_path, monkeypatch):
    """Reduced motion draws every mark at once, with no travelling pen; the pad's own strikes (the
    running tail, the header count) are drawn at once too."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"asks": _asks("asks"), "idle": _idle("idle")})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, panes=2, reduced=True)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.shape === 'loop').length === 2")
            went = page.evaluate(f"""async () => {{
              const l0 = Ink.inspect().layer.frames;
              document.querySelector('.tile[data-repo="asks"] .ask-choice').click();
              document.querySelector('.tile[data-repo="idle"]').classList.replace('state-idle', 'state-done');
              unread.set('idle', 1); bell();
              await new Promise(d => requestAnimationFrame(() => requestAnimationFrame(d)));
              const l = Ink.inspect().layer;
              return {{ frames: l.frames - l0, busy: l.busy, hands: l.hands, reduced: l.reduced,
                       marks: l.marks.map(m => [m.selector, m.shape, m.state, m.drawn, m.strikeOf]),
                       count: {SKIN}.inspect().count }};
            }}""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert went["reduced"] is True and went["hands"] is False and went["busy"] is False, went
    assert went["frames"] <= 2, went
    live = [m for m in went["marks"] if not m[4]]
    assert all(m[3] == 1 for m in live), live
    assert not [m for m in live if m[1] == "loop"], "the pencil loops erased at once"
    assert [m[2] for m in live if m[1] == "ellipse"] == ["drawn"] and [m for m in live if m[1] == "check"]
    assert any(m[2] == "struck" for m in went["marks"]), went["marks"]
    assert went["count"]["strike"] == 1, went["count"]


@pytest.mark.browser
def test_where_the_gate_is_off_the_same_grammar_is_drawn_plain_on_a_css_pad(fleet_home, tmp_path, monkeypatch):
    """Decision 3: no WebGL, the same page plain. The skin's table is the constructed stylesheet --
    an outline for idle, a tint for the question, a loop for each choice, a margin bar for an error
    -- in the skin's own inks, over the pad `skin.css` draws in gradients: rules, the double margin
    and the glue. The fallback writes nothing to the page to do it."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"asks": _asks("asks"), "idle": _idle("idle"),
                                 "broke": [_said("broke", "x"), _ev("broke", "error", {"exit_code": 2})]})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _desk(browser, port, token, extra="", panes=3)
            page.wait_for_function("""() => getComputedStyle(document.body).getPropertyValue('--paper').trim() !== ''
              && getComputedStyle(document.querySelector('.tile[data-repo="idle"]')).outlineStyle === 'solid'""",
                                   timeout=10000)
            look = page.evaluate("""() => {
              const t = r => document.querySelector(`.tile[data-repo="${r}"]`);
              const cs = e => getComputedStyle(e);
              const col = c => { const k = document.createElement('canvas').getContext('2d'); k.fillStyle = c; return k.fillStyle; };
              const body = cs(document.body);
              return {
                off: document.body.classList.contains('ink-off'),
                idle: [cs(t('idle')).outlineStyle, cs(t('idle')).outlineWidth, cs(t('idle')).outlineColor],
                name: cs(t('idle').querySelector('.repo')).textDecorationLine,
                question: cs(t('asks').querySelector('.ask:not([hidden]) .ask-q')).backgroundColor,
                choice: cs(t('asks').querySelector('.ask-choice')).outlineStyle,
                hl: cs(t('asks').querySelector('.head .repo')).backgroundColor,
                error: [cs(t('broke')).outlineStyle, cs(t('broke')).boxShadow],
                rules: body.backgroundImage, paper: body.backgroundColor,
                glue: cs(document.querySelector('header')).borderTopColor,
                margin: cs(t('idle')).backgroundImage,
                pencil: body.getPropertyValue('--ink-pencil').trim(),
                sheet: document.adoptedStyleSheets.flatMap(s => [...s.cssRules].map(r => r.cssText)).join('\\n'),
              }; }""")
            writes = page.evaluate("""async () => { let n = 0;
              const obs = new MutationObserver(rs => { n += rs.filter(r => r.attributeName === 'style').length; });
              obs.observe(document.documentElement, { subtree: true, attributes: true });
              document.querySelector('.tile[data-repo="asks"] .ask-choice').click();
              await new Promise(d => requestAnimationFrame(() => requestAnimationFrame(d)));
              obs.disconnect();
              return { n, circled: getComputedStyle(document.querySelector('.ask-choice[aria-pressed="true"]')).outlineWidth,
                       question: getComputedStyle(document.querySelector('.ask:not([hidden]) .ask-q')).backgroundColor }; }""")
            props = page.evaluate(PROPS)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert look["off"] is True
    assert look["idle"][:2] == ["solid", "1px"] and _near(_px(look["idle"][2]), props["--ink-pencil"], 2), look
    assert look["name"] == "underline", look
    assert look["question"] not in ("rgba(0, 0, 0, 0)", "transparent"), look
    assert look["hl"] == look["question"], "one highlighter"
    assert look["choice"] == "solid", look
    assert look["error"][0] == "solid" and "inset" in look["error"][1], look
    assert "repeating-linear-gradient" in look["rules"] and _near(_px(look["paper"]), props["--paper"], 2)
    assert _near(_px(look["glue"]), props["--glue"], 2), look
    assert "linear-gradient" in look["margin"], look
    for row in ROWS:
        assert f"body.ink-off :is({row[0]})" in look["sheet"] or row[2] == "write", row
    assert writes["n"] == 0, "the plain fallback wrote to the page"
    assert writes["circled"] == "2px" and writes["question"] in ("rgba(0, 0, 0, 0)", "transparent"), writes
    assert not [u for u in asked if "/static/ink/layer.js" in u or "vendor/three" in u]


def _px(s):
    """`rgb(r, g, b)` or `rgba(...)` as [r, g, b]."""
    return [int(float(x)) for x in re.findall(r"[\d.]+", s)[:3]]


@pytest.mark.browser
def test_an_idle_legal_pad_writes_nothing_and_its_ink_catches_up_in_frames(fleet_home, tmp_path, monkeypatch):
    """The render contract with the pad on the paper: the grammar's marks catch up within the frames
    a hand at the pen's speed needs (ground rule 5, counted in frames because CI draws in software),
    and once they have, an idle desk is zero DOM mutations and zero WebGL frames -- the running pen
    and the header count ask for no frame of their own."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _pad(tmp_path, monkeypatch, {"asks": _asks("asks"), "run": [_ev("run", "turn_started")]}, live={"run"})
    _config(fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _desk(browser, port, token, panes=2, count=True)
            _rest(page, "Ink.inspect().layer.marks.length >= 5")
            # Idle first: the catch-up below sets a class by hand, which the page's next redraw
            # would put back -- and the ink would still be answering that inside the idle window.
            idle = page.evaluate(IDLE_LOOP)
            rec = page.evaluate("""async () => {
              document.querySelector('.tile[data-repo="asks"]').classList.replace('state-needs_human', 'state-done');
              const frames = [];
              return await new Promise(done => {
                const tick = () => {
                  const l = Ink.inspect().layer;
                  frames.push({ frames: l.frames, marks: l.marks.map(m => [m.id, m.lane, m.drawn, m.selector, m.len, m.strokes]),
                                busy: l.busy });
                  if ((frames.length > 3 && !l.busy) || frames.length > 3000) return done(frames);
                  requestAnimationFrame(tick);
                };
                requestAnimationFrame(tick);
              });
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    check = [m for m in rec[-1]["marks"] if m[3] == DONE]
    assert len(check) == 1 and check[0][2] == 1, rec[-1]
    first = next(f for f in rec if any(m[3] == DONE for m in f["marks"]))
    frames = rec[-1]["frames"] - first["frames"] + 1
    bound = catch_up_frames(check)
    print(f"\n  the check caught up in {frames} frames (bound {bound})")
    assert 2 <= frames <= bound, (frames, bound)
    assert idle["n"] == 0, f"an idle legal pad wrote to the page: {idle}"
    assert idle["renders"] == 0, f"an idle legal pad was redrawn {idle['renders']} times"
