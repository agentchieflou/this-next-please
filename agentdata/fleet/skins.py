"""Skins for Desk on Windows (Issues #154, #155, #156, #157).

A skin is one more stylesheet over the same DOM: the approved grid with
CSS and hand-drawn SVG swapped in. A skin that needs a page change is not a skin.

Contract:
- theme.skin in ~/.agentdata/config.json, 'none' by default.
- No rasters/bitmaps: 100% original hand-authored vector SVG pixel art.
- Fallbacks: prefers-reduced-transparency and prefers-reduced-motion.
- Composited panel contrast verified in tests.
"""
from __future__ import annotations
import os

from .. import theme as T

SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "skins")

SKINS = {
    "glass": {
        "name": "glass",
        "title": "Glass",
        "base": "dark",
        "why": "frosted acrylic translucent panels over dark ground with subtle accent glow",
        "composited_panel": "#1B222C",
    },
    "voxel": {
        "name": "voxel",
        "title": "Voxel",
        "base": "matrix",
        "why": "chunky bevelled slab controls and pixel status blocks inspired by voxel worlds",
        "composited_panel": "#1E221E",
    },
    "farmstead": {
        "name": "farmstead",
        "title": "Farmstead",
        "base": "sand",
        "why": "warm paper, wood trim and rustic crop-stage markers inspired by pixel farming",
        "composited_panel": "#E8DDC3",
    },
}


def list_skins() -> list[dict]:
    """List available skins with their base palette, description, and stylesheet byte size."""
    out = [{
        "name": "none",
        "title": "Standard",
        "base": "system",
        "why": "the default clean HIG interface",
        "size_bytes": 0,
    }]
    for name, s in SKINS.items():
        css_file = os.path.join(SKINS_DIR, name, "skin.css")
        size = os.path.getsize(css_file) if os.path.isfile(css_file) else 0
        out.append({
            "name": name,
            "title": s["title"],
            "base": s["base"],
            "why": s["why"],
            "size_bytes": size,
            "composited_panel": s["composited_panel"],
        })
    return out


def get_skin(name: str) -> dict | None:
    return SKINS.get(name)
