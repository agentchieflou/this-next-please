"""Console helpers. TOON goes to stdout; conversation (prompts, progress) goes to stderr."""
from __future__ import annotations
import getpass
import sys


def utf8_stdout() -> None:
    """Windows consoles default to cp1252 while TOON output contains → · ≤. Never raises."""
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


def prompt(text: str, default: str | None = None, secret: bool = False) -> str:
    """Ask on stderr, read from stdin. Empty answer -> default. Secrets never echo."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    if secret:
        ans = getpass.getpass(f"{text}{suffix}: ")
    else:
        sys.stderr.write(f"{text}{suffix}: ")
        sys.stderr.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError("stdin closed")
        ans = line.rstrip("\r\n")
    return ans if ans.strip() else (default or "")
