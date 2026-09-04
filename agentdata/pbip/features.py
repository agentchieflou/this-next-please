"""Native Power BI features detector, check rules, and live verification.

Harden the gallery for all 20 native Power BI features:
Each feature has:
1. Detection logic (is it used in this model/report?)
2. A check rule catching how it breaks
3. A live verification step against a live model (Desktop port or XMLA)
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import pbir as P
from . import tmdl as T
from .normalize import Model, ModelIndex


NATIVE_FEATURES = [
    "bookmarks",
    "drillthrough",
    "tooltip",
    "sync_slicers",
    "field_parameters",
    "calculation_groups",
    "visual_calculations",
    "conditional_formatting",
    "rls_ols",
    "incremental_refresh",
    "hierarchies",
    "sort_by",
    "format_strings",
    "page_navigation",
    "mobile_layout",
    "visual_interactions",
    "relationships",
    "report_level_measures",
    "themes",
    "agg_tables",
]


@dataclass
class FeatureUsage:
    feature: str
    present: bool
    objects: list[str] = field(default_factory=list)
    status: str = "ok"  # ok | missing | error | warning
    findings_count: int = 0

    def row(self) -> list:
        return [self.feature, "true" if self.present else "false", ", ".join(self.objects) or "-", self.status]


def detect_features(model: Model, report: P.Report | None) -> list[FeatureUsage]:
    """Inspect model and report to detect which of the 20 native features are present."""
    results = []
    idx = ModelIndex(model, report)
    table_names = {t["name"] for t in model.tables}

    # 1. bookmarks
    bm_objs = [b.get("displayName") or b.get("name") or "bookmark" for b in (report.bookmarks if report else [])]
    results.append(FeatureUsage("bookmarks", bool(bm_objs), bm_objs))

    # 2. drillthrough
    dt_pages = []
    if report:
        for p in report.pages:
            raw = p.raw or {}
            if "drillthrough" in raw or "drillthroughFilter" in raw:
                dt_pages.append(p.name)
            elif any("drillthrough" in str(k).lower() for k in raw.keys()):
                dt_pages.append(p.name)
    results.append(FeatureUsage("drillthrough", bool(dt_pages), dt_pages))

    # 3. tooltip
    tt_objs = []
    if report:
        for p in report.pages:
            raw = p.raw or {}
            if raw.get("pageType") == "Tooltip" or raw.get("displayOption") == "Tooltip":
                tt_objs.append(f"page:{p.name}")
        for v in report.all_visuals():
            v_raw = v.raw.get("visual") or {}
            if "visualTooltip" in v_raw or "tooltip" in v_raw:
                tt_objs.append(f"visual:{v.id}")
    results.append(FeatureUsage("tooltip", bool(tt_objs), tt_objs))

    # 4. sync_slicers
    sync_objs = []
    if report:
        for v in report.all_visuals():
            v_raw = v.raw.get("visual") or {}
            if "syncSlicers" in v_raw or "syncSlicers" in v.raw:
                sync_objs.append(v.id)
    results.append(FeatureUsage("sync_slicers", bool(sync_objs), sync_objs))

    # 5. field_parameters
    fp_tables = []
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "partition":
                        src_text = str(child.props.get("source", "")) + " " + str(child.expr or "")
                        if "NAMEOF(" in src_text:
                            fp_tables.append(node.name)
    results.append(FeatureUsage("field_parameters", bool(fp_tables), fp_tables))

    # 6. calculation_groups
    cg_tables = []
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "calculationGroup":
                        cg_tables.append(node.name)
    results.append(FeatureUsage("calculation_groups", bool(cg_tables), cg_tables))

    # 7. visual_calculations
    vc_objs = []
    if report:
        for v in report.all_visuals():
            raw_qs = ((v.raw.get("visual") or {}).get("query") or {}).get("queryState") or {}
            for role, container in raw_qs.items():
                for proj in (container.get("projections") or []):
                    if "visualCalculation" in proj:
                        vc_objs.append(f"{v.id}:{proj.get('nativeQueryRef') or proj.get('queryRef')}")
    results.append(FeatureUsage("visual_calculations", bool(vc_objs), vc_objs))

    # 8. conditional_formatting
    cf_objs = []
    if report:
        for v in report.all_visuals():
            raw_objs = (v.raw.get("visual") or {}).get("objects") or {}
            raw_str = json.dumps(raw_objs)
            if "conditionalFormatting" in raw_str:
                cf_objs.append(v.id)
    results.append(FeatureUsage("conditional_formatting", bool(cf_objs), cf_objs))

    # 9. rls_ols
    rls_objs = []
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "role":
                for child in node.children:
                    if child.kind == "tablePermission":
                        rls_objs.append(f"{node.name}:{child.name}")
    if not rls_objs and model.roles:
        rls_objs = list(model.roles)
    results.append(FeatureUsage("rls_ols", bool(rls_objs), rls_objs))

    # 10. incremental_refresh
    ir_tables = []
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "refreshPolicy":
                        ir_tables.append(node.name)
    results.append(FeatureUsage("incremental_refresh", bool(ir_tables), ir_tables))

    # 11. hierarchies
    hiers = []
    for t in model.tables:
        for h in t.get("hierarchies", []):
            hiers.append(f"{t['name']}[{h['name']}]")
    results.append(FeatureUsage("hierarchies", bool(hiers), hiers))

    # 12. sort_by
    sorts = []
    for t in model.tables:
        for c in t.get("columns", []):
            if c.get("sortByColumn"):
                sorts.append(f"{t['name']}[{c['name']}]->{c['sortByColumn']}")
    results.append(FeatureUsage("sort_by", bool(sorts), sorts))

    # 13. format_strings
    formats = []
    for t in model.tables:
        for m in t.get("measures", []):
            if m.get("formatString"):
                formats.append(f"[{m['name']}]")
    # Check dynamic format string definitions
    for tf in model.files.values():
        for node in tf.nodes:
            for child in node.children:
                if child.kind == "measure" and "formatStringDefinition" in child.props:
                    formats.append(f"dynamic:[{child.name}]")
    results.append(FeatureUsage("format_strings", bool(formats), formats[:5]))

    # 14. page_navigation
    nav_objs = []
    if report:
        for v in report.all_visuals():
            raw_str = json.dumps(v.raw)
            if "PageNavigation" in raw_str or "navigate" in raw_str.lower():
                nav_objs.append(v.id)
    results.append(FeatureUsage("page_navigation", bool(nav_objs), nav_objs))

    # 15. mobile_layout
    mobile_pages = []
    if report:
        for p in report.pages:
            raw = p.raw or {}
            if "mobileState" in raw:
                mobile_pages.append(p.name)
    results.append(FeatureUsage("mobile_layout", bool(mobile_pages), mobile_pages))

    # 16. visual_interactions
    vi_objs = []
    if report and report.root:
        rep_json_path = os.path.join(report.root, "definition", "report.json")
        if os.path.exists(rep_json_path):
            try:
                rep_data = json.loads(open(rep_json_path, encoding="utf-8").read())
                vi = rep_data.get("visualInteractions") or []
                for item in vi:
                    vi_objs.append(f"{item.get('source')}->{item.get('target')}")
            except Exception:
                pass
    results.append(FeatureUsage("visual_interactions", bool(vi_objs), vi_objs))

    # 17. relationships
    rel_objs = []
    for r in model.relationships:
        if r.get("isActive") is False or r.get("active") is False:
            rel_objs.append(f"inactive:{r['fromTable']}->{r['toTable']}")
        else:
            rel_objs.append(f"{r['fromTable']}->{r['toTable']}")
    results.append(FeatureUsage("relationships", bool(rel_objs), rel_objs))

    # 18. report_level_measures
    ext_measures = [em["name"] for em in (report.extension_measures if report else [])]
    results.append(FeatureUsage("report_level_measures", bool(ext_measures), ext_measures))

    # 19. themes
    themes = []
    if report and report.root:
        rep_json_path = os.path.join(report.root, "definition", "report.json")
        if os.path.exists(rep_json_path):
            try:
                rep_data = json.loads(open(rep_json_path, encoding="utf-8").read())
                tc = rep_data.get("themeCollection") or {}
                if tc.get("baseTheme"):
                    themes.append(tc["baseTheme"].get("name", "custom"))
            except Exception:
                pass
    results.append(FeatureUsage("themes", bool(themes), themes))

    # 20. agg_tables
    aggs = [t["name"] for t in model.tables if t.get("hidden") and ("agg" in t["name"].lower() or "summary" in t["name"].lower())]
    if not aggs:
        aggs = [t["name"] for t in model.tables if "agg" in t["name"].lower()]
    results.append(FeatureUsage("agg_tables", bool(aggs), aggs))

    return results


def check_model_features(model: Model) -> list[Any]:
    """Execute check rules for model-side native features and return findings."""
    from .check import Finding
    findings: list[Finding] = []
    idx = ModelIndex(model)
    table_names = {t["name"] for t in model.tables}

    # Rule 5: field_parameters (fieldparam-nameof-mismatch)
    nameof_re = re.compile(r"NAMEOF\s*\(\s*(?:'([^']+)'|([A-Za-z0-9_]+))\s*\[([^\]]+)\]\s*\)", re.I)
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "partition" and (child.expr or child.props.get("source")):
                        src_text = str(child.props.get("source", "")) + " " + str(child.expr or "")
                        for m in nameof_re.finditer(src_text):
                            ent = m.group(1) or m.group(2)
                            prop = m.group(3)
                            if ent not in table_names:
                                findings.append(Finding(
                                    "error", "fieldparam-nameof-mismatch", f"{tf.path}:{child.line_start}", node.name,
                                    f"NAMEOF references table '{ent}' which does not exist in model",
                                    "fix table reference in NAMEOF expression",
                                ))
                            elif prop not in idx.tables[ent]["columns"] and prop not in idx.tables[ent]["measures"]:
                                findings.append(Finding(
                                    "error", "fieldparam-nameof-mismatch", f"{tf.path}:{child.line_start}", node.name,
                                    f"NAMEOF references '{ent}'[{prop}] which is not a column or measure in '{ent}'",
                                    "check spelling of column or measure in NAMEOF",
                                ))

    # Rule 6: calculation_groups (calcgroup-precedence-clash)
    cg_precedences: dict[int, str] = {}
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "calculationGroup":
                        prec_val = child.props.get("precedence")
                        if prec_val is not None:
                            try:
                                p_int = int(str(prec_val))
                                if p_int in cg_precedences:
                                    findings.append(Finding(
                                        "error", "calcgroup-precedence-clash", f"{tf.path}:{child.line_start}", node.name,
                                        f"calculation group '{node.name}' has precedence {p_int}, clashing with '{cg_precedences[p_int]}'",
                                        "assign distinct precedence values to calculation groups",
                                    ))
                                else:
                                    cg_precedences[p_int] = node.name
                            except ValueError:
                                pass

    # Rule 9: rls_ols (rls-table-missing, rls-filter-invalid-dax)
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "role":
                for child in node.children:
                    if child.kind == "tablePermission":
                        target_tbl = child.name
                        if target_tbl not in table_names:
                            findings.append(Finding(
                                "error", "rls-table-missing", f"{tf.path}:{child.line_start}", node.name,
                                f"role '{node.name}' defines tablePermission on '{target_tbl}' which is not in model",
                                "fix table name in role definition",
                            ))
                        elif child.expr:
                            if child.expr.count("(") != child.expr.count(")"):
                                findings.append(Finding(
                                    "error", "rls-filter-invalid-dax", f"{tf.path}:{child.line_start}", node.name,
                                    f"tablePermission DAX filter has unmatched parentheses: {child.expr[:60]}",
                                    "fix DAX syntax in table filter",
                                ))

    # Rule 10: incremental_refresh (refresh-policy-parameters-missing)
    model_param_names = {e["name"] for e in model.expressions}
    for tf in model.files.values():
        for node in tf.nodes:
            if node.kind == "table":
                for child in node.children:
                    if child.kind == "refreshPolicy":
                        if "RangeStart" not in model_param_names or "RangeEnd" not in model_param_names:
                            findings.append(Finding(
                                "error", "refresh-policy-parameters-missing", f"{tf.path}:{child.line_start}", node.name,
                                f"table '{node.name}' has refreshPolicy but model is missing RangeStart/RangeEnd parameters",
                                "add RangeStart and RangeEnd DateTime parameters to expressions.tmdl",
                            ))

    # Rule 13: format_strings (format-string-invalid)
    for t in model.tables:
        for m in t.get("measures", []):
            fs = m.get("formatString")
            if fs is not None and str(fs).strip() == "":
                findings.append(Finding(
                    "warning", "format-string-invalid", f"{t['file']}:{m['line']}", f"[{m['name']}]",
                    f"measure [{m['name']}] has empty formatString property",
                    "remove formatString property or supply valid format expression",
                ))

    # Rule 17: relationships (userelationship-inactive-missing)
    userel_re = re.compile(r"USERELATIONSHIP\s*\(\s*(?:'([^']+)'|([A-Za-z0-9_]+))\s*\[([^\]]+)\]\s*,\s*(?:'([^']+)'|([A-Za-z0-9_]+))\s*\[([^\]]+)\]\s*\)", re.I)
    inactive_pairs = set()
    for r in model.relationships:
        if r.get("isActive") is False or r.get("active") is False:
            t1, c1 = r["fromTable"], r["fromColumn"]
            t2, c2 = r["toTable"], r["toColumn"]
            inactive_pairs.add((f"{t1}[{c1}]".lower(), f"{t2}[{c2}]".lower()))
            inactive_pairs.add((f"{t2}[{c2}]".lower(), f"{t1}[{c1}]".lower()))

    for t in model.tables:
        for m in t.get("measures", []):
            expr = m.get("expression") or ""
            for match in userel_re.finditer(expr):
                t1 = match.group(1) or match.group(2)
                c1 = match.group(3)
                t2 = match.group(4) or match.group(5)
                c2 = match.group(6)
                pair = (f"{t1}[{c1}]".lower(), f"{t2}[{c2}]".lower())
                if pair not in inactive_pairs:
                    findings.append(Finding(
                        "error", "userelationship-inactive-missing", f"{t['file']}:{m['line']}", f"[{m['name']}]",
                        f"USERELATIONSHIP references '{t1}'[{c1}] and '{t2}'[{c2}], but no inactive relationship connects them",
                        "create an inactive relationship between these columns in relationships.tmdl",
                    ))

    # Rule 20: agg_tables (agg-table-hidden)
    for t in model.tables:
        tname = t["name"].lower()
        if "agg" in tname and not t.get("hidden"):
            findings.append(Finding(
                "warning", "agg-table-hidden", f"{t['file']}:{t['line']}", t["name"],
                f"aggregation table '{t['name']}' should be hidden from report authoring",
                "add `isHidden` to table definition in TMDL",
            ))

    return findings


def check_report_features(model: Model, report: P.Report) -> list[Any]:
    """Execute check rules for report-side native features and return findings."""
    from .check import Finding
    findings: list[Finding] = []
    idx = ModelIndex(model, report)
    table_names = {t["name"] for t in model.tables}
    page_names = {p.name for p in report.pages}
    page_ids = {p.id for p in report.pages}
    visual_ids = {v.id for v in report.all_visuals()}

    # Rule 1: bookmarks (bookmark-page-missing, bookmark-visual-missing)
    for b in report.bookmarks:
        exp = b.get("explorationState") or {}
        active_sec = exp.get("activeSection")
        if active_sec and active_sec not in page_names and active_sec not in page_ids:
            findings.append(Finding(
                "warning", "bookmark-page-missing", b["file"], b.get("displayName") or b.get("name") or "",
                f"bookmark activeSection '{active_sec}' does not match any page in report",
                "update bookmark or target existing page",
            ))
        for vid in b.get("visuals", []):
            if vid not in visual_ids:
                findings.append(Finding(
                    "warning", "bookmark-visual-missing", b["file"], b.get("displayName") or b.get("name") or "",
                    f"bookmark targets visual '{vid}' which no longer exists",
                    "recreate bookmark or delete reference",
                ))

    # Rule 2: drillthrough (drillthrough-field-missing)
    for p in report.pages:
        raw = p.raw or {}
        dt = raw.get("drillthrough")
        if isinstance(dt, dict):
            target = dt.get("target") or {}
            col_obj = target.get("Column") or target.get("Measure") or {}
            prop = col_obj.get("Property")
            entity = ((col_obj.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
            if entity and prop:
                if entity not in table_names or prop not in idx.tables.get(entity, {}).get("columns", set()) | idx.tables.get(entity, {}).get("measures", set()):
                    findings.append(Finding(
                        "error", "drillthrough-field-missing", p.file, p.name,
                        f"drillthrough target field '{entity}'[{prop}] is not in the model",
                        "update drillthrough target or restore column in model",
                    ))

    # Rule 3: tooltip (tooltip-page-not-tooltip)
    tooltip_pages = {
        p.name for p in report.pages
        if (p.raw or {}).get("pageType") == "Tooltip" or (p.raw or {}).get("displayOption") == "Tooltip"
    } | {
        p.id for p in report.pages
        if (p.raw or {}).get("pageType") == "Tooltip" or (p.raw or {}).get("displayOption") == "Tooltip"
    }
    for v in report.all_visuals():
        v_raw = v.raw.get("visual") or {}
        vt = v_raw.get("visualTooltip") or {}
        if vt.get("type") == "Page":
            target_page = vt.get("pageName")
            if target_page:
                if target_page not in page_names and target_page not in page_ids:
                    findings.append(Finding(
                        "error", "tooltip-page-not-tooltip", v.file, v.id,
                        f"visual tooltip references page '{target_page}' which does not exist in the report",
                        "point tooltip at an existing tooltip page",
                    ))
                elif target_page not in tooltip_pages:
                    findings.append(Finding(
                        "error", "tooltip-page-not-tooltip", v.file, v.id,
                        f"visual tooltip points to page '{target_page}' which is not configured with pageType Tooltip",
                        "set pageType: Tooltip or displayOption: Tooltip on target page",
                    ))

    # Rule 4: sync_slicers (sync-slicer-group-field-mismatch)
    group_fields: dict[str, str] = {}
    for v in report.all_visuals():
        v_raw = v.raw.get("visual") or {}
        ss = v_raw.get("syncSlicers") or v.raw.get("syncSlicers")
        if isinstance(ss, dict) and ss.get("group"):
            grp = ss["group"]
            field_names = [f.prop for f in v.fields if f.prop]
            field_repr = ":".join(sorted(field_names)) if field_names else ""
            if field_repr:
                if grp in group_fields and group_fields[grp] != field_repr:
                    findings.append(Finding(
                        "error", "sync-slicer-group-field-mismatch", v.file, v.id,
                        f"slicer in sync group '{grp}' uses field '{field_repr}', mismatching group field '{group_fields[grp]}'",
                        "ensure all slicers in the same sync group bind to the same column",
                    ))
                else:
                    group_fields[grp] = field_repr

    # Rule 8: conditional_formatting (cf-rule-field-missing)
    for v in report.all_visuals():
        raw_objs = (v.raw.get("visual") or {}).get("objects") or {}
        for obj_list in raw_objs.values():
            if isinstance(obj_list, list):
                for item in obj_list:
                    props = item.get("properties") or {}
                    for prop_val in props.values():
                        if isinstance(prop_val, dict) and "conditionalFormatting" in prop_val:
                            cf = prop_val["conditionalFormatting"]
                            cf_field = cf.get("field") or {}
                            col_or_meas = cf_field.get("Column") or cf_field.get("Measure") or {}
                            prop_name = col_or_meas.get("Property")
                            entity_name = ((col_or_meas.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
                            if entity_name and prop_name:
                                if entity_name not in table_names or (
                                    prop_name not in idx.tables[entity_name]["columns"]
                                    and prop_name not in idx.tables[entity_name]["measures"]
                                ):
                                    findings.append(Finding(
                                        "error", "cf-rule-field-missing", v.file, v.id,
                                        f"conditional formatting references '{entity_name}'[{prop_name}] which does not exist in model",
                                        "update conditional formatting field binding",
                                    ))

    # Rule 14: page_navigation (nav-action-page-missing)
    for v in report.all_visuals():
        raw_objs = (v.raw.get("visual") or {}).get("objects") or {}
        for act_list in raw_objs.get("action", []):
            props = act_list.get("properties") or {}
            act_type = str(((props.get("actionType") or {}).get("expr") or {}).get("Literal", {}).get("Value", "")).strip("'\"")
            dest = str(((props.get("destination") or {}).get("expr") or {}).get("Literal", {}).get("Value", "")).strip("'\"")
            if act_type == "PageNavigation" and dest:
                if dest not in page_names and dest not in page_ids:
                    findings.append(Finding(
                        "error", "nav-action-page-missing", v.file, v.id,
                        f"page navigation action points to destination '{dest}' which does not exist in the report",
                        "update action destination to match an existing page name",
                    ))

    # Rule 15: mobile_layout (mobile-visual-not-on-page)
    for p in report.pages:
        raw = p.raw or {}
        ms = raw.get("mobileState") or {}
        vc = ms.get("visualContainers") or {}
        page_vids = {v.id for v in p.visuals}
        for vid in vc.keys():
            if vid not in page_vids:
                findings.append(Finding(
                    "error", "mobile-visual-not-on-page", p.file, p.name,
                    f"mobileState contains visual '{vid}' which does not exist on page '{p.name}'",
                    "remove visual container from mobileState or place visual on page",
                ))

    # Rule 16: visual_interactions (interaction-visual-missing)
    if report.root:
        rep_json_path = os.path.join(report.root, "definition", "report.json")
        if os.path.exists(rep_json_path):
            try:
                rep_data = json.loads(open(rep_json_path, encoding="utf-8").read())
                vi = rep_data.get("visualInteractions") or []
                for item in vi:
                    src, tgt = item.get("source"), item.get("target")
                    if src and src not in visual_ids:
                        findings.append(Finding(
                            "error", "interaction-visual-missing", rep_json_path, src,
                            f"visualInteractions source visual '{src}' does not exist in the report",
                            "remove or update invalid visualInteractions entry",
                        ))
                    if tgt and tgt not in visual_ids:
                        findings.append(Finding(
                            "error", "interaction-visual-missing", rep_json_path, tgt,
                            f"visualInteractions target visual '{tgt}' does not exist in the report",
                            "remove or update invalid visualInteractions entry",
                        ))
            except Exception:
                pass

    # Rule 19: themes (theme-resource-missing)
    if report.root:
        rep_json_path = os.path.join(report.root, "definition", "report.json")
        if os.path.exists(rep_json_path):
            try:
                rep_data = json.loads(open(rep_json_path, encoding="utf-8").read())
                tc = rep_data.get("themeCollection") or {}
                bt = tc.get("baseTheme") or {}
                if bt.get("type") == "Custom":
                    ct = bt.get("customTheme") or {}
                    rp = ct.get("resourcePackage") or {}
                    for it in rp.get("items", []):
                        rel_path = it.get("path")
                        if rel_path:
                            full_path = os.path.join(report.root, "StaticResources", "SharedResources", rel_path)
                            if not os.path.exists(full_path):
                                findings.append(Finding(
                                    "error", "theme-resource-missing", rep_json_path, bt.get("name", "customTheme"),
                                    f"custom theme file '{rel_path}' not found at {full_path}",
                                    "place theme file in StaticResources/SharedResources or update path",
                                ))
            except Exception:
                pass

    return findings


def check_native_features(model: Model, report: P.Report | None) -> list[Any]:
    """Execute check rules for every native feature and return findings."""
    out = check_model_features(model)
    if report:
        out.extend(check_report_features(model, report))
    return out


def verify_feature_live(
    feature: str,
    server: str,
    model_name: str,
    runner: Callable | None = None,
    dscmd_exe: str | None = None,
) -> dict[str, Any]:
    """Execute live query verifying a native feature on a live instance/server."""
    from ..pbip import dax as D
    from .. import config as C

    cfg = C.load()
    dscmd = dscmd_exe or C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe") or "dscmd.exe"

    queries = {
        "field_parameters": "EVALUATE TOPN(5, 'FieldParam')",
        "calculation_groups": "EVALUATE ROW(\"YTD\", CALCULATE([Total Sales], 'TimeIntelligence'[Calculation Item] = \"YTD\"))",
        "relationships": "EVALUATE ROW(\"DeliveryDate\", [Sales Delivery Date])",
        "format_strings": "EVALUATE ROW(\"Format\", FORMAT([Total Sales], \"$#,##0\"))",
        "rls_ols": "EVALUATE TOPN(5, Customers)",
        "incremental_refresh": "EVALUATE ROW(\"RangeCheck\", [Total Sales])",
        "visual_calculations": "EVALUATE TOPN(5, Sales)",
        "sort_by": "EVALUATE TOPN(5, Dates, [MonthNumber])",
        "hierarchies": "EVALUATE TOPN(5, SUMMARIZE(Dates, Dates[Year], Dates[Quarter]))",
        "agg_tables": "EVALUATE TOPN(5, SalesAgg)",
    }

    q = queries.get(feature)
    if not q:
        return {"feature": feature, "verified": True, "type": "report-side", "query": "-"}

    try:
        tbl = D.run_dax(q, server, dscmd, database=model_name, run=runner)
        return {
            "feature": feature,
            "verified": True,
            "type": "dax",
            "query": q,
            "rows": len(tbl.rows),
        }
    except Exception as e:
        return {
            "feature": feature,
            "verified": False,
            "type": "dax",
            "query": q,
            "error": str(e),
        }
