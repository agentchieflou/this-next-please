"""One platform, phase 2 (#257): a skin's stylesheet holds its layout and its typography, and nothing
it paints.

The operator's end state is "three.js only". A skin that draws with ink draws its paper, its frames
and its marks in its module (`static/ink/skins/<name>.js`); its `skin.css` keeps what the page needs
to lay the words out -- a margin to leave, a hand to write in -- and the colours the module reads,
as custom properties. Under `body.ink-off` every skin is the one plain look (`app.css` and the
palette, with the skin's mark table drawn as plain CSS by the layer's fallback), so there is no CSS
skin left to agree with a WebGL one.

The guard, per rule of every such stylesheet:

1. A custom property (`--*`) is allowed anywhere -- it is an input, not a look -- except the
   palette's own twenty-three tokens: a skin never recolours the palette, which is shared with the
   terminal (docs/themes.md).
2. A layout or typography property is allowed anywhere.
3. Anything else -- a background, a border, a shadow, a radius, a filter, an opacity, a colour --
   is allowed only where a skin's ink is on the page (a selector with `:not(.ink-off)` or
   `#ink[data-skin]`), and only to clear the page for the canvas or to name a token: `transparent`,
   `none`, `0`, or `var(--...)`. Never a literal colour, never a `url()`: a skin stands aside for
   the canvas and never paints over it.

It covers every skin that ships an ink module; a skin that lands without one is a CSS skin still,
and joins the guard the day its module does.
"""
from __future__ import annotations
import os
import re

import pytest

from agentdata import theme
from agentdata.fleet import skins

STATIC = os.path.dirname(skins.SKINS_DIR)
INK_SKINS = os.path.join(STATIC, "ink", "skins")

#: The palette's own tokens (app.css, `theme.to_css`): a skin reads them, and never sets them.
PALETTE = {"--bg", "--panel", "--text", "--line", "--select", "--muted", "--accent", "--focus",
           "--running", "--waiting", "--human", "--done", "--idle",
           "--on-running", "--on-waiting", "--on-human", "--on-done", "--on-idle",
           "--running-text", "--waiting-text", "--human-text", "--done-text", "--idle-text"}

#: What lays the words out and what they are written in -- and three hints to the engine that paint
#: nothing themselves (`will-change`, `contain`, `color-scheme`).
LAYOUT = re.compile(r"^(display|position|inset|top|right|bottom|left|width|height|min-width|min-height|"
                    r"max-width|max-height|margin(-[a-z]+)*|padding(-[a-z]+)*|gap|row-gap|column-gap|"
                    r"flex(-[a-z]+)*|grid(-[a-z]+)*|align-[a-z]+|justify-[a-z]+|place-[a-z]+|order|"
                    r"overflow(-[a-z]+)?|z-index|box-sizing|vertical-align|content|container(-[a-z]+)?|"
                    r"scroll-snap-type|scroll-snap-align|will-change|contain|color-scheme)$")
TYPOGRAPHY = re.compile(r"^(font(-[a-z]+)*|letter-spacing|word-spacing|line-height|text-align|"
                        r"text-transform|text-indent|white-space|word-break|overflow-wrap|hyphens|"
                        r"tab-size)$")
#: What a rule where the ink is on may set anything else to: clear, or a token.
CLEARING = re.compile(r"^\s*(transparent|none|0(px)?|initial|unset|inherit|"
                      r"var\(--[\w-]+(,\s*var\(--[\w-]+\))?\))(\s*!important)?\s*$")
INK_ON = re.compile(r":not\(\.ink-off\)|#ink\[data-skin")


def rules(css: str):
    """Every declaration in a stylesheet as (selector, property, value), with the selector of each
    `@media` block's rules as written inside it. Comments are dropped first."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0

    def block(text, prefix=""):
        pos = 0
        while True:
            open_ = text.find("{", pos)
            if open_ < 0:
                return
            head = text[pos:open_].strip()
            depth, j = 1, open_ + 1
            while depth and j < len(text):
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            body = text[open_ + 1:j - 1]
            if head.startswith("@"):
                block(body, prefix)
            else:
                for decl in re.split(r";(?![^(]*\))", body):
                    if ":" not in decl:
                        continue
                    prop, value = decl.split(":", 1)
                    out.append((head, prop.strip().lower(), value.strip()))
            pos = j

    block(css)
    return out


def refused(css: str) -> list[str]:
    """What the guard refuses in a stylesheet, one line per declaration, saying why."""
    bad = []
    for selector, prop, value in rules(css):
        where = f"{selector} {{ {prop}: {value} }}"
        if prop.startswith("--"):
            if prop in PALETTE:
                bad.append(f"sets the palette's own {prop}: {where}")
            continue
        if LAYOUT.match(prop) or TYPOGRAPHY.match(prop):
            continue
        # Every selector of a list, not the list: `a:not(.ink-off) x, a.ink-off x` is one rule that
        # paints the plain look too.
        if not all(INK_ON.search(s) for s in re.split(r",(?![^(]*\))", selector)):
            bad.append(f"paints {prop} for every look, the plain one included: {where}")
        elif not CLEARING.match(value):
            bad.append(f"paints {prop} over the canvas (only transparent, none, 0 or a token): {where}")
    return bad


def ink_skins() -> list[str]:
    """Every skin skins.py offers that ships an ink module."""
    return sorted(n for n in skins.SKINS if os.path.exists(os.path.join(INK_SKINS, n + ".js")))


def test_the_guard_knows_decoration_when_it_sees_it():
    """The parser and the rule, on stylesheets written to be caught -- so the guard is not a test
    that passes because it reads nothing."""
    assert refused("body[data-skin=x] { --paper: #FCF3A6; --ink-pen: #1F3F9A; }") == []
    assert refused("body[data-skin=x] .tile { padding-left: 34px; font-family: var(--hand); }") == []
    assert refused("body[data-skin=x]:not(.ink-off) .tile { background: transparent; box-shadow: none; }") == []
    assert refused("body:has(> #ink[data-skin]) .chip { color: var(--running) !important; }") == []
    # How a list scrolls is layout, in every look: the ruled transcript scrolls in whole rows (#338).
    assert refused("body[data-skin=x] .transcript { scroll-snap-type: y mandatory; } "
                   "body[data-skin=x] .transcript > li { scroll-snap-align: end; }") == []
    for css in ("body[data-skin=x] { --bg: #000; }",
                "body[data-skin=x] .tile { background: #FBF3E0; }",
                "body[data-skin=x] .tile { box-shadow: 0 4px 10px rgba(0,0,0,.25); }",
                "body[data-skin=x] { background-image: url(\"data:image/svg+xml,x\"); }",
                "body[data-skin=x]:not(.ink-off) header { background: #7A4B24; }",
                "body[data-skin=x]:not(.ink-off) .chip::before { background-image: url(sprites.svg#a); }",
                "@media (prefers-reduced-transparency: reduce) { body[data-skin=x] .tile { background: var(--panel); } }",
                "/* a comment { background: red } */ body[data-skin=x] .tile { border: 4px solid #6E4A28; }",
                "body[data-skin=x]:not(.ink-off) .tile, body[data-skin=x].ink-off .tile { background: var(--paper); }"):
        assert refused(css), css
    # A value with a `;` inside brackets is one declaration, and nested blocks are read.
    assert len(rules("a { background: url('x;y'); } @media (x) { b { color: red; } }")) == 2


def test_the_guard_covers_every_skin_that_draws_with_ink():
    names = ink_skins()
    assert {"glass", "graph", "legalpad", "farmstead", "notebook", "voxel", "napkin"} <= set(names), names
    for name in names:
        assert os.path.exists(os.path.join(skins.SKINS_DIR, name, "skin.css")), name


@pytest.mark.parametrize("name", ink_skins())
def test_a_skin_that_draws_with_ink_keeps_only_layout_and_typography(name):
    """#257: every decorative rule is gone from the skin's stylesheet. What it paints, its module
    draws; what the plain look is, the page is."""
    css = open(os.path.join(skins.SKINS_DIR, name, "skin.css"), encoding="utf-8").read()
    bad = refused(css)
    assert bad == [], f"{name}/skin.css paints:\n  " + "\n  ".join(bad)
    # And it carries no art: a stylesheet with a data URI or a sprite in it is a stylesheet
    # painting, whatever property the guard missed.
    assert "url(" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S), f"{name}/skin.css draws a picture"


def test_the_page_stands_aside_for_a_skins_canvas_in_one_place():
    """The rule every ink skin used to write for itself -- panes, header, footer and cards clear, so
    the paper the module draws behind them shows -- is the page's, once, keyed on the canvas being
    there with a table on it. Not on `:not(.ink-off)`: between the gate saying on and the layer
    arriving, a clear pane would have nothing behind it."""
    css = open(os.path.join(STATIC, "app.css"), encoding="utf-8").read()
    block = [r for r in rules(css) if "#ink[data-skin]" in r[0]]
    cleared = {(sel, prop) for sel, prop, value in block if CLEARING.match(value)}
    for part in ("header", "footer", ".tile", ".asks"):
        assert any(part in sel and prop in ("background", "background-color") for sel, prop in cleared), \
            (part, block)
    # The selection ring stays: a selected pane is still one pane (HIG *Focus and selection*).
    assert any(".is-selected" in sel and prop == "box-shadow" for sel, prop, _ in block), block


def _inks(spec, palette, skin_name=None):
    """The inks a variant draws with: the palette's, unless the skin names its own (`inks`, and
    `ink_tokens` for one that borrows another of the palette's colours)."""
    tokens = theme.to_css(palette)
    by_token = {"pencil": "--muted", "pen": "--accent", "red": "--human", "green": "--done",
                "marker": "--human", "highlighter": "--waiting"}
    out = {tool: tokens[token] for tool, token in by_token.items() if token in tokens}
    for tool, token in (spec.get("ink_tokens") or {}).items():
        out[tool] = tokens[token]
    out.update({k: v for k, v in (spec.get("inks") or {}).items() if k in by_token})
    if skin_name:
        module_path = os.path.join(INK_SKINS, skin_name + ".js")
        if os.path.exists(module_path):
            drawn = set(re.findall(r"""tool:\s*["'](\w+)["']""", open(module_path, encoding="utf-8").read()))
            out = {k: v for k, v in out.items() if k in drawn}
    return out


@pytest.mark.parametrize("skin_name,variant,spec", [v for v in skins.every_variant()],
                         ids=[f"{s}:{v}" for s, v, _ in skins.every_variant()])
def test_every_skin_and_palette_passes_theme_check_plain_and_in_ink(skin_name, variant, spec):
    """#257: every skin × palette pair the operator can reach (a variant *is* its skin and its
    palette), read both ways it can be drawn. In ink, the text and the marks are on the variant's
    composited paper. Plain, they are on the palette's own panel -- the one look `body.ink-off`
    shows for every skin -- with the skin's mark table drawn as CSS in the same inks."""
    palette = theme.get(spec["base"])
    inks = _inks(spec, palette, skin_name=skin_name) if os.path.exists(os.path.join(INK_SKINS, skin_name + ".js")) else None
    for panel in skins.composited_panels(spec):
        theme.check(palette, composited_panel=panel, skin=f"{skin_name}:{variant}", inks=inks)
    theme.check(palette, composited_panel=theme.to_css(palette)["--panel"],
                skin=f"{skin_name}:{variant} (plain)", inks=inks)
