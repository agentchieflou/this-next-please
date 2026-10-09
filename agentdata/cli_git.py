"""ad-git push: the one push -- the current branch, to its own name, on a configured remote, gated (#502).
ad-git pr: the Bitbucket pull request for that branch, through pncli's pinned PR verb, gated (`bitbucket-pr`).

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

from . import completion
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


PR_PIN_HINT = {
    "pr_create": ('pin it: run `pncli bitbucket --help` for the PR verb and set the template: ad-setup --only pncli '
                  '--non-interactive --set pncli.verbs.pr_create="bitbucket <verb> --title {title} --source {source} '
                  '--target {target} --description {description}"'),
    "pr_update": ('pin it: run `pncli bitbucket --help` for the PR update verb and set the template: ad-setup --only '
                  'pncli --non-interactive --set pncli.verbs.pr_update="bitbucket <verb> --id {pr_id} --title {title} '
                  '--description {description}"'),
}
DESCRIPTION_SUBJECTS = 20


def _default_target(cwd: str, remote: str) -> str:
    code, head_ref, _ = _git(cwd, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    if code == 0 and head_ref:
        return head_ref.rsplit(f"refs/remotes/{remote}/", 1)[-1]
    return next((b for b in ("main", "master") if _ref(cwd, f"refs/remotes/{remote}/{b}")), "")


def pr_plan(cwd: str, *, title: str | None = None, target: str | None = None, draft: bool = True,
            overwrite: str | None = None, remote: str | None = None, cfg: dict | None = None) -> dict:
    """Everything `ad-git pr` would send, from local refs and config only. Raises `Refused`."""
    from .connectors import pncli as P
    cfg = C.load() if cfg is None else cfg
    p = plan(cwd, remote)                     # detached head, protected branch, unknown remote, diverged
    action = "update" if overwrite else "create"
    verb = "pr_update" if overwrite else "pr_create"
    template = P.verb_template(verb, cfg)
    if not template:
        raise Refused("not_pinned", f"pncli's PR {action} verb is not pinned (pncli.verbs.{verb} is unset)",
                      PR_PIN_HINT[verb], p)
    target = (target or _default_target(cwd, p["remote"])).strip()
    if not target:
        raise Refused("no_target", f"{p['remote']} names no default branch to open the PR against",
                      "pass --target <branch>", p)
    if target == p["branch"]:
        raise Refused("default_branch", f"the PR would merge {target!r} into itself",
                      "the work goes on a branch — AGENTS.md rule 16: `git checkout -b <type>/<KEY>-<slug>`", p)
    ticket = _active_ticket(cwd)
    if not title:
        _, subject, _ = _git(cwd, "log", "-1", "--format=%s")
        title = subject or p["branch"]
        if ticket and ticket.lower() not in title.lower():
            title = f"{ticket}: {title}"
    base = f"refs/remotes/{p['remote']}/{target}"
    span = f"{base}..HEAD" if _ref(cwd, base) else "HEAD"
    _, logged, _ = _git(cwd, "log", f"--max-count={DESCRIPTION_SUBJECTS}", "--format=%s", span)
    lines = ([f"Ticket: {ticket}", ""] if ticket else []) + ["Commits:"] + \
        [f"- {s}" for s in logged.splitlines() if s.strip()]
    description = "\n".join(lines)
    values = {"title": title, "source": p["branch"], "target": target, "description": description,
              "draft": "true" if draft else "false", "pr_id": overwrite or ""}
    try:
        argv = P.template_argv(template, {k: values[k] for k in P.VERBS[verb]})
    except ValueError as e:
        raise Refused("bad_template", f"pncli.verbs.{verb}: {e}", PR_PIN_HINT[verb], p) from None
    if P.verb(argv)[:1] != ("bitbucket",):
        raise Refused("bad_template", f"pncli.verbs.{verb} must be a bitbucket verb: {template}", PR_PIN_HINT[verb], p)
    out = {"action": action, "pr_id": overwrite or "", "title": title, "draft": bool(draft), "source": p["branch"],
           "target": target, "remote": p["remote"], "description": "replaced" if overwrite else "written",
           "live_hash": "", "head": p["head"], "argv": argv,
           "command": P.shown_argv(argv, {"description": description})}
    if not p.get("upstream_now") or p.get("ahead"):
        out["note"] = f"{p['branch']} has commits {p['remote']} has not seen: run `ad-git push` first"
    return out


def _pr(a) -> int:
    """`ad-git pr`: open (or update) the Bitbucket PR for the current branch through pncli, gated."""
    from .connectors import pncli as P
    src = "ad-git pr"
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    cwd = os.getcwd()
    cfg = C.load()
    try:
        p = pr_plan(cwd, title=a.title, target=a.target, draft=not a.ready, overwrite=a.overwrite, cfg=cfg)
    except Refused as r:
        meta = {"ok": False, "source": src, **{k: v for k, v in r.plan.items() if k in ("branch", "remote")},
                "refused": r.code, "error": r.error, "hint": r.hint}
        print(toon.encode({"meta": meta}))
        return r.exit_code
    keep = ("action", "pr_id", "title", "draft", "source", "target", "remote", "description", "live_hash", "head",
            "command", "note")
    # `source` is the PR's source branch here, the name the wrap-up's stable fields read (`fleet/wrapup.STABLE`);
    # a refusal's `source` is the command, as everywhere else.
    meta = {"ok": True, **{k: p[k] for k in keep if k in p}}
    if a.dry_run:
        meta["dry_run"] = True
        meta["next"] = "read the plan, then run the same command without --dry-run (in a fleet it waits on the operator)"
        _print_meta(meta, src)
        return 0
    from .fleet import approval

    payload = {k: p[k] for k in keep if k in p and k != "note"}
    decision = approval.require("bitbucket-pr", f"{p['action']} {'draft ' if p['draft'] else ''}PR "
                                f"{p['source']} → {p['target']}: {p['title']}", payload,
                                ticket=_active_ticket(cwd), cfg=cfg)
    if not decision.ok:
        print(toon.encode({"meta": approval.refusal(decision, src)}))
        return 2
    if decision.reason:
        meta["approval_note"] = decision.reason
    try:
        answer, elapsed = P.run(p["argv"], timeout=DEFAULT_TIMEOUT_S, cfg=cfg)
    except proc.ProcError as e:
        print(toon.encode({"meta": {"ok": False, "source": src, "refused": e.code, "error": e.msg,
                                    "hint": e.hint or "read pncli's message; nothing is retried"}}))
        return 1
    meta.update(pr_id=p["pr_id"] or P.find(answer, "id", "prId", "pr_id"), url=P.url_of(answer),
                elapsed_ms=int(elapsed * 1000))
    _print_meta(meta, src)
    return 0


def _print_meta(meta: dict, src: str) -> None:
    meta = {k: v for k, v in meta.items() if v is not None}
    if policy.pretty():
        ui.facts([(k, ", ".join(v) if isinstance(v, list) else v) for k, v in meta.items()], title=src)
    else:
        print(toon.encode({"meta": meta}))


def _tidy(a) -> int:
    """`ad-git tidy`: the cleanup guide's decisions for the checkout this runs in (`fleet/tidy.py`).

    `--dry-run` surveys and recommends, and changes nothing. `--apply` changes the tree, so inside a
    fleet it waits on the approval gate like `ad-git push`: an agent proposes, the operator decides.
    """
    from .fleet import tidy as T

    src = "ad-git tidy"
    cwd = os.getcwd()
    if a.pretty:
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        if not a.apply:
            s = T.survey(cwd)
            r = T.recommend(s)
            meta = {"ok": True, "source": src, "dry_run": True, "branch": s["branch"] or "(detached)",
                    "dirty": s["dirty"], "count": s["count"], "plan_id": s["plan_id"],
                    "recommended": r["recommended"] if s["dirty"] else "nothing", "why": r["why"],
                    "options": [o["choice"] for o in r["options"]], "debt": r["debt"]["score"],
                    "next": (f"ad-git tidy --apply {r['recommended']} --plan {s['plan_id']}" if s["dirty"]
                             else "nothing to do: the tree is clean")}
            rows = [[f["state"], f["path"]] for f in s["files"]]
            overlaps = [[o["where"], o["shared"], o["debt"]["score"]] for o in r["overlaps"]]
            if policy.pretty():
                ui.facts(list(meta.items()), title=src)
            else:
                print(toon.encode({"meta": meta}))
                if rows:
                    print(toon.table("files", ["state", "path"], rows))
                if overlaps:
                    print(toon.table("overlaps", ["where", "shared", "debt"], overlaps))
            return 0
        if not a.plan:
            raise T.TidyError("no_plan", "--apply needs --plan <id> from a --dry-run",
                              "run `ad-git tidy --dry-run` and read the plan_id")
        from .fleet import approval

        if approval.in_fleet():
            decision = approval.require("git-tidy", f"{a.apply} the uncommitted changes in {os.path.basename(cwd)}",
                                        {"choice": a.apply, "plan_id": a.plan, "message": a.message or "",
                                         "branch": a.branch or ""}, ticket=_active_ticket(cwd), cfg=C.load())
            if not decision.ok:
                print(toon.encode({"meta": approval.refusal(decision, src)}))
                return 2
        done = T.apply(cwd, a.plan, a.apply, msg=a.message or "", branch=a.branch or "")
        print(toon.encode({"meta": {"source": src, **done}}))
        return 0
    except T.TidyError as e:
        print(toon.encode({"meta": {"source": src, **{k: v for k, v in e.to_dict().items() if k != "survey"}}}))
        return 2


# Every spelling that would make this something other than "this branch, to its own name".
FORCE_WORDS = ("--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d", "--tags",
               "--all", "--prune")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-git", allow_abbrev=False,
                                 description="The git writes an agent may make, gated: push the current branch, open its "
                                             "Bitbucket PR, and tidy a dirty tree without losing anything.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", allow_abbrev=False,
                       help="push the current branch to its own name on a configured remote and set the upstream "
                            "(never forced, never a protected branch; --dry-run first; gated in a fleet)")
    p.add_argument("--remote", help="a remote `git remote` lists (default: origin); never a URL")
    p.add_argument("--dry-run", action="store_true", help="print the plan from local refs; contact no remote")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    r = sub.add_parser("pr", allow_abbrev=False,
                       help="open or update the Bitbucket PR for the current branch through pncli's pinned PR verb "
                            "(never from a protected branch; --dry-run first; gated in a fleet)")
    r.add_argument("--title", help="the PR title (default: the active ticket and the last commit's subject)")
    r.add_argument("--target", metavar="BRANCH", help="the branch to merge into (default: the remote's HEAD)")
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--draft", action="store_true", help="open it as a draft (the default)")
    mode.add_argument("--ready", action="store_true", help="open it ready for review")
    r.add_argument("--overwrite", metavar="PR_ID", help="update this PR instead of opening one")
    r.add_argument("--dry-run", action="store_true", help="print the plan from local refs and config; send nothing")
    r.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    t = sub.add_parser("tidy", allow_abbrev=False,
                       help="a dirty working tree, made clean without losing anything: survey it and recommend "
                            "one option (--dry-run), then --apply commit | branch | stash | skip --plan <id>")
    t.add_argument("--dry-run", action="store_true", help="survey and recommend; change nothing")
    t.add_argument("--apply", choices=["commit", "branch", "stash", "skip"],
                   help="the decision to apply; never a discard")
    t.add_argument("--plan", help="the plan_id the --dry-run printed; a tree that moved since is refused")
    t.add_argument("--message", help="the commit message for commit or branch")
    t.add_argument("--branch", help="the new branch's name for branch (default: wip/<branch>-<date>)")
    t.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    completion.autocomplete(ap)
    a, extra = ap.parse_known_args(argv)
    if a.cmd == "tidy":
        a = ap.parse_args(argv)
        return _tidy(a)
    if a.cmd == "pr":
        a = ap.parse_args(argv)
        return _pr(a)
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
    a = ap.parse_args(argv)                      # the same parse; this is the one AGENTDATA_PARSE_ONLY watches
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
