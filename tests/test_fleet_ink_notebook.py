"""The notebook (#249) and the night notebook (#250): the first skin drawn with ink, and the marks
every later paper skin is measured against (plan-ink §C, §D).

The skin is a module (`static/ink/skins/notebook.js`) whose mark table is plan-ink §The state
grammar, and a stylesheet (`static/skins/notebook/skin.css`) that holds its paper and inks as custom
properties. It is chosen like any skin, through the config the settings page writes. What is
asserted:

* `skins.py` offers it with a light and a dark variant, and the stylesheet paints the numbers
  `skins.py` declares -- the paper, the rules' partner inks, the words -- which `theme.check` holds:
  each ink 3:1 on its paper, the text 4.5:1 on the paper and through the highlighter;
* the module carries no colour and no markup;
* with ink on (`?ink=on`, the test override), each state's mark is drawn when the fold puts the
  state on the pane -- real events through the real server, never a class set by the test -- and
  leaves by being erased (pencil) or struck (ink) when it goes;
* the running line grows with the turn and carries the pen's tip; an answered question is struck
  and its answer circled, never the agent's name; the stale note, the finding and the header's
  count;
* reduced motion draws at once; the dark variant screens the highlighter onto charcoal stock;
* under `body.ink-off` the same table is drawn plain, on a ruled page;
* an idle desk with the notebook on it makes zero DOM mutations and zero WebGL frames, and the ink
  settles in a bounded number of frames.
"""
from __future__ import annotations
import dataclasses
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, serve as S, skins, supervisor

# The ink layer's own fixtures and helpers: the fleet directory, the desk's globals (autouse), the
# desk and the page, and what the layer shows of itself.
from test_fleet_ink import (  # noqa: F401 - fixtures are used by name
    COUNT_FETCHES, IDLE_LOOP, PEN, _layer, _marks, _open, _own_desk_globals, _repos, _rest, _serve,
    _stop, fleet_home)
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "notebook.js")
CSS = os.path.join(STATIC, "skins", "notebook", "skin.css")

#: The tools a variant declares an ink for, and the custom property the stylesheet sets each in.
TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")


# ============================================================================== without a browser


def _css_block(css: str, variant: str) -> dict:
    """The custom properties the stylesheet sets for a variant: the base block, and the dark one
    over it."""
    blocks = [r'body\[data-skin="notebook"\]\s*\{(.*?)\}']
    if variant == "dark":
        blocks.append(r'body\[data-skin="notebook"\]\[data-skin-variant="dark"\]\s*\{(.*?)\}')
    out = {}
    for pattern in blocks:
        body = re.search(pattern, css, re.S).group(1)
        out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", body)))
    return out


def test_the_notebook_is_a_skin_with_a_light_and_a_dark_variant():
    """Chosen through skins.py like every skin, so the settings page offers it. Dark is a variant,
    not a family: skins drive palettes, and the night page's ground is named by its variant."""
    nb = skins.SKINS["notebook"]
    assert nb["default"] == "light" and set(nb["variants"]) == {"light", "dark"}
    assert skins.split("notebook") == ("notebook", "light")
    assert skins.get_skin("notebook:dark")["base"] == "dark"
    assert theme.get(nb["variants"]["dark"]["base"]).ground and \
        theme.rel_luminance(theme.hex_to_rgb(nb["variants"]["dark"]["composited_panel"])) < 0.05
    assert "notebook" in [s["name"] for s in skins.list_skins()]
    assert S.ink_skins() == ["example", "notebook"]


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The paper, every ink, the text and the muted words: declared once in skins.py (where
    `theme.check` reads them) and painted by skin.css (where the page and the module read them),
    held to one number by this test rather than by somebody updating both."""
    css = open(CSS, encoding="utf-8").read()
    for variant, spec in skins.SKINS["notebook"]["variants"].items():
        props = _css_block(css, variant)
        assert props["paper"].upper() == spec["composited_panel"].upper(), variant
        assert props["text"].upper() == spec["text"].upper(), variant
        assert props["muted"].upper() == spec["muted"].upper(), variant
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), (variant, tool)
        assert "rule" in props and "margin" in props, variant


def test_theme_check_holds_every_ink_on_the_notebooks_paper():
    """Rule 5 of `theme.check` with the pairs the notebook brings: each ink 3:1 on its paper, the
    text 4.5:1 through the highlighter -- for the palette the variant names, and for the words the
    skin writes itself (`text`, `muted`), which sit on the same paper."""
    for variant, spec in skins.SKINS["notebook"]["variants"].items():
        base = theme.get(spec["base"])
        paper = spec["composited_panel"]
        theme.check(base, composited_panel=paper, skin=f"notebook:{variant}", inks=spec["inks"])
        theme.check(dataclasses.replace(base, text=spec["text"]), composited_panel=paper,
                    skin=f"notebook:{variant}", inks=spec["inks"])
        assert theme.contrast_ratio(spec["muted"], paper) >= 4.5, variant


def test_the_module_carries_no_colour_and_no_markup():
    """A palette colours the inks and the skin's stylesheet chooses the paper: the module reads
    both at paint time (desk-ink §Writing a skin, rule 3), and it has no static import (rule 1)."""
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the notebook module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList"):
        assert banned not in code, banned


# ================================================================================ in a browser


def _desk(tmp_path, fleet_home, names=("alpha", "beta"), skin="notebook"):
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


@pytest.fixture()
def alive(monkeypatch):
    """The agents a process is holding. The pane shows running (and done) only for a supervised
    agent -- a turn left open by a process that is gone is idle and says so (#147) -- so the test
    names which are, and the server's own fold does the rest."""
    names: set = set()
    real = supervisor.live
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 777, "repo": name} if name in names else real(name))
    return names


@pytest.fixture()
def finished(monkeypatch, alive):
    """Agents whose process is still held but whose turn is over: the fold then says what the
    stream says -- `done` for a terminal phase -- rather than `running`, which a held process
    otherwise always is. The one way the desk shows a supervised agent done."""
    names: set = set()
    real = agentstate.derive

    def derive(events, *, live=False, open_questions=None):
        mine = bool(events) and events[0].get("repo") in names
        return real(events, live=False if mine else live, open_questions=open_questions)
    monkeypatch.setattr(agentstate, "derive", derive)
    return names


def _emit(page, repo, *events):
    """Something happens to an agent: its events are written where the fold reads them, and the page
    is asked to look -- the classes come from the server's fold, never from the test."""
    E.append(repo, [E.event(repo, kind, data, ticket="RDSD-1") for kind, data in events])
    page.evaluate("() => refresh()")


def _until_class(page, repo, cls, on=True):
    page.wait_for_function(
        "([r, c, on]) => { const t = document.querySelector(`.tile[data-repo=\"${r}\"]`);"
        " return !!t && t.classList.contains(c) === on; }", arg=[repo, cls, on], timeout=15000)


def _notebook(page, variant="light"):
    page.wait_for_function(f"() => Ink.inspect().table === 'notebook:{variant}'", timeout=15000)


def _of(marks, lane, sel_part, tool=None, shape=None, live=True):
    """The marks in one pane whose row's selector contains `sel_part`."""
    out = [m for m in marks if m["lane"] == lane and sel_part in m["selector"]
           and (tool is None or m["tool"] == tool) and (shape is None or m["shape"] == shape)]
    if live:
        out = [m for m in out if m["state"] == "drawn" and not m["strikeOf"] and m["visible"]]
    return out


def _struck(marks, target_ids):
    return {m["strikeOf"] for m in marks if m["strikeOf"] in target_ids and m["state"] == "drawn"}


@pytest.mark.browser
def test_the_notebook_draws_the_state_grammar_and_each_mark_leaves_by_erase_or_strike(fleet_home, tmp_path, alive,
                                                                                    finished):
    """idle, running, error and done, each drawn when the fold puts it on the pane: pencil erased
    as the state goes, ink struck through. The running line grows with the turn, and the pen's tip
    sits at its end until the line is struck."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _notebook(page)
            A = "pane:alpha"

            # idle: a pencil outline and a pencil line under the name, on both panes.
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
            marks = _marks(page)
            for lane in (A, "pane:beta"):
                assert _of(marks, lane, ".tile.state-idle", "pencil", "outline")
                assert _of(marks, lane, "state-idle .head .repo", "pencil", "underline")
            layer = _layer(page)
            assert layer["skin"]["hooks"] == ["paper", "frame"] and layer["skin"]["paper"] == 1
            assert layer["skin"]["frames"] == 2 and layer["skin"]["errors"] == []
            assert layer["mode"] == 1 and not layer["dark"], "light stock: the highlighter multiplies"

            # running: the pencil goes (erased), the pen underline comes, with its tip.
            alive.add("alpha")
            _emit(page, "alpha", ("turn_started", {}))
            _until_class(page, "alpha", "state-running")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-running') && m.state === 'drawn')")
            marks = _marks(page)
            assert not [m for m in marks if m["lane"] == A and "state-idle" in m["selector"]], \
                "the idle pencil is erased, not kept"
            run = _of(marks, A, "state-running", "pen", "underline")
            assert len(run) == 1 and run[0]["strokes"] == 2 and run[0]["drawn"] == 1, run
            before = run[0]["len"]

            # It grows with the turn: a line in the transcript, a step more of pen.
            _emit(page, "alpha", ("assistant_text", {"text": "reading the view"}),
                  ("assistant_text", {"text": "and its grain"}))
            page.wait_for_function("() => document.querySelectorAll('.tile[data-repo=\"alpha\"] .transcript > li').length >= 3",
                                   timeout=15000)
            _rest(page, f"Ink.inspect().layer.marks.some(m => m.selector.includes('state-running')"
                        f" && m.state === 'drawn' && m.len > {before} + 10)")
            grown = _of(_marks(page), A, "state-running", "pen", "underline")[0]
            assert grown["drawn"] == 1 and grown["strokes"] == 2, grown

            # error: the pen line is struck (its tip lifted first), a red marker box and a bang.
            alive.discard("alpha")
            _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("error", {"exit_code": 2}))
            _until_class(page, "alpha", "state-error")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-error') && m.state === 'drawn').length === 2")
            marks = _marks(page)
            gone = [m for m in marks if m["lane"] == A and "state-running" in m["selector"] and not m["strikeOf"]]
            assert len(gone) == 1 and gone[0]["state"] == "struck" and gone[0]["strokes"] == 1, \
                "the running line is struck, and its tip lifted"
            assert _struck(marks, {gone[0]["id"]}) == {gone[0]["id"]}
            assert _of(marks, A, "state-error", "marker", "loop")
            assert _of(marks, A, "state-error", "marker", "bang")

            # done: a green check in the margin, on the other pane.
            alive.add("beta")
            finished.add("beta")
            _emit(page, "beta", ("phase_changed", {"from": "build", "to": "done"}))
            _until_class(page, "beta", "state-done")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-done') && m.state === 'drawn')")
            marks = _marks(page)
            assert _of(marks, "pane:beta", "state-done", "green", "check")
            assert not [m for m in marks if m["lane"] == "pane:beta" and "state-idle" in m["selector"]]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


ANSWER = """([repo]) => new Promise(done => {
  const tile = document.querySelector(`.tile[data-repo="${repo}"]`);
  tile.querySelector('.ask-choice').click();
  tile.querySelector('.asks-send').click();
  const wait = () => tile.querySelector('.ask.is-answered') ? done(true) : requestAnimationFrame(wait);
  wait();
})"""


@pytest.mark.browser
def test_needing_you_is_highlighted_and_answering_strikes_the_question_never_the_name(fleet_home, tmp_path):
    """needs you: the name and the question highlighted, pencil loops round the choices. Answered:
    the question and its highlight struck through in pen, the chosen answer circled, the loops
    erased -- and nothing struck on the agent's name, the flaw both prototypes had."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            # The server would resume the agent with the answer; the page only needs its reply.
            page.route("**/api/answer*", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body='{"ok": true, "action": "answer", "repo": "alpha", "pid": 1, "answered": ["q1"]}'))
            _notebook(page)
            A = "pane:alpha"
            _emit(page, "alpha", ("question_opened", {"question": "which window should this land in?",
                                                      "id": "q1", "blocking": True,
                                                      "choices": ["left", "right"]}))
            _until_class(page, "alpha", "needs-human")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('needs-human')"
                        " && m.state === 'drawn' && m.visible).length === 4")
            marks = _marks(page)
            name = _of(marks, A, "needs-human .head .repo", "highlighter", "lines")
            question = _of(marks, A, ".ask-q", "highlighter", "lines")
            loops = _of(marks, A, ".ask-choice", "pencil", "loop")
            assert len(name) == 1 and len(question) == 1 and len(loops) == 2, marks

            assert page.evaluate(ANSWER, ["alpha"])
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('is-answered .ask-q') && m.state === 'drawn')"
                        " && Ink.inspect().layer.marks.some(m => m.selector.includes('aria-pressed') && m.state === 'drawn')")
            marks = _marks(page)
            assert _of(marks, A, "is-answered .ask-q", "pen", "strike"), "the question is struck"
            circled = _of(marks, A, "aria-pressed", "pen", "ellipse")
            assert len(circled) == 1, "the chosen answer is circled"
            assert _struck(marks, {question[0]["id"]}) == {question[0]["id"]}, "its highlight is struck"
            assert not [m for m in marks if m["lane"] == A and ".ask-choice" in m["selector"]
                        and m["tool"] == "pencil"], "the loops are erased"
            # The name keeps its highlight, unstruck: the agent still needs you until it resumes.
            assert _of(marks, A, "needs-human .head .repo", "highlighter", "lines")
            assert not _struck(marks, {name[0]["id"]}), "the agent's name is never struck"
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_stale_note_the_finding_and_the_header_count(fleet_home, tmp_path, monkeypatch):
    """stale (#240): the chip's words handwritten in pencil with an arrow to the run line, and a
    dashed pencil outline. A finding -- a friction the agent recorded -- a red ellipse round its
    line, the highlighter on its token, its text written. The header's count: when it changes, the
    old number is struck beside the new one, which is written again."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    stale = set()
    monkeypatch.setattr(S, "_stale_cell", lambda stream, installed: {
        "stale": any(e.get("repo") in stale for e in stream[:1]), "unknown": False,
        "reason": "began on older skills", "skills_changed": []})
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _notebook(page)
            B = "pane:beta"
            stale.add("beta")
            page.evaluate("() => refresh()")
            page.wait_for_selector('.tile[data-repo="beta"] .oldsession:not([hidden])', timeout=15000)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('oldsession') && m.state === 'drawn').length === 3")
            marks = _marks(page)
            note = _of(marks, B, ".oldsession:not([hidden])", "pencil", "write")
            arrow = _of(marks, B, ".oldsession:not([hidden])", "pencil", "arrow")
            outline = _of(marks, B, ":has(.oldsession", "pencil", "outline")
            assert len(note) == 1 and note[0]["drawn"] == 1 and note[0]["clip"] == "", note
            assert len(arrow) == 1 and arrow[0]["strokes"] == 3 and len(outline) == 1, marks

            _emit(page, "beta", ("friction", {"severity": "minor", "unblock": "the grain is one row a day"}))
            page.wait_for_selector('.tile[data-repo="beta"] .transcript > li.friction', timeout=15000)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('li.friction') && m.state === 'drawn').length === 3")
            marks = _marks(page)
            assert _of(marks, B, "li.friction", "red", "ellipse")
            assert _of(marks, B, "li.friction > .k", "highlighter", "lines")
            assert _of(marks, B, "li.friction > .v", "pencil", "write")

            # Renewed: the note is erased -- unwritten -- and the arrow and the outline with it.
            stale.clear()
            page.evaluate("() => refresh()")
            page.wait_for_selector('.tile[data-repo="beta"] .oldsession[hidden]', state="attached", timeout=15000)
            _rest(page, "!Ink.inspect().layer.marks.some(m => m.selector.includes('oldsession'))")

            # The header's count, handwritten, then changed: the old number struck beside the new.
            _rest(page, "Ink.inspect().layer.marks.some(m => m.selector === '#bellcount' && m.drawn === 1)")
            page.evaluate("() => { unread.set('alpha', 3); bell(); }")
            _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'ghost' && m.state === 'struck')"
                        " && Ink.inspect().layer.marks.some(m => m.selector === '#bellcount' && m.shape === 'write' && m.drawn === 1)")
            marks = _marks(page)
            ghosts = [m for m in marks if m["shape"] == "ghost"]
            assert [g["was"] for g in ghosts] == ["0"], ghosts
            assert _struck(marks, {ghosts[0]["id"]}) == {ghosts[0]["id"]}
            count = page.evaluate("() => document.getElementById('bellcount').getBoundingClientRect().left")
            assert ghosts[0]["box"]["x"] == pytest.approx(count, abs=0.5), "the ghost is beside the count"
            assert page.evaluate("() => document.getElementById('bellcount').style.clipPath") == ""
            # Once more: one struck number is kept, the newest.
            page.evaluate("() => { unread.set('alpha', 5); bell(); }")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.shape === 'ghost').length === 1"
                        " && Ink.inspect().layer.marks.some(m => m.shape === 'ghost' && m.was === '3' && m.state === 'struck')")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_reduced_motion_draws_the_notebook_at_once(fleet_home, tmp_path, alive):
    """With `prefers-reduced-motion: reduce` a state's marks are on the paper in the frame after the
    class, with no travelling pen, and leave the same way."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
            _notebook(page)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
            alive.add("alpha")
            _emit(page, "alpha", ("turn_started", {}))
            _until_class(page, "alpha", "state-running")
            took = page.evaluate("""() => new Promise(done => {
              let n = 0;
              const step = () => { n += 1; const l = Ink.inspect().layer;
                const run = l.marks.find(m => m.selector.includes('state-running'));
                const idle = l.marks.some(m => m.lane === 'pane:alpha' && m.selector.includes('state-idle'));
                if (run && run.drawn === 1 && !idle) return done({ n, hands: l.hands });
                if (n > 30) return done({ n, hands: l.hands });
                requestAnimationFrame(step); };
              requestAnimationFrame(step); })""")
            assert took["n"] <= 3 and took["hands"] is False, took
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_night_notebook_screens_its_highlighter_onto_charcoal(fleet_home, tmp_path):
    """#250: `notebook:dark` is the same table on charcoal stock with gel inks. The layer reads the
    stock's luminance from `--paper`, so the highlighter screens rather than multiplies, and every
    ink is the variant's -- read from the page, never from the module."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home, skin="notebook:dark")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on")
            _notebook(page, "dark")
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
            layer = _layer(page)
            assert layer["dark"] and layer["mode"] == 2, "charcoal stock: the highlighter screens"
            assert layer["skin"]["paper"] == 1 and layer["skin"]["errors"] == []
            seen = page.evaluate("""() => { const cs = getComputedStyle(document.body);
              return { paper: cs.getPropertyValue('--paper').trim(), pen: cs.getPropertyValue('--ink-pen').trim(),
                       bg: cs.backgroundColor }; }""")
            spec = skins.SKINS["notebook"]["variants"]["dark"]
            assert seen["paper"].upper() == spec["composited_panel"] and seen["pen"].upper() == spec["inks"]["pen"]
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_without_ink_the_notebook_is_the_same_table_drawn_plain_on_a_ruled_page(fleet_home, tmp_path, alive):
    """The gate off (nothing measured, as in CI without the override): `body.ink-off`, no canvas and
    no three.js, the rules as a printed background and the marks as the layer's plain CSS -- the
    same table: an idle pane outlined, a running name underlined, needing you tinted."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, asked = _open(browser, port, token, "")
            page.wait_for_function("() => Ink.inspect().table === 'notebook:light' && Ink.inspect().plain", timeout=15000)
            alive.add("alpha")
            _emit(page, "alpha", ("turn_started", {}))
            _emit(page, "beta", ("question_opened", {"question": "which one?", "id": "q1", "blocking": True,
                                                     "choices": ["this", "that"]}))
            _until_class(page, "alpha", "state-running")
            _until_class(page, "beta", "needs-human")
            page.wait_for_selector('.tile[data-repo="beta"] .ask:not([hidden]) .ask-choice', timeout=15000)
            look = page.evaluate("""() => {
              const cs = el => getComputedStyle(el);
              const a = document.querySelector('.tile[data-repo="alpha"]'), b = document.querySelector('.tile[data-repo="beta"]');
              return { off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink'),
                       rules: cs(document.body).backgroundImage, margin: getComputedStyle(b, '::before').backgroundColor,
                       running: cs(a.querySelector('.head .repo')).textDecorationLine,
                       needs: cs(b.querySelector('.head .repo')).backgroundColor,
                       question: cs(b.querySelector('.ask:not([hidden]) .ask-q')).backgroundColor,
                       loop: cs(b.querySelector('.ask:not([hidden]) .ask-choice')).outlineStyle }; }""")
            assert look["off"] and not look["canvas"], look
            assert "repeating-linear-gradient" in look["rules"], look
            assert look["margin"] not in ("", "rgba(0, 0, 0, 0)"), look
            assert look["running"] == "underline", look
            assert look["needs"] not in ("", "rgba(0, 0, 0, 0)") and look["question"] == look["needs"], look
            assert look["loop"] == "solid", look
            assert not [u for u in asked if "three.module" in u or "/ink/layer.js" in u], "no layer without ink"
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_an_idle_notebook_writes_nothing_draws_nothing_and_settles_in_bounded_frames(fleet_home, tmp_path):
    """The render contract with the notebook on the paper: its marks are on the paper within the
    frames a hand at the pen's speed needs for their length, plus travel -- counted in frames, not
    milliseconds (plan-ink ground rule 5) -- and then an idle desk is zero DOM mutations and zero
    WebGL frames."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, "&ink=on", count=True)
            _notebook(page)
            _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
            layer = _layer(page)
            ink = sum(m["len"] for m in layer["marks"] if m["lane"] != "header")
            lanes = max(1, len([k for k in layer["lanes"] if k != "header"]))
            # Two panes draw at once, so the slower lane is at most all of it; each stroke's travel
            # is under half a second of frames. Generous, and still a number.
            strokes = sum(m["strokes"] for m in layer["marks"])
            bound = ink / PEN * 60 * 1.6 / lanes * 2 + strokes * 30 + 60
            assert layer["frames"] <= bound, (layer["frames"], bound)
            count = page.evaluate(IDLE_LOOP)
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"an idle notebook wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle notebook was redrawn {count['renders']} times"
