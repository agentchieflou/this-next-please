"""Mechanical TMDL edits so the agent never hand-types indentation: measure upsert (more to come)."""
from __future__ import annotations
import os
from . import tmdl as T
from .normalize import Model


def measure_set(model: Model, table: str, name: str, expr: str, format_string: str | None = None, display_folder: str | None = None,
                description: str | None = None, lineage_tag: bool = False, hidden: bool | None = None, dry_run: bool = False) -> dict:
    tf, node = None, None
    for path, f in model.files.items():
        for n in f.nodes:
            if n.kind == "table" and n.name == table:
                tf, node = f, n
    if tf is None or node is None:
        raise LookupError(f"table '{table}' not found in {model.definition_dir} (tables: {', '.join(sorted(t['name'] for t in model.tables))})")
    before = list(tf.lines)
    props: dict = {}
    existing = node.child("measure", name)
    if existing:  # keep untouched properties
        for k, v in existing.props.items():
            if k not in ("formatString", "displayFolder", "isHidden", "lineageTag"):
                props[k] = v
    if format_string is not None:
        props["formatString"] = format_string
    elif existing and existing.props.get("formatString"):
        props["formatString"] = existing.props["formatString"]
    if display_folder is not None:
        props["displayFolder"] = display_folder
    elif existing and existing.props.get("displayFolder"):
        props["displayFolder"] = existing.props["displayFolder"]
    if hidden or (hidden is None and existing and existing.props.get("isHidden") is True):
        props["isHidden"] = True
    desc = description if description is not None else (" ".join(existing.desc) if existing and existing.desc else None)
    action, line = T.upsert_measure(tf, node, name, expr, props, desc, lineage_tag)
    check = T.parse_text(tf.text, tf.path, bom=tf.bom)
    new_errors = [f for f in T.lint_file(check) if f.severity == "error"]
    if new_errors:
        tf.lines[:] = before
        raise ValueError("edit would leave the file invalid: " + "; ".join(f"L{f.line} {f.rule}: {f.message}" for f in new_errors[:3]))
    if not dry_run:
        T.write_file(tf)
    return {"action": action, "file": os.path.relpath(tf.path, model.definition_dir).replace("\\", "/"), "line": line,
            "table": table, "measure": name, "lines_changed": len(tf.lines) - len(before), "dry_run": dry_run}
