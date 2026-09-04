"""`ad-graph guard` — refuse a diff that touches code tests do not cover, or a graph nobody approved.

The protection this implements ("an agent must not change code no test covers") has to be a command
that says no. A rule in a SKILL.md is a sentence a model can talk itself past; a non-zero exit is
not. So every code-changing skill runs this before it commits, and `--install-hook` puts the same
check in `pre-commit` so the protection survives a skill being skipped.

Nothing here writes to a source or test file. The only paths it may write are the approval record
under `.agent/graph/` (for a human's `--allow`) and `.git/hooks/pre-commit` (for `--install-hook`).
"""
from __future__ import annotations
import os
import re
import sys
from typing import Any

from .approval import SNAPSHOT_NAME, drifted_nodes, get_git_user_name, now_iso
from .model import Graph, Node
from .query import load_graph
from .. import config
from .. import proc
from .. import textio

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HOOK_MARKER = "# written by `ad-graph guard --install-hook` -- safe to delete"

# exit codes: the caller reads these, not the prose
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NO_DATA = 3


class GuardError(Exception):
    def __init__(self, msg: str, hint: str = "", exit_code: int = EXIT_NO_DATA) -> None:
        super().__init__(msg)
        self.hint = hint
        self.exit_code = exit_code


# ------------------------------------------------------------------------------------ the diff


def _git(root: str, args: list[str]) -> tuple[int, str]:
    rc, out, _err, _el = proc.run(["git", *args], cwd=root, timeout=30)
    return rc, out


def _parse_unified(diff_text: str) -> dict[str, dict[str, Any]]:
    """{relpath: {new_lines, old_lines, old_path}} from `git diff -U0` output."""
    files: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            cur = None
            continue
        if line.startswith("--- "):
            old = line[4:].strip()
            pending_old = None if old == "/dev/null" else old[2:] if old.startswith(("a/", "b/")) else old
            files.setdefault("__pending__", {})["old_path"] = pending_old
            continue
        if line.startswith("+++ "):
            new = line[4:].strip()
            if new == "/dev/null":
                # a delete: keep it under its old path so the node still resolves
                rel = files.get("__pending__", {}).get("old_path")
            else:
                rel = new[2:] if new.startswith(("a/", "b/")) else new
            pending = files.pop("__pending__", {})
            if not rel:
                cur = None
                continue
            rel = rel.replace("\\", "/")
            cur = files.setdefault(rel, {"new_lines": set(), "old_lines": set(), "old_path": None})
            old_path = pending.get("old_path")
            if old_path and old_path.replace("\\", "/") != rel:
                cur["old_path"] = old_path.replace("\\", "/")
            continue
        if cur is None:
            continue
        m = HUNK.match(line)
        if not m:
            continue
        old_start, old_count, new_start, new_count = (
            int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1),
        )
        cur["new_lines"].update(range(new_start, new_start + new_count))
        cur["old_lines"].update(range(old_start, old_start + old_count))
    files.pop("__pending__", None)
    return files


def _ignored(rel: str) -> bool:
    """`.agent/` is the agent's own workspace (AGENTS.md rule 12), not source under review.

    Without this the guard reads the graph and coverage files it just wrote as an uncovered change
    and refuses itself.
    """
    parts = rel.split("/")
    return ".agent" in parts or ".git" in parts or "__pycache__" in parts


def collect_diff(root: str, mode: str = "worktree", ref: str | None = None) -> dict[str, dict[str, Any]]:
    """Changed lines per file. `worktree` includes untracked files, which is where new code arrives."""
    rc, _ = _git(root, ["rev-parse", "--git-dir"])
    if rc != 0:
        raise GuardError("not a git repository", "run `ad-graph guard` inside a git checkout", EXIT_USAGE)

    if mode == "staged":
        args = ["diff", "-U0", "--cached", "HEAD"]
    elif mode == "ref":
        if not ref:
            raise GuardError("--diff needs a git ref", "e.g. `--diff main`", EXIT_USAGE)
        args = ["diff", "-U0", ref]
    else:
        args = ["diff", "-U0", "HEAD"]

    rc, out = _git(root, args)
    if rc != 0:
        # a repository with no commits yet has no HEAD to diff against
        rc2, _ = _git(root, ["rev-parse", "--verify", "HEAD"])
        if rc2 != 0:
            out = ""
        else:
            raise GuardError(f"git {' '.join(args)} failed", "check the ref exists", EXIT_USAGE)

    files = _parse_unified(out)

    if mode == "worktree":
        rc, out = _git(root, ["ls-files", "--others", "--exclude-standard"])
        if rc == 0:
            for line in out.splitlines():
                rel = line.strip().replace("\\", "/")
                if not rel:
                    continue
                path = os.path.join(root, rel.replace("/", os.sep))
                try:
                    n = len(textio.read_text(path).splitlines())
                except Exception:
                    continue
                files.setdefault(rel, {"new_lines": set(), "old_lines": set(), "old_path": None})
                files[rel]["new_lines"].update(range(1, n + 1))

    return {rel: info for rel, info in files.items() if not _ignored(rel)}


# ------------------------------------------------------------------------------- node mapping


def _is_test_path(rel: str) -> bool:
    base = os.path.basename(rel)
    return base.startswith("test_") or base.endswith("_test.py") or "tests" in rel.split("/")[:-1]


def _nodes_in_file(graph: Graph, rel: str) -> list[Node]:
    return sorted(
        (n for n in graph.nodes.values() if n.path == rel),
        key=lambda n: (n.line_start, -n.line_end),
    )


def _node_for_line(nodes: list[Node], rel: str, line: int) -> str:
    """The innermost symbol containing `line`, else the file node, else the path itself."""
    best: Node | None = None
    for n in nodes:
        if n.kind == "file":
            best = best or n
            continue
        if n.line_start <= line <= n.line_end:
            if best is None or best.kind == "file" or n.line_start >= best.line_start:
                best = n
    return best.id if best else rel


# ------------------------------------------------------------------------------------- the run


def _coverage_of(graph: Graph, node_id: str) -> dict[str, Any]:
    return ((graph.coverage or {}).get("nodes") or {}).get(node_id) or {}


def _approval_state(
    root: str, graph_dir_abs: str, graph: Graph, meta: dict[str, Any], touched_files: set[str]
) -> tuple[str, dict[str, Any], set[str]]:
    """`missing` | `stale` | `current`, the approval record, and the drift the diff does not explain.

    Editing a file is supposed to move its own nodes -- judging staleness on the graph sha alone
    would make the guard refuse every edit it exists to check. Drift is explained when it lands in a
    file the diff touches, and stale when it lands anywhere else. Whole files rather than node ids,
    because a deleted symbol has no node left to match against.
    """
    approval_path = os.path.join(graph_dir_abs, "approval.json")
    if not os.path.isfile(approval_path):
        return "missing", {}, set()
    try:
        record = textio.read_json(approval_path, "approval.json")
    except Exception:
        return "missing", {}, set()

    snapshot_path = os.path.join(graph_dir_abs, SNAPSHOT_NAME)
    if not os.path.isfile(snapshot_path):
        # nothing to compare against: fall back to the whole-graph sha
        return ("current" if record.get("graph_sha256") == meta.get("sha256") else "stale"), record, set()

    try:
        snapshot = textio.read_json(snapshot_path, SNAPSHOT_NAME)
    except Exception:
        return "stale", record, set()

    unexplained = {
        nid for nid in drifted_nodes(graph, snapshot)
        if nid.split("::", 1)[0].replace("\\", "/") not in touched_files
    }
    return ("stale" if unexplained else "current"), record, unexplained


def _test_protection(graph: Graph, graph_dir_abs: str) -> list[dict[str, Any]]:
    """Tests removed, renamed away, or hollowed out since the approval."""
    snapshot_path = os.path.join(graph_dir_abs, SNAPSHOT_NAME)
    if not os.path.isfile(snapshot_path):
        return []
    try:
        snapshot = textio.read_json(snapshot_path, SNAPSHOT_NAME)
    except Exception:
        return []

    hint = "never remove or weaken a test to pass the guard"
    rows: list[dict[str, Any]] = []
    for nid, entry in sorted(snapshot.items()):
        if not isinstance(entry, dict) or entry.get("kind") != "test":
            continue
        node = graph.nodes.get(nid)
        if node is None:
            rows.append({
                "node": nid, "where": nid, "changed_lines": 0, "covered": "unknown",
                "coverage_pct": "", "verdict": "refused",
                "hint": f"{hint}: `{nid}` was deleted or renamed",
            })
        elif node.loc < int(entry.get("loc") or 0):
            rows.append({
                "node": nid, "where": node.where, "changed_lines": 0, "covered": "unknown",
                "coverage_pct": "", "verdict": "refused",
                "hint": f"{hint}: `{nid}` shrank from {entry['loc']} to {node.loc} lines",
            })
    return rows


def run_guard(
    root: str = ".",
    graph_dir: str = ".agent/graph",
    *,
    mode: str = "worktree",
    ref: str | None = None,
    tests_only: bool = False,
    min_coverage: float | None = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    root = os.path.abspath(root)
    graph_dir_abs = graph_dir if os.path.isabs(graph_dir) else os.path.join(root, graph_dir)
    graph, meta = load_graph(root, graph_dir=graph_dir)

    explicit_threshold = min_coverage is not None
    threshold = (min_coverage if explicit_threshold else config.min_coverage(cfg)) * 100.0
    has_coverage = bool((graph.coverage or {}).get("nodes"))

    files = collect_diff(root, mode=mode, ref=ref)
    if not files:
        return {
            "ok": True, "approved": "current", "refused": 0, "rows": [],
            "mode": mode, "coverage": "present" if has_coverage else "absent", "empty_diff": True,
        }

    allowed = set()
    rows: list[dict[str, Any]] = []
    per_node_lines: dict[str, set[int]] = {}
    node_file: dict[str, str] = {}

    for rel, info in sorted(files.items()):
        nodes = _nodes_in_file(graph, rel)
        lines = sorted(info["new_lines"]) or sorted(info["old_lines"])
        if not lines:
            continue
        for line in lines:
            nid = _node_for_line(nodes, rel, line)
            per_node_lines.setdefault(nid, set()).add(line)
            node_file[nid] = rel

    touched_files = set(files)
    approved, record, unexplained = _approval_state(root, graph_dir_abs, graph, meta, touched_files)
    allowed = {a.get("node") for a in (record.get("allowed") or []) if isinstance(a, dict)}

    for nid in sorted(per_node_lines):
        rel = node_file[nid]
        changed = sorted(per_node_lines[nid])
        node = graph.nodes.get(nid)
        cov = _coverage_of(graph, nid)
        pct = cov.get("pct")
        is_test = (node.kind == "test" if node else False) or _is_test_path(rel)

        verdict, hint, covered = "ok", "", "unknown"
        if has_coverage and pct is not None:
            covered = "true" if pct >= threshold else "false"

        if tests_only and not is_test:
            verdict, hint = "refused", "--tests-only: this run may touch test files and nothing else"
        elif approved != "current":
            # the approval gate outranks every exemption below it, including the one for test files:
            # an unapproved graph means nobody has read what this code does
            verdict = "refused"
            hint = (
                "run codebase-map and have a human run ad-graph approve"
                if approved == "missing"
                else "the graph moved outside your diff: rebuild, re-read, and have a human re-approve"
            )
        elif nid in allowed:
            verdict, hint = "ok", "human override recorded in approval.json"
        elif is_test:
            verdict, hint = "ok", "test file: exempt so test-cover can add coverage first"
        elif covered != "true":
            verdict = "refused"
            hint = (
                f"run test-cover for {nid} first"
                if has_coverage else
                "no coverage data: run `ad-test coverage`, then test-cover for this node"
            )
        else:
            missing = set(cov.get("missing") or [])
            unrun = sorted(set(changed) & missing)
            if unrun and not explicit_threshold:
                verdict = "refused"
                hint = f"the lines you changed have never run under a test: {unrun[:5]}"

        rows.append({
            "node": nid,
            "where": node.where if node else f"{rel}:{changed[0]}",
            "changed_lines": len(changed),
            "covered": covered,
            "coverage_pct": "" if pct is None else pct,
            "verdict": verdict,
            "hint": hint,
        })

    # independent of the approval state: weakening a test is refused whatever else is true
    rows.extend(_test_protection(graph, graph_dir_abs))

    refused = sum(1 for r in rows if r["verdict"] == "refused")
    return {
        "ok": refused == 0,
        "approved": approved,
        "refused": refused,
        "rows": rows,
        "mode": mode,
        "coverage": "present" if has_coverage else "absent",
        "min_coverage": threshold / 100.0,
        "unexplained_drift": sorted(unexplained)[:10],
        "empty_diff": False,
    }


# ------------------------------------------------------------------------------------- --allow


def allow_node(root: str, graph_dir: str, nodes: list[str], *, input_fn=None) -> dict[str, Any]:
    """Record a human's exemption. Same terminal requirement as `ad-graph approve`, same reason."""
    if input_fn is None and not (sys.stdin.isatty() and sys.stdout.isatty()):
        return {
            "ok": False, "exit_code": EXIT_NO_DATA,
            "error": "--allow must be run interactively in a terminal",
            "hint": "an override is a human decision; run it yourself from a terminal",
        }

    root = os.path.abspath(root)
    graph_dir_abs = graph_dir if os.path.isabs(graph_dir) else os.path.join(root, graph_dir)
    approval_path = os.path.join(graph_dir_abs, "approval.json")
    if not os.path.isfile(approval_path):
        return {
            "ok": False, "exit_code": EXIT_NO_DATA,
            "error": "no approval to attach an override to",
            "hint": "run ad-graph approve first",
        }

    record = textio.read_json(approval_path, "approval.json")
    prompt = f"Allow edits to {', '.join(nodes)} without test coverage? [y/N]: "
    answer = (input_fn(prompt) if input_fn else input(prompt)).strip().lower()
    if answer not in ("y", "yes"):
        return {"ok": False, "exit_code": EXIT_OK, "cancelled": True,
                "error": "override cancelled", "hint": "nothing was recorded"}

    who, when = get_git_user_name(), now_iso()
    existing = record.get("allowed") or []
    known = {a.get("node") for a in existing if isinstance(a, dict)}
    for nid in nodes:
        if nid not in known:
            existing.append({"node": nid, "by": who, "at": when})
    record["allowed"] = existing
    textio.write_json(approval_path, record)
    return {"ok": True, "exit_code": EXIT_OK, "allowed": nodes, "by": who, "at": when}


# -------------------------------------------------------------------------------- the git hook

HOOK_BODY = '''#!{interpreter}
{marker}
"""pre-commit: refuse a commit the code graph guard rejects."""
import subprocess
import sys

p = subprocess.run([sys.executable, "-m", "agentdata.cli_graph", "guard", "--staged"])
if p.returncode != 0:
    sys.stderr.write("\\nad-graph guard refused this commit. Fix the rows above, or --no-verify to skip.\\n")
sys.exit(p.returncode)
'''


def _hooks_dir(root: str) -> str:
    rc, out = _git(root, ["rev-parse", "--git-path", "hooks"])
    if rc != 0:
        raise GuardError("not a git repository", "run inside a git checkout", EXIT_USAGE)
    rel = out.strip()
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def install_hook(root: str = ".") -> dict[str, Any]:
    root = os.path.abspath(root)
    hooks = _hooks_dir(root)
    path = os.path.join(hooks, "pre-commit")
    if os.path.exists(path):
        existing = textio.read_text(path)
        if HOOK_MARKER not in existing:
            return {
                "ok": False, "exit_code": EXIT_USAGE, "path": path.replace("\\", "/"),
                "error": "a pre-commit hook already exists",
                "hint": "inspect it and chain `ad-graph guard --staged` in yourself; this command will not overwrite it",
            }
    os.makedirs(hooks, exist_ok=True)
    # a Python hook rather than a shell one, so the same file works under Git Bash, cmd and a real
    # shell; the shebang names this interpreter by absolute path because `env python` on a Windows
    # box frequently resolves to nothing at all
    textio.write_text(path, HOOK_BODY.format(
        interpreter=sys.executable.replace("\\", "/"), marker=HOOK_MARKER,
    ))
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    return {"ok": True, "exit_code": EXIT_OK, "path": path.replace("\\", "/"), "installed": True}


def uninstall_hook(root: str = ".") -> dict[str, Any]:
    root = os.path.abspath(root)
    path = os.path.join(_hooks_dir(root), "pre-commit")
    if not os.path.exists(path):
        return {"ok": True, "exit_code": EXIT_OK, "path": path.replace("\\", "/"), "removed": False}
    if HOOK_MARKER not in textio.read_text(path):
        return {
            "ok": False, "exit_code": EXIT_USAGE, "path": path.replace("\\", "/"),
            "error": "this pre-commit hook was not written by ad-graph",
            "hint": "remove it yourself if you meant to",
        }
    os.remove(path)
    return {"ok": True, "exit_code": EXIT_OK, "path": path.replace("\\", "/"), "removed": True}
