"""Typing into the console the fleet opened (#190).

`send` is another `copilot -p <message> --resume <session>` process. For a session already running in
a console that would be a second agent in one working tree, so it is refused -- and the tile's reply
box, for a console, would be a box that does nothing. What a console *does* accept is input records
in its input buffer, from any process the Windows console API lets attach: `AttachConsole(pid)`,
`WriteConsoleInputW(<the text as key events, then Enter>)`, `FreeConsole()`. The package already
speaks to the Win32 console through `ctypes` -- `theme.apply_conhost` recolours a bare `cmd.exe` with
`SetConsoleScreenBufferInfoEx` -- so this is three more calls behind one function, not a new kind of
dependency. `pywin32` and `winpty` stay banned (`tests/test_console_host.py`).

Three things this does not do, each of them the operator's:

* **It never sends a Ctrl-C.** `GenerateConsoleCtrlEvent` is called by nothing in this package, and a
  test greps for it. Interrupting a session a person is watching is theirs to decide.
* **It never answers a prompt.** What is typed is what the operator typed on the tile; a `y/n` in the
  console is answered in the console, and the tile offers to bring that window to the front.
* **It never closes the window.** `stop` refuses a console for the same reason.

The text is written as one line followed by Enter. The console echoes it, so the operator sees
exactly what the tile sent, and Copilot writes it into the session's own file as the user turn the
tile then draws (#188). There is no second channel to keep in step -- which is the whole epic.
"""
from __future__ import annotations
import os

# A process has one console at a time, and attaching is a process-wide act. That is why this runs in
# a short-lived helper (`ad-fleet say-into`) rather than in `ad-fleet serve`: the server may have a
# console of its own, and two tiles replying at once would fight over the one attachment.
KEY_EVENT = 1
VK_RETURN = 0x0D
STILL_A_CONSOLE = 0x00000005              # ERROR_ACCESS_DENIED: attached, but not to this one
ATTACH_LOST = 0x00000006                  # ERROR_INVALID_HANDLE: the window went while we typed


class ConsoleError(Exception):
    """A refusal in the CLI's words, with a `code` and the Win32 number behind it."""

    def __init__(self, msg: str, hint: str = "", *, code: str = "", win32: int = 0):
        super().__init__(msg)
        self.msg, self.hint, self.code, self.win32 = msg, hint, code, int(win32 or 0)


def _unsupported() -> ConsoleError:
    return ConsoleError(
        "typing into a console is a Windows thing on this machine",
        "the console is for the laptop. On POSIX, type in the terminal the fleet opened",
        code="unsupported_host")


def _attach(pid: int):
    """Attach this process to `pid`'s console and hand back kernel32 and the input handle.

    `CONIN$` and not `GetStdHandle(STD_INPUT_HANDLE)`: this helper is spawned with its stdio
    redirected so the caller can read its TOON, and `AttachConsole` does not re-point handles that
    were redirected. `GetStdHandle` would return the pipe, and the line would be written into
    nothing at all -- silently, which is the failure mode this whole epic exists to remove.
    """
    import ctypes
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.AttachConsole.argtypes = [w.DWORD]
    k.AttachConsole.restype = w.BOOL
    k.FreeConsole()                       # a console of our own would refuse the attach
    ctypes.set_last_error(0)
    if not k.AttachConsole(int(pid)):
        error = ctypes.get_last_error()
        raise ConsoleError(
            f"could not attach to the console of pid {pid} (win32 {error})",
            "that window may have closed, or it is not a console this account owns. "
            "`ad-fleet status` says what the fleet still thinks is running",
            code="console_unreachable", win32=error)
    handle = k.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    if handle == -1 or handle == 0xFFFFFFFFFFFFFFFF:
        error = ctypes.get_last_error()
        k.FreeConsole()
        raise ConsoleError(f"the console of pid {pid} took the attach but not the handle "
                           f"(win32 {error})",
                           "type in that window; `ad-fleet status` says what is running",
                           code="console_unreachable", win32=error)
    return k, handle


def _records(text: str):
    """`text` and then Enter, as key-down/key-up pairs. One record per half-press, the way a
    keyboard delivers them: a console reading with `ReadConsoleInput` sees both."""
    import ctypes
    from ctypes import wintypes as w

    class _Char(ctypes.Union):
        _fields_ = [("UnicodeChar", w.WCHAR), ("AsciiChar", ctypes.c_char)]

    class _Key(ctypes.Structure):
        _fields_ = [("bKeyDown", w.BOOL), ("wRepeatCount", w.WORD), ("wVirtualKeyCode", w.WORD),
                    ("wVirtualScanCode", w.WORD), ("uChar", _Char), ("dwControlKeyState", w.DWORD)]

    class _Event(ctypes.Union):
        _fields_ = [("KeyEvent", _Key)]

    class _Record(ctypes.Structure):
        _fields_ = [("EventType", w.WORD), ("Event", _Event)]

    pairs = [(ch, 0) for ch in text] + [("\r", VK_RETURN)]
    buffer = (_Record * (len(pairs) * 2))()
    at = 0
    for ch, key in pairs:
        for down in (1, 0):
            buffer[at].EventType = KEY_EVENT
            buffer[at].Event.KeyEvent.bKeyDown = down
            buffer[at].Event.KeyEvent.wRepeatCount = 1
            buffer[at].Event.KeyEvent.wVirtualKeyCode = key
            buffer[at].Event.KeyEvent.wVirtualScanCode = 0
            buffer[at].Event.KeyEvent.uChar.UnicodeChar = ch
            buffer[at].Event.KeyEvent.dwControlKeyState = 0
            at += 1
    return buffer, len(buffer)


def one_line(text: str) -> str:
    """The one line that will be typed. A reply with newlines in it would be several commands to a
    console, and the second one would run against whatever the first left behind."""
    line = " ".join(str(text or "").splitlines()).strip()
    if not line:
        raise ConsoleError("nothing to say", "type a message first", code="empty_message")
    return line


def say_into(pid: int, text: str) -> dict:
    """Type `text` and Enter into the console of `pid`. Windows only; every failure is a refusal."""
    line = one_line(text)
    if os.name != "nt":
        raise _unsupported()
    import ctypes
    from ctypes import wintypes as w

    k, handle = _attach(pid)
    try:
        buffer, count = _records(line)
        written = w.DWORD(0)
        ctypes.set_last_error(0)
        ok = k.WriteConsoleInputW(ctypes.c_void_p(handle), ctypes.byref(buffer),
                                  w.DWORD(count), ctypes.byref(written))
        error = ctypes.get_last_error()
    finally:
        k.CloseHandle(ctypes.c_void_p(handle))
        k.FreeConsole()
    if not ok or written.value != count:
        raise ConsoleError(
            f"the console of pid {pid} took {written.value} of {count} key events (win32 {error})",
            "type in that window instead; the tile will show what the session writes",
            code="console_unreachable", win32=error)
    return {"pid": int(pid), "echoed": line, "events": count}


def focus_console(pid: int) -> dict:
    """Bring `pid`'s console window to the front.

    A window the operator cannot find is the #133 tab shuffle again, in reverse: the fleet opened
    it, so the fleet can say where it went. Under Windows Terminal the console window belongs to the
    terminal rather than to the session (runbook row C4); when this returns nothing to raise, the
    refusal says so rather than pretending the window is now in front.
    """
    if os.name != "nt":
        raise _unsupported()
    import ctypes

    k, handle = _attach(pid)
    try:
        k.CloseHandle(ctypes.c_void_p(handle))
        window = k.GetConsoleWindow()
        if not window:
            raise ConsoleError(f"the console of pid {pid} has no window to raise",
                               "under Windows Terminal the window belongs to the terminal; "
                               "find that tab, or run the console with `fleet.console.host: cmd`",
                               code="console_unreachable")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow(ctypes.c_void_p(window), 9)          # SW_RESTORE, in case it is minimised
        ctypes.set_last_error(0)
        raised = user32.SetForegroundWindow(ctypes.c_void_p(window))
        error = ctypes.get_last_error()
    finally:
        k.FreeConsole()
    if not raised:
        raise ConsoleError(f"Windows would not bring pid {pid}'s console to the front "
                           f"(win32 {error})",
                           "click its window in the task bar; Windows only lets the foreground "
                           "application hand focus away",
                           code="console_unreachable", win32=error)
    return {"pid": int(pid), "focused": True}
