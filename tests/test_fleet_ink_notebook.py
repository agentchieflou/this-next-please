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
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import agentstate, events as E, serve as S, skins, supervisor

# The ink layer's own fixtures and helpers: the fleet directory, the desk's globals (autouse), the
# desk and the page, and what the layer shows of itself.
from desk_waits import observe_quiet
from test_fleet_ink import (  # noqa: F401 - fixtures are used by name
    AT_REST, COUNT_FETCHES, PEN, _choose, _layer, _marks, _open, _repos, _rest, _serve,
    _stop, fleet_home)
from desk_harness import close_pages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
MODULE = os.path.join(STATIC, "ink", "skins", "notebook.js")
CSS = os.path.join(STATIC, "skins", "notebook", "skin.css")

#: The tools a variant declares an ink for, and the custom property the stylesheet sets each in.
TOOLS = ("pencil", "pen", "red", "green", "marker", "highlighter")

#: The window the two tests that watch the pen travel are drawn in. The Windows leg runs the suite
#: serially under a 20-minute cap, and CI draws in software: an outline round a pane is its
#: perimeter at the pen's speed, so a smaller pane is a shorter wait for the same assertions. The
#: tests that assert what is drawn rather than how run under reduced motion, which draws at once.
DRAWN = {"width": 1000, "height": 620}

#: #398: the lamp's centre, as fractions of the viewport across and down (`notebook.js` `PAPER_FS`).
LAMP_AT = (0.3, 0.2)

#: #398: the light and the dark paper read back from the canvas (`READ`) at the lamp's centre at
#: `DRAWN` -- x=300, at the point between two rules nearest y=124 that no mark covers, which is
#: y=124 -- recorded on main @ dca5b20, before the lamp. A variant without a lamp reads the same
#: (plus or minus 1 per channel).
PAPER_BEFORE_THE_LAMP = {"light": (254, 254, 248), "dark": (27, 30, 37)}


# ============================================================================== without a browser


def _css_block(css: str, variant: str) -> dict:
    """The custom properties the stylesheet sets for a variant: the base block, and the variant's
    own over it -- every variant but the default has one (#398: any variant, not only dark)."""
    blocks = [r'body\[data-skin="notebook"\]\s*\{(.*?)\}']
    if variant != skins.SKINS["notebook"]["default"]:
        blocks.append(r'body\[data-skin="notebook"\]\[data-skin-variant="%s"\]\s*\{(.*?)\}' % re.escape(variant))
    out = {}
    for pattern in blocks:
        body = re.search(pattern, css, re.S).group(1)
        out.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", body)))
    return out


def test_the_notebook_is_a_skin_with_a_light_and_a_dark_variant():
    """Chosen through skins.py like every skin, so the settings page offers it. Dark is a variant,
    not a family: skins drive palettes, and the night page's ground is named by its variant. So is
    Lamplight (#398), the night-study page on `eye-relief`: a flavour on the dark side."""
    nb = skins.SKINS["notebook"]
    assert nb["default"] == "light" and set(nb["variants"]) == {"light", "dark", "lamplight"}
    assert skins.split("notebook") == ("notebook", "light")
    assert skins.get_skin("notebook:dark")["base"] == "dark"
    assert skins.get_skin("notebook:lamplight")["base"] == "eye-relief"
    assert theme.get(nb["variants"]["dark"]["base"]).ground and \
        theme.rel_luminance(theme.hex_to_rgb(nb["variants"]["dark"]["composited_panel"])) < 0.05
    assert "notebook" in [s["name"] for s in skins.list_skins()]
    assert "notebook" in S.ink_skins()


def test_the_stylesheet_paints_the_numbers_skins_py_declares():
    """The paper and every ink: declared once in skins.py (where `theme.check` reads them) and named
    by skin.css (where the page and the module read them), held to one number by this test rather
    than by somebody updating both. The words are the palette's own text and muted colour: since
    #257 a skin never recolours the palette, so skin.css sets neither. A lamp (#398) brightens the
    stock up to `--lamp-max`, so a variant with one is a pair: `--paper` at its darker end and
    `--lamp-max` at its lighter; without one the paper is the panel."""
    css = open(CSS, encoding="utf-8").read()
    for variant, spec in skins.SKINS["notebook"]["variants"].items():
        props = _css_block(css, variant)
        darkest, lightest = skins.composited_panels(spec)[0], skins.composited_panels(spec)[-1]
        assert props["paper"].upper() == darkest.upper(), variant
        if "lamp" in props:
            assert props["lamp-max"].upper() == lightest.upper(), variant
        else:
            assert darkest == lightest, (variant, "a pair with no lamp to light its lighter end")
        assert "text" not in props and "muted" not in props, (variant, "the palette's own words, recoloured")
        for tool in TOOLS:
            assert props[f"ink-{tool}"].upper() == spec["inks"][tool].upper(), (variant, tool)
        assert "rule" in props and "margin" in props, variant


def test_theme_check_holds_every_ink_on_the_notebooks_paper():
    """Rule 5 of `theme.check` with the pairs the notebook brings: each ink 3:1 on its paper, the
    text 4.5:1 through the highlighter -- for the palette the variant names, whose own text and
    muted words are what is written on the paper (#257: the skin no longer recolours them)."""
    for variant, spec in skins.SKINS["notebook"]["variants"].items():
        base = theme.get(spec["base"])
        for paper in skins.composited_panels(spec):
            theme.check(base, composited_panel=paper, skin=f"notebook:{variant}", inks=spec["inks"])
            assert theme.contrast_ratio(theme.to_css(base)["--muted"], paper) >= 4.5, (variant, paper)


def test_every_word_written_in_an_ink_reads_at_every_end_of_every_variants_paper():
    """#398. A `color: var(--ink-<tool>)` in skin.css is a word in that ink -- a finding's margin
    note in the red, the header's count in the pen, the stale note in pencil -- so it holds 4.5:1,
    not a mark's 3:1, at every end of every variant's paper. Lamplight's first red, #E07A6E, read
    4.23:1 at its lit end."""
    css = open(CSS, encoding="utf-8").read()
    coloured = set(re.findall(r"(?<![\w-])color:\s*var\(--ink-(\w+)\)", css))
    assert {"red", "pen"} <= coloured, ("the finding's note and the count are written in an ink", coloured)
    for variant, spec in skins.SKINS["notebook"]["variants"].items():
        for tool in sorted(coloured):
            for end in skins.composited_panels(spec):
                ratio = theme.contrast_ratio(spec["inks"][tool], end)
                assert ratio >= 4.5, (variant, tool, end, round(ratio, 2))


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


def _until(page, selector, present=True):
    """Until the page shows `selector` (or stops showing it), asking it to look again while it
    waits. One `refresh()` is not enough: a refresh already in flight when the events were written
    answers it with the fold from before them, and nothing asks again until the next poll."""
    page.wait_for_function(
        "([s, want]) => { if (!!document.querySelector(s) === want) return true; refresh(); return false; }",
        arg=[selector, present], timeout=15000, polling=250)


def _until_class(page, repo, cls, on=True):
    _until(page, f'.tile[data-repo="{repo}"].{cls}', on)


def _notebook(page, variant="light"):
    page.wait_for_function(f"() => Ink.inspect().table === 'notebook:{variant}'", timeout=15000)


#: The skin variants that lay the highlighter on the needs-you name: every one (#329; voxel's
#: worlds since #334's state grammar gave them a highlighter).
HIGHLIGHTED = tuple(f"{s}:{v}" for s, v, _ in skins.every_variant())

#: Every word made invisible, so a screenshot is what the text is read on and nothing else.
NO_TEXT = ("* { color: transparent !important; -webkit-text-fill-color: transparent !important;"
           " text-shadow: none !important; caret-color: transparent !important; }")

#: The needs-you name and its open question in pane `repo`: each one's computed colour and the rect
#: of its text (a Range over its contents, not the element's box). `null` for one the page does not
#: show at that moment (a refresh re-draws the question card), so a wait on it waits rather than throws.
READ_TARGETS = """(repo) => {
  const t = document.querySelector(`.tile[data-repo="${repo}"]`);
  return [t.querySelector('.head .repo'), t.querySelector('.asks:not([hidden]) .ask:not([hidden]) .ask-q')].map(el => {
    if (!el) return null;
    const r = document.createRange(); r.selectNodeContents(el); const b = r.getBoundingClientRect();
    return { colour: getComputedStyle(el).color, x: b.x, y: b.y, w: b.width, h: b.height }; }); }"""


def _rgb_hex(css):
    r, g, b = (int(float(c)) for c in re.findall(r"[\d.]+", css)[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


#: The variant `v` is the page's whole look: its table, its skin and variant on <body>, its
#: stylesheet loaded, and its palette's `--text` on the root. A snapshot answered from before the
#: choice can put the old palette back for a moment, so this is asked again after the screenshot.
CHOSEN = """([v, text]) => { const [s, variant] = v.split(':'), l = document.querySelector('link[data-skin]');
  return Ink.inspect().table === v && document.body.dataset.skin === s && document.body.dataset.skinVariant === variant
    && !!l && !!l.sheet && l.href.includes('/static/skins/' + s + '/skin.css')
    && getComputedStyle(document.documentElement).getPropertyValue('--text').trim().toUpperCase() === text; }"""


def _read_through_the_highlighter(page, repo, full, plain=False):
    """#329: the needs-you name and the question in `repo`, in the variant `full` just chosen, read
    against the pixels actually under them. Every word is made transparent, the paper is let come to
    rest, and the text's rect is screenshotted: the median and the lowest quartile of the words'
    colour against those pixels both keep 4.5:1. Returns what was read, for the failure message."""
    from test_fleet_desk_glass import _png_pixels     # here: that module imports the glass tests
    skin_name, variant = full.split(":")
    chosen = [full, theme.to_css(theme.get(skins.SKINS[skin_name]["variants"][variant]["base"]))["--text"].upper()]
    settled = "() => Ink.inspect().plain" if plain else AT_REST
    if not plain:
        # The layer draws with the inks it last read off the page: it has to have read this
        # variant's, whenever its stylesheet arrived (#329's flake: a sheet later than its module).
        ink = skins.SKINS[skin_name]["variants"][variant]["inks"]["highlighter"].upper()
        took = f"() => {{ const l = Ink.inspect().layer; return !!l && l.inks.highlighter === '{ink}'; }}"
        try:
            page.wait_for_function(took, timeout=15000)
        except Exception:
            raise AssertionError((full, "the layer never took the variant's highlighter", ink,
                                  (_layer(page) or {}).get("inks"))) from None
        settled = f"() => ({AT_REST})() && ({took})()"
    for _ in range(5):
        # The question is written in the palette's `--text`: once it is, the page has its palette.
        page.wait_for_function(f"([c, repo, rgb]) => ({CHOSEN})(c) && ({settled})()"
                               f" && !!({READ_TARGETS})(repo)[1] && ({READ_TARGETS})(repo)[1].colour === rgb",
                               arg=[chosen, repo, "rgb(%d, %d, %d)" % tuple(round(v * 255) for v in theme.hex_to_rgb(chosen[1]))],
                               timeout=30000)
        targets = page.evaluate(READ_TARGETS, repo)
        if not all(targets):
            continue
        page.evaluate("css => { const s = document.createElement('style'); s.id = 'no-text'; s.textContent = css;"
                      " document.head.appendChild(s); }", NO_TEXT)
        page.wait_for_function(f"() => ({settled})()", timeout=30000)
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        shots = [page.screenshot(clip={"x": tg["x"], "y": tg["y"], "width": tg["w"], "height": tg["h"]})
                 for tg in targets]
        page.evaluate("() => document.getElementById('no-text').remove()")
        try:
            page.wait_for_function(f"([c, repo, was]) => ({CHOSEN})(c) && ({READ_TARGETS})(repo).map(t => t && t.colour).join() === was",
                                   arg=[chosen, repo, ",".join(t["colour"] for t in targets)], timeout=5000)
            break
        except Exception:
            continue
    else:
        raise AssertionError((full, "the page never held the variant still long enough to read it"))
    out = []
    for name, tg, shot in zip(("name", "question"), targets, shots):
        assert tg["w"] >= 4 and tg["h"] >= 4, (full, name, tg)
        w, h, bpp, rows = _png_pixels(shot)
        words = _rgb_hex(tg["colour"])
        ratios = sorted(theme.contrast_ratio(words, "#%02X%02X%02X" % tuple(row[x * bpp:x * bpp + 3]))
                        for row in rows for x in range(w))
        med, p25 = ratios[len(ratios) // 2], ratios[len(ratios) // 4]
        out.append((full, "plain" if plain else "ink", name, words, round(med, 2), round(p25, 2)))
    bad = [o for o in out if o[4] < 4.5 or o[5] < 4.5]
    assert not bad, ("under 4.5:1 through the highlighter (median, p25)", bad)
    return out


def _each_variant_reads_through_its_highlighter(page, repo, variants, plain=False):
    """`_choose` each of `variants` in turn and read the name and the question through its
    highlighter (`_read_through_the_highlighter`), once the variant is the page's whole look."""
    read = []
    for full in variants:
        _choose(page, full)
        read += _read_through_the_highlighter(page, repo, full, plain=plain)
    return read


def _of(marks, lane, sel_part, tool=None, shape=None, live=True):
    """The marks in one pane whose row's selector contains `sel_part`."""
    out = [m for m in marks if m["lane"] == lane and sel_part in m["selector"]
           and (tool is None or m["tool"] == tool) and (shape is None or m["shape"] == shape)]
    if live:
        out = [m for m in out if m["state"] == "drawn" and not m["strikeOf"] and m["visible"]]
    return out


def _struck(marks, target_ids):
    return {m["strikeOf"] for m in marks if m["strikeOf"] in target_ids and m["state"] == "drawn"}


def _rgb(hex_colour):
    """`#RRGGBB` as a tuple of 0-255 channels, as the canvas is read back."""
    return tuple(round(v * 255) for v in theme.hex_to_rgb(hex_colour))


def _between_the_rules(marks, x, y):
    """#398: the y nearest `y`, at `x`, that is between two of the page's rules -- its y mod 28 from
    8 to 20; the shader's rule is at 27 -- and that no mark's bounds (`marks[].bounds`, 4px out for
    the stroke's width) cover."""
    def covered(at):
        return any(b["x"] - 4 <= x <= b["r"] + 4 and b["y"] - 4 <= at <= b["b"] + 4
                   for m in marks for b in m["bounds"])
    for at in sorted(range(0, 2 * y + 1), key=lambda v: (abs(v - y), v)):
        if 8 <= at % 28 <= 20 and not covered(at):
            return at
    raise AssertionError(("no paper between the rules and clear of the marks near", x, y))


def _paper_at_the_lamp(page, variant):
    """#398: `notebook:<variant>` the page's whole look (chosen first unless it already is), the
    layer holding its inks, the desk at rest; then the paper read back from the canvas (`READ`) at
    the lamp's centre at `DRAWN`, moved to the nearest point between two rules that no mark covers.
    Returns `(y, (r, g, b))`."""
    from test_fleet_ink_glass import READ   # here: that module imports this one
    spec = skins.SKINS["notebook"]["variants"][variant]
    chosen = [f"notebook:{variant}", theme.to_css(theme.get(spec["base"]))["--text"].upper()]
    if not page.evaluate(f"c => ({CHOSEN})(c)", chosen):
        _choose(page, chosen[0])
    page.wait_for_function(f"([c, pen]) => ({CHOSEN})(c) && !!Ink.inspect().layer && Ink.inspect().layer.inks.pen === pen",
                           arg=[chosen, spec["inks"]["pen"].upper()], timeout=30000)
    _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
    x = round(DRAWN["width"] * LAMP_AT[0])
    y = _between_the_rules(_marks(page), x, round(DRAWN["height"] * LAMP_AT[1]))
    px = page.evaluate(READ, [{"x": x, "y": y, "w": 1, "h": 1, "at": [[0, 0]]}])[0][0]
    return y, tuple(px[:3])


@pytest.mark.browser
def test_the_notebook_draws_the_state_grammar_and_each_mark_leaves_by_erase_or_strike(fleet_home, tmp_path, alive,
                                                                                    finished, desk_browser):
    """idle, running, error and done, each drawn when the fold puts it on the pane: pencil erased
    as the state goes, ink struck through. The running line grows with the turn, and the pen's tip
    sits at its end until the line is struck."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", **DRAWN)
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
        _until(page, '.tile[data-repo="alpha"] .transcript > li:nth-child(3)')
        _rest(page, f"Ink.inspect().layer.marks.some(m => m.selector.includes('state-running')"
                    f" && m.state === 'drawn' && m.len > {before} + 10)")
        grown = _of(_marks(page), A, "state-running", "pen", "underline")[0]
        assert grown["drawn"] == 1 and grown["strokes"] == 2, grown

        # error: the pen line is struck (its tip lifted first), a red marker loop round the why
        # (#335: never round the whole pane) and a bang.
        alive.discard("alpha")
        _emit(page, "alpha", ("turn_ended", {"turn": "1"}), ("error", {"exit_code": 2}))
        _until_class(page, "alpha", "state-error")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-error') && m.state === 'drawn').length === 2")
        marks = _marks(page)
        gone = [m for m in marks if m["lane"] == A and "state-running" in m["selector"] and not m["strikeOf"]]
        assert len(gone) == 1 and gone[0]["state"] == "struck" and gone[0]["strokes"] == 1, \
            "the running line is struck, and its tip lifted"
        assert _struck(marks, {gone[0]["id"]}) == {gone[0]["id"]}
        assert _of(marks, A, "state-error .why", "marker", "loop")
        assert not [m for m in _of(marks, A, "state-error", "marker", "loop") if m["selector"] == ".tile.state-error"]
        assert _of(marks, A, "state-error", "marker", "bang")

        # done: a green check in the margin, on the other pane.
        alive.add("beta")
        finished.add("beta")
        _emit(page, "beta", ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "beta", "state-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:beta' && m.state === 'drawn')")
        marks = _marks(page)
        assert _of(marks, "pane:beta", "is-done", "green", "check")
        assert not [m for m in marks if m["lane"] == "pane:beta" and "state-idle" in m["selector"]]
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


ANSWER = """([repo]) => new Promise(done => {
  const tile = document.querySelector(`.tile[data-repo="${repo}"]`);
  tile.querySelector('.ask-choice').click();
  tile.querySelector('.bottom .send').click();
  const wait = () => tile.querySelector('.ask.is-answered') ? done(true) : requestAnimationFrame(wait);
  wait();
})"""


@pytest.mark.browser
def test_needing_you_is_highlighted_and_answering_strikes_the_question_never_the_name(fleet_home, tmp_path, desk_browser):
    """needs you: the name and the question highlighted, pencil loops round the choices, and the
    question card looped in marker (#335: the loudest pane). Answered:
    the question and its highlight struck through in pen, the chosen answer circled, the loops
    erased -- and nothing struck on the agent's name, the flaw both prototypes had."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
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
                    " && m.state === 'drawn' && m.visible).length === 5")
        marks = _marks(page)
        name = _of(marks, A, "needs-human .head .repo", "highlighter", "lines")
        question = _of(marks, A, ".ask-q", "highlighter", "lines")
        loops = _of(marks, A, ".ask-choice", "pencil", "loop")
        card = _of(marks, A, "needs-human .asks:not([hidden])", "marker", "loop")
        assert len(name) == 1 and len(question) == 1 and len(loops) == 2 and len(card) == 1, marks

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
        # The agent records the answer and stops needing you: the name's highlight is taken up --
        # erased -- not struck through.
        _emit(page, "alpha", ("question_answered", {"id": "q1", "question": "which window should this land in?"}))
        _until_class(page, "alpha", "needs-human", False)
        _rest(page, "!Ink.inspect().layer.marks.some(m => m.selector.includes('needs-human .head .repo'))")
        marks = _marks(page)
        assert not _struck(marks, {name[0]["id"]}) and not [m for m in marks if m["strikeOf"] == name[0]["id"]]
        # Then it finishes, unsupervised: the chip says idle (#147) and the fold says done, which
        # the page writes as `is-done` (#253). The check is drawn in the margin all the same.
        _emit(page, "alpha", ("phase_changed", {"from": "build", "to": "done"}))
        _until_class(page, "alpha", "is-done")
        _rest(page, "Ink.inspect().layer.marks.some(m => m.shape === 'check' && m.lane === 'pane:alpha')")
        assert _of(_marks(page), A, "is-done", "green", "check")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_stale_note_the_finding_and_the_header_count(fleet_home, tmp_path, monkeypatch, desk_browser):
    """stale (#240): the chip's words handwritten in pencil with an arrow to the run line, and a
    dashed pencil outline. A finding -- a friction the agent recorded -- a red ellipse round its
    line, the highlighter on its token, its text written. The header's count: when it changes, the
    old number is struck beside the new one, which is written again."""
    stale = set()
    monkeypatch.setattr(S, "_stale_cell", lambda stream, installed: {
        "stale": any(e.get("repo") in stale for e in stream[:1]), "unknown": False,
        "reason": "began on older skills", "skills_changed": []})
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
        _notebook(page)
        B = "pane:beta"
        stale.add("beta")
        _until(page, '.tile[data-repo="beta"] .oldsession:not([hidden])')
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('oldsession') && m.state === 'drawn').length === 3")
        marks = _marks(page)
        note = _of(marks, B, ".oldsession:not([hidden])", "pencil", "write")
        arrow = _of(marks, B, ".oldsession:not([hidden])", "pencil", "arrow")
        outline = _of(marks, B, ":has(.oldsession", "pencil", "outline")
        assert len(note) == 1 and note[0]["drawn"] == 1 and note[0]["clip"] == "", note
        assert len(arrow) == 1 and arrow[0]["strokes"] == 3 and len(outline) == 1, marks

        _emit(page, "beta", ("friction", {"severity": "minor", "unblock": "the grain is one row a day"}))
        _until(page, '.tile[data-repo="beta"] .transcript > li.friction')
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('li.friction') && m.state === 'drawn').length === 3")
        marks = _marks(page)
        assert _of(marks, B, "li.friction", "red", "ellipse")
        assert _of(marks, B, "li.friction > .k", "highlighter", "lines")
        assert _of(marks, B, "li.friction > .v", "pencil", "write")

        # Renewed: the note is erased -- unwritten -- and the arrow and the outline with it.
        stale.clear()
        _until(page, '.tile[data-repo="beta"] .oldsession[hidden]')
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
        # Beside the count: the ghost is drawn to its left, anchored where the count is. Read at
        # rest -- the bell's own style settles a frame after its text (#249).
        page.wait_for_function("""() => { const g = Ink.inspect().layer.marks.find(m => m.shape === 'ghost');
          return !!g && Math.abs(g.box.x - document.getElementById('bellcount').getBoundingClientRect().left) < 0.5; }""",
                               timeout=10000)
        assert page.evaluate("() => document.getElementById('bellcount').style.clipPath") == ""
        # Once more: one struck number is kept, the newest.
        page.evaluate("() => { unread.set('alpha', 5); bell(); }")
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.shape === 'ghost').length === 1"
                    " && Ink.inspect().layer.marks.some(m => m.shape === 'ghost' && m.was === '3' && m.state === 'struck')")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_reduced_motion_draws_the_notebook_at_once(fleet_home, tmp_path, alive, desk_browser):
    """With `prefers-reduced-motion: reduce` a state's marks are on the paper in the frame after the
    class, with no travelling pen, and leave the same way."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
        _notebook(page)
        _rest(page, "Ink.inspect().layer.marks.filter(m => m.selector.includes('state-idle')).length === 4")
        alive.add("alpha")
        _emit(page, "alpha", ("turn_started", {}))
        _until_class(page, "alpha", "state-running")
        counted = page.evaluate("""() => new Promise(done => {
          let n = 0;
          const step = () => { n += 1; const l = Ink.inspect().layer;
            const run = l.marks.find(m => m.selector.includes('state-running'));
            const idle = l.marks.some(m => m.lane === 'pane:alpha' && m.selector.includes('state-idle'));
            if (run && run.drawn === 1 && !idle) return done({ n, hands: l.hands });
            if (n > 30) return done({ n, hands: l.hands });
            requestAnimationFrame(step); };
          requestAnimationFrame(step); })""")
        assert counted["n"] <= 3 and counted["hands"] is False, counted
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_the_night_notebook_screens_its_highlighter_onto_charcoal(fleet_home, tmp_path, desk_browser):
    """#250: `notebook:dark` is the same table on charcoal stock with gel inks. The layer reads the
    stock's luminance from `--paper`, so the highlighter screens rather than multiplies, and every
    ink is the variant's -- read from the page, never from the module."""
    _desk(tmp_path, fleet_home, skin="notebook:dark")
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", reduced=True)
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
        # #329, folded here (decision 13): the needs-you name and its question read at 4.5:1
        # through each paper variant's, each farmstead weather's and each voxel world's (#334)
        # highlighter, ink on (glass is read in the glass test), and through every variant's
        # plain tint with `?ink=off`.
        _emit(page, "alpha", ("question_opened", {"question": "which sprint boundary should it use?",
                                                  "id": "q1", "blocking": True, "choices": ["this", "that"]}))
        _until_class(page, "alpha", "needs-human")
        _until(page, '.tile[data-repo="alpha"] .asks:not([hidden]) .ask:not([hidden]) .ask-q')
        inked = [v for v in HIGHLIGHTED if not v.startswith("glass:")]
        inked.remove("notebook:dark")
        _each_variant_reads_through_its_highlighter(page, "alpha", ["notebook:dark"])
        # A loaded runner: the next skin's module is up, and the layer has read the page's
        # colours, before that skin's stylesheet applies. The sheet is held until then; once
        # it lands the layer must read them again, or its highlighter stays the fallback.
        # Light paper after charcoal, a family of its own: taken by name, since the order of
        # HIGHLIGHTED is every_variant()'s, and voxel's worlds (#334) come before farmstead's.
        late = "farmstead:daytime"
        inked.remove(late)
        held = []
        page.route("**/static/skins/*/skin.css*", lambda route: held.append(route))
        _choose(page, late)
        page.wait_for_function("v => { const c = document.querySelector('canvas[data-skin]');"
                               " return !!c && c.dataset.skin === v; }", arg=late, timeout=15000)
        assert len(held) == 1, held
        daytime = skins.SKINS["farmstead"]["variants"]["daytime"]["inks"]["highlighter"]
        assert _layer(page)["inks"]["highlighter"] != daytime, "the sheet is held: its inks cannot be read yet"
        held[0].continue_()
        page.unroute("**/static/skins/*/skin.css*")
        _read_through_the_highlighter(page, "alpha", late)
        _each_variant_reads_through_its_highlighter(page, "alpha", inked)
        plain, perrors, _ = _open(browser, port, token, "&ink=off", reduced=True)
        _each_variant_reads_through_its_highlighter(plain, "alpha", HIGHLIGHTED, plain=True)
        assert not errors and not perrors, (errors, perrors)
        close_pages(browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_without_ink_the_notebook_is_the_same_table_drawn_plain_on_a_ruled_page(fleet_home, tmp_path, alive, desk_browser):
    """The gate off (nothing measured, as in CI without the override): `body.ink-off`, no canvas and
    no three.js, and the marks as the layer's plain CSS -- the same table: an idle pane outlined, a
    running name underlined, needing you tinted. Since #257 no rules or margin are printed in CSS:
    the plain look is the one every skin shares, and the ruled paper is the module's alone. So
    Lamplight without ink (#398) is the plain `eye-relief` page: its ground, panel and words, no
    lamp and no canvas."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
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
        assert look["rules"] == "none" and look["margin"] in ("", "rgba(0, 0, 0, 0)"), \
            f"the plain look paints the notebook's paper: {look}"
        assert look["running"] == "underline", look
        assert look["needs"] not in ("", "rgba(0, 0, 0, 0)") and look["question"] == look["needs"], look
        assert look["loop"] == "solid", look
        relief = theme.to_css(theme.get(skins.SKINS["notebook"]["variants"]["lamplight"]["base"]))
        _choose(page, "notebook:lamplight")
        page.wait_for_function(f"c => ({CHOSEN})(c) && Ink.inspect().plain",
                               arg=["notebook:lamplight", relief["--text"].upper()], timeout=30000)
        plain = page.evaluate("""() => { const root = getComputedStyle(document.documentElement), body = getComputedStyle(document.body);
          return { off: document.body.classList.contains('ink-off'), canvas: !!document.getElementById('ink'),
                   ground: body.backgroundColor, rules: body.backgroundImage,
                   tokens: ['--bg', '--panel', '--text', '--muted'].map(n => root.getPropertyValue(n).trim().toUpperCase()) }; }""")
        assert plain["off"] and not plain["canvas"] and plain["rules"] == "none", plain
        assert plain["tokens"] == [relief[n].upper() for n in ("--bg", "--panel", "--text", "--muted")], plain
        assert plain["ground"] == "rgb(%d, %d, %d)" % _rgb(relief["--bg"]), plain
        assert not [u for u in asked if "three.module" in u or "/ink/layer.js" in u], "no layer without ink"
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)


@pytest.mark.browser
def test_an_idle_notebook_writes_nothing_draws_nothing_and_settles_in_bounded_frames(fleet_home, tmp_path, desk_browser):
    """The render contract with the notebook on the paper: its marks are on the paper within the
    frames a hand at the pen's speed needs for their length, plus travel -- counted in frames, not
    milliseconds (plan-ink ground rule 5) -- and then an idle desk is zero DOM mutations and zero
    WebGL frames.

    #398, the lamp: on the same desk the paper is read back from the canvas at the lamp's centre
    (`_paper_at_the_lamp`) in each variant. Light and dark read what they did before the lamp;
    Lamplight is lit there, and stays within its two ends, `--paper` and `--lamp-max` (plus or minus
    1 per channel); and an idle lamplit desk is zero mutations and zero frames too: the lamp is
    still."""
    _desk(tmp_path, fleet_home)
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, "&ink=on", count=True, **DRAWN)
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
        count = observe_quiet(page, passes=8)
        read = {variant: _paper_at_the_lamp(page, variant) for variant in ("light", "dark", "lamplight")}
        lit = observe_quiet(page, passes=8)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert count["mutations"] == 0, f"an idle notebook wrote to the page: {count}"
    assert count["renders"] == 0, f"an idle notebook was redrawn {count['renders']} times"
    for variant, was in PAPER_BEFORE_THE_LAMP.items():
        y, got = read[variant]
        assert all(abs(a - b) <= 1 for a, b in zip(got, was)), (variant, "the paper moved", y, got, was)
    panel = skins.SKINS["notebook"]["variants"]["lamplight"]["composited_panel"]
    lo, hi = _rgb(panel["darkest"]), _rgb(panel["lightest"])
    y, got = read["lamplight"]
    assert all(lo[i] - 1 <= got[i] <= hi[i] + 1 for i in range(3)), ("off the lamplit paper", y, got, lo, hi)
    assert any(got[i] > lo[i] + 1 for i in range(3)), ("the lamp is out: unlit stock at its centre", y, got, lo)
    assert lit["mutations"] == 0, f"an idle lamplit notebook wrote to the page: {lit}"
    assert lit["renders"] == 0, f"an idle lamplit notebook was redrawn {lit['renders']} times"
