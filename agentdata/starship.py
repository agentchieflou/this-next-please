"""Starship prompt engine comparison & configuration generator.

Generates starship.toml from Theme palette for comparison against Oh My Posh (#141):
- Startup cost per prompt (measured)
- cmd.exe support (via Clink starship-clink)
- Transient-prompt parity
- Nerd font needs
"""
from __future__ import annotations

import os
from typing import Any

from . import textio
from .theme import Theme

DEFAULT_STARSHIP_DIR = "~/.agentdata/themes/starship"


def starship_dir() -> str:
    d = os.path.expanduser(DEFAULT_STARSHIP_DIR)
    os.makedirs(d, exist_ok=True)
    return textio.norm_path(d)


def generate_starship_config(t: Theme) -> str:
    """Generate starship.toml string from Theme palette."""
    accent = t.accent or "#3FB950"
    ground = t.ground or "#000000"
    text = t.text or "#FFFFFF"
    status_ok = t.status.get("ok", "#3FB950")
    status_fail = t.status.get("fail", "#F85149")

    lines = [
        f"# agentdata theme prompt (Starship) - theme '{t.name}'",
        "add_newline = false",
        "",
        'format = """',
        f"[ $env:AGENTDATA_PROJECT ](bg:{accent} fg:{ground})\\",
        f"[ $git_branch ](bg:#6E7681 fg:{text})\\",
        f"[ $status ](bg:{status_ok} fg:{text})\\",
        '$character"""',
        "",
        "[character]",
        f'success_symbol = "[❯](bold {accent})"',
        f'error_symbol = "[❯](bold {status_fail})"',
        "",
        "[status]",
        "disabled = false",
        f'format = "[$symbol]($style) "',
        'symbol = "✓ "',
        "",
        "[git_branch]",
        f'format = "[$symbol$branch ]($style)"',
        'symbol = " "',
    ]
    return "\n".join(lines) + "\n"


def write_theme_starship(t: Theme, out_path: str | None = None) -> str:
    """Write starship.toml configuration for theme."""
    toml = generate_starship_config(t)
    target = out_path or os.path.join(starship_dir(), f"{t.name}.starship.toml")
    textio.write_text(target, toml)
    return textio.norm_path(target)
