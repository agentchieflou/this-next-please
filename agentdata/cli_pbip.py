# PYTHON_ARGCOMPLETE_OK
"""ad-pbip: project · check · refs · lint · measure set. The PBIP is the source of truth; outputs are TOON + files."""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from .textio import read_text
from . import completion
from . import config as C
from . import toon
from .console import utf8_stdout
from .model import AgentTable
from .model import OUT_DIR
from .pbip import author as AU
from .pbip import brief as BR
from .pbip import catalog as CAT
from .pbip import check as CK
from .pbip import dax as D
from .pbip import desktop as DT
from .pbip import dmv as DMV
from .pbip import edit as E
from .pbip import expr as EX
from .pbip import external_tool as EXT
from .pbip import normalize as N
from .pbip import pbir as P
from .pbip import project as PJ
from .pbip import screenshot as SC
from .pbip import tmdl as T
from .pbip import trace as TR
from .policy import error, render
from . import policy, ui


def _resolve_desktop_target(a):
    """If --server, --pid, or --db are missing, prefer fresh .agent/desktop.json."""
    handoff = EXT.read_handoff()
    if handoff:
        if hasattr(a, "server") and not getattr(a, "server", None) and handoff.get("server"):
            a.server = handoff["server"]
        if hasattr(a, "db") and not getattr(a, "db", None) and handoff.get("database"):
            a.db = handoff["database"]
        if hasattr(a, "pid") and not getattr(a, "pid", None) and handoff.get("pid"):
            a.pid = handoff["pid"]
    return handoff


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
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title=source, subtitle="ok" if meta["ok"] else "fail")
        if findings:
            ui.table(["severity", "kind", "where", "object", "message", "hint"],
                     [f.row() for f in findings[:show]],
                     title="findings", status_col=0, wrap=(4, 5))
        return 0 if errors == 0 else 1
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
    if policy.pretty():
        ui.facts([("pbip", pbip.replace("\\", "/")), ("path", res["out_dir"]), ("skipped", res["skipped"]),
                  *[(k, v) for k, v in counts.items()]], title="ad-pbip project")
        if res.get("files"):
            ui.table(["file", "path"], [[f, os.path.join(res["out_dir"], f).replace("\\", "/")] for f in res["files"]], title="projected files")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip project", "pbip": pbip.replace("\\", "/"), "skipped": res["skipped"],
                                    "path": res["out_dir"], "read": ["MODEL.md", "REPORT.md", "LINEAGE.md"] if report else ["MODEL.md"], **counts},
                           "files": res["files"]}))
    return 0


def cmd_check(a) -> int:
    _resolve_desktop_target(a)
    pbip = _pbip_dir(a.pbip)
    model, report, _ = N.load_all(pbip, legacy_ok=a.legacy_ok)
    findings = CK.check_model(model)
    extra = {"pbip": pbip.replace("\\", "/"), "report": bool(report), "te2": "skipped"}
    if report:
        findings += CK.check_report(report, model)
    else:
        findings.append(CK.Finding("warning", "report-missing", pbip, "", "no *.Report found; only the model was checked", "pass the folder that holds the .pbip"))
    cfg = C.load()
    if a.te2:
        te2 = a.te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe")
        fs, info = CK.run_te2(model.definition_dir, te2, bpa=a.bpa)
        findings += fs
        extra["te2"] = "ran" if info.get("ran") else "not run"
    if a.server and report:
        fs, info = CK.evaluate_live(report, model, a.server, _dscmd(cfg, a.dscmd), a.db, file_flag=_file_flag(cfg))
        findings += fs
        extra.update({"live": a.server, "measures_probed": info.get("measures_probed", 0), "measures_failed": info.get("measures_failed", 0)})
    return _findings_out(findings, "ad-pbip check", extra)


def _dscmd(cfg, flag=None):
    return flag or C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe") or ""


def _file_flag(cfg) -> bool:
    caps = C.get(cfg, "powerbi.tools.dscmd_caps") or {}
    return bool(caps.get("file_flag", True))


def _candidates() -> list[str]:
    facts = C.project_facts()
    c = [facts["pbip_path"]] if facts.get("pbip_path") else []
    return c + glob.glob("*.pbip") + glob.glob(os.path.join("*", "*.pbip"))


def cmd_desktop(a) -> int:
    cmd = getattr(a, "desktop_cmd", None)
    if cmd == "open":
        exe = getattr(a, "exe", None) or C.get(C.load(), "powerbi.tools.pbi_desktop_exe")
        res = DT.open_and_wait(a.path, wait_secs=getattr(a, "wait", 180), exe=exe)
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop open", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    if cmd == "close":
        res = DT.close(a.pid, save=getattr(a, "save", False), discard=getattr(a, "discard", False))
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop close", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    if cmd == "reload":
        res = DT.reload(a.pid, save=getattr(a, "save", False), discard=getattr(a, "discard", False), candidates=_candidates())
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop reload", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    # Default / status:
    if not getattr(a, "pid", None):
        _resolve_desktop_target(a)
    pid = getattr(a, "pid", None)
    rows = [i.row() for i in DT.status(pid=pid, candidates=_candidates())]
    src = "ad-pbip desktop status" if cmd == "status" else "ad-pbip desktop"
    if not rows:
        if policy.pretty():
            ui.note("no running Power BI Desktop instance found; open the .pbip (ad-pbip launch <pbip>)")
        else:
            print(toon.encode({"meta": {"ok": True, "source": src, "instances": 0,
                                        "hint": "no running Power BI Desktop instance found; open the .pbip (ad-pbip launch <pbip>)"}}))
        return 0
    print(render(AgentTable.from_records(rows, name="desktop", source=src), extra={"instances": len(rows)}))
    return 0


def cmd_capabilities(a) -> int:
    pid = getattr(a, "pid", None)
    caps = DT.capabilities(pid=pid)
    avail = sum(1 for c in caps if c.get("available"))
    t = AgentTable.from_records(caps, name="capabilities", source="ad-pbip capabilities")
    print(render(t, extra={"available": avail, "total": len(caps)}))
    return 0


def cmd_handoff(a) -> int:
    res = EXT.handoff(a.server, a.database, project_dir=getattr(a, "project", None))
    if policy.pretty():
        ui.facts([("server", a.server), ("database", a.database), *[(k, v) for k, v in res.items()]], title="ad-pbip handoff")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip handoff", **res}}))
    return 0


def cmd_register_tool(a) -> int:
    ok, dest, hint = EXT.register_tool(target_dir=getattr(a, "target_dir", None),
                                       python_exe=getattr(a, "python", None),
                                       project_dir=getattr(a, "project", None))
    if not ok:
        print(error(f"failed to register external tool at {dest}", hint or "run with administrator privileges", "ad-pbip"))
        return 1
    if policy.pretty():
        ui.facts([("registered", dest), ("tool", "agentdata.pbitool.json")], title="ad-pbip register-tool")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip register-tool", "path": dest, "next": "open Power BI Desktop -> External Tools ribbon -> agentdata"}}))
    return 0


def cmd_screenshot(a) -> int:
    if getattr(a, "compare", None):
        if len(a.compare) != 2:
            print(error("--compare requires exactly 2 image paths", "pass: --compare <a.png> <b.png>", "ad-pbip"))
            return 2
        img_a, img_b = a.compare
        masks = []
        res = SC.compare_images(img_a, img_b, threshold=getattr(a, "threshold", 0.5), masks=masks)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items()], title="ad-pbip screenshot compare", subtitle=res["verdict"])
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip screenshot compare", **res}}))
        return 0 if res["verdict"] == "same" else 1

    if not getattr(a, "pid", None):
        _resolve_desktop_target(a)

    if not getattr(a, "pid", None):
        print(error("give --pid <pid> (ad-pbip desktop) or --compare <a.png> <b.png>", "", "ad-pbip"))
        return 2

    pages, visuals = SC.screenshot_session(a.pid, page=getattr(a, "page", None), all_pages=getattr(a, "all", False),
                                           scale=getattr(a, "scale", 1), visual=getattr(a, "visual", None),
                                           settle_s=getattr(a, "settle", 0.5), out_dir=getattr(a, "out", None))
    if not pages:
        print(error("no pages captured", "check --pid and that Desktop window is open", "ad-pbip"))
        return 1

    t = AgentTable.from_records(pages, name="screenshots", source="ad-pbip screenshot")
    print(render(t, extra={"pages": len(pages), "visuals": len(visuals)}))
    return 0


def cmd_launch(a) -> int:
    exe = a.exe or C.get(C.load(), "powerbi.tools.pbi_desktop_exe")
    res = DT.launch(a.path, exe if exe and os.path.exists(exe) else None)
    if policy.pretty():
        ui.facts([("path", a.path), *[(k, v) for k, v in res.items()]], title="ad-pbip launch")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip launch", **res, "next": "wait for Desktop to load, then ad-pbip desktop"}}))
    return 0


def cmd_visual_query(a) -> int:
    _resolve_desktop_target(a)
    pbip = _pbip_dir(a.pbip)
    model, report, _ = N.load_all(pbip, legacy_ok=True)
    if not report:
        print(error("no report in this PBIP", "", "ad-pbip")); return 2
    needle = a.visual.lower()
    hits = [(p, v) for p in report.pages for v in p.visuals if (v.id.lower() == needle or (v.title or "").lower().find(needle) >= 0)
            and (not a.page or p.name.lower() == a.page.lower() or p.id.lower() == a.page.lower())]
    if len(hits) != 1:
        print(error(f"{len(hits)} visuals match {a.visual!r}", "use the visual id from REPORT.md, or add --page", "ad-pbip")); return 2
    page, visual = hits[0]
    dax, notes = D.visual_query(visual, N.ModelIndex(model, report), extra_filters=list(page.filters) + list(report.filters), top_n=a.top)
    os.makedirs(OUT_DIR, exist_ok=True)
    dax_path = os.path.join(OUT_DIR, f"{visual.id}_visual.dax").replace("\\", "/")
    with open(dax_path, "w", encoding="utf-8") as f:
        f.write(dax)
    if a.dry_run or not a.server:
        if policy.pretty():
            ui.facts([("visual", visual.id), ("title", visual.title or ""), ("page", page.name),
                      ("dax_path", dax_path), ("skipped", notes),
                      ("note", "no --server: query written, not executed")], title="ad-pbip visual-query")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip visual-query", "visual": visual.id, "title": visual.title, "page": page.name,
                                        "dax_path": dax_path, "skipped": notes, "note": "no --server: query written, not executed"}}))
        print(dax)
        return 0
    cfg = C.load()
    try:
        t = D.run_dax(dax, a.server, _dscmd(cfg, a.dscmd), a.db, file_flag=_file_flag(cfg), name=a.name or f"visual_{visual.id[:8]}")
    except D.DaxError as e:
        print(error(str(e)[:300], "check --server (ad-pbip desktop) and the DAX in dax_path; a DAX error here is a real report failure", "ad-pbip"))
        return 1
    t.source = f"ad-pbip visual-query {visual.id} @ {a.server}"
    print(render(t, extra={"visual": visual.id, "title": visual.title or "", "dax_path": dax_path, "skipped": notes}))
    return 0


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
    if getattr(a, "live", False):
        _resolve_desktop_target(a)
        if not getattr(a, "server", None):
            print(error("refs --live requires --server localhost:<port>", "pass --server or use Desktop External Tools", "ad-pbip"))
            return 2
        t = DMV.refs_live(pbip, a.server, database=getattr(a, "db", None))
        print(render(t, extra={"server": a.server, "live": True}))
        return 0

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
    if rows:
        print(render(t, extra={k: v for k, v in meta.items() if k not in ("ok", "source")}))
    elif policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")] + [("rows", 0), ("note", "no uses found")], title="ad-pbip refs")
    else:
        print(toon.encode({"meta": {**meta, "rows": 0, "note": "no uses found"}}))
    return 0


def cmd_measure_set(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, _report, _ = N.load_all(pbip, legacy_ok=True)
    expr = a.expr if a.expr is not None else read_text(a.expr_file)
    try:
        res = E.measure_set(model, a.table, a.name, expr, a.format_string, a.display_folder, a.description, a.lineage_tag,
                            hidden=True if a.hidden else None, dry_run=a.dry_run)
    except (LookupError, ValueError) as e:
        print(error(str(e), "check the table name (MODEL.md) and the DAX; nothing was written", "ad-pbip")); return 2
    if policy.pretty():
        ui.facts([("table", a.table), ("name", a.name), *[(k, v) for k, v in res.items()]], title="ad-pbip measure set")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip measure set", **res,
                                    "next": "ad-pbip check --te2, then reopen the PBIP in Desktop (it does not hot-reload TMDL)"}}))
    return 0


def cmd_trace(a) -> int:
    trace_cmd = getattr(a, "trace_cmd", None)
    if trace_cmd == "start":
        _resolve_desktop_target(a)
        if not getattr(a, "server", None) and not getattr(a, "pid", None):
            print(error("give --pid <pid> or --server localhost:<port>", "", "ad-pbip"))
            return 2
        server = a.server or f"localhost:{a.pid}"
        listener, out_file, meta = TR.start_trace(server, pid=getattr(a, "pid", None), seconds=getattr(a, "seconds", 60),
                                                  out_path=getattr(a, "out", None), database=getattr(a, "db", None))
        if policy.pretty():
            ui.facts([(k, v) for k, v in meta.items()], title="ad-pbip trace started")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip trace start", **meta, "next": f"run actions, then ad-pbip trace report {out_file}"}}))
        return 0

    if trace_cmd == "report":
        pbip = None
        try:
            pbip = _pbip_dir(getattr(a, "pbip", None))
        except Exception:
            pass
        t = TR.report_trace(a.file, report_dir=pbip)
        print(render(t, extra={"events_file": a.file}))
        return 0

    return 0


def cmd_dmv(a) -> int:
    _resolve_desktop_target(a)
    if not getattr(a, "server", None):
        print(error("give --server localhost:<port> (or press External Tools -> agentdata in Desktop)", "", "ad-pbip"))
        return 2
    try:
        t = DMV.run_dmv(a.server, a.query, database=getattr(a, "db", None))
        if a.query.strip().lower() == "segments":
            t = DMV.normalize_segments(t)
    except Exception as e:
        print(error(str(e)[:300], "verify server address and that Desktop Analysis Services is running", "ad-pbip"))
        return 1
    print(render(t, extra={"server": a.server, "query": a.query}))
    return 0


def cmd_page_cost(a) -> int:
    _resolve_desktop_target(a)
    if not getattr(a, "pid", None):
        print(error("give --pid <pid> (ad-pbip desktop)", "", "ad-pbip"))
        return 2
    pbip = None
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
    except Exception:
        pass
    t = DMV.page_cost(a.pid, a.page, pbip_dir=pbip, seconds=getattr(a, "seconds", 15))
    print(render(t, extra=t.raw or {}))
    return 0


def cmd_schema(a) -> int:
    try:
        res = CAT.schema_update()
    except Exception as e:
        print(error(str(e), "run ad-pbip schema update", "ad-pbip"))
        return 1
    if policy.pretty():
        ui.facts([(k, v) for k, v in res.items() if k not in ("visual_types", "formatting_objects")], title="ad-pbip schema update")
    else:
        print(toon.encode({"meta": {"source": "ad-pbip schema update", **res}}))
    return 0


def cmd_catalog(a) -> int:
    sub_c = getattr(a, "catalog_cmd", None)
    try:
        if sub_c == "list":
            t = CAT.list_visuals()
            print(render(t))
            return 0
        if sub_c == "describe":
            t = CAT.describe_visual(a.type)
            print(render(t, extra=t.raw))
            return 0
        if sub_c == "formatting":
            t = CAT.formatting_catalog(visual_type=getattr(a, "type", None),
                                       object_name=getattr(a, "object", None),
                                       property_name=getattr(a, "property", None),
                                       search=getattr(a, "search", None))
            print(render(t))
            return 0
    except (KeyError, FileNotFoundError) as e:
        print(error(str(e), "check visual type with `ad-pbip catalog list`", "ad-pbip"))
        return 2
    return 0


def cmd_expr(a) -> int:
    sub_c = getattr(a, "expr_cmd", None)
    if sub_c == "encode":
        enc = EX.encode_expr(a.text)
        if policy.pretty():
            ui.facts([("input", a.text), ("encoded", json.dumps(enc))], title="ad-pbip expr encode")
        else:
            print(json.dumps(enc, indent=2))
        return 0
    if sub_c == "decode":
        dec = EX.decode_expr(a.json)
        if policy.pretty():
            ui.facts([("input", a.json), ("decoded", dec)], title="ad-pbip expr decode")
        else:
            print(dec)
        return 0
    return 0


def cmd_theme(a) -> int:
    sub_c = getattr(a, "theme_cmd", None)
    if sub_c == "shade":
        try:
            shaded = EX.shade_color(a.color, a.pct)
        except ValueError as e:
            print(error(str(e), "use format #RRGGBB and pct between -100 and 100", "ad-pbip"))
            return 2
        if policy.pretty():
            ui.facts([("color", a.color), ("pct", a.pct), ("result", shaded)], title="ad-pbip theme shade")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip theme shade", "color": a.color, "pct": a.pct, "result": shaded}}))
        return 0
    if sub_c == "set":
        try:
            pbip = _pbip_dir(getattr(a, "pbip", None))
            res = AU.theme_set(pbip, a.file)
        except (FileNotFoundError, ValueError) as e:
            print(error(str(e), "check theme file path", "ad-pbip"))
            return 2
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items()], title="ad-pbip theme set")
        else:
            print(toon.encode({"meta": {"source": "ad-pbip theme set", **res}}))
        return 0
    return 0


def cmd_preview(a) -> int:
    sub_c = getattr(a, "preview_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        rep = P.load_report(pbip)
    except Exception as e:
        print(error(str(e), "provide valid PBIP path", "ad-pbip"))
        return 2

    if sub_c == "pages":
        rows = [[p.id, p.name, p.ordinal, getattr(p, "width", 1280), getattr(p, "height", 720), len(p.visuals)] for p in rep.pages]
        t = AgentTable("preview_pages", ["page_id", "display_name", "ordinal", "width", "height", "visuals_count"], rows, source="ad-pbip preview pages")
        print(render(t))
        return 0
    if sub_c == "visuals":
        rows = []
        for p in rep.pages:
            for v in p.visuals:
                pos = v.position or {}
                rows.append([p.name, v.id, v.type or "", v.title or "", pos.get("x", 0), pos.get("y", 0), pos.get("width", 0), pos.get("height", 0), len(v.fields)])
        t = AgentTable("preview_visuals", ["page", "visual_id", "type", "title", "x", "y", "width", "height", "fields_count"], rows, source="ad-pbip preview visuals")
        print(render(t))
        return 0
    if sub_c == "filters":
        rows = []
        for flt in rep.filters:
            rows.append(["report", "-", "-", flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
        for p in rep.pages:
            for flt in p.filters:
                rows.append(["page", p.name, "-", flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
            for v in p.visuals:
                for flt in v.filters:
                    rows.append(["visual", p.name, v.id, flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
        t = AgentTable("preview_filters", ["scope", "page", "visual", "filter_name", "type", "field"], rows, source="ad-pbip preview filters")
        print(render(t))
        return 0
    if sub_c == "themes":
        rj_path = os.path.join(rep.root, "definition", "report.json")
        tc = {}
        if os.path.exists(rj_path):
            tc = (P._load(rj_path) or {}).get("themeCollection") or {}
        rows = []
        for k, v in tc.items():
            if isinstance(v, dict):
                rows.append([k, v.get("name", ""), v.get("type", ""), v.get("path", "-")])
        t = AgentTable("preview_themes", ["slot", "name", "type", "path"], rows, source="ad-pbip preview themes")
        print(render(t))
        return 0
    return 0


def cmd_page(a) -> int:
    sub_c = getattr(a, "page_cmd", None)
    if getattr(a, "brief", None):
        stat = BR.brief_status(a.brief)
        if stat != "current":
            print(error(f"brief status is '{stat}'; approve with `ad-pbip brief approve {a.brief}`", "brief approval required", "ad-pbip"))
            return 2
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            res = AU.page_add(pbip, a.name, after=getattr(a, "after", None),
                              width=getattr(a, "width", 1280), height=getattr(a, "height", 720))
        elif sub_c == "remove":
            res = AU.page_remove(pbip, a.page)
        elif sub_c == "move":
            res = AU.page_move(pbip, a.page, after=getattr(a, "after", None))
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check page arguments", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip page {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip page {sub_c}", **res}}))
    return 0


def cmd_visual(a) -> int:
    sub_c = getattr(a, "visual_cmd", None)
    if getattr(a, "brief", None):
        stat = BR.brief_status(a.brief)
        if stat != "current":
            print(error(f"brief status is '{stat}'; approve with `ad-pbip brief approve {a.brief}`", "brief approval required", "ad-pbip"))
            return 2
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            pos = None
            if getattr(a, "position", None):
                pos = tuple(int(x.strip()) for x in a.position.split(","))

            # Validate against brief layout contract if brief is provided
            if getattr(a, "brief", None):
                _, brief_data, _ = BR.parse_brief_file(a.brief)
                matched = False
                for p in brief_data.get("pages", []):
                    if p.get("name") == a.page or p.get("title") == a.page:
                        for pl in (p.get("layout_contract") or {}).get("placements", []):
                            if pos and pl.get("position"):
                                ppos = pl["position"]
                                if (pos[0], pos[1], pos[2], pos[3]) == (ppos.get("x"), ppos.get("y"), ppos.get("width"), ppos.get("height")):
                                    matched = True
                                    break
                            elif not pos and pl.get("type") == a.type:
                                matched = True
                                break
                if not matched:
                    print(error(f"visual placement does not match approved layout_contract for page '{a.page}'", "use approved placement coordinates", "ad-pbip"))
                    return 2

            res = AU.visual_add(pbip, a.page, a.type, title=getattr(a, "title", None),
                                fields=getattr(a, "fields", None), position=pos)
        elif sub_c == "set":
            if "=" not in a.property:
                print(error("property must be format <object.property>=<value>", "", "ad-pbip"))
                return 2
            prop_path, val = a.property.split("=", 1)
            res = AU.visual_set(pbip, a.visual, prop_path, val)
        elif sub_c == "remove":
            res = AU.visual_remove(pbip, a.visual)
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check visual parameters with `ad-pbip catalog`", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip visual {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip visual {sub_c}", **res}}))
    return 0


def cmd_brief(a) -> int:
    sub_c = getattr(a, "brief_cmd", None)
    if sub_c == "check":
        findings = BR.check_brief(a.spec)
        return _findings_out(findings, f"ad-pbip brief check {a.spec}")
    if sub_c == "approve":
        try:
            res = BR.approve_brief(a.spec)
        except (RuntimeError, ValueError) as e:
            print(error(str(e), "run interactively in terminal", "ad-pbip"))
            return 2
        if not res.get("approved"):
            print(error("brief approval aborted by user", "", "ad-pbip"))
            return 1
        if policy.pretty():
            ui.facts([(k, str(v)) for k, v in res.items()], title="ad-pbip brief approve")
        else:
            print(toon.encode({"meta": {"source": "ad-pbip brief approve", **res}}))
        return 0
    if sub_c == "status":
        stat = BR.brief_status(a.spec)
        if policy.pretty():
            ui.facts([("spec", a.spec), ("status", stat)], title="ad-pbip brief status")
        else:
            print(toon.encode({"meta": {"ok": stat == "current", "source": "ad-pbip brief status", "spec": a.spec, "status": stat}}))
        return 0 if stat == "current" else 1
    return 0


def cmd_filter(a) -> int:
    sub_c = getattr(a, "filter_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "set":
            vals = [v.strip() for v in a.values.split(",")] if getattr(a, "values", None) else None
            bw = tuple(x.strip() for x in a.between.split(",")) if getattr(a, "between", None) else None
            res = AU.filter_set(pbip, a.scope, a.field, values=vals, between=bw,
                                top=getattr(a, "top", None), page=getattr(a, "page", None),
                                visual_id=getattr(a, "visual", None))
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check filter parameters", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip filter {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip filter {sub_c}", **res}}))
    return 0


def cmd_bookmark(a) -> int:
    sub_c = getattr(a, "bookmark_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            v_list = [v.strip() for v in a.visuals.split(",")] if getattr(a, "visuals", None) else None
            res = AU.bookmark_add(pbip, a.name, a.page, visuals=v_list)
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check bookmark parameters", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip bookmark {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip bookmark {sub_c}", **res}}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ad-pbip", description="PBIP projection, model<->report validation, TMDL lint and mechanical edits.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("project", help="write the LLM projection (.agent/pbip/<name>/)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--out"); p.add_argument("--force", action="store_true"); p.add_argument("--legacy-ok", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_project)
    p = sub.add_parser("check", help="cross-validate report fields against the TMDL model (+ TE2 build)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--te2", action="store_true"); p.add_argument("--te2-exe"); p.add_argument("--bpa", action="store_true")
    p.add_argument("--server", help="localhost:<port> (ad-pbip desktop) or an XMLA URL: evaluate every measure the report uses")
    p.add_argument("--db"); p.add_argument("--dscmd"); p.add_argument("--legacy-ok", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_check)
    p_dt = sub.add_parser("desktop", help="Power BI Desktop session control: status, open, close, reload")
    p_dt.add_argument("--pid", type=int, help="filter by process id (status)")
    p_dt.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    dt_sub = p_dt.add_subparsers(dest="desktop_cmd", required=False)

    p_stat = dt_sub.add_parser("status", help="list running Desktop instances (pid, port, pages, unsaved, version)")
    p_stat.add_argument("--pid", type=int, help="filter by process id")
    p_stat.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_stat.set_defaults(fn=cmd_desktop)

    p_open = dt_sub.add_parser("open", help="open a .pbip/.pbix in Desktop and wait until ready")
    p_open.add_argument("path", help="path to .pbip or .pbix")
    p_open.add_argument("--wait", type=int, default=180, help="seconds to wait for Desktop readiness (default: 180; 0=fire-and-forget)")
    p_open.add_argument("--exe", help="explicit path to PBIDesktop.exe")
    p_open.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_open.set_defaults(fn=cmd_desktop)

    p_close = dt_sub.add_parser("close", help="close a running Desktop instance cleanly via WM_CLOSE")
    p_close.add_argument("--pid", type=int, required=True, help="process id to close")
    g_close = p_close.add_mutually_exclusive_group()
    g_close.add_argument("--save", action="store_true", help="save changes if prompted")
    g_close.add_argument("--discard", action="store_true", help="discard changes if prompted")
    p_close.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_close.set_defaults(fn=cmd_desktop)

    p_reload = dt_sub.add_parser("reload", help="reload a running Desktop instance after file edits")
    p_reload.add_argument("--pid", type=int, required=True, help="process id to reload")
    g_rel = p_reload.add_mutually_exclusive_group()
    g_rel.add_argument("--save", action="store_true", help="save changes before reload if prompted")
    g_rel.add_argument("--discard", action="store_true", help="discard changes before reload if prompted")
    p_reload.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_reload.set_defaults(fn=cmd_desktop)

    p_dt.set_defaults(fn=cmd_desktop)

    p_cap = sub.add_parser("capabilities", help="probe Power BI Desktop and toolchain capabilities table")
    p_cap.add_argument("--pid", type=int, help="evaluate capabilities for a specific Desktop pid")
    p_cap.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p_cap.set_defaults(fn=cmd_capabilities)

    p_shot = sub.add_parser("screenshot", help="capture page or visual screenshots, or compare before/after images")
    p_shot.add_argument("--pid", type=int, help="running Desktop process id to capture")
    p_shot.add_argument("--page", help="page id or displayName to capture")
    p_shot.add_argument("--all", action="store_true", help="capture all pages")
    p_shot.add_argument("--scale", type=int, default=1, choices=[1, 2, 3], help="rendering scale multiplier (default: 1)")
    p_shot.add_argument("--visual", help="visual title or id to crop from page")
    p_shot.add_argument("--settle", type=float, default=0.5, help="seconds to wait for render settle (default: 0.5)")
    p_shot.add_argument("--out", help="output directory for captured images (default: .agent/out/shots/<ts>/)")
    p_shot.add_argument("--compare", nargs=2, metavar=("A", "B"), help="compare two images: --compare <a.png> <b.png>")
    p_shot.add_argument("--threshold", type=float, default=0.5, help="change ratio threshold for verdict (default: 0.5)")
    p_shot.add_argument("--mask", action="append", help="visual id to mask during compare")
    p_shot.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p_shot.set_defaults(fn=cmd_screenshot)

    p_hand = sub.add_parser("handoff", help="IPC callback when human clicks agentdata in Desktop ribbon")
    p_hand.add_argument("--server", required=True, help="Analysis Services localhost:<port> address from Desktop")
    p_hand.add_argument("--database", required=True, help="Analysis Services database GUID from Desktop")
    p_hand.add_argument("--project", help="explicit project folder to write .agent/desktop.json into")
    p_hand.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_hand.set_defaults(fn=cmd_handoff)

    p_reg = sub.add_parser("register-tool", help="register agentdata as Power BI Desktop External Tool")
    p_reg.add_argument("--python", help="explicit python executable path (default: sys.executable)")
    p_reg.add_argument("--target-dir", help="custom destination directory for .pbitool.json (testing/mock)")
    p_reg.add_argument("--project", help="explicit project directory to bake into tool arguments")
    p_reg.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_reg.set_defaults(fn=cmd_register_tool)

    p = sub.add_parser("launch", help="open a .pbip in Power BI Desktop")
    p.add_argument("path"); p.add_argument("--exe")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_launch)
    p = sub.add_parser("visual-query", help="build the visual's DAX (SUMMARIZECOLUMNS) and run it via dscmd")
    p.add_argument("pbip", nargs="?"); p.add_argument("--visual", required=True); p.add_argument("--page"); p.add_argument("--server")
    p.add_argument("--db"); p.add_argument("--dscmd"); p.add_argument("--top", type=int, default=500); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--name")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_visual_query)
    p = sub.add_parser("lint", help="TMDL syntax lint for a definition folder or one .tmdl file")
    p.add_argument("path")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("refs", help="where is a column/measure used; what feeds a visual or page")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table"); p.add_argument("--column"); p.add_argument("--measure"); p.add_argument("--visual"); p.add_argument("--page")
    p.add_argument("--live", action="store_true", help="reconcile against live DISCOVER_CALC_DEPENDENCY from server")
    p.add_argument("--server", help="Analysis Services server for --live")
    p.add_argument("--db", help="database name for --live")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_refs)

    p_dmv = sub.add_parser("dmv", help="run Analysis Services DMV query or shortcut (deps, segments, sessions, schema)")
    p_dmv.add_argument("query", help="DMV SQL query or shortcut name (deps, segments, sessions, schema)")
    p_dmv.add_argument("--server", help="localhost:<port> address")
    p_dmv.add_argument("--db", help="database name")
    p_dmv.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_dmv.set_defaults(fn=cmd_dmv)

    p_cost = sub.add_parser("page-cost", help="navigate to page and benchmark visual query latencies via trace")
    p_cost.add_argument("pbip", nargs="?")
    p_cost.add_argument("--pid", type=int, help="running Desktop process id")
    p_cost.add_argument("--page", required=True, help="page id or displayName to evaluate")
    p_cost.add_argument("--seconds", type=int, default=15, help="trace duration in seconds (default: 15)")
    p_cost.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cost.set_defaults(fn=cmd_page_cost)

    p_tr = sub.add_parser("trace", help="Analysis Services trace control and aggregation")
    tr_sub = p_tr.add_subparsers(dest="trace_cmd", required=True)
    p_ts = tr_sub.add_parser("start", help="start trace listener and launch TE2 trace script")
    p_ts.add_argument("--pid", type=int, help="running Desktop process id")
    p_ts.add_argument("--server", help="localhost:<port> address")
    p_ts.add_argument("--db", help="database name")
    p_ts.add_argument("--seconds", type=int, default=60, help="duration in seconds (default: 60)")
    p_ts.add_argument("--out", help="output .jsonl file path (default: .agent/out/trace-<ts>.jsonl)")
    p_ts.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ts.set_defaults(fn=cmd_trace)

    p_tr_rep = tr_sub.add_parser("report", help="aggregate and correlate trace .jsonl events to visuals")
    p_tr_rep.add_argument("file", help="path to trace .jsonl file")
    p_tr_rep.add_argument("pbip", nargs="?", help="optional PBIP path to correlate visual names")
    p_tr_rep.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_tr_rep.set_defaults(fn=cmd_trace)
    m = sub.add_parser("measure", help="mechanical measure edits").add_subparsers(dest="mcmd", required=True)
    p = m.add_parser("set", help="add or replace a measure with correct TMDL layout")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table", required=True); p.add_argument("--name", required=True)
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--expr"); g.add_argument("--expr-file")
    p.add_argument("--format-string"); p.add_argument("--display-folder"); p.add_argument("--description"); p.add_argument("--hidden", action="store_true")
    p.add_argument("--lineage-tag", action="store_true", help="write a new lineageTag (default: none; Desktop assigns on save)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_measure_set)

    # Schema
    p_sc = sub.add_parser("schema", help="vendored PBIR JSON schema validation and updates")
    sc_sub = p_sc.add_subparsers(dest="schema_cmd", required=True)
    p_sc_up = sc_sub.add_parser("update", help="validate and refresh vendored schemas against VERSION metadata")
    p_sc_up.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_sc_up.set_defaults(fn=cmd_schema)

    # Catalog
    p_cat = sub.add_parser("catalog", help="schema-driven visual catalog: visual types, roles, and formatting")
    cat_sub = p_cat.add_subparsers(dest="catalog_cmd", required=True)
    p_cl = cat_sub.add_parser("list", help="list available visual types, roles, and deprecation status")
    p_cl.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cl.set_defaults(fn=cmd_catalog)
    p_cd = cat_sub.add_parser("describe", help="describe roles and cardinality constraints for visual type")
    p_cd.add_argument("type", help="visual type name (e.g. columnChart, cardVisual, tableEx)")
    p_cd.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cd.set_defaults(fn=cmd_catalog)
    p_cf = cat_sub.add_parser("formatting", help="inspect formatting objects, properties, and enum values")
    p_cf.add_argument("type", nargs="?", help="optional visual type name")
    p_cf.add_argument("--object", help="filter by formatting object name (e.g. title, background)")
    p_cf.add_argument("--property", help="filter by property name (e.g. text, color)")
    p_cf.add_argument("--search", help="search formatting descriptions and names")
    p_cf.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cf.set_defaults(fn=cmd_catalog)

    # Expr
    p_ex = sub.add_parser("expr", help="QueryExpressionContainer encoding and decoding")
    ex_sub = p_ex.add_subparsers(dest="expr_cmd", required=True)
    p_ee = ex_sub.add_parser("encode", help="encode human field reference into QueryExpressionContainer JSON")
    p_ee.add_argument("text", help="field reference (e.g. 'Sales'[Amount], [Margin], Sum('Sales'[Qty]))")
    p_ee.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ee.set_defaults(fn=cmd_expr)
    p_ed = ex_sub.add_parser("decode", help="decode QueryExpressionContainer JSON into human field reference")
    p_ed.add_argument("json", help="QueryExpressionContainer JSON string")
    p_ed.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ed.set_defaults(fn=cmd_expr)

    # Theme
    p_th = sub.add_parser("theme", help="report theme shading and registration")
    th_sub = p_th.add_subparsers(dest="theme_cmd", required=True)
    p_ts = th_sub.add_parser("shade", help="shade (darken) or tint (lighten) a hex color")
    p_ts.add_argument("--color", required=True, help="hex color (e.g. #1F77B4)")
    p_ts.add_argument("--pct", type=float, required=True, help="percentage to darken (negative) or lighten (positive), e.g. -20")
    p_ts.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ts.set_defaults(fn=cmd_theme)
    p_tset = th_sub.add_parser("set", help="register custom theme in report.json and copy to StaticResources")
    p_tset.add_argument("pbip", nargs="?", help="PBIP root path")
    p_tset.add_argument("--file", required=True, help="path to theme.json file")
    p_tset.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_tset.set_defaults(fn=cmd_theme)

    # Preview
    p_prev = sub.add_parser("preview", help="preview report structure as tabular views")
    prev_sub = p_prev.add_subparsers(dest="preview_cmd", required=True)
    for pslot in ("pages", "visuals", "filters", "themes"):
        pp = prev_sub.add_parser(pslot, help=f"preview report {pslot}")
        pp.add_argument("pbip", nargs="?", help="PBIP root path")
        pp.add_argument("--pretty", action="store_true", help="draw it as a table")
        pp.set_defaults(fn=cmd_preview)

    # Page
    p_pg = sub.add_parser("page", help="mechanical page edits (add, remove, move)")
    pg_sub = p_pg.add_subparsers(dest="page_cmd", required=True)
    p_pa = pg_sub.add_parser("add", help="add new page")
    p_pa.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pa.add_argument("--name", required=True, help="display name of the page")
    p_pa.add_argument("--after", help="insert after this page id or display name")
    p_pa.add_argument("--width", type=int, default=1280, help="canvas width (default: 1280)")
    p_pa.add_argument("--height", type=int, default=720, help="canvas height (default: 720)")
    p_pa.add_argument("--brief", help="path to approved report-spec.md (validates approval and layout contract)")
    p_pa.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pa.set_defaults(fn=cmd_page)
    p_pr = pg_sub.add_parser("remove", help="remove page")
    p_pr.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pr.add_argument("--page", required=True, help="page id or display name to remove")
    p_pr.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pr.set_defaults(fn=cmd_page)
    p_pm = pg_sub.add_parser("move", help="reorder page in pages.json")
    p_pm.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pm.add_argument("--page", required=True, help="page id or display name to move")
    p_pm.add_argument("--after", help="place after this page id or display name (default: move to first)")
    p_pm.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pm.set_defaults(fn=cmd_page)

    # Visual
    p_vis = sub.add_parser("visual", help="mechanical visual edits (add, set, remove)")
    vis_sub = p_vis.add_subparsers(dest="visual_cmd", required=True)
    p_va = vis_sub.add_parser("add", help="add visual with schema validation")
    p_va.add_argument("pbip", nargs="?", help="PBIP root path")
    p_va.add_argument("--page", required=True, help="page id or display name")
    p_va.add_argument("--type", required=True, help="visual type (e.g. columnChart, cardVisual, tableEx)")
    p_va.add_argument("--title", help="visual title text")
    p_va.add_argument("--fields", nargs="+", help="fields in format 'Table'[Column] or [Measure]")
    p_va.add_argument("--position", help="position format x,y,width,height (e.g. 20,20,500,300)")
    p_va.add_argument("--brief", help="path to approved report-spec.md (validates approval and layout contract)")
    p_va.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_va.set_defaults(fn=cmd_visual)
    p_vs = vis_sub.add_parser("set", help="set visual formatting or position property")
    p_vs.add_argument("pbip", nargs="?", help="PBIP root path")
    p_vs.add_argument("--visual", required=True, help="visual id (20-hex)")
    p_vs.add_argument("--property", required=True, help="property in format <object.property>=<value> or position.x=10")
    p_vs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_vs.set_defaults(fn=cmd_visual)
    p_vr = vis_sub.add_parser("remove", help="remove visual")
    p_vr.add_argument("pbip", nargs="?", help="PBIP root path")
    p_vr.add_argument("--visual", required=True, help="visual id (20-hex) to remove")
    p_vr.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_vr.set_defaults(fn=cmd_visual)

    # Filter
    p_flt = sub.add_parser("filter", help="mechanical filter edits")
    flt_sub = p_flt.add_subparsers(dest="filter_cmd", required=True)
    p_fs = flt_sub.add_parser("set", help="set report, page, or visual level filter")
    p_fs.add_argument("pbip", nargs="?", help="PBIP root path")
    p_fs.add_argument("--scope", required=True, choices=["report", "page", "visual"], help="filter scope")
    p_fs.add_argument("--page", help="page id or display name (for page scope)")
    p_fs.add_argument("--visual", help="visual id (for visual scope)")
    p_fs.add_argument("--field", required=True, help="field reference 'Table'[Column]")
    g_flt = p_fs.add_mutually_exclusive_group(required=True)
    g_flt.add_argument("--values", help="comma-separated values for categorical filter (e.g. 2024,2025)")
    g_flt.add_argument("--between", help="lower,upper bounds for between filter")
    g_flt.add_argument("--top", type=int, help="top count for TopN filter")
    p_fs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_fs.set_defaults(fn=cmd_filter)

    # Bookmark
    p_bm = sub.add_parser("bookmark", help="mechanical bookmark edits")
    bm_sub = p_bm.add_subparsers(dest="bookmark_cmd", required=True)
    p_ba = bm_sub.add_parser("add", help="create new bookmark")
    p_ba.add_argument("pbip", nargs="?", help="PBIP root path")
    p_ba.add_argument("--name", required=True, help="bookmark display name")
    p_ba.add_argument("--page", required=True, help="active page id or display name")
    p_ba.add_argument("--visuals", help="comma-separated list of visual ids to capture")
    p_ba.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ba.set_defaults(fn=cmd_bookmark)

    # Brief
    p_br = sub.add_parser("brief", help="report specification and design brief validation and approval")
    br_sub = p_br.add_subparsers(dest="brief_cmd", required=True)
    p_bc = br_sub.add_parser("check", help="validate brief layout_contract, space_audit, and model fields")
    p_bc.add_argument("spec", help="path to report-spec.md file")
    p_bc.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bc.set_defaults(fn=cmd_brief)
    p_ba_app = br_sub.add_parser("approve", help="terminal-only interactive human approval gate")
    p_ba_app.add_argument("spec", help="path to report-spec.md file")
    p_ba_app.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ba_app.set_defaults(fn=cmd_brief)
    p_bs = br_sub.add_parser("status", help="check brief approval status (current, stale, missing)")
    p_bs.add_argument("spec", help="path to report-spec.md file")
    p_bs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bs.set_defaults(fn=cmd_brief)
    return ap


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = build_parser()
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        sys.exit(a.fn(a))
    except (FileNotFoundError, ValueError) as e:
        print(error(str(e)[:300], "pass the folder that contains the .pbip (or set pbip_path in AGENTS.md)", "ad-pbip")); sys.exit(2)
    except C.ConfigError as e:
        print(error(str(e), e.hint, "ad-pbip")); sys.exit(2)


if __name__ == "__main__":
    main()
