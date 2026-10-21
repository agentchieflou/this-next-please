"""The TNP wordmark and the two colours it is drawn in: teal into blue, left to right.

toil draws its name in yellow and orange; this is the overlay's own mark, so it reads as a different tool at a
glance. 24-bit colour where the terminal says it has it (Windows Terminal, VS Code, COLORTERM=truecolor), the
nearest xterm-256 colour otherwise, and plain blocks when colour is off (NO_COLOR, a pipe, --color never).
"""
from __future__ import annotations

import os

from .. import color

TEAL = (0, 201, 183)
BLUE = (37, 99, 235)
MUTED = (135, 150, 165)

WORDMARK = [
    "████████  ███    ██  ██████▄ ",
    "   ██     ████   ██  ██    ██",
    "   ██     ██ ██  ██  ██████▀ ",
    "   ██     ██  ██ ██  ██      ",
    "   ██     ██   ████  ██      ",
]
NAME = "this-next-please"


def truecolor() -> bool:
    return (os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit") or bool(os.environ.get("WT_SESSION"))
            or os.environ.get("TERM_PROGRAM", "").lower() in ("vscode", "iterm.app", "wezterm"))


def _code(rgb: tuple[int, int, int]) -> str:
    if truecolor():
        return "38;2;%d;%d;%d" % rgb
    r, g, b = (round(v / 255 * 5) for v in rgb)
    return f"38;5;{16 + 36 * r + 6 * g + b}"


def rgb(text: str, value: tuple[int, int, int], bold: bool = False) -> str:
    if not color.enabled() or not text:
        return text
    return f"\x1b[{'1;' if bold else ''}{_code(value)}m{text}\x1b[0m"


def mix(t: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * t) for a, b in zip(TEAL, BLUE))  # type: ignore[return-value]


def gradient(text: str, bold: bool = False) -> str:
    """`text` shaded teal -> blue by column; spaces carry no colour."""
    if not color.enabled():
        return text
    n = max(len(text) - 1, 1)
    return "".join(ch if ch == " " else rgb(ch, mix(i / n), bold) for i, ch in enumerate(text))


def wordmark() -> list[str]:
    width = max(len(line) for line in WORDMARK)
    return ["  " + gradient(line.ljust(width)).rstrip() for line in WORDMARK]


def accent(text: str) -> str:
    return rgb(text, TEAL, bold=True)


def blue(text: str) -> str:
    return rgb(text, BLUE, bold=True)


def muted(text: str) -> str:
    return rgb(text, MUTED)
