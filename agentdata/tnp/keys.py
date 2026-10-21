"""One key press, without Enter: termios on Linux/macOS, msvcrt on Windows.

Named keys come back as words: up, down, left, right, home, end, pgup, pgdn, enter, esc, backspace, tab, space,
ctrl-u. Anything else comes back as the character typed, case kept, so a text field takes `TDPROD1` as typed and a
pasted JDBC URL arrives one character at a time. Menus decide for themselves what `q`, `j` and `k` mean; a text
field must be able to type them.
"""
from __future__ import annotations

import contextlib
import os
import sys

_HELD: list = []                 # the saved terminal mode while `held()` is active (posix)

_ESC = {"[A": "up", "[B": "down", "[C": "right", "[D": "left", "OA": "up", "OB": "down", "OC": "right",
        "OD": "left", "[H": "home", "[F": "end", "OH": "home", "OF": "end", "[1~": "home", "[4~": "end",
        "[5~": "pgup", "[6~": "pgdn", "[3~": "delete"}
_WIN = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end", "I": "pgup", "Q": "pgdn",
        "S": "delete"}


def name(ch: str) -> str:
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\x08", "\x7f"):
        return "backspace"
    if ch == "\t":
        return "tab"
    if ch == " ":
        return "space"
    if ch == "\x15":
        return "ctrl-u"
    if ch == "\x1b":
        return "esc"
    return ch


@contextlib.contextmanager
def held():
    """Keys one at a time, unechoed, for the whole session: a key pressed while a screen is still drawing is
    queued, not echoed onto it. Ctrl-C still interrupts. `released()` hands the terminal back for a while."""
    if os.name == "nt" or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        _HELD.append(old)
        yield
    finally:
        if _HELD:
            _HELD.pop()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


@contextlib.contextmanager
def released():
    """The terminal as a shell has it (echo, line editing), while a command runs or a line is read."""
    if os.name == "nt" or not _HELD or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    termios.tcsetattr(fd, termios.TCSADRAIN, _HELD[-1])
    try:
        yield
    finally:
        tty.setcbreak(fd)


def _read_posix(fd: int) -> str:
    import select
    raw = os.read(fd, 1)
    if raw == b"\x1b":
        seq = b""
        while len(seq) < 3 and select.select([fd], [], [], 0.03)[0]:
            seq += os.read(fd, 1)
            if seq[-1:].isalpha() or seq[-1:] == b"~":
                break
        return _ESC.get(seq.decode(errors="ignore"), "esc") if seq else "esc"
    if raw and raw[0] >= 0xC0:                       # the rest of one UTF-8 character
        need = 1 if raw[0] < 0xE0 else 2 if raw[0] < 0xF0 else 3
        raw += os.read(fd, need)
    return name(raw.decode(errors="ignore"))


def read_key() -> str:
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return _WIN.get(msvcrt.getwch(), "")
        return name(ch)
    import termios
    import tty
    fd = sys.stdin.fileno()
    if _HELD:
        return _read_posix(fd)
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return _read_posix(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
