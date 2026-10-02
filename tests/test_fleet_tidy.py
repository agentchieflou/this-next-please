"""`agentdata/fleet/tidy.py` and `ad-git tidy`: a dirty tree made clean without losing anything.

Real git repositories in a temporary folder, because every promise here is about what git does:
the commit lands where it was offered, the stash holds the untracked file too, `.agent/` is never
touched, a hook's refusal leaves the tree as it was, and nothing a choice can name discards work.
"""
from __future__ import annotations
import os
import subprocess

import pytest

from agentdata import cli_git
from agentdata.fleet import tidy as T

DAY = 86400
NOW = 1_790_000_000


def git(cwd, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    if when is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(when)} +0000"
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


def write(cwd, rel, body):
    path = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(path) or cwd, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    """The suite isolates git's global config, so the commits the cleanup makes need a name."""
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)


@pytest.fixture()
def repo(tmp_path):
    """`main` with two files, and `feature/RDSD-1-x` one commit ahead, checked out; `.agent/` beside."""
    root = str(tmp_path / "repo")
    os.makedirs(root)
    git(root, "init", "-q", "-b", "main")
    write(root, "a.py", "a\n")
    write(root, "b.py", "b\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init", when=NOW - 10 * DAY)
    git(root, "checkout", "-qb", "feature/RDSD-1-x")
    write(root, "a.py", "a\nfeature\n")
    git(root, "commit", "-qam", "feat: a", when=NOW - DAY)
    write(root, ".agent/state.json", "{}\n")
    return root


def test_a_clean_tree_has_nothing_to_decide(repo, tmp_path):
    s = T.survey(repo, now=NOW)
    assert s["dirty"] is False and s["count"] == 0, ".agent/ is never counted"
    assert T.apply(repo, s["plan_id"], "commit")["did"] == "nothing"


def test_changes_on_a_feature_branch_are_committed_where_they_were_made(repo):
    write(repo, "a.py", "a\nfeature\nmore\n")
    write(repo, "new.py", "n\n")
    s = T.survey(repo, now=NOW)
    assert (s["branch"], s["count"], s["protected"]) == ("feature/RDSD-1-x", 2, False)
    r = T.recommend(s)
    assert r["recommended"] == "commit" and "where they were made" in r["why"]
    assert [o["choice"] for o in r["options"]] == ["commit", "branch", "stash", "skip"]

    done = T.apply(repo, s["plan_id"], "commit")
    assert done["did"] == "commit" and done["clean"] is True
    assert "RDSD-1" in git(repo, "log", "-1", "--format=%s"), "the default message carries the ticket"
    assert set(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {"a.py", "new.py"}
    assert os.path.isfile(os.path.join(repo, ".agent", "state.json")), ".agent/ is the agent's"
    assert "?? .agent/" in git(repo, "status", "--porcelain")


def test_a_protected_branch_takes_no_commit_and_the_work_moves_to_a_branch(repo):
    git(repo, "checkout", "-q", "main")
    write(repo, "b.py", "b\nedited on main\n")
    s = T.survey(repo, now=NOW)
    assert s["protected"] is True
    r = T.recommend(s)
    assert r["recommended"] == "branch" and "commit" not in [o["choice"] for o in r["options"]]
    with pytest.raises(T.TidyError) as e:
        T.apply(repo, s["plan_id"], "commit")
    assert e.value.code == "protected_branch"

    done = T.apply(repo, s["plan_id"], "branch", branch="wip/main-edit", msg="chore: keep the main edit")
    assert (done["did"], done["branch"], done["from"], done["clean"]) == ("branch", "wip/main-edit", "main", True)
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "wip/main-edit"
    assert "edited on main" not in git(repo, "show", "main:b.py"), "main itself never moved"


def test_a_stash_keeps_everything_untracked_files_included(repo):
    write(repo, "a.py", "changed\n")
    write(repo, "untracked.txt", "keep me\n")
    s = T.survey(repo, now=NOW)
    done = T.apply(repo, s["plan_id"], "stash")
    assert done["did"] == "stash" and done["clean"] is True and "git stash pop" in done["undo"]
    assert "cleanup guide" in git(repo, "stash", "list")
    git(repo, "stash", "pop")
    assert open(os.path.join(repo, "untracked.txt"), encoding="utf-8").read() == "keep me\n"


def test_a_decision_about_a_tree_that_moved_is_refused(repo):
    write(repo, "a.py", "one\n")
    s = T.survey(repo, now=NOW)
    write(repo, "b.py", "another edit, after the guide looked\n")
    with pytest.raises(T.TidyError) as e:
        T.apply(repo, s["plan_id"], "commit")
    assert e.value.code == "changed" and e.value.survey["count"] == 2


def test_nothing_a_choice_can_name_discards_work(repo):
    write(repo, "a.py", "precious\n")
    s = T.survey(repo, now=NOW)
    for bad in ("discard", "reset", "clean", ""):
        with pytest.raises(T.TidyError) as e:
            T.apply(repo, s["plan_id"], bad)
        assert e.value.code == "bad_choice"
    assert open(os.path.join(repo, "a.py"), encoding="utf-8").read() == "precious\n"


def test_a_commit_hook_that_refuses_leaves_the_tree_as_it_was(repo):
    hook = os.path.join(repo, ".git", "hooks", "pre-commit")
    write(repo, ".git/hooks/pre-commit", "#!/bin/sh\necho 'guard: refused by the graph guard' >&2\nexit 1\n")
    os.chmod(hook, 0o755)
    write(repo, "a.py", "change\n")
    s = T.survey(repo, now=NOW)
    with pytest.raises(T.TidyError) as e:
        T.apply(repo, s["plan_id"], "commit")
    assert e.value.code == "commit_refused" and "graph guard" in e.value.error
    assert git(repo, "diff", "--cached", "--name-only") == "", "unstaged again"
    assert T.survey(repo, now=NOW)["plan_id"] == s["plan_id"], "the tree is exactly as it was"


def test_on_a_conflict_the_home_with_less_tech_debt_keeps_the_work(repo):
    """The operator's rule: when the same files change in two homes, the one that adds less tech
    debt keeps the work, and the other side is stashed -- kept, and free to undo."""
    # a fresher branch that also changes a.py, cut from today's main
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-qb", "feature/RDSD-2-fresh")
    write(repo, "a.py", "a\nfresh\n")
    git(repo, "commit", "-qam", "feat: fresh", when=NOW - 3600)
    # main moves on, so the old feature branch falls behind
    git(repo, "checkout", "-q", "main")
    for i in range(6):
        write(repo, "b.py", f"b{i}\n")
        git(repo, "commit", "-qam", f"main {i}", when=NOW - 2 * DAY + i)
    git(repo, "checkout", "-q", "feature/RDSD-1-x")
    write(repo, "a.py", "a\nfeature\nstale edit\n")
    s = T.survey(repo, now=NOW)
    assert s["behind"] == 6
    r = T.recommend(s)
    assert r["recommended"] == "stash", r["why"]
    assert r["overlaps"][0]["where"] == "branch feature/RDSD-2-fresh" and "a.py" in r["overlaps"][0]["files"]
    assert r["debt"]["score"] > r["overlaps"][0]["debt"]["score"]

    # and the other way round: from the fresh branch, the stale one is the indebted home
    T.apply(repo, s["plan_id"], "stash")
    git(repo, "checkout", "-q", "feature/RDSD-2-fresh")
    write(repo, "a.py", "a\nfresh\nnew edit\n")
    r = T.recommend(T.survey(repo, now=NOW))
    assert r["recommended"] == "commit" and "less tech debt" in r["why"]


def test_a_tree_in_the_middle_of_a_merge_is_left_for_a_terminal(repo):
    git(repo, "checkout", "-q", "main")
    write(repo, "a.py", "a\nmain side\n")
    git(repo, "commit", "-qam", "main side", when=NOW - 100)
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "merge", "-q", "feature/RDSD-1-x")
    s = T.survey(repo, now=NOW)
    assert s["mid_operation"] == "a merge" and s["conflicted"] == ["a.py"]
    r = T.recommend(s)
    assert r["recommended"] == "skip" and [o["choice"] for o in r["options"]] == ["skip"]
    with pytest.raises(T.TidyError) as e:
        T.apply(repo, s["plan_id"], "stash")
    assert e.value.code == "mid_operation"


def test_debt_is_explained_part_by_part():
    d = T.debt({"behind": 80, "age_days": 100, "carries": 7, "branch": "fix/typo"})
    assert d["parts"] == {"behind": 50.0, "age": 15.0, "carries": 0.7, "untracked": 2.0, "protected": 0.0}
    assert d["score"] == 67.7
    assert T.debt({"branch": "main", "protected": True})["parts"]["protected"] == 100.0


# ------------------------------------------------------------------------------------- the CLI


def test_ad_git_tidy_surveys_then_applies_the_plan_it_printed(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    write(repo, "a.py", "x\n")
    assert cli_git.main(["tidy", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "recommended: commit" in out and "plan_id:" in out and "next: ad-git tidy --apply commit --plan" in out
    plan = next(ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.strip().startswith("plan_id:"))

    assert cli_git.main(["tidy", "--apply", "commit"]) == 2
    assert "no_plan" in capsys.readouterr().out
    assert cli_git.main(["tidy", "--apply", "commit", "--plan", plan, "--message", "fix: RDSD-1 x"]) == 0
    assert "did: commit" in capsys.readouterr().out
    assert git(repo, "log", "-1", "--format=%s").strip() == "fix: RDSD-1 x"


def test_in_a_fleet_ad_git_tidy_waits_on_the_operator(repo, monkeypatch, capsys):
    from agentdata.fleet import approval

    monkeypatch.chdir(repo)
    write(repo, "a.py", "y\n")
    plan = T.survey(repo)["plan_id"]
    asked = []
    monkeypatch.setattr(approval, "in_fleet", lambda: "luna")
    monkeypatch.setattr(approval, "require", lambda kind, summary, payload, **kw: (
        asked.append((kind, payload["choice"])) or approval.Decision(approval.DENIED, id="x")))
    assert cli_git.main(["tidy", "--apply", "stash", "--plan", plan]) == 2
    assert asked == [("git-tidy", "stash")]
    assert "approval_denied" in capsys.readouterr().out
    assert T.survey(repo)["dirty"] is True, "a denied tidy changed nothing"


def test_ad_git_tidy_has_no_discard_to_ask_for():
    with pytest.raises(SystemExit):
        cli_git.main(["tidy", "--apply", "discard", "--plan", "abc"])


@pytest.mark.parametrize("choice", ["commit", "stash", "branch"])
def test_a_project_that_ignores_agent_is_tidied_without_naming_it(repo, choice):
    """The stub's `.gitignore` ignores `.agent/`, and naming an ignored path in a pathspec makes
    `git add` and `git stash push` refuse the whole command -- the stash half-done. Caught by the
    fleet test, against a checkout shaped like a real project."""
    write(repo, ".gitignore", ".agent/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-qm", "ignore .agent", when=NOW - 100)
    write(repo, "a.py", "edited\n")
    write(repo, "n.py", "new\n")
    s = T.survey(repo, now=NOW)
    assert s["count"] == 2
    done = T.apply(repo, s["plan_id"], choice)
    assert done["did"] == choice and done["clean"] is True
    assert open(os.path.join(repo, ".agent", "state.json"), encoding="utf-8").read() == "{}\n"
