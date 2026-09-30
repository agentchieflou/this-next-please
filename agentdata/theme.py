"""Theme model, contrast checks, terminal recolouring, and palette rendering.

One palette drives four renders: SGR/truecolor escapes, an Oh My Posh .omp.json, a Windows Terminal scheme,
and the dashboard CSS custom properties.

Status colours carry meaning and NEVER change role; the glyph is always present; `reds` is the proof.
Pure white on pure black is refused -- `eye-relief` caps contrast near 7:1 on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass
import colorsys
import hashlib
import os
import random
import re
import sys
from typing import Any

from . import textio
from . import theme_signals as signals


class ThemeError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Theme:
    name: str
    title: str
    why: str
    ground: str | None
    text: str | None
    accent: str | None
    cursor: str | None
    ansi: tuple[str, ...]
    status: dict[str, str]
    light: bool = False
    layout: str = "jandedobbeleer"
    muted: str | None = None


# ---------- Color math & Contrast check ----------

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, round(rgb[0] * 255))),
        max(0, min(255, round(rgb[1] * 255))),
        max(0, min(255, round(rgb[2] * 255)))
    )


def rel_luminance(rgb: tuple[float, float, float]) -> float:
    def adjust(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [adjust(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(h1: str, h2: str) -> float:
    l1 = rel_luminance(hex_to_rgb(h1))
    l2 = rel_luminance(hex_to_rgb(h2))
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def hue(h: str) -> float:
    r, g, b = hex_to_rgb(h)
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


def hue_distance(h1: str, h2: str) -> float:
    d = abs(hue(h1) - hue(h2))
    return min(d, 360.0 - d)


def mix(h1: str, h2: str, weight: float) -> str:
    """Blend h1 towards h2 by weight (0.0 = all h1, 1.0 = all h2)."""
    r1, g1, b1 = hex_to_rgb(h1)
    r2, g2, b2 = hex_to_rgb(h2)
    r = r1 + (r2 - r1) * weight
    g = g1 + (g2 - g1) * weight
    b = b1 + (b2 - b1) * weight
    return rgb_to_hex((r, g, b))


def saturation(h: str) -> float:
    """HSV saturation, 0-1: how far from grey."""
    return colorsys.rgb_to_hsv(*hex_to_rgb(h))[1]


#: A colour whose HSV saturation is at or under this reads as grey: it cannot be mistaken for a state.
ACHROMATIC = 0.25
#: The hue a mark that says "focused", "selected", "pressed" or "which project" keeps from every state colour.
STATE_HUE_GAP = 30.0


def neutral(h: str, cap: float = 0.12) -> str:
    """`h` with its HSV value kept and its saturation capped at `cap` (#339): the same lightness, nearly grey."""
    hh, ss, vv = colorsys.rgb_to_hsv(*hex_to_rgb(h))
    return rgb_to_hex(colorsys.hsv_to_rgb(hh, min(ss, cap), vv))


def clear_of_states(colour: str, roles) -> bool:
    """True when `colour` cannot be read as a state (#339): achromatic, or >= 30 degrees of hue from every
    chromatic role colour in `roles`. An achromatic role (a grey idle) has no hue to be confused with."""
    if saturation(colour) <= ACHROMATIC:
        return True
    return all(hue_distance(colour, r) >= STATE_HUE_GAP for r in roles if saturation(r) > ACHROMATIC)


def marks_clear(colour: str | None, grounds, roles) -> bool:
    """The step-1 test of #339: a mark colour that is >= 3:1 on every one of `grounds` and clear of every state."""
    return bool(colour) and all(contrast_ratio(colour, g) >= 3.0 for g in grounds) and clear_of_states(colour, roles)


def _muted(t: Theme, accent: str | None = None) -> str:
    """Derive a muted colour: mix text towards ground at the largest weight that keeps >= 4.6:1."""
    if not t.text or not t.ground:
        return "#888888"
    acc = accent or t.accent or t.text
    panel = mix(t.ground, t.text, 0.04)
    select = mix(t.ground, acc, 0.18)
    surfaces = (t.ground, panel, select)
    for step in range(100, -1, -1):
        w = step / 100.0
        cand = mix(t.text, t.ground, w)
        if all(contrast_ratio(cand, s) >= 4.6 for s in surfaces):
            return cand
    return t.text


#: The five role tokens a word is written ON (a chip, a badge, a rail's glyph), in `to_css` order.
ROLES = ("--running", "--waiting", "--human", "--done", "--idle")


def on_role(role: str, text: str, ground: str) -> str:
    """The colour a word is written in on the role colour `role` (#327): the first of `text`,
    `ground`, white and near-black that reads at 4.5:1 on it, or, if none does, the one that reads
    best. Status colours are shared with the terminal and never change, so the word bends instead."""
    candidates = (text, ground, "#FFFFFF", "#111111")
    for c in candidates:
        if contrast_ratio(c, role) >= 4.5:
            return c
    return max(candidates, key=lambda c: contrast_ratio(c, role))


def role_text(role: str, text: str, grounds) -> str:
    """The colour a word is written in when it is written IN the role colour `role` (#328): the why
    line, "exit 2", "it asked you:", a clear chip's word. The role itself when it reads at 4.5:1 on
    every one of `grounds`; otherwise the role moved toward `text` in steps of 0.02 until it does;
    `text` if no step does (rule 8 of `check` then judges it). A mark in the role colour -- a border,
    an outline, a disc -- is held to 3:1 and keeps the role itself; a word needs 4.5:1 (WCAG 1.4.3)."""
    grounds = tuple(grounds)
    for step in range(50):
        cand = mix(role, text, step / 50) if step else role
        if all(contrast_ratio(cand, g) >= 4.5 for g in grounds):
            return cand
    return text


def to_css(t: Theme, project_accent: str | None = None, panels=()) -> dict[str, str]:
    """Render a Theme as CSS custom properties according to the stated mapping.

    Tokens:
      --bg: ground
      --text: text
      --panel: ground moved 4% toward text
      --line: ground moved 15% toward text
      --select: ground moved 18% toward accent
      --muted: t.muted or derived at >= 4.6:1
      --accent: accent or project's own
      --focus: cursor when it is >= 3:1 on --panel and every one of `panels` and clear of every state
        (`clear_of_states`), else `neutral(text)` (#339): focus, selection and pressed never wear a state
      --running: status.info
      --waiting: status.warn
      --human: status.fail
      --done: status.ok
      --idle: status.skip
      --on-running, --on-waiting, --on-human, --on-done, --on-idle: the word on that role colour,
        chosen by `on_role` (#327)
      --running-text, --waiting-text, --human-text, --done-text, --idle-text: a word written in that
        role colour, chosen by `role_text` against --bg, --panel, --select and every colour in
        `panels` (#328)

    `panels` are the composited panels the palette is drawn on under a skin (the fleet's
    `skins.panels_on(t.name)`, which the caller passes: this module never imports the fleet), so one
    set of `-text` tokens serves the palette under every skin drawn on it.
    """
    if t.name == "none" or t.ground is None or t.text is None:
        return {}
    accent = project_accent or t.accent
    panel = mix(t.ground, t.text, 0.04)
    line = mix(t.ground, t.text, 0.15)
    select = mix(t.ground, accent, 0.18)
    muted = t.muted if t.muted is not None else _muted(t, accent=accent)
    out = {
        "--bg": t.ground,
        "--text": t.text,
        "--panel": panel,
        "--line": line,
        "--select": select,
        "--muted": muted,
        "--accent": accent,
        "--running": t.status.get("info", "#58A6FF"),
        "--waiting": t.status.get("warn", "#D29922"),
        "--human": t.status.get("fail", "#FF5C5C"),
        "--done": t.status.get("ok", "#3FB950"),
        "--idle": t.status.get("skip", "#8B949E"),
    }
    roles = [out[r] for r in ROLES]
    out["--focus"] = t.cursor if marks_clear(t.cursor, (panel, *panels), roles) else neutral(t.text)
    for role in ROLES:
        out["--on-" + role[2:]] = on_role(out[role], t.text, t.ground)
    grounds = (t.ground, panel, select, *panels)
    for role in ROLES:
        out[role + "-text"] = role_text(out[role], t.text, grounds)
    return out


def pane_mark(t: Theme, panels=()) -> str:
    """The colour a pane's project strip falls back to when no project chose one (#339): the palette's accent
    when it passes the `--focus` test (>= 3:1 on `--panel` and every panel, clear of every state), else the
    palette's `--muted` made neutral. `""` for the plain palette, whose strip `.tile`'s own border paints."""
    if t.name == "none" or t.ground is None or t.text is None:
        return ""
    c = to_css(t, panels=panels)
    if marks_clear(t.accent, (c["--panel"], *panels), [c[r] for r in ROLES]):
        return t.accent
    return neutral(c["--muted"])


def css(t: Theme, project_accent: str | None = None, panels=()) -> dict[str, str]:
    """Alias for to_css()."""
    return to_css(t, project_accent=project_accent, panels=panels)


#: How much of a highlighter's ink a highlighted line of text is read through in the plain
#: fallback (`static/ink/ink.js` PLAIN_TINT): rule 5's `plain=True` reading.
INK_TINT = 0.38

#: The ink layer's highlighter (#329), as `static/ink/pen.js`'s highlighter branch draws it: on a
#: dark ground the swipe is screened on at 0.42 of the ink, on a light one multiplied in at 0.68.
#: `tests/test_theme.py` reads both numbers back out of pen.js, so the model cannot drift from it.
HL_SCREEN = 0.42
HL_MULTIPLY = 0.68


def is_dark(h: str) -> bool:
    """The ink layer's `dark` (`static/ink/layer.js` `colours()`): Rec. 709 weights over the
    gamma-encoded 0-1 channels, under 0.4 -- not `rel_luminance`."""
    r, g, b = hex_to_rgb(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.4


def highlight_under(paper: str, ink: str, dark: bool) -> str:
    """The colour under a highlighted word at full coverage, per sRGB channel: screen
    `1-(1-paper)(1-HL_SCREEN*ink)` on a dark ground, multiply `paper*(1-HL_MULTIPLY*(1-ink))` on a
    light one. Streaks only thin the ink, so this is the worst case the text is read on."""
    p, i = hex_to_rgb(paper), hex_to_rgb(ink)
    if dark:
        return rgb_to_hex(tuple(1 - (1 - a) * (1 - HL_SCREEN * b) for a, b in zip(p, i)))
    return rgb_to_hex(tuple(a * (1 - HL_MULTIPLY * (1 - b)) for a, b in zip(p, i)))


def check(t: Theme, composited_panel: str | None = None, skin: str | None = None,
          inks: dict[str, str] | None = None, panels=(), *, plain: bool = False,
          dark: bool | None = None) -> None:
    """The theme invariant, computed, not judged by eye.

    1. text on ground >= 4.5:1 and <= 19:1 (pure white on pure black is refused).
    2. Each status colour on ground >= 3:1.
    3. Status pairwise distinction (ok, warn, fail).
    4. For reds and matrix, fail is not within stated hue distance of text.
    5. Ink on paper (#248): each ink a paper skin draws with (`inks`, tool -> colour) is a mark on
       the panel, so >= 3:1 against it (WCAG 1.4.11, non-text contrast) -- except the
       highlighter, which is read THROUGH: the text must keep 4.5:1 on what the swipe leaves under
       it (#329). In ink that is `highlight_under(panel, ink, dark)`, the layer's own blend;
       `dark` is the variant's, from its `--paper` when its skin.css sets one, else the palette's
       ground (`dark=None`), never the composited panel's. `plain=True` reads the plain
       fallback's `INK_TINT` of the ink over the panel instead.
    6. Muted text on ground (#325): to_css(t)["--muted"] >= 4.5:1 on target_ground.
    7. The word on a state colour (#327): each to_css(t)["--on-<role>"] >= 4.5:1 on its role
       colour -- a chip's, a badge's and a rail glyph's word.
    8. A word in a state colour (#328): each `--<role>-text` >= 4.5:1 on target_ground and on each
       of `panels` -- the why line, "exit 2", "it asked you:", a clear chip's word. The tokens are
       the ones `to_css` chooses for the grounds judged here (the composited panel and `panels`),
       as the page is served them for every panel of its skins (`skins.panels_on`). The role
       colour itself stays for marks, at rule 2's 3:1.
    9. The pressed ground (#328): to_css(t)["--text"] >= 4.5:1 on to_css(t)["--select"], the word
       on a pressed control (the model picker's pill, the pressed tab, the pin). The palette is the
       only input: a project's accent paints only the pane's left edge. `--accent` on `--panel` or
       `--select` is not held: random rolls fall under 2.5:1 there, and a pressed control's ring is
       a second mark -- its word carries the state.
    10. Focus is never a state (#339): to_css(t)["--focus"] >= 3:1 on target_ground and on each of
       `panels`, and achromatic (HSV saturation <= 0.25) or >= 30 degrees of hue from every chromatic
       role -- the keyboard ring, the selected pane's ring and a pressed control's ring.
    """
    if t.name == "none" or t.ground is None or t.text is None:
        return

    target_ground = composited_panel or t.ground
    skin_ctx = f"skin '{skin}': " if skin else ""

    # Rule 1: text on ground
    c_txt = contrast_ratio(t.text, target_ground)
    if c_txt < 4.5:
        raise ThemeError(
            f"{skin_ctx}theme '{t.name}': text contrast {c_txt:.2f}:1 is below 4.5:1 floor",
            hint=f"{skin_ctx}text '{t.text}' on panel '{target_ground}'"
        )
    if c_txt > 19.0:
        raise ThemeError(
            f"{skin_ctx}theme '{t.name}': text contrast {c_txt:.2f}:1 exceeds 19:1 cap",
            hint=f"{skin_ctx}text '{t.text}' on ground '{target_ground}' is too harsh (pure white on pure black refused)"
        )

    # Rule 2: each status colour on ground
    for role, sc in t.status.items():
        c_st = contrast_ratio(sc, target_ground)
        if c_st < 3.0:
            raise ThemeError(
                f"{skin_ctx}theme '{t.name}': status '{role}' contrast {c_st:.2f}:1 is below 3:1 floor",
                hint=f"{skin_ctx}status.{role} '{sc}' on ground '{target_ground}'"
            )

    # Rule 3: status pairwise distinction
    if "ok" in t.status and "fail" in t.status:
        ok_c = t.status["ok"]
        fail_c = t.status["fail"]
        hd_ok_fail = hue_distance(ok_c, fail_c)
        if hd_ok_fail < 30.0:
            raise ThemeError(
                f"theme '{t.name}': status ok and fail hues are too close ({hd_ok_fail:.1f}°)",
                hint=f"ok '{ok_c}' vs fail '{fail_c}'"
            )

    # Rule 4: matrix & reds proof themes
    if t.name in ("matrix", "reds") and "fail" in t.status:
        hd = hue_distance(t.status["fail"], t.text)
        if hd < 35.0:
            raise ThemeError(
                f"theme '{t.name}': status fail is too close to text in hue ({hd:.1f}°)",
                hint=f"fail '{t.status['fail']}' vs text '{t.text}'"
            )

    # Rule 5: ink on paper
    for tool, ink in sorted((inks or {}).items()):
        if tool == "highlighter":
            if plain:
                tint = mix(target_ground, ink, INK_TINT)
            else:
                tint = highlight_under(target_ground, ink, is_dark(t.ground) if dark is None else dark)
            c_hl = contrast_ratio(t.text, tint)
            if c_hl < 4.5:
                raise ThemeError(
                    f"{skin_ctx}theme '{t.name}': text through the highlighter is {c_hl:.2f}:1, below 4.5:1",
                    hint=f"{skin_ctx}text '{t.text}' on highlighter '{ink}' over paper '{target_ground}'"
                )
            continue
        c_ink = contrast_ratio(ink, target_ground)
        if c_ink < 3.0:
            raise ThemeError(
                f"{skin_ctx}theme '{t.name}': ink '{tool}' contrast {c_ink:.2f}:1 is below 3:1 floor",
                hint=f"{skin_ctx}{tool} '{ink}' on paper '{target_ground}'"
            )

    # Rule 6: muted on ground (#325)
    c_muted = to_css(t).get("--muted")
    if c_muted:
        cr_muted = contrast_ratio(c_muted, target_ground)
        if cr_muted < 4.5:
            raise ThemeError(
                f"{skin_ctx}theme '{t.name}': muted contrast {cr_muted:.2f}:1 is below 4.5:1 floor",
                hint=f"{skin_ctx}muted '{c_muted}' on ground '{target_ground}'"
            )

    # Rule 7: the word on a state colour (#327)
    tokens = to_css(t)
    for role in ROLES:
        on = tokens.get("--on-" + role[2:])
        if not on:
            continue
        cr_on = contrast_ratio(on, tokens[role])
        if cr_on < 4.5:
            raise ThemeError(
                f"{skin_ctx}theme '{t.name}': the word on {role} is {cr_on:.2f}:1, below 4.5:1 floor",
                hint=f"{skin_ctx}--on-{role[2:]} '{on}' on {role} '{tokens[role]}'"
            )

    # Rule 8: a word in a state colour (#328)
    grounds = [target_ground] + [p for p in panels if p != target_ground]
    worded = to_css(t, panels=((composited_panel,) if composited_panel else ()) + tuple(panels))
    for role in ROLES:
        word = worded[role + "-text"]
        for g in grounds:
            cr_word = contrast_ratio(word, g)
            if cr_word < 4.5:
                raise ThemeError(
                    f"{skin_ctx}theme '{t.name}': the word in {role} is {cr_word:.2f}:1 on '{g}', "
                    f"below 4.5:1 floor",
                    hint=f"{skin_ctx}{role}-text '{word}' on '{g}' ({role} '{worded[role]}' moved "
                         f"toward text '{t.text}' reads on no step)"
                )

    # Rule 9: the pressed ground (#328)
    cr_pressed = contrast_ratio(tokens["--text"], tokens["--select"])
    if cr_pressed < 4.5:
        raise ThemeError(
            f"{skin_ctx}theme '{t.name}': text on the pressed ground is {cr_pressed:.2f}:1, below 4.5:1 floor",
            hint=f"{skin_ctx}text '{tokens['--text']}' on --select '{tokens['--select']}' "
                 f"(ground '{t.ground}' moved 18% toward accent '{tokens['--accent']}')"
        )

    # Rule 10: focus is never a state (#339)
    focus = worded["--focus"]
    roles = [worded[r] for r in ROLES]
    for g in grounds:
        cr_focus = contrast_ratio(focus, g)
        if cr_focus < 3.0:
            raise ThemeError(
                f"{skin_ctx}theme '{t.name}': the focus ring is {cr_focus:.2f}:1 on '{g}', below 3:1 floor",
                hint=f"{skin_ctx}--focus '{focus}' on '{g}' (the cursor '{t.cursor}', or text '{t.text}' made neutral)"
            )
    if not clear_of_states(focus, roles):
        near = min((r for r in ROLES if saturation(worded[r]) > ACHROMATIC),
                   key=lambda r: hue_distance(focus, worded[r]))
        raise ThemeError(
            f"{skin_ctx}theme '{t.name}': the focus ring is {hue_distance(focus, worded[near]):.1f} degrees "
            f"from {near}, under {STATE_HUE_GAP:.0f}",
            hint=f"{skin_ctx}--focus '{focus}' vs {near} '{worded[near]}': focus must never read as a state"
        )


# ---------- Built-in Theme Definitions ----------

def _make_ansi(ground: str, text: str, accent: str, light: bool = False) -> tuple[str, ...]:
    """Derive standard 16 ANSI slots from ground, text, and accent."""
    if light:
        return (
            ground, "#B3261E", "#2E7D4F", "#A8651B", "#2B6CB0", "#7B2CBF", "#0E8A8A", text,
            "#8C867A", "#D32F2F", "#388E3C", "#F57C00", "#1976D2", "#8E24AA", "#0097A7", "#1A1A1A"
        )
    return (
        ground, "#F85149", "#3FB950", "#D29922", "#58A6FF", "#BC8CFF", "#39C5CF", text,
        "#6E7681", "#FF7B72", "#56D364", "#E3B341", "#79C0FF", "#D2A8FF", "#56D4DD", "#FFFFFF"
    )


GREENS = Theme(
    name="greens",
    title="Greens",
    why="calm and go; a leaf-green desk",
    ground="#0B1F14",
    text="#CDE6D2",
    accent="#3FB950",
    cursor="#3FB950",
    ansi=_make_ansi("#0B1F14", "#CDE6D2", "#3FB950"),
    status={
        "ok": "#7EE787",
        "warn": "#D29922",
        "fail": "#F85149",
        "skip": "#8B949E",
        "info": "#58A6FF",
        "error": "#F85149",
    },
    light=False,
    layout="jandedobbeleer",
    muted="#8DA493",
)

REDS = Theme(
    name="reds",
    title="Reds",
    why="the loud desk; a red ground where errors cannot hide behind the ground",
    ground="#400000",
    text="#F2D9D9",
    accent="#FF5C5C",
    cursor="#FF5C5C",
    ansi=_make_ansi("#400000", "#F2D9D9", "#FF5C5C"),
    status={
        "ok": "#7EE787",
        "warn": "#FFA657",
        "fail": "#FFD166",  # Amber, not red! Red vanishes against red ground
        "skip": "#8B949E",
        "info": "#79C0FF",
        "error": "#FFD166",
    },
    light=False,
    layout="night-owl",
    muted="#B79191",
)

EYE_RELIEF = Theme(
    name="eye-relief",
    title="Eye Relief",
    why="for hour six; low blue, low glare, nothing pure white",
    ground="#2B2A27",
    text="#D6CDB8",
    accent="#C9A227",
    cursor="#C9A227",
    ansi=_make_ansi("#2B2A27", "#D6CDB8", "#C9A227"),
    status={
        "ok": "#68B87A",
        "warn": "#C9A227",
        "fail": "#D96B6B",
        "skip": "#8C867A",
        "info": "#6B9ED9",
        "error": "#D96B6B",
    },
    light=False,
    layout="atomic",
    muted="#B6AE9C",
)

EYE_RELIEF_DAY = Theme(
    name="eye-relief-day",
    title="Eye Relief Day",
    why="the same idea for a bright room",
    ground="#F2ECDC",
    text="#3B3A34",
    accent="#8A6D1F",
    cursor="#8A6D1F",
    ansi=_make_ansi("#F2ECDC", "#3B3A34", "#8A6D1F", light=True),
    status={
        "ok": "#2A733E",
        "warn": "#8A6D1F",
        "fail": "#A82D2D",
        "skip": "#736F66",
        "info": "#2A5F9E",
        "error": "#A82D2D",
    },
    light=True,
    layout="atomic",
    muted="#5C5A52",
)

NFL_BROWNS = Theme(
    name="nfl-browns",
    title="NFL Browns",
    why="Cleveland Browns: brown, orange, white",
    ground="#311D00",
    text="#F2E8D9",
    accent="#FF3C00",
    cursor="#FF3C00",
    ansi=_make_ansi("#311D00", "#F2E8D9", "#FF3C00"),
    status={
        "ok": "#56D364",
        "warn": "#E3B341",
        "fail": "#FF5C5C",
        "skip": "#8B949E",
        "info": "#58A6FF",
        "error": "#FF5C5C",
    },
    light=False,
    layout="jandedobbeleer",
    muted="#A79984",
)

NONE = Theme(
    name="none",
    title="None",
    why="the terminal exactly as you had it (the default)",
    ground=None,
    text=None,
    accent=None,
    cursor=None,
    ansi=(),
    status={},
    light=False,
    layout="jandedobbeleer"
)

# Five more palettes (#153)
DARK = Theme(
    name="dark",
    title="Dark",
    why="the neutral dark the page already had, now a name the terminal can share",
    ground="#14171A",
    text="#E3E7EA",
    accent="#58A6FF",
    cursor="#58A6FF",
    ansi=_make_ansi("#14171A", "#E3E7EA", "#58A6FF"),
    status={
        "ok": "#3FB950",
        "warn": "#D29922",
        "fail": "#F85149",
        "skip": "#8B949E",
        "info": "#58A6FF",
        "error": "#F85149",
    },
    light=False,
    layout="jandedobbeleer",
    muted="#A5A9AC",
)

VANTA_BLACK = Theme(
    name="vanta-black",
    title="Vanta Black",
    why="the true-black panel for OLED and pitch rooms",
    ground="#000000",
    text="#C8C8C8",
    accent="#E6E6E6",
    cursor="#E6E6E6",
    ansi=_make_ansi("#000000", "#C8C8C8", "#E6E6E6"),
    status={
        "ok": "#3FB950",
        "warn": "#D29922",
        "fail": "#F85149",
        "skip": "#808080",
        "info": "#58A6FF",
        "error": "#F85149",
    },
    light=False,
    layout="jandedobbeleer",
    muted="#929292",
)

MATRIX = Theme(
    name="matrix",
    title="Matrix",
    why="phosphor on black; the falling code screen",
    ground="#020A03",
    text="#3DF07A",
    accent="#00FF41",
    cursor="#00FF41",
    ansi=_make_ansi("#020A03", "#3DF07A", "#00FF41"),
    status={
        "ok": "#A8FFC0",
        "warn": "#E3B341",
        "fail": "#FF3B3B",  # Red, contrasting with green text
        "skip": "#4A9E66",
        "info": "#5EF0FF",
        "error": "#FF3B3B",
    },
    light=False,
    layout="jandedobbeleer",
    muted="#2CAD57",
)

BLUES = Theme(
    name="blues",
    title="Blues",
    why="deep ocean navy and slate",
    ground="#0B1B33",
    text="#D6E4F7",
    accent="#4DA3FF",
    cursor="#4DA3FF",
    ansi=_make_ansi("#0B1B33", "#D6E4F7", "#4DA3FF"),
    status={
        "ok": "#3FB950",
        "warn": "#E3B341",
        "fail": "#F85149",
        "skip": "#8B949E",
        "info": "#5EE1E6",  # Cyan so running never hides in navy ground
        "error": "#F85149",
    },
    light=False,
    layout="night-owl",
    muted="#9BAABE",
)

SAND = Theme(
    name="sand",
    title="Sand",
    why="warm desert solarized parchment",
    ground="#EFE6D2",
    text="#3A3126",
    accent="#B9631E",
    cursor="#B9631E",
    ansi=_make_ansi("#EFE6D2", "#3A3126", "#B9631E", light=True),
    status={
        "ok": "#2E7D4F",
        "warn": "#A8651B",
        "fail": "#B3261E",
        "skip": "#6B6051",
        "info": "#2B6CB0",
        "error": "#B3261E",
    },
    light=True,
    layout="atomic",
    muted="#60574A",
)


# Two greyed palettes for the weather genre (docs/themes.md §Genres): the sky's colour, not a
# saturated ground, so the rain and the cloud cover read as weather rather than as a tint.
SLATE = Theme(
    name="slate",
    title="Slate",
    why="a rainy afternoon: grey-blue, low saturation, the desk in the wet",
    ground="#252A30",
    text="#D3DAE3",
    accent="#8FB3D1",
    cursor="#8FB3D1",
    ansi=_make_ansi("#252A30", "#D3DAE3", "#8FB3D1"),
    status={
        "ok": "#5FC77A",
        "warn": "#D9A83A",
        "fail": "#F0645C",
        "skip": "#8E97A3",
        "info": "#6CB8E6",
        "error": "#F0645C",
    },
    light=False,
    layout="night-owl",
    muted="#B0B8C2",
)

OVERCAST = Theme(
    name="overcast",
    title="Overcast",
    why="a cloudy day: pale grey light with no sun in it",
    ground="#E6E9EC",
    text="#2E343B",
    accent="#4F6E8C",
    cursor="#4F6E8C",
    ansi=_make_ansi("#E6E9EC", "#2E343B", "#4F6E8C", light=True),
    status={
        "ok": "#2A733E",
        "warn": "#8A6320",
        "fail": "#B3261E",
        "skip": "#66707B",
        "info": "#2A5F9E",
        "error": "#B3261E",
    },
    light=True,
    layout="atomic",
    muted="#53585E",
)


BUILTINS: dict[str, Theme] = {
    "greens": GREENS,
    "reds": REDS,
    "eye-relief": EYE_RELIEF,
    "eye-relief-day": EYE_RELIEF_DAY,
    "nfl-browns": NFL_BROWNS,
    "none": NONE,
    "dark": DARK,
    "vanta-black": VANTA_BLACK,
    "matrix": MATRIX,
    "blues": BLUES,
    "sand": SAND,
    "slate": SLATE,
    "overcast": OVERCAST,
}


def random_theme(seed_val: Any = None) -> Theme:
    """Generate a stable, checked random theme from a seed (project name, day, or int)."""
    if seed_val is None:
        seed_int = 42
        seed_str = "42"
    elif isinstance(seed_val, str):
        seed_str = seed_val
        seed_int = int(hashlib.sha256(seed_val.encode("utf-8")).hexdigest()[:8], 16)
    else:
        seed_int = int(seed_val)
        seed_str = str(seed_val)

    rng = random.Random(seed_int)
    h_bg = rng.random()
    l_bg = 0.05 + rng.random() * 0.07
    s_bg = 0.2 + rng.random() * 0.4
    rgb_bg = colorsys.hls_to_rgb(h_bg, l_bg, s_bg)
    ground = rgb_to_hex(rgb_bg)

    l_txt = 0.82 + rng.random() * 0.06
    s_txt = 0.1 + rng.random() * 0.2
    h_txt = (h_bg + 0.5) % 1.0
    rgb_txt = colorsys.hls_to_rgb(h_txt, l_txt, s_txt)
    text = rgb_to_hex(rgb_txt)

    h_acc = (h_bg + 0.3 + rng.random() * 0.4) % 1.0
    rgb_acc = colorsys.hls_to_rgb(h_acc, 0.6, 0.7)
    accent = rgb_to_hex(rgb_acc)

    status = {
        "ok": "#3FB950",
        "warn": "#D29922",
        "fail": "#F85149",
        "skip": "#8B949E",
        "info": "#58A6FF",
        "error": "#F85149",
    }

    t = Theme(
        name="random",
        title=f"Random ({seed_str})",
        why=f"generated palette seeded from {seed_str}",
        ground=ground,
        text=text,
        accent=accent,
        cursor=accent,
        ansi=_make_ansi(ground, text, accent),
        status=status,
        light=False,
        layout="jandedobbeleer"
    )
    check(t)
    return t


def get(name: str, *, seed: Any = None) -> Theme:
    """Lookup a theme by name. Accepts 'random' with an optional seed."""
    key = name.strip().lower()
    if key == "random":
        return random_theme(seed)
    if key in BUILTINS:
        return BUILTINS[key]
    said = parse_name(key)
    if said and "flip" in said:
        return flip(get(said["flip"]))
    if said:
        return from_hue("#" + said["hex"], said["mode"], said["side"])
    raise ThemeError(f"unknown theme '{name}'",
                     hint=f"choose from: {', '.join(BUILTINS.keys())}, random, colors:<mode>:<hex>:<side>, flip:<name>")


# ---------- Generated palettes: any hue, three modes, either side (#621's follow-up) ----------
#
# The Colors genre (docs/themes.md §Colors): the operator names a colour, as a hex value or from a
# colour picker, and a whole palette is built from it -- in three modes, `matte` (muted, soft),
# `glass` (lit, for the frost) and `cyber` (high contrast) -- on the light or the dark side. The
# same engine gives every built-in palette its other side (`flip`), so every look has a light and
# a dark mode, and derives a paper skin's inks for a paper (`inks_on`). Nothing here is judged by
# eye: every generated palette passes `check`, and a test sweeps the hue circle in every mode on
# both sides to hold that. A generated palette has a NAME the terminal resolves on its own
# (`get`): `colors:<mode>:<hex6>:<side>` and `flip:<palette>`, so `theme.default` needs no other
# key in config.json and `ad-theme` follows the desk as it always did.

MODES = ("matte", "glass", "cyber")
SIDES = ("light", "dark")
COLORS_PREFIX = "colors:"
FLIP_PREFIX = "flip:"
HEX6 = re.compile(r"^#?([0-9A-Fa-f]{6})$")

#: The fixed status hues, in degrees: ok green, warn amber, fail red, info blue. `skip` is the
#: hue's own grey. The hue gap between ok and fail is rule 3's 30 degrees many times over, and a
#: chosen hue never moves them: a state colour carries meaning and never changes role.
STATUS_HUES = {"ok": 140.0, "warn": 42.0, "fail": 4.0, "info": 212.0}


def _hsl(h: float, s: float, l: float) -> str:
    """A hex colour from hue (degrees), saturation and lightness, all clamped."""
    r, g, b = colorsys.hls_to_rgb((h % 360.0) / 360.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return rgb_to_hex((r, g, b))


def _hsl_of(h: str) -> tuple[float, float, float]:
    """(hue degrees, saturation, lightness) of a hex colour, HSL."""
    hh, ll, ss = colorsys.rgb_to_hls(*hex_to_rgb(h))
    return hh * 360.0, ss, ll


def _fit(h: float, s: float, l: float, against, ratio: float, *, toward: float, cap: float = 19.0) -> str:
    """The colour at hue `h`, saturation `s` and lightness `l`, its lightness stepped `toward` 0 or
    1 until it reads at `ratio` on every colour in `against` (and under `cap` on each), by 0.01.
    Lightness alone moves: the hue is the operator's and the saturation the mode's. Answers the
    last step when none reads, which `check` then judges."""
    best = _hsl(h, s, l)
    for step in range(101):
        ll = l + (toward - l) * step / 100.0
        cand = _hsl(h, s, ll)
        rs = [contrast_ratio(cand, a) for a in against]
        if all(r >= ratio for r in rs):
            if all(r <= cap for r in rs):
                return cand
            best = cand
            if all(r > cap for r in rs):
                return best
        best = cand
    return best


#: Per mode, per side: the ground's saturation scale and lightness, the text's saturation scale,
#: lightness and floor, the accent's saturation and lightness, and the statuses' saturation.
_MODE = {
    "matte": {"dark": dict(gs=0.30, gl=0.13, ts=0.12, tl=0.86, acs=0.45, acl=0.66, ss=0.42),
              "light": dict(gs=0.30, gl=0.93, ts=0.12, tl=0.16, acs=0.45, acl=0.38, ss=0.48)},
    "glass": {"dark": dict(gs=0.55, gl=0.11, ts=0.10, tl=0.90, acs=0.85, acl=0.64, ss=0.62),
              "light": dict(gs=0.45, gl=0.95, ts=0.10, tl=0.13, acs=0.85, acl=0.40, ss=0.62)},
    "cyber": {"dark": dict(gs=0.70, gl=0.05, ts=0.80, tl=0.86, acs=1.00, acl=0.58, ss=0.95),
              "light": dict(gs=0.60, gl=0.97, ts=0.80, tl=0.14, acs=1.00, acl=0.40, ss=0.90)},
}


def from_hue(colour: str, mode: str = "matte", side: str = "dark", *, title: str | None = None) -> Theme:
    """A checked palette built from one colour (#621's follow-up, the Colors genre).

    `colour` is any hex value; its hue and saturation seed the ground, the text and the accent.
    `mode` is `matte` (muted, soft: a low-saturation ground, calm text), `glass` (lit: the ground
    keeps more of the colour, the accent glows, for the frost) or `cyber` (high contrast: a
    near-black or near-white ground with the colour saturated, the accent the complement, text
    near the 19:1 cap). `side` is `light` or `dark`. Every lightness is fitted (`_fit`) so
    `check` passes for any hue: the text at 4.5:1 and under 19:1 on the ground, the four fixed
    status hues at 3:1 on it, the accent at 3:1, and the cursor left to `to_css`'s neutral focus
    since a chosen hue could be a state's. The name is the palette's own address:
    `colors:<mode>:<HEX6>:<side>`, which `get` resolves."""
    m = HEX6.match(str(colour or "").strip())
    if not m:
        raise ThemeError(f"not a colour: {colour!r}", hint="six hex digits, as #3A7BD5")
    hex6 = m.group(1).upper()
    if mode not in MODES:
        raise ThemeError(f"unknown mode {mode!r}", hint=f"one of {', '.join(MODES)}")
    if side not in SIDES:
        raise ThemeError(f"unknown side {side!r}", hint="light or dark")
    h, s, _l = _hsl_of("#" + hex6)
    s = max(s, 0.08)                         # a grey seed still tints, faintly
    k = _MODE[mode][side]
    light = side == "light"
    ground = _hsl(h, s * k["gs"], k["gl"])
    if mode == "cyber":
        text_h, acc_h = h, (h + 180.0) % 360.0
    else:
        text_h, acc_h = h, h
    text = _fit(text_h, s * k["ts"], k["tl"], (ground,), 7.0, toward=1.0 if not light else 0.0)
    accent = _fit(acc_h, min(1.0, s * k["acs"] + (0.15 if mode != "matte" else 0.0)), k["acl"],
                  (ground,), 3.0, toward=1.0 if not light else 0.0)
    # Every status at 4.5:1 on the ground, not rule 2's 3:1: at 4.5 the ground itself is the word
    # on the state (rule 7) and the state is its own word in it (rule 8), on any hue.
    status = {}
    for role, sh in STATUS_HUES.items():
        base_l = (0.62 if not light else 0.33)
        status[role] = _fit(sh, k["ss"], base_l, (ground,), 4.5, toward=1.0 if not light else 0.0)
    status["skip"] = _fit(h, min(0.18, s * 0.3), 0.55 if not light else 0.40, (ground,), 4.5,
                          toward=1.0 if not light else 0.0)
    status["error"] = status["fail"]
    t = Theme(
        name=f"{COLORS_PREFIX}{mode}:{hex6}:{side}",
        title=title or f"Colors · {mode.title()} #{hex6} ({side})",
        why=f"built from #{hex6} in {mode} mode, the {side} side",
        ground=ground, text=text, accent=accent, cursor=None,
        ansi=_make_ansi(ground, text, accent, light=light),
        status=status, light=light, layout="night-owl" if not light else "atomic",
    )
    check(t)
    return t


def flip(t: Theme) -> Theme:
    """The other side of a built-in palette (#621's follow-up): every look has a light and a dark
    mode, and a palette that was drawn for one side is given the other by the same engine, seeded
    from its own accent (its hue) in `matte` mode. Named `flip:<palette>`, which `get` resolves, so
    `theme.default` can hold it for the terminal. `none` is its own flip (it follows the system)."""
    if t.name == "none" or not t.accent:
        return t
    if t.name.startswith(FLIP_PREFIX):
        return get(t.name[len(FLIP_PREFIX):])
    side = "dark" if t.light else "light"
    made = from_hue(t.accent, "matte", side, title=f"{t.title} ({side})")
    return Theme(name=FLIP_PREFIX + t.name, title=made.title, why=f"{t.title}'s {side} side, built from its accent",
                 ground=made.ground, text=made.text, accent=made.accent, cursor=made.cursor, ansi=made.ansi,
                 status=made.status, light=made.light, layout=made.layout, muted=made.muted)


def inks_on(t: Theme, paper: str, dark: bool | None = None, *, papers=()) -> dict[str, str]:
    """A paper skin's six inks for `paper` on the palette `t`, each holding rule 5 (#248, #329):
    pencil from the muted text, pen from the accent, red and the marker from `--human`, green from
    `--done`, each moved toward the text until it reads at 3:1 on the paper (and on every end in
    `papers`, when the panel is a pair); the highlighter the palette's `--waiting` moved toward the
    ground until the text keeps 4.5:1 through it on every end (`highlight_under`). What a generated
    look (Colors) draws its marks with, and a guide when a variant is added by hand."""
    css = to_css(t)
    dark = is_dark(paper) if dark is None else dark
    ends = [paper] + [e for e in papers if e != paper]
    def mark(colour: str) -> str:
        for step in range(51):
            cand = mix(colour, t.text, step / 50) if step else colour
            if all(contrast_ratio(cand, e) >= 3.0 for e in ends):
                return cand
        return t.text
    inks = {"pencil": mark(css["--muted"]), "pen": mark(css["--accent"]), "red": mark(css["--human"]),
            "green": mark(css["--done"]), "marker": mark(css["--human"])}
    hl = css["--waiting"]
    for step in range(101):
        cand = mix(hl, t.ground, step / 100) if step else hl
        if all(contrast_ratio(t.text, highlight_under(e, cand, dark)) >= 4.5 for e in ends):
            inks["highlighter"] = cand
            break
    else:
        inks["highlighter"] = t.ground
    return inks


def parse_name(name: str) -> dict | None:
    """What a generated palette's name says: `{"mode", "hex", "side"}` for `colors:...`,
    `{"flip": palette}` for `flip:...`, else None."""
    key = str(name or "").strip().lower()
    if key.startswith(COLORS_PREFIX):
        parts = key[len(COLORS_PREFIX):].split(":")
        if len(parts) == 3 and parts[0] in MODES and HEX6.match(parts[1]) and parts[2] in SIDES:
            return {"mode": parts[0], "hex": parts[1].lstrip("#").upper(), "side": parts[2]}
        return None
    if key.startswith(FLIP_PREFIX):
        return {"flip": key[len(FLIP_PREFIX):]}
    return None


def list_themes() -> list[Theme]:
    return list(BUILTINS.values())


# ---------- Escapes Rendering (#137) ----------

def escapes(t: Theme) -> str:
    """Render OSC 4/10/11/12 live recolour escapes."""
    if t.name == "none" or t.ground is None or t.text is None:
        return ""
    parts: list[str] = []
    # OSC 4: 16 ANSI slots
    for idx, col in enumerate(t.ansi[:16]):
        parts.append(f"\x1b]4;{idx};{col}\x1b\\")
    # OSC 10: text
    parts.append(f"\x1b]10;{t.text}\x1b\\")
    # OSC 11: ground
    parts.append(f"\x1b]11;{t.ground}\x1b\\")
    # OSC 12: cursor
    cursor = t.cursor or t.accent or t.text
    parts.append(f"\x1b]12;{cursor}\x1b\\")
    return "".join(parts)


def reset_escapes() -> str:
    """Reset dynamic colours: OSC 110, 111, 112."""
    return "\x1b]110\x1b\\\x1b]111\x1b\\\x1b]112\x1b\\"


def apply_conhost(t: Theme, persist: bool = False) -> dict[str, Any]:
    """Recolour a bare conhost/cmd.exe window via SetConsoleScreenBufferInfoEx."""
    if sys.platform != "win32":
        return {"ok": False, "mechanism": "none", "reason": "not Windows"}
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return {"ok": False, "mechanism": "none", "reason": "ctypes unavailable"}

    if t.name == "none" or not t.ansi:
        return {"ok": True, "mechanism": "conhost-noop"}

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    if handle in (0, -1, None):
        return {"ok": False, "mechanism": "none", "reason": "invalid stdout handle"}

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", wintypes.SHORT), ("Top", wintypes.SHORT),
                    ("Right", wintypes.SHORT), ("Bottom", wintypes.SHORT)]

    class COLORREF(wintypes.DWORD):
        pass

    class CONSOLE_SCREEN_BUFFER_INFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.ULONG),
            ("dwSize", COORD),
            ("dwCursorPosition", COORD),
            ("wAttributes", wintypes.WORD),
            ("srWindow", SMALL_RECT),
            ("dwMaximumWindowSize", COORD),
            ("wPopupAttributes", wintypes.WORD),
            ("bFullscreenSupported", wintypes.BOOL),
            ("ColorTable", COLORREF * 16),
        ]

    info = CONSOLE_SCREEN_BUFFER_INFOEX()
    info.cbSize = ctypes.sizeof(CONSOLE_SCREEN_BUFFER_INFOEX)
    if not kernel32.GetConsoleScreenBufferInfoEx(handle, ctypes.byref(info)):
        return {"ok": False, "mechanism": "none", "reason": "GetConsoleScreenBufferInfoEx failed"}

    def colref(hex_str: str) -> int:
        r, g, b = [int(x * 255) for x in hex_to_rgb(hex_str)]
        return r | (g << 8) | (b << 16)

    for i, col in enumerate(t.ansi[:16]):
        info.ColorTable[i] = COLORREF(colref(col))

    ok = kernel32.SetConsoleScreenBufferInfoEx(handle, ctypes.byref(info))
    if persist:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Console", 0, winreg.KEY_SET_VALUE) as key:
                for i, col in enumerate(t.ansi[:16]):
                    winreg.SetValueEx(key, f"ColorTable{i:02d}", 0, winreg.REG_DWORD, colref(col))
        except Exception:
            pass
    return {"ok": bool(ok), "mechanism": "conhost-api", "persisted": persist}


def apply(t: Theme, persist: bool = False) -> dict[str, Any]:
    """Apply theme to the live terminal (OSC escapes or Win32 conhost API)."""
    from . import console
    host = console.host()
    if host == "conhost":
        return apply_conhost(t, persist=persist)
    seq = escapes(t)
    if seq and sys.stdout:
        try:
            sys.stdout.write(seq)
            sys.stdout.flush()
        except Exception:
            pass
    return {"ok": True, "mechanism": f"osc-{host}"}
