"""Guards that make the contract mechanical: the run root is never written; artifacts land only in the governed dir."""
from __future__ import annotations
import hashlib
import os

from . import DpmError

CHUNK = 1 << 20


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: str) -> dict:
    """Cheap fingerprint of a tree: relative path, size and mtime of every file. Reading a run never changes it; anything
    that does shows up as a different sha256 and in diff()."""
    entries: list[tuple[str, int, int]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            entries.append((os.path.relpath(p, root).replace("\\", "/"), st.st_size, st.st_mtime_ns))
    h = hashlib.sha256()
    for rel, size, mtime in entries:
        h.update(f"{rel}\t{size}\t{mtime}\n".encode("utf-8"))
    return {"sha256": h.hexdigest(), "files": len(entries), "bytes": sum(e[1] for e in entries), "entries": entries}


def diff(before: dict, after: dict) -> list[str]:
    b = {e[0]: e[1:] for e in before["entries"]}
    a = {e[0]: e[1:] for e in after["entries"]}
    out = [f"added {p}" for p in a if p not in b] + [f"removed {p}" for p in b if p not in a]
    out += [f"modified {p}" for p in a if p in b and a[p] != b[p]]
    return sorted(out)


def real(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(p))))


def is_within(child: str, parent: str) -> bool:
    c, p = real(child), real(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def governed_dir(consumer_root: str, artifact_dir: str, run_root: str) -> str:
    """Absolute artifact directory. Refuses anything outside the consumer repo or overlapping the run root."""
    if not os.path.isdir(consumer_root):
        raise DpmError("consumer_root_missing", f"consumer root is not a directory: {consumer_root}",
                       "pass --consumer <path to the data_remediation_foundry_DPM_fork checkout>")
    out = os.path.expanduser(artifact_dir)
    if not os.path.isabs(out):
        out = os.path.join(consumer_root, out)
    out = os.path.abspath(out)
    if not is_within(out, consumer_root):
        raise DpmError("artifact_dir_outside_consumer", f"artifact dir {out} is outside the consumer repo {os.path.abspath(consumer_root)}",
                       "set dpm_artifact_dir in AGENTS.md to the consumer's governed artifact directory, relative to its repo root")
    if is_within(out, run_root) or is_within(run_root, out):
        raise DpmError("artifact_dir_touches_run_root", f"artifact dir {out} overlaps the DPM run root {run_root}",
                       "never write beneath the run root; choose a directory inside the consumer repo")
    return out
