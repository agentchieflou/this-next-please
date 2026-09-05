"""Fabric item-definition parts assembly, extraction, and comparison."""
from __future__ import annotations
import base64
import json
import os
import re
from .. import textio

IGNORED_NAMES = {".platform", "localsettings.json", ".git", ".agent", ".gitignore"}
IGNORED_EXTS = {".pbi", ".user"}


def is_ignored(rel_path: str) -> bool:
    norm = textio.norm_path(rel_path).lower()
    parts = norm.split("/")
    for p in parts:
        if p in IGNORED_NAMES or p.startswith(".agent"):
            return True
        _, ext = os.path.splitext(p)
        if ext in IGNORED_EXTS:
            return True
    return False


def load_report_parts(report_folder: str, target_model_id: str | None = None) -> tuple[list[dict], list[str]]:
    """Assemble all parts from a .Report folder.
    
    Paths are forward-slash normalized.
    `definition.pbir` is converted in-memory to `byConnection` (the file on disk stays `byPath`).
    Payloads are base64-encoded.
    Returns (parts_list, rel_paths_list).
    """
    if not os.path.isdir(report_folder):
        raise FileNotFoundError(f"report folder does not exist: {report_folder}")

    parts: list[dict] = []
    paths: list[str] = []

    for root, dirs, files in os.walk(report_folder):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_NAMES and not d.startswith(".agent")]
        for f in sorted(files):
            full_path = os.path.join(root, f)
            rel_path = textio.norm_path(os.path.relpath(full_path, report_folder))
            if is_ignored(rel_path):
                continue

            if rel_path == "definition.pbir" and target_model_id:
                # Rewrite to byConnection in memory only
                try:
                    pbir_data = json.loads(open(full_path, encoding="utf-8").read())
                except Exception:
                    pbir_data = {}
                pbir_data["datasetReference"] = {
                    "byConnection": {
                        "connectionString": None,
                        "pbiServiceModelId": None,
                        "pbiModelVirtualServerName": "sobe_wowvirtualserver",
                        "pbiModelDatabaseName": target_model_id
                    }
                }
                raw_bytes = json.dumps(pbir_data, indent=2).encode("utf-8")
            else:
                with open(full_path, "rb") as fh:
                    raw_bytes = fh.read()

            b64_payload = base64.b64encode(raw_bytes).decode("ascii")
            parts.append({
                "path": rel_path,
                "payload": b64_payload,
                "payloadType": "InlineBase64"
            })
            paths.append(rel_path)

    return parts, paths


def load_model_parts(model_folder: str) -> tuple[list[dict], list[str]]:
    """Assemble TMDL definition parts from a semantic model folder.
    
    Paths are forward-slash normalized.
    Payloads are base64-encoded.
    Returns (parts_list, rel_paths_list).
    """
    if not os.path.isdir(model_folder):
        raise FileNotFoundError(f"model folder does not exist: {model_folder}")

    # If folder contains a 'definition' subfolder, use definition as the root or include definition/
    parts: list[dict] = []
    paths: list[str] = []

    for root, dirs, files in os.walk(model_folder):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_NAMES and not d.startswith(".agent")]
        for f in sorted(files):
            full_path = os.path.join(root, f)
            rel_path = textio.norm_path(os.path.relpath(full_path, model_folder))
            if is_ignored(rel_path):
                continue

            with open(full_path, "rb") as fh:
                raw_bytes = fh.read()

            b64_payload = base64.b64encode(raw_bytes).decode("ascii")
            parts.append({
                "path": rel_path,
                "payload": b64_payload,
                "payloadType": "InlineBase64"
            })
            paths.append(rel_path)

    return parts, paths


def extract_parts_to_disk(parts: list[dict], out_dir: str) -> tuple[int, int]:
    """Decode base64 parts to disk using forward-slash paths.
    
    Returns (part_count, total_bytes).
    """
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    count = 0
    total_bytes = 0

    for part in parts:
        path = textio.norm_path(part.get("path", "")).lstrip("/")
        if not path:
            continue
        dest = os.path.abspath(os.path.join(out_dir_abs, path))
        if not dest.startswith(out_dir_abs):
            # Prevent directory traversal
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        payload = part.get("payload", "")
        ptype = part.get("payloadType", "InlineBase64")
        if ptype == "InlineBase64":
            data = base64.b64decode(payload)
        else:
            data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)

        with open(dest, "wb") as f:
            f.write(data)

        count += 1
        total_bytes += len(data)

    return count, total_bytes


def check_vanished_parts(current_paths: list[str], previous_dir: str) -> list[str]:
    """Check if any parts in previous_dir are missing in current_paths.
    
    Returns list of vanished relative paths.
    """
    if not os.path.isdir(previous_dir):
        return []

    cur_set = set(textio.norm_path(p) for p in current_paths)
    vanished: list[str] = []

    for root, dirs, files in os.walk(previous_dir):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORED_NAMES and not d.startswith(".agent")]
        for f in files:
            full = os.path.join(root, f)
            rel = textio.norm_path(os.path.relpath(full, previous_dir))
            if is_ignored(rel):
                continue
            if rel not in cur_set:
                vanished.append(rel)

    return sorted(vanished)
