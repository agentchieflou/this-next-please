"""The playbook (#389, epic #294): a coach's chalkboard on `nfl-browns`, the state grammar in X's and O's.

The skin is a module (`static/ink/skins/playbook.js`) whose mark table is the notebook's grammar in
football notation, and a stylesheet (`static/skins/playbook/skin.css`) that holds the board's
colours as custom properties. What is asserted:

* `skins.py` offers it, and it is the look drawn on `nfl-browns`, which is no longer palette-only;
* the stylesheet sets the numbers `skins.py` declares, and every word it colours with an ink keeps
  4.5:1 at both ends of the board; the route (the pen) and the error (the marker) are 30 degrees
  apart in hue, so an error never reads as a route;
* the module carries no colour, no markup, no static import, and fits `SKIN_BUDGET`;
* nothing the skin says or draws names a team or a league (#318's names decision);
* in a browser (`?ink=on`, the skin set in `cfg.json` before the page opens): each state's row is
  drawn when its class comes and leaves by erase or strike; the O hugs the pane's number and
  misses its name; answering strikes the question, never the name; reduced motion draws at once
  with no hand; `?ink=off` is the same table plain, with no canvas and no three.js; and an idle
  playbook writes nothing and draws nothing.
"""
from __future__ import annotations
import gzip
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import events as E, serve as S, skins, supervisor

from desk_waits import assert_idle
from test_fleet_ink import (  # noqa: F401 - fixtures are used by name
    RING, SKIN_BUDGET, _hugs, _layer, _marks, _open, _repos, _rest, _serve, _stop, fleet_home)
from desk_harness import close_pages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "playbook.js")
CSS = os.path.join(STATIC, "skins", "playbook", "skin.css")

#: The tools a variant declares an ink for, and the custom property the stylesheet sets each in.
TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")

#: Words the skin's own strings and art never carry (#318: the palette keeps its shipped name; the
#: skin names no team or league and draws no logo).
TRADEMARKS = ("nfl", "browns", "cleveland", "logo", "helmet", "dawg")


# ============================================================================== without a browser


def _css_block(css: str, variant: str) -> dict:
    """The custom properties the stylesheet sets for a variant: the skin's block, then the
    variant's own over it."""
    out = {}
    for pattern in (r'body\[data-skin="playbook"\]\s*\{(.*?)\}',
                    r'body\[data-skin="playbook"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % variant):
        m = re.search(pattern, css, re.S)
        if m:
            out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1))))
    return out


def test_the_playbook_is_a_skin_the_settings_page_offers():
    assert skins.split("playbook") == ("playbook", "chalkboard")
    assert "playbook" in S.ink_skins()
    offered = {s["name"]: s for s in skins.list_skins()}
    assert "playbook" in offered and offered["playbook"]["variants"][0]["name"] == "chalkboard"
    assert skins.get_skin("playbook")["base"] == "nfl-browns"
    assert "nfl-browns" not in skins.PALETTE_ONLY


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The board's two ends and every ink, declared once in skins.py (where `theme.check` reads
    them) and named by skin.css (where the page and the module read them)."""
    css = open(CSS, encoding="utf-8").read()
    for variant, spec in skins.SKINS["playbook"]["variants"].items():
        props = _css_block(css, variant)
        panel = spec["composited_panel"]
        assert props["paper"].upper() == panel["darkest"].upper(), variant
        assert props["board-max"].upper() == panel["lightest"].upper(), variant
        assert "yard" in props, variant
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), (variant, tool)
        for token in ("text", "muted", "bg", "panel"):
            assert token not in props, (variant, "the palette's own token, recoloured", token)


def test_every_word_written_in_an_ink_reads_at_both_ends_of_every_variant():
    """A `color: var(--ink-<tool>)` is text in that ink: 4.5:1 at the board's darkest and lightest
    end, for every variant. The pen (3.56:1 at the light end) and the red never colour a word."""
    css = open(CSS, encoding="utf-8").read()
    coloured = set(re.findall(r"(?<![\w-])color:\s*var\(--ink-(\w+)\)", css))
    assert coloured, "the finding's words and the count are written in an ink"
    assert not coloured & {"pen", "red"}, coloured
    for variant, spec in skins.SKINS["playbook"]["variants"].items():
        for tool in coloured:
            for end in skins.composited_panels(spec):
                ratio = theme.contrast_ratio(spec["inks"][tool], end)
                assert ratio >= 4.5, (variant, tool, end, round(ratio, 2))


def test_theme_check_holds_every_variant_and_an_error_never_reads_as_a_route():
    for variant, spec in skins.SKINS["playbook"]["variants"].items():
        base = theme.get(spec["base"])
        for end in skins.composited_panels(spec):
            theme.check(base, composited_panel=end, skin=f"playbook:{variant}", inks=spec["inks"],
                        dark=theme.is_dark(_css_block(open(CSS, encoding="utf-8").read(), variant)["paper"]))
            assert theme.contrast_ratio(theme.to_css(base)["--muted"], end) >= 4.5, (variant, end)
        assert theme.hue_distance(spec["inks"]["pen"], spec["inks"]["marker"]) >= 30, variant


def test_the_module_carries_no_colour_no_markup_and_fits_its_budget():
    body = open(MODULE, encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", body, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), "a hex colour in the playbook module"
    assert not re.search(r"^\s*import\s", code, re.M), "a static import"
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "classList"):
        assert banned not in code, banned
    size = len(gzip.compress(open(MODULE, "rb").read(), 6, mtime=0))
    assert size < SKIN_BUDGET, size


def test_nothing_the_skin_says_or_draws_names_a_team_or_a_league():
    """Comments included: the module, the stylesheet, the skin's title and why and each variant's."""
    pb = skins.SKINS["playbook"]
    said = [open(MODULE, encoding="utf-8").read(), open(CSS, encoding="utf-8").read(), pb["title"], pb["why"]]
    for spec in pb["variants"].values():
        said += [spec["title"], spec["why"]]
    for text in said:
        for word in TRADEMARKS:
            assert word not in text.lower(), (word, text[:80])


# ================================================================================ in a browser


def _desk(tmp_path, fleet_home, names=("alpha", "beta"), skin="playbook"):
    _repos(tmp_path, names)
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")


@pytest.fixture()
def alive(monkeypatch):
    """The agents a process is holding: running is shown only for a supervised agent (#147)."""
    names: set = set()
    real = supervisor.live
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 777, "repo": name} if name in names else real(name))
    return names


def _emit(page, repo, *events):
    """Something happens to an agent: its events are written where the fold reads them, and the
    page is asked to look. The classes come from the server's fold, never from the test."""
    E.append(repo, [E.event(repo, kind, data, ticket="RDSD-1") for kind, data in events])
    page.evaluate("() => refresh()")


def _until(page, selector, present=True):
    page.wait_for_function(
        "([s, want]) => { if (!!document.querySelector(s) === want) return true; refresh(); return false; }",
        arg=[selector, present], timeout=15000, polling=250)


def _until_class(page, repo, cls, on=True):
    _until(page, f'.tile[data-repo="{repo}"].{cls}', on)


def _playbook(page, variant="chalkboard"):
    page.wait_for_function(f"() => Ink.inspect().table === 'playbook:{variant}'", timeout=15000)


def _of(marks, lane, sel_part, tool=None, shape=None, ink=None):
    """The live marks in one pane whose row's selector contains `sel_part`."""
    return [m for m in marks if m["lane"] == lane and sel_part in m["selector"]
            and (tool is None or m["tool"] == tool) and (shape is None or m["shape"] == shape)
            and (ink is None or m.get("ink") == ink)
            and m["state"] == "drawn" and not m["strikeOf"] and m["visible"]]


def _gone(marks, lane, sel_part):
    """True when no mark of the row is left in the pane but a strike: erased marks are dropped,
    struck ones stay as `struck` under their strike."""
    return all(m["state"] == "struck" or m["strikeOf"]
               for m in marks if m["lane"] == lane and sel_part in m["selector"])


@pytest.mark.browser
def test_the_playbook_draws_its_grammar_and_each_mark_leaves_by_erase_or_strike(fleet_home, tmp_path, alive,
                                                                                desk_browser):
    """An open pane's O and line of scrimmage; the huddle (idle), the route (running), the option
    route (waiting_approval, dashed), stopped at the line (blocked: a red route with a bar, and an X),
    the fumble (error) and the touchdown (done), each drawn when the fold puts the class on the pane
    and gone by erase or strike when it goes. Under reduced motion, in the frame after the class,
    with no hand."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(desk_browser, port, token, "&ink=on", reduced=True)
        _playbook(page)
        A, B = "pane:alpha", "pane:beta"
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4"
                    " && Ink.inspect().layer.marks.filter(m => m.shape === 'ring').length === 2")
        marks = _marks(page)
        for lane in (A, B):
            assert _of(marks, lane, ".tile.state-idle", "pencil", "outline")
            assert _of(marks, lane, "state-idle .head .repo", "pencil", "underline")
            assert _of(marks, lane, ".head .n", "pencil", "ring")
            assert _of(marks, lane, ":not([data-tier='rail']) .head", "pencil", "divider")
        _hugs(page.evaluate(RING))
        layer = _layer(page)
        assert layer["dark"] and layer["mode"] == 2, "a dark board: the highlighter screens"
        assert layer["handModel"] in ("", "chalk") and layer["hands"] is False, "reduced motion: no hand"

        # blocked: a friction that stops it. The huddle is erased; a red route ending in a bar and
        # an X in the margin come -- in the frame after the class, with no hand.
        _emit(page, "alpha", ("friction", {"severity": "blocker", "unblock": "the grain is one row a day"}))
        _until_class(page, "alpha", "state-blocked")
        counted = page.evaluate("""() => new Promise(done => {
          let n = 0;
          const step = () => { n += 1; const l = Ink.inspect().layer;
            const stop = l.marks.find(m => m.selector.includes('state-blocked .head') && m.state === 'drawn');
            const idle = l.marks.some(m => m.lane === 'pane:alpha' && m.selector.includes('state-idle'));
            if (stop && stop.drawn === 1 && !idle) return done({ n, hands: l.hands });
            if (n > 30) return done({ n, hands: l.hands });
            requestAnimationFrame(step); };
          requestAnimationFrame(step); })""")
        assert counted["n"] <= 3 and counted["hands"] is False, counted
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-blocked') && m.state === 'drawn').length === 2")
        marks = _marks(page)
        stop = _of(marks, A, "state-blocked .head .repo", "pencil", "underline", ink="red")
        assert len(stop) == 1 and stop[0]["cap"] == "bar", stop
        assert _of(marks, A, ".tile.state-blocked", "red", "cross")

        # running (a turn outranks the friction): stopped-at-the-line goes, the route comes.
        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _until_class(page, "alpha", "state-running")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-running') && m.state === 'drawn')")
        marks = _marks(page)
        assert _gone(marks, A, "state-blocked"), "the red route and the X are taken up"
        run = _of(marks, A, "state-running", "pencil", "underline", ink="pen")
        assert len(run) == 1 and run[0]["cap"] == "arrow", run

        # waiting_approval (an approval outranks the friction): the route goes, the option route,
        # dashed, comes.
        alive.discard("alpha")
        _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("needs_approval", {"summary": "transition RDSD-1"}))
        _until_class(page, "alpha", "state-waiting_approval")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('state-waiting_approval') && m.state === 'drawn')")
        marks = _marks(page)
        assert _gone(marks, A, "state-running"), "the route is taken up"
        option = _of(marks, A, "state-waiting_approval", "pencil", "underline", ink="pen")
        assert len(option) == 1 and option[0]["cap"] == "arrow", option

        # done on beta: the touchdown's check. Unsupervised, its chip still says idle (#147).
        _emit(page, "beta", ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "beta", "is-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:beta' && m.state === 'drawn')")
        marks = _marks(page)
        assert _of(marks, B, "is-done", "green", "check")

        # error outranks done: the fumble's loop round the why and its bang, and the check gone.
        _emit(page, "beta", ("error", {"exit_code": 2}))
        _until_class(page, "beta", "state-error")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.lane === 'pane:beta' && m.selector.includes('state-error') && m.state === 'drawn').length === 2")
        marks = _marks(page)
        assert _of(marks, B, "state-error .why", "marker", "loop")
        assert _of(marks, B, ".tile.state-error", "marker", "bang")
        assert _gone(marks, B, "is-done"), "the check is taken up"
        assert not errors, errors
        close_pages(desk_browser)
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
def test_the_flag_then_the_call_strikes_the_question_never_the_name(fleet_home, tmp_path, desk_browser):
    """needs you (the flag): the name and the question highlighted, loops round the choices, the
    card looped in marker. Answered (the call): the question struck in the pen's orange chalk, the
    chosen answer circled, the loops erased -- and nothing ever struck on the agent's name."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        page, errors, _ = _open(desk_browser, port, token, "&ink=on", reduced=True)
        page.route("**/api/answer*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body='{"ok": true, "action": "answer", "repo": "alpha", "pid": 1, "answered": ["q1"]}'))
        _playbook(page)
        A = "pane:alpha"
        _emit(page, "alpha", ("question_opened", {"question": "which window should this land in?",
                                                  "id": "q1", "blocking": True, "choices": ["left", "right"]}))
        _until_class(page, "alpha", "needs-human")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('needs-human')"
                    " && m.state === 'drawn' && m.visible).length === 5")
        marks = _marks(page)
        name = _of(marks, A, "needs-human .head .repo", "highlighter", "lines")
        question = _of(marks, A, ".ask-q", "highlighter", "lines")
        assert len(name) == 1 and len(question) == 1, marks
        assert len(_of(marks, A, ".ask-choice", "pencil", "loop")) == 2
        assert _of(marks, A, "needs-human .asks:not([hidden])", "marker", "loop")

        assert page.evaluate(ANSWER, ["alpha"])
        _rest(page, "Ink.inspect().layer.marks.some(m => m.selector.includes('is-answered .ask-q') && m.state === 'drawn')"
                    " && Ink.inspect().layer.marks.some(m => m.selector.includes('aria-pressed') && m.state === 'drawn')")
        marks = _marks(page)
        assert _of(marks, A, "is-answered .ask-q", "pencil", "strike", ink="pen"), "the question is struck"
        assert len(_of(marks, A, "aria-pressed", "pencil", "ellipse", ink="pen")) == 1, "the call is circled"
        assert not [m for m in marks if m["lane"] == A and ".ask-choice" in m["selector"]
                    and m["shape"] == "loop"], "the loops are erased"
        assert _of(marks, A, "needs-human .head .repo", "highlighter", "lines"), "the name keeps its flag"
        assert not [m for m in marks if m["strikeOf"] == name[0]["id"]], "the agent's name is never struck"
        _emit(page, "alpha", ("question_answered", {"id": "q1", "question": "which window should this land in?"}))
        _until_class(page, "alpha", "needs-human", False)
        _rest(page, "!Ink.inspect().layer.marks.some(m => m.selector.includes('needs-human .head .repo'))")
        assert not [m for m in _marks(page) if m["strikeOf"] == name[0]["id"]], "taken up, not struck"
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_without_ink_the_playbook_is_plain_and_an_idle_board_is_still(fleet_home, tmp_path, alive, desk_browser):
    """`?ink=off` (the gate off, as in CI without the override): `body.ink-off`, no canvas, no
    three.js, and the same table as plain CSS -- the running name underlined solid, the option
    route's dashed. Then, ink on: an idle board makes zero DOM mutations and zero WebGL frames."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        page, errors, asked = _open(desk_browser, port, token, "")
        page.wait_for_function("() => Ink.inspect().table === 'playbook:chalkboard' && Ink.inspect().plain",
                               timeout=15000)
        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _emit(page, "beta", ("needs_approval", {"summary": "transition RDSD-1"}))
        _until_class(page, "alpha", "state-running")
        _until_class(page, "beta", "state-waiting_approval")
        look = page.evaluate("""() => {
          const cs = el => getComputedStyle(el);
          const a = document.querySelector('.tile[data-repo="alpha"] .head .repo');
          const b = document.querySelector('.tile[data-repo="beta"] .head .repo');
          return { off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink'),
                   running: [cs(a).textDecorationLine, cs(a).textDecorationStyle],
                   option: [cs(b).textDecorationLine, cs(b).textDecorationStyle] }; }""")
        assert look["off"] and not look["canvas"], look
        assert look["running"] == ["underline", "solid"], look
        assert look["option"] == ["underline", "dashed"], look
        assert not [u for u in asked if "three.module" in u or "/ink/layer.js" in u], "no layer without ink"
        assert not errors, errors
        close_pages(desk_browser)

        alive.discard("alpha")
        E.append("alpha", [E.event("alpha", "turn_ended", {"turn": "1"}, ticket="RDSD-1")])
        page, errors, _ = _open(desk_browser, port, token, "&ink=on", width=1000, height=620)
        _playbook(page)
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.shape === 'ring').length === 2")
        assert_idle(page)
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        _stop(server)
