"""Copilot AI Readiness audit: evaluates semantic model metadata for Copilot / Q&A.

Scored checklist:
- Descriptions on tables, columns, and measures
- Hidden hygiene (IDs, foreign keys hidden from end-user view)
- Synonyms and linguistic schema
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .. import normalize as N


@dataclass
class CopilotCheckItem:
    category: str
    target: str
    status: str  # pass | fail | info
    points_earned: float
    points_max: float
    detail: str
    fix: dict[str, Any] | None = None


@dataclass
class CopilotAuditResult:
    score: int  # 0 to 100
    total_checks: int
    passed_checks: int
    failed_checks: int
    items: list[CopilotCheckItem]

    def summary(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "total_checks": self.total_checks,
            "passed": self.passed_checks,
            "failed": self.failed_checks,
            "items": [
                {
                    "category": it.category,
                    "target": it.target,
                    "status": it.status,
                    "detail": it.detail,
                }
                for it in self.items
            ],
        }


def audit_copilot(model: N.Model) -> CopilotAuditResult:
    """Evaluate model readiness for Copilot and AI semantic query generation."""
    items: list[CopilotCheckItem] = []

    # 1. Table Descriptions (20 pts max)
    tables = model.tables
    t_count = max(1, len(tables))
    t_weight = 20.0 / t_count
    for t in tables:
        tname = t["name"]
        has_desc = bool(t.get("description"))
        if has_desc:
            items.append(CopilotCheckItem("table-description", tname, "pass", t_weight, t_weight, "Table has description"))
        else:
            items.append(CopilotCheckItem(
                "table-description", tname, "fail", 0.0, t_weight,
                f"Table '{tname}' lacks business description",
                {"op": "object.describe", "table": tname, "objectType": "table", "name": tname, "description": f"Data for {tname}"}
            ))

    # 2. Measure Descriptions (35 pts max)
    all_measures = []
    for t in tables:
        for m in t.get("measures", []):
            all_measures.append((t["name"], m))
    m_count = max(1, len(all_measures))
    m_weight = 35.0 / m_count
    for tname, m in all_measures:
        mname = m["name"]
        has_desc = bool(m.get("description"))
        if has_desc:
            items.append(CopilotCheckItem("measure-description", f"'{tname}'[{mname}]", "pass", m_weight, m_weight, "Measure has description"))
        else:
            items.append(CopilotCheckItem(
                "measure-description", f"'{tname}'[{mname}]", "fail", 0.0, m_weight,
                f"Measure '{mname}' lacks calculation description for Copilot",
                {"op": "object.describe", "table": tname, "objectType": "measure", "name": mname, "description": f"Calculates {mname}"}
            ))

    # 3. Key Column Hiding Hygiene (25 pts max)
    key_suffixes = ("key", "id", "number")
    key_cols = []
    for t in tables:
        tname = t["name"]
        for c in t.get("columns", []):
            cname = c["name"]
            lower_name = cname.lower()
            if any(lower_name.endswith(k) for k in key_suffixes):
                key_cols.append((tname, c))
    k_count = max(1, len(key_cols))
    k_weight = 25.0 / k_count
    for tname, c in key_cols:
        cname = c["name"]
        is_hidden = c.get("isHidden") is True
        if is_hidden:
            items.append(CopilotCheckItem("hidden-hygiene", f"'{tname}'[{cname}]", "pass", k_weight, k_weight, "Technical key column is hidden"))
        else:
            items.append(CopilotCheckItem(
                "hidden-hygiene", f"'{tname}'[{cname}]", "fail", 0.0, k_weight,
                f"Technical key '{cname}' is visible; should be hidden to avoid misleading Copilot",
                {"op": "object.hide", "table": tname, "objectType": "column", "name": cname, "isHidden": True}
            ))

    # 4. Column Descriptions & Synonyms (20 pts max)
    # Non-hidden business columns
    biz_cols = []
    for t in tables:
        tname = t["name"]
        for c in t.get("columns", []):
            cname = c["name"]
            if not c.get("isHidden"):
                biz_cols.append((tname, c))
    b_count = max(1, len(biz_cols))
    b_weight = 20.0 / b_count
    for tname, c in biz_cols:
        cname = c["name"]
        has_desc = bool(c.get("description"))
        if has_desc:
            items.append(CopilotCheckItem("column-description", f"'{tname}'[{cname}]", "pass", b_weight, b_weight, "Visible column has description"))
        else:
            items.append(CopilotCheckItem(
                "column-description", f"'{tname}'[{cname}]", "fail", 0.0, b_weight,
                f"Visible column '{tname}'[{cname}] has no description or synonyms",
                {"op": "object.describe", "table": tname, "objectType": "column", "name": cname, "description": f"Field {cname}"}
            ))

    # Calculate total score
    earned = sum(it.points_earned for it in items)
    max_pts = sum(it.points_max for it in items)
    score = int(round((earned / max_pts * 100))) if max_pts > 0 else 100
    passed = sum(1 for it in items if it.status == "pass")
    failed = sum(1 for it in items if it.status == "fail")

    return CopilotAuditResult(
        score=score,
        total_checks=len(items),
        passed_checks=passed,
        failed_checks=failed,
        items=items,
    )
