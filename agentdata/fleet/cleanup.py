"""The cleanup guide's server side: every dirty checkout, newest first, each with one decision.

The map's *clean up* opens a guide in a window of its own that walks the operator through the dirty
working trees one at a time (`static/tidy.js`). This module is what it asks: `plans()` surveys every
registered checkout (`fleet/tidy.py`), keeps the dirty ones, finds where their changed files
overlap -- another dirty checkout of the same project, or one of the checkout's own unmerged
branches -- and attaches the recommendation; `decide()` applies the one option the operator pressed.

Two rules of the fleet bend here, on purpose and only this far, because the operator asked for this:

* **The fleet writes in a checkout.** Only on a press, only `commit`, `branch` or `stash` (nothing
  that loses work), never in `.agent/` (the agent's, and `ad-state`'s), and never in a tree whose
  agent is running a turn: that agent is editing the very files, so the press is refused
  `agent_busy` until its turn ends.
* **Something the map opens changes something.** The map itself stays read-only; the guide is its
  own page, and every write it makes is one press on one decision it showed first.

Every decision is appended to `<fleet dir>/cleanup.jsonl` with what it did and how to undo it,
because a commit or a stash made from a page is exactly the kind of thing somebody asks about
tomorrow.
"""
from __future__ import annotations

import json
import os
import time

from .. import textio
from . import tidy as T
from .registry import Registry, RegistryError, fleet_dir

JOURNAL = "cleanup.jsonl"


class CleanupError(Exception):
    def __init__(self, code: str, msg: str, hint: str = "", extra: dict | None = None):
        super().__init__(msg)
        self.code, self.msg, self.hint, self.extra = code, msg, hint, extra or {}


def _busy(name: str) -> dict:
    from . import supervisor

    lock = supervisor.live(name)
    if not lock:
        return {}
    kind = "console" if lock.get("kind") == "console" else ("adopted" if lock.get("external") else "turn")
    return {"kind": kind, "pid": int(lock.get("pid") or 0)}


def _repos(names=None) -> list:
    try:
        repos = Registry().sorted()
    except (RegistryError, OSError):
        return []
    if names:
        wanted = set(names)
        repos = [r for r in repos if r.name in wanted]
    return [r for r in repos if os.path.isdir(r.path)]


def plans(names=None, *, now: float | None = None) -> dict:
    """`{ok, trees, clean, unreadable}`: one entry per dirty checkout, the most recent first.

    The overlaps are computed across the whole registry before any name filter is applied, so the
    guide opened on one checkout still knows that its files also change in a sibling worktree.
    """
    now = time.time() if now is None else now
    surveys, clean, unreadable = {}, [], []
    every = _repos()
    for repo in every:
        try:
            s = T.survey(repo.path, now=now)
        except Exception as e:                                # noqa: BLE001 - one bad tree is one row
            unreadable.append({"repo": repo.name, "why": str(getattr(e, "error", e))[:200]})
            continue
        s.update(repo=repo.name, project=repo.project)
        if s["dirty"]:
            surveys[repo.name] = s
        else:
            clean.append(repo.name)

    trees = []
    for name, s in surveys.items():
        if names and name not in names:
            continue
        siblings = [dict(o, where=f"checkout {o['repo']}") for n, o in surveys.items()
                    if n != name and o["project"] == s["project"]]
        decision = T.recommend(s, siblings)
        busy = _busy(name)
        if busy:
            decision = dict(decision, recommended="skip",
                            why=f"{name}'s agent is running ({busy['kind']}): it is editing these files. "
                                f"Come back when its turn ends, or stop it first")
        trees.append({**s, **decision, "busy": busy, "message": T.message(s)})
    trees.sort(key=lambda t: (-int(t.get("recent_at") or 0), t["repo"]))
    for i, t in enumerate(trees, 1):
        t["step"] = i
    return {"ok": True, "trees": trees, "total": len(trees), "clean": sorted(clean),
            "unreadable": unreadable,
            "says": (f"{len(trees)} dirty tree{'s' if len(trees) != 1 else ''}, the most recent first"
                     if trees else "every working tree is clean")}


def _journal(row: dict) -> None:
    try:
        path = os.path.join(fleet_dir(), JOURNAL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        from ..log import debug_exc

        debug_exc("cleanup journal")


def decide(name: str, body: dict) -> dict:
    """Apply one decision to one checkout, then answer with what it did and that tree's next state."""
    repos = {r.name: r for r in _repos()}
    repo = repos.get(str(name or ""))
    if repo is None:
        raise CleanupError("no_repo", f"{name!r} is not a registered checkout", "`ad-fleet repo add` it first")
    busy = _busy(repo.name)
    if busy:
        raise CleanupError("agent_busy", f"{repo.name}'s agent is running ({busy['kind']})",
                           "it is editing these files: wait for its turn to end, or stop it first")
    choice = str(body.get("choice") or "")
    try:
        done = T.apply(repo.path, str(body.get("plan_id") or ""), choice,
                       msg=str(body.get("message") or ""), branch=str(body.get("branch") or ""))
    except T.TidyError as e:
        raise CleanupError(e.code, e.error, e.hint) from None
    _journal({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "repo": repo.name, "path": textio.norm_path(repo.path),
              **{k: v for k, v in done.items() if k != "ok"}})
    return {"ok": True, "repo": repo.name, "done": done, **plans([repo.name])}
