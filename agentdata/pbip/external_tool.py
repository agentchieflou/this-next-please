"""Power BI Desktop External Tool registration and handoff IPC.

Registers agentdata as a Desktop External Tool so clicking 'agentdata' in Desktop's
External Tools ribbon substitutes %server% and %database% and hands off context
to the agent via .agent/desktop.json.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from . import desktop as DT
from .. import config as C

Runner = Callable[[list[str], int], tuple[int, str, str]]
DEFAULT_ICON = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4nGMQqHH8TwlmGDVg1IBRA4aLAQBRu8wQ68Y02AAAAABJRU5ErkJggg=="
)
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "external-tool", "agentdata.pbitool.json")


def external_tools_dir() -> str:
    """Path to Power BI Desktop External Tools folder."""
    common = os.environ.get("CommonProgramFiles") or r"C:\Program Files\Common Files"
    return os.path.join(common, "Microsoft Shared", "Power BI Desktop", "External Tools")


def is_external_tools_enabled(run: Runner | None = None) -> tuple[bool, str]:
    """Check registry HKLM/HKCU for EnableExternalTools killswitch."""
    if run:
        script = 'Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Microsoft Power BI Desktop" -Name "EnableExternalTools" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty EnableExternalTools'
        rc, out, _ = run(DT.PS + [script], 5)
        if rc == 0 and out.strip() == "0":
            return False, "disabled by HKLM EnableExternalTools=0"
        return True, "enabled"

    # Check winreg on Windows
    if sys.platform == "win32":
        try:
            import winreg
            for root, root_name in [(winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")]:
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Microsoft Power BI Desktop") as key:
                        val, _ = winreg.QueryValueEx(key, "EnableExternalTools")
                        if str(val) == "0":
                            return False, f"disabled by {root_name} EnableExternalTools=0"
                except (FileNotFoundError, OSError):
                    pass
            return True, "enabled (registry ok)"
        except Exception:
            pass

    return True, "enabled"


def render_tool_json(python_exe: str | None = None, project_dir: str | None = None) -> dict:
    """Generate the tool JSON structure with resolved python executable."""
    py = (python_exe or sys.executable).replace("\\", "/")
    data = None
    if os.path.exists(TEMPLATE_PATH):
        try:
            with open(TEMPLATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None

    if not data:
        data = {
            "version": "1.0.0",
            "name": "agentdata",
            "description": "Antigravity data agent bridge for Power BI Desktop",
            "path": py,
            "arguments": '-m agentdata pbip handoff --server "%server%" --database "%database%"',
            "iconData": DEFAULT_ICON,
        }
    else:
        args = data.get("arguments", '-m agentdata pbip handoff --server "%server%" --database "%database%"')
        if project_dir and "--project" not in args:
            args = f'{args} --project "{project_dir.replace("\\", "/")}"'
        data["path"] = py
        data["arguments"] = args

    return data


def register_tool(target_dir: str | None = None, python_exe: str | None = None,
                  project_dir: str | None = None) -> tuple[bool, str, str | None]:
    """Register agentdata.pbitool.json into External Tools folder.

    Writes to a temp file first, then moves/copies to target. If access is denied,
    returns False with destination path and the exact PowerShell elevation hint.
    """
    dest_dir = target_dir or external_tools_dir()
    dest_file = os.path.join(dest_dir, "agentdata.pbitool.json")
    tool_data = render_tool_json(python_exe=python_exe, project_dir=project_dir)

    tmp_file = os.path.join(tempfile.gettempdir(), f"agentdata_{os.getpid()}.pbitool.json")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(tool_data, f, indent=2)

    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(tmp_file, dest_file)
        try:
            os.remove(tmp_file)
        except OSError:
            pass
        return True, dest_file, None
    except (PermissionError, OSError) as e:
        hint = f'Run elevated in PowerShell: Copy-Item -LiteralPath "{tmp_file}" -Destination "{dest_file}" -Force'
        return False, dest_file, hint


def is_pid_alive(pid: int | None) -> bool:
    """Check if process id is still alive."""
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def handoff(server: str, database: str, project_dir: str | None = None,
            run: Runner | None = None) -> dict:
    """Process Desktop external tool launch and write .agent/desktop.json."""
    # Find matching Desktop instance
    inst = None
    target_pid = None
    target_file = None
    port_str = server.split(":")[-1] if ":" in server else server

    try:
        insts = DT.status(run=run)
        for i in insts:
            if str(i.port) == str(port_str) or (i.server and i.server.endswith(str(port_str))):
                inst = i
                target_pid = i.pid
                target_file = i.file or i.matched
                break
    except Exception:
        pass

    # Resolve project directory
    resolved_proj = project_dir
    if not resolved_proj and target_file:
        # Check if target_file is within a known git / .agent project
        cand = os.path.dirname(target_file)
        while cand and cand != os.path.dirname(cand):
            if os.path.exists(os.path.join(cand, ".agent")) or os.path.exists(os.path.join(cand, "AGENTS.md")):
                resolved_proj = cand
                break
            cand = os.path.dirname(cand)

    if not resolved_proj:
        resolved_proj = "."

    agent_dir = os.path.join(resolved_proj, ".agent")
    os.makedirs(agent_dir, exist_ok=True)
    desktop_json = os.path.join(agent_dir, "desktop.json")

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "server": server,
        "database": database,
        "pid": target_pid,
        "file": target_file,
        "handed_off_at": now_iso,
    }

    with open(desktop_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    proj_name = os.path.basename(os.path.abspath(resolved_proj))
    print(f"handed off to {proj_name} ({server})")

    return {
        "ok": True,
        "project": resolved_proj,
        "server": server,
        "database": database,
        "pid": target_pid,
        "file": target_file,
        "handed_off_at": now_iso,
        "path": desktop_json,
    }


def read_handoff(project_dir: str | None = None, max_age_seconds: float = 8 * 3600) -> dict | None:
    """Read .agent/desktop.json if it is fresh and the Desktop pid is still alive."""
    base = project_dir or "."
    desktop_json = os.path.join(base, ".agent", "desktop.json")
    if not os.path.exists(desktop_json):
        return None

    try:
        with open(desktop_json, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return None

    # Check staleness
    handed_off = data.get("handed_off_at")
    if handed_off:
        try:
            # ISO timestamp parsing
            ts = datetime.fromisoformat(handed_off.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > max_age_seconds:
                return None
        except Exception:
            pass

    # Check pid liveness
    pid = data.get("pid")
    if pid and not is_pid_alive(pid):
        return None

    return data
