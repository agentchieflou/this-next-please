"""Oh My Posh prompt engine integration: detect, generate .omp.json, install & uninstall.

Generates one .omp.json per theme from the Theme palette, showing project, branch, ticket and phase.
Startup lines chain into pwsh, bash, and cmd (via Clink).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import proc
from . import textio
from . import theme
from .theme import Theme

MARKER = "# agentdata theme prompt (Oh My Posh)"
MARKER_LUA = "-- agentdata theme prompt (Oh My Posh)"
DEFAULT_OMP_DIR = "~/.agentdata/themes/omp"
SCHEMA_URL = "https://raw.githubusercontent.com/JanDeDobbeleer/oh-my-posh/main/themes/schema.json"


def omp_dir() -> str:
    d = os.path.expanduser(DEFAULT_OMP_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def detect() -> dict[str, Any]:
    """Detect whether oh-my-posh and Clink are available on PATH or in standard paths."""
    exe = proc.which("oh-my-posh")
    if not exe and sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA", "")
        cand = os.path.join(local_app, "Programs", "oh-my-posh", "bin", "oh-my-posh.exe")
        if os.path.isfile(cand):
            exe = cand

    version = None
    if exe:
        try:
            rc, out, _err, _el = proc.run([exe, "--version"], timeout=5)
            if rc == 0 and out.strip():
                version = out.strip()
        except Exception:
            pass

    clink_exe = proc.which("clink")
    if not clink_exe and sys.platform == "win32":
        for cand in (
            r"C:\Program Files (x86)\clink\clink.bat",
            r"C:\Program Files\clink\clink.bat",
        ):
            if os.path.isfile(cand):
                clink_exe = cand
                break

    # Nerd Font check: env vars or console font
    nerd_font = bool(os.environ.get("NERD_FONT") or os.environ.get("POSH_NERD_FONT"))

    return {
        "installed": bool(exe),
        "exe": exe,
        "version": version,
        "clink": bool(clink_exe),
        "clink_exe": clink_exe,
        "nerd_font": nerd_font,
    }


def generate_omp_config(t: Theme, layout: str = "jandedobbeleer") -> dict[str, Any]:
    """Generate an Oh My Posh JSON configuration dict from a Theme."""
    accent = t.accent or "#3FB950"
    ground = t.ground or "#000000"
    text = t.text or "#FFFFFF"
    status_ok = t.status.get("ok", "#3FB950")
    status_fail = t.status.get("fail", "#F85149")
    status_info = t.status.get("info", "#58A6FF")

    blocks = [
        {
            "type": "prompt",
            "alignment": "left",
            "segments": [
                {
                    "type": "text",
                    "style": "powerline",
                    "powerline_symbol": "\ue0b0",
                    "background": accent,
                    "foreground": ground,
                    "template": " {{ if .Env.AGENTDATA_PROJECT }}{{ .Env.AGENTDATA_PROJECT }}{{ else }}{{ .Folder }}{{ end }} ",
                },
                {
                    "type": "git",
                    "style": "powerline",
                    "powerline_symbol": "\ue0b0",
                    "background": t.ansi[8] if len(t.ansi) > 8 else "#6E7681",
                    "foreground": text,
                    "template": " {{ .HEAD }} ",
                },
                {
                    "type": "text",
                    "style": "powerline",
                    "powerline_symbol": "\ue0b0",
                    "background": status_info,
                    "foreground": ground,
                    "template": " {{ if .Env.AGENTDATA_TICKET }}{{ .Env.AGENTDATA_TICKET }} \u00b7 {{ .Env.AGENTDATA_PHASE }}{{ end }} ",
                },
                {
                    "type": "status",
                    "style": "diamond",
                    "background": status_ok,
                    "background_templates": [
                        f"{{{{ if gt .Code 0 }}}}{status_fail}{{{{ end }}}}"
                    ],
                    "foreground": text,
                    "trailing_diamond": "\ue0b0",
                    "template": " {{ if gt .Code 0 }}\u2717{{ else }}\u2713{{ end }} ",
                }
            ]
        }
    ]

    return {
        "$schema": SCHEMA_URL,
        "version": 2,
        "final_space": True,
        "transient_prompt": {
            "background": "transparent",
            "foreground": accent,
            "template": "\u276f "
        },
        "blocks": blocks,
    }


def write_theme_omp(t: Theme, out_path: str | None = None) -> str:
    """Write .omp.json for theme to disk."""
    cfg = generate_omp_config(t, layout=t.layout)
    target = out_path or os.path.join(omp_dir(), f"{t.name}.omp.json")
    textio.write_json(target, cfg)
    return textio.norm_path(target)


def startup_file(shell: str) -> str:
    """Return the startup file for the given shell."""
    shell = shell.lower().strip()
    home = os.path.expanduser("~")
    if shell in ("bash", "sh"):
        return os.path.join(home, ".bashrc")
    if shell == "zsh":
        return os.path.join(home, ".zshrc")
    if shell in ("pwsh", "powershell"):
        docs = os.path.join(home, "Documents")
        return os.path.join(docs, "PowerShell", "profile.ps1")
    if shell == "cmd":
        local_app = os.environ.get("LOCALAPPDATA", home)
        return os.path.join(local_app, "clink", "oh-my-posh.lua")
    raise ValueError(f"unknown shell '{shell}'")


def install_line(shell: str, omp_file: str) -> str:
    shell = shell.lower().strip()
    p = textio.norm_path(omp_file)
    if shell in ("pwsh", "powershell"):
        return f'oh-my-posh init pwsh --config "{p}" | Invoke-Expression  {MARKER}'
    if shell in ("bash", "zsh", "sh"):
        return f'eval "$(oh-my-posh init bash --config "{p}")"  {MARKER}'
    if shell == "cmd":
        return f'load(io.popen(\'oh-my-posh init cmd --config "{p}"\'):read("*a"))()  {MARKER_LUA}'
    raise ValueError(f"unknown shell '{shell}'")


def install(shell: str, omp_file: str, path: str | None = None) -> dict[str, Any]:
    """Idempotently install the Oh My Posh init line in startup file."""
    shell = shell.lower().strip()
    target = path or startup_file(shell)
    line = install_line(shell, omp_file)
    marker = MARKER_LUA if shell == "cmd" else MARKER

    existing = textio.read_text(target) if os.path.isfile(target) else ""
    kept = [ln for ln in existing.splitlines() if marker not in ln]
    already = len(kept) != len(existing.splitlines())
    body = "\n".join(kept).rstrip("\n")
    new = (body + "\n\n" if body else "") + line + "\n"
    changed = new != existing

    if changed:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        textio.write_text(target, new)

    return {
        "shell": shell,
        "path": textio.norm_path(target),
        "changed": changed,
        "replaced": already,
        "line": line,
    }


def uninstall(shell: str, path: str | None = None) -> dict[str, Any]:
    """Remove Oh My Posh init line from startup file."""
    shell = shell.lower().strip()
    target = path or startup_file(shell)
    marker = MARKER_LUA if shell == "cmd" else MARKER

    if not os.path.isfile(target):
        return {"shell": shell, "path": textio.norm_path(target), "removed": False}

    existing = textio.read_text(target)
    lines = existing.splitlines()
    kept = [ln for ln in lines if marker not in ln]
    removed = len(kept) != len(lines)

    if removed:
        # If file becomes empty and was previously empty, preserve trailing newline
        new = "\n".join(kept)
        if new and not new.endswith("\n"):
            new += "\n"
        textio.write_text(target, new)

    return {
        "shell": shell,
        "path": textio.norm_path(target),
        "removed": removed,
    }
