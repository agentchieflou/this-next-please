"""Which Power BI Desktop window does the human mean? Windows already knows: the one on top.

The External Tools ribbon has exactly one payload nothing else supplies -- *this* document, the one
the human is looking at -- and buying that one answer costs a privileged write of
`<name>.pbitool.json` into `%CommonProgramFiles%\\Microsoft Shared\\Power BI Desktop\\External Tools`,
which on the reporter's machine is Administrators-only (epic #112). Everything else the ribbon hands
over (`%server%`, `%database%`) is already reachable from `C:\\Enforce` through dscmd and TE2.

`EnumWindows` answers the same question for free, and the reason is the whole trick: it walks
top-level windows **in Z-order**, so the highest visible `PBIDesktop.exe` window is the one the human
clicked last. The gesture is one they already made -- click the window, then run the command -- so
"which one" needs no ribbon button, no `RegisterHotKey` listener and no resident process. All three
of those were considered in #112's discovery rounds and withdrawn: a hotkey is a global hook by
another name.

Two implementation notes that are bugs if you get them wrong:

* **The callback must be held in a local.** `ctypes.WINFUNCTYPE(...)(_visit)` builds a thunk with no
  other reference to it; passed inline as an argument, CPython is free to collect it while
  `EnumWindows` is still calling into it, and the process dies inside user32 with no Python
  traceback. Binding it to a name that outlives the call is the fix.
* **A private `WinDLL` handle, not `ctypes.windll.user32`.** `windll` is a process-wide cache, so
  setting `argtypes` on it would rewrite the same function objects `desktop.capabilities` and any
  future `PrintWindow` caller see.

On anything that is not Windows -- this repo's CI, and the box most of this was written on -- there
is no user32 to call, so the same rows come back through the injected `Runner` that
`desktop.discover` already uses, which is what makes the fakes in `tests/` drive this at all. That
path reports the order the process table gave it, *not* Z-order; only the ctypes path can answer
"which one is on top", and only Windows runs it.
"""
from __future__ import annotations
import sys
from typing import Callable

Runner = Callable[[list[str], int], tuple[int, str, str]]

# Desktop's window title is "<document name> - Power BI Desktop"; the suffix is the whole test.
TITLE_SUFFIX = "Power BI Desktop"


def title_is_desktop(title: str | None) -> bool:
    """True only when the title *ends* in "Power BI Desktop".

    `in` is the tempting spelling and it is wrong: a browser tab reading
    "Power BI Desktop documentation - Google Chrome" contains the phrase, and handing its pid to
    `desktop.status()` produces a confident answer about the wrong process.
    """
    return bool(title) and str(title).strip().endswith(TITLE_SUFFIX)


def _enum_ctypes() -> list[tuple[int, str]]:
    """The real answer: visible top-level Desktop windows, highest in Z-order first."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)  # not windll: see module docstring
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    rows: list[tuple[int, str]] = []
    seen: set[int] = set()

    def _visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if not title_is_desktop(title):
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        value = int(pid.value)
        if value and value not in seen:
            seen.add(value)
            rows.append((value, title))
        return True

    callback = ENUMPROC(_visit)  # MUST outlive EnumWindows -- see module docstring
    user32.EnumWindows(callback, 0)
    return rows


def _from_runner(run: Runner | None) -> list[tuple[int, str]]:
    """The same rows through the process table, so the fakes drive this on a machine with no user32.

    Deliberately honest about what it cannot do: `Get-Process` has no notion of Z-order, so this
    returns the order the runner gave. It exists to keep the *shape* testable off Windows.
    """
    from . import desktop as DT  # deferred: desktop.windows_zorder wraps this module

    run = run or DT.default_run
    rows: list[tuple[int, str]] = []
    seen: set[int] = set()
    for item in DT._ps_json(run, DT.PBIDESKTOP_TITLES):
        pid = item.get("Id")
        title = item.get("MainWindowTitle")
        if pid is None or not title_is_desktop(title):
            continue
        try:
            value = int(pid)
        except (TypeError, ValueError):
            continue
        if value and value not in seen:
            seen.add(value)
            rows.append((value, str(title)))
    return rows


def desktop_windows(run: Runner | None = None) -> list[tuple[int, str]]:
    """Visible top-level Power BI Desktop windows as `(pid, title)`, index 0 = the one on top.

    Index 0 is the contract: `ad-pbip handoff --active` takes it and asks `desktop.status(pid)` for
    the port, which is the ribbon's job done with a gesture the human already made. One row per pid
    -- a second window for the same process would only give `status()` the same answer twice.

    Windows answers through `ctypes`; every other platform, and a Windows box whose user32 call
    fails, falls back to the injected `Runner`. An empty list means no Desktop window is open, which
    is a normal answer and not an error: the caller refuses with a hint, it does not raise here.
    """
    if sys.platform == "win32":
        try:
            return _enum_ctypes()
        except Exception:  # noqa: BLE001 - a user32 that will not answer is not a reason to fail
            pass
    return _from_runner(run)
