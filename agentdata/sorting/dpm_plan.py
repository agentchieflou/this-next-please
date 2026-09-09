"""Planning and applying RDSD-22488's structure. Same split as the generic filer: an agent plans, a person applies.

The plan is computed from the catalogue and the download folder together -- the catalogue says what a file *is*, the
folder says whether it is actually there. Neither alone is enough, and the difference between them is the most useful
thing this produces: a catalogue row with no file on disk is a retrieval that did not land, and a file on disk with no
catalogue row is a document nobody can classify. Both are named rather than dropped.
"""
from __future__ import annotations
import datetime as _dt
import hashlib
import os

from . import SortError
from . import catalog as C
from . import dpm_layout as D
from . import links as L
from . import plan as P
from .. import textio

CHUNK = 1 << 20

# One row per catalogue record. `file` is the only verdict `dpm-apply` acts on.
VERDICTS = ("file", "already_filed", "missing_from_disk", "collision", "unclassified")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(textio.longpath(path), "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def make(*, heap: str, root: str, ticket: str, catalogs: list, expected_loans: list | None = None) -> dict:
    """`catalogs` is a list of `catalog.read()` results -- one per source system."""
    if not os.path.isdir(heap):
        raise SortError("heap_missing", f"no such download folder: {textio.norm_path(heap)}",
                        "point --heap at the folder retrieval wrote the documents to")
    heap = os.path.abspath(heap)
    ticket_dir = D.ticket_root(root, ticket)
    if P.is_within(ticket_dir, heap) or P.is_within(heap, ticket_dir):
        raise SortError("destination_inside_heap",
                        f"the structure root {textio.norm_path(ticket_dir)} overlaps the download folder",
                        "the organised tree lives beside the downloads, not inside them")

    # Names only, and one listing: a corpus is large and `os.scandir` on a network share is the expensive part.
    on_disk = {}
    for name, is_dir, _is_link, size, _mtime in P._entries(heap):
        if not is_dir:
            on_disk[name.lower()] = (name, size)

    rows, claimed, seen_names = [], {}, set()
    skipped_by_loan = {}
    for source in catalogs:
        for record in source["rows"]:
            loan = record["loan_number"]
            name = record["file_name"]
            seen_names.add(name.lower())
            found = on_disk.get(name.lower())
            places = D.destinations(record)
            base = {"verdict": "", "loan_number": loan, "source": name, "destination": places["raw"],
                    "kind": "raw_docs", "why": "", "record": record, "views": places["views"],
                    "bytes": found[1] if found else 0}
            if not found:
                rows.append({**base, "verdict": "missing_from_disk",
                             "why": f"the {record['source_system']} catalogue lists it, but it is not in the folder"})
                continue
            already = skipped_by_loan.get(loan)
            if already is None:
                already = skipped_by_loan[loan] = D.already_filed(ticket_dir, loan)
            if places["raw"].rsplit("/", 1)[-1] in already:
                rows.append({**base, "verdict": "already_filed",
                             "why": "this loan's manifest already records it; retrieval is not repeated"})
                continue
            previous = claimed.get(places["raw"].lower())
            if previous:
                rows.append({**base, "verdict": "collision",
                             "why": f"{previous} is already filed to that path by this plan"})
                continue
            claimed[places["raw"].lower()] = name
            rows.append({**base, "verdict": "file"})

    # A file in the folder that no catalogue mentions cannot be classified, so it cannot be viewed -- and dropping it
    # from the listing is how a document goes missing without anybody noticing.
    for lowered, (name, size) in sorted(on_disk.items()):
        if lowered not in seen_names:
            rows.append({"verdict": "unclassified", "loan_number": "", "source": name, "destination": "",
                         "kind": "", "bytes": size, "record": None, "views": {},
                         "why": "no catalogue row names this file, so nothing knows its loan or its type"})

    catalogued = [r["record"] for r in rows if r["record"] is not None]
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    return {"ticket": ticket, "heap": textio.norm_path(heap), "root": textio.norm_path(ticket_dir),
            "sources": [{"source_system": s["source_system"], "rows": len(s["rows"]),
                         "unusable": len(s["unusable"]), "loan_field": s["loan_field"]} for s in catalogs],
            "unusable": [u for s in catalogs for u in s["unusable"]],
            "fingerprint": P.fingerprint(heap), "counts": counts,
            "administration": D.administration(catalogued, expected_loans), "rows": rows}


def review_md(plan: dict) -> str:
    counts = plan["counts"]
    lines = [f"# {plan['ticket']} — filing plan", "",
             f"* downloads: `{plan['heap']}`", f"* structure: `{plan['root']}`",
             f"* catalogues: " + ", ".join(f"{s['source_system']} ({s['rows']} rows, loan field `{s['loan_field']}`)"
                                           for s in plan["sources"]),
             "", "| verdict | count |", "| --- | --- |"]
    lines += [f"| {v} | {counts[v]} |" for v in VERDICTS]
    lines += ["", "Nothing has been filed. `ad-sort dpm-apply` is the command that does that, and it is a person's.",
              ""]
    for verdict in VERDICTS:
        chosen = [r for r in plan["rows"] if r["verdict"] == verdict]
        if not chosen:
            continue
        lines += [f"## {verdict} ({len(chosen)})", "", "| loan | file | destination | why |", "| --- | --- | --- | --- |"]
        lines += [f"| `{r['loan_number']}` | `{r['source']}` | `{r['destination']}` | {r['why']} |" for r in chosen]
        lines.append("")
    if plan["unusable"]:
        lines += [f"## Catalogue lines that could not be read ({len(plan['unusable'])})", ""]
        lines += [f"* line {u['line']}: {u['why']}" for u in plan["unusable"]] + [""]
    return "\n".join(lines)


def apply(plan: dict, *, rebuild_views: bool = False) -> dict:
    """File the evidence, then link the views. A person's command.

    Order matters: raw_docs first, and every view is made from the raw_doc rather than from the download folder, so a
    view is always a second name for the evidence and never for a staging file somebody may delete.
    """
    heap = plan["heap"]
    if not os.path.isdir(heap):
        raise SortError("heap_missing", f"the download folder this plan was made for is gone: {heap}",
                        "re-plan against the folder as it is now")
    now = P.fingerprint(heap)
    if now["sha256"] != (plan.get("fingerprint") or {}).get("sha256"):
        raise SortError("heap_changed",
                        f"the download folder has changed since this plan was written "
                        f"({(plan.get('fingerprint') or {}).get('files')} files then, {now['files']} now)",
                        "run `ad-sort dpm-plan` again and read the new plan")

    root = plan["root"]
    volume = L.probe(root)
    prefer = L.HARDLINK if volume["hardlinks"] else L.COPY
    stamp = _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    filed, views_made, failed, by_loan = 0, 0, [], {}
    for row in plan["rows"]:
        if row["verdict"] != "file":
            continue
        record = row["record"]
        source_path = os.path.join(heap, row["source"])
        raw_target = os.path.join(root, *row["destination"].split("/"))
        try:
            if os.path.exists(raw_target):
                mode = "already there"
            else:
                mode = L.place(source_path, raw_target, prefer=prefer)
            digest = _sha256(raw_target)
            for _folder, view_path in row["views"].items():
                target = os.path.join(root, *view_path.split("/"))
                if not os.path.exists(target):
                    L.place(raw_target, target, prefer=prefer)
                    views_made += 1
            by_loan.setdefault(record["loan_number"], []).append({
                **record, "raw_doc": row["destination"].rsplit("/", 1)[-1],
                "source_path": textio.norm_path(source_path), "sha256": digest,
                "bytes": os.path.getsize(raw_target), "link_mode": mode,
                "document_reference": D.reference(record), "filed_at": stamp})
            filed += 1
        except OSError as e:
            failed.append({"loan": row["loan_number"], "file": row["source"], "error": str(e)})

    manifests = []
    for loan, new_rows in sorted(by_loan.items()):
        path = os.path.join(root, textio.safe_name(loan), D.META, D.MANIFEST)
        existing = D.read_manifest(path)
        have = {r.get("raw_doc") for r in existing}
        merged = existing + [r for r in new_rows if r["raw_doc"] not in have]
        manifests.append(D.write_manifest(path, merged))

    return {"root": textio.norm_path(root), "filed": filed, "views": views_made, "failed": len(failed),
            "link_mode": prefer, "hardlinks_available": volume["hardlinks"], "volume": volume["evidence"],
            "manifests": manifests, "errors": failed}
