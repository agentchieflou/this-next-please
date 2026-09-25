r"""Check an agent PR's files against the lanes in .github/agent-lanes.json, before anyone reviews it.

    python .github/scripts/agent_pr_check.py --base origin/main [--lane N]... [--allow N]...

The diff is `git merge-base <base> HEAD`..HEAD, so work that reached the base after the branch point (and was merged
into the branch) is never blamed on the branch. Each touched file is printed as a `lane | kind | file` row (`-` for a
file no lane owns); pyproject.toml is split by the dotted keys the lanes name, compared with tomllib.

Violations (exit 1):
  - a `frozen` or `release-only` lane touched;
  - with `--lane` given, an `exclusive` or `sequenced` lane touched that is not listed.
`--allow <lane>` turns that lane's violations into `allowed:` lines; the PR links the operator's approving comment.
Warnings never fail: an `append-rows` file with deleted lines, two `exclusive` lanes, an uncommitted tree.
Exit 2, with a hint on stderr, when the check cannot run.

The rules are a list of functions `(ctx) -> list[Finding]` (RULES), so a new rule never touches the diff code.
Every git call goes through agentdata.proc.run; nothing here reaches the network.
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from typing import Any, Callable

# agentdata comes from this script's own checkout, whatever repository the check is pointed at.
_SELF_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SELF_ROOT not in sys.path:
    sys.path.insert(0, _SELF_ROOT)

from agentdata import proc  # noqa: E402

LANES_REL = ".github/agent-lanes.json"
PYPROJECT = "pyproject.toml"
SKIN_KEY = "skin:<name>"
SKIN_SOURCE = "agentdata/fleet/static/ink/skins/*.js"
KINDS = ("frozen", "release-only", "exclusive", "sequenced", "append-rows")
_MISSING = object()


class CannotRun(Exception):
    def __init__(self, msg: str, hint: str = "") -> None:
        super().__init__(msg)
        self.hint = hint


@dataclass
class Lane:
    name: str
    kind: str
    paths: list[str]
    toml: list[str]
    planned: list[str]


@dataclass
class Finding:
    level: str          # "violation" or "warning"
    lane: str
    message: str


@dataclass
class Context:
    base: str
    merge_base: str
    lanes: dict[str, Lane]
    rows: list[tuple[str, str, str]]                    # (lane, kind, file label)
    touched: dict[str, list[str]]                       # lane -> file labels, in diff order
    declared: set[str]
    deletions: dict[str, int] = field(default_factory=dict)   # append-rows file -> deleted lines


# ------------------------------------------------------------------------------------------------ git


def git(root: str, args: list[str]) -> tuple[int, str, str]:
    code, out, err, _elapsed = proc.run(["git", *args], cwd=root, timeout=60)
    return code, out, err


def toplevel(cwd: str) -> str:
    code, out, err = git(cwd, ["rev-parse", "--show-toplevel"])
    if code != 0:
        raise CannotRun(f"not a git checkout: {cwd}", "run the check from inside the branch's checkout")
    return out.strip()


def merge_base(root: str, base: str) -> str:
    code, _out, _err = git(root, ["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"])
    if code != 0:
        raise CannotRun(f"unknown base: {base}", "run `git fetch origin` and try again")
    code, out, err = git(root, ["merge-base", base, "HEAD"])
    if code != 0:
        raise CannotRun(f"no merge base between {base} and HEAD: {err.strip()}", "run `git fetch origin` and try again")
    return out.strip()


def changed_paths(root: str, mb: str) -> list[str]:
    """Every path the branch touched since the merge base: both sides of a rename, the new side of a copy."""
    code, out, err = git(root, ["diff", "--name-status", "-M", "-z", mb, "HEAD"])
    if code != 0:
        raise CannotRun(f"git diff failed: {err.strip()}")
    parts = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i]
        if status[0] in "RC":
            old, new = parts[i + 1], parts[i + 2]
            paths += [old, new] if status[0] == "R" else [new]
            i += 3
        else:
            paths.append(parts[i + 1])
            i += 2
    seen: set[str] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def show(root: str, rev: str, path: str) -> str | None:
    code, out, _err = git(root, ["show", f"{rev}:{path}"])
    return out if code == 0 else None


def tracked(root: str) -> list[str]:
    code, out, err = git(root, ["ls-files", "-z"])
    if code != 0:
        raise CannotRun(f"git ls-files failed: {err.strip()}")
    return [p for p in out.split("\0") if p]


# ---------------------------------------------------------------------------------------------- lanes


def matches(path: str, globs: list[str]) -> bool:
    """fnmatchcase on the posix path: `*` crosses `/`, so `**` behaves as `*`."""
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def skin_names(paths: list[str]) -> list[str]:
    stems = {p.rsplit("/", 1)[-1][:-3] for p in paths if fnmatch.fnmatchcase(p, SKIN_SOURCE)}
    return sorted(s for s in stems if s and "/" not in s)


def load_lanes(root: str, extra_paths: list[str] | None = None) -> dict[str, Lane]:
    """The lanes file of the checked repository, with `skin:<name>` expanded to one lane per skin module."""
    path = os.path.join(root, *LANES_REL.split("/"))
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise CannotRun(f"no {LANES_REL} in {root}", "run the check from a checkout of this repository") from None
    except json.JSONDecodeError as e:
        raise CannotRun(f"{LANES_REL} is not JSON: {e}") from None
    return expand(raw, tracked(root) + list(extra_paths or []))


def expand(raw: dict[str, Any], paths: list[str]) -> dict[str, Lane]:
    if raw.get("version") != 1:
        raise CannotRun(f"{LANES_REL}: unsupported version {raw.get('version')!r}")
    lanes: dict[str, Lane] = {}
    for name, spec in (raw.get("lanes") or {}).items():
        if spec.get("kind") not in KINDS:
            raise CannotRun(f"{LANES_REL}: lane {name} has unknown kind {spec.get('kind')!r}")
        def lane(n: str, sub: Callable[[str], str] = lambda s: s) -> Lane:
            return Lane(n, spec["kind"], [sub(g) for g in spec.get("paths", [])], list(spec.get("toml", [])),
                        [sub(g) for g in spec.get("planned", [])])
        if name == SKIN_KEY:
            for skin in skin_names(paths):
                lanes[f"skin:{skin}"] = lane(f"skin:{skin}", lambda s, k=skin: s.replace("<name>", k))
        else:
            lanes[name] = lane(name)
    return lanes


def check_map(raw: dict[str, Any], paths: list[str], pyproject: dict[str, Any]) -> list[str]:
    """Problems with the lanes map against a checkout: a glob or toml key, outside `planned`, that matches nothing.

    `skin:<name>` is checked across all skins: each of its globs must match for at least one skin."""
    problems: list[str] = []
    skins = skin_names(paths)
    if SKIN_KEY in (raw.get("lanes") or {}) and not skins:
        problems.append(f"{SKIN_KEY}: no {SKIN_SOURCE} to expand to")
    for name, spec in (raw.get("lanes") or {}).items():
        for g in spec.get("paths", []):
            candidates = [g.replace("<name>", s) for s in skins] if name == SKIN_KEY else [g]
            if not any(fnmatch.fnmatchcase(p, c) for c in candidates for p in paths):
                problems.append(f"{name}: glob {g} matches no tracked file")
        for key in spec.get("toml", []):
            if lookup(pyproject, key) is _MISSING:
                problems.append(f"{name}: toml key {key} is not in {PYPROJECT}")
        for g in spec.get("planned", []):
            if any(fnmatch.fnmatchcase(p, g) for p in paths):
                problems.append(f"{name}: planned glob {g} now matches a file; move it to paths")
    return problems


# ---------------------------------------------------------------------------------------------- toml


def lookup(doc: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return _MISSING
        doc = doc[part]
    return doc


def drop(doc: dict[str, Any], dotted: str) -> None:
    *parents, last = dotted.split(".")
    for part in parents:
        doc = doc.get(part) if isinstance(doc, dict) else None
        if not isinstance(doc, dict):
            return
    if isinstance(doc, dict):
        doc.pop(last, None)


def parse_toml(text: str | None) -> Any:
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {"<unparseable>": text}


def toml_rows(root: str, mb: str, lanes: dict[str, Lane]) -> tuple[list[str], bool]:
    """(lanes whose toml keys changed, whether anything outside those keys changed)."""
    old, new = parse_toml(show(root, mb, PYPROJECT)), parse_toml(show(root, "HEAD", PYPROJECT))
    hit: list[str] = []
    keys: list[str] = []
    for lane in lanes.values():
        for key in lane.toml:
            keys.append(key)
            if lookup(old, key) != lookup(new, key) and lane.name not in hit:
                hit.append(lane.name)
    rest_old, rest_new = copy.deepcopy(old), copy.deepcopy(new)
    for key in keys:
        drop(rest_old, key)
        drop(rest_new, key)
    return hit, rest_old != rest_new


# ---------------------------------------------------------------------------------------------- context


def build_context(root: str, base: str, declared: list[str], allow: list[str]) -> Context:
    mb = merge_base(root, base)
    paths = changed_paths(root, mb)
    lanes = load_lanes(root, paths)
    unknown = sorted({*declared, *allow} - set(lanes))
    if unknown:
        raise CannotRun("unknown lane: " + ", ".join(unknown), "lanes: " + ", ".join(lanes))

    rows: list[tuple[str, str, str]] = []
    touched: dict[str, list[str]] = {}

    def add(lane: str, kind: str, label: str) -> None:
        rows.append((lane, kind, label))
        if lane != "-":
            touched.setdefault(lane, []).append(label)

    for path in paths:
        owners = [lane for lane in lanes.values() if matches(path, lane.paths)]
        if path == PYPROJECT:
            hit, rest = toml_rows(root, mb, lanes)
            for name in hit:
                add(name, lanes[name].kind, f"{PYPROJECT} [{', '.join(lanes[name].toml)}]")
            if rest and not owners:
                add("-", "-", PYPROJECT)
        elif not owners:
            add("-", "-", path)
        for lane in owners:
            add(lane.name, lane.kind, path)

    ctx = Context(base, mb, lanes, rows, touched, set(declared))
    for name, files in touched.items():
        if lanes[name].kind != "append-rows":
            continue
        for f in files:
            code, out, _err = git(root, ["diff", "--numstat", mb, "HEAD", "--", f])
            first = out.split("\t", 2) if code == 0 and out.strip() else []
            if len(first) == 3 and first[1].isdigit():
                ctx.deletions[f] = int(first[1])
    return ctx


# ---------------------------------------------------------------------------------------------- rules


def rule_frozen(ctx: Context) -> list[Finding]:
    out = []
    for name, files in ctx.touched.items():
        kind = ctx.lanes[name].kind
        if kind == "frozen":
            out.append(Finding("violation", name, f"frozen lane touched ({', '.join(files)}): link the operator's "
                                                  f"approving comment and pass --allow {name}"))
        elif kind == "release-only":
            out.append(Finding("violation", name, f"release-only lane touched ({', '.join(files)}): only the "
                                                  "release PR changes it"))
    return out


def rule_declared(ctx: Context) -> list[Finding]:
    if not ctx.declared:
        return []
    return [Finding("violation", name, f"{ctx.lanes[name].kind} lane touched but not declared with --lane "
                                       f"({', '.join(files)})")
            for name, files in ctx.touched.items()
            if ctx.lanes[name].kind in ("exclusive", "sequenced") and name not in ctx.declared]


def rule_append_rows(ctx: Context) -> list[Finding]:
    return [Finding("warning", name, f"{f} lost {ctx.deletions[f]} line(s): rewrite only your own rows")
            for name, files in ctx.touched.items() if ctx.lanes[name].kind == "append-rows"
            for f in files if ctx.deletions.get(f, 0) > 0]


def rule_two_exclusive(ctx: Context) -> list[Finding]:
    names = [n for n in ctx.touched if ctx.lanes[n].kind == "exclusive"]
    if len(names) < 2:
        return []
    return [Finding("warning", ",".join(names), f"{len(names)} exclusive lanes touched ({', '.join(names)}): "
                                                "each is one open PR at a time")]


RULES: list[Callable[[Context], list[Finding]]] = [rule_frozen, rule_declared, rule_append_rows, rule_two_exclusive]


# ---------------------------------------------------------------------------------------------- main


def dirty(root: str) -> bool:
    code, out, _err = git(root, ["status", "--porcelain", "--untracked-files=no"])
    return code == 0 and bool(out.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="the ref the PR merges into, e.g. origin/main")
    ap.add_argument("--lane", action="append", default=[], help="a lane this PR declares (repeatable)")
    ap.add_argument("--allow", action="append", default=[],
                    help="a lane the operator approved for this PR; its violations become `allowed:` lines")
    a = ap.parse_args(argv)

    try:
        root = toplevel(os.getcwd())
        ctx = build_context(root, a.base, a.lane, a.allow)
        is_dirty = dirty(root)
    except CannotRun as e:
        print(f"agent_pr_check: {e}", file=sys.stderr)
        if e.hint:
            print(f"hint: {e.hint}", file=sys.stderr)
        return 2
    except proc.ProcError as e:
        print(f"agent_pr_check: {e}", file=sys.stderr)
        print("hint: git must be on PATH", file=sys.stderr)
        return 2

    findings = [f for rule in RULES for f in rule(ctx)]
    allowed = [f for f in findings if f.level == "violation" and f.lane in a.allow]
    violations = [f for f in findings if f.level == "violation" and f.lane not in a.allow]
    warnings = [f for f in findings if f.level == "warning"]

    print(f"base: {a.base} (merge base {ctx.merge_base[:12]})")
    if not ctx.rows:
        print("no lanes touched")
    else:
        print("lane | kind | file")
        for lane, kind, label in ctx.rows:
            print(f"{lane} | {kind} | {label}")
    print(f"violations: {len(violations)}")
    for f in violations:
        print(f"  {f.lane}: {f.message}")
    for f in allowed:
        print(f"allowed: {f.lane}: {f.message}")
    for f in warnings:
        print(f"warning: {f.lane}: {f.message}")
    if is_dirty:
        print("warning: the working tree has uncommitted changes; only commits are checked")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
