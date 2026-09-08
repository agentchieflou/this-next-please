"""Reading a heap and deciding where each file would go. Reads names and `stat`; opens nothing; writes nothing.

The output is a plan: one row per entry in the heap, each carrying its verdict. The verdicts are the whole contract, so
they are few and each of them says something different to the person reading:

* `file` -- a rule claimed it and the destination is free. This is the only verdict `apply` acts on.
* `unmatched` -- no rule claimed it. Not a failure; it is the heap telling you the rules do not cover it yet.
* `collision` -- two files in the heap want one destination, or something is already there. Refused rather than
  resolved: a planner that appended `(2)` would be deciding which document is the real one.
* `skipped` -- an entry a plan may not act on, with the reason: a directory, a link leading out of the heap, a
  partially-downloaded `.crdownload`/`.partial`, or a file over the size cap.

`collision` is deliberately not silent and deliberately not automatic. Everything else in this repository that could
overwrite a file refuses instead, and a document heap is the worst possible place to start guessing.
"""
from __future__ import annotations
import datetime as _dt
import hashlib
import os

from . import SortError
from . import rules as R
from .. import textio

# The same cap `ad-fleet inbox` uses for what it will offer: past this, a heap entry is something else -- an installer,
# a disk image, a database -- and filing it by name is not a judgement this can make.
SIZE_CAP = 64 * 1024 * 1024

PARTIAL_SUFFIXES = (".crdownload", ".partial", ".part", ".tmp")

PLAN_COLS = ("verdict", "source", "destination", "rule", "why")

# What a plan row is allowed to say. Named here so the CLI, the writer and the tests agree on one list.
VERDICTS = ("file", "unmatched", "collision", "skipped")


def _real(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(p))))


def is_within(child: str, parent: str) -> bool:
    c, p = _real(child), _real(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def _fields(name: str, mtime: float) -> dict:
    stem, ext = os.path.splitext(name)
    when = _dt.datetime.fromtimestamp(mtime)
    return {"original": name, "stem": stem, "ext": ext, "ext_nodot": ext.lstrip("."),
            "year": f"{when.year:04d}", "month": f"{when.month:02d}", "day": f"{when.day:02d}"}


def _render(template: str, fields: dict) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", textio.safe_name(str(value)) if key not in ("ext", "original") else str(value))
    return out


def _destination(rule: dict, fields: dict, top: str) -> str:
    """The relative destination path for one matched file, under the rule set's own `into`."""
    folder = _render(rule["into"], fields)
    name = _render(rule["rename"], fields) if rule["rename"] else fields["original"]
    parts = [p for p in textio.norm_path(top + "/" + folder).split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise SortError("escaping_destination", f'rule {rule["name"]!r} produced a destination containing "..": {folder}',
                        "a rule may only file downwards; remove the .. from its `into`")
    return "/".join(parts + [textio.safe_name(name)])


def _entries(heap: str) -> list:
    """Every entry directly in the heap, as (name, is_dir, is_link, size, mtime). `scandir` only: nothing is opened."""
    try:
        with os.scandir(heap) as it:
            found = [(e.name, e) for e in it]
    except OSError as e:
        raise SortError("heap_unreadable", f"cannot list {textio.norm_path(heap)}: {e}",
                        "check the path and that this account may read it") from None
    out = []
    for name, entry in sorted(found, key=lambda pair: pair[0].lower()):
        try:
            is_link = entry.is_symlink()
            stat = entry.stat(follow_symlinks=False) if is_link else entry.stat()
            out.append((name, entry.is_dir(follow_symlinks=False), is_link, stat.st_size, stat.st_mtime))
        except OSError:
            out.append((name, False, False, -1, 0.0))
    return out


def fingerprint(heap: str) -> dict:
    """What the heap looked like when the plan was made, so `apply` can refuse a plan for a different one."""
    h = hashlib.sha256()
    count = 0
    for name, is_dir, _is_link, size, mtime in _entries(heap):
        if is_dir:
            continue
        h.update(f"{name}\t{size}\t{int(mtime)}\n".encode("utf-8"))
        count += 1
    return {"sha256": h.hexdigest(), "files": count}


def _skip_reason(name: str, is_dir: bool, is_link: bool, size: int, heap: str) -> str:
    if is_dir:
        return "a directory: this plans one folder, not a tree"
    if name.lower().endswith(PARTIAL_SUFFIXES):
        return "still being written (a browser's partial download)"
    if is_link and not is_within(os.path.join(heap, name), heap):
        return f"a link leading outside the heap, to {textio.norm_path(os.path.realpath(os.path.join(heap, name)))}"
    if size < 0:
        return "could not be stat'ed"
    if size > SIZE_CAP:
        return f"{size} bytes, over the {SIZE_CAP}-byte cap"
    return ""


def make(heap: str, rules: dict, *, dest: str | None = None) -> dict:
    """The plan for one heap under one rule set. Reads the heap; writes nothing anywhere."""
    if not os.path.isdir(heap):
        raise SortError("heap_missing", f"no such folder: {textio.norm_path(heap)}",
                        "point --heap at the folder the documents actually arrived in")
    heap = os.path.abspath(heap).rstrip(os.sep) or os.path.abspath(heap)
    # Beside the heap by default, never inside it. Filing a heap into itself would put the plan's own inputs under its
    # own output, and the next `plan` of that folder would describe the copies. It is a mistake with a quiet, expensive
    # shape, so the default avoids it and an explicit `--dest` that lands there is refused rather than tolerated.
    destination_root = (os.path.abspath(os.path.expanduser(dest)) if dest else
                        os.path.join(os.path.dirname(heap), os.path.basename(heap) + "-sorted"))
    if is_within(destination_root, heap) or is_within(heap, destination_root):
        raise SortError("destination_inside_heap",
                        f"the destination {textio.norm_path(destination_root)} overlaps the heap {textio.norm_path(heap)}",
                        "file into a folder beside the heap, not inside it")

    rows, claimed = [], {}
    for name, is_dir, is_link, size, mtime in _entries(heap):
        why = _skip_reason(name, is_dir, is_link, size, heap)
        if why:
            rows.append({"verdict": "skipped", "source": name, "destination": "", "rule": "", "why": why,
                         "bytes": max(size, 0)})
            continue
        for rule in rules["rules"]:
            captured = R.matches(rule, name)
            if captured is None:
                continue
            fields = {**_fields(name, mtime), **captured}
            target = _destination(rule, fields, rules["into"])
            previous = claimed.get(target.lower())
            if previous:
                rows.append({"verdict": "collision", "source": name, "destination": target, "rule": rule["name"],
                             "why": f"{previous} is already filed there by this plan", "bytes": size})
            elif os.path.exists(os.path.join(destination_root, *target.split("/"))):
                rows.append({"verdict": "collision", "source": name, "destination": target, "rule": rule["name"],
                             "why": "a file is already there on disk", "bytes": size})
            else:
                claimed[target.lower()] = name
                rows.append({"verdict": "file", "source": name, "destination": target, "rule": rule["name"],
                             "why": "", "bytes": size})
            break
        else:
            rows.append({"verdict": "unmatched", "source": name, "destination": "", "rule": "", "bytes": size,
                         "why": "no rule claims this name"})

    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    return {"version": R.VERSION, "heap": textio.norm_path(heap), "dest": textio.norm_path(destination_root),
            "into": rules["into"], "rules_sha256": R.sha256(rules), "fingerprint": fingerprint(heap),
            "counts": counts, "rows": rows}


def review_md(plan: dict) -> str:
    """The plan as a page a person reads before deciding. The rows a human argues with live here, not in chat."""
    counts = plan["counts"]
    lines = [f"# Sort plan — {plan['heap']}", "",
             f"* destination: `{plan['dest']}`, under `{plan['into']}/`",
             f"* rules: `{plan['rules_sha256'][:12]}`",
             f"* heap: {plan['fingerprint']['files']} files, `{plan['fingerprint']['sha256'][:12]}`",
             "", "| verdict | count |", "| --- | --- |"]
    lines += [f"| {v} | {counts[v]} |" for v in VERDICTS]
    lines += ["", "Nothing has been copied. `ad-sort apply --plan <this plan's json>` is the command that does that, "
                  "and it is a person's to run.", ""]
    for verdict in VERDICTS:
        chosen = [r for r in plan["rows"] if r["verdict"] == verdict]
        if not chosen:
            continue
        lines += [f"## {verdict} ({len(chosen)})", "", "| source | destination | rule | why |", "| --- | --- | --- | --- |"]
        lines += [f"| `{r['source']}` | `{r['destination']}` | {r['rule']} | {r['why']} |" for r in chosen]
        lines.append("")
    return "\n".join(lines)
