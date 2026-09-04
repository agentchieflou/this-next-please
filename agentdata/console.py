"""Console helpers. TOON goes to stdout; conversation (prompts, progress) goes to stderr.

Which *host* a command is running in decides three things the user notices: whether colour appears,
whether the status glyphs are `✓ ✗` or `+ x`, and — the one that matters — whether a password echoes
while they type it.

The host that forced this module to exist is a **standalone mintty** window (Git Bash outside
PyCharm or Windows Terminal). It is not a Windows console: Python's stdio are pipes, `isatty()` is
False, so colour switched itself off and `getpass` fell back to reading stdin, printing
*"Warning: Password input may be echoed"* and then echoing the keyring password `ad-setup` asks for.

Two things follow. mintty renders ANSI even though Python sees a pipe, so colour belongs on there --
but only when the handle really is an MSYS pty, or `> file` in the same shell would collect escapes
(`is_msys_pty`). And echo cannot be suppressed from inside that process: mintty's pty does the
echoing, and Windows Python reaches neither a console handle nor `/dev/tty`. So the password path
tries the two mechanisms that do work and, where neither exists, says so in one specific line
naming `winpty` rather than printing getpass's vague warning and echoing anyway.

Nothing here adds a dependency: `colorama`, `winpty` and `pyreadline` are all out, and the Win32
console API through `ctypes` is already the pattern in `color.py`.
"""
from __future__ import annotations
import getpass
import os
import sys

from . import color

# every value `host()` can return, so a test can enumerate them
HOSTS = (
    "windows-terminal",     # WT_SESSION -- VT and UTF-8, the good case
    "vscode",               # TERM_PROGRAM=vscode; renders ANSI without being a TTY
    "pycharm-terminal",     # the MINGW64 / pwsh tab: ConPTY, a real TTY
    "pycharm-run",          # the run window: PYCHARM_HOSTED=1, not a TTY, still renders ANSI
    "mintty",               # standalone Git Bash: pipes, not a console, but ANSI-capable
    "conpty",               # a modern Windows console handle
    "conhost",              # a legacy console window
    "tty",                  # an ordinary POSIX terminal
    "pipe",                 # a machine is reading
)
# hosts that render ANSI even though Python cannot see a TTY
ANSI_WITHOUT_TTY = ("mintty", "pycharm-run", "vscode")


def _has_console_handle() -> bool:
    """True when a Windows console is attached (GetConsoleMode answers on stdout or stderr)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        for handle_id in (-11, -12):
            handle = k32.GetStdHandle(handle_id)
            if handle in (0, -1, None):
                continue
            mode = wintypes.DWORD()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _isatty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001
        return False


def is_msys_pty(stream=None) -> bool:
    """True when this handle is an MSYS/Cygwin pty -- i.e. mintty is on the other end.

    This is the distinction the whole mintty fix turns on. To Windows Python, "mintty is my
    terminal" and "my output is redirected to a file or another program" both look like
    `isatty() == False`, so classifying on that alone would put ANSI escapes into a redirected file
    the moment colour was enabled for mintty.

    An MSYS pty is a named pipe whose name contains `msys-`/`cygwin-` and `-pty`, which
    `GetFileInformationByHandleEx(FileNameInfo)` reports. A plain `> file` or `| grep` does not
    match, so those stay uncoloured.
    """
    if os.name != "nt":
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())

        class FILE_NAME_INFO(ctypes.Structure):
            _fields_ = [("FileNameLength", wintypes.DWORD), ("FileName", ctypes.c_wchar * 512)]

        info = FILE_NAME_INFO()
        # 2 == FileNameInfo
        ok = ctypes.windll.kernel32.GetFileInformationByHandleEx(  # type: ignore[attr-defined]
            wintypes.HANDLE(handle), 2, ctypes.byref(info), ctypes.sizeof(info),
        )
        if not ok:
            return False
        name = (info.FileName or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return ("msys-" in name or "cygwin-" in name) and "-pty" in name


def host(env: dict[str, str] | None = None, stream=None, console_handle=None) -> str:
    """Classify the terminal host. `console_handle` is injectable so tests need no console."""
    env = os.environ if env is None else env
    stream = stream if stream is not None else sys.stdout
    tty = _isatty(stream)

    if env.get("WT_SESSION"):
        return "windows-terminal"
    if env.get("TERM_PROGRAM") == "vscode":
        return "vscode"
    if env.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        return "pycharm-terminal"
    if env.get("PYCHARM_HOSTED") == "1":
        return "pycharm-run"

    if os.name == "nt":
        # mintty: an MSYS pty on the other end of the handle. Checked by handle name rather than by
        # `MSYSTEM and not isatty`, which is equally true of `> file` inside the same shell.
        if env.get("MSYSTEM") and not tty and is_msys_pty(stream):
            return "mintty"
        has_console = _has_console_handle() if console_handle is None else console_handle
        if has_console:
            # ConPTY sets this for the session it hosts; a legacy window does not
            return "conpty" if (tty or env.get("WT_SESSION") or env.get("ConEmuANSI")) else "conhost"
        return "pipe"

    return "tty" if tty else "pipe"


def shell(env: dict[str, str] | None = None) -> str:
    """The parent shell. See `agentdata/shell.py`; re-exported so callers have one console module."""
    from . import shell as _shell
    return _shell.detect(env=env)


def renders_ansi(env: dict[str, str] | None = None, stream=None) -> bool:
    """True when this host shows ANSI, whether or not Python can see a TTY."""
    return host(env=env, stream=stream) in ANSI_WITHOUT_TTY


def code_page() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        return str(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return ""


def utf8_stdout() -> None:
    """Windows consoles default to cp1252 while TOON output contains → · ≤. Never raises.

    This is the *bytes* contract and it does not depend on the host: a redirected or piped stream is
    UTF-8 everywhere. What degrades per host is the human rendering (`ui.glyphs()`), not the file.
    """
    for stream in (sys.stdout, sys.stderr):
        rc = getattr(stream, "reconfigure", None)
        if rc is None:
            continue
        try:
            rc(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------ reading a secret


ECHO_RISK_HINT = (
    "this window cannot turn off echo for Python, so what you type would be visible. "
    "Run the command from Windows Terminal, PyCharm's terminal, or prefix it with `winpty` "
    "(shipped with Git for Windows): `winpty ad-setup --only sources`"
)


def _secret_via_console(prompt_text: str) -> str | None:
    """Read through the Windows console (msvcrt), which does not echo. None when there is none."""
    if os.name != "nt":
        return None
    try:
        import msvcrt
    except ImportError:
        return None
    if not _has_console_handle():
        return None
    try:
        sys.stderr.write(prompt_text)
        sys.stderr.flush()
        chars: list[str] = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stderr.write("\n")
                sys.stderr.flush()
                return "".join(chars)
            if ch == "\003":
                raise KeyboardInterrupt
            if ch == "\b":
                if chars:
                    chars.pop()
            elif ch == "\000" or ch == "\xe0":
                msvcrt.getwch()          # swallow the second half of a function key
            else:
                chars.append(ch)
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception:  # noqa: BLE001
        return None


def _secret_via_tty(prompt_text: str) -> str | None:
    """Read through the controlling terminal with echo disabled. None when there is none."""
    try:
        import termios
        import tty as _tty
    except ImportError:
        return None
    try:
        fd = os.open("/dev/tty", os.O_RDWR | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return None
    try:
        with open(fd, "r+", buffering=1, encoding="utf-8", errors="replace", closefd=True) as handle:
            old = termios.tcgetattr(fd)
            try:
                new = termios.tcgetattr(fd)
                new[3] &= ~termios.ECHO           # lflag
                termios.tcsetattr(fd, termios.TCSADRAIN, new)
                handle.write(prompt_text)
                handle.flush()
                answer = handle.readline()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                handle.write("\n")
                handle.flush()
        return answer.rstrip("\r\n")
    except Exception:  # noqa: BLE001
        return None


def _read_secret(prompt_text: str, env: dict[str, str] | None = None) -> str:
    """A password, read without echo wherever the host allows it.

    `getpass.getpass()` on a host where stdin is not a terminal prints
    "Warning: Password input may be echoed" and then does exactly that -- in standalone mintty that
    is the `ad-setup` keyring prompt putting a password into the scrollback. Two mechanisms actually
    suppress echo, and both are tried before that: the Windows console through `msvcrt`, and a
    controlling terminal through `termios`.

    Where neither exists, the honest thing is to say so in one specific line naming the fix, rather
    than to print getpass's vague warning and echo anyway. Windows Python inside a standalone mintty
    is that case: mintty's pty does the echoing, and nothing reachable from this process turns it
    off -- which is exactly what `winpty` is for.
    """
    for reader in (_secret_via_console, _secret_via_tty):
        answer = reader(prompt_text)
        if answer is not None:
            return answer

    eprint(color.paint(f"! {ECHO_RISK_HINT}", "yellow"))
    sys.stderr.write(prompt_text)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError("stdin closed")
    return line.rstrip("\r\n")


def prompt(text: str, default: str | None = None, secret: bool = False) -> str:
    """Ask on stderr, read from stdin. Empty answer -> default. Secrets never echo."""
    suffix = color.paint(f" [{default}]", "dim") if default not in (None, "") else ""
    text = color.paint(text, "cyan")
    if secret:
        ans = _read_secret(f"{text}{suffix}: ")
    else:
        sys.stderr.write(f"{text}{suffix}: ")
        sys.stderr.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError("stdin closed")
        ans = line.rstrip("\r\n")
    return ans if ans.strip() else (default or "")
