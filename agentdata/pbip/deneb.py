"""Deneb: the Microsoft-certified visual that draws any Vega or Vega-Lite specification.

It is how a custom chart gets built without a custom visual. A tenant that renders certified visuals
only renders Deneb, and a specification can draw what a visual of our own would have: marks, labels,
layers, interactivity. Without a verb for it the agent's only way in was hand-written visual JSON,
which `pbi-report-author` forbids, so "it can't be done" was the answer it reached.

Everything here follows Deneb's own PBIR guide (deneb-viz.github.io/pbir-guide, "PBIR Implementation
Guide", 2026-09): the visual type is the AppSource GUID, the fields go in the `dataset` role, and the
specification is `visual.objects.vega[0].properties.jsonSpec`, stringified inside single quotes, with
booleans as `true`/`false` and text in single quotes. The guide does not say how an apostrophe inside
is escaped. Power BI doubles it, as in every PBIR text literal (`expr.text_literal`), so a
specification may hold one: a Vega expression string in single quotes, or `Men's` in a label.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import author as AU
from . import expr as E
from . import pbir as P
from .. import textio

GUID = "deneb7E15AEF80B9E4D4F8E12924291ECE89A"
# Editions that share the GUID's suffix but are not on AppSource, so not the certified visual.
UNCERTIFIED_EDITIONS = ("STANDALONE", "ALPHA", "BETA")
PROVIDERS = ("vegaLite", "vega")
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"


class DenebError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


def _uses_dataset(node: Any) -> bool:
    """Deneb hands the visual's fields to the specification as the data set named `dataset`."""
    if isinstance(node, dict):
        data = node.get("data")
        named = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
        if any(isinstance(d, dict) and d.get("name") == "dataset" for d in named):
            return True
        return any(_uses_dataset(v) for v in node.values())
    if isinstance(node, list):
        return any(_uses_dataset(v) for v in node)
    return False


def load_spec(path: str) -> tuple[dict, str]:
    """Parse the specification and return it with the text that goes into `jsonSpec`."""
    text = textio.read_text(path)
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        raise DenebError(f"{path}:{e.lineno}:{e.colno}: not JSON: {e.msg}",
                         "Deneb accepts comments, but this verb validates plain JSON: remove them") from None
    if not isinstance(spec, dict):
        raise DenebError(f"{path}: a specification is a JSON object", "")
    if not _uses_dataset(spec):
        raise DenebError(f"{path}: no data set named \"dataset\"",
                         "Deneb passes the visual's fields as {\"data\": {\"name\": \"dataset\"}} (Vega-Lite) or "
                         "a data entry named dataset (Vega)")
    return spec, json.dumps(spec, indent=2, ensure_ascii=False)


def _text(value: str) -> dict:
    return {"expr": E.text_literal(value)}


def _bool(value: bool) -> dict:
    return {"expr": {"Literal": {"Value": "true" if value else "false"}}}


def _vega_properties(spec_text: str, provider: str, cross_filter: bool, cross_highlight: bool) -> dict:
    props = {"jsonSpec": _text(spec_text), "jsonConfig": _text("{}"), "provider": _text(provider)}
    if cross_filter:
        props.update({"enableSelection": _bool(True), "selectionMode": _text("simple")})
    if cross_highlight:
        props["enableHighlight"] = _bool(True)
    return props


def _sibling_schema(page_dir: Path) -> str:
    """Copy the `$schema` of a visual already on the page; never bump the version by hand."""
    for vj in sorted(page_dir.glob("visuals/*/visual.json")):
        schema = AU._load_json(vj).get("$schema")
        if schema:
            return schema
    return SCHEMA


def _register(report_root: str) -> str:
    """List the certified visual in report.json `publicCustomVisuals`: Power BI fetches it from AppSource."""
    rj_path = os.path.join(report_root, "definition", "report.json")
    rj = AU._load_json(rj_path) if os.path.exists(rj_path) else {}
    public = rj.setdefault("publicCustomVisuals", [])
    if GUID not in public:
        public.append(GUID)
        AU._save_json(rj_path, rj)
        return "added"
    return "present"


def add(pbip_path: str, page: str, spec_path: str, fields: list[str], *, provider: str = "vegaLite",
        title: str | None = None, position: tuple[int, int, int, int] | None = None,
        cross_filter: bool = False, cross_highlight: bool = False, facts: dict | None = None) -> dict[str, Any]:
    """A new Deneb visual on `page`, its Values filled with `fields`, drawing the specification."""
    if (facts or {}).get("pbi_custom_visuals", "").strip().lower() == "org-only":
        raise DenebError("this tenant renders organizational-store visuals only, so Deneb from AppSource would "
                         "not render",
                         "add Deneb from My organization in Desktop once, then "
                         "`ad-pbip visual deneb --visual <id> --spec <file>` sets its specification")
    if not fields:
        raise DenebError("a Deneb visual needs at least one field", "--fields 'Table'[Column] [Measure] ...")
    _spec, spec_text = load_spec(spec_path)
    root = P.find_report_dir(pbip_path)
    page_dir, page_data = AU.find_page_dir(root, page)

    x, y, w, h = position or (20, 20, 500, 300)
    page_w, page_h = page_data.get("width", 1280), page_data.get("height", 720)
    if x < 0 or y < 0 or x + w > page_w or y + h > page_h:
        raise DenebError(f"position {x},{y},{w},{h} is off the {page_w}x{page_h} canvas", "")

    projections = []
    for raw in fields:
        encoded = E.encode_expr(raw, is_measure=raw.strip().startswith("[") or "(" in raw)
        prop = next((encoded[k].get("Property") for k in ("Column", "Measure", "Aggregation") if k in encoded), None)
        projections.append({"field": encoded, "queryRef": raw.replace("'", "").replace("[", ".").replace("]", ""),
                             "nativeQueryRef": prop or raw})

    visual_id = AU._gen_hex(20)
    vis: dict[str, Any] = {
        "$schema": _sibling_schema(page_dir),
        "name": visual_id,
        "position": {"x": x, "y": y, "z": 1000, "height": h, "width": w, "tabOrder": 1000},
        "visual": {
            "visualType": GUID,
            "query": {"queryState": {"dataset": {"projections": projections}}},
            "objects": {"vega": [{"properties": _vega_properties(spec_text, provider, cross_filter, cross_highlight)}]},
            "drillFilterOtherVisuals": True,
        },
    }
    if title:
        vis["visual"]["visualContainerObjects"] = {"title": [{"properties": {"text": _text(title)}}]}
    path = page_dir / "visuals" / visual_id / "visual.json"
    AU._save_json(path, vis)
    return {"ok": True, "action": "deneb_add", "visual_id": visual_id, "visualType": GUID, "provider": provider,
            "fields": len(projections), "registered": _register(root), "path": textio.norm_path(str(path))}


def update(pbip_path: str, visual_id: str, spec_path: str, *, provider: str = "vegaLite",
           cross_filter: bool = False, cross_highlight: bool = False) -> dict[str, Any]:
    """Replace an existing Deneb visual's specification; its fields and everything Deneb manages stay."""
    _spec, spec_text = load_spec(spec_path)
    root = P.find_report_dir(pbip_path)
    path, vis = AU.find_visual_file(root, visual_id)
    vtype = (vis.get("visual") or {}).get("visualType") or ""
    edition = next((e for e in UNCERTIFIED_EDITIONS if vtype.upper().startswith(e)), None)
    if edition:
        raise DenebError(f"visual {visual_id} is Deneb's {edition.lower()} edition ({vtype}), which is not the "
                         "certified visual",
                         "replace it with Deneb from AppSource or My organization, then set its specification")
    if GUID not in vtype:
        raise DenebError(f"visual {visual_id} is a '{vtype}', not Deneb", "add one with --page and --fields")
    objects = vis["visual"].setdefault("objects", {})
    vega = objects.setdefault("vega", [{}])
    props = vega[0].setdefault("properties", {})
    props.update(_vega_properties(spec_text, provider, cross_filter, cross_highlight))
    AU._save_json(path, vis)
    return {"ok": True, "action": "deneb_update", "visual_id": visual_id, "visualType": vtype, "provider": provider,
            "path": textio.norm_path(str(path))}
