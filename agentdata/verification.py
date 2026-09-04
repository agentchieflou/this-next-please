"""Machine-readable evidence for the laptop verification suite.

`docs/windows-verification.md` used to end every section with "paste results back", and what came
back was a photograph of a terminal. A photograph cannot be diffed, searched, or attached to a
regression test. Every laptop step now appends a TOON record here instead, and the file is what goes
into the issue.

Nothing secret can reach it by construction: only `ad-*` stdout is captured, and that never contains
a credential -- passwords live in keyring and tokens in pncli's own config, neither of which any
`ad-*` command prints.
"""
from __future__ import annotations
import os
import platform
import shutil
import sys
import time
from datetime import datetime
from typing import Any

from . import proc
from . import textio
from . import toon

ENV_FLAG = "AGENTDATA_LAPTOP"
OUT_DIR = os.path.join(".agent", "out")


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def path_for(root: str = ".", stamp: str | None = None) -> str:
    stamp = stamp or datetime.now().strftime("%Y%m%dT%H%M%S")
    return os.path.join(root, OUT_DIR, f"verification-{stamp}.toon")


class Recorder:
    """Appends one record per step, and an environment bundle at the top."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.records: list[dict[str, Any]] = []
        self.started = time.time()

    def environment(self) -> dict[str, Any]:
        return environment_bundle()

    def step(self, section: str, step: str, command: str, exit_code: int,
             detail: str = "", seconds: float = 0.0, **paste: Any) -> None:
        row = {
            "section": section,
            "step": step,
            "command": command,
            "exit_code": exit_code,
            "seconds": round(seconds, 2),
            "detail": detail[:400],
        }
        row.update({k: v for k, v in paste.items() if v is not None})
        self.records.append(row)

    def write(self) -> str:
        passed = sum(1 for r in self.records if r["exit_code"] == 0)
        payload = {
            "meta": {
                "ok": passed == len(self.records),
                "source": "laptop verification",
                "steps": len(self.records),
                "passed": passed,
                "failed": len(self.records) - passed,
                "seconds": round(time.time() - self.started, 1),
                "generated": datetime.now().isoformat(timespec="seconds"),
            },
            "environment": self.environment(),
            "steps": self.records,
        }
        return textio.write_text(self.path, toon.encode(payload) + "\n")


# ------------------------------------------------------------------------- the environment bundle


def _version_of(exe: str, *args: str) -> str:
    found = shutil.which(exe)
    if not found:
        return ""
    try:
        rc, out, err, _el = proc.run([found, *(args or ("--version",))], timeout=20)
    except Exception:  # noqa: BLE001
        return ""
    text = (out or err or "").strip().splitlines()
    return text[0][:120] if rc == 0 and text else ""


def default_shell_settings() -> list[dict[str, str]]:
    """Which shell each IDE opens by default, and whether it is one we support.

    A laptop can have pwsh installed and still get a Windows PowerShell 5.1 tab, because the IDE
    remembers an old default. That is invisible until something behaves oddly, so it is reported.
    """
    home = os.path.expanduser("~")
    candidates = [
        ("PyCharm", os.path.join(home, "AppData", "Roaming", "JetBrains"), "terminal.xml", "shellPath"),
        ("Windows Terminal",
         os.path.join(home, "AppData", "Local", "Packages"), "settings.json", "defaultProfile"),
        ("VS Code", os.path.join(home, "AppData", "Roaming", "Code", "User"), "settings.json",
         "terminal.integrated.defaultProfile.windows"),
    ]
    rows: list[dict[str, str]] = []
    for name, base, filename, key in candidates:
        found = ""
        if os.path.isdir(base):
            for dirpath, _dirs, files in os.walk(base):
                if filename in files:
                    try:
                        text = textio.read_text(os.path.join(dirpath, filename))
                    except Exception:  # noqa: BLE001
                        continue
                    if key in text:
                        snippet = text.split(key, 1)[1][:120].replace("\n", " ")
                        found = snippet.strip(' ":=>{},')
                        break
                if dirpath.count(os.sep) - base.count(os.sep) > 3:
                    continue
        status = "ok"
        if found and "windowspowershell" in found.lower().replace(" ", ""):
            status = "warn"
        elif not found:
            status = "unknown"
        rows.append({"app": name, "default_shell": found or "not found", "status": status})
    return rows


def pythons() -> list[dict[str, Any]]:
    """Every python a shell would find, flagged against the floor and the App Execution Alias trap.

    `python.exe` under `WindowsApps` is Microsoft Store's stub: it opens the Store rather than
    running anything, and it sits early on PATH by default.
    """
    from . import update

    rows = []
    for row in update.pythons_on_path():
        row = dict(row)
        row["store_alias"] = "windowsapps" in row["path"].lower()
        rows.append(row)
    return rows


def environment_bundle() -> dict[str, Any]:
    from . import console as CON
    from . import shell as SH
    from . import update

    powershell_51 = shutil.which("powershell")
    bundle: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()} build {platform.version()}",
        "python": f"{platform.python_version()} ({sys.executable.replace(chr(92), '/')})",
        "shell": SH.detect(),
        "host": CON.host(),
        "code_page": CON.code_page(),
        "pathext": os.environ.get("PATHEXT", ""),
        "autocrlf": _git_config("core.autocrlf"),
        "long_paths_enabled": textio.long_paths_enabled(),
        "shells": {
            "bash": _version_of("bash"),
            "pwsh": _version_of("pwsh"),
            "windows-powershell": ("installed, unsupported" if powershell_51 else ""),
        },
        "tools": {name: (shutil.which(name) or "") for name in
                  ("pip", "gh", "az", "pncli", "node", "git", "ad-doctor")},
        "pythons": pythons(),
        "installs": update.installed_distributions(),
        "default_shells": default_shell_settings(),
    }
    return bundle


def _git_config(key: str) -> str:
    try:
        rc, out, _err, _el = proc.run(["git", "config", "--get", key], timeout=10)
        return out.strip() if rc == 0 else ""
    except Exception:  # noqa: BLE001
        return ""
