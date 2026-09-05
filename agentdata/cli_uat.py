# PYTHON_ARGCOMPLETE_OK
"""ad-uat: expect (document -> TSV + grain) · plan (visual -> commands) · reconcile (tiers -> classes + findings.md)."""
from __future__ import annotations
import argparse
import os
import sys
from . import completion
from . import config as C
from . import policy, ui
from . import toon
from .console import utf8_stdout
from .model import OUT_DIR, AgentTable
from .policy import error, render
from .uat import expect as X
from .uat import plan as PL
from .uat import jira_sql as JQ
from .uat import jira_vs_source as JV
from .uat import jira_vs_warehouses as JW
from .uat import reconcile as R


def cmd_expect(a) -> int:
    t = X.load_expected(a.file, a.sheet, a.table_index, a.name)
    grain = X.infer_grain(t)
    X.coerce_metrics(t, grain["metrics"])
    print(render(t, raw=a.raw, extra={"grain": grain}))
    return 0


def cmd_plan(a) -> int:
    facts = C.project_facts()
    pbip = a.pbip or (os.path.dirname(facts["pbip_path"]) if facts.get("pbip_path") else ".")
    window = tuple(a.window.split(",", 1)) if a.window and "," in a.window else None
    res = PL.build(pbip, a.visual, a.ticket or facts.get("jira_project", "UAT"), a.page, a.expected, window, facts)
    if policy.pretty():
        ui.facts([("visual", res["visual"]), ("title", res["title"] or ""), ("page", res["page"]),
                  ("key_guess", res["key_guess"]), ("metrics", ", ".join(res["metrics"])),
                  ("sources", ", ".join(res["sources"])), ("truth_order", " -> ".join(res["truth_order"]))],
                 title="ad-uat plan")
        if res.get("measures"):
            ui.table(["name", "table", "deps"],
                     [[m["name"], m["table"], ";".join(m["deps"])] for m in res["measures"]],
                     title="measures")
        if res.get("steps"):
            ui.table(["tier", "command", "description"],
                     [[s.get("tier", ""), s.get("command", ""), s.get("description", "")] for s in res["steps"]],
                     title="steps", wrap=(1, 2))
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-uat plan", "visual": res["visual"], "title": res["title"] or "", "page": res["page"],
                                    "key_guess": res["key_guess"], "metrics": res["metrics"], "sources": res["sources"], "sql": res["sql"], "truth_order": res["truth_order"]},
                           "measures": [{"name": m["name"], "table": m["table"], "deps": ";".join(m["deps"])} for m in res["measures"]],
                           "steps": res["steps"]}))
    return 0


def _read(path: str | None, name: str) -> AgentTable | None:
    return AgentTable.read_tsv(path, name) if path else None


def cmd_reconcile(a) -> int:
    window = tuple(a.window.split(",", 1)) if a.window and "," in a.window else None
    res = R.reconcile(expected=_read(a.expected, "expected"), jira=_read(a.jira, "jira"), hist=_read(a.hist, "hist"),
                      hist2=_read(getattr(a, "hist2", None), "hist2"),
                      hist2_name=getattr(a, "hist2_name", None) or "hist2", pbi=_read(a.pbi, "pbi"),
                      key=a.key, cols=[c.strip() for c in a.cols.split(",") if c.strip()], window=window,
                      coverage=_read(a.hist_coverage, "coverage"), tol=a.tol)
    os.makedirs(OUT_DIR, exist_ok=True)
    md_path = os.path.join(OUT_DIR, f"{a.ticket}-uat-findings.md").replace("\\", "/")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(R.findings_md(res, a.ticket))
    t = AgentTable.from_records(res["findings"], name="uat_findings", source="ad-uat reconcile",
                                fields=["key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note"])
    path = t.write_tsv() if res["findings"] else None
    meta = {"ok": True, "source": "ad-uat reconcile", "key": a.key, "cols": res["cols"], "tiers": res["tiers"], "keys_total": res["keys_total"],
            "compared": res["compared"], "ok_count": res["counts"]["ok"], "window": "..".join(res["window"]) if res["window"] else "", "md": md_path}
    if path:
        meta["path"] = path
    shown = []
    per_class: dict[str, int] = {}
    for f in res["findings"]:
        if per_class.get(f["class"], 0) < a.show:
            shown.append(f)
            per_class[f["class"]] = per_class.get(f["class"], 0) + 1
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")] +
                 [(f"count_{c}", n) for c, n in res["counts"].items() if c != "ok"],
                 title="ad-uat reconcile")
        if shown:
            ui.table(["key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note"],
                     [[f[c] for c in ("key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note")] for f in shown],
                     title="findings", status_col=2)
    else:
        print(toon.encode({"meta": meta, "counts": {c: n for c, n in res["counts"].items() if c != "ok"}}))
        print(toon.table("findings", ["key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note"],
                         [[f[c] for c in ("key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note")] for f in shown]))
    return 0


def cmd_jira_vs_warehouses(a) -> int:
    """Live Jira against **two** warehouse histories, and the two warehouses against each other.

    Not the single-engine flow run twice. The business question behind it is migration parity --
    *do the two platforms agree* -- and that is a comparison neither single run can make.
    """
    window = tuple(a.window.split(",", 1)) if a.window and "," in a.window else None
    if not window:
        print(error("no window", "--window <start>,<end> in YYYY-MM-DD", "ad-uat"))
        return 2
    sources = [x.strip() for x in a.sources.split(",") if x.strip()]
    if len(sources) != 2:
        print(error(f"--sources needs exactly two engines, got {len(sources)}",
                    "e.g. --sources teradata,hive -- for one engine use `ad-uat jira-vs-source`",
                    "ad-uat"))
        return 2
    if sources[0] == sources[1]:
        print(error("--sources names the same engine twice",
                    "the comparison is between two platforms; one of them is `jira-vs-source`",
                    "ad-uat"))
        return 2

    fields = [f.strip() for f in (a.fields or "status,assignee").split(",") if f.strip()]
    res = JW.run(ticket=a.ticket, sources=sources, jql=a.jql, window=window, fields=fields,
                 sql_dir=a.sql_dir, plan_only=a.plan_only, max_results=a.max_results,
                 tol=a.tol)
    meta = {"ok": True, "source": "ad-uat jira-vs-warehouses", "ticket": res["ticket"],
            "engines": ",".join(res["sources"]), "window": res["window"], "sql": res["sql"]}
    if a.plan_only:
        meta["plan_only"] = True
        meta["next"] = res["next"]
        return _emit_uat(meta)
    meta.update({k: res[k] for k in ("live_rows", "matched", "findings")})
    meta["counts"] = " · ".join(f"{c} {n}" for c, n in res["counts"].items() if n and c != "ok")
    meta["drift"] = res["counts"].get("warehouse-drift", 0)
    if res.get("warnings"):
        meta["warning"] = "; ".join(res["warnings"])
    return _emit_uat(meta)


def cmd_jira_vs_source(a) -> int:
    """Live Jira against Jira history in a warehouse, in one call.

    The nine mechanical steps the skill used to spell out -- pull, generate, lint, run, diff,
    count, exemplify, write -- with the two judgements left where they belong: the window and the
    scope come from the ticket, and what the differences *mean* is read off the findings file.
    """
    window = tuple(a.window.split(",", 1)) if a.window and "," in a.window else None
    if not window:
        print(error("no window", "--window <start>,<end> in YYYY-MM-DD; the ticket's acceptance "
                                 "criteria have to name one", "ad-uat"))
        return 2
    fields = [f.strip() for f in (a.fields or "status,assignee").split(",") if f.strip()]
    res = JV.run(ticket=a.ticket, source=a.source, jql=a.jql, window=window, fields=fields,
                 sql_dir=a.sql_dir, plan_only=a.plan_only, max_results=a.max_results)

    if a.plan_only:
        return _emit_uat({"ok": True, "source": "ad-uat jira-vs-source", "plan_only": True,
                          "ticket": res["ticket"], "engine": res["source"], "sql": res["sql"],
                          "coverage_sql": res["coverage_sql"], "warnings": res["warnings"],
                          "next": res["next"]})

    meta = {"ok": True, "source": "ad-uat jira-vs-source", "ticket": res["ticket"],
            "engine": res["source"], "window": res["window"], "sql": res["sql"],
            "live_rows": res["live_rows"], "history_rows": res["history_rows"],
            "matched": res["matched"], "only_live": res["only_live"],
            "only_history": res["only_history"], "changed": res["changed"],
            "compared": ",".join(res["compared"]), "findings": res["findings"]}
    if res["truncation_warning"]:
        meta["warning"] = res["truncation_warning"]
    if res["warnings"]:
        meta["sql_warnings"] = res["warnings"]
    return _emit_uat(meta)


def _emit_uat(meta: dict) -> int:
    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in meta.items()], title="ad-uat jira-vs-source")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-uat", description="UAT from a document: expected values, the reproduction recipe per tier, and the reconciliation.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("expect", help="load expected values from csv/tsv/xlsx/docx/md and infer the grain")
    p.add_argument("file"); p.add_argument("--sheet"); p.add_argument("--table-index", type=int, default=0); p.add_argument("--name", default="expected")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_expect)
    p = sub.add_parser("plan", help="visual -> measures -> tables -> source objects -> commands per tier")
    p.add_argument("pbip", nargs="?"); p.add_argument("--visual", required=True); p.add_argument("--page"); p.add_argument("--ticket")
    p.add_argument("--expected"); p.add_argument("--window", help="start,end (YYYY-MM-DD)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("reconcile", help="compare tiers and classify every (key, metric)")
    p.add_argument("--expected"); p.add_argument("--jira"); p.add_argument("--hist"); p.add_argument("--pbi")
    p.add_argument("--hist2", help="a second warehouse history tier: enables the warehouse-vs-warehouse comparison")
    p.add_argument("--hist2-name", dest="hist2_name",
                   help="what to call it in the findings (default hist2); use the engine, e.g. hive")
    p.add_argument("--key", required=True); p.add_argument("--cols", required=True); p.add_argument("--window"); p.add_argument("--hist-coverage")
    p.add_argument("--tol", type=float, default=0.0); p.add_argument("--ticket", default="uat"); p.add_argument("--show", type=int, default=20)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_reconcile)
    p = sub.add_parser("jira-vs-warehouses",
                       help="live Jira vs TWO warehouse histories, including whether the two "
                            "warehouses agree with each other (migration parity)")
    p.add_argument("--sources", required=True,
                   help="exactly two engines, comma-separated, e.g. teradata,hive")
    p.add_argument("--ticket", required=True)
    p.add_argument("--jql", required=True, help="the live scope, from the ticket's criteria")
    p.add_argument("--window", required=True, help="start,end (YYYY-MM-DD)")
    p.add_argument("--fields", default="status,assignee")
    p.add_argument("--tol", type=float, default=0.0, help="numeric tolerance when comparing values")
    p.add_argument("--max-results", type=int, default=2000, dest="max_results")
    p.add_argument("--sql-dir", default=os.path.join(".agent", "sql"), dest="sql_dir")
    p.add_argument("--plan-only", action="store_true", dest="plan_only",
                   help="write and lint both SQL files, run nothing")
    p.add_argument("--pretty", action="store_true", help="draw it for a person to read")
    p.set_defaults(fn=cmd_jira_vs_warehouses)

    p = sub.add_parser("jira-vs-source",
                       help="live Jira vs Jira history in a warehouse: generate the SQL, run both "
                            "sides, diff, and write the findings")
    p.add_argument("--source", required=True, choices=list(JQ.DIALECTS),
                   help="which warehouse holds the Jira history")
    p.add_argument("--ticket", required=True, help="the ticket this UAT is for")
    p.add_argument("--jql", required=True, help="the live scope, from the ticket's criteria")
    p.add_argument("--window", required=True, help="start,end (YYYY-MM-DD)")
    p.add_argument("--fields", default="status,assignee",
                   help="columns to compare on both sides (default status,assignee)")
    p.add_argument("--max-results", type=int, default=2000, dest="max_results")
    p.add_argument("--sql-dir", default=os.path.join(".agent", "sql"), dest="sql_dir")
    p.add_argument("--plan-only", action="store_true", dest="plan_only",
                   help="write and lint the SQL, run nothing -- for checking the column names first")
    p.add_argument("--pretty", action="store_true", help="draw it for a person to read")
    p.set_defaults(fn=cmd_jira_vs_source)

    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        sys.exit(a.fn(a))
    except (X.ExpectError, JV.UatError) as e:
        print(error(str(e), e.hint, "ad-uat")); sys.exit(2)
    except (ValueError, LookupError, FileNotFoundError) as e:
        print(error(str(e)[:300], "check the paths, --key and --cols (ad-view <tsv> shows the columns)", "ad-uat")); sys.exit(2)
    except C.ConfigError as e:
        print(error(str(e), e.hint, "ad-uat")); sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())
