"""Binding verification: diff PBIR field and entity references against target TMDL model."""
from __future__ import annotations
import os
from typing import Any

from ..pbip import normalize as N
from ..pbip import pbir as P


def verify_binding(report_dir: str, model_dir: str) -> tuple[bool, list[dict[str, Any]]]:
    """Verify that all entity and column/measure references in a PBIR report resolve in target TMDL model.
    
    Returns (is_valid, list_of_unresolved_refs).
    """
    # Locate model.tmdl
    tmdl_dir = model_dir
    if os.path.exists(os.path.join(model_dir, "definition", "model.tmdl")):
        tmdl_dir = os.path.join(model_dir, "definition")
    elif not os.path.exists(os.path.join(model_dir, "model.tmdl")):
        # Check subdirectories
        for entry in os.scandir(model_dir):
            if entry.is_dir():
                sub_def = os.path.join(entry.path, "definition")
                if os.path.exists(os.path.join(sub_def, "model.tmdl")):
                    tmdl_dir = sub_def
                    break
                if os.path.exists(os.path.join(entry.path, "model.tmdl")):
                    tmdl_dir = entry.path
                    break

    if not os.path.exists(os.path.join(tmdl_dir, "model.tmdl")):
        raise FileNotFoundError(f"no model.tmdl found under {model_dir}")

    target_model = N.load_model(tmdl_dir)
    report = P.load_report(report_dir)
    idx = N.ModelIndex(target_model, report)

    unresolved: list[dict[str, Any]] = []

    for v in report.all_visuals():
        for r in v.fields:
            ok, why = idx.resolve(r)
            if not ok:
                unresolved.append({
                    "visual_id": v.id,
                    "visual_title": v.title,
                    "entity": r.entity,
                    "prop": r.prop,
                    "kind": r.kind,
                    "context": r.context,
                    "reason": why,
                    "where": f"{v.file} {r.path}",
                })

    for em in report.extension_measures:
        if em["entity"] not in idx.tables:
            unresolved.append({
                "visual_id": "",
                "visual_title": "extension-measure",
                "entity": em["entity"],
                "prop": em["name"],
                "kind": "measure",
                "context": "report extension measure",
                "reason": f"target table '{em['entity']}' not in target model",
                "where": em.get("file", "report.json"),
            })

    return len(unresolved) == 0, unresolved
