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


def to_css(t: Theme, project_accent: str | None = None) -> dict[str, str]:
    """Render a Theme as CSS custom properties according to the stated mapping.

    Tokens:
      --bg: ground
      --text: text
      --panel: ground moved 4% toward text
      --line: ground moved 15% toward text
      --select: ground moved 18% toward accent
      --muted: t.muted or derived at >= 4.6:1
      --accent: accent or project's own
      --focus: cursor
      --running: status.info
      --waiting: status.warn
      --human: status.fail
      --done: status.ok
      --idle: status.skip
      --on-running, --on-waiting, --on-human, --on-done, --on-idle: the word on that role colour,
        chosen by `on_role` (#327)
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
        "--focus": t.cursor,
        "--running": t.status.get("info", "#58A6FF"),
        "--waiting": t.status.get("warn", "#D29922"),
        "--human": t.status.get("fail", "#FF5C5C"),
        "--done": t.status.get("ok", "#3FB950"),
        "--idle": t.status.get("skip", "#8B949E"),
    }
    for role in ROLES:
        out["--on-" + role[2:]] = on_role(out[role], t.text, t.ground)
    return out


def css(t: Theme, project_accent: str | None = None) -> dict[str, str]:
    """Alias for to_css()."""
    return to_css(t, project_accent=project_accent)


#: How much of a highlighter's ink a highlighted line of text is read through -- the plain
#: fallback's tint (`static/ink/ink.js` PLAIN_TINT), and the check below. A multiplied swipe on
#: paper is lighter than this at its streaks and never darker, so the check is the worst case.
INK_TINT = 0.38


def check(t: Theme, composited_panel: str | None = None, skin: str | None = None,
          inks: dict[str, str] | None = None) -> None:
    """The theme invariant, computed, not judged by eye.

    1. text on ground >= 4.5:1 and <= 19:1 (pure white on pure black is refused).
    2. Each status colour on ground >= 3:1.
    3. Status pairwise distinction (ok, warn, fail).
    4. For reds and matrix, fail is not within stated hue distance of text.
    5. Ink on paper (#248): each ink a paper skin draws with (`inks`, tool -> colour) is a mark on
       the panel, so >= 3:1 against it (WCAG 1.4.11, non-text contrast) -- except the
       highlighter, which is read THROUGH: the text on its tint must keep 4.5:1. The ink layer
       brings the mechanism; the pairs arrive with the paper skins (#249-#253).
    6. Muted text on ground (#325): to_css(t)["--muted"] >= 4.5:1 on target_ground.
    7. The word on a state colour (#327): each to_css(t)["--on-<role>"] >= 4.5:1 on its role
       colour -- a chip's, a badge's and a rail glyph's word.
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
            tint = mix(target_ground, ink, INK_TINT)
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
    raise ThemeError(f"unknown theme '{name}'", hint=f"choose from: {', '.join(BUILTINS.keys())}, random")


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
