"""Carrying out a plan. Copies, never moves; refuses a plan whose heap has changed since it was written.

This is the human's command, and the split is the point: `plan` is what an agent may run, because it writes nothing but
its own plan file, and `apply` is what somebody who has read that plan runs afterwards. Nothing here re-decides
anything -- it copies exactly the `file` rows and refuses if the ground moved.

It copies. The originals stay in the heap, so a wrong rule set costs disk and not documents, and a second `plan` of the
same heap still describes the same heap. Moving is a different tool with a different safety story (a journal, an undo)
and is deliberately not this one.
"""
from __future__ import annotations
import os
import shutil

from . import SortError
from . import plan as P
from .. import textio


def check_ready(plan: dict, *, dest: str | None = None) -> str:
    """The destination root this plan may write under, or a refusal. Verifies the heap is as planned."""
    heap = plan.get("heap") or ""
    if not os.path.isdir(heap):
        raise SortError("heap_missing", f"the heap this plan was made for is gone: {heap}",
                        "re-plan against the folder as it is now")
    now = P.fingerprint(heap)
    if now["sha256"] != (plan.get("fingerprint") or {}).get("sha256"):
        raise SortError("heap_changed",
                        f"the heap has changed since this plan was written "
                        f"({(plan.get('fingerprint') or {}).get('files')} files then, {now['files']} now)",
                        "run `ad-sort plan` again and read the new plan; applying a stale plan would file "
                        "a heap nobody looked at")
    root = os.path.abspath(os.path.expanduser(dest)) if dest else (plan.get("dest") or "")
    if not root:
        raise SortError("no_destination", "the plan names no destination", "re-plan with --dest")
    if P.is_within(root, heap) or P.is_within(heap, root):
        raise SortError("destination_inside_heap", f"the destination {textio.norm_path(root)} overlaps the heap",
                        "file into a folder beside the heap, not inside it")
    return root


def run(plan: dict, *, dest: str | None = None) -> dict:
    """Copy every `file` row. Returns a receipt: what was copied, what was already there, what failed."""
    root = check_ready(plan, dest=dest)
    heap = plan["heap"]
    copied, failed, existed = [], [], []
    for row in plan["rows"]:
        if row.get("verdict") != "file":
            continue
        source = os.path.join(heap, row["source"])
        target = os.path.join(root, *row["destination"].split("/"))
        # Re-checked here and not only in `plan`: between the two commands somebody may have created the file, and the
        # one thing this must never do is overwrite a document.
        if os.path.exists(target):
            existed.append(row["destination"])
            continue
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(textio.longpath(source), textio.longpath(target))
            copied.append(row["destination"])
        except OSError as e:
            failed.append({"destination": row["destination"], "error": str(e)})
    return {"dest": textio.norm_path(root), "copied": len(copied), "existed": len(existed),
            "failed": len(failed), "files": copied, "already_there": existed, "errors": failed}


def receipt_md(plan: dict, result: dict) -> str:
    lines = [f"# Sort applied — {plan['heap']}", "",
             f"* into: `{result['dest']}`",
             f"* copied: {result['copied']} · already there: {result['existed']} · failed: {result['failed']}",
             "* the originals are untouched: this copies and never moves.", ""]
    for title, items in (("Copied", result["files"]), ("Already there, left alone", result["already_there"])):
        if items:
            lines += [f"## {title} ({len(items)})", ""] + [f"* `{i}`" for i in items] + [""]
    if result["errors"]:
        lines += [f"## Failed ({len(result['errors'])})", ""]
        lines += [f"* `{e['destination']}` — {e['error']}" for e in result["errors"]] + [""]
    return "\n".join(lines)
