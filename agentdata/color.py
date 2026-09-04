"""ANSI colour for the human-facing CLI, off whenever a machine is reading.

A legacy Windows console does not enable VT sequences by default, so escapes would be printed literally: the
console API turns them on (no dependency, nothing to install) and colour stays off if that fails. Hosts that render
ANSI without Python seeing a TTY -- PyCharm's run window, the VS Code terminal, and a standalone mintty window whose
stdio are pipes to the pty -- are recognised through `console.host()`.

Only the 8 basic colours plus bold/dim are used: they are the ones every Windows console renders correctly on both a
light and a dark background. TOON data is coloured only in the status column of a table a human is reading — when
stdout is piped (Luna's terminal, a script), `enabled()` is False and every helper returns the text unchanged, so no
escape ever reaches an agent's context or a log file."""
from __future__ import annotations
import os
import re
import sys

CODES = {"reset": "0", "bold": "1", "dim": "2", "italic": "3", "underline": "4",
         "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36", "white": "37",
         "grey": "90", "bright_red": "91", "bright_green": "92", "bright_yellow": "93", "bright_cyan": "96"}
STATUS = {"ok": ("green",), "warn": ("yellow",), "fail": ("red", "bold"), "skip": ("grey",),
          "error": ("red", "bold"), "true": ("green",), "false": ("red", "bold")}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_enabled: bool | None = None


def _windows_vt() -> bool:
    """Ask the Windows console for VT processing. Returns False on any failure, including a redirected handle."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover - not Windows
        return False
    kernel32 = ctypes.windll.kernel32                      # type: ignore[attr-defined]
    ok = False
    for handle_id in (-11, -12):                           # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
        handle = kernel32.GetStdHandle(handle_id)
        if handle in (0, -1, None):
            continue
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            continue
        if kernel32.SetConsoleMode(handle, mode.value | 0x0004):   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            ok = True
    return ok


def _detect(stream) -> bool:
    choice = (os.environ.get("AGENTDATA_COLOR") or "auto").strip().lower()
    if choice in ("never", "0", "off", "no") or os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    forced = choice in ("always", "1", "on", "yes") or os.environ.get("FORCE_COLOR") not in (None, "", "0")
    if not forced:
        # Some hosts render ANSI without Python being able to see a TTY: PyCharm's run window, the
        # VS Code terminal, and a standalone mintty window, whose stdio are pipes to the pty.
        try:
            from . import console
            hosted = console.renders_ansi(stream=stream)
        except Exception:  # noqa: BLE001
            hosted = os.environ.get("PYCHARM_HOSTED") == "1" or os.environ.get("TERM_PROGRAM") == "vscode"
        try:
            if not (hosted or stream.isatty()):
                return False
        except Exception:  # noqa: BLE001
            return False
    if os.name == "nt" and os.environ.get("WT_SESSION") is None and os.environ.get("TERM_PROGRAM") != "vscode":
        # mintty is not a Windows console, so SetConsoleMode has nothing to enable -- and it renders
        # ANSI regardless. Asking the console API there is what silently turned colour off. Only a
        # real MSYS pty counts: `> file` in the same shell must stay uncoloured.
        try:
            from . import console
            if console.is_msys_pty(stream):
                return True
        except Exception:  # noqa: BLE001
            pass
        return _windows_vt() or forced
    return True


def enabled(stream=None) -> bool:
    """Cached decision for stdout. `reset_cache()` re-decides (tests, or after a stream swap)."""
    global _enabled
    if _enabled is None:
        _enabled = _detect(stream or sys.stdout)
    return _enabled


def reset_cache() -> None:
    global _enabled
    _enabled = None


def set_enabled(value: bool | None) -> None:
    """--color / --no-color. None returns to auto-detection."""
    global _enabled
    _enabled = value


def paint(text: str, *styles: str) -> str:
    if not text or not enabled() or not styles:
        return text
    codes = ";".join(CODES[s] for s in styles if s in CODES)
    return f"\x1b[{codes}m{text}\x1b[0m" if codes else text


def status(value: str) -> str:
    """Colour a check status / an ok flag by meaning."""
    return paint(value, *STATUS.get(str(value).strip().lower(), ()))


def strip(text: str) -> str:
    return ANSI_RE.sub("", text)
