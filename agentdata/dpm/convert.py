"""Routes, the consumer job manifest with lineage, the governed artifacts, and later lineage verification."""
from __future__ import annotations
import csv
import json
import os
import re
from datetime import datetime, timezone

from .. import textio
from . import DpmError
from .guard import file_sha256
from .run import Run
from .validate import Doc, Finding, Result, native_reusable

JOB_MANIFEST_VERSION = "1"
CONTRACT_VERSION = 1
FILES = ("job-manifest.json", "jobs.tsv", "excluded.tsv", "validation.tsv", "lineage.tsv", "receipt.json")
JOB_COLS = ["job_id", "route", "selection_id", "loan_id", "document_id", "sha256", "page", "page_count", "source_path", "text_path",
            "char_count", "text_quality"]
EXCL_COLS = ["document_id", "sha256", "loan_id", "selection_id", "bucket", "reasons", "pages", "source_path", "manifest"]
LINEAGE_COLS = ["job_id", "producer", "run_id", "selection_manifest", "selection_item", "canonical_table", "canonical_rowid",
                "document_id", "source_sha256", "source_path", "page", "text_analysis", "text_path"]
FINDING_COLS = ["severity", "kind", "where", "object", "message", "hint"]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tool_version() -> str:
    try:
        from importlib.metadata import version
        return version("agentdata")
    except Exception:  # noqa: BLE001
        return "0"


def safe_name(s) -> str:
    return re.sub(r"[^\w.\-]+", "_", str(s)).strip("._") or "run"


def job_id(d: Doc, page: int) -> str:
    return f"{d.selection_id}:{d.document_id}:p{page}"


def lineage(run: Run, run_id: str, d: Doc, page: int | None = None) -> dict:
    e = d.page_info.get(page) or {} if page is not None else {}
    return {"producer": run.b["producer"], "run_id": run_id, "selection_manifest": d.manifest, "selection_item": d.item_index,
            "canonical_table": run.b["canonical"]["table"], "canonical_rowid": d.canonical_rowid, "document_id": d.document_id,
            "source_sha256": d.sha256, "source_path": d.source_rel or d.source_path, "page": page, "text_analysis": d.analysis_rel,
            "text_path": e.get("text_rel")}


def build(run: Run, result: Result, *, consumer_root: str, artifact_dir: str, binding_label: str, binding_sha: str,
          snapshot_sha: str, snapshot_files: int, generated_at: str | None = None) -> dict:
    part = run.b["partition"]
    jobs: list[dict] = []
    excluded: list[dict] = []
    for d in sorted(result.docs, key=lambda x: (x.selection_id or "", x.label, x.item_index)):
        if d.bucket != "resolved":
            excluded.append({"document_id": d.document_id, "sha256": d.sha256, "loan_id": d.loan_id, "selection_id": d.selection_id,
                             "bucket": d.bucket, "reasons": list(dict.fromkeys(d.unresolved or d.unsupported)), "pages": d.pages,
                             "source_path": d.source_rel or d.source_path, "lineage": lineage(run, result.run_id, d)})
            continue
        for p in d.pages:
            e = d.page_info.get(p, {})
            native = native_reusable(e, part)
            jobs.append({"job_id": job_id(d, p), "route": "native_text" if native else "ocr", "selection_id": d.selection_id,
                         "loan_id": d.loan_id, "document_id": d.document_id, "sha256": d.sha256, "page": p, "page_count": d.page_count,
                         "source_path": d.source_rel, "text_path": e.get("text_rel") if native else None,
                         "char_count": e.get("char_count"), "text_quality": e.get("text_quality"), "lineage": lineage(run, result.run_id, d, p)})
    counts = result.counts()
    counts["jobs"] = len(jobs)
    versions = dict(run.versions())
    versions["selection_manifest"] = sorted({s.version for s in result.selections if s.version})
    versions["text_analysis"] = run.analysis_versions()
    return {
        "job_manifest_version": JOB_MANIFEST_VERSION,
        "contract": {"name": "dpm-consumer-integration", "version": CONTRACT_VERSION, "binding": binding_label, "binding_sha256": binding_sha},
        "producer": {"name": run.b["producer"], "run_id": result.run_id, "run_root": textio.norm_path(run.root),
                     "orchestrator_db": run.rel(run.db_path), "orchestrator_db_sha256": file_sha256(run.db_path), "versions": versions,
                     "selection_manifests": [s.path for s in result.selections], "channels": result.channels_source,
                     "snapshot_sha256": snapshot_sha, "snapshot_files": snapshot_files},
        "consumer": {"name": run.b["consumer"], "root": textio.norm_path(os.path.abspath(consumer_root)),
                     "artifact_dir": textio.norm_path(os.path.abspath(artifact_dir)), "generated_at": generated_at or now_iso(),
                     "generator": f"agentdata ad-dpm convert {tool_version()}"},
        "counts": counts,
        "jobs": jobs,
        "excluded": excluded,
    }


def _tsv(path: str, cols: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else (";".join(map(str, v)) if isinstance(v, list) else v) for v in r])


def present(out_dir: str) -> list[str]:
    return [f for f in FILES if os.path.exists(os.path.join(out_dir, f))]


def refuse_if_present(out_dir: str, *, force: bool) -> list[str]:
    """`artifacts_exist` as early as possible: the caller has not hashed anything yet."""
    existing = present(out_dir)
    if existing and not force:
        raise DpmError("artifacts_exist", f"{textio.norm_path(out_dir)} already holds {', '.join(existing)}",
                       "pass --force to replace the previous handoff for this run id (the receipt records the replacement)")
    return existing


def write(manifest: dict, findings: list[Finding], out_dir: str, *, force: bool, receipt: dict) -> list[dict]:
    """Write the governed artifacts. Refuses to overwrite a previous handoff for the same run id unless force."""
    existing = refuse_if_present(out_dir, force=force)
    os.makedirs(out_dir, exist_ok=True)
    p = lambda name: os.path.join(out_dir, name)  # noqa: E731
    with open(p("job-manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    _tsv(p("jobs.tsv"), JOB_COLS, [[j.get(c) for c in JOB_COLS] for j in manifest["jobs"]])
    _tsv(p("excluded.tsv"), EXCL_COLS, [[x.get(c) if c != "manifest" else x["lineage"]["selection_manifest"] for c in EXCL_COLS] for x in manifest["excluded"]])
    _tsv(p("validation.tsv"), FINDING_COLS, [f.row() for f in findings])
    _tsv(p("lineage.tsv"), LINEAGE_COLS, [[j["job_id"]] + [j["lineage"].get(c) for c in LINEAGE_COLS[1:]] for j in manifest["jobs"]])
    files = []
    for name in FILES[:-1]:
        files.append({"path": name, "sha256": file_sha256(p(name)), "bytes": os.path.getsize(p(name))})
    receipt = dict(receipt)
    receipt["files"] = files
    receipt["replaced"] = existing
    with open(p("receipt.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
        f.write("\n")
    files.append({"path": "receipt.json", "sha256": file_sha256(p("receipt.json")), "bytes": os.path.getsize(p("receipt.json"))})
    return files


def load_manifest(path: str) -> dict:
    try:
        m = textio.read_json(path, "job manifest")
    except (OSError, ValueError) as e:
        raise DpmError("manifest_invalid", f"cannot read job manifest {path}: {e}",
                       "pass the job-manifest.json written by ad-dpm convert") from None
    if not isinstance(m, dict) or str(m.get("job_manifest_version")) != JOB_MANIFEST_VERSION or "jobs" not in m:
        raise DpmError("unsupported_version", f"{path} is not a job manifest version {JOB_MANIFEST_VERSION}", "only manifests written by ad-dpm convert can be verified")
    return m


def verify(manifest: dict, *, run_root: str | None = None, rehash: bool = True) -> dict:
    """Re-resolve every job's lineage against the run root: orchestrator.db unchanged, source file present and (rehash)
    identical, selection manifest present, native text file present."""
    root = os.path.abspath(run_root or manifest["producer"]["run_root"])
    if not os.path.isdir(root):
        raise DpmError("run_root_missing", f"run root {root} not found", "pass --run-root if the run moved; the manifest records where it was")
    prod = manifest["producer"]
    db = os.path.join(root, prod["orchestrator_db"])
    db_ok = os.path.isfile(db) and file_sha256(db) == prod.get("orchestrator_db_sha256")
    rows: list[dict] = []
    hashes: dict[str, str] = {}
    for j in manifest["jobs"]:
        reasons: list[str] = []
        ln = j.get("lineage", {})
        sel = ln.get("selection_manifest")
        if not sel or not os.path.isfile(os.path.join(root, sel)):
            reasons.append("selection manifest missing")
        src = j.get("source_path")
        sp = os.path.join(root, src) if src and not os.path.isabs(src) else src
        if not sp or not os.path.isfile(sp):
            reasons.append("source missing")
        elif rehash:
            h = hashes.get(sp) or hashes.setdefault(sp, file_sha256(sp))
            if h != j.get("sha256"):
                reasons.append("source sha256 changed")
        if j.get("route") == "native_text":
            tp = j.get("text_path")
            if not tp or not os.path.isfile(os.path.join(root, tp)):
                reasons.append("native text missing")
        if not db_ok:
            reasons.append("orchestrator.db changed")
        rows.append({"job_id": j["job_id"], "route": j.get("route"), "document_id": j.get("document_id"), "page": j.get("page"),
                     "status": "broken" if reasons else "ok", "reason": "; ".join(reasons)})
    broken = sum(1 for r in rows if r["status"] == "broken")
    return {"run_root": textio.norm_path(root), "orchestrator_db_ok": db_ok, "jobs": len(rows), "ok_count": len(rows) - broken,
            "broken": broken, "rows": rows, "ok": db_ok and broken == 0}
