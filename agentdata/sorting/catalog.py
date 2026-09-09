"""The per-source-system JSONL that says what each downloaded document *is*.

Retrieval writes one JSONL per source system (LSS, LIS, IMZ), one record per downloaded file. Those records are the
only place the fields this filing structure is organised by actually exist -- `DocSubtypeName` and `FileDesc` are not
in the filename and are not in `orchestrator.db`'s canonical `documents` table. So the catalogue is an **input**, read
and never inferred, which is also what keeps the planner's promise that it opens no document: it reads the sidecar,
not the PDF.

Field names are bound per source system rather than assumed, the way `ad-dpm`'s binding is. LSS and IMZ share the set
below. **LIS is deliberately unmapped**: nobody has said what its records look like, and a guess here would file real
documents under a field that does not mean what we think it means.
"""
from __future__ import annotations
import json
import os

from . import SortError
from .. import textio

# concept -> the key retrieval writes. Bound, not guessed; `ad-sort dpm-plan --source` picks the map.
LSS_IMZ = {
    "file_name": "FileName",
    "doc_subtype": "DocSubtypeName",
    "business_area": "BusinessAreaName",
    "repo_doc_name": "RepositoryDocName",
    "repo_stored_at": "RepoStorageDatetime",
    "total_pages": "Total Pages",
    "file_size": "FileSizeInBytes",
    "file_desc": "FileDesc",
    "can_view": "IsCanView",
    "is_tiff": "IsTiff",
}

SOURCES: dict[str, dict | None] = {"LSS": LSS_IMZ, "IMZ": LSS_IMZ, "LIS": None}

# The loan number is what the structure's second level is, and it was never named among the fields above. Rather than
# pick one, the reader looks for these in order and says which it used -- and refuses, listing the record's real keys,
# when none of them is there. `--loan-field` overrides.
LOAN_KEYS = ("LoanNumber", "Loan_Number", "loan_number", "LoanNbr", "LoanNum", "LoanId", "loan_id", "Loan")

# What a normalised record carries. The manifest writes these plus the lineage columns.
FIELDS = ("loan_number", "file_name", "doc_subtype", "file_desc", "business_area", "repo_doc_name",
          "repo_stored_at", "total_pages", "file_size", "can_view", "is_tiff", "source_system")

TRUE = {"true", "t", "yes", "y", "1"}
FALSE = {"false", "f", "no", "n", "0", ""}


def _bool(value, field: str, line: int):
    """`IsCanView` and `IsTiff` decide a count somebody reports and a conversion queue somebody works, so an
    unrecognised spelling is a refusal rather than a falsy default."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in TRUE:
        return True
    if text in FALSE:
        return False
    raise SortError("bad_catalog_value", f"line {line}: {field} is {value!r}, which is neither true nor false",
                    f"expected one of {sorted(TRUE)} or {sorted(FALSE)}")


def loan_key(record: dict, override: str = "") -> str:
    if override:
        if override not in record:
            raise SortError("loan_field_missing", f"no {override!r} in the catalogue records",
                            f"the record has: {', '.join(sorted(record))}")
        return override
    for candidate in LOAN_KEYS:
        if candidate in record:
            return candidate
    raise SortError("loan_field_missing",
                    "no loan number field in the catalogue records, and the structure files by loan",
                    f"looked for {', '.join(LOAN_KEYS)}; the record has: {', '.join(sorted(record))}. "
                    "Name it with --loan-field.")


def field_map(source: str) -> dict:
    key = (source or "").strip().upper()
    if key not in SOURCES:
        raise SortError("unknown_source_system", f"no field map for source system {source!r}",
                        f"known: {', '.join(sorted(SOURCES))}")
    mapped = SOURCES[key]
    if mapped is None:
        raise SortError("unmapped_source_system",
                        f"{key} records have not been described, so nothing here knows which key is which",
                        "send one sample record and the map goes in `agentdata/sorting/catalog.py`; guessing it "
                        "would file real documents under a field that may not mean what we think it means")
    return mapped


def read(path: str, source: str, *, loan_field: str = "") -> dict:
    """Normalise one source system's JSONL. Returns rows plus what it had to skip, and why."""
    mapped = field_map(source)
    if not os.path.isfile(path):
        raise SortError("catalog_missing", f"no catalogue at {textio.norm_path(path)}",
                        "retrieval writes one JSONL per source system; point --catalog at it")

    rows, bad, chosen_loan_key = [], [], loan_field
    for number, line in enumerate(textio.read_text(path).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as e:
            bad.append({"line": number, "why": f"not JSON: {e}"})
            continue
        if not isinstance(record, dict):
            bad.append({"line": number, "why": f"a {type(record).__name__}, not an object"})
            continue
        if not chosen_loan_key:
            chosen_loan_key = loan_key(record, loan_field)
        name = str(record.get(mapped["file_name"], "") or "").strip()
        loan = str(record.get(chosen_loan_key, "") or "").strip()
        if not name or not loan:
            bad.append({"line": number, "why": f"no {'file name' if not name else 'loan number'}"})
            continue
        rows.append({
            "loan_number": loan,
            "file_name": name,
            "doc_subtype": str(record.get(mapped["doc_subtype"], "") or "").strip(),
            "file_desc": str(record.get(mapped["file_desc"], "") or "").strip(),
            "business_area": str(record.get(mapped["business_area"], "") or "").strip(),
            "repo_doc_name": str(record.get(mapped["repo_doc_name"], "") or "").strip(),
            "repo_stored_at": str(record.get(mapped["repo_stored_at"], "") or "").strip(),
            "total_pages": str(record.get(mapped["total_pages"], "") or "").strip(),
            "file_size": str(record.get(mapped["file_size"], "") or "").strip(),
            "can_view": _bool(record.get(mapped["can_view"]), mapped["can_view"], number),
            "is_tiff": _bool(record.get(mapped["is_tiff"]), mapped["is_tiff"], number),
            "source_system": (source or "").strip().upper(),
            "line": number,
        })
    if not rows and not bad:
        raise SortError("catalog_empty", f"{textio.norm_path(path)} has no records",
                        "an empty catalogue means retrieval produced nothing for this ticket; that is a retrieval "
                        "answer, not a filing one")
    return {"rows": rows, "unusable": bad, "loan_field": chosen_loan_key, "source_system": (source or "").upper()}


def loans_from(path: str) -> list[str]:
    """The loan population somebody expected, one per line (a bare list or the first column of a CSV).

    Without it, "which loans had no documents" cannot be answered: a catalogue only knows the loans that produced
    something. This file is what makes the absent ones visible.
    """
    if not os.path.isfile(path):
        raise SortError("loan_list_missing", f"no loan list at {textio.norm_path(path)}",
                        "one loan number per line; it is what makes a loan with zero documents visible")
    out, seen = [], set()
    for line in textio.read_text(path).splitlines():
        loan = line.split(",")[0].strip().strip('"')
        if not loan or loan.lower() in ("loan", "loan_number", "loannumber"):
            continue
        if loan not in seen:
            seen.add(loan)
            out.append(loan)
    return out
