"""Tiered reconciliation: live Jira (T1) > Jira history in Teradata (T2) > Power BI (T3), plus the expected values.
Every (key, metric) gets one class with an exact reason; `history-gap` is the "the warehouse cannot reproduce Jira"
case the user asked to be spotted (no history rows covering the window / null points)."""
from __future__ import annotations
import datetime as _dt
import os
from typing import Any

from ..model import AgentTable

CLASSES = ("report-bug", "history-gap", "lag", "mapping-bug", "warehouse-drift", "expectation-wrong",
           "missing", "unexplained")
TIER_ORDER = ("jira", "hist", "hist2", "pbi")
DEFINITION = {
    "report-bug": "Power BI disagrees with the warehouse while the warehouse matches Jira: the model or report logic is wrong",
    "history-gap": "the warehouse has no history rows (or null points) covering the window for this key: it cannot reproduce live Jira",
    "lag": "the warehouse is behind: its last change for this key predates the window end",
    "mapping-bug": "history covers the window but disagrees with live Jira: a mapping/transformation defect in the load",
    "warehouse-drift": "the two warehouses disagree with each other: the migration between them has not reproduced this value, whatever either says about Jira",
    "expectation-wrong": "every available tier agrees; the expected value in the document is wrong",
    "missing": "the key exists in only one tier",
    "unexplained": "tiers disagree and the evidence needed to classify is missing (supply --hist-coverage / a history tier)",
}
RECOMMENDATION = {
    "report-bug": "fix the measure/report (tmdl-edit), re-run pbi-validate, re-export",
    "history-gap": "report the gap to the data owner; do not patch the warehouse or the report to match",
    "lag": "re-run after the next load or narrow the window to the last loaded timestamp",
    "mapping-bug": "raise a load defect with the 3 example keys; keep Jira as the truth in the findings",
    "warehouse-drift": "raise a migration defect against the platform that disagrees with Jira; if both do, the load is common to them and Jira is still the truth",
    "expectation-wrong": "reply to the requester with the reproduced numbers and the tier that produced them",
    "missing": "check scope (JQL / WHERE clause) and the join key on each side",
    "unexplained": "provide the coverage TSV (references/uat-sql-templates.md) and re-run",
}


def eq(a: Any, b: Any, tol: float = 0.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _index(t: AgentTable | None, key: str) -> dict[str, list]:
    if t is None or key not in t.columns:
        return {}
    ki = t.columns.index(key)
    return {str(r[ki]).strip(): r for r in t.rows if r[ki] not in (None, "")}


def _val(t: AgentTable | None, row, col: str):
    if t is None or row is None or col not in t.columns:
        return None
    return row[t.columns.index(col)]


def _ts(v) -> _dt.datetime | None:
    if v in (None, ""):
        return None
    s = str(v).strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            return _dt.datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def classify(key: str, col: str, exp, t1, t2, t3, cov_row: dict | None, coverage_given: bool, window_end: _dt.datetime | None, tol: float,
             hist_present: bool = False, t2b=None, hist2_name: str = "hist2") -> tuple[str, str, Any]:
    """`t2b` is the optional second warehouse history. Keyword-only in practice and defaulted, so
    every existing caller -- the 2-tier and 4-tier ones -- behaves exactly as before."""
    present = {k: v for k, v in (("jira", t1), ("hist", t2), ("hist2", t2b), ("pbi", t3)) if v is not None}
    truth_tier = next((k for k in TIER_ORDER if k in present), None)
    truth = present.get(truth_tier) if truth_tier else None
    vals = list(present.values())
    agree = all(eq(vals[0], v, tol) for v in vals[1:]) if vals else True
    if agree and exp is not None and vals and not eq(exp, truth, tol):
        return "expectation-wrong", f"all tiers give {truth} ({truth_tier})", truth
    if hist_present and t2 is None and t1 is not None:
        nulls = (cov_row or {}).get("points_null")
        return "history-gap", f"jira {t1} but the history row has no value" + (f" (points_null={nulls})" if nulls not in (None, "") else ""), truth
    # Checked before the Jira comparisons: when two warehouses disagree with each other, that is
    # the finding -- a migration that has not reproduced the value. Reporting it as "hist disagrees
    # with Jira" would name one platform and hide that the other one differs too.
    if t2 is not None and t2b is not None and not eq(t2, t2b, tol):
        agrees = [n for n, v in (("hist", t2), (hist2_name, t2b)) if t1 is not None and eq(v, t1, tol)]
        detail = f"hist {t2} vs {hist2_name} {t2b}"
        if t1 is not None:
            detail += f"; jira {t1}" + (f" agrees with {agrees[0]}" if agrees else " agrees with neither")
        return "warehouse-drift", detail, truth
    if t3 is not None and t2 is not None and not eq(t3, t2, tol) and (t1 is None or eq(t2, t1, tol)):
        return "report-bug", f"pbi {t3} vs hist {t2}", truth
    if t1 is not None and t2 is not None and not eq(t2, t1, tol):
        if not coverage_given:
            return "unexplained", "hist != jira; supply --hist-coverage to classify", truth
        first = _ts((cov_row or {}).get("first_ts"))
        last = _ts((cov_row or {}).get("last_ts"))
        n = (cov_row or {}).get("n_rows")
        if cov_row is None or (n is not None and float(n) == 0) or (first and window_end and first > window_end) or (cov_row or {}).get("points_null") not in (None, "", 0, "0") and t2 in (None, 0):
            return "history-gap", f"jira {t1} vs hist {t2}; history rows: {n if cov_row else 0}", truth
        if last and window_end and last < window_end:
            return "lag", f"jira {t1} vs hist {t2}; last history change {last.date()} < window end", truth
        return "mapping-bug", f"jira {t1} vs hist {t2}; history covers the window", truth
    if t1 is not None and t2 is None and t3 is not None and not eq(t3, t1, tol):
        return "unexplained", f"pbi {t3} vs jira {t1}; no history tier to say why", truth
    if t1 is None and t2 is None and t3 is None:
        return "missing", "no tier has this key", exp
    return "ok", "", truth


def reconcile(*, expected: AgentTable | None, jira: AgentTable | None, hist: AgentTable | None, pbi: AgentTable | None,
              key: str, cols: list[str], window: tuple[str, str] | None = None, coverage: AgentTable | None = None,
              tol: float = 0.0, hist2: AgentTable | None = None, hist2_name: str = "hist2") -> dict:
    tiers = {"expected": expected, "jira": jira, "hist": hist, "hist2": hist2, "pbi": pbi}
    given = [k for k, v in tiers.items() if v is not None]
    if len(given) < 2:
        raise ValueError("reconcile needs at least two of --expected/--jira/--hist/--hist2/--pbi")
    for k, t in tiers.items():
        if t is not None and key not in t.columns:
            raise ValueError(f"key '{key}' missing in {k} (columns: {', '.join(t.columns[:8])})")
    idx = {k: _index(t, key) for k, t in tiers.items()}
    cov = _index(coverage, "key") if coverage is not None else {}
    cov_rows = {k: dict(zip(coverage.columns, r)) for k, r in cov.items()} if coverage is not None else {}
    window_end = _ts(window[1]) if window else None
    keys = sorted(set().union(*[set(d) for d in idx.values()]))
    findings: list[dict] = []
    counts = {c: 0 for c in CLASSES}
    counts["ok"] = 0
    for k in keys:
        have = [t for t in given if k in idx[t]]
        if len(have) == 1:
            counts["missing"] += 1
            findings.append({"key": k, "col": "*", "class": "missing", "expected": None, "jira": None, "hist": None, "pbi": None, "truth": None, "note": f"only in {have[0]}"})
            continue
        for col in cols:
            exp = _val(expected, idx["expected"].get(k), col)
            t1 = _val(jira, idx["jira"].get(k), col)
            t2 = _val(hist, idx["hist"].get(k), col)
            t2b = _val(hist2, idx["hist2"].get(k), col)
            t3 = _val(pbi, idx["pbi"].get(k), col)
            cls, note, truth = classify(k, col, exp, t1, t2, t3, cov_rows.get(k), coverage is not None, window_end, tol,
                                        hist_present=k in idx["hist"], t2b=t2b, hist2_name=hist2_name)
            counts[cls] += 1
            if cls != "ok":
                findings.append({"key": k, "col": col, "class": cls, "expected": exp, "jira": t1, "hist": t2,
                                 "hist2": t2b, "pbi": t3, "truth": truth, "note": note})
    order = {c: i for i, c in enumerate(CLASSES)}
    findings.sort(key=lambda f: (order.get(f["class"], 99), f["key"], f["col"]))
    return {"counts": counts, "findings": findings, "tiers": given, "keys_total": len(keys), "compared": len(keys) * len(cols), "key": key, "cols": cols,
            "window": list(window) if window else None, "hist2_name": hist2_name}


def findings_md(result: dict, ticket: str, max_lines: int = 40) -> str:
    """<= 40 lines: counts, one section per class with an adaptive number of example rows, one recommendation per class."""
    counts = result["counts"]
    present = [c for c in CLASSES if counts.get(c)]
    head = [f"# {ticket} UAT findings — {_dt.date.today().isoformat()}", "",
            f"key `{result['key']}` · metrics {', '.join(result['cols'])} · window {('..'.join(result['window']) if result['window'] else 'n/a')} · "
            f"tiers {', '.join(result['tiers'])} · keys {result['keys_total']} · comparisons {result['compared']} · ok {counts.get('ok', 0)}",
            "", "counts: " + (" · ".join(f"{c} {n}" for c, n in counts.items() if n and c != "ok") or "none")]
    rec = ["", "## Recommendation"] + ([f"- {c}: {RECOMMENDATION[c]}" for c in present] or ["- all comparisons agree; no action"])
    budget = max_lines - len(head) - len(rec)
    per = budget // len(present) if present else 0
    examples = max(1, min(3, per - 2))
    body: list[str] = []
    for c in present:
        title = f"## {c} — {DEFINITION[c]}"
        if c == "history-gap":
            title += " **The Teradata history cannot reproduce live Jira for these keys: report the number, do not patch the warehouse or the report to match.**"
        body += ["", title]
        second = result.get("hist2_name", "hist2")
        for f in [x for x in result["findings"] if x["class"] == c][:examples]:
            row = (f"- {f['key']} {f['col']}: expected {_fmt(f['expected'])} · jira {_fmt(f['jira'])} · "
                   f"hist {_fmt(f['hist'])}")
            if "hist2" in f and f.get("hist2") is not None:
                row += f" · {second} {_fmt(f['hist2'])}"
            body.append(row + f" · pbi {_fmt(f['pbi'])} — {f['note']}")
    lines = head + body + rec
    return "\n".join(lines[:max_lines]).rstrip() + "\n"


def _fmt(v: Any) -> str:
    return "–" if v is None else str(v)
