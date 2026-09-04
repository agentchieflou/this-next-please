"""Which shell is this command running under, and is it one we support?

Windows PowerShell 5.1 is out of support (epic #63): it is not tested, and every quirk the repo was
built around -- UTF-16 from `>`, a BOM from `Set-Content -Encoding utf8`, no `??` or ternary -- is
gone under PowerShell 7. A 5.1 session gets told to switch rather than silently getting behaviour
nobody checks.

Detection is a parent-process name walk with no new dependency, and it launches nothing: a Win32
process snapshot through `ctypes`, the pattern `agentdata/color.py` already uses for the console API.
That matters because `ad-update --check` is a dry run -- shelling out to PowerShell to ask which
shell we are in broke that contract, and is a slow way to answer a question the kernel already knows.
`psutil` is used when the optional extra happens to be installed, and the `Win32_Process` query
survives only as an explicitly opted-in last resort. Everything here degrades to `unknown` rather
than raising: a shell we cannot name is not a reason for a command to fail.
"""
from __future__ import annotations
import json
import os
import sys
from typing import Any

from . import proc

# parent process image name -> the shell we call it
KNOWN = {
    "pwsh.exe": "pwsh",
    "powershell.exe": "windows-powershell",
    "bash.exe": "bash",
    "sh.exe": "bash",
    "zsh": "zsh",
    "bash": "bash",
    "cmd.exe": "cmd",
    "pwsh": "pwsh",
}
UNSUPPORTED = {"windows-powershell"}
SWITCH_HINT = "PowerShell 7 required: install pwsh (winget install Microsoft.PowerShell) or use Git Bash"

_PS_PARENTS = (
    "$p = Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\"; "
    "$out = @(); "
    "while ($p) { $out += $p.Name; $p = Get-CimInstance Win32_Process -Filter \"ProcessId=$($p.ParentProcessId)\" "
    "-ErrorAction SilentlyContinue }; "
    "$out | ConvertTo-Json -Compress"
)


def _parents_toolhelp() -> list[str]:
    """The ancestor chain from the Win32 process snapshot -- no subprocess, no dependency.

    This is the path that matters: `ad-update --check` and `ad-doctor` both want to name the shell,
    and `--check` is a dry run that must not launch anything (tests/test_update.py enforces it).
    Shelling out to PowerShell to ask which shell we are in is also a slow way to answer a question
    the kernel already knows.
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        table: dict[int, tuple[int, str]] = {}
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        while True:
            table[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile)
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        k32.CloseHandle(snap)

    names, pid, seen = [], os.getpid(), set()
    for _ in range(8):
        row = table.get(pid)
        if not row or row[0] in seen:
            break
        seen.add(pid)
        pid = row[0]
        parent = table.get(pid)
        if not parent:
            break
        names.append(parent[1])
    return names


def _parents_psutil() -> list[str]:
    try:
        import psutil  # optional extra
    except Exception:
        return []
    try:
        names, p = [], psutil.Process(os.getpid())
        for _ in range(8):
            p = p.parent()
            if p is None:
                break
            names.append(p.name())
        return names
    except Exception:
        return []


def _parents_wmi(run=None) -> list[str]:
    runner = run or (lambda argv, timeout: proc.run(argv, timeout=timeout)[:3])
    try:
        rc, out, _err = runner(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_PARENTS], 15,
        )
    except Exception:
        return []
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, str):
        return [data]
    return [str(x) for x in data] if isinstance(data, list) else []


def parent_names(run=None, *, allow_subprocess: bool = False) -> list[str]:
    """Ancestor process names, nearest first. Empty when we cannot tell.

    The WMI query is a last resort and is off by default: a caller that must not launch anything
    (`ad-update --check`) gets the ctypes snapshot or nothing.
    """
    if os.name != "nt":
        return []
    if run is not None:                      # an injected runner is a test, and is always honoured
        return _parents_wmi(run=run)
    try:
        names = _parents_toolhelp()
    except Exception:  # noqa: BLE001
        names = []
    if names:
        return names
    names = _parents_psutil()
    if names or not allow_subprocess:
        return names
    return _parents_wmi()


def detect(run=None, env: dict[str, str] | None = None, *, allow_subprocess: bool = False) -> str:
    """`pwsh` | `windows-powershell` | `bash` | `cmd` | `zsh` | `posix` | `unknown`."""
    env = os.environ if env is None else env

    if os.name != "nt":
        shell = os.path.basename(env.get("SHELL", ""))
        return KNOWN.get(shell, "posix" if shell else "posix")

    # Git Bash sets these and is not visible as a parent when Python is launched through a shim
    if env.get("MSYSTEM") or env.get("SHELL", "").endswith(("bash", "bash.exe")):
        return "bash"

    for name in parent_names(run=run, allow_subprocess=allow_subprocess):
        got = KNOWN.get(name.lower())
        if got:
            return got
    return "unknown"


def check_row(run=None, env: dict[str, str] | None = None, *, allow_subprocess: bool = False) -> dict[str, Any]:
    """One `console/shell` row for `ad-doctor` and `ad-update --check`.

    Never `fail`: an unsupported shell is a thing to fix, not a broken install, and failing here
    would stop a user from seeing the rest of the report that tells them what else is wrong.
    """
    shell = detect(run=run, env=env, allow_subprocess=allow_subprocess)
    if shell in UNSUPPORTED:
        return {"name": "shell", "status": "warn", "detail": "Windows PowerShell 5.1 is not supported",
                "hint": SWITCH_HINT, "shell": shell}
    if shell == "unknown":
        return {"name": "shell", "status": "warn", "detail": "could not identify the parent shell",
                "hint": "run from pwsh 7, Git Bash or cmd; `ad-doctor --report` names what it found",
                "shell": shell}
    return {"name": "shell", "status": "ok", "detail": shell, "hint": "", "shell": shell}
