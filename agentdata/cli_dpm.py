# PYTHON_ARGCOMPLETE_OK
"""ad-dpm: locate · inspect · validate · convert · lineage · binding.

The DPM run root is read-only (SQLite opened immutable; a tree fingerprint before and after every command proves nothing
changed). Generated artifacts go only beneath the consumer repository's governed artifact directory. Contract refusals
(unsupported version, binding mismatch, path outside the governed dir, ...) print `meta.refused` and exit 2; validation
failures exit 1; success exits 0."""
from __future__ import annotations
import argparse
import os
import sys

from . import completion
from . import config as C
from . import toon
from .console import utf8_stdout
from .dpm import DpmError
from .dpm import binding as B
from .dpm import convert as CV
from .dpm import describe as DS
from .dpm import guard as G
from .dpm import validate as V
from .dpm.run import Run
from .model import AgentTable
from . import policy, ui
from .policy import error, render

SHOW = 50


def _consumer(a) -> str:
    return os.path.abspath(a.consumer or ".")


def _binding(a, consumer: str) -> tuple[dict, str, str]:
    path = C.resolve("dpm_binding", flag=a.binding, env="DPM_BINDING", cfg=C.load(), cfg_path="dpm.binding", facts=C.project_facts(), default="")
    if path and not os.path.isabs(path):
        path = os.path.join(consumer, path)
    b, label = B.load(path or None)
    return b, label, B.sha256(b)


def _locate(a, b: dict, *, check: bool = True) -> Run:
    facts, cfg = C.project_facts(), C.load()
    run_root = C.resolve("dpm_run_root", flag=a.run_root, env="DPM_RUN_ROOT", cfg=cfg, cfg_path="dpm.run_root", facts=facts, default="")
    runs_dir = C.resolve("dpm_runs_dir", flag=a.runs_dir, env="DPM_RUNS_DIR", cfg=cfg, cfg_path="dpm.runs_dir", facts=facts, default="")
    if (a.run_id or a.latest) and not a.run_root:
        run_root = ""   # an explicit run selection beats a remembered run root
    run = Run.locate(b, run_root=run_root or None, runs_dir=runs_dir or None, run_id=a.run_id, latest=a.latest)
    if check:
        run.check_versions()
        run.canonical_documents()   # the binding must resolve before any work
    return run


def _short(h: str) -> str:
    return h[:12]


def cmd_locate(a) -> int:
    consumer = _consumer(a)
    b, label, bsha = _binding(a, consumer)
    run = _locate(a, b)
    snap = G.snapshot(run.root)
    analysis_files = len(os.listdir(run.analysis_dir))
    meta = {"ok": True, "source": "ad-dpm locate", "run_root": run.root.replace("\\", "/"), "run_id": run.run_id(),
            "orchestrator_db": run.rel(run.db_path), "selection_manifests": len(run.selection_paths()),
            "text_analysis_files": analysis_files, "canonical_documents": run.count(b["canonical"]["table"]),
            **{k: v for k, v in run.versions().items() if v is not None},
            "binding": label, "binding_sha256": _short(bsha), "snapshot_sha256": _short(snap["sha256"]), "snapshot_files": snap["files"],
            "next": "ad-dpm validate --run-root <run_root>"}
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm locate")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def cmd_inspect(a) -> int:
    consumer = _consumer(a)
    b, label, bsha = _binding(a, consumer)
    run = _locate(a, b, check=False)
    d = DS.describe(run)
    meta = {"ok": d["binding_ok"] and bool(d["supported"]), "source": "ad-dpm inspect", "run_root": run.root.replace("\\", "/"),
            "binding": label, "binding_sha256": _short(bsha), "binding_ok": d["binding_ok"], "supported_version": d["supported"],
            "tables": len(d["tables"]), "selection_manifests": len(d["manifests"]), "text_analysis_files": d["analysis"]["files"]}
    if d["problems"]:
        meta["problems"] = d["problems"]
    if not d["binding_ok"]:
        meta["hint"] = ("a `missing` row is a name DPM uses differently: ad-dpm binding --write <consumer>/dpm-binding.json, set that concept to "
                        "the candidate, point the dpm_binding fact at the file, re-run. Rebinding is a contract change: show Michael the diff.")
    elif d["supported"] is False:
        meta["hint"] = "the producer version is not supported; hand off to Michael / the DPM owners (see problems)"
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm inspect", subtitle="ok" if meta["ok"] else "fail")
        if d.get("tables"):
            ui.table(["table", "rows", "status"], [[t.get("name"), t.get("rows"), t.get("status", "ok")] for t in d["tables"]], title="tables", status_col=2)
    else:
        print(toon.encode({"meta": meta, "tables": d["tables"], "binding": d["binding"], "manifests": d["manifests"], "analysis": d["analysis"]}))
    return 0 if meta["ok"] else 1


def _findings_table(findings, source: str) -> AgentTable:
    return AgentTable.from_records([f.record() for f in findings], name="dpm_findings", source=source, fields=CV.FINDING_COLS)


def cmd_validate(a) -> int:
    consumer = _consumer(a)
    b, label, bsha = _binding(a, consumer)
    run = _locate(a, b)
    before = G.snapshot(run.root)
    res = V.validate(run, hash_sources=not a.no_hash)
    run.close()
    after = G.snapshot(run.root)
    untouched = before["sha256"] == after["sha256"]
    counts = res.counts()
    ok = counts["errors"] == 0 and untouched
    meta = {"ok": ok, "run_root": run.root.replace("\\", "/"), "run_id": res.run_id, **counts, "channels": res.channels_source,
            "hash_verified": not a.no_hash, "binding": label, "binding_sha256": _short(bsha), "run_root_untouched": untouched}
    if not untouched:
        meta["changed"] = G.diff(before, after)[:20]
        meta["hint"] = "the run root changed while it was being read: it is not frozen; ask DPM before converting"
    elif counts["errors"]:
        meta["hint"] = "every error is a reference that does not resolve; report them to DPM (never edit the run root); convert excludes those documents"
    elif counts["unsupported"]:
        meta["hint"] = f"{counts['unsupported']} document(s) are unsupported (see warnings); convert lists them in excluded.tsv"
    order = {"error": 0, "warning": 1, "info": 2}
    res.findings.sort(key=lambda f: (order.get(f.severity, 3), f.kind, f.where))
    print(render(_findings_table(res.findings, "ad-dpm validate"), extra=meta))
    return 0 if ok else 1


def cmd_convert(a) -> int:
    consumer = _consumer(a)
    b, label, bsha = _binding(a, consumer)
    run = _locate(a, b)
    art = C.resolve("dpm_artifact_dir", flag=a.artifact_dir, env="DPM_ARTIFACT_DIR", cfg=C.load(), cfg_path="dpm.artifact_dir", facts=C.project_facts(),
                    hint="set dpm_artifact_dir in AGENTS.md to the consumer's governed artifact directory (its contribution docs name it); "
                         "if it is undocumented, STOP and ask Michael")
    out_root = G.governed_dir(consumer, art, run.root)
    out_dir = os.path.join(out_root, CV.safe_name(run.run_id()))
    CV.refuse_if_present(out_dir, force=a.force)     # before hashing every source document, not after
    before = G.snapshot(run.root)
    res = V.validate(run, hash_sources=not a.no_hash)
    mid = G.snapshot(run.root)
    if mid["sha256"] != before["sha256"]:
        raise DpmError("run_root_changed", "the run root changed while it was being read; nothing was written",
                       "the run is not frozen: " + "; ".join(G.diff(before, mid)[:5]) + " — ask DPM to finish the run, then retry")
    counts = res.counts()
    if a.strict and counts["errors"]:
        raise DpmError("unresolved_references", f"{counts['errors']} reference error(s); --strict writes nothing",
                       "ad-dpm validate lists them; drop --strict to convert with those documents in the unresolved bucket")
    manifest = CV.build(run, res, consumer_root=consumer, artifact_dir=out_root, binding_label=label, binding_sha=bsha,
                        snapshot_sha=before["sha256"], snapshot_files=before["files"])
    run.close()
    receipt = {"receipt_version": 1, "generated_at": manifest["consumer"]["generated_at"], "generator": manifest["consumer"]["generator"],
               "command": " ".join(["ad-dpm"] + sys.argv[1:]), "run_id": res.run_id, "run_root": manifest["producer"]["run_root"],
               "orchestrator_db_sha256": manifest["producer"]["orchestrator_db_sha256"], "snapshot_before": before["sha256"],
               "binding": {"label": label, "sha256": bsha}, "counts": manifest["counts"], "hash_verified": not a.no_hash}
    files = CV.write(manifest, res.findings, out_dir, force=a.force, receipt=receipt)
    after = G.snapshot(run.root)
    untouched = before["sha256"] == after["sha256"]
    meta = {"ok": untouched, "source": "ad-dpm convert", "run_id": res.run_id, "run_root": manifest["producer"]["run_root"],
            "path": out_dir.replace("\\", "/"), "manifest": os.path.join(out_dir, "job-manifest.json").replace("\\", "/"), **manifest["counts"],
            "binding": label, "binding_sha256": _short(bsha), "run_root_untouched": untouched, "replaced": bool(a.force)}
    if not untouched:
        meta["changed"] = G.diff(before, after)[:20]
        meta["hint"] = "BUG: the run root changed during convert; do not hand this manifest over; friction-log it"
    elif counts["unresolved"] or counts["unsupported"]:
        meta["hint"] = (f"{counts['unresolved']} unresolved + {counts['unsupported']} unsupported document(s) are in excluded.tsv with reasons; "
                        "report unresolved ones to DPM; never patch the run root to make them resolve")
    meta["next"] = f"ad-dpm lineage --manifest {meta['manifest']}"
    body = {"meta": meta, "files": files,
            "excluded": [{"document_id": x["document_id"], "selection_id": x["selection_id"], "bucket": x["bucket"], "reasons": ";".join(x["reasons"])}
                         for x in manifest["excluded"][:SHOW]]}
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm convert", subtitle="ok" if untouched else "fail")
        if files:
            ui.table(["file", "path"], list(files.items()), title="files")
        if body["excluded"]:
            ui.table(["document_id", "selection_id", "bucket", "reasons"],
                     [[x["document_id"], x["selection_id"], x["bucket"], x["reasons"]] for x in body["excluded"]],
                     title="excluded documents", wrap=(3,))
    else:
        print(toon.encode(body))
    return 0 if untouched else 1


def cmd_lineage(a) -> int:
    m = CV.load_manifest(a.manifest)
    res = CV.verify(m, run_root=a.run_root, rehash=not a.no_hash)
    if a.job:
        hits = [j for j in m["jobs"] if j["job_id"] == a.job]
        if not hits:
            print(error(f"no job {a.job!r} in {a.manifest}", "job ids are <selection>:<document>:p<page>; see jobs.tsv", "ad-dpm lineage"))
            return 2
        j = hits[0]
        row = next(r for r in res["rows"] if r["job_id"] == a.job)
        if policy.pretty():
            ui.facts([("job_id", a.job), ("status", ui.status_text(row["status"])), ("route", j["route"]),
                      ("reason", row["reason"]), ("run_root", res["run_root"])], title=f"ad-dpm lineage {a.job}")
            if j.get("lineage"):
                ui.table(["step", "path"], list(j["lineage"].items()), title="lineage")
        else:
            print(toon.encode({"meta": {"ok": row["status"] == "ok", "source": "ad-dpm lineage", "job_id": a.job, "route": j["route"], "status": row["status"],
                                        "reason": row["reason"], "run_root": res["run_root"]}, "lineage": j["lineage"]}))
        return 0 if row["status"] == "ok" else 1
    meta = {"ok": res["ok"], "source": "ad-dpm lineage", "manifest": a.manifest.replace("\\", "/"), "run_root": res["run_root"],
            "run_id": m["producer"]["run_id"], "orchestrator_db_ok": res["orchestrator_db_ok"], "jobs": res["jobs"], "ok_count": res["ok_count"],
            "broken": res["broken"], "rehash": not a.no_hash}
    if not res["ok"]:
        meta["hint"] = "the producer side moved under this manifest; re-run ad-dpm convert --force after DPM confirms the run, do not hand-edit the manifest"
    broken_rows = [r for r in res["rows"] if r["status"] == "broken"][:SHOW]
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm lineage", subtitle="ok" if res["ok"] else "fail")
        if broken_rows:
            ui.table(["job_id", "status", "reason"],
                     [[r.get("job_id"), r.get("status"), r.get("reason")] for r in broken_rows],
                     title="broken references", status_col=1, wrap=(2,))
    else:
        print(toon.encode({"meta": meta, "broken": broken_rows}))
    return 0 if res["ok"] else 1


def cmd_binding(a) -> int:
    consumer = _consumer(a)
    if a.write:
        path = a.write if os.path.isabs(a.write) else os.path.join(consumer, a.write)
        if os.path.exists(path) and not a.force:
            raise DpmError("file_exists", f"{path} exists", "pass --force to overwrite it with the builtin binding")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(B.dump(B.builtin()))
        meta = {"ok": True, "source": "ad-dpm binding", "path": path.replace("\\", "/"), "sha256": _short(B.sha256(B.builtin())),
                "next": "edit only the names DPM uses differently, then set the dpm_binding fact in AGENTS.md to this file"}
        if policy.pretty():
            ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm binding")
        else:
            print(toon.encode({"meta": meta}))
        return 0
    b, label, bsha = _binding(a, consumer)
    if a.show:
        print(B.dump(b), end="")
        return 0
    meta = {"ok": True, "source": "ad-dpm binding", "binding": label, "sha256": bsha, "producer": b["producer"], "consumer": b["consumer"],
            "supported_orchestrator": b["versions"]["orchestrator"]["supported"],
            "supported_selection_manifest": b["versions"]["selection_manifest"]["supported"],
            "supported_text_analysis": b["versions"]["text_analysis"]["supported"]}
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")], title="ad-dpm binding")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def _run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--run-root", help="DPM run root (folder holding orchestrator.db and text_analysis/); default: dpm_run_root fact")
    p.add_argument("--runs-dir", help="folder of run roots; default: dpm_runs_dir fact")
    p.add_argument("--run-id", help="pick this run under --runs-dir (folder name or runs.run_id)")
    p.add_argument("--latest", action="store_true", help="pick the newest run under --runs-dir")
    p.add_argument("--binding", help="binding JSON (default: dpm_binding fact, else builtin)")
    p.add_argument("--consumer", help="consumer repo root (default: current directory)")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-dpm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("locate", help="find and validate a run root: markers, versions, binding")
    _run_args(p)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_locate)

    p = sub.add_parser("inspect", help="what the run root contains; which bound names resolve (never refuses)")
    _run_args(p)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("validate", help="resolve every reference (source, sha256, page, channel, loan, selection, text_analysis)")
    _run_args(p)
    p.add_argument("--no-hash", action="store_true", help="skip recomputing source sha256 (faster; hash_verified false)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("convert", help="write the consumer job manifest + lineage beneath the governed artifact dir")
    _run_args(p)
    p.add_argument("--artifact-dir", help="consumer governed artifact dir, relative to --consumer (default: dpm_artifact_dir fact)")
    p.add_argument("--no-hash", action="store_true")
    p.add_argument("--strict", action="store_true", help="write nothing when any reference fails to resolve")
    p.add_argument("--force", action="store_true", help="replace a previous handoff for the same run id")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("lineage", help="verify a job manifest's lineage still resolves against the run root")
    p.add_argument("--manifest", required=True, help="path to job-manifest.json")
    p.add_argument("--run-root", help="override the run root recorded in the manifest")
    p.add_argument("--job", help="print the full lineage chain of one job id")
    p.add_argument("--no-hash", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_lineage)

    p = sub.add_parser("binding", help="show the effective binding, or write the builtin one to edit")
    p.add_argument("--binding")
    p.add_argument("--consumer")
    p.add_argument("--show", action="store_true", help="print the effective binding as JSON")
    p.add_argument("--write", help="write the builtin binding to this path")
    p.add_argument("--force", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_binding)

    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.func(a)
    except DpmError as e:
        print(toon.encode({"meta": {"ok": False, "source": f"ad-dpm {a.cmd}", "refused": e.code, "error": e.msg, "hint": e.hint}}))
        return 2
    except C.ConfigError as e:
        print(error(str(e), getattr(e, "hint", ""), f"ad-dpm {a.cmd}"))
        return 2


if __name__ == "__main__":
    sys.exit(main())
