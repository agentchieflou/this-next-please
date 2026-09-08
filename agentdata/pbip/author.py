"""Mechanical PBIR authoring: schema-validated pages, visuals, filters, bookmarks, and themes.

Enforces Microsoft PBIR schemas and anti-pattern rules:
- Fresh 20-hex lowercase visual names.
- Role cardinality validated against schema catalog.
- Canonical Filter Where conditions using SourceRef.Source (never SourceRef.Entity).
- Canvas bounds and positioning validation.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any
from . import catalog as CAT
from . import expr as E
from . import pbir as P
from .. import textio


def _gen_hex(length: int) -> str:
    """Generate lowercase hex string of exact length."""
    return uuid.uuid4().hex[:length].lower()


def _save_json(path: str | Path, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def find_page_dir(report_root: str, page_name_or_id: str) -> tuple[Path, dict]:
    """Find page directory and page.json by display name or id."""
    pages_base = Path(report_root) / "definition" / "pages"
    if not pages_base.exists():
        raise FileNotFoundError(f"Pages directory not found under {report_root}")

    target = page_name_or_id.strip()
    # Check exact folder name match
    direct = pages_base / target
    if direct.is_dir() and (direct / "page.json").exists():
        return direct, _load_json(direct / "page.json")

    # Search by displayName or folder name case-insensitively
    for pdir in pages_base.iterdir():
        if pdir.is_dir() and (pdir / "page.json").exists():
            pj_data = _load_json(pdir / "page.json")
            if (pj_data.get("displayName") or "").lower() == target.lower() or pdir.name.lower() == target.lower():
                return pdir, pj_data

    raise KeyError(f"Page '{page_name_or_id}' not found in report pages")


def page_add(pbip_path: str, name: str, after: str | None = None,
             width: int = 1280, height: int = 720) -> dict[str, Any]:
    """Add a new page with folder, page.json, and updated pages.json order."""
    root = P.find_report_dir(pbip_path)
    pages_base = Path(root) / "definition" / "pages"
    os.makedirs(pages_base, exist_ok=True)

    page_id = _gen_hex(20)
    page_dir = pages_base / page_id
    os.makedirs(page_dir / "visuals", exist_ok=True)

    page_data = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/1.0.0/schema.json",
        "name": page_id,
        "displayName": name.strip(),
        "displayOption": "FitToPage",
        "height": height,
        "width": width,
    }
    _save_json(page_dir / "page.json", page_data)

    # Update pages.json
    pages_json_path = pages_base / "pages.json"
    pages_order = []
    pages_meta = {}
    if pages_json_path.exists():
        pages_meta = _load_json(pages_json_path)
        pages_order = list(pages_meta.get("pageOrder") or [])

    if not pages_meta.get("$schema"):
        pages_meta["$schema"] = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json"

    if after and after in pages_order:
        idx = pages_order.index(after) + 1
        pages_order.insert(idx, page_id)
    elif after:
        # Match by display name
        inserted = False
        for i, pid in enumerate(pages_order):
            pj_file = pages_base / pid / "page.json"
            if pj_file.exists():
                pj = _load_json(pj_file)
                if (pj.get("displayName") or "").lower() == after.lower():
                    pages_order.insert(i + 1, page_id)
                    inserted = True
                    break
        if not inserted:
            pages_order.append(page_id)
    else:
        pages_order.append(page_id)

    pages_meta["pageOrder"] = pages_order
    if not pages_meta.get("activePageName"):
        pages_meta["activePageName"] = page_id
    _save_json(pages_json_path, pages_meta)

    return {
        "ok": True,
        "action": "page_add",
        "page_id": page_id,
        "displayName": name,
        "path": textio.norm_path(str(page_dir / "page.json")),
        "pageOrder": pages_order,
    }


def page_remove(pbip_path: str, page_name_or_id: str) -> dict[str, Any]:
    """Remove a page folder and its reference in pages.json."""
    root = P.find_report_dir(pbip_path)
    page_dir, page_data = find_page_dir(root, page_name_or_id)
    page_id = page_dir.name

    shutil.rmtree(page_dir)

    pages_json_path = Path(root) / "definition" / "pages" / "pages.json"
    pages_order = []
    if pages_json_path.exists():
        pages_meta = _load_json(pages_json_path)
        pages_order = [p for p in (pages_meta.get("pageOrder") or []) if p != page_id]
        pages_meta["pageOrder"] = pages_order
        if pages_meta.get("activePageName") == page_id:
            pages_meta["activePageName"] = pages_order[0] if pages_order else ""
        _save_json(pages_json_path, pages_meta)

    return {"ok": True, "action": "page_remove", "page_id": page_id, "pageOrder": pages_order}


def page_move(pbip_path: str, page_name_or_id: str, after: str | None = None) -> dict[str, Any]:
    """Reorder a page in pages.json."""
    root = P.find_report_dir(pbip_path)
    page_dir, _ = find_page_dir(root, page_name_or_id)
    page_id = page_dir.name

    pages_json_path = Path(root) / "definition" / "pages" / "pages.json"
    if not pages_json_path.exists():
        raise FileNotFoundError(f"pages.json not found under {root}")

    pages_meta = _load_json(pages_json_path)
    order = [p for p in (pages_meta.get("pageOrder") or []) if p != page_id]

    if after:
        # Find after id
        after_id = after
        for p in order:
            pj = Path(root) / "definition" / "pages" / p / "page.json"
            if pj.exists() and _load_json(pj).get("displayName", "").lower() == after.lower():
                after_id = p
                break
        if after_id in order:
            idx = order.index(after_id) + 1
            order.insert(idx, page_id)
        else:
            order.append(page_id)
    else:
        # Move to front
        order.insert(0, page_id)

    pages_meta["pageOrder"] = order
    _save_json(pages_json_path, pages_meta)
    return {"ok": True, "action": "page_move", "page_id": page_id, "pageOrder": order}


def visual_add(pbip_path: str, page_name_or_id: str, visual_type: str,
               title: str | None = None, fields: list[str] | None = None,
               position: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    """Add a visual with fresh 20-hex id, role cardinality validation, and position checks."""
    root = P.find_report_dir(pbip_path)
    page_dir, page_data = find_page_dir(root, page_name_or_id)

    # 1. Validate visual type against catalog
    cat = CAT.load_catalog()
    visuals = cat.get("visuals", {})
    if visual_type not in visuals:
        # Check case-insensitively
        matches = [k for k in visuals if k.lower() == visual_type.lower()]
        if matches:
            visual_type = matches[0]
        else:
            raise KeyError(f"Visual type '{visual_type}' not found in catalog. Run `ad-pbip catalog list` for available types.")

    vmeta = visuals[visual_type]
    if vmeta.get("legacy"):
        repl = vmeta.get("replacement")
        raise ValueError(f"Legacy visual type '{visual_type}' is deprecated; use modern replacement '{repl}' instead.")

    # 2. Validate position against canvas
    x, y, w, h = position or (20, 20, 500, 300)
    page_w = page_data.get("width", 1280)
    page_h = page_data.get("height", 720)

    if x < 0 or y < 0:
        raise ValueError(f"Position (x={x}, y={y}) must be >= 0.")
    if x + w > page_w or y + h > page_h:
        raise ValueError(f"Position extends off-canvas: visual bounds ({x + w}, {y + h}) exceed page dimensions ({page_w}, {page_h}).")

    # 3. Map fields to roles in schema order
    roles_def = vmeta.get("roles", {})
    query_state: dict[str, dict] = {}
    assigned_fields = list(fields or [])

    # Classify fields and assign to roles
    field_idx = 0
    for role_name, rdata in roles_def.items():
        if field_idx >= len(assigned_fields):
            break
        max_c = rdata.get("max", 1)
        r_projs = []
        for _ in range(max_c):
            if field_idx >= len(assigned_fields):
                break
            raw_f = assigned_fields[field_idx]
            field_idx += 1

            # Detect measure vs column
            is_meas = raw_f.strip().startswith("[") or "(" in raw_f or rdata.get("kind") == "Measure"
            encoded = E.encode_expr(raw_f, is_measure=is_meas)
            prop = None
            for k in ("Column", "Measure", "Aggregation"):
                if k in encoded:
                    prop = encoded[k].get("Property") or raw_f
                    break
            qref = raw_f.replace("'", "").replace("[", ".").replace("]", "")
            proj = {
                "field": encoded,
                "queryRef": qref,
                "nativeQueryRef": prop or raw_f,
            }
            if rdata.get("kind") == "Grouping":
                proj["active"] = True
            r_projs.append(proj)

        if r_projs:
            query_state[role_name] = {"projections": r_projs}

    # Ensure minimum cardinality satisfied
    for role_name, rdata in roles_def.items():
        min_c = rdata.get("min", 0)
        curr_count = len(query_state.get(role_name, {}).get("projections", []))
        if curr_count < min_c:
            raise ValueError(f"Visual type '{visual_type}' requires at least {min_c} field(s) for role '{role_name}', got {curr_count}.")

    # 4. Generate visual container JSON
    visual_id = _gen_hex(20)
    vis_dir = page_dir / "visuals" / visual_id
    os.makedirs(vis_dir, exist_ok=True)

    vis_data: dict[str, Any] = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
        "name": visual_id,
        "position": {
            "x": x,
            "y": y,
            "z": 1000,
            "height": h,
            "width": w,
            "tabOrder": 1000,
        },
        "visual": {
            "visualType": visual_type,
            "query": {
                "queryState": query_state
            }
        }
    }

    if title:
        vis_data["visual"]["visualContainerObjects"] = {
            "title": [
                {
                    "properties": {
                        "text": {
                            "expr": {
                                "Literal": {
                                    "Value": f"'{title}'"
                                }
                            }
                        }
                    }
                }
            ]
        }

    vj_path = vis_dir / "visual.json"
    _save_json(vj_path, vis_data)

    return {
        "ok": True,
        "action": "visual_add",
        "visual_id": visual_id,
        "visualType": visual_type,
        "title": title,
        "page_id": page_dir.name,
        "path": textio.norm_path(str(vj_path)),
        "position": {"x": x, "y": y, "width": w, "height": h},
    }


def find_visual_file(report_root: str, visual_id: str) -> tuple[Path, dict]:
    """Locate visual.json across all pages."""
    pages_base = Path(report_root) / "definition" / "pages"
    for vj in pages_base.rglob("visual.json"):
        if vj.parent.name.lower() == visual_id.lower():
            return vj, _load_json(vj)
        try:
            data = _load_json(vj)
            if (data.get("name") or "").lower() == visual_id.lower():
                return vj, data
        except Exception:
            pass
    raise KeyError(f"Visual '{visual_id}' not found in report")


def visual_set(pbip_path: str, visual_id: str, prop_path: str, value: Any) -> dict[str, Any]:
    """Set visual formatting or position property with validation against schema."""
    root = P.find_report_dir(pbip_path)
    vj_path, vis_data = find_visual_file(root, visual_id)

    # Position property: position.x, position.width, etc.
    if prop_path.startswith("position."):
        pos_attr = prop_path.split(".", 1)[1]
        if pos_attr not in ("x", "y", "z", "width", "height", "tabOrder"):
            raise KeyError(f"Unknown position property '{pos_attr}'")
        vis_data.setdefault("position", {})[pos_attr] = int(value)
        _save_json(vj_path, vis_data)
        return {"ok": True, "action": "visual_set", "visual_id": visual_id, "property": prop_path, "value": int(value)}

    # Formatting property: <object>.<property>
    if "." not in prop_path:
        raise ValueError(f"Property path must be in 'object.property' format (e.g. title.text), got '{prop_path}'")

    obj_name, prop_name = prop_path.split(".", 1)

    # Validate against catalog formatting
    cat = CAT.load_catalog()
    formatting = cat.get("formatting", {})
    if obj_name not in formatting:
        raise KeyError(f"Formatting object '{obj_name}' not in schema catalog. Run `ad-pbip catalog formatting` for available objects.")
    obj_props = formatting[obj_name].get("properties", {})
    if prop_name not in obj_props:
        raise KeyError(f"Property '{prop_name}' not valid for object '{obj_name}'.")

    # Coerce value based on type
    ptype = obj_props[prop_name].get("type", "string")
    if ptype == "number":
        typed_val: Any = float(value) if "." in str(value) else int(value)
    elif ptype == "bool":
        typed_val = str(value).lower() in ("true", "1", "yes")
    else:
        typed_val = str(value)

    # Set in visualContainerObjects (or visual.objects)
    vis = vis_data.setdefault("visual", {})
    vco = vis.setdefault("visualContainerObjects", {})
    obj_entry = vco.setdefault(obj_name, [{}])[0]
    props = obj_entry.setdefault("properties", {})

    if ptype == "string" and prop_name == "text":
        props[prop_name] = {"expr": {"Literal": {"Value": f"'{typed_val}'"}}}
    elif ptype == "color":
        props[prop_name] = {"solid": {"color": typed_val}}
    else:
        props[prop_name] = {"expr": {"Literal": {"Value": str(typed_val)}}}

    _save_json(vj_path, vis_data)
    return {"ok": True, "action": "visual_set", "visual_id": visual_id, "property": prop_path, "value": typed_val}


def visual_remove(pbip_path: str, visual_id: str) -> dict[str, Any]:
    """Remove visual directory."""
    root = P.find_report_dir(pbip_path)
    vj_path, _ = find_visual_file(root, visual_id)
    vis_dir = vj_path.parent
    shutil.rmtree(vis_dir)
    return {"ok": True, "action": "visual_remove", "visual_id": visual_id}


def filter_set(pbip_path: str, scope: str, field_ref: str,
               values: list[str] | None = None, between: tuple[Any, Any] | None = None,
               top: int | None = None, page: str | None = None,
               visual_id: str | None = None) -> dict[str, Any]:
    """Set filter on report, page, or visual using canonical SourceRef.Source in Where."""
    root = P.find_report_dir(pbip_path)
    encoded = E.encode_expr(field_ref)

    # Extract entity and property
    col_or_meas = encoded.get("Column") or encoded.get("Measure") or {}
    prop = col_or_meas.get("Property") or "Field"
    entity = ((col_or_meas.get("Expression") or {}).get("SourceRef") or {}).get("Entity") or "Table"

    alias = "t"
    filter_id = "Filter" + _gen_hex(24)

    # Construct Condition
    if values is not None:
        filter_type = "Categorical"
        cond = {
            "In": {
                "Expressions": [
                    {
                        "Column": {
                            "Expression": {
                                "SourceRef": {
                                    "Source": alias
                                }
                            },
                            "Property": prop
                        }
                    }
                ],
                "Values": [
                    [{"Literal": {"Value": f"'{v}'" if not v.isdigit() else f"{v}L"}}] for v in values
                ]
            }
        }
    elif between is not None:
        filter_type = "Advanced"
        cond = {
            "Between": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Source": alias
                            }
                        },
                        "Property": prop
                    }
                },
                "LowerBound": {"Literal": {"Value": str(between[0])}},
                "UpperBound": {"Literal": {"Value": str(between[1])}}
            }
        }
    elif top is not None:
        filter_type = "TopN"
        cond = {
            "TopN": {
                "Count": top,
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {
                                "Source": alias
                            }
                        },
                        "Property": prop
                    }
                }
            }
        }
    else:
        raise ValueError("Must specify one of values, between, or top for filter.")

    filter_def = {
        "name": filter_id,
        "type": filter_type,
        "field": encoded,
        "filter": {
            "Version": 2,
            "From": [
                {
                    "Name": alias,
                    "Entity": entity,
                    "Type": 0
                }
            ],
            "Where": [
                {
                    "Condition": cond
                }
            ]
        }
    }

    # Attach to appropriate target
    target_file = None
    if scope == "report":
        target_file = Path(root) / "definition" / "report.json"
    elif scope == "page":
        if not page:
            raise ValueError("Must specify --page when scope is page")
        pdir, _ = find_page_dir(root, page)
        target_file = pdir / "page.json"
    elif scope == "visual":
        if not visual_id:
            raise ValueError("Must specify --visual when scope is visual")
        vj_path, _ = find_visual_file(root, visual_id)
        target_file = vj_path
    else:
        raise ValueError(f"Invalid scope '{scope}'; expected report, page, or visual")

    target_data = _load_json(target_file)
    fc = target_data.setdefault("filterConfig", {})
    flist = fc.setdefault("filters", [])
    flist.append(filter_def)
    _save_json(target_file, target_data)

    return {
        "ok": True,
        "action": "filter_set",
        "filter_id": filter_id,
        "scope": scope,
        "field": field_ref,
        "path": textio.norm_path(str(target_file))
    }


def bookmark_add(pbip_path: str, name: str, page: str,
                 visuals: list[str] | None = None) -> dict[str, Any]:
    """Create a bookmark definition file."""
    root = P.find_report_dir(pbip_path)
    page_dir, _ = find_page_dir(root, page)
    page_id = page_dir.name

    bm_dir = Path(root) / "definition" / "bookmarks"
    os.makedirs(bm_dir, exist_ok=True)

    bm_id = "Bookmark" + _gen_hex(16)
    v_dict = {vid: {} for vid in (visuals or [])}

    bm_data = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/bookmark/1.0.0/schema.json",
        "name": bm_id,
        "displayName": name,
        "explorationState": {
            "version": "1.3",
            "activeSection": page_id,
            "sections": {
                page_id: {
                    "visualContainers": v_dict
                }
            }
        }
    }

    bm_file = bm_dir / f"{bm_id}.json"
    _save_json(bm_file, bm_data)
    return {"ok": True, "action": "bookmark_add", "name": bm_id, "displayName": name, "path": textio.norm_path(str(bm_file))}


def theme_set(pbip_path: str, theme_file: str) -> dict[str, Any]:
    """Register custom theme in report.json and copy file to StaticResources."""
    if not os.path.exists(theme_file):
        raise FileNotFoundError(f"Theme file not found: {theme_file}")

    theme_data = _load_json(theme_file)
    theme_name = theme_data.get("name") or Path(theme_file).stem

    root = P.find_report_dir(pbip_path)
    res_dir = Path(root) / "StaticResources" / "RegisteredResources"
    os.makedirs(res_dir, exist_ok=True)

    dest_filename = Path(theme_file).name
    dest_path = res_dir / dest_filename
    shutil.copyfile(theme_file, dest_path)

    # Register in definition/report.json
    rj_path = Path(root) / "definition" / "report.json"
    rdata = _load_json(rj_path) if rj_path.exists() else {}
    tc = rdata.setdefault("themeCollection", {})
    tc["customTheme"] = {
        "name": theme_name,
        "reportVersionAtImport": "2.0.0",
        "type": "RegisteredResources",
        "path": f"StaticResources/RegisteredResources/{dest_filename}"
    }
    _save_json(rj_path, rdata)

    return {
        "ok": True,
        "action": "theme_set",
        "name": theme_name,
        "target": textio.norm_path(str(dest_path)),
        "report_json": textio.norm_path(str(rj_path))
    }
