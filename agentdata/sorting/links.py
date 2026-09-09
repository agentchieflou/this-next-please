"""Hardlink, or copy, and never a mystery about which happened.

The ticket's rule is "hardlinks preferred over copied files", and the reason is the model underneath it: downloaded
documents are canonical evidence, derived views are disposable navigation aids. A hardlink is exactly that -- a second
name for one set of bytes, so a view costs no storage and deleting a whole view tree cannot touch the evidence.

Two facts decide whether that is available, and neither can be assumed from a drive letter:

* a hardlink cannot cross volumes, and
* most SMB shares do not implement `CreateHardLink` at all -- a mapped drive letter says nothing about this.

So this probes rather than believes, once per destination volume, and records the mode it actually used on every row it
writes. A manifest that says `copy` where somebody expected `hardlink` is a storage forecast being wrong; a manifest
that does not say is an argument nobody can settle.
"""
from __future__ import annotations
import os
import shutil

from .. import textio

HARDLINK = "hardlink"
COPY = "copy"


def probe(directory: str) -> dict:
    """Can this directory's volume make a hardlink? Creates two names for one temp file, then removes both."""
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, ".ad-sort-linkprobe")
    link = os.path.join(directory, ".ad-sort-linkprobe-2")
    for path in (target, link):
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        with open(textio.longpath(target), "w", encoding="utf-8") as f:
            f.write("ad-sort hardlink probe\n")
    except OSError as e:
        return {"hardlinks": False, "writable": False, "evidence": f"cannot create a file here: {e}"}
    answer = {"hardlinks": False, "writable": True, "evidence": ""}
    try:
        os.link(textio.longpath(target), textio.longpath(link))
        answer["hardlinks"] = True
        answer["evidence"] = "os.link succeeded on this volume"
    except (OSError, AttributeError, NotImplementedError) as e:
        answer["evidence"] = f"os.link failed here, so views would be copies: {e}"
    finally:
        for path in (link, target):
            try:
                os.remove(path)
            except OSError:
                pass
    return answer


def place(source: str, target: str, *, prefer: str = HARDLINK) -> str:
    """Put `source`'s bytes at `target`. Returns the mode used. Never overwrites: the caller checked, and so do we."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if prefer == HARDLINK:
        try:
            os.link(textio.longpath(source), textio.longpath(target))
            return HARDLINK
        except (OSError, AttributeError, NotImplementedError):
            pass                                    # a different volume, or a share that has no hardlinks
    shutil.copy2(textio.longpath(source), textio.longpath(target))
    return COPY
