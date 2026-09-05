"""Named field values out of the text DPM already located — with the field list supplied per job.

`convert.py` stops at routing: it says which documents are readable and how (`native_text` or
`ocr`), with full lineage. What it does not do is say *what is in them*, and the obvious next step
is the one that goes wrong: hard-coding a list of business fields. "Borrower name", "loan amount"
— right for one job, wrong for the next, and unmaintainable in a month.

So the field list is an **input**, the way `ad-uat expect` treats an expected-values document as a
claim to test rather than a schema to assume. Nothing in this module names a business field.

Three invariants it inherits rather than reinvents:

* **The run root is never written.** Fingerprinted before and after, like every other `ad-dpm`
  command, and the check is the same `guard.snapshot`/`diff` pair.
* **Lineage is DPM's**, copied from the manifest job that produced the text. A parallel provenance
  mechanism would be a second answer to "where did this come from", and the whole contract exists
  so there is one.
* **An `ocr` route is not extracted from.** Its text quality is unverified, and a value pulled out
  of bad OCR looks exactly like a value pulled out of good text. It is bucketed, the way
  `convert.py` buckets `unsupported` and `unresolved` rather than forcing them through.
"""
from __future__ import annotations
import json
import os
import re

from .. import textio
from . import DpmError
from .guard import diff, snapshot

def safe(name: str) -> str:
    """A run id as a filename. `convert.py` has the same need and the same answer."""
    return textio.safe_name(str(name).replace("/", "-").replace("\\", "-")) or "dpm"


SCHEMA_VERSION = "1"
RESULT_VERSION = "1"

# One row per (document, field). `needs_ocr_review` is a *status*, not a failure: the document may
# well contain the field, and nobody here can say so honestly.
STATUSES = ("found", "not_found", "ambiguous", "needs_ocr_review", "no_text")

RESULT_COLS = ["job_id", "field", "status", "value", "page", "document_id", "sha256", "engine",
               "hint", "text_path"]

# How much of the line after a hint counts as the value. Long enough for an address, short enough
# that a runaway match is obviously wrong when a person reads it.
VALUE_CHARS = 120


class FieldSchema:
    """What to look for, supplied per job. Nothing here is built in."""

    def __init__(self, fields: list[dict], version: str = SCHEMA_VERSION):
        self.fields = fields
        self.version = version

    @property
    def names(self) -> list[str]:
        return [f["name"] for f in self.fields]

    def required(self) -> list[str]:
        return [f["name"] for f in self.fields if f.get("required")]


def load_schema(path: str) -> FieldSchema:
    """Read and check a field schema. Refuses rather than guesses: a schema with a typo produces
    silently empty results, which read exactly like "the documents do not contain this"."""
    try:
        raw = textio.read_json(path, "field schema")
    except (OSError, ValueError) as e:
        raise DpmError("bad_field_schema", f"cannot read the field schema: {e}",
                       "it is JSON: {\"fields\": [{\"name\": \"...\", \"hint\": \"...\"}]}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), list) or not raw["fields"]:
        # A shape, not an example from somebody's domain: this tool has no business fields and
        # its error messages should not imply one either.
        raise DpmError("bad_field_schema", "the field schema has no `fields` list",
                       'e.g. {"fields": [{"name": "<field_name>", "hint": "<label as it appears '
                       'in the document>:", "required": true}]}')

    seen, fields = set(), []
    for i, field in enumerate(raw["fields"]):
        if not isinstance(field, dict) or not str(field.get("name") or "").strip():
            raise DpmError("bad_field_schema", f"field {i} has no name", "every field needs a `name`")
        name = str(field["name"]).strip()
        if name in seen:
            raise DpmError("bad_field_schema", f"the field {name!r} appears twice",
                           "field names are the output's key; two of them cannot both be it")
        seen.add(name)
        hint = str(field.get("hint") or "").strip()
        if not hint:
            raise DpmError("bad_field_schema", f"the field {name!r} has no hint",
                           "a hint is the label to search near, as it appears in the document "
                           "(including its colon), or a pattern with `regex: true`")
        if field.get("regex"):
            try:
                re.compile(hint)
            except re.error as e:
                raise DpmError("bad_field_schema", f"the field {name!r} has an invalid regex: {e}",
                               "test it before the job; an invalid pattern finds nothing and "
                               "reads as an empty document") from None
        fields.append({"name": name, "hint": hint, "regex": bool(field.get("regex")),
                       "required": bool(field.get("required"))})
    return FieldSchema(fields, str(raw.get("schema_version") or SCHEMA_VERSION))


# ------------------------------------------------------------------------------- the engines


class Engine:
    """How a field is found in one document's text.

    A real seam, not a flag over one code path: the Azure Content Understanding engine (#31) plugs
    in here with the same schema in and the same rows out, so nothing downstream -- the skill, the
    review file, the provenance -- has to know which one ran.

    An engine is given the text and the schema and returns one result per field. It is never given
    the run root, and never writes anything.
    """

    name = "base"

    def find(self, text: str, field: dict) -> tuple[str, str, str]:
        """(status, value, detail). `status` is one of STATUSES."""
        raise NotImplementedError


class SimpleEngine(Engine):
    """Plain text search near the hint. Deliberately unclever.

    It is the floor, not the goal: it finds a labelled value on a line and says `ambiguous` when a
    label appears more than once with different values -- which is the honest answer, and the one a
    reviewer can act on. Anything smarter is #31's engine.
    """

    name = "simple"

    def find(self, text: str, field: dict) -> tuple[str, str, str]:
        if not text.strip():
            return "no_text", "", "the document has no extracted text"
        pattern = field["hint"] if field["regex"] else re.escape(field["hint"])
        found = []
        for match in re.finditer(pattern, text, re.I):
            value = _after(text, match.end())
            if value:
                found.append(value)
        if not found:
            return "not_found", "", f"no match for {field['hint']!r}"
        unique = list(dict.fromkeys(found))
        if len(unique) > 1:
            return "ambiguous", unique[0], (f"{len(found)} matches with {len(unique)} different "
                                            f"values: {', '.join(repr(u) for u in unique[:3])}")
        return "found", unique[0], f"{len(found)} match(es), one value"


def _after(text: str, position: int) -> str:
    """The value that follows a label: the rest of the line, or the next non-empty one.

    A label at the end of its line is the common layout in a form, and treating it as "no value"
    would report half a document as missing.
    """
    rest = text[position:position + VALUE_CHARS * 2]
    line, _, remainder = rest.partition("\n")
    line = line.strip(" \t:=-–—")
    if line:
        return " ".join(line.split())[:VALUE_CHARS]
    for candidate in remainder.splitlines():
        candidate = candidate.strip(" \t:=-–—")
        if candidate:
            return " ".join(candidate.split())[:VALUE_CHARS]
    return ""


ENGINES: dict[str, type[Engine]] = {SimpleEngine.name: SimpleEngine}


def register(engine: type[Engine]) -> None:
    """How another module adds an engine. #31 calls this; nothing here has to change for it."""
    ENGINES[engine.name] = engine


def engine_for(name: str) -> Engine:
    if name not in ENGINES:
        raise DpmError("unknown_engine", f"unknown engine {name!r}", "one of " + " | ".join(sorted(ENGINES)))
    return ENGINES[name]()


# ------------------------------------------------------------------------------- the run


def read_manifest(path: str) -> dict:
    try:
        manifest = textio.read_json(path, "job manifest")
    except (OSError, ValueError) as e:
        raise DpmError("bad_manifest", f"cannot read the job manifest: {e}",
                       "`ad-dpm convert` writes it as job-manifest.json") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("jobs"), list):
        raise DpmError("bad_manifest", "that file is not a DPM job manifest",
                       "it needs a `jobs` list; `ad-dpm convert` produces one")
    return manifest


def extract(*, manifest: dict, schema: FieldSchema, engine_name: str = SimpleEngine.name,
            run_root: str | None = None, read_text=None) -> dict:
    """One row per (job, field), with the job's own lineage carried through.

    `read_text` is injectable so the tests do not need a DPM run on disk; by default it reads the
    `text_path` the manifest recorded.
    """
    engine = engine_for(engine_name)
    reader = read_text or _read_text

    before = snapshot(run_root) if run_root else None
    rows, counts = [], {status: 0 for status in STATUSES}
    for job in manifest["jobs"]:
        lineage = job.get("lineage") or {}
        common = {"job_id": job.get("job_id"), "page": job.get("page"),
                  "document_id": job.get("document_id"),
                  "sha256": job.get("sha256") or lineage.get("source_sha256"),
                  "engine": engine.name, "text_path": job.get("text_path")}

        if job.get("route") != "native_text":
            # Not "failed to extract". The document may well contain every field; nobody here can
            # say so honestly, because the OCR text's quality is unverified. Bucketed the way
            # `convert.py` buckets what it cannot route, rather than guessed at.
            for field in schema.fields:
                counts["needs_ocr_review"] += 1
                rows.append({**common, "field": field["name"], "status": "needs_ocr_review",
                             "value": "", "hint": field["hint"],
                             "detail": f"route is {job.get('route')}: the text quality is not "
                                       f"verified, so a value read from it would not be either"})
            continue

        text = reader(job)
        for field in schema.fields:
            status, value, detail = engine.find(text, field)
            counts[status] = counts.get(status, 0) + 1
            rows.append({**common, "field": field["name"], "status": status, "value": value,
                         "hint": field["hint"], "detail": detail})

    result = {"result_version": RESULT_VERSION, "engine": engine.name,
              "schema_version": schema.version, "fields": schema.names,
              "required": schema.required(), "rows": rows, "counts": counts,
              "jobs": len(manifest["jobs"]), "documents": len({r["document_id"] for r in rows})}
    result["missing_required"] = _missing_required(rows, schema)

    if run_root:
        changed = diff(before, snapshot(run_root))
        if changed:
            raise DpmError("run_root_changed", f"the run root changed while reading it: {changed[:3]}",
                           "extraction reads; something else is writing to the run")
    return result


def _read_text(job: dict) -> str:
    path = job.get("text_path")
    if not path:
        return ""
    try:
        return textio.read_text(path)
    except OSError:
        return ""


def _missing_required(rows: list[dict], schema: FieldSchema) -> list[dict]:
    """A required field that no document yielded. The reviewer's first question."""
    required = set(schema.required())
    if not required:
        return []
    found = {r["field"] for r in rows if r["status"] == "found"}
    return [{"field": name, "documents_checked": len({r["document_id"] for r in rows})}
            for name in schema.required() if name not in found]


def review_md(result: dict, run_id: str, *, max_examples: int = 3) -> str:
    """What a human reviewer reads. Every number here is a count and every value is cited by
    document and page, because the point of the file is deciding what to check by hand."""
    counts = result["counts"]
    lines = [f"# {run_id}: field extraction", "",
             f"Engine `{result['engine']}` · schema version {result['schema_version']} · "
             f"{result['documents']} document(s) · {len(result['fields'])} field(s).", "",
             "| Status | Count | Means |", "| --- | --- | --- |",
             f"| found | {counts.get('found', 0)} | one value, one place |",
             f"| ambiguous | {counts.get('ambiguous', 0)} | the label appears more than once with different values |",
             f"| not_found | {counts.get('not_found', 0)} | the label is not in the text |",
             f"| needs_ocr_review | {counts.get('needs_ocr_review', 0)} | **not extracted**: the route is OCR and its text quality is unverified |",
             f"| no_text | {counts.get('no_text', 0)} | routed as native text but the text is empty |", ""]

    if result["missing_required"]:
        lines += ["## Required fields no document yielded", ""]
        lines += [f"- `{m['field']}` — not found in any of {m['documents_checked']} document(s)"
                  for m in result["missing_required"]]
        lines.append("")

    ambiguous = [r for r in result["rows"] if r["status"] == "ambiguous"]
    if ambiguous:
        lines += ["## Ambiguous — check these by hand", ""]
        for row in ambiguous[:max_examples]:
            lines.append(f"- `{row['document_id']}` p{row['page']} `{row['field']}`: "
                         f"took `{row['value']}` — {row['detail']}")
        lines.append("")

    if counts.get("needs_ocr_review"):
        lines += ["## Not extracted", "",
                  "Documents routed to OCR are **not** extracted from here: their text quality is "
                  "unverified, and a value read from bad OCR looks exactly like a value read from "
                  "good text. Verify the OCR, or extract them with an engine that reads the image.",
                  ""]

    lines += ["## Provenance", "",
              "Every row carries the document id, page and source sha256 from the DPM job manifest "
              "— the same lineage `ad-dpm convert` recorded, not a second one."]
    return "\n".join(lines) + "\n"
