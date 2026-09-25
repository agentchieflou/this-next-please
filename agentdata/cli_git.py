"""ad-git push: the one push -- the current branch, to its own name, on a configured remote, gated (#502).

`shell(git push)` stays on the fleet's deny floor (launch.py). A deny is a prefix, so no allow entry can offer a
push without also offering `git push -u origin HEAD --force`; and a push without an explicit refspec follows
`branch.<b>.merge` and `remote.<r>.push`, so a branch cut from `origin/main` can land on `main`. This command is
the push instead, and everything it must *refuse* lives here, where a refusal is a return value:

* a protected branch -- `main`, `master`, `develop`, and whatever the remote's HEAD names, read locally for the
  plan and asked of the remote itself before the write (`poll.default_branch`'s fallback to the current branch
  is a heuristic for a tile, never a guard);
* a detached HEAD; a remote `git remote` does not list (a URL included); a branch behind its remote branch;
* any force, delete, mirror, tags or refspec: there is no option for them, and any extra argument is refused.

The plan is worked out from local refs only, so `--dry-run` contacts no remote. The real run passes
`approval.require("git-push", ...)` inside a fleet, then pushes `refs/heads/<b>:refs/heads/<b>` with
`--set-upstream`, with git's prompts off and a timeout, and reads the remote-tracking ref back.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config as C
from . import policy, proc, toon, ui
from .console import utf8_stdout

PROTECTED = ("main", "master", "develop")
AHEAD_CAP = 1000                                   # a branch never pushed is counted against the default, capped
SUBJECTS = 5
DEFAULT_TIMEOUT_S = 120
READ_TIMEOUT_S = 30
# Nothing git runs for us may wait for a person: no terminal prompt, no credential-manager window.
QUIET_ENV = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


class Refused(Exception):
    def __init__(self, code: str, error: str, hint: str, plan: dict | None = None, exit_code: int = 2):
        super().__init__(error)
        self.code, self.error, self.hint, self.plan, self.exit_code = code, error, hint, plan or {}, exit_code


def _git(cwd: str, *args: str, timeout: int = READ_TIMEOUT_S) -> tuple[int, str, str]:
    code, out, err, _ = proc.run(["git", *args], cwd=cwd, timeout=timeout, env=dict(QUIET_ENV))
    return code, out.strip(), err.strip()


def _ref(cwd: str, ref: str) -> str:
    code, out, _ = _git(cwd, "rev-parse", "--verify", "--quiet", ref)
    return out if code == 0 else ""


def _active_ticket(cwd: str) -> str:
    from . import state as S
    try:
        return str(S.load(os.path.join(cwd, ".agent", "state.json")).get("active_ticket") or "")
    except Exception:  # noqa: BLE001 - a note, never a reason to refuse
        return ""


def plan(cwd: str, remote: str | None = None) -> dict:
    """What a push would do, from local refs only. Raises `Refused` for anything this command will not push."""
    code, branch, err = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        raise Refused("push_failed", f"not a git checkout: {err or cwd}", "run it in the repository's working tree",
                      exit_code=2)
    if branch == "HEAD":
        raise Refused("detached_head", "HEAD is detached: there is no branch to push",
                      "check out the ticket's branch, or `git checkout -b <branch>` (AGENTS.md rule 16)")
    remote = remote or "origin"
    _, listed, _ = _git(cwd, "remote")
    remotes = [r for r in listed.splitlines() if r.strip()]
    if remote not in remotes:
        raise Refused("unknown_remote", f"{remote!r} is not a configured remote",
                      "configured: " + (", ".join(remotes) or "none") + "; pass one of them with --remote NAME")
    code, head_ref, _ = _git(cwd, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    remote_head = head_ref.rsplit(f"refs/remotes/{remote}/", 1)[-1] if code == 0 and head_ref else ""
    protected = sorted(set(PROTECTED) | ({remote_head} if remote_head else set()))
    base = {"branch": branch, "remote": remote, "target": f"refs/heads/{branch}",
            "upstream": f"{remote}/{branch}", "protected": protected}
    if branch in protected:
        raise Refused("default_branch", f"{branch!r} is a protected branch on {remote}",
                      "the work goes on a branch — AGENTS.md rule 16: `git checkout -b <type>/<KEY>-<slug>`", base)

    head = _ref(cwd, "HEAD")
    tracking = _ref(cwd, f"refs/remotes/{remote}/{branch}")
    if tracking:
        span = f"{tracking}..{head}"
        _, n, _ = _git(cwd, "rev-list", "--count", span)
        _, b, _ = _git(cwd, "rev-list", "--count", f"{head}..{tracking}")
        ahead, behind = int(n or 0), int(b or 0)
    else:
        default = next((r for r in ([f"refs/remotes/{remote}/{remote_head}"] if remote_head else [])
                        + [f"refs/remotes/{remote}/main", f"refs/remotes/{remote}/master",
                           "refs/heads/main", "refs/heads/master"] if _ref(cwd, r)), "")
        span = f"{default}..{head}" if default else head
        _, n, _ = _git(cwd, "rev-list", "--count", f"--max-count={AHEAD_CAP}", span)
        ahead, behind = int(n or 0), 0
    _, logged, _ = _git(cwd, "log", f"--max-count={SUBJECTS}", "--format=%s", span) if ahead else (0, "", "")
    _, upstream_now, _ = _git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    out = {**base, "head": head[:12], "upstream_now": upstream_now if upstream_now and "@{u}" not in upstream_now
           else "", "ahead": ahead, "behind": behind, "subjects": [s for s in logged.splitlines() if s][:SUBJECTS]}
    key = _active_ticket(cwd)
    if key and key.lower() not in branch.lower():
        out["note"] = f"the branch name does not carry the active ticket {key} (AGENTS.md rule 16)"
    if behind:
        raise Refused("diverged", f"{branch} is {behind} commit(s) behind {remote}/{branch}",
                      "a push would be rejected and there is no force here: bring the remote branch in "
                      f"(`git pull --no-rebase {remote} {branch}`), then push again", out)
    return out


def _timeout(cfg: dict) -> int:
    try:
        return max(1, int(C.get(cfg, "fleet.git_push_timeout_s") or DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


def push(cwd: str, remote: str | None = None, *, dry_run: bool = False, source: str = "ad-git push") -> tuple[int, dict]:
    """(exit code, meta). The whole command, without printing, so the wrap-up and the tests call it the same way."""
    try:
        p = plan(cwd, remote)
    except Refused as r:
        return r.exit_code, {"ok": False, "source": source, **r.plan, "refused": r.code, "error": r.error,
                             "hint": r.hint}
    meta = {"ok": True, "source": source, **p}
    if dry_run:
        return 0, {**meta, "dry_run": True}
    if not p["ahead"]:
        return 0, {**meta, "note": meta.get("note") or f"nothing to push: {p['branch']} is not ahead"}

    cfg = C.load()
    from .fleet import approval

    decision = approval.require("git-push", f"{p['branch']} → {p['remote']} ({p['ahead']} commits)", p,
                                ticket=_active_ticket(cwd), cfg=cfg)
    if not decision.ok:
        return 2, approval.refusal(decision, source)

    remote, branch = p["remote"], p["branch"]
    code, said, err = _git(cwd, "ls-remote", "--symref", remote, "HEAD", timeout=_timeout(cfg))
    if code != 0:
        return 1, {**meta, "ok": False, "refused": "push_failed", "error": f"{remote} did not answer: "
                   + (err.splitlines()[-1] if err else f"git exited {code}"),
                   "hint": "check the remote is reachable and signed in (git never prompts here); nothing was pushed"}
    for line in said.splitlines():
        if line.startswith("ref:") and line.split()[1] == f"refs/heads/{branch}":
            return 2, {**meta, "ok": False, "refused": "default_branch",
                       "error": f"{remote}'s HEAD names {branch!r}: it is the remote's default branch",
                       "hint": "the work goes on a branch — AGENTS.md rule 16: `git checkout -b <type>/<KEY>-<slug>`"}
    ref = f"refs/heads/{branch}"
    try:
        code, out, err, _ = proc.run(["git", "push", "--porcelain", "--set-upstream", remote, f"{ref}:{ref}"],
                                     cwd=cwd, timeout=_timeout(cfg), env=dict(QUIET_ENV))
    except proc.ProcError as e:
        return 1, {**meta, "ok": False, "refused": "push_failed", "error": e.msg,
                   "hint": e.hint or "raise fleet.git_push_timeout_s, or run `ad-git push` again when the remote answers"}
    landed = _ref(cwd, f"refs/remotes/{remote}/{branch}")
    if code != 0 or landed != _ref(cwd, "HEAD"):
        tail = [ln for ln in (err or out or "").splitlines() if ln.strip()]
        return 1, {**meta, "ok": False, "refused": "push_failed",
                   "error": (tail[-1] if tail else f"git push exited {code}")[:300],
                   "hint": "read git's message above; a rejected push means the remote moved -- fetch and look, "
                           "never force"}
    return 0, {**meta, "pushed": True, "upstream": f"{remote}/{branch}"}


# Every spelling that would make this something other than "this branch, to its own name".
FORCE_WORDS = ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d", "--tags",
               "--all", "--prune")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-git", allow_abbrev=False,
                                 description="The one git write an agent may make: push the current branch, gated.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", allow_abbrev=False,
                       help="push the current branch to its own name on a configured remote and set the upstream "
                            "(never forced, never a protected branch; --dry-run first; gated in a fleet)")
    p.add_argument("--remote", help="a remote `git remote` lists (default: origin); never a URL")
    p.add_argument("--dry-run", action="store_true", help="print the plan from local refs; contact no remote")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    a, extra = ap.parse_known_args(argv)
    src = "ad-git push"
    if extra:
        word = extra[0].split("=", 1)[0]
        what = "a force" if word in FORCE_WORDS[:4] else "a refspec or option this command does not take"
        print(toon.encode({"meta": {"ok": False, "source": src, "refused": "force_refused",
                                    "error": f"{extra[0]!r} is {what}: ad-git push only pushes the current branch "
                                             "to its own name",
                                    "hint": "no force, delete, mirror, tags or refspec exists here; if the remote "
                                            "moved, fetch and bring it in, then push again"}}))
        return 2
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    rc, meta = push(os.getcwd(), a.remote, dry_run=a.dry_run, source=src)
    meta = {k: v for k, v in meta.items() if v not in (None, "")}
    if policy.pretty():
        ui.facts([(k, ", ".join(v) if isinstance(v, list) else v) for k, v in meta.items()], title=src)
    else:
        print(toon.encode({"meta": meta}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
