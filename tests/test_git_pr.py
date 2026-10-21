"""`ad-git pr`: the Bitbucket pull request for the current branch, through toil's `bitbucket pr create|update`, gated.

Same shape as `ad-git push` (tests/test_git_push.py): never from a protected branch or a detached head, a dry run
that contacts nothing, and a real run that waits on the approval gate in a fleet (`bitbucket-pr`) and is the only
one to carry `--allow-write`. toil's PR verb has no draft, so `--draft` is refused rather than quietly ignored.
"""
from __future__ import annotations

import os

import pytest

from agentdata import cli_git as G
from agentdata.fleet import approval, launch

import fakes
from test_git_push import commit, git, repo  # noqa: F401 - `repo` is a fixture, used by name

WINDOWS = os.name == "nt"


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    fakes.toil_connections(monkeypatch)


def _fake(monkeypatch, tmp_path) -> dict:
    fakes.apply(monkeypatch, tmp_path, ["toil"], case="pr_created")
    monkeypatch.setenv("TOIL_EXE", os.path.join(str(tmp_path), "fakebin", "toil.cmd" if WINDOWS else "toil"))
    return {"AGENTDATA_FAKE_LOG": os.environ["AGENTDATA_FAKE_LOG"]}


def run(capsys, *argv):
    rc = G.main(["pr", *argv])
    return rc, capsys.readouterr().out


def test_a_draft_is_refused_because_toil_cannot_open_one(repo, capsys):  # noqa: F811
    rc, out = run(capsys, "--draft", "--dry-run")
    assert rc == 2 and "refused: draft_unsupported" in out and "without --draft" in out


def test_a_dry_run_prints_the_plan_and_sends_nothing(repo, capsys, monkeypatch, tmp_path):  # noqa: F811
    env = _fake(monkeypatch, tmp_path)
    rc, out = run(capsys, "--title", "RDSD-1: the thing", "--dry-run")
    assert rc == 0, out
    for line in ("action: create", "source: feature/RDSD-1-thing", "target: main", "draft: false",
                 "description: written", "dry_run: true"):
        assert line in out, out
    assert "toil bitbucket pr create --title 'RDSD-1: the thing' --source feature/RDSD-1-thing --target main" in out
    assert "--description '<" in out and "docs: three" not in out, "the description is summarised"
    assert "--connection corp-bb --allow-write" in out, "the plan shows the exact command the approved run sends"
    assert "connection: corp-bb" in out
    assert "ad-git push" in out, "commits the remote has not seen: push first"
    assert fakes.calls(env, "toil") == []


def test_ready_and_target_and_the_default_title(repo, capsys, tmp_path):  # noqa: F811
    rc, out = run(capsys, "--ready", "--target", "develop", "--dry-run")
    assert rc == 0 and "draft: false" in out and "target: develop" in out
    assert "title: \"docs: three\"" in out or "title: docs: three" in out


@pytest.mark.parametrize("branch", ["main", "master", "develop"])
def test_a_protected_branch_is_refused(repo, capsys, tmp_path, branch):  # noqa: F811
    work, _bare = repo
    git(work, "checkout", "-q", "-B", branch)
    rc, out = run(capsys, "--dry-run")
    assert rc == 2 and "refused: default_branch" in out


def test_a_detached_head_is_refused(repo, capsys, tmp_path):  # noqa: F811
    work, _bare = repo
    git(work, "checkout", "-q", "--detach")
    rc, out = run(capsys, "--dry-run")
    assert rc == 2 and "refused: detached_head" in out


def test_a_real_run_asks_the_gate_and_sends_the_description_as_one_argument(repo, capsys, monkeypatch,  # noqa: F811
                                                                             tmp_path):
    env = _fake(monkeypatch, tmp_path)
    asked = []

    def require(kind, summary, payload=None, **kw):
        asked.append((kind, summary, dict(payload or {})))
        return approval.Decision(approval.APPROVED, auto=True)

    monkeypatch.setattr(approval, "require", require)
    rc, out = run(capsys, "--title", "RDSD-1: add thing")
    assert rc == 0, out
    assert [k for k, _s, _p in asked] == ["bitbucket-pr"]
    assert asked[0][2]["source"] == "feature/RDSD-1-thing" and asked[0][2]["target"] == "main"
    (sent,) = fakes.calls(env, "toil")
    assert sent[:3] == ["bitbucket", "pr", "create"] and sent[sent.index("--title") + 1] == "RDSD-1: add thing"
    assert sent[-1] == "--allow-write"
    description = sent[sent.index("--description") + 1]
    assert description.splitlines()[0] == "Commits:" and "- docs: three" in description.splitlines()
    assert "pr_id: 42" in out and "pull-requests/42" in out


def test_writes_off_is_refused_before_the_operator_is_asked(repo, capsys, monkeypatch):  # noqa: F811
    fakes.toil_connections(monkeypatch, [dict(c, writes=False) for c in fakes.WRITABLE])
    monkeypatch.setattr(approval, "require", lambda *a, **k: pytest.fail("asked to approve a write toil refuses"))
    for extra in (("--dry-run",), ()):
        rc, out = run(capsys, "--title", "RDSD-1: x", *extra)
        assert rc == 2 and "refused: writes_off" in out and "TOIL_BITBUCKET_WRITES=true" in out
        assert "toil bitbucket pr create" in out


def test_the_pr_is_on_the_strict_allow_list_and_the_gate_is_in_the_command():
    assert "shell(ad-git pr)" in launch.DEFAULT_ALLOW
    source = open(G.__file__, encoding="utf-8").read()
    assert 'approval.require("bitbucket-pr"' in source
