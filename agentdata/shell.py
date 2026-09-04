"""Which shell is this command running under, and is it one we support?

Windows PowerShell 5.1 is out of support (epic #63): it is not tested, and every quirk the repo was
built around -- UTF-16 from `>`, a BOM from `Set-Content -Encoding utf8`, no `??` or ternary -- is
gone under PowerShell 7. A 5.1 session gets told to switch rather than silently getting behaviour
nobody checks.

Detection is a parent-process name walk, the pattern `agentdata/pbip/desktop.py` already uses, with
no new dependency: `psutil` when the optional extra happens to be installed, else one `Win32_Process`
query. Everything here degrades to `unknown` rather than raising -- a shell we cannot name is not a
reason for a command to fail.
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


def parent_names(run=None) -> list[str]:
    """Ancestor process names, nearest first. Empty when we cannot tell."""
    if os.name != "nt":
        return []
    return _parents_psutil() or _parents_wmi(run=run)


def detect(run=None, env: dict[str, str] | None = None) -> str:
    """`pwsh` | `windows-powershell` | `bash` | `cmd` | `zsh` | `posix` | `unknown`."""
    env = os.environ if env is None else env

    if os.name != "nt":
        shell = os.path.basename(env.get("SHELL", ""))
        return KNOWN.get(shell, "posix" if shell else "posix")

    # Git Bash sets these and is not visible as a parent when Python is launched through a shim
    if env.get("MSYSTEM") or env.get("SHELL", "").endswith(("bash", "bash.exe")):
        return "bash"

    for name in parent_names(run=run):
        got = KNOWN.get(name.lower())
        if got:
            return got
    return "unknown"


def check_row(run=None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """One `console/shell` row for `ad-doctor` and `ad-update --check`.

    Never `fail`: an unsupported shell is a thing to fix, not a broken install, and failing here
    would stop a user from seeing the rest of the report that tells them what else is wrong.
    """
    shell = detect(run=run, env=env)
    if shell in UNSUPPORTED:
        return {"name": "shell", "status": "warn", "detail": "Windows PowerShell 5.1 is not supported",
                "hint": SWITCH_HINT, "shell": shell}
    if shell == "unknown":
        return {"name": "shell", "status": "warn", "detail": "could not identify the parent shell",
                "hint": "run from pwsh 7, Git Bash or cmd; `ad-doctor --report` names what it found",
                "shell": shell}
    return {"name": "shell", "status": "ok", "detail": shell, "hint": "", "shell": shell}
