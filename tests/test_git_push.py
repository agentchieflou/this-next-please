"""`ad-git push`: the one push a fleet agent may make, and the wrap-up's push (#502, WRAP-D1).

`shell(git push)` stays on the deny floor. `ad-git push` pushes the current branch to the branch of the same name on
a configured remote -- never a protected branch, never forced, never where `branch.<b>.merge` or `remote.<r>.push`
would have sent it -- and inside a fleet it waits on the approval gate like every other write.

Every case runs real git against a bare repository reached by a path, so nothing here touches a network.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import pytest

from agentdata import cli_git as G
from agentdata import proc
from agentdata.fleet import approval, launch, registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def git(cwd, *args) -> str:
    return subprocess.run([*GIT, *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, subject: str) -> None:
    git(cwd, "commit", "-q", "--allow-empty", "-m", subject)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A clone of a bare `origin` whose HEAD is `main`, on `feature/RDSD-1-thing` with 3 commits nobody pushed."""
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", str(work))
    git(work, "remote", "add", "origin", str(bare))
    commit(work, "chore: start")
    git(work, "push", "-q", "origin", "main")
    git(work, "remote", "set-head", "origin", "main")
    git(work, "checkout", "-q", "-b", "feature/RDSD-1-thing")
    for s in ("feat: one", "fix: two", "docs: three"):
        commit(work, s)
    monkeypatch.chdir(work)
    return work, bare


def remote_refs(bare) -> dict:
    out = git(bare, "for-each-ref", "--format=%(refname) %(objectname)")
    return dict(line.split(" ", 1) for line in out.splitlines() if line)


def run(capsys, *argv):
    rc = G.main(["push", *argv])
    return rc, capsys.readouterr().out


# --------------------------------------------------------------------------------- the dry-run


def test_a_dry_run_shows_the_plan_and_contacts_no_remote(repo, capsys):
    work, bare = repo
    before = remote_refs(bare)
    moved = bare.parent / "away.git"
    shutil.move(str(bare), str(moved))                    # a dry-run that reached the remote would fail now
    try:
        rc, out = run(capsys, "--dry-run")
    finally:
        shutil.move(str(moved), str(bare))
    assert rc == 0, out
    for want in ("ok: true", "branch: feature/RDSD-1-thing", "remote: origin", "target: refs/heads/feature/RDSD-1-thing",
                 "upstream: origin/feature/RDSD-1-thing", "ahead: 3", "behind: 0", "dry_run: true"):
        assert want in out, (want, out)
    assert '"docs: three"' in out and '"feat: one"' in out
    assert remote_refs(bare) == before


def test_the_real_run_pushes_the_branch_and_sets_its_upstream(repo, capsys):
    work, bare = repo
    rc, out = run(capsys)
    assert rc == 0, out
    assert "pushed: true" in out
    head = git(work, "rev-parse", "HEAD")
    assert remote_refs(bare)["refs/heads/feature/RDSD-1-thing"] == head
    assert git(work, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") == "origin/feature/RDSD-1-thing"
    rc, out = run(capsys, "--dry-run")                   # nothing left to push
    assert rc == 0 and "ahead: 0" in out


def test_nothing_ahead_pushes_nothing_and_says_so(repo, capsys):
    work, bare = repo
    git(work, "push", "-q", "origin", "feature/RDSD-1-thing")
    git(work, "fetch", "-q", "origin")
    before = remote_refs(bare)
    rc, out = run(capsys)
    assert rc == 0 and "ok: true" in out and "ahead: 0" in out and "pushed: true" not in out
    assert remote_refs(bare) == before


def test_a_branch_without_the_active_ticket_gets_a_note_not_a_refusal(repo, capsys):
    work, _ = repo
    os.makedirs(work / ".agent")
    (work / ".agent" / "state.json").write_text('{"active_ticket": "RDSD-7"}', encoding="utf-8")
    rc, out = run(capsys, "--dry-run")
    assert rc == 0 and "RDSD-7" in out and "rule 16" in out


# --------------------------------------------------------------------------------- what it refuses


@pytest.mark.parametrize("branch", ["main", "master", "develop", "trunk"])
def test_a_protected_branch_is_refused(repo, capsys, branch):
    work, bare = repo
    if branch == "trunk":                                 # the remote's HEAD names it, whatever it is called
        git(work, "push", "-q", "origin", "HEAD:refs/heads/trunk")
        git(work, "remote", "set-head", "origin", "trunk")
    if branch != "main":
        git(work, "checkout", "-q", "-B", branch)
    else:
        git(work, "checkout", "-q", "main")
        commit(work, "chore: on main")
    before = remote_refs(bare)
    rc, out = run(capsys)
    assert rc == 2, out
    assert "refused: default_branch" in out and "rule 16" in out
    assert remote_refs(bare) == before


def test_a_detached_head_is_refused(repo, capsys):
    work, _ = repo
    git(work, "checkout", "-q", "--detach")
    rc, out = run(capsys, "--dry-run")
    assert rc == 2 and "refused: detached_head" in out


def test_an_upstream_of_origin_main_still_pushes_only_the_branch(repo, capsys):
    """A branch cut from `origin/main` tracks it; a bare `git push` would follow `branch.<b>.merge` to main."""
    work, bare = repo
    git(work, "checkout", "-q", "-b", "cut-from-main", "--track", "origin/main")
    commit(work, "feat: cut")
    main_before = remote_refs(bare)["refs/heads/main"]
    rc, out = run(capsys)
    assert rc == 0, out
    refs = remote_refs(bare)
    assert refs["refs/heads/main"] == main_before
    assert refs["refs/heads/cut-from-main"] == git(work, "rev-parse", "HEAD")


def test_a_push_mapping_to_main_is_ignored(repo, capsys):
    work, bare = repo
    git(work, "config", "remote.origin.push", "HEAD:refs/heads/main")
    main_before = remote_refs(bare)["refs/heads/main"]
    rc, out = run(capsys)
    assert rc == 0, out
    refs = remote_refs(bare)
    assert refs["refs/heads/main"] == main_before and "refs/heads/feature/RDSD-1-thing" in refs


@pytest.mark.parametrize("remote", ["https://example.test/x.git", "nope"])
def test_a_remote_that_is_not_configured_is_refused(repo, capsys, remote):
    rc, out = run(capsys, "--remote", remote, "--dry-run")
    assert rc == 2 and "refused: unknown_remote" in out and "origin" in out


@pytest.mark.parametrize("spelling", [["--force"], ["-f"], ["--force-with-lease"], ["--force-with-lease=main"],
                                      ["--mirror"], ["--delete"], ["--tags"], ["origin"], ["HEAD:main"],
                                      ["--no-verify"]])
def test_every_force_and_every_extra_argument_is_refused(repo, capsys, spelling):
    work, bare = repo
    before = remote_refs(bare)
    rc, out = run(capsys, *spelling)
    assert rc == 2 and "refused: force_refused" in out, out
    assert remote_refs(bare) == before


def test_a_branch_behind_its_remote_branch_is_refused_as_diverged(repo, capsys, tmp_path):
    work, bare = repo
    git(work, "push", "-q", "origin", "feature/RDSD-1-thing")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "feature/RDSD-1-thing", str(bare), str(other))
    commit(other, "feat: someone else")
    git(other, "push", "-q", "origin", "feature/RDSD-1-thing")
    git(work, "fetch", "-q", "origin")
    commit(work, "feat: mine")
    before = remote_refs(bare)
    rc, out = run(capsys)
    assert rc == 2 and "refused: diverged" in out and "behind: 1" in out
    assert remote_refs(bare) == before


def test_the_remote_head_asked_at_push_time_is_protected_too(repo, capsys, monkeypatch):
    """No `refs/remotes/origin/HEAD` locally: only the remote itself can say its default is this branch."""
    work, bare = repo
    git(work, "push", "-q", "origin", "feature/RDSD-1-thing")
    git(work, "remote", "set-head", "origin", "--delete")
    git(bare, "symbolic-ref", "HEAD", "refs/heads/feature/RDSD-1-thing")
    commit(work, "feat: four")
    before = remote_refs(bare)
    rc, out = run(capsys)
    assert rc == 2 and "refused: default_branch" in out
    assert remote_refs(bare) == before


def test_a_rejected_push_is_push_failed_with_gits_message(repo, capsys):
    work, bare = repo
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'branch is frozen for the release' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before = remote_refs(bare)
    rc, out = run(capsys)
    assert rc == 1 and "refused: push_failed" in out and "hint:" in out
    assert "pre-receive" in out or "rejected" in out or "frozen" in out
    assert remote_refs(bare) == before


# --------------------------------------------------------------------------------- how git is run


def test_the_push_never_prompts_and_always_has_a_timeout(repo, capsys, monkeypatch):
    calls = []
    real = proc.run

    def recorder(argv, **kw):
        calls.append((list(argv), kw))
        return real(argv, **kw)

    monkeypatch.setattr(G.proc, "run", recorder)
    rc, out = run(capsys)
    assert rc == 0, out
    pushes = [(a, kw) for a, kw in calls if a[:2] == ["git", "push"]]
    assert len(pushes) == 1
    argv, kw = pushes[0]
    assert argv == ["git", "push", "--porcelain", "--set-upstream", "origin",
                    "refs/heads/feature/RDSD-1-thing:refs/heads/feature/RDSD-1-thing"]
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0" and kw["env"]["GCM_INTERACTIVE"] == "never"
    assert kw["timeout"] == 120
    assert all(kw.get("timeout") for _, kw in calls), "every git call has a timeout"
    assert all(kw.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0" for _, kw in calls)


def test_the_timeout_comes_from_config(repo, capsys, monkeypatch):
    from agentdata import config as C
    cfg = C.load()
    C.put(cfg, "fleet.git_push_timeout_s", 7)
    C.save(cfg)
    seen = []
    real = proc.run
    monkeypatch.setattr(G.proc, "run", lambda argv, **kw: (seen.append((argv, kw)), real(argv, **kw))[1])
    rc, _ = run(capsys)
    assert rc == 0 and [kw["timeout"] for a, kw in seen if a[:2] == ["git", "push"]] == [7]


# --------------------------------------------------------------------------------- the gate


@pytest.fixture()
def as_agent(repo, tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    real_require = approval.require                     # poll fast: the default two seconds is a person's pace
    monkeypatch.setattr(approval, "require", lambda *a, **kw: real_require(*a, **{"poll": 0.02, **kw}))
    return repo


def _gated(capsys, state, reason=""):
    result: dict = {}

    def agent():
        result["rc"], result["out"] = run(capsys)

    t = threading.Thread(target=agent)
    t.start()
    deadline = time.time() + 10
    while not approval.pending() and time.time() < deadline:
        time.sleep(0.02)
    req = approval.pending()[0]
    approval.decide(req["id"], state, reason=reason, by="operator")
    t.join(timeout=20)
    return req, result


def test_inside_a_fleet_the_push_asks_once_with_the_plan(as_agent, capsys):
    work, bare = as_agent
    req, result = _gated(capsys, approval.APPROVED)
    assert req["kind"] == "git-push" and req["summary"] == "feature/RDSD-1-thing → origin (3 commits)"
    plan = req["payload"]
    assert plan["branch"] == "feature/RDSD-1-thing" and plan["target"] == "refs/heads/feature/RDSD-1-thing"
    assert plan["ahead"] == 3 and plan["subjects"][0] == "docs: three"
    assert result["rc"] == 0, result["out"]
    assert "refs/heads/feature/RDSD-1-thing" in remote_refs(bare)


def test_inside_a_fleet_a_deny_pushes_nothing(as_agent, capsys):
    work, bare = as_agent
    before = remote_refs(bare)
    _, result = _gated(capsys, approval.DENIED, reason="not yet")
    assert result["rc"] == 2 and "refused: approval_denied" in result["out"]
    assert remote_refs(bare) == before


# --------------------------------------------------------------------------------- the allow-list and the skill


def test_the_agent_may_run_ad_git_push_and_still_never_git_push():
    argv = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs")
    allowed = [argv[i + 1] for i, a in enumerate(argv) if a == "--allow-tool"]
    denied = [argv[i + 1] for i, a in enumerate(argv) if a == "--deny-tool"]
    assert "shell(ad-git push)" in allowed
    assert allowed.index("shell(ad-git push)") == allowed.index("shell(git commit -m)") + 1
    assert not any(a.startswith("shell(git push") for a in allowed)
    assert "shell(git push)" in denied


def test_bitbucket_pr_pushes_through_ad_git_push_dry_run_first():
    text = open(os.path.join(ROOT, "skills", "bitbucket-pr", "SKILL.md"), encoding="utf-8").read()
    step = next(line for line in text.splitlines() if line.startswith("4. "))
    assert "ad-git push --dry-run" in step and "git push -u" not in text
    assert "approval_denied" in step and "friction-log" in step
    refusals = open(os.path.join(ROOT, "docs", "refusals.md"), encoding="utf-8").read()
    for code in ("detached_head", "unknown_remote", "default_branch", "diverged", "force_refused", "push_failed"):
        assert f"`refused: {code}`" in refusals, code
