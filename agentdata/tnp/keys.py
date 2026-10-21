"""One key press, without Enter: arrows, Enter, digits, letters. termios on Linux/macOS, msvcrt on Windows.

Only the menus read keys this way; every question a step asks is an ordinary line prompt, so the terminal is back
in its normal mode (echo, line editing, paste) before anything is typed.
"""
from __future__ import annotations

import os
import sys

_ESC = {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "OA": "up", "OB": "down", "OC": "right", "OD": "left"}
_WIN = {"H": "up", "P": "down", "K": "left", "M": "right"}


def _name(ch: str) -> str:
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\x08", "\x7f"):
        return "back"
    return {"k": "up", "j": "down"}.get(ch.lower(), ch.lower())


def read_key() -> str:
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return _WIN.get(msvcrt.getwch(), "")
        return "esc" if ch == "\x1b" else _name(ch)
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch == "\x1b":
            if select.select([fd], [], [], 0.05)[0]:
                return _ESC.get(os.read(fd, 2).decode(errors="ignore"), "esc")
            return "esc"
        return _name(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
