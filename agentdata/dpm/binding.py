"""Contract binding: the names in a DPM run root that map to the concepts this skill validates.

The concepts are fixed (run-root markers, orchestrator.db canonical manifest, selection manifests, text_analysis
outputs, version markers, partition thresholds). Only names and thresholds are bound, and only here. A consumer repo
overrides any of them with a JSON file (`ad-dpm binding --write dpm-binding.json`, edit, point the `dpm_binding` fact at
it). Unknown keys are refused so a typo can never silently unbind a check. Changing a `supported` list is a contract
decision: it needs the DPM owners' sign-off, not a worker model's.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os

from .. import textio
from . import DpmError

BINDING_V1: dict = {
    "binding_version": 1,
    "producer": "DPM",
    "consumer": "data_remediation_foundry_DPM_fork",
    "run_root": {
        # both markers must exist for a folder to count as a run root
        "orchestrator_db": "orchestrator.db",
        "text_analysis_dir": "text_analysis",
        # globs relative to the run root; the first pattern that matches anything is not special: all matches are read
        "selection_manifests": ["selections/*.json", "selection_manifests/*.json", "manifests/selection*.json", "*.selection.json"],
        # where the run id lives; falls back to the run root folder name
        "run_id": {"table": "runs", "column": "run_id"},
    },
    "versions": {
        # orchestrator.db: PRAGMA user_version and/or a version table. At least one must resolve to a supported value.
        "orchestrator": {"pragma_user_version": True, "table": "schema_version", "column": "version", "supported": ["1"], "required": True},
        "selection_manifest": {"key": "manifest_version", "supported": ["1", "1.0"], "required": True},
        "text_analysis": {"key": "schema_version", "supported": ["1", "1.0"], "required": True},
    },
    "canonical": {
        # the canonical document manifest inside orchestrator.db; concept -> column name
        "table": "documents",
        "columns": {"document_id": "document_id", "loan_id": "loan_id", "sha256": "sha256", "channel": "channel",
                    "source_path": "source_path", "page_count": "page_count", "mime_type": "mime_type", "status": "status"},
        "optional_columns": ["mime_type", "status", "page_count"],
        "unsupported_statuses": ["unsupported", "rejected", "corrupt", "failed"],
    },
    # optional page-level canonical table; when present every selected page must exist in it
    "pages": {"table": "pages", "columns": {"document_id": "document_id", "page_number": "page_number"}, "required": False},
    # allowed channels: the explicit list wins; else the channels table; else unconstrained (warning)
    "channels": {"allowed": [], "table": "channels", "column": "channel"},
    "selection": {
        "keys": {"selection_id": "selection_id", "run_id": "run_id", "items": "items", "document_id": "document_id",
                 "sha256": "sha256", "loan_id": "loan_id", "pages": "pages"},
    },
    "text_analysis": {
        # file name inside text_analysis_dir; placeholders: {document_id} {sha256}
        "file": "{document_id}.json",
        "keys": {"document_id": "document_id", "sha256": "sha256", "unsupported": "unsupported", "pages": "pages", "page": "page",
                 "has_native_text": "has_native_text", "char_count": "char_count", "text_quality": "text_quality", "text_path": "text_path"},
    },
    "partition": {
        # a page's native text is reusable when has_native_text, char_count >= native_min_chars,
        # text_quality >= native_min_quality (only checked when the key is present) and the text file exists
        "native_min_chars": 20,
        "native_min_quality": 0.5,
        # a document with at least one page that needs OCR must be one of these types, else it is `unsupported`
        "ocr_mime": ["application/pdf", "image/tiff", "image/png", "image/jpeg"],
        "ocr_extensions": [".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg"],
    },
}


def builtin() -> dict:
    return copy.deepcopy(BINDING_V1)


def _merge(base: dict, over: dict, trail: str) -> dict:
    for k, v in over.items():
        here = f"{trail}.{k}" if trail else k
        if k not in base:
            raise DpmError("binding_invalid", f"unknown binding key {here!r}", "keys must match the builtin binding: ad-dpm binding --show")
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise DpmError("binding_invalid", f"binding key {here!r} must be an object", "ad-dpm binding --show prints the expected shape")
            _merge(base[k], v, here)
        elif isinstance(base[k], list):
            if not isinstance(v, list):
                raise DpmError("binding_invalid", f"binding key {here!r} must be a list", "ad-dpm binding --show prints the expected shape")
            base[k] = list(v)
        else:
            base[k] = v
    return base


def load(path: str | None) -> tuple[dict, str]:
    """Effective binding and its label (`builtin` or the file path). Overrides are deep-merged over the builtin."""
    b = builtin()
    if not path:
        return b, "builtin"
    if not os.path.isfile(path):
        raise DpmError("binding_missing", f"binding file not found: {path}",
                       "check the dpm_binding fact in AGENTS.md (relative to the consumer root), or drop it to use the builtin binding")
    try:
        over = textio.read_json(path, "binding")   # a binding file may come from any tool; read what it wrote
    except ValueError as e:
        raise DpmError("binding_invalid", str(e), "") from None
    if not isinstance(over, dict):
        raise DpmError("binding_invalid", f"{path}: top level must be an object", "")
    if str(over.get("binding_version", 1)) != "1":
        raise DpmError("binding_invalid", f"{path}: binding_version {over.get('binding_version')!r} is not supported (1)", "")
    return _merge(b, over, ""), path.replace("\\", "/")


def sha256(binding: dict) -> str:
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def dump(binding: dict) -> str:
    return json.dumps(binding, indent=2) + "\n"
