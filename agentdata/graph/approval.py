"""`ad-graph approve` and `ad-graph status` — human-in-the-loop approval gate."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import os
import re
import subprocess
import sys
from typing import Any, Callable

from .model import Graph
from .query import get_changed, load_graph
from .. import state as S
from .. import textio


# the {node id: source sha} of the graph at the moment a human approved it. Kept beside approval.json
# rather than inside it so the approval record stays a short thing a human can read, and so "which nodes
# moved since approval" stays answerable after a rebuild -- `ad-graph changed` compares meta fingerprints
# against disk, which is 0 by construction the instant a rebuild finishes.
SNAPSHOT_NAME = "approved-nodes.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def node_shas(graph: Graph) -> dict[str, dict[str, Any]]:
    """{node id: {sha, loc, kind}}. `loc` and `kind` are what lets the guard notice a test that
    still exists but has been hollowed out."""
    return {
        nid: {"sha": n.sha, "loc": n.loc, "kind": n.kind}
        for nid, n in sorted(graph.nodes.items())
    }


def snapshot_sha(entry: Any) -> str:
    """The sha out of a snapshot entry, tolerating the flat {id: sha} form written by earlier runs."""
    if isinstance(entry, dict):
        return str(entry.get("sha", ""))
    return str(entry or "")


def drifted_nodes(graph: Graph, snapshot: dict[str, Any]) -> set[str]:
    """Nodes added, removed, or whose source changed since the snapshot was taken."""
    current = node_shas(graph)
    return {
        nid for nid in set(current) | set(snapshot)
        if snapshot_sha(current.get(nid)) != snapshot_sha(snapshot.get(nid))
    }


def drift_from_snapshot(graph: Graph, snapshot: dict[str, Any]) -> int:
    return len(drifted_nodes(graph, snapshot))


def get_git_user_name() -> str:
    try:
        p = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "human"


def check_approval_status(
    root: str = ".",
    graph_dir: str = ".agent/graph",
) -> dict[str, Any]:
    """Check whether a valid, fresh graph approval exists."""
    root = os.path.abspath(root)
    graph, meta = load_graph(root, graph_dir=graph_dir)

    graph_dir_abs = os.path.abspath(graph_dir) if os.path.isabs(graph_dir) else os.path.join(root, graph_dir)
    approval_file = os.path.join(graph_dir_abs, "approval.json")
    understanding_file = os.path.join(graph_dir_abs, "understanding.md")

    if not os.path.isfile(approval_file):
        return {
            "ok": True,
            "status": "none",
            "approved": False,
            "graph_sha256": meta.get("sha256", ""),
            "changed_nodes": 0,
            "approved_at": None,
            "approved_by": None,
        }

    try:
        app_data = textio.read_json(approval_file, "approval.json")
    except Exception:
        return {
            "ok": True,
            "status": "stale",
            "approved": False,
            "graph_sha256": meta.get("sha256", ""),
            "changed_nodes": 0,
            "approved_at": None,
            "approved_by": None,
        }

    cur_graph_sha = meta.get("sha256", "")
    app_graph_sha = app_data.get("graph_sha256", "")

    cur_und_sha = None
    if os.path.isfile(understanding_file):
        cur_und_sha = hashlib.sha256(textio.read_text(understanding_file).encode("utf-8")).hexdigest()

    app_und_sha = app_data.get("understanding_sha256", "")

    is_current = (cur_graph_sha == app_graph_sha) and (app_und_sha == cur_und_sha)
    changed_count = 0
    if not is_current:
        snapshot_file = os.path.join(graph_dir_abs, SNAPSHOT_NAME)
        if os.path.isfile(snapshot_file):
            try:
                changed_count = drift_from_snapshot(graph, textio.read_json(snapshot_file, SNAPSHOT_NAME))
            except Exception:
                changed_count = 0
        else:
            # an approval granted before the snapshot existed: fall back to disk drift
            try:
                changed_count = len(get_changed(graph, meta, root=root))
            except Exception:
                changed_count = 0

    return {
        "ok": True,
        "status": "current" if is_current else "stale",
        "approved": is_current,
        "graph_sha256": cur_graph_sha,
        "approved_graph_sha256": app_graph_sha,
        "understanding_sha256": cur_und_sha,
        "approved_understanding_sha256": app_und_sha,
        "changed_nodes": changed_count,
        "approved_at": app_data.get("approved_at"),
        "approved_by": app_data.get("approved_by"),
    }


def approve_graph(
    root: str = ".",
    graph_dir: str = ".agent/graph",
    *,
    input_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Interactively prompt human reviewer in terminal to approve the codebase understanding."""
    root = os.path.abspath(root)

    # Human-only check: stdin and stdout must both be a TTY
    if input_fn is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return {
                "ok": False,
                "exit_code": 3,
                "error": "ad-graph approve must be run interactively in a terminal",
                "hint": "run ad-graph approve directly from an interactive terminal (stdin/stdout must be a TTY)",
            }

    graph_dir_abs = os.path.abspath(graph_dir) if os.path.isabs(graph_dir) else os.path.join(root, graph_dir)
    understanding_file = os.path.join(graph_dir_abs, "understanding.md")
    if not os.path.isfile(understanding_file):
        return {
            "ok": False,
            "exit_code": 1,
            "error": "understanding.md not found",
            "hint": "run ad-graph explain first",
        }

    graph, meta = load_graph(root, graph_dir=graph_dir)
    graph_sha = meta.get("sha256", "")
    graph_sha8 = graph_sha[:8] if len(graph_sha) >= 8 else graph_sha

    # Extract section headings
    doc_content = textio.read_text(understanding_file)
    headings = re.findall(r"(?m)^##\s+(.+)$", doc_content)

    print(f"Codebase Understanding: {understanding_file}")
    print(f"Graph SHA256: {graph_sha}")
    print("Document Sections:")
    for h in headings:
        print(f"  • {h}")

    prompt_msg = f"Approve this understanding for graph {graph_sha8}? [y/N]: "
    if input_fn is not None:
        response = input_fn(prompt_msg)
    else:
        try:
            response = input(prompt_msg)
        except (EOFError, KeyboardInterrupt):
            response = "n"

    ans = response.strip().lower()
    if ans not in ("y", "yes"):
        return {
            "ok": False,
            "exit_code": 0,
            "error": "approval cancelled by user",
            "hint": "review understanding.md and re-run ad-graph approve when ready",
            "cancelled": True,
        }

    und_sha = hashlib.sha256(doc_content.encode("utf-8")).hexdigest()
    user = get_git_user_name()
    now = now_iso()

    app_data = {
        "graph_sha256": graph_sha,
        "understanding_sha256": und_sha,
        "approved_at": now,
        "approved_by": user,
    }
    approval_path = os.path.join(graph_dir_abs, "approval.json")
    textio.write_json(approval_path, app_data)
    textio.write_json(os.path.join(graph_dir_abs, SNAPSHOT_NAME), node_shas(graph))

    # Stamp state via agentdata.state (same path as ad-state set --tool graph_approved=...)
    state_path = os.path.join(root, ".agent", "state.json")
    if os.path.isfile(state_path):
        try:
            st = S.load(state_path)
            S.apply(st, {}, tools={"graph_approved": graph_sha8})
            S.save(st, state_path)
        except Exception:
            pass

    return {
        "ok": True,
        "exit_code": 0,
        "source": "ad-graph approve",
        "approved": True,
        "graph_sha256": graph_sha,
        "understanding_sha256": und_sha,
        "approved_at": now,
        "approved_by": user,
        "path": approval_path,
    }
