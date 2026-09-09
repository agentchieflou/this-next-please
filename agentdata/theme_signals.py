"""Theme attention signals: OSC 9;4 progress, OSC 2 tab titles, and terminal bell.

Zero escapes on piped stdout or unsupported hosts.
Supported hosts:
- windows-terminal: OSC 9;4 progress, OSC 2 tab titles, BEL / OSC 9 notifications.
- mintty (Git Bash): OSC 9;4 progress, OSC 2 titles, BEL.
- vscode: OSC 9;4 progress (xterm.js), OSC 2 titles, BEL.
- pycharm-terminal: OSC 2 titles, BEL.
- conhost: OSC 2 titles, Win32 SetConsoleTitle, BEL.
- pipe: All suppressed (empty string / no-op).
"""
from __future__ import annotations

import os
import sys
from typing import Any

from . import color
from . import console


# State codes for OSC 9;4
STATE_DONE = 0          # clear / normal
STATE_PROGRESS = 1      # normal progress (with percentage)
STATE_ERROR = 2         # error state (red indicator in tab/taskbar)
STATE_INDETERMINATE = 3 # busy / marquee
STATE_WARNING = 4       # warning / paused

STATE_MAP = {
    "done": STATE_DONE,
    "clear": STATE_DONE,
    "none": STATE_DONE,
    "0": STATE_DONE,
    0: STATE_DONE,
    "progress": STATE_PROGRESS,
    "normal": STATE_PROGRESS,
    "pct": STATE_PROGRESS,
    "1": STATE_PROGRESS,
    1: STATE_PROGRESS,
    "error": STATE_ERROR,
    "fail": STATE_ERROR,
    "failed": STATE_ERROR,
    "2": STATE_ERROR,
    2: STATE_ERROR,
    "indeterminate": STATE_INDETERMINATE,
    "busy": STATE_INDETERMINATE,
    "spin": STATE_INDETERMINATE,
    "3": STATE_INDETERMINATE,
    3: STATE_INDETERMINATE,
    "warning": STATE_WARNING,
    "warn": STATE_WARNING,
    "paused": STATE_WARNING,
    "4": STATE_WARNING,
    4: STATE_WARNING,
}


def supports_signals(host: str | None = None) -> bool:
    """Return whether current host supports OSC escape sequences."""
    h = host or console.host()
    if h == "pipe":
        return False
    if host is None and not color.enabled() and h in ("pipe", "unknown"):
        return False
    return True


def supports_progress(host: str | None = None) -> bool:
    """Return whether host supports OSC 9;4 progress bar."""
    h = host or console.host()
    if host is None and not color.enabled():
        return False
    return h in ("windows-terminal", "mintty", "vscode", "tty")


def progress(state: int | str = STATE_INDETERMINATE, pct: int | float | None = None,
             host: str | None = None) -> str:
    """Format OSC 9;4 progress escape sequence.

    State:
      0 = clear / done
      1 = normal progress (pct 0..100)
      2 = error
      3 = indeterminate
      4 = warning / paused
    """
    if not supports_progress(host):
        return ""

    st = STATE_MAP.get(state, STATE_INDETERMINATE)
    if st == STATE_DONE:
        return "\x1b]9;4;0\x1b\\"
    if st == STATE_PROGRESS:
        p = max(0, min(100, int(pct if pct is not None else 0)))
        return f"\x1b]9;4;1;{p}\x1b\\"
    if st == STATE_ERROR:
        if pct is not None:
            p = max(0, min(100, int(pct)))
            return f"\x1b]9;4;2;{p}\x1b\\"
        return "\x1b]9;4;2\x1b\\"
    if st == STATE_INDETERMINATE:
        return "\x1b]9;4;3\x1b\\"
    if st == STATE_WARNING:
        p = max(0, min(100, int(pct if pct is not None else 0)))
        return f"\x1b]9;4;4;{p}\x1b\\"
    return ""


def emit_progress(state: int | str = STATE_INDETERMINATE, pct: int | float | None = None,
                  stream: Any = None) -> None:
    """Write OSC 9;4 sequence to stderr (default) so stdout data pipes stay 100% pure."""
    seq = progress(state, pct)
    if not seq:
        return
    out = stream if stream is not None else sys.stderr
    try:
        out.write(seq)
        out.flush()
    except Exception:
        pass


def title(text: str, host: str | None = None) -> str:
    """Format OSC 2 tab/window title sequence."""
    if not supports_signals(host):
        return ""
    clean = "".join(ch for ch in text if ch >= " " or ch in "\t")
    return f"\x1b]2;{clean}\x1b\\"


def set_title(text: str, stream: Any = None) -> None:
    """Emit OSC 2 title sequence to stdout or Win32 console."""
    seq = title(text)
    if seq:
        out = stream if stream is not None else sys.stdout
        try:
            out.write(seq)
            out.flush()
        except Exception:
            pass
    elif sys.platform == "win32" and console.host() == "conhost":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(str(text))
        except Exception:
            pass


def bell(text: str | None = None, host: str | None = None) -> str:
    """Format BEL / OSC 9 notification sequence."""
    if not supports_signals(host):
        return ""
    parts = ["\x07"]
    if text:
        clean = "".join(ch for ch in text if ch >= " " or ch in "\t")
        parts.append(f"\x1b]9;{clean}\x1b\\")
    return "".join(parts)


def emit_bell(text: str | None = None, stream: Any = None) -> None:
    """Emit BEL / OSC 9 notification to stderr."""
    seq = bell(text)
    if not seq:
        return
    out = stream if stream is not None else sys.stderr
    try:
        out.write(seq)
        out.flush()
    except Exception:
        pass
