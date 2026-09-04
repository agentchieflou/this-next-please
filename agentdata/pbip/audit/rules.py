"""Semantic model audit rules and diagnostics.

Implements classic Power BI best-practice rules:
1. columns-not-hidden-used-in-measures
2. summarize-by-numeric-key
3. missing-format-string
4. bi-directional-relationship
5. unused-columns
6. dax-anti-pattern-filter-all
7. implicit-measures-used
8. missing-description-used-measure
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Any
from .. import normalize as N
from .. import pbir as P
from .. import tmdl as T


@dataclass
class AuditFinding:
    rule_id: str
    severity: str  # error | warning
    what: str
    why: str
    obj: str
    where: str
    fix: dict[str, Any] | None = None

    def row(self) -> dict[str, Any]:
        return {
            "rule": self.rule_id,
            "severity": self.severity,
            "object": self.obj,
            "where": self.where,
            "what": self.what,
            "why": self.why,
            "fix": json.dumps(self.fix) if self.fix else "",
        }


def _extract_column_refs_from_dax(dax_expr: str) -> set[tuple[str | None, str]]:
    """Extract (table, column) or (None, column) references from DAX string."""
    refs = set()
    # Match 'Table'[Column] or Table[Column]
    for m in re.finditer(r"(?:'([^']+)'|([A-Za-z0-9_]+))\[([^\]]+)\]", dax_expr):
        tbl = m.group(1) or m.group(2)
        col = m.group(3)
        refs.add((tbl, col))
    return refs


def audit_model(model: N.Model, report: P.Report | None = None,
                trace_evidence: list[dict[str, Any]] | None = None) -> list[AuditFinding]:
    """Run 8+ model audit rules against normalized Model and optional Report."""
    findings: list[AuditFinding] = []

    # Map tables and measures
    all_table_names = set(t["name"] for t in model.tables)
    measure_column_inputs: set[tuple[str, str]] = set()
    all_referenced_columns: set[tuple[str, str]] = set()
    all_measures: list[dict[str, Any]] = []

    # 1. Collect all measures and their column references
    for t in model.tables:
        tname = t["name"]
        for m in t.get("measures", []):
            m_copy = dict(m)
            m_copy["table"] = tname
            all_measures.append(m_copy)
            expr = m.get("expression") or ""
            dax_refs = _extract_column_refs_from_dax(expr)
            for tbl, col in dax_refs:
                target_tbl = tbl or tname
                measure_column_inputs.add((target_tbl, col))
                all_referenced_columns.add((target_tbl, col))

    # Also collect relationship refs
    for rel in model.relationships:
        f_tbl, f_col = rel.get("fromTable"), rel.get("fromColumn")
        t_tbl, t_col = rel.get("toTable"), rel.get("toColumn")
        if f_tbl and f_col:
            all_referenced_columns.add((f_tbl, f_col))
        if t_tbl and t_col:
            all_referenced_columns.add((t_tbl, t_col))

    # Also collect hierarchy refs
    for t in model.tables:
        tname = t["name"]
        for h in t.get("hierarchies", []):
            for lvl in h.get("levels", []):
                col_name = lvl.get("column")
                if col_name:
                    all_referenced_columns.add((tname, col_name))

    # Report visuals references
    report_used_measures: set[tuple[str | None, str]] = set()
    report_used_columns: set[tuple[str, str]] = set()
    implicit_measure_visuals: list[dict[str, Any]] = []

    if report:
        for page in report.pages:
            p_name = page.name or page.id
            for v in page.visuals:
                v_title = v.title or v.id
                v_loc = f"{p_name} -> {v_title}"
                for r in v.refs:
                    if r.kind == "measure":
                        report_used_measures.add((r.entity, r.prop))
                    elif r.kind == "column":
                        if r.entity:
                            report_used_columns.add((r.entity, r.prop))
                            all_referenced_columns.add((r.entity, r.prop))

                # Check for implicit measures in visual queries
                for proj in v.projections:
                    field_obj = proj.get("field") or {}
                    if "Aggregation" in field_obj:
                        agg = field_obj["Aggregation"]
                        inner = agg.get("Expression", {})
                        if "Column" in inner:
                            c_prop = inner["Column"].get("Property")
                            c_ent = inner["Column"].get("Expression", {}).get("SourceRef", {}).get("Entity")
                            if c_prop and c_ent:
                                implicit_measure_visuals.append({
                                    "table": c_ent,
                                    "column": c_prop,
                                    "visual": v_title,
                                    "where": v_loc,
                                })

    # RULE 1: columns-not-hidden-used-in-measures
    for t in model.tables:
        tname = t["name"]
        for c in t.get("columns", []):
            cname = c["name"]
            if (tname, cname) in measure_column_inputs:
                is_hidden = c.get("isHidden") is True
                if not is_hidden:
                    findings.append(AuditFinding(
                        rule_id="columns-not-hidden-used-in-measures",
                        severity="warning",
                        what=f"Column '{tname}'[{cname}] feeds measure(s) but is not hidden",
                        why="Columns that only serve as measure inputs should be hidden to encourage explicit measure usage",
                        obj=f"'{tname}'[{cname}]",
                        where=f"tables/{tname}.tmdl",
                        fix={"op": "object.hide", "table": tname, "objectType": "column", "name": cname, "isHidden": True},
                    ))

    # RULE 2: summarize-by-numeric-key
    key_suffixes = ("key", "id", "number")
    for t in model.tables:
        tname = t["name"]
        for c in t.get("columns", []):
            cname = c["name"]
            dtype = str(c.get("dataType", "")).lower()
            sum_by = str(c.get("summarizeBy", "")).lower()
            lower_name = cname.lower()
            is_key_name = any(lower_name.endswith(k) for k in key_suffixes)
            is_numeric = dtype in ("int64", "decimal", "double", "integer") or not dtype
            if is_key_name and is_numeric and sum_by not in ("none", ""):
                findings.append(AuditFinding(
                    rule_id="summarize-by-numeric-key",
                    severity="warning",
                    what=f"Numeric key column '{tname}'[{cname}] has summarizeBy: {sum_by}",
                    why="Numeric ID and Key columns should have summarizeBy: none to avoid accidental summing",
                    obj=f"'{tname}'[{cname}]",
                    where=f"tables/{tname}.tmdl",
                    fix={"op": "object.describe", "table": tname, "objectType": "column", "name": cname, "description": "Key column"},
                ))

    # RULE 3: missing-format-string
    for m in all_measures:
        tname = m["table"]
        mname = m["name"]
        fmt = m.get("formatString")
        if not fmt:
            findings.append(AuditFinding(
                rule_id="missing-format-string",
                severity="warning",
                what=f"Measure '{tname}'[{mname}] has no formatString",
                why="Measures must have explicit format strings to display consistently across visuals",
                obj=f"'{tname}'[{mname}]",
                where=f"tables/{tname}.tmdl",
                fix={"op": "measure.set", "table": tname, "name": mname, "formatString": "#,##0"},
            ))

    # RULE 4: bi-directional-relationship
    for rel in model.relationships:
        f_tbl = rel.get("fromTable")
        f_col = rel.get("fromColumn")
        t_tbl = rel.get("toTable")
        t_col = rel.get("toColumn")
        c_filter = str(rel.get("crossFilteringBehavior", "")).lower()
        if c_filter in ("bothdirections", "both"):
            rel_label = f"{f_tbl}.{f_col} <-> {t_tbl}.{t_col}"
            findings.append(AuditFinding(
                rule_id="bi-directional-relationship",
                severity="warning",
                what=f"Relationship '{rel_label}' is bi-directional",
                why="Bi-directional relationships cause ambiguous filtering paths, circular dependencies, and high query latency",
                obj=rel_label,
                where="relationships.tmdl",
                fix={"op": "relationship.set", "fromTable": f_tbl, "fromColumn": f_col,
                     "toTable": t_tbl, "toColumn": t_col, "crossFilteringBehavior": "oneDirection"},
            ))

    # RULE 5: unused-columns
    for t in model.tables:
        tname = t["name"]
        for c in t.get("columns", []):
            cname = c["name"]
            is_key = c.get("isKey") is True
            if (tname, cname) not in all_referenced_columns and not is_key:
                findings.append(AuditFinding(
                    rule_id="unused-columns",
                    severity="warning",
                    what=f"Column '{tname}'[{cname}] is not referenced by any measure, hierarchy, relationship, or visual",
                    why="Unused columns bloat in-memory storage in VertiPaq and slow down model refreshes",
                    obj=f"'{tname}'[{cname}]",
                    where=f"tables/{tname}.tmdl",
                    fix={"op": "object.delete", "table": tname, "objectType": "column", "name": cname},
                ))

    # RULE 6: dax-anti-pattern-filter-all
    filter_all_pat = re.compile(r"FILTER\s*\(\s*ALL\s*\(\s*(?:'([^']+)'|([A-Za-z0-9_]+))\s*\)", re.I)
    for m in all_measures:
        tname = m["table"]
        mname = m["name"]
        expr = m.get("expression") or ""
        match = filter_all_pat.search(expr)
        if match:
            target = match.group(1) or match.group(2)
            findings.append(AuditFinding(
                rule_id="dax-anti-pattern-filter-all",
                severity="warning",
                what=f"Measure '{tname}'[{mname}] uses FILTER(ALL('{target}')) across whole table",
                why="Filtering on an entire table eliminates VertiPaq column indexes; filter the specific column or use KEEPFILTERS",
                obj=f"'{tname}'[{mname}]",
                where=f"tables/{tname}.tmdl",
                fix={"op": "measure.set", "table": tname, "name": mname,
                     "expression": f"/* optimized */ CALCULATE([{mname}], KEEPFILTERS('{target}'[Column] = ...))"},
            ))

    # RULE 7: implicit-measures-used
    for item in implicit_measure_visuals:
        tname = item["table"]
        cname = item["column"]
        vis = item["visual"]
        loc = item["where"]
        findings.append(AuditFinding(
            rule_id="implicit-measures-used",
            severity="warning",
            what=f"Visual '{vis}' uses implicit aggregation on column '{tname}'[{cname}]",
            why="Implicit measures cannot be formatted, reused in DAX calculations, or governed",
            obj=f"'{tname}'[{cname}]",
            where=loc,
            fix={"op": "measure.set", "table": tname, "name": f"Total {cname}", "expression": f"SUM('{tname}'[{cname}])"},
        ))

    # RULE 8: missing-description-used-measure
    for m in all_measures:
        tname = m["table"]
        mname = m["name"]
        is_used = (tname, mname) in report_used_measures or (None, mname) in report_used_measures
        has_desc = bool(m.get("description"))
        if is_used and not has_desc:
            findings.append(AuditFinding(
                rule_id="missing-description-used-measure",
                severity="warning",
                what=f"Report-used measure '{tname}'[{mname}] has no description",
                why="Measures exposed to report users and Copilot semantic search require descriptions explaining business rules",
                obj=f"'{tname}'[{mname}]",
                where=f"tables/{tname}.tmdl",
                fix={"op": "object.describe", "table": tname, "objectType": "measure", "name": mname, "description": f"Calculates {mname}"},
            ))

    return findings
