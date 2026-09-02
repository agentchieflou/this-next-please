"""ad-pbip: project · check · refs · lint · measure set. The PBIP is the source of truth; outputs are TOON + files."""
from __future__ import annotations
import argparse
import glob
import os
import sys
from . import config as C
from . import toon
from .console import utf8_stdout
from .model import AgentTable
from .pbip import check as CK
from .pbip import edit as E
from .pbip import normalize as N
from .pbip import project as PJ
from .pbip import tmdl as T
from .policy import error, render


def _pbip_dir(arg: str | None) -> str:
    if arg:
        return arg
    facts = C.project_facts()
    if facts.get("pbip_path"):
        p = facts["pbip_path"]
        return os.path.dirname(p) or "." if p.lower().endswith(".pbip") else p
    if glob.glob("*.pbip") or glob.glob("*.Report"):
        return "."
    raise C.ConfigError("no PBIP given", hint="pass <pbip-dir> or set `pbip_path` in AGENTS.md")


def _findings_out(findings, source, extra=None, show=50):
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    order = {"error": 0, "warning": 1, "info": 2}
    findings = sorted(findings, key=lambda f: (order.get(f.severity, 3), f.where))
    meta = {"ok": errors == 0, "source": source, "errors": errors, "warnings": warnings, "infos": len(findings) - errors - warnings}
    if errors:
        meta["hint"] = findings[0].hint or findings[0].message
    if extra:
        meta.update(extra)
    body = toon.table("findings", ["severity", "kind", "where", "object", "message", "hint"], [f.row() for f in findings[:show]])
    print("\n".join([toon.encode(meta, key="meta"), body]))
    return 0 if errors == 0 else 1


def cmd_project(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, report, norm = N.load_all(pbip, legacy_ok=a.legacy_ok)
    name = os.path.basename(os.path.abspath(pbip.rstrip("/\\")))
    out_dir = a.out or os.path.join(".agent", "pbip", name)
    res = PJ.write_projection(norm, model, report, out_dir, force=a.force)
    counts = {"tables": len(model.tables), "measures": sum(len(t["measures"]) for t in model.tables),
              "columns": sum(len(t["columns"]) for t in model.tables), "relationships": len(model.relationships),
              "pages": len(report.pages) if report else 0, "visuals": sum(len(p.visuals) for p in report.pages) if report else 0,
              "lint_errors": sum(1 for f in model.lint if f.severity == "error")}
    print(toon.encode({"meta": {"ok": True, "source": "ad-pbip project", "pbip": pbip.replace("\\", "/"), "skipped": res["skipped"],
                                "path": res["out_dir"], "read": ["MODEL.md", "REPORT.md", "LINEAGE.md"] if report else ["MODEL.md"], **counts},
                       "files": res["files"]}))
    return 0


def cmd_check(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, report, _ = N.load_all(pbip, legacy_ok=a.legacy_ok)
    findings = CK.check_model(model)
    extra = {"pbip": pbip.replace("\\", "/"), "report": bool(report), "te2": "skipped"}
    if report:
        findings += CK.check_report(report, model)
    else:
        findings.append(CK.Finding("warning", "report-missing", pbip, "", "no *.Report found; only the model was checked", "pass the folder that holds the .pbip"))
    if a.te2:
        te2 = a.te2_exe or C.get(C.load(), "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe")
        fs, info = CK.run_te2(model.definition_dir, te2, bpa=a.bpa)
        findings += fs
        extra["te2"] = "ran" if info.get("ran") else "not run"
    return _findings_out(findings, "ad-pbip check", extra)


def cmd_lint(a) -> int:
    target = a.path
    files = [target] if os.path.isfile(target) else T.model_files(target)
    findings: list[CK.Finding] = []
    for p in files:
        tf = T.read_file(p)
        for f in T.lint_file(tf):
            findings.append(CK.Finding(f.severity, "tmdl-" + f.rule, f"{os.path.relpath(p, target if os.path.isdir(target) else os.path.dirname(target) or '.').replace(chr(92), '/')}:{f.line}", "", f.message, f.fix))
    return _findings_out(findings, "ad-pbip lint", {"files": len(files)})


def cmd_refs(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, report, norm = N.load_all(pbip, legacy_ok=True)
    lin = norm["lineage"]
    rows: list[dict] = []
    meta: dict = {"ok": True, "source": "ad-pbip refs"}
    if a.visual or a.page:
        if not report:
            print(error("no report in this PBIP", "refs --visual needs a *.Report", "ad-pbip")); return 2
        needle = (a.visual or a.page).lower()
        hits = [(p, v) for p in report.pages for v in p.visuals
                if (a.visual and (v.id.lower() == needle or (v.title or "").lower().find(needle) >= 0)) or (a.page and (p.name.lower() == needle or p.id.lower() == needle))]
        if not hits:
            print(error(f"no visual/page matches {needle!r}", "use the id or title from REPORT.md (ad-pbip project)", "ad-pbip")); return 2
        by_table = {t["name"]: t for t in model.tables}
        for p, v in hits:
            for r in v.fields:
                if not r.entity:
                    continue
                row = {"page": p.name, "visual": v.id, "title": v.title, "context": r.context, "kind": r.kind, "field": r.label(), "deps": "", "sources": ""}
                if r.kind == "measure":
                    t = by_table.get(r.entity)
                    m = next((x for x in (t["measures"] if t else []) if x["name"] == r.prop), None)
                    if m:
                        row["deps"] = ";".join(m["deps"]["columns"] + [f"[{d}]" for d in m["deps"]["measures"]])
                        tabs = {T.split_ref(d)[0] for d in m["deps"]["columns"]} | {r.entity}
                        row["sources"] = ";".join(sorted({s for tn in tabs if tn for s in lin["sources"].get(tn, [])}))
                else:
                    row["sources"] = ";".join(lin["sources"].get(r.entity, []))
                rows.append(row)
        meta["matched"] = len(hits)
    else:
        label = f"'{a.table}'[{a.column or a.measure}]" if (a.column or a.measure) else None
        if not a.table:
            print(error("give --table (with --column/--measure), --visual or --page", "", "ad-pbip")); return 2
        if label:
            for u in lin["field_usage"].get(label, []):
                rows.append({"where": "report", "page": u["page"], "visual": u["visual"], "title": u["title"], "context": u["context"], "object": label})
            for user in lin["measure_usage"].get(label if a.column else f"[{a.measure}]", []):
                rows.append({"where": "measure", "page": "", "visual": "", "title": "", "context": "dax", "object": user})
            for r in model.relationships:
                if a.column and ((r["fromTable"], r["fromColumn"]) == (a.table, a.column) or (r["toTable"], r["toColumn"]) == (a.table, a.column)):
                    rows.append({"where": "relationship", "page": "", "visual": "", "title": "", "context": r["name"], "object": f"{r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]"})
            for t in model.tables:
                for c in t["columns"]:
                    if a.column and t["name"] == a.table and c["sortByColumn"] == a.column:
                        rows.append({"where": "sortByColumn", "page": "", "visual": "", "title": "", "context": "", "object": f"'{t['name']}'[{c['name']}]"})
                for h in t["hierarchies"]:
                    if a.column and t["name"] == a.table and any(lv["column"] == a.column for lv in h["levels"]):
                        rows.append({"where": "hierarchy", "page": "", "visual": "", "title": "", "context": "", "object": f"'{t['name']}'[{h['name']}]"})
        else:
            for lbl, uses in lin["field_usage"].items():
                if lbl.startswith(f"'{a.table}'["):
                    for u in uses:
                        rows.append({"where": "report", "page": u["page"], "visual": u["visual"], "title": u["title"], "context": u["context"], "object": lbl})
        meta["object"] = label or f"table {a.table}"
        meta["sources"] = ";".join(lin["sources"].get(a.table, []))
    t = AgentTable.from_records(rows, name="refs", source="ad-pbip refs")
    print(render(t, extra={k: v for k, v in meta.items() if k not in ("ok", "source")}) if rows else toon.encode({"meta": {**meta, "rows": 0, "note": "no uses found"}}))
    return 0


def cmd_measure_set(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, _report, _ = N.load_all(pbip, legacy_ok=True)
    expr = a.expr if a.expr is not None else open(a.expr_file, encoding="utf-8-sig").read()
    try:
        res = E.measure_set(model, a.table, a.name, expr, a.format_string, a.display_folder, a.description, a.lineage_tag,
                            hidden=True if a.hidden else None, dry_run=a.dry_run)
    except (LookupError, ValueError) as e:
        print(error(str(e), "check the table name (MODEL.md) and the DAX; nothing was written", "ad-pbip")); return 2
    print(toon.encode({"meta": {"ok": True, "source": "ad-pbip measure set", **res,
                                "next": "ad-pbip check --te2, then reopen the PBIP in Desktop (it does not hot-reload TMDL)"}}))
    return 0


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-pbip", description="PBIP projection, model<->report validation, TMDL lint and mechanical edits.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("project", help="write the LLM projection (.agent/pbip/<name>/)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--out"); p.add_argument("--force", action="store_true"); p.add_argument("--legacy-ok", action="store_true"); p.set_defaults(fn=cmd_project)
    p = sub.add_parser("check", help="cross-validate report fields against the TMDL model (+ TE2 build)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--te2", action="store_true"); p.add_argument("--te2-exe"); p.add_argument("--bpa", action="store_true")
    p.add_argument("--legacy-ok", action="store_true"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("lint", help="TMDL syntax lint for a definition folder or one .tmdl file")
    p.add_argument("path"); p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("refs", help="where is a column/measure used; what feeds a visual or page")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table"); p.add_argument("--column"); p.add_argument("--measure"); p.add_argument("--visual"); p.add_argument("--page")
    p.set_defaults(fn=cmd_refs)
    m = sub.add_parser("measure", help="mechanical measure edits").add_subparsers(dest="mcmd", required=True)
    p = m.add_parser("set", help="add or replace a measure with correct TMDL layout")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table", required=True); p.add_argument("--name", required=True)
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--expr"); g.add_argument("--expr-file")
    p.add_argument("--format-string"); p.add_argument("--display-folder"); p.add_argument("--description"); p.add_argument("--hidden", action="store_true")
    p.add_argument("--lineage-tag", action="store_true", help="write a new lineageTag (default: none; Desktop assigns on save)")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_measure_set)
    a = ap.parse_args()
    try:
        sys.exit(a.fn(a))
    except (FileNotFoundError, ValueError) as e:
        print(error(str(e)[:300], "pass the folder that contains the .pbip (or set pbip_path in AGENTS.md)", "ad-pbip")); sys.exit(2)
    except C.ConfigError as e:
        print(error(str(e), e.hint, "ad-pbip")); sys.exit(2)
