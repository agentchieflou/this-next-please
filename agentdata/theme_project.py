"""One theme per project: directory hooks (pwsh, bash, clink) and Windows Terminal fragment.

Zero-Python directory hooks: hook.{ps1,sh,lua} have prefix tables embedded,
so cd switches colours and exports AGENTDATA_PROJECT, AGENTDATA_TICKET, AGENTDATA_PHASE
in under a frame without spawning python.exe.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from . import config
from . import textio
from . import theme
from .fleet.registry import Registry

HOOK_MARKER = "# agentdata directory theme hook"
HOOK_MARKER_LUA = "-- agentdata directory theme hook"
THEMES_DIR = "~/.agentdata/themes"


def themes_dir() -> str:
    d = os.path.expanduser(THEMES_DIR)
    os.makedirs(d, exist_ok=True)
    return textio.norm_path(d)


def wt_fragment_path() -> str:
    local_app = os.environ.get("LOCALAPPDATA")
    if not local_app:
        local_app = os.path.expanduser("~")
    return textio.norm_path(
        os.path.join(local_app, "Microsoft", "Windows Terminal", "Fragments", "agentdata", "agentdata.json")
    )


def resolve_project_themes() -> list[dict[str, Any]]:
    """Resolve theme for every registered repository."""
    cfg = config.load()
    default_theme_name = config.get(cfg, "theme.default", "greens")
    proj_map = config.get(cfg, "theme.projects", {})
    if not isinstance(proj_map, dict):
        proj_map = {}

    reg = Registry()
    entries = []
    for r in reg.repos.values():
        theme_name = proj_map.get(r.name) or proj_map.get(os.path.abspath(r.path)) or default_theme_name
        try:
            t = theme.get(theme_name, seed=r.name)
        except Exception:
            t = theme.GREENS
        entries.append({
            "name": r.name,
            "path": textio.norm_path(os.path.abspath(r.path)),
            "theme_name": t.name,
            "theme": t,
            "accent": t.accent or "#3FB950",
            "escapes": theme.escapes(t),
        })
    return entries


# ---------- Windows Terminal Fragment ----------

def generate_wt_fragment() -> dict[str, Any]:
    """Generate Windows Terminal fragment dictionary."""
    schemes = []
    for t in theme.list_themes():
        if t.name == "none" or not t.ansi or len(t.ansi) < 16:
            continue
        ansi = t.ansi
        schemes.append({
            "name": t.name,
            "background": t.ground,
            "foreground": t.text,
            "cursorColor": t.cursor or t.accent or t.text,
            "black": ansi[0],
            "red": ansi[1],
            "green": ansi[2],
            "yellow": ansi[3],
            "blue": ansi[4],
            "purple": ansi[5],
            "cyan": ansi[6],
            "white": ansi[7],
            "brightBlack": ansi[8],
            "brightRed": ansi[9],
            "brightGreen": ansi[10],
            "brightYellow": ansi[11],
            "brightBlue": ansi[12],
            "brightPurple": ansi[13],
            "brightCyan": ansi[14],
            "brightWhite": ansi[15],
        })

    profiles = []
    for entry in resolve_project_themes():
        profiles.append({
            "name": entry["name"],
            "tabTitle": entry["name"],
            "startingDirectory": entry["path"],
            "colorScheme": entry["theme_name"],
            "tabColor": entry["accent"],
        })

    return {
        "$schema": "https://aka.ms/terminal-profiles-schema",
        "schemes": schemes,
        "profiles": profiles,
    }


def write_wt_fragment(path: str | None = None) -> str:
    target = path or wt_fragment_path()
    data = generate_wt_fragment()
    textio.write_json(target, data)
    return textio.norm_path(target)


def remove_wt_fragment(path: str | None = None) -> bool:
    target = path or wt_fragment_path()
    if os.path.isfile(target):
        try:
            os.remove(target)
            return True
        except OSError:
            return False
    return False


# ---------- Directory Hooks (Zero Python at prompt time) ----------

def generate_ps1_hook(entries: list[dict[str, Any]], default_escapes: str = "") -> str:
    """Generate PowerShell hook script."""
    lines = [
        f"{HOOK_MARKER} (PowerShell)",
        "$script:LastDir = ''",
        "$script:Rules = @(",
    ]
    for e in entries:
        norm_p = e['path'].replace("'", "''")
        esc = e['escapes'].replace("`", "``").replace("$", "`$").replace('"', '`"')
        lines.append(
            f"  [pscustomobject]@{{ Path = '{norm_p}'; Project = '{e['name']}'; Escapes = \"{esc}\" }}"
        )
    lines.extend([
        ")",
        "$script:DefaultEscapes = \"" + default_escapes.replace('"', '`"') + "\"",
        "",
        "function Update-AgentdataThemeHook {",
        "  $cur = $PWD.Path",
        "  if ($cur -ne $script:LastDir) {",
        "    $script:LastDir = $cur",
        "    $matched = $null",
        "    foreach ($r in $script:Rules) {",
        "      if ($cur.StartsWith($r.Path, [System.StringComparison]::OrdinalIgnoreCase)) {",
        "        $matched = $r",
        "        break",
        "      }",
        "    }",
        "    if ($matched) {",
        "      $env:AGENTDATA_PROJECT = $matched.Project",
        "      if ($matched.Escapes) { [Console]::Write($matched.Escapes) }",
        "      $stateFile = [System.IO.Path]::Combine($matched.Path, '.agent', 'state.json')",
        "      if ([System.IO.File]::Exists($stateFile)) {",
        "        try {",
        "          $raw = [System.IO.File]::ReadAllText($stateFile)",
        "          if ($raw -match '\"active_ticket\":\\s*\"([^\"]+)\"') { $env:AGENTDATA_TICKET = $matches[1] }",
        "          if ($raw -match '\"phase\":\\s*\"([^\"]+)\"') { $env:AGENTDATA_PHASE = $matches[1] }",
        "        } catch {}",
        "      }",
        "    } else {",
        "      $env:AGENTDATA_PROJECT = ''",
        "      $env:AGENTDATA_TICKET = ''",
        "      $env:AGENTDATA_PHASE = ''",
        "      if ($script:DefaultEscapes) { [Console]::Write($script:DefaultEscapes) }",
        "    }",
        "  }",
        "}",
        "",
        "if (-not $script:OriginalPrompt) {",
        "  $script:OriginalPrompt = (Get-Command prompt -ErrorAction SilentlyContinue).ScriptBlock",
        "}",
        "function global:prompt {",
        "  Update-AgentdataThemeHook",
        "  if ($script:OriginalPrompt) { & $script:OriginalPrompt } else { \"PS $PWD> \" }",
        "}",
    ])
    return "\n".join(lines) + "\n"


def generate_sh_hook(entries: list[dict[str, Any]], default_escapes: str = "") -> str:
    """Generate Bash/POSIX hook script."""
    lines = [
        f"{HOOK_MARKER} (bash)",
        "_AD_LAST_DIR=''",
        "",
        "_ad_theme_hook() {",
        "  local cur=\"$PWD\"",
        "  if [ \"$cur\" != \"$_AD_LAST_DIR\" ]; then",
        "    _AD_LAST_DIR=\"$cur\"",
    ]

    for idx, e in enumerate(entries):
        cond = "if" if idx == 0 else "elif"
        norm_p = e["path"].replace("\\", "/")
        lines.append(f'    {cond} [[ "$cur" == "{norm_p}"* ]]; then')
        lines.append(f'      export AGENTDATA_PROJECT="{e["name"]}"')
        if e["escapes"]:
            # Output escapes in printf
            hex_esc = "".join(f"\\x{ord(c):02x}" for c in e["escapes"])
            lines.append(f'      printf "{hex_esc}"')
        lines.append(f'      local sf="{norm_p}/.agent/state.json"')
        lines.append('      if [ -f "$sf" ]; then')
        lines.append('        export AGENTDATA_TICKET=$(grep -o \'"active_ticket": *"[^"]*"\' "$sf" | head -n1 | cut -d\'"\' -f4)')
        lines.append('        export AGENTDATA_PHASE=$(grep -o \'"phase": *"[^"]*"\' "$sf" | head -n1 | cut -d\'"\' -f4)')
        lines.append('      fi')

    if entries:
        lines.append("    else")
        lines.append("      export AGENTDATA_PROJECT=''")
        lines.append("      export AGENTDATA_TICKET=''")
        lines.append("      export AGENTDATA_PHASE=''")
        if default_escapes:
            hex_def = "".join(f"\\x{ord(c):02x}" for c in default_escapes)
            lines.append(f'      printf "{hex_def}"')
        lines.append("    fi")

    lines.extend([
        "  fi",
        "}",
        'if [[ ";$PROMPT_COMMAND;" != *";_ad_theme_hook;"* ]]; then',
        '  PROMPT_COMMAND="_ad_theme_hook;${PROMPT_COMMAND:-}"',
        'fi',
    ])
    return "\n".join(lines) + "\n"


def generate_lua_hook(entries: list[dict[str, Any]]) -> str:
    """Generate Clink Lua script for cmd.exe."""
    lines = [
        f"{HOOK_MARKER_LUA} (Clink for cmd.exe)",
        "local last_dir = ''",
        "local rules = {",
    ]
    for e in entries:
        norm_p = e["path"].replace("\\", "\\\\").lower()
        lines.append(f'  {{ path = "{norm_p}", project = "{e["name"]}" }},')
    lines.extend([
        "}",
        "",
        "local function onbeginedit()",
        "  local cur = os.getcwd():lower()",
        "  if cur ~= last_dir then",
        "    last_dir = cur",
        "    local matched = nil",
        "    for _, r in ipairs(rules) do",
        "      if string.sub(cur, 1, string.len(r.path)) == r.path then",
        "        matched = r",
        "        break",
        "      end",
        "    end",
        "    if matched then",
        '      clink.setenv("AGENTDATA_PROJECT", matched.project)',
        "    else",
        '      clink.setenv("AGENTDATA_PROJECT", "")',
        '      clink.setenv("AGENTDATA_TICKET", "")',
        '      clink.setenv("AGENTDATA_PHASE", "")',
        "    end",
        "  end",
        "end",
        "",
        "if clink and clink.onbeginedit then",
        "  clink.onbeginedit(onbeginedit)",
        "end",
    ])
    return "\n".join(lines) + "\n"


def write_hooks(hook_directory: str | None = None) -> dict[str, str]:
    """Generate and write hook.ps1, hook.sh, hook.lua."""
    d = hook_directory or themes_dir()
    entries = resolve_project_themes()

    cfg = config.load()
    default_name = config.get(cfg, "theme.default", "greens")
    try:
        def_t = theme.get(default_name)
        def_esc = theme.escapes(def_t)
    except Exception:
        def_esc = ""

    ps1_path = os.path.join(d, "hook.ps1")
    sh_path = os.path.join(d, "hook.sh")
    lua_path = os.path.join(d, "hook.lua")

    textio.write_text(ps1_path, generate_ps1_hook(entries, default_escapes=def_esc))
    textio.write_text(sh_path, generate_sh_hook(entries, default_escapes=def_esc))
    textio.write_text(lua_path, generate_lua_hook(entries))

    return {
        "ps1": textio.norm_path(ps1_path),
        "sh": textio.norm_path(sh_path),
        "lua": textio.norm_path(lua_path),
    }


def install_hook(shell: str, startup_path: str | None = None) -> dict[str, Any]:
    """Add dot-sourcing of the hook into the target shell startup file."""
    shell = shell.lower().strip()
    hooks = write_hooks()

    from . import omp
    target = startup_path or omp.startup_file(shell)

    if shell in ("pwsh", "powershell"):
        line = f". '{hooks['ps1']}'  {HOOK_MARKER}"
        marker = HOOK_MARKER
    elif shell in ("bash", "sh", "zsh"):
        line = f"source '{hooks['sh']}'  {HOOK_MARKER}"
        marker = HOOK_MARKER
    elif shell == "cmd":
        line = f"dofile('{hooks['lua']}')  {HOOK_MARKER_LUA}"
        marker = HOOK_MARKER_LUA
    else:
        raise ValueError(f"unknown shell: {shell}")

    existing = textio.read_text(target) if os.path.isfile(target) else ""
    kept = [ln for ln in existing.splitlines() if marker not in ln]
    already = len(kept) != len(existing.splitlines())
    body = "\n".join(kept).rstrip("\n")
    new = (body + "\n\n" if body else "") + line + "\n"
    changed = new != existing

    if changed:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        textio.write_text(target, new)

    return {"shell": shell, "path": textio.norm_path(target), "changed": changed, "replaced": already}


def uninstall_hook(shell: str, startup_path: str | None = None) -> dict[str, Any]:
    """Remove dot-sourcing of the hook from startup file."""
    shell = shell.lower().strip()
    from . import omp
    target = startup_path or omp.startup_file(shell)
    marker = HOOK_MARKER_LUA if shell == "cmd" else HOOK_MARKER

    if not os.path.isfile(target):
        return {"shell": shell, "path": textio.norm_path(target), "removed": False}

    existing = textio.read_text(target)
    lines = existing.splitlines()
    kept = [ln for ln in lines if marker not in ln]
    removed = len(kept) != len(lines)

    if removed:
        new = "\n".join(kept)
        if new and not new.endswith("\n"):
            new += "\n"
        textio.write_text(target, new)

    return {"shell": shell, "path": textio.norm_path(target), "removed": removed}
