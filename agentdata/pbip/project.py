"""Projection writer: normalized.json + TSVs + targeted Markdown under .agent/pbip/<name>/. Deterministic output,
skipped when the source hashes in meta.json are unchanged. Never writes into the PBIP."""
from __future__ import annotations
import csv
import hashlib
import json
import os
from typing import Any

from ..textio import read_text
from .normalize import Model, source_files
from . import pbir as P


def _sha(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def hashes(model: Model, report: P.Report | None) -> dict[str, str]:
    return {p.replace("\\", "/"): _sha(p) for p in source_files(model, report)}


def _tsv(path: str, cols: list[str], rows: list[list[Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else (json.dumps(v) if isinstance(v, (list, dict)) else v) for v in r])


def write_projection(norm: dict, model: Model, report: P.Report | None, out_dir: str, force: bool = False) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    meta_path = os.path.join(out_dir, "meta.json")
    new_hashes = hashes(model, report)
    if not force and os.path.exists(meta_path):
        try:
            old = json.loads(read_text(meta_path))
            if old.get("sources") == new_hashes:
                return {"skipped": True, "out_dir": out_dir.replace("\\", "/"), "files": sorted(os.listdir(out_dir))}
        except (ValueError, OSError):
            pass
    m = norm["model"]
    with open(os.path.join(out_dir, "normalized.json"), "w", encoding="utf-8") as f:
        json.dump(norm, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    _tsv(os.path.join(out_dir, "tables.tsv"), ["table", "hidden", "columns", "measures", "hierarchies", "partitions", "connector", "sources", "file"],
         [[t["name"], t["hidden"], len(t["columns"]), len(t["measures"]), len(t["hierarchies"]), len(t["partitions"]),
           ";".join(sorted({p["connector"] for p in t["partitions"] if p["connector"]})), ";".join(norm["lineage"]["sources"].get(t["name"], [])), t["file"]] for t in m["tables"]])
    _tsv(os.path.join(out_dir, "columns.tsv"), ["table", "column", "kind", "dataType", "hidden", "summarizeBy", "formatString", "sortByColumn", "sourceColumn", "used_in_report", "file", "line"],
         [[t["name"], c["name"], c["kind"], c["dataType"], c["hidden"], c["summarizeBy"], c["formatString"], c["sortByColumn"], c["sourceColumn"],
           len(norm["lineage"]["field_usage"].get(f"'{t['name']}'[{c['name']}]", [])), t["file"], c["line"]] for t in m["tables"] for c in t["columns"]])
    _tsv(os.path.join(out_dir, "measures.tsv"), ["table", "measure", "formatString", "displayFolder", "hidden", "dep_columns", "dep_measures", "used_in_report", "expression", "file", "line"],
         [[t["name"], x["name"], x["formatString"], x["displayFolder"], x["hidden"], ";".join(x["deps"]["columns"]), ";".join(x["deps"]["measures"]),
           len(norm["lineage"]["field_usage"].get(f"'{t['name']}'[{x['name']}]", [])), x["expression"].replace("\n", " ").strip(), t["file"], x["line"]]
          for t in m["tables"] for x in t["measures"]])
    _tsv(os.path.join(out_dir, "relationships.tsv"), ["name", "fromTable", "fromColumn", "toTable", "toColumn", "active", "crossFilter"],
         [[r["name"], r["fromTable"], r["fromColumn"], r["toTable"], r["toColumn"], r["active"], r["crossFilter"]] for r in m["relationships"]])
    files = ["normalized.json", "tables.tsv", "columns.tsv", "measures.tsv", "relationships.tsv", "MODEL.md", "meta.json"]
    rep = norm.get("report")
    if rep:
        _tsv(os.path.join(out_dir, "visuals.tsv"), ["page", "visual", "type", "title", "hidden", "fields", "filters", "file"],
             [[p["name"], v["id"], v["type"], v["title"], v["hidden"], len(v["fields"]), len(v["filters"]), v["file"]] for p in rep["pages"] for v in p["visuals"]])
        _tsv(os.path.join(out_dir, "visual_fields.tsv"), ["page", "visual", "context", "kind", "entity", "prop", "hierarchy", "agg"],
             [[p["name"], v["id"], f["context"], f["kind"], f["entity"], f["prop"], f["hierarchy"], f["agg"]] for p in rep["pages"] for v in p["visuals"] for f in v["fields"]])
        frows = [["report", "", f["name"], f["type"], f["field"]] for f in rep["filters"]]
        for p in rep["pages"]:
            frows += [[p["name"], "", f["name"], f["type"], f["field"]] for f in p["filters"]]
            for v in p["visuals"]:
                frows += [[p["name"], v["id"], f["name"], f["type"], f["field"]] for f in v["filters"]]
        _tsv(os.path.join(out_dir, "filters.tsv"), ["page", "visual", "name", "type", "field"], frows)
        files += ["visuals.tsv", "visual_fields.tsv", "filters.tsv", "REPORT.md", "LINEAGE.md"]
        with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(report_md(norm))
        with open(os.path.join(out_dir, "LINEAGE.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(lineage_md(norm))
    with open(os.path.join(out_dir, "MODEL.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(model_md(norm))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": norm["generated_at"], "pbip": norm["pbip"], "sources": new_hashes,
                   "counts": {"tables": len(m["tables"]), "columns": sum(len(t["columns"]) for t in m["tables"]),
                              "measures": sum(len(t["measures"]) for t in m["tables"]), "relationships": len(m["relationships"]),
                              "pages": len(rep["pages"]) if rep else 0, "visuals": sum(len(p["visuals"]) for p in rep["pages"]) if rep else 0}}, f, indent=1, sort_keys=True)
        f.write("\n")
    return {"skipped": False, "out_dir": out_dir.replace("\\", "/"), "files": sorted(files)}


def model_md(norm: dict) -> str:
    m = norm["model"]
    out = [f"# Model {m.get('name') or ''}".rstrip(), "", f"{len(m['tables'])} tables · {sum(len(t['measures']) for t in m['tables'])} measures · "
           f"{len(m['relationships'])} relationships · compatibility {m.get('compatibility') or '?'}", ""]
    out += ["## Relationships", ""] + [f"- {r['fromTable']}[{r['fromColumn']}] → {r['toTable']}[{r['toColumn']}]"
                                       f"{'' if r['active'] else ' (inactive)'}{' · ' + r['crossFilter'] if r['crossFilter'] != 'oneDirection' else ''}" for r in m["relationships"]] + [""]
    for t in m["tables"]:
        out.append(f"## {t['name']}{' (hidden)' if t['hidden'] else ''} — `{t['file']}`")
        if t.get("description"):
            out.append(f"_{t['description']}_")
        src = norm["lineage"]["sources"].get(t["name"]) or []
        conn = {p["connector"] for p in t["partitions"] if p["connector"]}
        parts = ", ".join("%s (%s)" % (p["name"], p["kind"] or p["mode"]) for p in t["partitions"]) or "none"
        out.append("Partitions: " + parts + (" · connector " + ", ".join(sorted(conn)) if conn else "") + (" · sources " + ", ".join(src) if src else ""))
        if t["measures"]:
            out += ["", "| measure | format | folder | depends on |", "|---|---|---|---|"]
            for x in t["measures"]:
                deps = ", ".join(x["deps"]["columns"] + [f"[{d}]" for d in x["deps"]["measures"]])
                out.append(f"| {x['name']}{' (hidden)' if x['hidden'] else ''} | {x['formatString'] or ''} | {x['displayFolder'] or ''} | {deps} |")
        if t["columns"]:
            out += ["", "| column | type | kind | summarize | notes |", "|---|---|---|---|---|"]
            for c in t["columns"]:
                notes = []
                if c["hidden"]:
                    notes.append("hidden")
                if c["sortByColumn"]:
                    notes.append(f"sort by {c['sortByColumn']}")
                if c["formatString"]:
                    notes.append(f"format {c['formatString']}")
                out.append(f"| {c['name']} | {c['dataType'] or ''} | {c['kind']} | {c['summarizeBy'] or ''} | {'; '.join(notes)} |")
        for h in t["hierarchies"]:
            out.append(f"\nHierarchy **{h['name']}**: " + " › ".join(f"{lv['name']} ({lv['column']})" for lv in h["levels"]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def report_md(norm: dict) -> str:
    rep = norm["report"]
    out = ["# Report", "", f"{len(rep['pages'])} pages · {sum(len(p['visuals']) for p in rep['pages'])} visuals · "
           f"{'legacy report.json' if rep['legacy'] else 'PBIR ' + str(rep.get('version') or '')} · model `{rep.get('dataset_path') or rep.get('dataset_connection') or '?'}`", ""]
    if rep["filters"]:
        out += ["Report filters: " + ", ".join(f"{f['field']} ({f['type']})" for f in rep["filters"]), ""]
    for p in rep["pages"]:
        out.append(f"## {p['name']} (`{p['id']}`){' hidden' if p['hidden'] else ''}")
        if p["filters"]:
            out.append("Page filters: " + ", ".join(f"{f['field']} ({f['type']})" for f in p["filters"]))
        out += ["", "| visual | type | title | fields | filters |", "|---|---|---|---|---|"]
        for v in p["visuals"]:
            fields = "; ".join(f"{f['context'].replace('projection:', '')}: {f['label']}" for f in v["fields"] if f["entity"])
            flt = "; ".join(f["field"] or "" for f in v["filters"])
            out.append(f"| `{v['id']}`{' hidden' if v['hidden'] else ''} | {v['type'] or ''} | {v['title'] or ''} | {fields} | {flt} |")
        out.append("")
    if rep["extension_measures"]:
        out += ["## Report-level measures", ""] + [f"- '{m['entity']}'[{m['name']}] = `{(m['expression'] or '').strip()[:120]}`" for m in rep["extension_measures"]] + [""]
    if rep["bookmarks"]:
        out += ["## Bookmarks", ""] + [f"- {b.get('displayName') or b.get('name')} → pages {', '.join(b['pages'])}; visuals {', '.join(b['visuals'])}" for b in rep["bookmarks"]] + [""]
    return "\n".join(out).rstrip() + "\n"


def lineage_md(norm: dict) -> str:
    lin = norm["lineage"]
    out = ["# Lineage", "", "## Report field → visuals", ""]
    for label, uses in lin["field_usage"].items():
        out.append(f"- {label}: " + "; ".join(f"{u['page']}/{u['visual']}{' (' + u['title'] + ')' if u['title'] else ''} [{u['context']}]" for u in uses))
    out += ["", "## Column / measure → measures that use it", ""]
    for label, users in lin["measure_usage"].items():
        out.append(f"- {label}: " + ", ".join(users))
    out += ["", "## Table → source objects (from partition M)", ""]
    for t, src in lin["sources"].items():
        out.append(f"- {t}: {', '.join(src) or '(not detected)'}")
    return "\n".join(out).rstrip() + "\n"
