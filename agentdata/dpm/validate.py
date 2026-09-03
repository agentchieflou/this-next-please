"""Reference resolution. Every selection item is resolved against the canonical manifest, its source file (sha256 is
recomputed), the page range, the channel set and its text_analysis output. Every failure is an error Finding and moves
the document to the `unresolved` bucket; `unsupported` is a separate bucket (warning). Nothing here writes."""
from __future__ import annotations
import os
from dataclasses import dataclass, field

from .guard import file_sha256, is_within
from .run import HEX64, Run, Selection

HINTS = {
    "document-unknown": "the selection names a document the canonical manifest does not contain; report to DPM, never edit the run",
    "document-ambiguous": "several canonical documents share this sha256 and the item carries no document_id; ask DPM to disambiguate",
    "sha256-selection-mismatch": "the selection's sha256 differs from the canonical one; the selection is stale; report to DPM",
    "sha256-malformed": "sha256 must be 64 lowercase hex characters; report to DPM",
    "sha256-content-mismatch": "the file on disk hashes differently from the canonical sha256: the run root was altered or the manifest is stale; report to DPM",
    "loan-missing": "canonical row has no loan id; report to DPM",
    "loan-mismatch": "selection loan id differs from the canonical loan id; report to DPM",
    "channel-missing": "canonical row has no channel; report to DPM",
    "channel-unknown": "channel not in the allowed set (binding channels.allowed or the channels table); extend the set only with DPM sign-off",
    "source-missing": "source document path does not resolve to a file; report to DPM",
    "source-outside-root": "the source document lives outside the run root: it is not covered by the run's snapshot and may change under the handoff",
    "document-id-unsafe": "document id contains a path separator or '..' — it is used to name files; report to DPM",
    "page-count-missing": "no page count (canonical page_count, pages table or text_analysis pages); report to DPM",
    "page-invalid": "selection pages must be positive integers or omitted for all pages",
    "page-out-of-range": "selection page exceeds the document's page count; report to DPM",
    "page-not-in-canonical": "the pages table has no row for this page; report to DPM",
    "analysis-missing": "no text_analysis output for this document; DPM must re-run text analysis for it",
    "analysis-mismatch": "text_analysis output names another document/sha256; report to DPM",
    "analysis-page-missing": "text_analysis output has no entry for this selected page; report to DPM",
    "text-path-missing": "the page claims native text but names no text file; nothing can be reused; report to DPM",
    "text-missing": "the native text file named by text_analysis is absent or empty; report to DPM",
    "selection-run-mismatch": "the selection manifest belongs to another run id; use the matching run root",
    "selection-duplicate-id": "two manifests carry the same selection id; report to DPM",
    "selection-id-missing": "selection manifest has no selection id; report to DPM",
    "document-unsupported-status": "canonical status marks the document unsupported; it is excluded, not routed",
    "document-unsupported-analysis": "text_analysis marks the document unsupported; it is excluded, not routed",
    "document-unsupported-type": "a page needs OCR but the document type is not OCR-able (binding partition.ocr_mime/ocr_extensions); excluded",
    "canonical-duplicate-id": "the canonical manifest lists the same document id twice; report to DPM",
    "channels-unconstrained": "no allowed-channel list (binding channels.allowed) and no channels table: any non-empty channel is accepted",
    "selection-empty": "selection manifest has no items",
    "orchestrator-wal-pending": "orchestrator.db has an unapplied write-ahead log; ask DPM to checkpoint the run before handing it over",
}


@dataclass
class Finding:
    severity: str   # error | warning | info
    kind: str
    where: str
    object: str
    message: str
    hint: str = ""

    def row(self) -> list:
        return [self.severity, self.kind, self.where, self.object, self.message, self.hint]

    def record(self) -> dict:
        return {"severity": self.severity, "kind": self.kind, "where": self.where, "object": self.object, "message": self.message, "hint": self.hint}


@dataclass
class Doc:
    """One selection item, resolved (or not) against the run."""
    selection_id: str | None
    manifest: str
    item_index: int
    document_id: str | None
    sha256: str | None
    loan_id: str | None
    channel: str | None = None
    source_path: str | None = None
    source_rel: str | None = None
    page_count: int | None = None
    mime: str | None = None
    status: str | None = None
    canonical_rowid: int | None = None
    pages: list[int] = field(default_factory=list)
    analysis_rel: str | None = None
    page_info: dict = field(default_factory=dict)     # page -> {has_native_text, char_count, text_quality, text_path, text_rel}
    unresolved: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    hash_verified: bool = False

    @property
    def bucket(self) -> str:
        return "unresolved" if self.unresolved else "unsupported" if self.unsupported else "resolved"

    @property
    def where(self) -> str:
        return f"{self.manifest}#{self.item_index}"

    @property
    def label(self) -> str:
        return self.document_id or self.sha256 or "?"


@dataclass
class Result:
    findings: list[Finding]
    docs: list[Doc]
    selections: list[Selection]
    channels_source: str
    run_id: str
    partition: dict          # binding thresholds; counts() needs them, so it is never optional

    def counts(self) -> dict:
        native = sum(1 for d in self.docs if d.bucket == "resolved" for p in d.pages if native_reusable(d.page_info.get(p, {}), self.partition))
        pages = sum(len(d.pages) for d in self.docs if d.bucket == "resolved")
        return {"selections": len(self.selections), "documents": len(self.docs), "pages_selected": sum(len(d.pages) for d in self.docs),
                "resolved": sum(1 for d in self.docs if d.bucket == "resolved"),
                "unresolved": sum(1 for d in self.docs if d.bucket == "unresolved"),
                "unsupported": sum(1 for d in self.docs if d.bucket == "unsupported"),
                "native_text": native, "ocr": pages - native,
                "errors": sum(1 for f in self.findings if f.severity == "error"),
                "warnings": sum(1 for f in self.findings if f.severity == "warning")}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def native_reusable(entry: dict, part: dict) -> bool:
    """Contract rule: native text is reusable when the page has it, it is long enough, good enough and the file exists."""
    if not entry or not entry.get("has_native_text"):
        return False
    chars = _num(entry.get("char_count"))
    if chars is None or chars < float(part.get("native_min_chars", 0)):
        return False
    quality = entry.get("text_quality")
    if quality is not None:
        qn = _num(quality)
        if qn is None or qn < float(part.get("native_min_quality", 0)):
            return False
    return bool(entry.get("text_rel"))


def ocr_able(doc: Doc, part: dict) -> bool:
    mime = (doc.mime or "").lower().split(";")[0].strip()
    if mime:
        return mime in {m.lower() for m in part.get("ocr_mime", [])}
    ext = os.path.splitext(doc.source_path or "")[1].lower()
    return ext in {e.lower() for e in part.get("ocr_extensions", [])}


def unsafe_id(value: str) -> bool:
    """Ids reach the filesystem (text_analysis/<document_id>.json), so a separator or `..` is never acceptable."""
    return "/" in value or "\\" in value or ".." in value.split("/") or value.strip() in ("", ".")


def _as_page(v) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 and n == float(v) else None


def validate(run: Run, *, hash_sources: bool = True) -> Result:
    b = run.b
    part = b["partition"]
    findings: list[Finding] = []

    def err(kind: str, where: str, obj: str, message: str, severity: str = "error") -> None:
        findings.append(Finding(severity, kind, where, obj, message, HINTS.get(kind, "")))

    if run.wal_pending():
        err("orchestrator-wal-pending", run.rel(run.db_path), "", "write-ahead log present; immutable read may be stale", "warning")
    by_id: dict[str, dict] = {}
    by_sha: dict[str, list[dict]] = {}
    for r in run.canonical_documents():
        did = None if r.get("document_id") is None else str(r["document_id"])
        sha = (str(r.get("sha256") or "")).strip().lower() or None
        if did is not None:
            if did in by_id:
                err("canonical-duplicate-id", b["canonical"]["table"], did, f"document id {did} appears more than once")
            by_id[did] = r
        if sha:
            by_sha.setdefault(sha, []).append(r)
    allowed, ch_source = run.allowed_channels()
    if allowed is None:
        err("channels-unconstrained", "binding", "channels", "no allowed-channel set", "warning")
    pages_tbl = run.pages_by_document()
    run_id = run.run_id()
    selections = run.selections()
    seen: dict[str, str] = {}
    docs: list[Doc] = []
    hashes: dict[str, str] = {}
    for s in selections:
        bad_manifest: list[str] = []
        if s.selection_id is None:
            err("selection-id-missing", s.path, "", "no selection id")
            bad_manifest.append("selection-id-missing")
        elif s.selection_id in seen:
            err("selection-duplicate-id", s.path, s.selection_id, f"selection id also in {seen[s.selection_id]}")
            bad_manifest.append("selection-duplicate-id")
        else:
            seen[s.selection_id] = s.path
        if s.run_id and s.run_id != run_id:
            err("selection-run-mismatch", s.path, s.selection_id or "", f"manifest run id {s.run_id!r} != run {run_id!r}")
            bad_manifest.append("selection-run-mismatch")
        if not s.items:
            err("selection-empty", s.path, s.selection_id or "", "no items", "warning")
        for i, item in enumerate(s.items):
            if not isinstance(item, dict):
                d = Doc(s.selection_id, s.path, i, None, None, None)
                d.unresolved.append("document-unknown")
                err("document-unknown", d.where, "?", "item is not an object")
                docs.append(d)
                continue
            d = _resolve(run, s, i, item, by_id, by_sha, allowed, pages_tbl, hashes, hash_sources, err)
            d.unresolved = bad_manifest + d.unresolved
            docs.append(d)
    return Result(findings, docs, selections, ch_source, run_id, part)


def _resolve(run: Run, s: Selection, i: int, item: dict, by_id, by_sha, allowed, pages_tbl, hashes, hash_sources, err) -> Doc:
    b = run.b
    k = b["selection"]["keys"]
    part = b["partition"]
    did = item.get(k["document_id"])
    did = None if did is None else str(did)
    isha = (str(item.get(k["sha256"]) or "")).strip().lower() or None
    iloan = item.get(k["loan_id"])
    d = Doc(s.selection_id, s.path, i, did, isha, None if iloan is None else str(iloan))

    def fail(kind: str, message: str) -> None:
        d.unresolved.append(kind)
        err(kind, d.where, d.label, message)

    def unsupported(kind: str, message: str) -> None:
        d.unsupported.append(kind)
        err(kind, d.where, d.label, message, "warning")

    if did is not None and unsafe_id(did):
        d.unresolved.append("document-id-unsafe")
        err("document-id-unsafe", d.where, d.label, f"document id {did!r} cannot name a file")
        return d
    row = by_id.get(did) if did is not None else None
    if row is None and isha:
        cands = by_sha.get(isha, [])
        if len(cands) == 1:
            row = cands[0]
        elif len(cands) > 1:
            fail("document-ambiguous", f"{len(cands)} canonical documents share sha256 {isha[:12]}…")
            return d
    if row is None:
        fail("document-unknown", f"document {d.label} is not in the canonical manifest")
        return d
    d.document_id = None if row.get("document_id") is None else str(row["document_id"])
    if d.document_id and unsafe_id(d.document_id):      # it is interpolated into the text_analysis file name
        d.unresolved.append("document-id-unsafe")
        err("document-id-unsafe", d.where, d.label, f"document id {d.document_id!r} cannot name a file")
        return d
    d.canonical_rowid = row.get("_rowid")
    csha = (str(row.get("sha256") or "")).strip().lower() or None
    if isha and csha and isha != csha:
        fail("sha256-selection-mismatch", f"selection sha256 {isha[:12]}… != canonical {csha[:12]}…")
    d.sha256 = csha or isha
    if not d.sha256 or not HEX64.match(d.sha256):
        fail("sha256-malformed", f"sha256 {d.sha256!r}")
    cloan = row.get("loan_id")
    d.loan_id = None if cloan is None else str(cloan)
    if not d.loan_id:
        fail("loan-missing", "no loan id")
    elif iloan is not None and str(iloan) != d.loan_id:
        fail("loan-mismatch", f"selection loan {iloan!r} != canonical {d.loan_id!r}")
    ch = row.get("channel")
    d.channel = None if ch is None else str(ch)
    if not d.channel:
        fail("channel-missing", "no channel")
    elif allowed is not None and d.channel not in allowed:
        fail("channel-unknown", f"channel {d.channel!r} not in {sorted(allowed)}")
    d.mime = None if row.get("mime_type") is None else str(row["mime_type"])
    d.status = None if row.get("status") is None else str(row["status"])
    sp = row.get("source_path")
    d.source_path = None if sp is None else str(sp)
    if not d.source_path:
        fail("source-missing", "no source path")
    else:
        abs_path = run.resolve(d.source_path)
        d.source_rel = run.rel(abs_path)
        if not is_within(abs_path, run.root):
            err("source-outside-root", d.where, d.label, f"{d.source_rel} is outside the run root", "warning")
        if not os.path.isfile(abs_path):
            fail("source-missing", f"{d.source_rel} not found")
        elif hash_sources and d.sha256 and HEX64.match(d.sha256):
            actual = hashes.get(abs_path) or hashes.setdefault(abs_path, file_sha256(abs_path))
            if actual != d.sha256:
                fail("sha256-content-mismatch", f"{d.source_rel} hashes to {actual[:12]}…, canonical {d.sha256[:12]}…")
            else:
                d.hash_verified = True
    # page count: canonical -> pages table -> text_analysis
    pc = row.get("page_count")
    try:
        pc = int(pc) if pc is not None else None
    except (TypeError, ValueError):
        pc = None
    if pc is None and pages_tbl is not None and d.document_id in pages_tbl:
        pc = len(pages_tbl[d.document_id])
    ana = run.analysis(d.document_id, d.sha256)
    ak = b["text_analysis"]["keys"]
    ana_pages: dict[int, dict] = {}
    if ana is None:
        fail("analysis-missing", f"{run.analysis_rel(d.document_id, d.sha256)} not found")
    else:
        d.analysis_rel = run.analysis_rel(d.document_id, d.sha256)
        a_id, a_sha = ana.get(ak["document_id"]), (str(ana.get(ak["sha256"]) or "")).strip().lower() or None
        if (a_id is not None and str(a_id) != d.document_id) or (a_sha and d.sha256 and a_sha != d.sha256):
            fail("analysis-mismatch", f"{d.analysis_rel} names document {a_id!r} / sha256 {(a_sha or '')[:12]}…")
        if ana.get(ak["unsupported"]):
            unsupported("document-unsupported-analysis", f"text_analysis flags the document unsupported: {ana.get(ak['unsupported'])!r}")
        for entry in ana.get(ak["pages"]) or []:
            if isinstance(entry, dict):
                p = _as_page(entry.get(ak["page"]))
                if p is not None:
                    ana_pages[p] = {"has_native_text": bool(entry.get(ak["has_native_text"])), "char_count": entry.get(ak["char_count"]),
                                    "text_quality": entry.get(ak["text_quality"]), "text_path": entry.get(ak["text_path"]), "text_rel": None}
        if pc is None and ana_pages:
            pc = max(ana_pages)
    d.page_count = pc
    if pc is None or pc <= 0:
        fail("page-count-missing", "no page count")
    raw = item.get(k["pages"])
    if raw in (None, "", "all", "*", []):
        d.pages = list(range(1, (pc or 0) + 1))
    else:
        got: list[int] = []
        for v in (raw if isinstance(raw, list) else [raw]):
            p = _as_page(v)
            if p is None:
                fail("page-invalid", f"page {v!r}")
            elif p not in got:
                got.append(p)
        d.pages = sorted(got)
    if d.status and d.status.strip().lower() in {x.lower() for x in b["canonical"].get("unsupported_statuses", [])}:
        unsupported("document-unsupported-status", f"canonical status {d.status!r}")
    needs_ocr = False
    for p in d.pages:
        if pc is not None and p > pc:
            fail("page-out-of-range", f"page {p} > page_count {pc}")
            continue
        if pages_tbl is not None and d.document_id in pages_tbl and p not in pages_tbl[d.document_id]:
            fail("page-not-in-canonical", f"page {p} has no row in the pages table")
        if ana is None:
            continue
        entry = ana_pages.get(p)
        if entry is None:
            fail("analysis-page-missing", f"page {p} has no text_analysis entry")
            continue
        if entry["has_native_text"]:
            tp = entry.get("text_path")
            if not tp:
                fail("text-path-missing", f"page {p} has native text but no text file")
            else:
                tabs = run.resolve(tp)
                if not os.path.isfile(tabs) or os.path.getsize(tabs) == 0:
                    fail("text-missing", f"page {p}: {run.rel(tabs)} absent or empty")
                else:
                    entry["text_rel"] = run.rel(tabs)
        d.page_info[p] = entry
        if not native_reusable(entry, part):
            needs_ocr = True
    if needs_ocr and not d.unresolved and not ocr_able(d, part):
        unsupported("document-unsupported-type", f"needs OCR but type {d.mime or os.path.splitext(d.source_path or '')[1] or '?'} is not OCR-able")
    return d
