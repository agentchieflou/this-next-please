"""ad-uat: expect (document -> TSV + grain) · plan (visual -> commands) · reconcile (tiers -> classes + findings.md)."""
from __future__ import annotations
import argparse
import os
import sys
from . import config as C
from . import toon
from .console import utf8_stdout
from .model import OUT_DIR, AgentTable
from .policy import error, render
from .uat import expect as X
from .uat import plan as PL
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
    print(toon.encode({"meta": {"ok": True, "source": "ad-uat plan", "visual": res["visual"], "title": res["title"] or "", "page": res["page"],
                                "key_guess": res["key_guess"], "metrics": res["metrics"], "sources": res["sources"], "sql": res["sql"], "truth_order": res["truth_order"]},
                       "measures": [{"name": m["name"], "table": m["table"], "deps": ";".join(m["deps"])} for m in res["measures"]],
                       "steps": res["steps"]}))
    return 0


def _read(path: str | None, name: str) -> AgentTable | None:
    return AgentTable.read_tsv(path, name) if path else None


def cmd_reconcile(a) -> int:
    window = tuple(a.window.split(",", 1)) if a.window and "," in a.window else None
    res = R.reconcile(expected=_read(a.expected, "expected"), jira=_read(a.jira, "jira"), hist=_read(a.hist, "hist"), pbi=_read(a.pbi, "pbi"),
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
    print(toon.encode({"meta": meta, "counts": {c: n for c, n in res["counts"].items() if c != "ok"}}))
    print(toon.table("findings", ["key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note"],
                     [[f[c] for c in ("key", "col", "class", "expected", "jira", "hist", "pbi", "truth", "note")] for f in shown]))
    return 0


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-uat", description="UAT from a document: expected values, the reproduction recipe per tier, and the reconciliation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("expect", help="load expected values from csv/tsv/xlsx/docx/md and infer the grain")
    p.add_argument("file"); p.add_argument("--sheet"); p.add_argument("--table-index", type=int, default=0); p.add_argument("--name", default="expected")
    p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_expect)
    p = sub.add_parser("plan", help="visual -> measures -> tables -> source objects -> commands per tier")
    p.add_argument("pbip", nargs="?"); p.add_argument("--visual", required=True); p.add_argument("--page"); p.add_argument("--ticket")
    p.add_argument("--expected"); p.add_argument("--window", help="start,end (YYYY-MM-DD)"); p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("reconcile", help="compare tiers and classify every (key, metric)")
    p.add_argument("--expected"); p.add_argument("--jira"); p.add_argument("--hist"); p.add_argument("--pbi")
    p.add_argument("--key", required=True); p.add_argument("--cols", required=True); p.add_argument("--window"); p.add_argument("--hist-coverage")
    p.add_argument("--tol", type=float, default=0.0); p.add_argument("--ticket", default="uat"); p.add_argument("--show", type=int, default=20)
    p.set_defaults(fn=cmd_reconcile)
    a = ap.parse_args()
    try:
        sys.exit(a.fn(a))
    except (X.ExpectError,) as e:
        print(error(str(e), e.hint, "ad-uat")); sys.exit(2)
    except (ValueError, LookupError, FileNotFoundError) as e:
        print(error(str(e)[:300], "check the paths, --key and --cols (ad-view <tsv> shows the columns)", "ad-uat")); sys.exit(2)
    except C.ConfigError as e:
        print(error(str(e), e.hint, "ad-uat")); sys.exit(2)
