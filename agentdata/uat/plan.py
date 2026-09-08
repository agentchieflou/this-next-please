"""ad-uat plan: from a visual (and the TMDL behind it) to the exact commands and SQL that reproduce its numbers on
each tier. It writes SQL templates under .agent/sql/ and prints the recipe; it runs nothing."""
from __future__ import annotations
import os
import re

from .. import config as C
from ..pbip import normalize as N
from ..pbip import tmdl as T
from .expect import normalize_header
from .. import textio

HIST_SQL = """-- {ticket}: Jira history as of the window end (one row per issue key). Adapt column names to {hist_table}.
SELECT h.ISSUE_KEY AS "key",
       h.STATUS      AS status,
       h.STORY_POINTS AS points
FROM   {hist_table} h
WHERE  h.PROJECT_KEY = '{project}'
  AND  h.CHANGED_TS <= TIMESTAMP '{end} 23:59:59'
QUALIFY ROW_NUMBER() OVER (PARTITION BY h.ISSUE_KEY ORDER BY h.CHANGED_TS DESC) = 1;
"""
COVERAGE_SQL = """-- {ticket}: history coverage per key (feeds ad-uat reconcile --hist-coverage)
SELECT h.ISSUE_KEY AS "key",
       MIN(h.CHANGED_TS) AS first_ts,
       MAX(h.CHANGED_TS) AS last_ts,
       COUNT(*)          AS n_rows,
       SUM(CASE WHEN h.STORY_POINTS IS NULL THEN 1 ELSE 0 END) AS points_null
FROM   {hist_table} h
WHERE  h.PROJECT_KEY = '{project}'
  AND  h.CHANGED_TS <= TIMESTAMP '{end} 23:59:59'
GROUP BY h.ISSUE_KEY;
"""


def build(pbip_dir: str, visual: str, ticket: str, page: str | None = None, expected: str | None = None,
          window: tuple[str, str] | None = None, facts: dict | None = None, sql_dir: str = os.path.join(".agent", "sql")) -> dict:
    facts = facts if facts is not None else C.project_facts()
    model, report, norm = N.load_all(pbip_dir, legacy_ok=True)
    if not report:
        raise LookupError("no report in this PBIP")
    needle = visual.lower()
    hits = [(p, v) for p in report.pages for v in p.visuals if (v.id.lower() == needle or (v.title or "").lower().find(needle) >= 0)
            and (not page or p.name.lower() == page.lower() or p.id.lower() == page.lower())]
    if len(hits) != 1:
        raise LookupError(f"{len(hits)} visuals match {visual!r}; use the id from REPORT.md or add --page")
    pg, vis = hits[0]
    by_table = {t["name"]: t for t in model.tables}
    measures, group_cols, tables = [], [], set()
    for r in vis.fields:
        if not r.entity or not r.context.startswith("projection:"):
            continue
        tables.add(r.entity)
        if r.kind == "measure":
            t = by_table.get(r.entity)
            m = next((x for x in (t["measures"] if t else []) if x["name"] == r.prop), None)
            deps = m["deps"] if m else {"columns": [], "measures": []}
            for d in deps["columns"]:
                dt = T.split_ref(d)[0]
                if dt:
                    tables.add(dt)
            measures.append({"name": r.prop, "table": r.entity, "expression": (m or {}).get("expression", "").strip().replace("\n", " ")[:200],
                             "deps": deps["columns"] + [f"[{x}]" for x in deps["measures"]]})
        elif r.kind in ("column", "level"):
            group_cols.append(r.label())
    sources = sorted({s for tn in tables for s in norm["lineage"]["sources"].get(tn, [])})
    key_guess = normalize_header(T.split_ref(group_cols[0])[1]) if group_cols else "key"
    metrics = [normalize_header(m["name"]) for m in measures]
    start, end = window or ("<start>", "<end>")
    hist_table = facts.get("jira_hist_table", "<jira_hist_table>")
    project = facts.get("jira_project", "<PROJECT_KEY>")
    os.makedirs(sql_dir, exist_ok=True)
    hist_sql = textio.norm_path(os.path.join(sql_dir, f"{ticket}-uat-hist.sql"))
    cov_sql = textio.norm_path(os.path.join(sql_dir, f"{ticket}-uat-cov.sql"))
    with open(hist_sql, "w", encoding="utf-8") as f:
        f.write(HIST_SQL.format(ticket=ticket, hist_table=hist_table, project=project, end=end))
    with open(cov_sql, "w", encoding="utf-8") as f:
        f.write(COVERAGE_SQL.format(ticket=ticket, hist_table=hist_table, project=project, end=end))
    sprintish = any(re.search(r"sprint|point|velocity|commit|complet", (m["name"] + m["expression"]).lower()) for m in measures)
    steps = []
    if expected:
        steps.append({"tier": "expected", "cmd": f'ad-uat expect "{expected}" --name expected', "gives": "<expected.tsv> + grain (key, metrics)"})
    steps.append({"tier": "3 pbi", "cmd": f'ad-pbip visual-query "{pbip_dir}" --visual "{vis.title or vis.id}" --server localhost:<port>  # port: ad-pbip desktop',
                  "gives": "<pbi.tsv>: the visual's own numbers"})
    steps.append({"tier": "2 hist", "cmd": f"ad-td --sql-file {hist_sql} --name hist   # then: ad-td --sql-file {cov_sql} --name cov", "gives": "<hist.tsv>, <cov.tsv> (edit the column names to the real table first)"})
    if sprintish:
        steps.append({"tier": "1 jira", "cmd": f'ad-jira sprint-replay --sprint <id> --board {facts.get("jira_board_id", "<jira_board_id>")} --jql "project = {project} AND updated >= \'{start}\'"', "gives": "<jira.tsv>: committed/completed per issue (truth for points)"})
    else:
        steps.append({"tier": "1 jira", "cmd": f'ad-pncli jira search --jql "project = {project} AND updated >= \'{start}\' AND updated <= \'{end}\'" --fields key,status,assignee,updated --max-results 2000', "gives": "<jira.tsv>: live values (truth)"})
    steps.append({"tier": "reconcile", "cmd": f"ad-uat reconcile --expected <expected.tsv> --jira <jira.tsv> --hist <hist.tsv> --pbi <pbi.tsv> --key {key_guess} --cols {','.join(metrics) or '<metric>'} --window {start},{end} --hist-coverage <cov.tsv> --ticket {ticket}",
                  "gives": ".agent/out/<ticket>-uat-findings.md with a class per (key, metric)"})
    return {"visual": vis.id, "title": vis.title, "type": vis.type, "page": pg.name, "group_by": group_cols, "measures": measures,
            "tables": sorted(tables), "sources": sources, "key_guess": key_guess, "metrics": metrics, "sql": [hist_sql, cov_sql], "steps": steps,
            "truth_order": "live Jira > Jira history (Teradata) > Power BI; the expected document is a claim to test, not a tier"}
