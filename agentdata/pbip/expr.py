"""QueryExpressionContainer encoding/decoding and theme color utilities.

Converts between human field references ('Sales'[Amount], [Margin], Sum('Sales'[Amount]))
and PBIR QueryExpressionContainer JSON structures.
Provides theme shading / tinting utilities.
"""
from __future__ import annotations
import json
import re
from typing import Any
from . import pbir as P

AGG_MAP = {
    "sum": 0,
    "avg": 1,
    "average": 1,
    "distinctcount": 2,
    "min": 3,
    "max": 4,
    "count": 5,
    "median": 6,
    "stddev": 7,
    "var": 8,
}
AGG_REV = {v: k.title() for k, v in AGG_MAP.items()}


def encode_expr(text: str, is_measure: bool = False, entity_hint: str | None = None) -> dict[str, Any]:
    """Encode human reference into QueryExpressionContainer dict."""
    s = text.strip()

    # Check for Aggregation: e.g. Sum('Sales'[Amount]) or Count([Id])
    m_agg = re.match(r"^(\w+)\s*\(\s*(.+)\s*\)$", s)
    if m_agg:
        fn_name = m_agg.group(1).lower()
        inner_text = m_agg.group(2).strip()
        fn_id = AGG_MAP.get(fn_name, 0)
        inner_expr = encode_expr(inner_text, is_measure=False, entity_hint=entity_hint)
        return {
            "Aggregation": {
                "Expression": inner_expr,
                "Function": fn_id,
            }
        }

    # Match 'Table'[Column] or Table[Column]
    m_full = re.match(r"^(?:'([^']+)'|([A-Za-z0-9_]+))\[([^\]]+)\]$", s)
    if m_full:
        entity = m_full.group(1) or m_full.group(2)
        prop = m_full.group(3)
        key = "Measure" if is_measure else "Column"
        return {
            key: {
                "Expression": {
                    "SourceRef": {
                        "Entity": entity
                    }
                },
                "Property": prop
            }
        }

    # Match [MeasureName] or [ColumnName]
    m_bare = re.match(r"^\[([^\]]+)\]$", s)
    if m_bare:
        prop = m_bare.group(1)
        sr = {"Entity": entity_hint} if entity_hint else {}
        key = "Measure" if is_measure else "Column"
        expr_body: dict[str, Any] = {"Property": prop}
        if sr:
            expr_body["Expression"] = {"SourceRef": sr}
        return {key: expr_body}

    # Plain text identifier
    sr = {"Entity": entity_hint} if entity_hint else {}
    expr_body = {"Property": s}
    if sr:
        expr_body["Expression"] = {"SourceRef": sr}
    return {"Measure" if is_measure else "Column": expr_body}


def decode_expr(data: dict | str) -> str:
    """Decode QueryExpressionContainer JSON or string into readable field reference."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return data

    if not isinstance(data, dict):
        return str(data)

    refs = list(P.walk_refs(data))
    if refs:
        return refs[0].label()

    return json.dumps(data)


def shade_color(hex_color: str, pct: float) -> str:
    """Shade (darken) or tint (lighten) a hex color by percentage (-100 to 100)."""
    clean = hex_color.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        raise ValueError(f"Invalid hex color '{hex_color}'. Expected #RRGGBB format.")

    r = int(clean[0:2], 16)
    g = int(clean[2:4], 16)
    b = int(clean[4:6], 16)

    factor = pct / 100.0

    if factor < 0:
        # Darken: multiply by (1 + factor)
        mult = 1.0 + factor
        r = max(0, min(255, int(round(r * mult))))
        g = max(0, min(255, int(round(g * mult))))
        b = max(0, min(255, int(round(b * mult))))
    else:
        # Lighten: blend towards white (255)
        r = max(0, min(255, int(round(r + (255 - r) * factor))))
        g = max(0, min(255, int(round(g + (255 - g) * factor))))
        b = max(0, min(255, int(round(b + (255 - b) * factor))))

    return f"#{r:02X}{g:02X}{b:02X}"
