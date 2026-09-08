"""PBIR schema-driven catalog: visual types, roles, and formatting metadata.

Vendored under agentdata/pbip/schema/ under Microsoft MIT licence.
Provides authoritative roles, cardinality, deprecation markers, and formatting properties.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any
from ..model import AgentTable
from .. import textio

SCHEMA_DIR = Path(__file__).parent / "schema"
VISUALS_JSON = SCHEMA_DIR / "visuals.json"
VERSION_FILE = SCHEMA_DIR / "VERSION"


def load_catalog() -> dict[str, Any]:
    """Load the vendored visuals catalog."""
    if not VISUALS_JSON.exists():
        raise FileNotFoundError(f"Visual catalog not found at {VISUALS_JSON}")
    with open(VISUALS_JSON, encoding="utf-8") as f:
        return json.load(f)


def get_version_info() -> dict[str, str]:
    """Read VERSION metadata."""
    info = {}
    if VERSION_FILE.exists():
        with open(VERSION_FILE, encoding="utf-8") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
    return info


def list_visuals() -> AgentTable:
    """List all available visual types with roles and deprecation markers."""
    cat = load_catalog()
    visuals = cat.get("visuals", {})
    rows = []
    schema_path = textio.norm_path(str(VISUALS_JSON.relative_to(Path(__file__).parent.parent.parent)))

    for vtype, vdata in sorted(visuals.items()):
        desc = vdata.get("description", "")
        roles = ", ".join(vdata.get("roles", {}).keys())
        legacy = "yes" if vdata.get("legacy") else "no"
        repl = vdata.get("replacement") or "-"
        rows.append([vtype, desc, roles, legacy, repl, f"{schema_path}#/visuals/{vtype}"])

    cols = ["type", "description", "roles", "legacy", "replacement", "schema_path"]
    return AgentTable("visual_catalog", cols, rows, source=f"schema {schema_path}")


def describe_visual(visual_type: str, report_dir: str | None = None) -> AgentTable:
    """Describe roles, constraints, and data kinds for a visual type."""
    cat = load_catalog()
    visuals = cat.get("visuals", {})
    if visual_type not in visuals:
        # Search case-insensitively
        matches = [k for k in visuals if k.lower() == visual_type.lower()]
        if matches:
            visual_type = matches[0]
        else:
            # Check custom visual packages
            from ..pbiviz import core as PV
            cap_data = None
            if report_dir:
                cap_data = PV.read_visual_capabilities(visual_type, report_dir)
            if not cap_data:
                import glob
                reg_pkgs = glob.glob(f"**/StaticResources/RegisteredResources/{visual_type}*.pbiviz", recursive=True)
                if reg_pkgs:
                    cap_data = PV.read_visual_capabilities(visual_type, os.path.dirname(os.path.dirname(os.path.dirname(reg_pkgs[0]))))
            if not cap_data:
                v_dir = os.path.join("visuals", visual_type)
                if os.path.isdir(v_dir) and os.path.exists(os.path.join(v_dir, "capabilities.json")):
                    with open(os.path.join(v_dir, "capabilities.json"), "r", encoding="utf-8") as f:
                        cap_data = json.load(f)

            if cap_data:
                rows = []
                for r in cap_data.get("dataRoles", []):
                    rname = r.get("name")
                    kind = r.get("kind", "Any")
                    desc = r.get("description", "")
                    min_c = 1 if r.get("required") else 0
                    max_c = 1
                    rows.append([rname, min_c, max_c, kind, desc, f"custom://{visual_type}/roles/{rname}"])
                cols = ["role", "min", "max", "allowed_kinds", "description", "schema_path"]
                table = AgentTable(f"visual_{visual_type}", cols, rows, source=f"custom_visual {visual_type}")
                table.raw = {"visual_type": visual_type, "custom": True}
                return table

            raise KeyError(f"Visual type '{visual_type}' not found in catalog. Run `ad-pbip catalog list` for available types.")

    vdata = visuals[visual_type]
    roles = vdata.get("roles", {})
    schema_path = textio.norm_path(str(VISUALS_JSON.relative_to(Path(__file__).parent.parent.parent)))

    rows = []
    for role_name, rdata in roles.items():
        min_c = rdata.get("min", 0)
        max_c = rdata.get("max", 1)
        kind = rdata.get("kind", "Any")
        desc = rdata.get("description", "")
        rows.append([
            role_name,
            min_c,
            max_c,
            kind,
            desc,
            f"{schema_path}#/visuals/{visual_type}/roles/{role_name}",
        ])

    cols = ["role", "min", "max", "allowed_kinds", "description", "schema_path"]
    table = AgentTable(f"visual_{visual_type}", cols, rows, source=f"schema {schema_path}")
    table.raw = {"visual_type": visual_type, "legacy": vdata.get("legacy", False), "replacement": vdata.get("replacement")}
    return table


def formatting_catalog(visual_type: str | None = None, object_name: str | None = None,
                       property_name: str | None = None, search: str | None = None) -> AgentTable:
    """Query available formatting objects and properties."""
    cat = load_catalog()
    formatting = cat.get("formatting", {})
    schema_path = textio.norm_path(str(VISUALS_JSON.relative_to(Path(__file__).parent.parent.parent)))

    rows = []
    for obj, odata in sorted(formatting.items()):
        if object_name and obj.lower() != object_name.lower():
            continue
        props = odata.get("properties", {})
        for prop, pdata in sorted(props.items()):
            if property_name and prop.lower() != property_name.lower():
                continue
            ptype = pdata.get("type", "string")
            enums = ", ".join(pdata.get("enum", [])) if pdata.get("enum") else "-"
            pdesc = pdata.get("description", "")

            # If search filter applied
            if search:
                s_lower = search.lower()
                text = f"{obj} {prop} {ptype} {enums} {pdesc}".lower()
                if s_lower not in text:
                    continue

            rows.append([
                obj,
                prop,
                ptype,
                enums,
                pdesc,
                f"{schema_path}#/formatting/{obj}/properties/{prop}",
            ])

    cols = ["object", "property", "type", "enum_values", "description", "schema_path"]
    return AgentTable("formatting_catalog", cols, rows, source=f"schema {schema_path}")


def schema_update() -> dict[str, Any]:
    """Validate vendored schema files and verify VERSION file."""
    vinfo = get_version_info()
    cat = load_catalog()
    visual_types = list(cat.get("visuals", {}).keys())
    formatting_objects = list(cat.get("formatting", {}).keys())

    # Check that required schema files exist
    required_files = ["report.json", "page.json", "pagesMetadata.json", "visualContainer.json", "filterConfig.json", "bookmark.json", "visuals.json", "LICENSE", "VERSION"]
    missing = [f for f in required_files if not (SCHEMA_DIR / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing schema files: {missing}")

    return {
        "ok": True,
        "version": vinfo.get("tag", "2.0.0"),
        "commit": vinfo.get("commit", "unknown"),
        "pbir_format_version": vinfo.get("pbir_format_version", "2.0.0"),
        "visual_types_count": len(visual_types),
        "visual_types": visual_types,
        "formatting_objects_count": len(formatting_objects),
        "formatting_objects": formatting_objects,
    }
