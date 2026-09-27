"""Computed theme tokens in a real browser (Issue #325), the word on a state colour (#327), and a
word written in a state colour (#328).

Acceptance criteria:
- Browser, notebook:light and glass:smoke with ?ink=on:
  getComputedStyle(document.querySelector('.runline')).color equals the served --muted
  converted to rgb(r, g, b), and the reply input's ::placeholder colour equals it too.
"""
from __future__ import annotations

import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import events as E, serve as S, skins
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from desk_harness import close_pages
from test_fleet_ink import (  # noqa: F401 - fixtures used by name
    _desk_of, _open, _serve, _stop, fleet_home
)
from test_fleet_ink_notebook import _emit, alive, finished  # noqa: F401 - fixtures used by name


def _hex_to_rgb(hex_str: str) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgb({r}, {g}, {b})"


@pytest.mark.browser
@pytest.mark.parametrize("skin_name", ["notebook:light", "glass:smoke"])
def test_computed_muted_and_placeholder_tokens(fleet_home, tmp_path, skin_name, desk_browser):
    _desk_of(tmp_path, ("alpha", "beta"))

    # Write skin configuration
    (fleet_home.parent / "cfg.json").write_text(f'{{"theme": {{"skin": "{skin_name}"}}}}', encoding="utf-8")

    skin, variant = skin_name.split(":")
    t = theme.get(skins.SKINS[skin]["variants"][variant]["base"])
    expected_muted = theme.to_css(t)["--muted"]
    expected_rgb = _hex_to_rgb(expected_muted)

    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, extra="&ink=on", panes=2)

        page.wait_for_function(
            """() => !!document.querySelector('.runline') && !!document.querySelector('input.say')""",
            timeout=10000,
        )
        page.wait_for_function(
            f"""() => getComputedStyle(document.querySelector('.runline')).color === '{expected_rgb}'""",
            timeout=10000,
        )
        page.wait_for_function(
            f"""() => getComputedStyle(document.querySelector('input.say'), '::placeholder').color === '{expected_rgb}'""",
            timeout=10000,
        )

        runline_color = page.evaluate("() => getComputedStyle(document.querySelector('.runline')).color")
        placeholder_color = page.evaluate("() => getComputedStyle(document.querySelector('input.say'), '::placeholder').color")

        assert runline_color == expected_rgb
        assert placeholder_color == expected_rgb
        assert not errors, errors
        page.close()
        close_pages(browser)
    finally:
        _stop(server)


# ------------------------------------------------------------ #327: the word on a state colour

STATIC = os.path.join(os.path.dirname(S.__file__), "static")
ROLES = ("running", "waiting", "human", "done", "idle")
ROLE_TOKEN = re.compile(r"var\(--(running|waiting|human|done|idle|on-(running|waiting|human|done|idle))\)")
WHITE = re.compile(r"#fff\b|#ffffff\b|\bwhite\b", re.I)


def _app_css() -> str:
    with open(os.path.join(STATIC, "app.css"), encoding="utf-8") as f:
        return re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)


def _blocks(css: str):
    """Every innermost rule as (selector, {property: value}), `@media` and `@container` bodies
    included."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for decl in re.split(r";(?![^(]*\))", m.group(2)):
            if ":" in decl:
                prop, value = decl.split(":", 1)
                decls[prop.strip().lower()] = value.strip()
        out.append((" ".join(m.group(1).split()), decls))
    return out


def _root_tokens(css: str) -> dict:
    """The `none` palette: app.css's first `:root` block."""
    decls = next(d for s, d in _blocks(css) if s == ":root")
    return {k: v for k, v in decls.items() if k.startswith("--")}


def _palettes():
    """(name, tokens) for every built-in through `to_css`, and `none` from app.css `:root` (light,
    and the dark block's surfaces over it)."""
    out = [(t.name, theme.to_css(t)) for t in theme.list_themes() if t.name != "none"]
    css = _app_css()
    root = _root_tokens(css)
    out.append(("none", root))
    dark = next(d for s, d in _blocks(css) if s == ":root:not([data-theme])")
    out.append(("none (dark)", dict(root, **dark)))
    return out


def test_no_white_word_or_ground_on_a_state_colour_in_app_css():
    """No `#fff`, `#ffffff` or `white` as `color` or `background` in any app.css rule whose background
    or colour is a role token: the word on a state colour is its `--on-<role>` (#327)."""
    bad, seen = [], 0
    for sel, decls in _blocks(_app_css()):
        paint = {p: v for p, v in decls.items() if p in ("color", "background", "background-color")}
        if any(ROLE_TOKEN.search(v) for v in paint.values()):
            seen += 1
            bad += [f"{sel} {{ {p}: {v} }}" for p, v in paint.items() if WHITE.search(v)]
    assert seen >= 15, seen
    assert not bad, bad


def test_every_rail_glyph_reads_at_4_5_on_its_disc_in_every_palette():
    """Every `.pr-glyph` rule names its colour and its background as tokens, and the pair reads at
    4.5:1 for every built-in through `to_css` and for `none` (the group glyph is `--panel` on
    `--muted`)."""
    pairs = []
    for sel, decls in _blocks(_app_css()):
        if ".pr-glyph" not in sel:
            continue
        fg, bg = decls.get("color", ""), decls.get("background", decls.get("background-color", ""))
        fm, bm = re.fullmatch(r"var\((--[\w-]+)\)", fg), re.fullmatch(r"var\((--[\w-]+)\)", bg)
        assert fm and bm, f"{sel}: colour {fg!r} on {bg!r} must both be tokens"
        pairs.append((sel, fm.group(1), bm.group(1)))
    assert len(pairs) >= 8, pairs
    assert (".pane-rail.st-group .pr-glyph", "--panel", "--muted") in pairs
    low = []
    for name, tokens in _palettes():
        for sel, fg, bg in pairs:
            ratio = theme.contrast_ratio(tokens[fg], tokens[bg])
            if ratio < 4.5:
                low.append(f"{name}: {sel} {fg} {tokens[fg]} on {bg} {tokens[bg]} = {ratio:.2f}")
    assert not low, low


def test_the_none_palettes_words_read_at_4_5_on_its_state_colours():
    """app.css `:root` carries an `--on-<role>` for each role, chosen by the same rule as `to_css`, and
    each reads at 4.5:1 on its role (white on `--done` is 3.57:1 there, so it cannot be white)."""
    root = _root_tokens(_app_css())
    for role in ROLES:
        on, bg = root["--on-" + role], root["--" + role]
        assert theme.contrast_ratio(on, bg) >= 4.5, f"--on-{role} {on} on --{role} {bg}"
        assert on.lower() == theme.on_role(bg, root["--text"], root["--bg"]).lower(), role


def test_apply_theme_writes_every_token_to_css_returns():
    """A token `to_css` returns and `applyTheme` does not list is never written to the page."""
    with open(os.path.join(STATIC, "common.js"), encoding="utf-8") as f:
        js = f.read()
    body = js[js.index("function applyTheme("):]
    listed = set(re.findall(r'"(--[\w-]+)"', body[body.index("var tokens = ["):body.index("];")]))
    for t in list(theme.list_themes()) + [theme.random_theme(7)]:
        missing = set(theme.to_css(t)) - listed
        assert not missing, (t.name, missing)


#: One pane per role: its name is the chip it wears.
STATES = {"run": "running", "wait": "waiting_approval", "err": "error", "fin": "done", "rest": "idle"}

#: Each chip's word and age, as computed colours, against the chip's computed background.
CHIPS = """() => [...document.querySelectorAll('#grid .tile .head .chip')].map(c => {
  const age = c.querySelector('.chipage');
  return { repo: c.closest('.tile').dataset.repo, cls: c.className, bg: getComputedStyle(c).backgroundColor,
           word: getComputedStyle(c).color, age: age ? getComputedStyle(age).color : null,
           opacity: age ? getComputedStyle(age).opacity : null };
})"""


def _rgb(css: str):
    m = re.fullmatch(r"rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)", css or "")
    assert m, css
    return "#{:02X}{:02X}{:02X}".format(*(int(m.group(i)) for i in (1, 2, 3))), float(m.group(4) or 1)


def _chip_desk(tmp_path, alive, finished):
    """Five agents from real events, one per role: running (a held process, a turn open), waiting
    (an approval), error (exit 2), idle, and one held with its turn over that the test finishes
    (phase done) once the page is up."""
    names = tuple(STATES)
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    alive.update({"run", "fin"})
    finished.add("fin")
    E.append("run", [E.event("run", "turn_started", {}, ticket="RDSD-1")])
    E.append("wait", [E.event("wait", "needs_approval", {"summary": "transition RDSD-1"}, ticket="RDSD-1")])
    E.append("err", [E.event("err", "turn_started", {}, ticket="RDSD-1"),
                     E.event("err", "turn_ended", {"turn": "1"}, ticket="RDSD-1"),
                     E.event("err", "error", {"exit_code": 2}, ticket="RDSD-1")])
    S.arrange(order=list(names))
    S.update_window("main", open=names[0], widths={n: 1 for n in names})


# ------------------------------------------------------------ #339: rings, read off the screen

RECT = """(sel) => { const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height }; }"""
#: Keyboard focus as a person gives it: a Tab first, so the ring is the `:focus-visible` one.
FOCUS = """(sel) => { const el = document.querySelector(sel); el.focus(); return el.matches(':focus-visible'); }"""


def _pixels(page, clip):
    from test_fleet_desk_glass import _png_pixels

    w, h, bpp, rows = _png_pixels(page.screenshot(clip=clip))
    return [tuple(row[x * bpp:x * bpp + 3]) for row in rows for x in range(w)]


def _median(pixels):
    """The median pixel by luminance, as `#RRGGBB`."""
    px = sorted(pixels, key=lambda c: theme.rel_luminance(tuple(v / 255 for v in c)))[len(pixels) // 2]
    return "#{:02X}{:02X}{:02X}".format(*px)


def _ring(page, sel, side):
    """How a 2px ring 2-4px outside `sel`'s box (a `:focus-visible` outline at offset 2, the selection's
    `--focus` ring) reads against the pixels just outside it, 4-6px out: the median of one pixel row
    inside each band, 16px about the middle of the `side` edge (`top` or `bottom`), from a clipped
    screenshot."""
    import math

    r = page.evaluate(RECT, sel)
    assert r and r["w"] and r["h"], (sel, r)
    edge = r["y"] if side == "top" else r["y"] + r["h"]
    rows = ((math.ceil(edge - 2.5) - 1, math.ceil(edge - 4.5) - 1) if side == "top"
            else (math.floor(edge + 2.5), math.floor(edge + 4.5)))
    x = round(r["x"] + r["w"] / 2) - 8
    ring, out = (_median(_pixels(page, {"x": x, "y": y, "width": 16, "height": 1})) for y in rows)
    return round(theme.contrast_ratio(ring, out), 2), ring, out


def _rings(page, look, selected=None):
    """#339's rings on this page: Tab to the sidebar button in the header and to a pane, each ring >= 3:1
    against the pixels just outside it; and, with `selected`, the selected pane's outer ring under ink."""
    page.keyboard.press("Tab")
    low = []
    for sel, side in (("#sidetoggle", "bottom"), ("#grid > .tile[data-repo]:not(.is-hidden)", "top")):
        assert page.evaluate(FOCUS, sel), (look, sel, "not :focus-visible")
        ratio, ring, out = _ring(page, sel, side)
        if ratio < 3.0:
            low.append(f"{look}: the focus ring on {sel} {ring} against {out} = {ratio}")
    page.evaluate("() => document.activeElement.blur()")
    if selected:
        sel = f'#grid > .tile[data-repo="{selected}"].is-selected'
        page.wait_for_function("(sel) => !!document.querySelector(sel)", arg=sel, timeout=15000)
        ratio, ring, out = _ring(page, sel, "top")
        if ratio < 3.0:
            low.append(f"{look}: the selected pane's ring {ring} against {out} = {ratio}")
    return low


@pytest.mark.browser
@pytest.mark.parametrize("ink", ["on", "off"])
@pytest.mark.parametrize("look", ["voxel:overworld", "voxel:nether", "glass:azure", "none"])
def test_every_chip_word_and_age_read_at_4_5_on_the_chip(fleet_home, tmp_path, alive, finished, look, ink, desk_browser):
    """Browser (#327), ink on and off: each `.chip` word and its `.chipage`, as computed, read at
    4.5:1 on the chip's computed background, for one pane in every state. The look is served in the
    page (#345), not switched in late."""
    _chip_desk(tmp_path, alive, finished)
    (fleet_home.parent / "cfg.json").write_text(f'{{"theme": {{"skin": "{look}"}}}}', encoding="utf-8")
    server, token, port = _serve()
    try:
        browser = desk_browser
        page, errors, _ = _open(browser, port, token, extra=f"&ink={ink}", panes=len(STATES))
        # Once the page has the desk: its first fold writes each project's own phase first.
        _emit(page, "fin", ("phase_changed", {"from": "build", "to": "done"}))
        want = ", ".join(f'.tile[data-repo="{r}"] .head .chip.{s}' for r, s in STATES.items())
        try:
            page.wait_for_function(
                "(want) => { if (document.querySelectorAll(want).length === 5) return true; refresh(); return false; }",
                arg=want, timeout=15000, polling=250)
        except Exception:
            pytest.fail(f"the chips never reached their states: {page.evaluate(CHIPS)}")
        if look != "none":
            family = look.split(":")[0]
            page.wait_for_function(
                f"""() => document.body.dataset.skin === '{family}'
                         && [...document.styleSheets].some(s => (s.href || '').includes('/skins/{family}/'))""",
                timeout=15000)
        chips = page.evaluate(CHIPS)
        # #339: with ink on, on voxel:overworld and the plain page (light), the keyboard's rings read at
        # 3:1 on what is around them, and so does the selected pane's two-tone ring on voxel.
        rings = []
        if ink == "on" and look in ("voxel:overworld", "none"):
            if look != "none":
                S.select(selected="wait")
            rings = _rings(page, look, selected="wait" if look != "none" else None)
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert not rings, rings
    assert {c["repo"] for c in chips} == set(STATES), chips
    low = []
    for c in chips:
        bg, alpha = _rgb(c["bg"])
        assert alpha == 1, f"{look} ink {ink}: {c['repo']} chip ground {c['bg']} is not opaque"
        for part in ("word", "age"):
            fg, a = _rgb(c[part])
            ratio = theme.contrast_ratio(fg, bg)
            if ratio < 4.5 or a != 1:
                low.append(f"{c['repo']} ({c['cls']}) {part} {c[part]} on {c['bg']} = {ratio:.2f}")
        assert c["opacity"] == "1", c
    assert not low, (look, ink, low)


# ------------------------------------------------------------ #328: a word in a state colour

#: A word written in a bare state colour -- the criterion's own pattern. A border, an outline or a
#: `text-decoration-color` in one is a mark, held to 3:1, and the lookbehind leaves it alone.
BARE_WORD = re.compile(r"(?<![\w-])color\s*:\s*var\(--(running|waiting|human|done|idle)\)")


def _stylesheets():
    """app.css and every skin's stylesheet, comments dropped, as (name, css)."""
    out = [("app.css", _app_css())]
    skins_dir = os.path.join(STATIC, "skins")
    for name in sorted(os.listdir(skins_dir)):
        path = os.path.join(skins_dir, name, "skin.css")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                out.append((f"skins/{name}/skin.css", re.sub(r"/\*.*?\*/", "", f.read(), flags=re.S)))
    return out


def _root_blocks(css: str) -> dict:
    """The plain page's two palettes as app.css writes them: `:root`, and under the OS dark scheme
    `:root:not([data-theme])` over it (the state colours are shared, the surfaces are its own)."""
    root = _root_tokens(css)
    dark = next(d for s, d in _blocks(css) if s == ":root:not([data-theme])")
    return {"light": root, "dark": dict(root, **{k: v for k, v in dark.items() if k.startswith("--")})}


def test_no_word_is_written_in_a_bare_state_colour():
    """#328: a word in a state colour is written in its `--<role>-text` token, held to 4.5:1, never
    in the role colour itself, which is held only to a mark's 3:1 -- in app.css and in every skin's
    stylesheet. The one place a role colour is the word is on its own `--on-<role>` disc (the
    needs-you rail's glyph and badge), the pair rule 7 holds."""
    bad, discs = [], 0
    for name, css in _stylesheets():
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            sel, body = " ".join(m.group(1).split()), m.group(2)
            decls = dict((p.strip().lower(), v.strip()) for p, _, v in
                         (d.partition(":") for d in re.split(r";(?![^(]*\))", body) if ":" in d))
            ground = decls.get("background", decls.get("background-color", ""))
            for word in BARE_WORD.finditer(body):
                if re.fullmatch(r"var\(--on-%s\)" % word.group(1), ground):
                    discs += 1
                else:
                    bad.append(f"{name}: {sel} {{ {word.group(0)} }}")
    assert discs >= 2, "the scan found no needs-you disc: it is reading nothing"
    assert not bad, "\n".join(bad)
    every = "".join(css for _, css in _stylesheets())
    for role in ROLES:
        assert f"var(--{role}-text)" in every, f"no stylesheet writes a word in --{role}-text"


def test_the_plain_pages_words_in_a_state_colour_read_at_4_5_light_and_dark():
    """#328: both app.css `:root` blocks carry the five `-text` tokens -- the dark one its own, as
    the light block's `--human-text` is 2.89:1 on the dark `--panel` -- each chosen by the rule
    `to_css` uses (`theme.role_text`) against its own block's `--bg`, `--panel` and `--select`, and
    each reading at 4.5:1 on all three."""
    css = _app_css()
    dark_block = next(d for s, d in _blocks(css) if s == ":root:not([data-theme])")
    low = []
    for scheme, tokens in _root_blocks(css).items():
        grounds = [tokens["--bg"], tokens["--panel"], tokens["--select"]]
        for role in ROLES:
            if scheme == "dark":
                assert f"--{role}-text" in dark_block, f"the dark block leaves --{role}-text to the light one"
            word = tokens[f"--{role}-text"]
            chosen = theme.role_text(tokens[f"--{role}"], tokens["--text"], grounds)
            assert word.lower() == chosen.lower(), f"{scheme} --{role}-text {word}, the rule chooses {chosen}"
            low += [f"{scheme} --{role}-text {word} on {g} = {theme.contrast_ratio(word, g):.2f}"
                    for g in grounds if theme.contrast_ratio(word, g) < 4.5]
    assert not low, low


def test_the_plain_page_holds_text_at_4_5_on_the_pressed_ground():
    """Rule 9 (#328) for the plain page: `--text` on `--select`, where a pressed control writes its
    word, reads at 4.5:1 in both app.css `:root` blocks (13.34:1 light, 10.81:1 dark)."""
    for scheme, tokens in _root_blocks(_app_css()).items():
        ratio = theme.contrast_ratio(tokens["--text"], tokens["--select"])
        assert ratio >= 4.5, f"{scheme}: --text {tokens['--text']} on --select {tokens['--select']} = {ratio:.2f}"


#: The looks the criterion names, ink on; each variant is drawn on its own palette.
WORD_LOOKS = ("glass:smoke", "graph:blueprint", "voxel:overworld", "farmstead:rainy")

#: Every word the criterion names that is written in `--human`: the error's why line, the
#: transcript's "exit 2" and the question card's "it asked you:".
HUMAN_WORDS = {"why": '.tile[data-repo="err"].state-error .why',
               "exit": '.tile[data-repo="err"] .transcript li.error .v',
               "asks": '.tile[data-repo="ask"] .asks:not([hidden]) .asks-head'}

PAINTED = """(sel) => Object.fromEntries(Object.entries(sel).map(([k, s]) => {
  const el = document.querySelector(s);
  return [k, el ? getComputedStyle(el).color : null];
}))"""
SERVED = "() => getComputedStyle(document.documentElement).getPropertyValue('--human-text').trim()"


#: #339's pressed controls: an open sidebar tab and a pinned pane's pin. Each one's computed colour and
#: box-shadow, its rect, and the served `--text`.
PRESSED_CONTROLS = {"tab": ".side-tabs .segment.active", "pin": ".tile.is-pinned .head .pintoggle"}
PRESSED_READ = """(sel) => Object.fromEntries(Object.entries(sel).map(([k, s]) => {
  const el = document.querySelector(s), c = getComputedStyle(el), r = el.getBoundingClientRect();
  return [k, { color: c.color, shadow: c.boxShadow, rect: { x: r.left, y: r.top, width: r.width, height: r.height } }];
}))"""
#: The word and the pin's glyph (its stroke is `currentColor`) made transparent, for the pixels under them.
UNWORDED = """(sel) => { const st = document.createElement('style');
  st.textContent = Object.values(sel).join(', ') + ' { color: transparent !important; }';
  document.head.appendChild(st); }"""


def _pressed(page, look):
    """#339, criterion 6: the sidebar open on a tab (the window's `section`) and the pinned pane's pin compute `color` equal
    to the served `--text` and a ring; with the word and glyph transparent, `--text` against the median
    of each control's own pixels is >= 4.5:1. Returns what failed."""
    try:
        page.wait_for_function("(sel) => { if (Object.values(sel).every(s => !!document.querySelector(s))) return true;"
                               " refresh(); return false; }", arg=PRESSED_CONTROLS, timeout=15000, polling=250)
    except Exception:
        pytest.fail(f"{look}: the pressed controls never showed: " + str(page.evaluate(
            "(sel) => Object.fromEntries(Object.entries(sel).map(([k, s]) => [k, !!document.querySelector(s)]))"
            " ", PRESSED_CONTROLS)) + " " + str(page.evaluate("() => [...document.querySelectorAll('.tile')]"
            ".map(t => t.className)")))
    text = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--text').trim()")
    read = page.evaluate(PRESSED_READ, PRESSED_CONTROLS)
    page.evaluate(UNWORDED, PRESSED_CONTROLS)
    page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
    low = []
    for name, got in read.items():
        if got["color"] != _hex_to_rgb(text) or got["shadow"] in ("", "none"):
            low.append(f"{look}: the pressed {name} is {got['color']} with ring {got['shadow']!r}; --text is {text}")
        ground = _median(_pixels(page, got["rect"]))
        ratio = theme.contrast_ratio(text, ground)
        if ratio < 4.5:
            low.append(f"{look}: --text {text} on the pressed {name}'s median {ground} = {ratio:.2f}")
    return low


def _words_desk(tmp_path):
    """Two panes from real events: `err`, whose last turn ended in exit 2 (its why line and its
    transcript's `li.error`), and `ask`, holding a blocking question (the card's head)."""
    for name in ("err", "ask"):
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "assistant_text", {"text": "working on " + name}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])
    E.append("err", [E.event("err", "turn_started", {}, ticket="RDSD-1"),
                     E.event("err", "turn_ended", {"turn": "1"}, ticket="RDSD-1"),
                     E.event("err", "error", {"exit_code": 2}, ticket="RDSD-1")])
    E.append("ask", [E.event("ask", "question_opened", {"question": "which window should this land in?",
                                                        "id": "q1", "blocking": True,
                                                        "choices": ["left", "right"]}, ticket="RDSD-1")])
    S.arrange(order=["err", "ask"])
    S.update_window("main", open="err", widths={"err": 1, "ask": 1})


def _choose(fleet_home, theme_json: str):
    """The look the next page is served: written while no page of this desk is open."""
    (fleet_home.parent / "cfg.json").write_text('{"theme": %s}' % theme_json, encoding="utf-8")


def _until_words(page, sel):
    """Until the fold has put every word on the page, asking it to look again while it waits."""
    page.wait_for_function(
        "(sel) => { if (Object.values(sel).every(s => !!document.querySelector(s))) return true;"
        " refresh(); return false; }", arg=sel, timeout=15000, polling=250)


@pytest.mark.browser
def test_words_in_a_state_colour_are_painted_in_the_served_text_token(fleet_home, tmp_path, desk_browser):
    """Browser (#328). Ink on, on glass:smoke, graph:blueprint, voxel:overworld and farmstead:rainy:
    the error's why line, the transcript's "exit 2" and the question card's head are painted in the
    `--human-text` the page is served -- the one `to_css(base, panels=panels_on(base))` chose -- and
    farmstead's clear error chip writes its word in it too. Then the plain page under the OS dark
    scheme (`none`, Playwright `color_scheme="dark"`): the card's head and the why line are painted in
    the dark `:root` block's own `--human-text`. One server and one browser; a page per look."""
    _words_desk(tmp_path)
    seen, low = {}, []
    server, token, port = _serve()
    try:
        browser = desk_browser
        for look in WORD_LOOKS:
            family = look.split(":")[0]
            _choose(fleet_home, '{"skin": "%s"}' % look)
            sel = dict(HUMAN_WORDS)
            if family == "farmstead":
                sel["chip"] = '.tile[data-repo="err"] .head .chip.error'
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=2)
            _until_words(page, sel)
            page.wait_for_function(
                """([look, family]) => (Ink.inspect().table === look || (refresh(), false))
                         && document.body.dataset.skin === family && !document.body.classList.contains('ink-off')
                         && [...document.querySelectorAll('link[data-skin]')].some(l => l.sheet
                              && l.href.includes('/static/skins/' + family + '/skin.css'))""",
                arg=[look, family], timeout=30000, polling=250)
            seen[look] = (page.evaluate(SERVED), page.evaluate(PAINTED, sel))
            if look == "voxel:overworld":
                S.arrange(pinned=["err"])
                S.update_window("main", section="drawer")
                low += _pressed(page, look)
            assert not errors, (look, errors)
            page.close()

        # #339 on the other looks the criteria name, ink on: farmstead:daytime's keyboard rings and its
        # selected pane's ring; the pressed tab and pin on the plain page, sand with no skin and
        # notebook:light.
        S.select(selected="ask")
        for look, chosen in (("farmstead:daytime", '{"skin": "farmstead:daytime"}'),
                             ("none", "{}"), ("sand", '{"skin": "none", "default": "sand"}'),
                             ("notebook:light", '{"skin": "notebook:light"}')):
            _choose(fleet_home, chosen)
            page, errors, _ = _open(browser, port, token, "&ink=on", panes=2)
            if ":" in look:
                page.wait_for_function(
                    """(look) => (Ink.inspect().table === look || (refresh(), false))
                         && !document.body.classList.contains('ink-off')""",
                    arg=look, timeout=30000, polling=250)
            if look == "farmstead:daytime":
                low += _rings(page, look, selected="ask")
            else:
                low += _pressed(page, look)
            assert not errors, (look, errors)
            page.close()

        _choose(fleet_home, "{}")
        page = browser.new_page(viewport={"width": 1400, "height": 900}, color_scheme="dark")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        sel = {k: HUMAN_WORDS[k] for k in ("asks", "why")}
        _until_words(page, sel)
        page.wait_for_function("() => !document.documentElement.dataset.theme && !document.body.dataset.skin",
                               timeout=15000)
        seen["none (dark)"] = (page.evaluate(SERVED), page.evaluate(PAINTED, sel))
        low += _rings(page, "none (dark)")
        assert not errors, errors
        close_pages(browser)
    finally:
        _stop(server)
    assert not low, low

    # Every look first, so a page that paints its words in anything but its served token says which.
    unpainted = {look: (served or "no --human-text served", painted) for look, (served, painted) in seen.items()
                 if not served or painted != {k: _hex_to_rgb(served) for k in painted}}
    assert not unpainted, unpainted
    for look in WORD_LOOKS:
        served, painted = seen[look]
        family, variant = look.split(":")
        base = skins.SKINS[family]["variants"][variant]["base"]
        want = theme.to_css(theme.get(base), panels=skins.panels_on(base))["--human-text"]
        assert served.upper() == want, f"{look}: served --human-text {served}, to_css chose {want}"
        assert want != theme.get(base).status["fail"], f"{look}: the test cannot tell the token from the role"
    served, painted = seen["none (dark)"]
    dark_word = _root_blocks(_app_css())["dark"].get("--human-text")
    assert served and served.lower() == str(dark_word).lower(), (served, dark_word, painted)
    assert painted == {"asks": _hex_to_rgb(served), "why": _hex_to_rgb(served)}, (served, painted)


# ------------------------------------------------------------ #339: focus, selection and pressed never wear a state

#: The four pressed rules #339 draws the model picker's way: `--text` on `--select` and a ring.
PRESSED = (".segment.active", ".head .pintoggle.active", ".tile.is-pinned .head .pintoggle",
           ".head .pintoggle.active, .head .maxtoggle.active")


def test_focus_selection_and_pressed_never_take_a_state_or_the_accent_in_app_css():
    """#339, static. No `:focus-visible` rule in app.css takes its colour from `--accent`; no rule whose
    selector has `.active` or `.is-pinned` writes `color: var(--accent)`; the four pressed rules set
    `color: var(--text)`, `background: var(--select)` and a ring in `--focus`; under ink the selected pane
    wears the two-tone ring; the pane's strip is `--focus`; and both plain `:root` blocks carry a `--focus`
    chosen by the palette rule (their own `--text` made neutral) that passes rule 10 on their surfaces."""
    blocks = _blocks(_app_css())
    focus_rules = [(s, d) for s, d in blocks if ":focus-visible" in s]
    assert len(focus_rules) >= 5, focus_rules
    bad = [f"{s} {{ {p}: {v} }}" for s, d in focus_rules for p, v in d.items() if "--accent" in v]
    bad += [f"{s} {{ color: {d['color']} }}" for s, d in blocks
            if (".active" in s or ".is-pinned" in s) and "var(--accent)" in d.get("color", "")]
    assert not bad, bad
    for sel in PRESSED:
        decls = next((d for s, d in blocks if s == sel), None)
        assert decls, f"no rule {sel!r}"
        assert decls.get("color") == "var(--text)" and decls.get("background") == "var(--select)", (sel, decls)
        assert decls.get("box-shadow") == "inset 0 0 0 2px var(--focus)", (sel, decls)
    inked = next(d for s, d in blocks if s == "body:has(> #ink[data-skin]) .tile.is-selected")
    assert inked["box-shadow"] == "0 0 0 2px var(--bg), 0 0 0 4px var(--focus), 0 0 0 6px var(--bg)", inked
    tile = next(d for s, d in blocks if s == ".tile")
    assert tile["border-left"] == "3px solid var(--focus)", tile
    for scheme, tokens in _root_blocks(_app_css()).items():
        focus, roles = tokens["--focus"], [tokens["--" + r] for r in ROLES]
        assert focus.lower() == theme.neutral(tokens["--text"]).lower(), (scheme, focus)
        assert theme.clear_of_states(focus, roles), (scheme, focus)
        for g in ("--bg", "--panel", "--select"):
            assert theme.contrast_ratio(focus, tokens[g]) >= 3.0, (scheme, g, focus, tokens[g])


def test_a_pane_no_project_coloured_wears_no_state_in_the_fleet(fleet_home, tmp_path):
    """#339, `/api/fleet`. On voxel:overworld, voxel:nether and farmstead:daytime every pane's accent is
    achromatic or >= 30 degrees from every chromatic role of the palette it is served on, and >= 3:1 on
    its panel -- unless `theme.projects` chose it, which is used as chosen. On the plain page (`none`) no
    pane is sent an accent at all (the tile's own `--focus` border paints the strip), and never
    `#3FB950`, the done green."""
    _desk_of(tmp_path, ("alpha", "beta", "gamma"))
    cfg = fleet_home.parent / "cfg.json"
    for look in ("voxel:overworld", "voxel:nether", "farmstead:daytime"):
        cfg.write_text('{"theme": {"skin": "%s", "projects": {"gamma": {"accent": "#3FB950"}}}}' % look,
                       encoding="utf-8")
        base = skins.get_skin(look)["base"]
        panels = skins.panels_on(base)
        tokens = theme.to_css(theme.get(base), panels=panels)
        roles = [tokens["--" + r] for r in ROLES]
        accents = {r["repo"]: r["accent"] for r in S.fleet_snapshot()["repos"]}
        assert accents["gamma"] == "#3FB950", accents                  # the operator's choice, as chosen
        for repo in ("alpha", "beta"):
            mark = accents[repo]
            assert mark == theme.pane_mark(theme.get(base), panels=panels), (look, repo, mark)
            assert theme.clear_of_states(mark, roles), (look, repo, mark)
            assert all(theme.contrast_ratio(mark, g) >= 3.0 for g in (tokens["--panel"], *panels)), (look, mark)
    cfg.write_text('{"theme": {}}', encoding="utf-8")
    assert {r["repo"]: r["accent"] for r in S.fleet_snapshot()["repos"]} == {"alpha": "", "beta": "", "gamma": ""}
