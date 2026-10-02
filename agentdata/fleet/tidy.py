"""Make a dirty working tree clean without losing anything: commit it, move it to a branch, or stash it.

One checkout at a time, and one decision at a time, because each is the operator's (the cleanup guide
on the map, `ad-git tidy`, or an agent asking through `ad-state ask`). This module surveys a tree,
recommends one option decisively, and applies the option it is told to -- and nothing it can do
loses work:

* **commit** -- the changes, on the branch the tree is on. Never on a protected branch (`main`,
  `master`, `develop`, the remote's HEAD) and never on a detached HEAD.
* **branch** -- the changes, on a new branch cut from HEAD and checked out (`git switch -c`), so a
  tree on `main` ends clean on `wip/...`, which is AGENTS.md rule 16's shape.
* **stash** -- the changes parked in a named stash, untracked files included: the tree is clean and
  `git stash pop` brings them back.
* **skip** -- nothing.

There is no discard, no reset of the working tree, no force and no hook bypass: a commit the
repository's own pre-commit hook refuses is reported with the hook's words and unstaged again,
never retried with `--no-verify`. `.agent/` is excluded from every operation -- it is the agent's,
and `ad-state` is its only writer.

Every apply names the survey it was decided on (`plan_id`, a hash of HEAD and the tree's status). A
tree that moved since -- an agent wrote a file, the operator committed in a terminal -- is refused
`changed` and surveyed again, so a decision is never applied to a tree it was not made about.

**The recommendation.** The operator asked for two preferences, applied in this order:

1. *The most recent branch first.* Dirty trees are worked through newest first (the later of the
   branch's last commit and the newest changed file), and the default home for a tree's changes is
   the branch it is already on, when that branch may take a commit.
2. *On a conflict, the least tech debt.* When the changed files are also changed somewhere else --
   another dirty checkout of the project, or an unmerged local branch -- the two homes are scored
   (`debt`): commits behind the default branch, days since the branch last moved, how much it
   already carries, and nothing at all on a protected branch. The home with less debt keeps the
   work (commit or branch); the other side's changes are stashed, which keeps them and costs
   nothing to undo. The score and its parts are shown, so the decision can be argued with.
"""
from __future__ import annotations

import hashlib
import os
import re
import time

from .. import proc, textio
from ..cli_git import PROTECTED, QUIET_ENV, READ_TIMEOUT_S, _git

CHOICES = ("commit", "branch", "stash", "skip")
EXCLUDE = ":(exclude).agent"
FILES_CAP = 200          # files listed per tree; the count is always exact
BRANCHES_CAP = 10        # unmerged local branches compared, most recent first
SPREAD_CAP = 500         # files read from one branch's diff
KEY = re.compile(r"[A-Za-z][A-Za-z0-9]+-\d+")
SLUG = re.compile(r"[^A-Za-z0-9._-]+")

# The weights of `debt`, in points. A protected branch is never a home for a commit at all, so its
# weight outranks everything else put together.
W_BEHIND, CAP_BEHIND = 1.0, 50
W_AGE, CAP_AGE = 0.5, 30
W_SPREAD, CAP_SPREAD = 0.1, 100
W_UNTRACKED = 2.0
W_PROTECTED = 100.0

_STATE = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "modified",
          "U": "conflicted", "?": "untracked"}


class TidyError(Exception):
    def __init__(self, code: str, error: str, hint: str = "", survey: dict | None = None):
        super().__init__(error)
        self.code, self.error, self.hint, self.survey = code, error, hint, survey or {}

    def to_dict(self) -> dict:
        out = {"ok": False, "refused": self.code, "error": self.error, "hint": self.hint}
        if self.survey:
            out["survey"] = self.survey
        return out


# ------------------------------------------------------------------------------------ reading


def _status(cwd: str) -> tuple[str, list[dict]]:
    """The raw porcelain (for the plan id) and one row per changed path outside `.agent/`."""
    # Not `_git`: it strips the output, and a status entry's first column is often a space.
    code, raw, err, _ = proc.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all",
                                  "--", ".", EXCLUDE], cwd=cwd, timeout=READ_TIMEOUT_S, env=dict(QUIET_ENV))
    raw, err = raw or "", (err or "").strip()
    if code != 0:
        raise TidyError("not_a_checkout", f"git status failed: {err or cwd}", "run it in a working tree")
    rows, parts, i = [], raw.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1                                   # the old name follows a rename or a copy
        code_ = "U" if ("U" in xy or xy in ("AA", "DD")) else ("?" if xy == "??" else (xy[1].strip() or xy[0]))
        rows.append({"path": textio.norm_path(path), "state": _STATE.get(code_, "modified")})
    return raw, rows


def _int(text: str) -> int:
    try:
        return int(str(text).strip() or 0)
    except ValueError:
        return 0


def _ref(cwd: str, ref: str) -> bool:
    return _git(cwd, "rev-parse", "--verify", "--quiet", ref)[0] == 0


def _default(cwd: str) -> tuple[str, str]:
    """`(ref, name)` of the branch work lands on: the remote's HEAD, else main or master."""
    code, head, _ = _git(cwd, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if code == 0 and head:
        return head, head.rsplit("/", 1)[-1]
    for ref in ("refs/remotes/origin/main", "refs/remotes/origin/master", "refs/heads/main", "refs/heads/master"):
        if _ref(cwd, ref):
            return ref, ref.rsplit("/", 1)[-1]
    return "", ""


def _files_between(cwd: str, base: str, tip: str) -> list[str]:
    if not base:
        return []
    code, out, _ = _git(cwd, "diff", "--name-only", f"{base}...{tip}")
    return [textio.norm_path(p) for p in out.splitlines() if p.strip()][:SPREAD_CAP] if code == 0 else []


def _mid_operation(cwd: str) -> str:
    code, git_dir, _ = _git(cwd, "rev-parse", "--git-dir")
    if code != 0:
        return ""
    git_dir = git_dir if os.path.isabs(git_dir) else os.path.join(cwd, git_dir)
    for marker, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"),
                         ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert")):
        if os.path.exists(os.path.join(git_dir, marker)):
            return what
    return ""


def survey(cwd: str, *, now: float | None = None, with_branches: bool = True) -> dict:
    """Everything a decision about this tree needs, read from git and nothing else."""
    now = time.time() if now is None else now
    raw, files = _status(cwd)
    code, branch, _ = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD")[1] if code == 0 else ""
    detached = branch == "HEAD"
    default_ref, default = _default(cwd)
    protected = sorted(set(PROTECTED) | ({default} if default else set()))
    committed = _int(_git(cwd, "log", "-1", "--format=%ct")[1]) if head else 0
    newest = 0.0
    for f in files:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(cwd, f["path"])))
        except OSError:
            pass
    behind = ahead = 0
    if default_ref and head and not detached and branch != default:
        behind = _int(_git(cwd, "rev-list", "--count", f"HEAD..{default_ref}")[1])
        ahead = _int(_git(cwd, "rev-list", "--count", f"{default_ref}..HEAD")[1])
    out = {
        "path": textio.norm_path(cwd), "branch": "" if detached else branch, "detached": detached,
        "head": head[:12], "default": default, "protected": (branch in protected) if not detached else False,
        "dirty": bool(files), "count": len(files), "files": files[:FILES_CAP],
        "conflicted": [f["path"] for f in files if f["state"] == "conflicted"],
        "mid_operation": _mid_operation(cwd),
        "committed_at": committed, "changed_at": int(newest), "recent_at": int(max(committed, newest)),
        "behind": behind, "ahead": ahead,
        "age_days": round(max(0.0, now - committed) / 86400.0, 1) if committed else 0.0,
        "carries": len(_files_between(cwd, default_ref, "HEAD")) if (default_ref and not detached
                                                                         and branch != default) else 0,
        "plan_id": hashlib.sha256((head + "\n" + raw).encode("utf-8", "replace")).hexdigest()[:12],
    }
    out["branches"] = _branches(cwd, default_ref, branch, now) if with_branches and default_ref else []
    return out


def _branches(cwd: str, default_ref: str, current: str, now: float) -> list[dict]:
    """Unmerged local branches other than the current one, most recently committed first."""
    code, listed, _ = _git(cwd, "for-each-ref", "--sort=-committerdate", "refs/heads",
                           "--format=%(refname:short)%09%(committerdate:unix)")
    if code != 0:
        return []
    _, unmerged, _ = _git(cwd, "branch", "--no-merged", default_ref, "--format=%(refname:short)")
    keep = {b.strip() for b in unmerged.splitlines() if b.strip()}
    out = []
    for line in listed.splitlines():
        name, _, when = line.partition("\t")
        if not name or name == current or name not in keep:
            continue
        files = _files_between(cwd, default_ref, f"refs/heads/{name}")
        behind = _int(_git(cwd, "rev-list", "--count", f"refs/heads/{name}..{default_ref}")[1])
        out.append({"branch": name, "committed_at": _int(when), "files": files, "behind": behind,
                    "age_days": round(max(0.0, now - _int(when)) / 86400.0, 1), "carries": len(files)})
        if len(out) >= BRANCHES_CAP:
            break
    return out


# ------------------------------------------------------------------------------ the decision


def debt(home: dict) -> dict:
    """How much tech debt landing work on `home` adds: `{score, parts}`, lower is better.

    `home` is a tree (`survey`) or a branch (`survey()["branches"]`): commits behind the default
    branch are a merge waiting to happen, days since it moved are a branch nobody is landing, files it
    already carries are a review that grows, and a branch name without a ticket key is work nobody can
    track. A protected branch or a detached HEAD is never a home for a commit.
    """
    parts = {
        "behind": round(min(int(home.get("behind") or 0), CAP_BEHIND) * W_BEHIND, 1),
        "age": round(min(float(home.get("age_days") or 0.0), CAP_AGE) * W_AGE, 1),
        "carries": round(min(int(home.get("carries") or 0), CAP_SPREAD) * W_SPREAD, 1),
        "untracked": W_UNTRACKED if not KEY.search(str(home.get("branch") or "")) else 0.0,
        "protected": W_PROTECTED if (home.get("protected") or home.get("detached")) else 0.0,
    }
    return {"score": round(sum(parts.values()), 1), "parts": parts}


def branch_name(s: dict, today: str | None = None) -> str:
    """A new branch for this tree's changes: `wip/<branch or ticket>-<date>`, never one that exists."""
    stem = SLUG.sub("-", s.get("branch") or "detached").strip("-.") or "work"
    return f"wip/{stem}-{today or time.strftime('%Y%m%d')}"


def message(s: dict) -> str:
    key = KEY.search(str(s.get("branch") or ""))
    return (f"chore: {key.group(0) + ' ' if key else ''}save {s.get('count', 0)} uncommitted "
            f"file{'s' if s.get('count') != 1 else ''} from the cleanup guide")


def recommend(s: dict, others: list[dict] | None = None) -> dict:
    """The options for this tree, the one to take, and why -- in words a person can argue with.

    `others` are the other homes the same files live in: other dirty checkouts of the project (their
    surveys, with `where`) and this checkout's own unmerged branches (added here). Each overlap names
    the files it shares with this tree.
    """
    mine = debt(s)
    may_commit = bool(s.get("branch")) and not s.get("protected") and not s.get("detached")
    options = []
    if may_commit:
        options.append({"choice": "commit", "label": f"commit them on {s['branch']}",
                        "undo": "git reset --soft HEAD~1"})
    options.append({"choice": "branch", "label": f"move them to a new branch {branch_name(s)}",
                    "branch": branch_name(s), "undo": f"git switch {s.get('branch') or '-'}"})
    options.append({"choice": "stash", "label": "stash them (untracked files too)", "undo": "git stash pop"})
    options.append({"choice": "skip", "label": "leave this tree as it is", "undo": ""})

    if s.get("mid_operation") or s.get("conflicted"):
        what = s.get("mid_operation") or "a merge"
        return {"options": [o for o in options if o["choice"] == "skip"], "recommended": "skip",
                "why": f"this tree is in the middle of {what} with conflicts to resolve; finish or abort "
                       f"it in a terminal first -- committing now would record the conflict markers",
                "debt": mine, "overlaps": []}

    changed = {f["path"] for f in s.get("files") or []}
    homes = [dict(o, where=o.get("where") or f"checkout {o.get('repo', '')}") for o in others or []]
    homes += [dict(b, where=f"branch {b['branch']}") for b in s.get("branches") or []]
    overlaps = []
    for o in homes:
        shared = sorted(changed & {f["path"] if isinstance(f, dict) else f for f in o.get("files") or []})
        if shared:
            overlaps.append({"where": o["where"], "branch": o.get("branch", ""), "files": shared[:20],
                             "shared": len(shared), "debt": debt(o)})
    keep = "commit" if may_commit else "branch"
    if not overlaps:
        why = (f"{s['branch']} is the branch this tree is on and nothing else changes these files: "
               f"commit them where they were made" if may_commit else
               f"{s.get('branch') or 'a detached HEAD'} takes no commits, so the work goes on a branch "
               f"of its own (AGENTS.md rule 16)")
        return {"options": options, "recommended": keep, "why": why, "debt": mine, "overlaps": []}

    rival = min(overlaps, key=lambda o: o["debt"]["score"])
    if mine["score"] <= rival["debt"]["score"]:
        why = (f"{rival['shared']} of these files also change on {rival['where']}. Keeping them here adds "
               f"less tech debt ({mine['score']} against {rival['debt']['score']}): "
               + ("commit them on " + s["branch"] if may_commit else "move them to a branch of their own")
               + f", and bring {rival['where']} up to date from it")
        return {"options": options, "recommended": keep, "why": why, "debt": mine, "overlaps": overlaps}
    why = (f"{rival['shared']} of these files also change on {rival['where']}, which carries less tech debt "
           f"({rival['debt']['score']} against {mine['score']} here). Landing them here would set up a "
           f"conflict on the more indebted branch, so stash them: nothing is lost, and `git stash pop` "
           f"brings them back wherever you decide they belong")
    return {"options": options, "recommended": "stash", "why": why, "debt": mine, "overlaps": overlaps}


# ---------------------------------------------------------------------------------- applying


def _scope(cwd: str) -> list[str]:
    """The pathspec every write uses: the whole tree, `.agent/` left out.

    Spelled out only when git would otherwise see `.agent/`: a project that ignores it (the stub's
    `.gitignore` does) must not name it at all, because naming an ignored path makes `git add` and
    `git stash push` refuse the whole command -- the stash half-done -- rather than skip it.
    """
    ignored = _git(cwd, "check-ignore", "-q", ".agent")[0] == 0
    return ["--", "."] if ignored else ["--", ".", EXCLUDE]


def _unstage(cwd: str) -> None:
    _git(cwd, "reset", "-q", *_scope(cwd))


def _commit(cwd: str, msg: str) -> str:
    code, _, err = _git(cwd, "add", "-A", *_scope(cwd))
    if code != 0:
        raise TidyError("tidy_failed", f"git add failed: {err}", "nothing was committed")
    code, out, err = _git(cwd, "commit", "-q", "-m", msg, timeout=120)
    if code != 0:
        _unstage(cwd)
        said = [ln for ln in (err or out or "").splitlines() if ln.strip()]
        raise TidyError("commit_refused", (said[-1] if said else f"git commit exited {code}")[:300],
                        "the repository's commit hook or git refused it; the changes are still in the tree, "
                        "unstaged. Read the message, or stash instead")
    return _git(cwd, "rev-parse", "--short", "HEAD")[1]


def apply(cwd: str, plan_id: str, choice: str, *, msg: str = "", branch: str = "") -> dict:
    """Apply one decision to the tree it was made about. Raises `TidyError` for anything refused."""
    if choice not in CHOICES:
        raise TidyError("bad_choice", f"{choice!r} is not one of {', '.join(CHOICES)}",
                        "discarding work is not something the cleanup does: use a terminal for that")
    s = survey(cwd, with_branches=False)
    if s["plan_id"] != str(plan_id or ""):
        raise TidyError("changed", "the tree changed since this decision was offered",
                        "look again: the guide shows it as it is now", s)
    if choice == "skip":
        return {"ok": True, "did": "skip", "clean": not s["dirty"], "undo": ""}
    if not s["dirty"]:
        return {"ok": True, "did": "nothing", "clean": True, "undo": "", "note": "already clean"}
    if s["mid_operation"] or s["conflicted"]:
        raise TidyError("mid_operation", f"the tree is in the middle of {s['mid_operation'] or 'a merge'}",
                        "finish or abort it in a terminal first", s)
    if choice == "commit":
        if not s["branch"] or s["protected"]:
            raise TidyError("protected_branch",
                            f"{s['branch'] or 'a detached HEAD'} takes no commits from the cleanup",
                            "move the changes to a new branch instead (AGENTS.md rule 16)", s)
        sha = _commit(cwd, msg.strip() or message(s))
        return {"ok": True, "did": "commit", "branch": s["branch"], "commit": sha,
                "clean": not survey(cwd, with_branches=False)["dirty"], "undo": "git reset --soft HEAD~1"}
    if choice == "branch":
        name = (branch or branch_name(s)).strip()
        if _git(cwd, "check-ref-format", "--branch", name)[0] != 0 or name.startswith("-"):
            raise TidyError("bad_branch", f"{name!r} is not a branch name git accepts", "pick another name", s)
        if _ref(cwd, f"refs/heads/{name}"):
            raise TidyError("branch_exists", f"{name} already exists",
                            "pick another name; the cleanup never moves work onto an existing branch", s)
        was = s["branch"]
        code, _, err = _git(cwd, "switch", "-q", "-c", name)
        if code != 0:
            raise TidyError("tidy_failed", f"git switch -c failed: {err}", "nothing was changed", s)
        try:
            sha = _commit(cwd, msg.strip() or message(dict(s, branch=name)))
        except TidyError:
            _git(cwd, "switch", "-q", was or "-")
            _git(cwd, "branch", "-q", "-d", name)
            raise
        return {"ok": True, "did": "branch", "branch": name, "from": was, "commit": sha,
                "clean": not survey(cwd, with_branches=False)["dirty"],
                "undo": f"git switch {was}" if was else ""}
    label = f"cleanup guide {time.strftime('%Y-%m-%d %H:%M')} on {s['branch'] or s['head']}"
    code, _, err = _git(cwd, "stash", "push", "-q", "--include-untracked", "-m", label, *_scope(cwd))
    if code != 0:
        raise TidyError("tidy_failed", f"git stash failed: {err}", "nothing was changed", s)
    ref = _git(cwd, "rev-parse", "--short", "stash@{0}")[1]
    return {"ok": True, "did": "stash", "stash": ref, "label": label,
            "clean": not survey(cwd, with_branches=False)["dirty"], "undo": f"git stash pop (the stash named {label!r})"}
