"""`ad-dpm inspect`: what a run root actually contains, and whether every bound name resolves against it. Never refuses:
this is the tool you run when locate/validate refused, to see what to rebind or what to report to DPM."""
from __future__ import annotations
import glob
import os
import sqlite3

from . import DpmError
from .run import Run, norm_version

KEYWORDS = {
    "document_id": ["doc", "id"], "loan_id": ["loan"], "sha256": ["sha", "hash", "digest"],
    "channel": ["chan", "source", "intake", "origin"], "source_path": ["path", "file", "uri", "location"],
    "page_count": ["page", "count"], "mime_type": ["mime", "type", "content"], "status": ["status", "state"],
    "page_number": ["page", "num"], "run_id": ["run"], "version": ["version", "schema"], "items": ["item", "doc", "page", "entries"],
    "selection_id": ["select", "id"], "pages": ["page"], "page": ["page", "num", "index"], "has_native_text": ["native", "text", "layer"],
    "char_count": ["char", "len", "count"], "text_quality": ["quality", "conf", "score"], "text_path": ["path", "file", "txt"],
    "unsupported": ["unsupp", "error", "reject"], "table": ["doc", "manifest", "file", "source"],
}


def candidates(concept: str, names) -> list[str]:
    kws = KEYWORDS.get(concept, [concept])
    return sorted({n for n in names if isinstance(n, str) and any(k in n.lower() for k in kws)})[:6]


def describe(run: Run) -> dict:
    b = run.b
    rows: list[dict] = []
    problems: list[str] = []

    def row(concept: str, bound, status: str, cands=None, observed=None) -> None:
        rows.append({"concept": concept, "bound": bound if isinstance(bound, str) else ";".join(map(str, bound)), "status": status,
                     "candidates": ";".join(cands or []), "observed": "" if observed is None else str(observed)})

    rr = b["run_root"]
    root_files = sorted(os.listdir(run.root)) if os.path.isdir(run.root) else []
    row("run_root.orchestrator_db", rr["orchestrator_db"], "ok" if os.path.isfile(run.db_path) else "missing",
        [f for f in root_files if f.lower().endswith((".db", ".sqlite", ".sqlite3"))])
    row("run_root.text_analysis_dir", rr["text_analysis_dir"], "ok" if os.path.isdir(run.analysis_dir) else "missing",
        [f for f in root_files if os.path.isdir(os.path.join(run.root, f)) and ("text" in f.lower() or "analy" in f.lower())])
    sel_paths = run.selection_paths()
    row("run_root.selection_manifests", rr["selection_manifests"], "ok" if sel_paths else "missing",
        [] if sel_paths else [run.rel(p) for p in glob.glob(os.path.join(run.root, "*.json")) + glob.glob(os.path.join(run.root, "*", "*.json"))][:6],
        observed=len(sel_paths))

    tables: list[dict] = []
    db_ok = True
    try:
        for t, cols in run.tables().items():
            try:
                n_rows = run.count(t)
            except sqlite3.Error as e:            # a view over a dropped table: report it, never traceback
                n_rows = -1
                problems.append(f"{t}: {e}")
            tables.append({"table": t, "rows": n_rows, "columns": ";".join(cols)})
    except (DpmError, sqlite3.Error) as e:
        db_ok = False
        problems.append(getattr(e, "msg", str(e)))
    table_names = [t["table"] for t in tables]

    versions: dict = {}
    supported = None
    if db_ok:
        spec = rr.get("run_id") or {}
        try:
            observed_run = run.run_id()
        except sqlite3.Error as e:
            observed_run = ""
            problems.append(str(e))
        row("run_root.run_id", f"{spec.get('table')}.{spec.get('column')}", "ok" if run.has(spec.get("table"), spec.get("column")) else "fallback: folder name",
            observed=observed_run)
        vspec = b["versions"]["orchestrator"]
        try:
            versions = run.versions()
        except sqlite3.Error as e:
            versions = {}
            problems.append(str(e))
        row("versions.orchestrator", f"user_version | {vspec.get('table')}.{vspec.get('column')}",
            "ok" if any(v is not None for v in versions.values()) else "missing",
            candidates("version", table_names), observed=" ".join(f"{k}={v}" for k, v in versions.items() if v is not None))
        try:
            run.check_versions()
            supported = True
        except DpmError as e:
            supported = False
            problems.append(e.msg)
        c = b["canonical"]
        if run.has(c["table"]):
            try:
                observed_rows = run.count(c["table"])
            except sqlite3.Error as e:
                observed_rows = "?"
                problems.append(str(e))
            row("canonical.table", c["table"], "ok", observed=observed_rows)
            cols = run.tables()[c["table"]]
            for concept, col in c["columns"].items():
                if col in cols:
                    row(f"canonical.columns.{concept}", col, "ok")
                else:
                    row(f"canonical.columns.{concept}", col, "optional-missing" if concept in c.get("optional_columns", []) else "missing", candidates(concept, cols))
        else:
            row("canonical.table", c["table"], "missing", candidates("table", table_names))
        p = b.get("pages") or {}
        pc = p.get("columns", {})
        pages_ok = run.has(p.get("table"), pc.get("document_id")) and run.has(p.get("table"), pc.get("page_number"))
        row("pages.table", f"{p.get('table')}({pc.get('document_id')},{pc.get('page_number')})", "ok" if pages_ok else ("missing" if p.get("required") else "optional-missing"),
            [] if pages_ok else candidates("page", table_names))
        ch = b["channels"]
        if ch.get("allowed"):
            row("channels", ch["allowed"], "ok (binding list)")
        elif run.has(ch.get("table"), ch.get("column")):
            try:
                observed_ch = run.count(ch["table"])
            except sqlite3.Error as e:
                observed_ch = "?"
                problems.append(str(e))
            row("channels", f"{ch['table']}.{ch['column']}", "ok", observed=observed_ch)
        else:
            row("channels", f"{ch.get('table')}.{ch.get('column')}", "unconstrained", candidates("channel", table_names))

    manifests: list[dict] = []
    if sel_paths:
        k, vs = b["selection"]["keys"], b["versions"]["selection_manifest"]
        first = None
        for sp in sel_paths:
            try:
                data = run._json(sp, "selection manifest")
            except DpmError as e:
                problems.append(e.msg)
                continue
            if not isinstance(data, dict):
                problems.append(f"{run.rel(sp)}: top level is not an object")
                continue
            first = first or data
            items = data.get(k["items"])
            manifests.append({"path": run.rel(sp), "selection_id": data.get(k["selection_id"]), "version": norm_version(data.get(vs["key"])),
                              "items": len(items) if isinstance(items, list) else None, "top_keys": ";".join(map(str, data.keys()))})
        if first is not None:
            keys = list(first.keys())
            for concept in ("selection_id", "items"):
                row(f"selection.keys.{concept}", k[concept], "ok" if k[concept] in first else "missing", [] if k[concept] in first else candidates(concept, keys))
            row("selection.keys.run_id", k["run_id"], "ok" if k["run_id"] in first else "optional-missing", observed=first.get(k["run_id"]))
            row("versions.selection_manifest", vs["key"], "ok" if norm_version(first.get(vs["key"])) else "missing", candidates("version", keys),
                observed=first.get(vs["key"]))
            items = first.get(k["items"])
            item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
            if item is not None:
                ikeys = list(item.keys())
                has_ref = k["document_id"] in item or k["sha256"] in item
                row("selection.keys.document_id|sha256", f"{k['document_id']}|{k['sha256']}", "ok" if has_ref else "missing",
                    [] if has_ref else candidates("document_id", ikeys) + candidates("sha256", ikeys))
                for concept in ("loan_id", "pages"):
                    row(f"selection.keys.{concept}", k[concept], "ok" if k[concept] in item else "optional-missing", [] if k[concept] in item else candidates(concept, ikeys))

    analysis: dict = {"files": 0, "sample": "", "top_keys": "", "page_keys": ""}
    if os.path.isdir(run.analysis_dir):
        names = sorted(os.listdir(run.analysis_dir))
        analysis["files"] = len(names)
        sample = None
        if db_ok and run.has(b["canonical"]["table"]):
            try:
                docs = run.canonical_documents()
            except DpmError as e:
                docs = []
                problems.append(e.msg)
            if docs:
                d0 = docs[0]
                rel = run.analysis_rel(d0.get("document_id"), d0.get("sha256"))
                exists = os.path.isfile(os.path.join(run.root, rel))
                row("text_analysis.file", b["text_analysis"]["file"], "ok" if exists else "missing", [] if exists else names[:6], observed=rel)
                if exists:
                    try:
                        sample = run._json(os.path.join(run.root, rel), "text_analysis output")
                        analysis["sample"] = rel
                    except DpmError as e:
                        problems.append(e.msg)
        if isinstance(sample, dict):
            ak, vs = b["text_analysis"]["keys"], b["versions"]["text_analysis"]
            keys = list(sample.keys())
            analysis["top_keys"] = ";".join(map(str, keys))
            row("versions.text_analysis", vs["key"], "ok" if norm_version(sample.get(vs["key"])) else "missing", candidates("version", keys), observed=sample.get(vs["key"]))
            row("text_analysis.keys.pages", ak["pages"], "ok" if isinstance(sample.get(ak["pages"]), list) else "missing", candidates("pages", keys))
            pages = sample.get(ak["pages"])
            entry = pages[0] if isinstance(pages, list) and pages and isinstance(pages[0], dict) else None
            if entry is not None:
                ekeys = list(entry.keys())
                analysis["page_keys"] = ";".join(map(str, ekeys))
                for concept in ("page", "has_native_text"):
                    row(f"text_analysis.keys.{concept}", ak[concept], "ok" if ak[concept] in entry else "missing", [] if ak[concept] in entry else candidates(concept, ekeys))
                for concept in ("char_count", "text_quality", "text_path"):
                    row(f"text_analysis.keys.{concept}", ak[concept], "ok" if ak[concept] in entry else "optional-missing", [] if ak[concept] in entry else candidates(concept, ekeys))
    binding_ok = not any(r["status"] == "missing" for r in rows)
    return {"tables": tables, "binding": rows, "manifests": manifests, "analysis": analysis, "versions": versions,
            "supported": supported, "binding_ok": binding_ok, "problems": problems}
