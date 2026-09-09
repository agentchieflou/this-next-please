r"""RDSD-22488's structure: canonical evidence under the loan, disposable views beside it.

    <root>\<dpm_ticket>\
      <loan_number>\
        raw_docs\<original filename>              the downloaded file, canonical
        metadata\document_manifest.csv            every row's lineage back to that download
      views\
        doc_type\<doc_subtype>\<loan>\<reference>         hardlinks
        file_description\<file_desc>\<loan>\<reference>   hardlinks

The two halves are not the same kind of thing and the code keeps them apart on purpose. `raw_docs` is evidence: it is
written once, its manifest records where each file came from, and re-running never rewrites it. `views/` is a
navigation aid: it can be deleted entirely and rebuilt from the manifest without touching a document or repeating a
retrieval, which is requirement 4 of the ticket and the reason hardlinks are worth the trouble.

What this does *not* do is convert anything. `IsTiff` documents are filed as they are and listed as a conversion queue
with their loan and count, because turning a TIFF into a PDF needs an imaging dependency this package does not have and
a correctness story of its own (page order, colour, DPI, what happens to the original). Filing something and calling it
converted would be worse than saying it is queued.
"""
from __future__ import annotations
import csv
import io
import os

from . import SortError
from . import links as L
from .. import textio

RAW = "raw_docs"
META = "metadata"
VIEWS = "views"
MANIFEST = "document_manifest.csv"

# The views the ticket names. Adding one is a row here plus its column in the manifest -- nothing else.
VIEW_AXES = (("doc_type", "doc_subtype"), ("file_description", "file_desc"))

# The manifest is the traceability record, so its first columns are the lineage: where this file is now, and exactly
# which downloaded file it is. Everything after that is the catalogue's own fields, unchanged.
MANIFEST_COLS = ("loan_number", "raw_doc", "source_path", "source_system", "sha256", "bytes", "link_mode",
                 "document_reference", "doc_subtype", "file_desc", "business_area", "repo_doc_name",
                 "repo_stored_at", "total_pages", "can_view", "is_tiff", "filed_at")

PLAN_COLS = ("verdict", "loan_number", "source", "destination", "kind", "why")


def _safe(part: str, fallback: str) -> str:
    """One path segment from a metadata value. A blank subtype is a real state and gets a named folder, not a blank."""
    cleaned = textio.safe_name((part or "").strip()) or fallback
    return cleaned.strip() or fallback


def ticket_root(root: str, ticket: str) -> str:
    if not ticket or not ticket.strip():
        raise SortError("no_ticket", "the structure's first level is the DPM ticket and none was given",
                        "pass --ticket RDSD-22488")
    return os.path.join(os.path.abspath(os.path.expanduser(root)), textio.safe_name(ticket.strip()))


def reference(row: dict) -> str:
    """The leaf name a view uses: the repository's own reference, keeping the document's extension.

    `RepositoryDocName` is the reference the ticket names, and the filename is the fallback. The extension is carried
    over when the reference has none, because a view exists to be *browsed*: a file called `REPO-0001` does not open on
    a double-click and Windows has nothing to go on. Which name was used is recorded in the manifest rather than left
    to be inferred from the shape of the string.
    """
    name = row.get("file_name") or ""
    base = _safe(row.get("repo_doc_name") or "", _safe(name, "document"))
    extension = os.path.splitext(name)[1]
    return base + extension if extension and not os.path.splitext(base)[1] else base


def destinations(row: dict) -> dict:
    """Where one catalogue row goes: its raw_docs path, and one view path per axis. All relative to the ticket root."""
    loan = _safe(row.get("loan_number") or "", "unknown-loan")
    name = _safe(row.get("file_name") or "", "document")
    out = {"raw": f"{loan}/{RAW}/{name}", "views": {}}
    ref = reference(row)
    for folder, field in VIEW_AXES:
        bucket = _safe(row.get(field) or "", f"unspecified-{folder}")
        out["views"][folder] = f"{VIEWS}/{folder}/{bucket}/{loan}/{ref}"
    return out


def read_manifest(path: str) -> list[dict]:
    """A loan's existing manifest, or []. This is what makes a second run skip what the first one filed."""
    if not os.path.isfile(path):
        return []
    with io.StringIO(textio.read_text(path)) as handle:
        return [dict(r) for r in csv.DictReader(handle)]


def write_manifest(path: str, rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(MANIFEST_COLS), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in MANIFEST_COLS})
    return textio.write_text(path, buffer.getvalue())


def already_filed(ticket_dir: str, loan: str) -> set:
    """The raw_doc names this loan's manifest already records, so retrieval is never repeated."""
    manifest = os.path.join(ticket_dir, _safe(loan, "unknown-loan"), META, MANIFEST)
    return {r.get("raw_doc", "") for r in read_manifest(manifest) if r.get("raw_doc")}


def administration(rows: list[dict], expected_loans: list | None) -> dict:
    """The three counts somebody has to report, and the one that needs an input to be answerable at all."""
    present = {}
    for row in rows:
        loan = row.get("loan_number") or ""
        cell = present.setdefault(loan, {"documents": 0, "not_viewable": 0, "tiff": 0})
        cell["documents"] += 1
        if row.get("can_view") is False:
            cell["not_viewable"] += 1
        if row.get("is_tiff") is True:
            cell["tiff"] += 1

    # A catalogue only knows the loans that produced something. Which loans produced *nothing* is only answerable
    # against the population somebody expected, so without that list this reports that it cannot say.
    if expected_loans is None:
        empty, known = [], False
    else:
        empty, known = [loan for loan in expected_loans if loan not in present], True
    return {"per_loan": present, "loans_with_no_documents": empty, "population_known": known,
            "loans": len(present), "documents": sum(c["documents"] for c in present.values()),
            "not_viewable": sum(c["not_viewable"] for c in present.values()),
            "tiff_to_convert": sum(c["tiff"] for c in present.values())}


def admin_md(ticket: str, admin: dict, rows: list[dict]) -> str:
    """The administrative report: what came back, what could not be viewed, what is waiting on conversion."""
    lines = [f"# {ticket} — document retrieval, administratively", "",
             f"* loans with at least one document: **{admin['loans']}**",
             f"* documents: **{admin['documents']}**",
             f"* could not be viewed (`IsCanView` false): **{admin['not_viewable']}**",
             f"* TIFF awaiting conversion to PDF: **{admin['tiff_to_convert']}**", ""]
    if admin["population_known"]:
        empty = admin["loans_with_no_documents"]
        lines += [f"## Loans with no documents ({len(empty)})", ""]
        lines += ([f"* `{loan}`" for loan in empty] or ["Every loan in the population returned at least one document."])
    else:
        lines += ["## Loans with no documents", "",
                  "**Not answerable from the catalogue alone.** A catalogue only records loans that produced a "
                  "document, so a loan that returned nothing is absent rather than zero. Pass the expected loan "
                  "population with `--loans <file>` and this section fills in."]
    lines += ["", "## Per loan", "", "| loan | documents | not viewable | TIFF |", "| --- | --- | --- | --- |"]
    for loan in sorted(admin["per_loan"]):
        cell = admin["per_loan"][loan]
        lines.append(f"| `{loan}` | {cell['documents']} | {cell['not_viewable']} | {cell['tiff']} |")

    queued = [r for r in rows if r.get("is_tiff") is True]
    if queued:
        lines += ["", f"## TIFF conversion queue ({len(queued)})", "",
                  "Filed as they are. **Nothing here has been converted** — that needs an imaging dependency this "
                  "package does not carry, and a filing tool that claimed to convert would be the worst of both.", "",
                  "| loan | file | pages |", "| --- | --- | --- |"]
        lines += [f"| `{r['loan_number']}` | `{r['file_name']}` | {r.get('total_pages', '')} |" for r in queued]
    return "\n".join(lines) + "\n"
