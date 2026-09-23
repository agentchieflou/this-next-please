"""Graph paper (#253, slice G of the ink epic #246): a grid on the page's own 28px baseline, a
mechanical pencil, ruled strokes snapped to the grid, and every agent's trace plotted on it.

The skin is `static/ink/skins/graph.js` (its mark table and materials) beside
`static/skins/graph/skin.css` (its colours, and its look under `body.ink-off`). Every mark comes
from a class or attribute `app.js` already sets, so these tests drive REAL agent states -- events
appended to the agent's stream, folded by the server, drawn by the page -- and never set a state
class by hand: a class the page owns is put back by its next draw. What is asserted:

* the paper state grammar (plan-ink §The state grammar): each state draws its mark when the page
  sets it, and the mark leaves by being erased (pencil) or struck (ink) when it goes -- the
  question is struck, never the agent's name;
* ruled strokes land on the grid's lines, and the grid is the page's 28px, a heavy line every 140;
* the mechanical pencil is the layer's pencil tuned thin, even and without taper;
* each agent's hour is plotted on the grid from the page's own data, and the 2D trace steps aside
  (keeping its sentence) only while the skin draws;
* reduced motion draws at once; the plain fallback draws the same table and the grid in CSS;
* `theme.check` holds every ink the skin introduces on its paper;
* an idle desk with the skin drawn is still zero DOM mutations and zero WebGL frames, and the ink
  catches up in a bounded number of frames.

CI renders in SwiftShader, which the probe calls `software`, so every test that needs ink opens
the desk with `?ink=on` -- the layer's test override, never a measurement.
"""
from __future__ import annotations
import json
import os
import re
import threading

import pytest

from agentdata import theme
from agentdata.fleet import events as E, fingerprint as FP, registry, serve as S, skins, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import AT_REST, COUNT_FETCHES, IDLE_LOOP, RECORD, catch_up_frames

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "graph.js")
CSS = os.path.join(STATIC, "skins", "graph", "skin.css")

GRID = 28
#: What the installed skills and CLI are, for every test here: every session began on them, so no
#: pane is stale unless a test says so (#240).
NOW = {"version": "9.9.9", "commit": "c" * 12, "skills": "5" * 12}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    FP.forget()
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """The desk module's globals are process-wide, which is right for a server and wrong for a suite
    that gives every test a fresh fleet directory."""
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})
    monkeypatch.setattr(S, "_measure_asks", {})


# ------------------------------------------------------------------------------- the agents


def ev(repo, kind, data=None):
    return E.event(repo, kind, data or {}, ticket="RDSD-1")


#: What puts an agent in each state, as the fold reads it (`agentstate.classify`). Running is not
#: an event: it is a process holding the checkout (`_run`), which outranks everything in the fold.
STATES = {
    "idle": [],
    "running": [],
    "error": [("error", {"exit_code": 2})],
    "done": [("phase_changed", {"from": "querying", "to": "done"})],
    "needs": [("question_opened", {"id": "q1", "question": "Which schema should it read?",
                                   "choices": ["dev", "prod"]})],
    "finding": [("friction", {"file": ".agent/friction/1-sql.md", "unblock": "grant read on the schema",
                              "severity": "blocker"})],
}


def _agent(tmp_path, name, state="idle", *, stale=False):
    # The phase is also `state.json`'s, which the server reads beside the stream.
    phase = "done" if state == "done" else "idle"
    Registry().add(make_project(tmp_path / name, phase=phase, ticket="RDSD-1"), name=name)
    started = {"pid": 1}
    if not stale:
        started["install"] = dict(NOW)
    E.append(name, [ev(name, "started", started),
                    ev(name, "assistant_text", {"text": "working on " + name}),
                    ev(name, "turn_ended", {"turn": "0"})] +
             [ev(name, k, d) for k, d in STATES[state]])
    if state == "running":
        _run(name)


def _run(name):
    """A process holding the checkout: this one, which is alive for as long as the test is. The
    server calls that agent supervised and running (`supervisor.live`)."""
    supervisor.write_lock(name, {"pid": os.getpid(), "repo": name, "ticket": "RDSD-1", "launch": []})
    # And the turn it began, which is what reaches an open desk: the stream moves on an event.
    _append(name, ("turn_started", {"turn": "1"}))


def _fail(name):
    """The process is gone and its last turn exited non-zero: the fold's `error`."""
    supervisor.clear_lock(name)
    _append(name, ("error", {"exit_code": 2}))


def _desk(tmp_path, fleet_home, agents, skin="graph"):
    """A desk of `agents` ({name: state}), every one a pane with a width, and the skin chosen."""
    for name, state in agents.items():
        stale = state == "stale"
        _agent(tmp_path, name, "idle" if stale else state, stale=stale)
    names = list(agents)
    S.arrange(order=names)
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text(json.dumps({"theme": {"skin": skin}}), encoding="utf-8")


def _serve():
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


def _open(browser, port, token, extra="&ink=on", *, panes=2, width=1500, height=900, reduced=False,
          count=False, table="graph"):
    """A desk page with the skin's table in force, waited on until every pane has its width."""
    page = browser.new_page(viewport={"width": width, "height": height},
                            reduced_motion="reduce" if reduced else "no-preference")
    if count:
        page.add_init_script(COUNT_FETCHES)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "ink:" in m.text else None)
    page.goto(f"http://127.0.0.1:{port}/?t={token}{extra}", wait_until="domcontentloaded")
    page.wait_for_function(
        f"""() => document.querySelectorAll('#grid .tile.is-solo').length === {panes}
             && [...document.querySelectorAll('#grid .tile')].every(t => !!t.dataset.tier)
             && !!window.Ink && (Ink.inspect().table || '').startsWith({table!r})
             && !document.body.classList.contains('is-stale')""", timeout=20000)
    return page, errors


def _tile_has(page, repo, cls, timeout=20000):
    """Wait for the PAGE to set a class on a pane: the state comes from the server's fold."""
    page.wait_for_function(
        "([r, c]) => { const t = document.querySelector(`.tile[data-repo=\"${r}\"]`); return !!t && t.classList.contains(c); }",
        arg=[repo, cls], timeout=timeout)


def _rest(page, also="true", timeout=30000):
    page.wait_for_function(f"() => ({AT_REST})() && ({also})", timeout=timeout)


def _marks(page):
    return page.evaluate("() => Ink.inspect().layer.marks")


def _of(marks, repo, selector_part, *, live=True):
    lane = "pane:" + repo
    return [m for m in marks if m["lane"] == lane and selector_part in m["selector"]
            and (not live or m["state"] == "drawn")]


def _strikes_of(marks, target):
    return [m for m in marks if m["strikeOf"] == target["id"]]


def _append(repo, *kinds):
    E.append(repo, [ev(repo, k, d) for k, d in kinds])


def _on_grid(v):
    return abs(v - round(v / GRID) * GRID) <= 0.75


def _ruled(mark):
    """Each of a ruled mark's strokes lies along a grid line: flat ones at a line's y, upright ones
    at a line's x."""
    out = []
    for b in mark["bounds"]:
        flat = (b["r"] - b["x"]) >= (b["b"] - b["y"])
        out.append(_on_grid(b["y"]) and _on_grid(b["b"]) if flat else _on_grid(b["x"]) and _on_grid(b["r"]))
    return out


# ========================================================================== without a browser


def test_graph_is_a_skin_with_a_module_and_every_ink_holds_on_its_paper():
    """Registered like any skin (skins.py: the settings page offers it), drawn with ink (its module
    ships beside the example), and every ink it introduces checked on its paper -- `theme.check`'s
    rule 5, per variant -- with the text keeping 4.5:1 where it crosses a heavy grid line."""
    assert "graph" in skins.SKINS and "graph" in S.ink_skins()
    assert os.path.isfile(MODULE) and os.path.isfile(CSS)
    graph = skins.SKINS["graph"]
    assert graph["default"] == "engineering" and set(graph["variants"]) == {"engineering", "blueprint"}
    for name, spec in graph["variants"].items():
        palette = theme.get(spec["base"])
        assert set(spec["inks"]) == {"pencil", "pen", "red", "green", "marker", "highlighter", "trace"}
        theme.check(palette, composited_panel=spec["composited_panel"], skin=f"graph:{name}",
                    inks=spec["inks"])
        assert theme.contrast_ratio(palette.text, spec["grid"]) >= 4.5, name
    # One of the light variant's inks too pale for its paper is refused, naming the skin.
    engineering = graph["variants"]["engineering"]
    with pytest.raises(theme.ThemeError) as e:
        theme.check(theme.get(engineering["base"]), composited_panel=engineering["composited_panel"],
                    skin="graph:engineering", inks=dict(engineering["inks"], pencil="#D3E0CC"))
    assert "ink 'pencil'" in e.value.args[0] and "graph:engineering" in e.value.args[0]


def _css_blocks():
    """`--name: value` per variant, as skin.css declares them: the default in the block with no
    variant attribute, each other variant in its own."""
    css = open(CSS, encoding="utf-8").read()
    out = {}
    for sel, body in re.findall(r"(body\[data-skin=\"graph\"\][^{]*)\{([^}]*)\}", css):
        m = re.search(r'data-skin-variant="([\w-]+)"', sel)
        variant = m.group(1) if m else skins.SKINS["graph"]["default"]
        if ":not" in sel or " " in sel.strip():
            continue
        for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body):
            out.setdefault(variant, {})[k] = v.strip()
    return out


def test_the_stylesheet_paints_the_numbers_skins_py_checks():
    """The colours live in skin.css as custom properties -- the module reads them at paint time and
    never carries a hex -- and they are the same numbers `theme.check` was run on, per variant."""
    blocks = _css_blocks()
    for name, spec in skins.SKINS["graph"]["variants"].items():
        got = blocks[name]
        assert got["--paper"].upper() == spec["composited_panel"].upper(), name
        assert got["--grid-major"].upper() == spec["grid"].upper(), name
        for tool, ink in spec["inks"].items():
            assert got[f"--ink-{tool}"].upper() == ink.upper(), (name, tool)
        assert "--grid" in got
    module = open(MODULE, encoding="utf-8").read()
    # A colour is a quoted `#hex` or a `0x` number; `#253` in a comment is an issue.
    assert not re.search(r"[\"'`]#[0-9a-fA-F]{3,8}\b|0x[0-9a-fA-F]{6}\b", module), "a colour written in the module"
    assert not re.search(r"^\s*import\s", module, re.M), "a static import does not carry the token"
    for name in ("--paper", "--grid", "--grid-major", "--ink-trace"):
        assert f'"{name}"' in module, name


# ============================================================================== in a browser


@pytest.mark.browser
def test_idle_running_error_and_done_draw_their_marks_and_leave_by_erase_or_strike(fleet_home, tmp_path):
    """plan-ink §The state grammar, the pane's four states, from the classes the page sets:

    * idle -- a pencil outline and a pencil underline under the name; they are ERASED when the
      agent starts a turn (pencil leaves by the eraser);
    * running -- a pen underline under the name; it is STRUCK when the turn fails (ink leaves by a
      pen line through it);
    * error -- a red marker box round the pane and a bang in the margin;
    * done -- a green check in the margin.

    And the ruled ones -- outlines and underlines -- lie on the grid's lines."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "idle", "beta": "done"})
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token)
            _tile_has(page, "beta", "is-done")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.shape === 'outline'"
                        " && m.state === 'drawn') && Ink.inspect().layer.marks.some(m => m.shape === 'check')")
            seen["idle"] = _marks(page)
            _run("alpha")
            _tile_has(page, "alpha", "state-running")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.tool === 'pen'"
                        " && m.shape === 'underline' && m.state === 'drawn')"
                        " && !Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.tool === 'pencil'"
                        " && m.shape === 'outline')")
            seen["running"] = _marks(page)
            _fail("alpha")
            _tile_has(page, "alpha", "state-error")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.shape === 'bang'"
                        " && m.state === 'drawn')")
            seen["error"] = _marks(page)
            seen["skin"] = page.evaluate("() => Ink.inspect().layer.skin")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    idle = seen["idle"]
    [outline] = _of(idle, "alpha", ".tile.state-idle:not")
    [under] = _of(idle, "alpha", ".tile.state-idle .head .repo")
    assert outline["tool"] == "pencil" and outline["shape"] == "outline" and outline["strokes"] == 4
    assert under["tool"] == "pencil" and under["shape"] == "underline"
    assert all(_ruled(outline)) and all(_ruled(under)), (outline["bounds"], under["bounds"])
    # The underline is on the first grid line under the name, never through it.
    assert under["bounds"][0]["y"] >= under["box"]["y"] + under["box"]["h"] - 0.75, under
    [check] = _of(idle, "beta", ".tile.is-done")
    assert check["tool"] == "green" and check["shape"] == "check"
    assert seen["skin"]["paper"] == 3 and seen["skin"]["errors"] == [], seen["skin"]

    running = seen["running"]
    # Pencil leaves by the eraser: the outline and the underline are gone, with no strike left.
    assert not [m for m in running if m["lane"] == "pane:alpha" and m["tool"] == "pencil"
                and m["shape"] in ("outline", "underline")], running
    [pen] = _of(running, "alpha", ".tile.state-running .head .repo")
    assert pen["tool"] == "pen" and all(_ruled(pen))

    error = seen["error"]
    # Ink leaves by a strike: the running underline is still there, struck through in pen.
    [was] = _of(error, "alpha", ".tile.state-running .head .repo", live=False)
    assert was["state"] == "struck" and _strikes_of(error, was)[0]["tool"] == "pen", was
    [box] = _of(error, "alpha", ".tile.state-error")[:1]
    boxes = [m for m in _of(error, "alpha", ".tile.state-error") if m["shape"] == "outline"]
    bangs = [m for m in _of(error, "alpha", ".tile.state-error") if m["shape"] == "bang"]
    assert boxes and boxes[0]["tool"] == "marker" and all(_ruled(boxes[0])), box
    assert bangs and bangs[0]["tool"] == "red"


@pytest.mark.browser
def test_needs_you_then_answered_strikes_the_question_and_never_the_name(fleet_home, tmp_path):
    """needs you: the highlighter on the name and on the question, and pencil loops round the
    choices. answered: pressing a choice strikes the question and its highlight through in pen and
    circles the chosen answer (its pencil loop is erased); when the agent no longer needs you the
    name's highlight is taken up, never struck through the agent's name."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"beta": "needs", "alpha": "idle"})
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token)
            _tile_has(page, "beta", "needs-human")
            page.wait_for_selector('.tile[data-repo="beta"] .ask:not([hidden]) .ask-choice', timeout=20000)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.lane === 'pane:beta' && m.shape === 'loop'"
                        " && m.state === 'drawn').length === 2")
            seen["needs"] = _marks(page)
            page.click('.tile[data-repo="beta"] .ask:not([hidden]) .ask-choice >> nth=0')
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:beta' && m.shape === 'ellipse'"
                        " && m.state === 'drawn')")
            seen["answered"] = _marks(page)
            _append("beta", ("question_answered", {"id": "q1", "question": "Which schema should it read?"}))
            page.wait_for_function("() => !document.querySelector('.tile[data-repo=\"beta\"]')"
                                   ".classList.contains('needs-human')", timeout=20000)
            _rest(page, "!Ink.inspect().layer.marks.some(m => m.lane === 'pane:beta' && m.tool === 'highlighter'"
                        " && m.selector.includes('.repo'))")
            seen["after"] = _marks(page)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    needs = seen["needs"]
    [name] = _of(needs, "beta", ".tile.needs-human .head .repo")
    [question] = _of(needs, "beta", ".ask-q")
    loops = _of(needs, "beta", 'aria-pressed="false"')
    assert name["tool"] == "highlighter" and name["shape"] == "lines"
    assert question["tool"] == "highlighter" and question["shape"] == "lines"
    assert len(loops) == 2 and {m["tool"] for m in loops} == {"pencil"} and {m["shape"] for m in loops} == {"loop"}

    answered = seen["answered"]
    [q] = [m for m in answered if m["id"] == question["id"]]
    struck = _strikes_of(answered, q)
    assert q["state"] == "struck" and struck and struck[0]["tool"] == "pen", q
    [circle] = _of(answered, "beta", 'aria-pressed="true"')
    assert circle["tool"] == "pen" and circle["shape"] == "ellipse"
    assert len(_of(answered, "beta", 'aria-pressed="false"')) == 1, "the chosen answer's pencil loop is erased"
    assert [m for m in answered if m["id"] == name["id"]][0]["state"] == "drawn", "the name is still highlighted"

    after = seen["after"]
    assert not [m for m in after if m["id"] == name["id"]], "the name's highlight was not taken up"
    assert not [m for m in after if m["strikeOf"] == name["id"]], "the agent's name was struck through"


@pytest.mark.browser
def test_stale_a_finding_and_the_count_are_written_and_the_hour_is_plotted_on_the_grid(fleet_home, tmp_path):
    """stale (#240): the chip written in pencil as a margin note, an arrow to the run line, and a
    dashed pencil outline on the grid. A finding (a skill's STOP in the transcript): a red ellipse
    round the line, the highlighter on its token, its own text written. The count: handwritten.
    And each agent's hour, plotted on the grid line under its trace from the page's own
    `data-trace`, again when the hour changes -- with the 2D canvas transparent but still its
    sentence."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "stale", "beta": "finding"})
    server, token, port = _serve()
    seen = {}
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token)
            page.wait_for_selector('.tile[data-repo="beta"] .transcript li.friction', timeout=20000)
            page.wait_for_selector('.tile[data-repo="alpha"] .oldsession:not([hidden])', timeout=20000)
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.shape === 'arrow'"
                        " && m.state === 'drawn') && Ink.inspect().layer.skin.frames === 2")
            seen["marks"] = _marks(page)
            plot = """async () => (await import(q('/static/ink/skins/graph.js'))).plotted()"""
            seen["plot"] = page.evaluate(plot)
            seen["canvas"] = page.evaluate("""() => [...document.querySelectorAll('.tile .head .trace')].map(c => ({
                repo: c.closest('.tile').dataset.repo, opacity: getComputedStyle(c).opacity,
                label: c.getAttribute('aria-label'), trace: c.dataset.trace,
                box: (r => ({ x: r.left, y: r.top, w: r.width, h: r.height }))(c.getBoundingClientRect()) }))""")
            _append("alpha", *[("tool_call", {"tool": "grep"}) for _ in range(6)])
            page.wait_for_function("t => document.querySelector('.tile[data-repo=\"alpha\"] .trace')"
                                   ".dataset.trace !== t", arg=seen["canvas"][0]["trace"], timeout=20000)
            # Plotted again on the layer's next frame -- the one the attribute's change asked for.
            page.wait_for_function("""async () => { const now = (await import(q('/static/ink/skins/graph.js')))
                .plotted().find(p => p.repo === 'alpha');
              return !!now && now.trace === document.querySelector('.tile[data-repo="alpha"] .trace').dataset.trace; }""",
                                   timeout=20000)
            _rest(page)
            seen["replot"] = page.evaluate(plot)
            seen["counts"] = page.evaluate("() => document.getElementById('counts').style.clipPath")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)

    marks = seen["marks"]
    note = [m for m in _of(marks, "alpha", ".oldsession") if m["shape"] == "write"]
    arrow = [m for m in _of(marks, "alpha", ".oldsession") if m["shape"] == "arrow"]
    dashed = _of(marks, "alpha", ".tile:has(")
    assert note and note[0]["tool"] == "pencil" and note[0]["drawn"] == 1
    assert arrow and arrow[0]["tool"] == "pencil" and arrow[0]["strokes"] == 3
    assert dashed and dashed[0]["tool"] == "pencil" and all(_ruled(dashed[0])), dashed
    assert not _of(marks, "alpha", ".tile.state-idle:not"), "a stale pane's outline is the dashed one"
    ellipse = [m for m in _of(marks, "beta", "li.friction") if m["shape"] == "ellipse"]
    token_ = _of(marks, "beta", "li.friction .k")
    text = _of(marks, "beta", "li.friction .v")
    assert ellipse and ellipse[0]["tool"] == "red"
    assert token_ and token_[0]["tool"] == "highlighter" and text and text[0]["shape"] == "write"
    [count] = [m for m in marks if m["lane"] == "header" and "#counts" in m["selector"]]
    assert count["shape"] == "write" and count["drawn"] == 1 and seen["counts"] == ""
    axes = [m for m in marks if ".trace[data-trace]" in m["selector"]]
    assert len(axes) == 2 and all(all(_ruled(m)) for m in axes), axes

    for c in seen["canvas"]:
        assert c["opacity"] == "0" and c["label"], "the canvas steps aside and keeps its sentence"
    plots = {p["repo"]: p for p in seen["plot"]}
    assert set(plots) == {"alpha", "beta"}, seen["plot"]
    for c in seen["canvas"]:
        got = plots[c["repo"]]
        minutes = len(c["trace"].split("|")[1].split())
        assert got["base"] % GRID == 0 and abs(got["base"] - (c["box"]["y"] + c["box"]["h"])) <= GRID / 2, got
        assert len(got["points"]) == minutes, (len(got["points"]), minutes)
        xs = [pt[0] for pt in got["points"]]
        assert c["box"]["x"] <= min(xs) and max(xs) <= c["box"]["x"] + c["box"]["w"], (xs[0], xs[-1], c["box"])
        assert all(got["base"] - c["box"]["h"] - 0.5 <= pt[1] <= got["base"] + 0.5 for pt in got["points"])
        axis = [m for m in axes if m["lane"] == "pane:" + c["repo"]][0]
        assert abs(axis["bounds"][0]["y"] - got["base"]) <= 0.75, "the plot sits on its ruled axis"
    before, after = plots["alpha"], {p["repo"]: p for p in seen["replot"]}["alpha"]
    assert before["trace"] == seen["canvas"][0]["trace"] or before["trace"] == seen["canvas"][1]["trace"]
    assert after["trace"] != before["trace"], "the hour changed and was not plotted again"
    # The busiest minute is as tall as the canvas; a quiet one sits on the axis.
    alpha = [c for c in seen["canvas"] if c["repo"] == "alpha"][0]
    counts = [float(n.rstrip("!")) for n in after["trace"].split("|")[1].split()]
    busiest = counts.index(max(counts))
    assert abs(after["points"][busiest][1] - (after["base"] - alpha["box"]["h"])) <= 0.5, after["points"][busiest]
    assert all(abs(pt[1] - after["base"]) <= 0.5 for pt, n in zip(after["points"], counts) if n == 0)


@pytest.mark.browser
def test_the_mechanical_pencil_is_thin_even_and_ruled(fleet_home, tmp_path):
    """The skin's pencil is the layer's pencil tuned (the table's `tools`): thin, even, and with no
    wobble, bow or taper. A table asking the layer for something it cannot tune or rule is refused,
    naming the row."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "idle", "beta": "idle"})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token)
            got = page.evaluate("""async () => {
              const pen = await import(q('/static/ink/pen.js'));
              const m = await import(q('/static/ink/skins/graph.js'));
              const tune = m.options().tools.pencil;
              const path = { pts: [[0, 0], [200, 0]] };
              const width = g => Array.from(g.attrs.aW);
              const plain = pen.geometry(path, 'pencil', 7), tuned = pen.geometry(path, 'pencil', 7, tune);
              const ys = g => g.P.map(p => p[1]);
              const refused = [];
              for (const bad of [
                  { marks: [{ selector: '.tile', tool: 'pencil', shape: 'loop', snap: 28 }] },
                  { marks: [{ selector: '.tile', tool: 'pencil', shape: 'outline', snap: 2 }] },
                  { marks: [{ selector: '.tile', tool: 'pen', shape: 'outline', leaves: 'faded' }] },
                  { marks: [], tools: { crayon: { w: 1 } } },
                  { marks: [], tools: { pencil: { kind: 3 } } },
                  { marks: [], tools: { pencil: { lam: 0 } } }]) {
                try { Ink.setSkin(bad); refused.push(''); } catch (e) { refused.push(String(e.message)); }
              }
              return { plain: [Math.min(...width(plain)), Math.max(...width(plain)), Math.max(...ys(plain).map(Math.abs))],
                       tuned: [Math.min(...width(tuned)), Math.max(...width(tuned)), Math.max(...ys(tuned).map(Math.abs))],
                       refused, table: Ink.inspect().table };
            }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    lo, hi, drift = got["tuned"]
    assert hi <= 1.2 and hi - lo <= 0.12, f"not thin and even: {got['tuned']} (the plain pencil: {got['plain']})"
    assert drift < 0.05, "a mechanical pencil's line does not wander"
    assert got["plain"][1] - got["plain"][0] > 0.3, "the plain pencil tapers; the tuning is what changed"
    snap_loop, snap_small, leaves, crayon, kind, lam = got["refused"]
    assert "`snap`" in snap_loop and "mark 0" in snap_loop and "`snap`" in snap_small
    assert "`leaves`" in leaves and "crayon" in crayon and "tools.pencil.kind" in kind
    assert "tools.pencil.lam" in lam
    assert got["table"].startswith("graph"), "a refused table leaves the one in force alone"


@pytest.mark.browser
def test_reduced_motion_draws_the_paper_at_once(fleet_home, tmp_path):
    """Reduced motion draws every mark at once, with no travelling pen -- and leaves at once."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "idle", "beta": "done"})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token, reduced=True)
            _tile_has(page, "beta", "is-done")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.lane === 'pane:alpha' && m.shape === 'outline')")
            # Leaving, counted in frames: the idle pencil is gone within two of the page's draw.
            _run("alpha")
            went = page.evaluate("""async () => {
              const t = document.querySelector('.tile[data-repo="alpha"]');
              const frames = [];
              for (let i = 0; i < 2000 && !t.classList.contains('state-running'); i++) {
                await new Promise(d => requestAnimationFrame(d));
              }
              for (let i = 0; i < 3; i++) {
                const l = Ink.inspect().layer;
                frames.push({ hands: l.hands, busy: l.busy,
                              marks: l.marks.filter(m => m.lane === 'pane:alpha').map(m => [m.tool, m.shape, m.state, m.drawn]) });
                await new Promise(d => requestAnimationFrame(d));
              }
              return frames;
            }""")
            layer = page.evaluate("() => Ink.inspect().layer")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert layer["reduced"] is True and layer["hands"] is False
    settled = went[2]["marks"]
    assert ["pen", "underline", "drawn", 1] in settled, went
    assert not [m for m in settled if m[0] == "pencil" and m[1] in ("outline", "underline")], went
    assert not any(f["hands"] for f in went)


@pytest.mark.browser
def test_the_plain_fallback_is_the_same_table_on_a_css_grid(fleet_home, tmp_path):
    """Where the gate is off (here: nothing measured this browser), the same table is drawn plain by
    the layer's CSS fallback, and the grid is the skin's CSS, from the same origin and pitches. The
    2D trace is the trace again. Nothing of the layer is fetched."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "idle", "beta": "needs"})
    server, token, port = _serve()
    asked = []
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            page.on("request", lambda r: asked.append(r.url))
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_function("""() => document.body.classList.contains('ink-off')
                && (Ink.inspect().table || '').startsWith('graph') && Ink.inspect().plain
                && document.querySelector('.tile[data-repo="beta"]').classList.contains('needs-human')
                && document.querySelector('.tile[data-repo="alpha"]').classList.contains('state-idle')""",
                                   timeout=20000)
            got = page.evaluate("""() => {
              const cs = s => getComputedStyle(document.querySelector(s));
              return {
                body: cs('body').backgroundImage, size: cs('body').backgroundSize,
                outline: cs('.tile[data-repo="alpha"]').outlineStyle,
                underline: cs('.tile[data-repo="alpha"] .head .repo').textDecorationLine,
                highlight: cs('.tile[data-repo="beta"] .head .repo').backgroundColor,
                trace: cs('.tile[data-repo="alpha"] .trace').opacity,
                canvas: !!document.getElementById('ink'), verdict: Ink.verdict.source,
              }; }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert got["body"].count("linear-gradient") == 4 and "140px 140px" in got["size"] and "28px 28px" in got["size"], got
    assert got["outline"] == "solid" and got["underline"] == "underline", got
    assert got["highlight"] not in ("rgba(0, 0, 0, 0)", "transparent"), got
    assert got["trace"] != "0" and not got["canvas"], got
    assert not [u for u in asked if "/static/ink/layer.js" in u or "three.module" in u], "the fallback fetched the layer"


@pytest.mark.browser
def test_an_idle_graph_desk_writes_nothing_draws_nothing_and_caught_up_in_bounded_frames(fleet_home, tmp_path):
    """The render contract with the skin drawing: once its marks and plots are on the paper, an
    idle desk is zero DOM mutations and zero WebGL frames. And the skin's marks caught up within
    the frames a hand at the pen's speed needs for them (ground rule 5), with the trace plotted in
    the frames the layer drew anyway: the skin never asks for one of its own."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, {"alpha": "idle", "beta": "done"}, skin="none")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors = _open(browser, port, token, count=True, table="")
            _tile_has(page, "beta", "is-done")
            page.evaluate("s => post('theme', { skin: s })", "graph")
            page.wait_for_function("() => (Ink.inspect().table || '').startsWith('graph') && !!Ink.inspect().layer",
                                   timeout=20000)
            rec = page.evaluate(RECORD, [[]])
            _rest(page, "Ink.inspect().layer.skin.frames === 2")
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    last = rec[-1]
    assert last["marks"] and all(m[2] == 1 for m in last["marks"]), last
    drawing = [f for f in rec if f["busy"]]
    frames = (drawing[-1]["frames"] - drawing[0]["frames"] + 1) if drawing else 0
    bound = catch_up_frames(last["marks"])
    print(f"\n  graph paper caught up in {frames} frames (bound {bound})")
    assert frames <= bound, (frames, bound)
    assert count["n"] == 0, f"an idle graph desk wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle graph paper was redrawn {count['renders']} times"
