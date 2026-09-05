r"""Reading files other tools wrote, and writing ours safely on Windows.

**Reading** is deliberately tolerant. Files reach this project from Notepad (cp1252), from other
teams, from older scripts, and from Windows PowerShell 5.1, which wrote a UTF-8 BOM with
`Set-Content -Encoding utf8` / `Out-File` and UTF-16 LE with `>`. That tolerance is about where a
file came from, not about which shell you type in: under the supported shells -- pwsh 7, Git Bash,
cmd -- every ordinary write already produces UTF-8, and `docs/shells.md` §Files says so.

**Writing** is UTF-8 without BOM, LF, atomic. Three Windows-only hazards are handled here so no
caller has to think about them:

* a **locked target** (PyCharm, Power BI Desktop or an antivirus holding the file) makes
  `os.replace` raise `PermissionError`. We retry briefly, then write in place and say so, rather
  than failing a command outright or leaving a `.tmp` behind;
* a **path over 260 characters** -- easy under a deep `PycharmProjects` tree -- needs the `\\?\`
  prefix unless `LongPathsEnabled` is set;
* a **reserved device name** (`con`, `aux`, `nul`, `com1`) as a ticket or table fragment in an
  output filename cannot be created at all.
"""
from __future__ import annotations
import json
import locale
import os
import re
import threading
import time

BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))

# cmd.exe's `echo > f` writes the console's OEM code page, 437 on a US laptop, so `é` is one byte
# that is not UTF-8 and not cp1252's. It is the one shell whose default redirect is not UTF-8.
OEM_FALLBACKS = ("cp437", "cp850")

# Windows refuses these as a file name, with or without an extension
RESERVED_NAMES = {"con", "prn", "aux", "nul",
                  *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
LONG_PATH_LIMIT = 240        # below 260, with room for a `.tmp` suffix
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF = 0.1


def decode(raw: bytes) -> str:
    """BOM-sniffed decode; without a BOM: UTF-8, the console's preferred encoding, cp1252, OEM, latin-1."""
    for bom, enc in BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(enc) if enc != "utf-8-sig" else raw.decode(enc)
    if len(raw) >= 2 and raw[1:2] == b"\x00" and raw[0:1] != b"\x00":   # BOM-less UTF-16 LE (ASCII text)
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    tried = ["utf-8"]
    pref = locale.getpreferredencoding(False) or ""
    if pref and pref.lower().replace("-", "") not in ("utf8", "cp65001"):
        tried.append(pref)
    tried += ["cp1252", *OEM_FALLBACKS, "latin-1"]
    for enc in tried:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


# ------------------------------------------------------------------------------- Windows paths


def longpath(path: str) -> str:
    """The form the Win32 API accepts for a path over the 260-character limit.

    Only applied when it is needed and can help: the `\\\\?\\` prefix requires an absolute path with
    no `..`, and it must not be handed to anything that will print it back to a user.
    """
    if os.name != "nt" or len(path) < LONG_PATH_LIMIT or path.startswith("\\\\?\\"):
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\"):                      # a UNC share
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def long_paths_enabled() -> bool | None:
    """Whether Windows has the registry policy on. None when we cannot tell (or not Windows)."""
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            value, _kind = winreg.QueryValueEx(key, "LongPathsEnabled")
            return bool(value)
    except Exception:  # noqa: BLE001
        return None


_MSYS_DRIVE = re.compile(r"^/([A-Za-z])/")


def from_msys(path: str) -> str:
    """`/c/Users/x` -> `C:/Users/x`. Git Bash converts most *arguments* itself, but not a path that
    reached us through a config file, an AGENTS.md fact or an answers file, where no shell was
    involved."""
    if os.name != "nt" or not path:
        return path
    m = _MSYS_DRIVE.match(path)
    return f"{m.group(1).upper()}:/{path[3:]}" if m else path


def norm_path(path: str) -> str:
    """One canonical spelling for a path in output: forward slashes, MSYS drives resolved.

    This existed as `.replace("\\\\", "/")` in dozens of places, which is fine until one of them
    forgets and two `meta.path` values for the same file stop comparing equal. Idempotent, so it can
    be applied more than once without harm.
    """
    if not path:
        return path
    out = path.replace("\\", "/")
    out = from_msys(out)
    if len(out) > 1 and out[1] == ":":
        out = out[0].upper() + out[1:]
    return out


def safe_name(name: str) -> str:
    """An output filename Windows will actually accept.

    A ticket key or a table name lands in `.agent/out/<KEY>-<purpose>.tsv`, and `nul.tsv` cannot be
    created on Windows however hard you try -- the failure is an unhelpful OSError far from the
    cause.
    """
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in name)
    cleaned = cleaned.rstrip(" .") or "_"
    stem = cleaned.split(".", 1)[0].lower()
    if stem in RESERVED_NAMES:
        cleaned = f"{cleaned.split('.', 1)[0]}_" + (f".{cleaned.split('.', 1)[1]}" if "." in cleaned else "")
    return cleaned


def collides_case_insensitively(directory: str, name: str) -> str:
    """An existing file differing only in case, or "". Two of them cannot coexist on Windows."""
    try:
        entries = os.listdir(directory)
    except OSError:
        return ""
    lowered = name.lower()
    for entry in entries:
        if entry != name and entry.lower() == lowered:
            return entry
    return ""


# -------------------------------------------------------------------------------------- reading


def read_text(path: str) -> str:
    with open(longpath(path), "rb") as f:
        return decode(f.read()).lstrip("﻿")


def read_json(path: str, what: str = "file"):
    """JSON from any encoding another tool produced. Raises ValueError with the path on bad JSON."""
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as e:
        raise ValueError(f"{what} is not valid JSON: {path} ({e.msg}, line {e.lineno})") from None


# -------------------------------------------------------------------------------------- writing


class LockedTarget(RuntimeError):
    """The atomic replace could not happen because something else holds the file."""

    def __init__(self, path: str) -> None:
        super().__init__(f"{path} is held open by another program")
        self.path = path


def _replace_with_retry(tmp: str, path: str) -> str:
    """os.replace, retried briefly, then written in place. Returns "atomic" or "in-place".

    PyCharm reindexing `.agent/state.json`, Power BI Desktop holding a TMDL file, and antivirus
    scanning a freshly written file all produce a `PermissionError` that is gone a fraction of a
    second later. Failing the command there would be wrong; so would silently losing the write.
    """
    last: Exception | None = None
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(longpath(tmp), longpath(path))
            return "atomic"
        except PermissionError as e:
            last = e
            time.sleep(REPLACE_BACKOFF * (attempt + 1))
        except OSError as e:
            last = e
            break

    # last resort: overwrite in place. Not atomic, but the content reaches the file.
    try:
        with open(longpath(tmp), "rb") as src:
            payload = src.read()
        with open(longpath(path), "wb") as dst:
            dst.write(payload)
        return "in-place"
    except OSError:
        raise LockedTarget(path) from last
    finally:
        # never leave a .tmp behind, whichever way this went
        try:
            os.remove(longpath(tmp))
        except OSError:
            pass


def write_text(path: str, text: str, *, report: dict | None = None) -> str:
    """UTF-8 without BOM, LF, atomic where the OS allows it. Returns the path with forward slashes.

    `report`, when given, receives `{"how": "atomic"|"in-place"}` so a caller that wants to warn
    about a locked file can, without every caller having to care.
    """
    d = os.path.dirname(path)
    if d:
        os.makedirs(longpath(d), exist_ok=True)
    # The scratch name is per writer, not per path. Two processes writing the same file at once --
    # `ad-state` in an agent and `ad-fleet serve` refreshing the same cursor, say -- both wrote
    # `<path>.tmp`, and then one renamed it away while the other was still holding it: a
    # FileNotFoundError on Linux and a PermissionError on Windows, from code that looked atomic.
    # The rename itself is still the atomic step; only the staging file needed to be unshared.
    tmp = f"{path}.{os.getpid()}.{threading.get_ident():x}.tmp"
    with open(longpath(tmp), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    how = _replace_with_retry(tmp, path)
    if report is not None:
        report["how"] = how
    return path.replace("\\", "/")


def write_json(path: str, data, indent: int = 2, *, report: dict | None = None) -> str:
    return write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n", report=report)
