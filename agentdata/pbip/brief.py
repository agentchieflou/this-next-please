"""Report planning and design brief: specification checking, approval gate, and layout contracts.

Validates that:
- Every page has a layout_contract with valid canvas dimensions.
- Every placement is within canvas bounds.
- Zero overlapping placements (rectangle collision check).
- Space audit sums to <= 100%.
- No bare single-value card in a dominant region (> 30% canvas).
- Every field reference resolves in the projected TMDL model.
- Visual types exist in the PBIR schema catalog.
- Approval is strictly human-interactive (terminal TTY only).
"""
from __future__ import annotations
import getpass
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml

from . import catalog as CAT
from . import expr as EX
from . import normalize as N
from . import pbir as P
from .check import Finding
from ..model import AgentTable


def compute_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def compute_model_sha(model: N.Model) -> str:
    """Compute deterministic composite hash for model TMDL files."""
    h = hashlib.sha256()
    for t in sorted(model.tables, key=lambda x: x.get("name", "")):
        h.update(t.get("name", "").encode("utf-8"))
        for m in sorted(t.get("measures", []), key=lambda x: x.get("name", "")):
            h.update(f"{m.get('name')}:{m.get('expression')}".encode("utf-8"))
        for c in sorted(t.get("columns", []), key=lambda x: x.get("name", "")):
            h.update(f"{c.get('name')}:{c.get('dataType')}".encode("utf-8"))
    return h.hexdigest()


def parse_brief_file(spec_path: str | Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Extract frontmatter and embedded design_brief YAML block from Markdown file."""
    if not os.path.exists(spec_path):
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    with open(spec_path, encoding="utf-8-sig") as f:
        content = f.read()

    # Parse YAML frontmatter if present
    frontmatter = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2]
            except Exception:
                pass

    # Extract design_brief YAML block
    # Looks for ```yaml ... ``` under ## Design Brief: or design_brief in frontmatter
    design_brief = {}
    if "design_brief" in frontmatter and isinstance(frontmatter["design_brief"], dict):
        design_brief = frontmatter["design_brief"]
    else:
        # Match fenced code block under design brief
        m = re.search(r"(?:##\s*Design Brief[^\n]*\n+)?```(?:yaml|yml)\s*\n(.*?)```", body, re.DOTALL | re.I)
        if m:
            try:
                parsed = yaml.safe_load(m.group(1))
                if isinstance(parsed, dict):
                    design_brief = parsed.get("design_brief") or parsed
            except Exception:
                pass

    return frontmatter, design_brief, content


def check_brief(spec_path: str | Path, model_override: N.Model | None = None) -> list[Finding]:
    """Validate report spec and design brief YAML against layout and model rules."""
    findings: list[Finding] = []
    fm, brief, _ = parse_brief_file(spec_path)
    spec_str = str(spec_path).replace("\\", "/")

    if not brief:
        findings.append(Finding("error", "brief-missing", spec_str, "",
                               "No design_brief YAML block found in spec",
                               "embed ```yaml design_brief: ... ``` in report-spec.md"))
        return findings

    # Resolve Model for field validation
    pbip_path = fm.get("pbip")
    model = model_override
    if not model and pbip_path and os.path.exists(pbip_path):
        try:
            model, _, _ = N.load_all(pbip_path, legacy_ok=True)
        except Exception:
            pass

    idx = N.ModelIndex(model) if model else None

    # Load visual catalog for type validation
    cat = CAT.load_catalog()
    visual_types = cat.get("visuals", {})

    pages = brief.get("pages") or []
    if not pages:
        findings.append(Finding("error", "brief-pages-empty", spec_str, "",
                               "design_brief contains no pages", "define at least one page under pages[]"))
        return findings

    for p_idx, page in enumerate(pages):
        page_name = page.get("name") or page.get("title") or f"page_{p_idx + 1}"
        page_loc = f"{spec_str} -> page[{page_name}]"

        # 1. Page title non-empty
        if not page.get("title") and not page.get("name"):
            findings.append(Finding("error", "brief-page-title-empty", page_loc, page_name,
                                   "Page title or name is missing or empty", "provide a descriptive title"))

        # 2. Canvas dimensions valid
        canvas = page.get("canvas") or {}
        cw = canvas.get("width", 1280)
        ch = canvas.get("height", 720)
        if cw <= 0 or ch <= 0:
            findings.append(Finding("error", "brief-canvas-invalid", page_loc, f"{cw}x{ch}",
                                   f"Invalid canvas dimensions ({cw}x{ch})", "set positive width and height (e.g. 1280x720)"))

        # 3. Layout contract & placements
        contract = page.get("layout_contract") or {}
        if not contract:
            findings.append(Finding("error", "brief-layout-contract-missing", page_loc, page_name,
                                   "Page is missing layout_contract", "define grid, regions, and placements"))
            continue

        placements = contract.get("placements") or []
        if not placements:
            findings.append(Finding("warning", "brief-placements-empty", page_loc, page_name,
                                   "layout_contract has no visual placements", "define visual placements"))
            continue

        # Check placements bounds and types
        placement_rects = []
        for v in placements:
            vid = v.get("visual_id") or v.get("id") or "unnamed"
            vtype = v.get("type") or v.get("visualType")
            vpos = v.get("position") or {}
            x = vpos.get("x", 0)
            y = vpos.get("y", 0)
            w = vpos.get("width", 0)
            h = vpos.get("height", 0)
            v_loc = f"{page_loc} -> {vid}"

            # Validate visual type exists in catalog
            if not vtype or vtype not in visual_types:
                findings.append(Finding("error", "brief-visual-type-invalid", v_loc, str(vtype),
                                       f"Visual type '{vtype}' does not exist in PBIR catalog",
                                       "run `ad-pbip catalog list` for valid types"))
            elif visual_types[vtype].get("legacy"):
                repl = visual_types[vtype].get("replacement")
                findings.append(Finding("warning", "brief-visual-type-legacy", v_loc, str(vtype),
                                       f"Visual uses deprecated legacy type '{vtype}'",
                                       f"use modern replacement '{repl}'"))

            # Canvas boundary check
            if x < 0 or y < 0 or (x + w > cw) or (y + h > ch):
                findings.append(Finding("error", "position-off-canvas", v_loc, f"{x},{y},{w},{h}",
                                       f"Placement bounds (x={x}, y={y}, w={w}, h={h}) extend outside canvas ({cw}x{ch})",
                                       "adjust placement coordinates to fit inside canvas"))

            # Dominant single-value card check: if area > 30% of canvas
            canvas_area = cw * ch
            v_area = w * h
            fields = v.get("fields") or []
            if (vtype == "card" or (vtype == "cardVisual" and len(fields) <= 1)) and canvas_area > 0:
                if (v_area / canvas_area) > 0.30:
                    findings.append(Finding("error", "brief-dominant-bare-card", v_loc, vid,
                                           f"Single-metric card occupies {round(v_area/canvas_area*100)}% of canvas",
                                           "cards should be concise callouts; use chart or multi-metric card for dominant regions"))

            # Field resolution against model
            if idx and fields:
                for f_raw in fields:
                    try:
                        is_m = f_raw.strip().startswith("[") or "(" in f_raw
                        if not is_m and idx:
                            m_prop = re.match(r"^(?:'([^']+)'|([A-Za-z0-9_]+))?\[([^\]]+)\]$", f_raw.strip())
                            if m_prop:
                                ent = m_prop.group(1) or m_prop.group(2)
                                p = m_prop.group(3)
                                if (ent and p in idx.tables.get(ent, {}).get("measures", set())) or (p in idx.measure_table):
                                    is_m = True
                        encoded = EX.encode_expr(f_raw, is_measure=is_m)
                        refs = list(P.walk_refs(encoded))
                        for r in refs:
                            ok, why = idx.resolve(r)
                            if not ok:
                                findings.append(Finding("error", "field-unresolved", v_loc, r.label(),
                                                       f"Field '{r.label()}' not found in model: {why}",
                                                       "verify spelling against MODEL.md"))
                    except Exception as e:
                        findings.append(Finding("error", "field-encode-failed", v_loc, str(f_raw),
                                               f"Failed to parse field expression: {e}", "use 'Table'[Column] format"))

            placement_rects.append((vid, x, y, w, h))

        # 4. No overlaps (rectangle collision math)
        for i in range(len(placement_rects)):
            for j in range(i + 1, len(placement_rects)):
                id1, x1, y1, w1, h1 = placement_rects[i]
                id2, x2, y2, w2, h2 = placement_rects[j]
                ox = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
                oy = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
                if ox > 0 and oy > 0:
                    findings.append(Finding("error", "overlap", page_loc, f"{id1} & {id2}",
                                           f"Placements '{id1}' and '{id2}' overlap by {ox}x{oy}px",
                                           "adjust layout_contract coordinates to eliminate overlap"))

        # 5. Space audit check
        audit = page.get("space_audit")
        if not audit:
            findings.append(Finding("warning", "brief-space-audit-missing", page_loc, page_name,
                                   "Page is missing space_audit breakdown", "define space_audit percentages"))
        else:
            total_pct = sum(float(val) for val in audit.values() if isinstance(val, (int, float)))
            if total_pct > 100.5:
                findings.append(Finding("error", "brief-space-audit-sum", page_loc, f"{total_pct}%",
                                       f"space_audit sums to {total_pct}%, which exceeds 100%",
                                       "rebalance space_audit percentages to sum <= 100%"))

    return findings


def get_approval_path(spec_path: str | Path) -> Path:
    p = Path(spec_path)
    stem = p.stem
    if stem.endswith("-report-spec"):
        key = stem[:-len("-report-spec")]
    else:
        key = stem
    return p.parent / f"{key}.approval.json"


def brief_status(spec_path: str | Path, model_override: N.Model | None = None) -> str:
    """Return status: current | stale | missing."""
    app_file = get_approval_path(spec_path)
    if not app_file.exists():
        return "missing"

    try:
        with open(app_file, encoding="utf-8") as f:
            app_data = json.load(f)
    except Exception:
        return "missing"

    cur_spec_sha = compute_file_sha256(spec_path)
    if app_data.get("spec_sha256") != cur_spec_sha:
        return "stale"

    fm, _, _ = parse_brief_file(spec_path)
    pbip_path = fm.get("pbip")
    if model_override:
        cur_model_sha = compute_model_sha(model_override)
        if app_data.get("model_sha") and app_data.get("model_sha") != cur_model_sha:
            return "stale"
    elif pbip_path and os.path.exists(pbip_path):
        try:
            m, _, _ = N.load_all(pbip_path, legacy_ok=True)
            cur_model_sha = compute_model_sha(m)
            if app_data.get("model_sha") and app_data.get("model_sha") != cur_model_sha:
                return "stale"
        except Exception:
            pass

    return "current"


def approve_brief(spec_path: str | Path, model_override: N.Model | None = None,
                  stdin: Any = None, stdout: Any = None) -> dict[str, Any]:
    """Terminal-only human approval gate for report specification."""
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout

    # Terminal-only check
    is_tty = getattr(in_stream, "isatty", lambda: False)() and getattr(out_stream, "isatty", lambda: False)()
    if not is_tty:
        raise RuntimeError("brief approve must be run interactively in a terminal (human-only approval gate).")

    # Run check first
    findings = check_brief(spec_path, model_override=model_override)
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise ValueError(f"Cannot approve brief with {len(errors)} error(s): {errors[0].message}")

    fm, brief, _ = parse_brief_file(spec_path)
    spec_sha = compute_file_sha256(spec_path)

    # Resolve model sha
    model_sha = fm.get("model_sha", "")
    if not model_sha:
        pbip_path = fm.get("pbip")
        if model_override:
            model_sha = compute_model_sha(model_override)
        elif pbip_path and os.path.exists(pbip_path):
            try:
                m, _, _ = N.load_all(pbip_path, legacy_ok=True)
                model_sha = compute_model_sha(m)
            except Exception:
                pass

    pages = brief.get("pages", [])
    out_stream.write(f"\nReport Specification Approval Gate\n")
    out_stream.write(f"Spec file:    {spec_path}\n")
    out_stream.write(f"Spec SHA256:  {spec_sha}\n")
    out_stream.write(f"Model SHA:    {model_sha[:16] if model_sha else 'unknown'}\n")
    out_stream.write(f"Pages ({len(pages)}):\n")
    for p in pages:
        p_name = p.get("title") or p.get("name")
        p_count = len((p.get("layout_contract") or {}).get("placements", []))
        out_stream.write(f"  - {p_name} ({p_count} visual placements)\n")
    out_stream.write("\n")
    out_stream.flush()

    answer = in_stream.readline().strip()
    if answer.lower() not in ("y", "yes"):
        return {"ok": False, "approved": False, "message": "Approval aborted by user"}

    user = getpass.getuser()
    now_iso = datetime.now(timezone.utc).isoformat()
    approval_data = {
        "spec_file": str(spec_path).replace("\\", "/"),
        "spec_sha256": spec_sha,
        "model_sha": model_sha,
        "by": user,
        "at": now_iso,
    }

    app_file = get_approval_path(spec_path)
    os.makedirs(app_file.parent, exist_ok=True)
    with open(app_file, "w", encoding="utf-8") as f:
        json.dump(approval_data, f, indent=2)

    return {
        "ok": True,
        "approved": True,
        "approval_file": str(app_file).replace("\\", "/"),
        "spec_sha256": spec_sha,
        "by": user,
        "at": now_iso,
    }
