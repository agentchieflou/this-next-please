"""ad-update: pick up a new version of the CLI and the skills, and prove which commit is installed."""
import os
import sys
import time

import pytest

from agentdata import proc
from agentdata import update as U


def _skills(tmp_path, names=("router", "jira-triage"), age_days=0.0):
    d = tmp_path / "skills"
    for n in names:
        (d / n).mkdir(parents=True)
        f = d / n / "SKILL.md"
        f.write_text(f"---\nname: {n}\n---\n", encoding="utf-8")
        if age_days:
            old = time.time() - age_days * 86400
            os.utime(f, (old, old))
    return str(d)


def test_command_text_matches_the_install_kind(monkeypatch):
    monkeypatch.setattr(U, "source_checkout", lambda: None)
    text = U.cli_command_text()
    assert text.startswith("python -m pip install --force-reinstall --no-deps ") and "git+https://github.com/agentchieflou" in text
    assert '"agentdata @ git+' in text                       # pip skips a git URL whose version did not change
    assert "--no-deps" not in U.cli_command_text("teradata,odbc") and "agentdata[teradata,odbc] @" in U.cli_command_text("teradata,odbc")
    monkeypatch.setattr(U, "source_checkout", lambda: "/repos/this-next-please")
    assert U.cli_command_text() == 'git -C "/repos/this-next-please" pull && pip install -e ".[dev]"'
    argv = U.cli_command()
    assert argv[:6] == [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps"]


def test_skills_state_and_staleness(tmp_path):
    st = U.skills_state(_skills(tmp_path))
    assert st["installed"] == 2 and st["names"] == ["jira-triage", "router"] and st["newest"]
    assert U.stale(st) is False
    assert U.stale(U.skills_state(_skills(tmp_path / "old", age_days=30))) is True
    assert U.stale({"installed": 0, "newest_epoch": 0.0}) is False      # nothing installed is not "stale"
    empty = U.skills_state(str(tmp_path / "nothing"))
    assert empty["installed"] == 0 and empty["dir"].endswith("nothing")


def test_check_runs_nothing_and_reports_both_parts(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(proc, "run", lambda *a, **k: pytest.fail("--check must not run anything"))
    assert U.main(["--check", "--skills-dir", _skills(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "source: ad-update" in out and "version: " in out and "skills: 2" in out
    assert "gh skill install agentchieflou/this-next-please --all --scope user" in out
    assert "stale_skills: false" in out and "installed_skills[2]" in out


def test_a_checkout_skips_only_the_cli_half_and_is_not_a_failure(tmp_path, capsys, monkeypatch):
    """Running from a checkout is a state, not an error: pip must leave it alone, but the skills still update."""
    monkeypatch.setattr(U, "source_checkout", lambda: "/repos/this-next-please")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return 0, "skills installed", "", 1.0

    monkeypatch.setattr(proc, "run", fake_run)
    skills_dir = _skills(tmp_path)
    rc = U.main(["--skills-dir", skills_dir])
    out = capsys.readouterr().out
    assert rc == 0 and "ok: true" in out                       # nothing failed
    assert [c[0] for c in calls] == ["gh"]                     # the skills half ran; pip did not
    assert "skipped[1]: cli" in out and "running from a checkout at /repos/this-next-please" in out
    assert "--from-git" in out and "--pull" in out
    calls.clear()
    U.main(["--pull", "--skills-dir", skills_dir])            # --pull updates the checkout itself
    assert calls[0][:4] == ["git", "-C", "/repos/this-next-please", "pull"] and "--ff-only" in calls[0]
    calls.clear()
    monkeypatch.setattr(U, "direct_url", lambda: {"url": "https://github.com/x.git", "vcs_info": {"commit_id": "b" * 40}})
    U.main(["--from-git", "--cli"])                            # --from-git leaves the checkout behind
    assert calls[0][:4] == [sys.executable, "-m", "pip", "install"] and "--force-reinstall" in calls[0]


def test_check_names_the_install_kind(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(U, "source_checkout", lambda: "/repos/this-next-please")
    monkeypatch.setattr(proc, "run", lambda *a, **k: pytest.fail("--check must not run anything"))
    skills_dir = _skills(tmp_path)
    assert U.main(["--check", "--skills-dir", skills_dir]) == 0
    assert "install: running from a checkout at /repos/this-next-please" in capsys.readouterr().out
    monkeypatch.setattr(U, "source_checkout", lambda: None)
    monkeypatch.setattr(U, "direct_url", lambda: {"url": "https://x.git", "dir_info": {"editable": True}})
    assert U.main(["--check", "--skills-dir", skills_dir]) == 0
    out = capsys.readouterr().out
    assert "install: editable install" in out and U.cli_state()["kind"] == "editable install"


def test_update_runs_both_commands_and_surfaces_a_failure(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(U, "source_checkout", lambda: None)
    monkeypatch.setattr(U, "direct_url", lambda: {"url": "https://github.com/x.git", "vcs_info": {"commit_id": "a" * 40}})
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        if argv[0] == "gh":
            raise proc.ProcError("not_found", "gh: executable not found", "")
        return 0, "Successfully installed agentdata-0.3.0", "", 1.0

    monkeypatch.setattr(proc, "run", fake_run)
    rc = U.main(["--skills-dir", _skills(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1                                                     # the skills half failed
    assert [c[:4] for c in calls] == [[sys.executable, "-m", "pip", "install"], ["gh", "skill", "install", "agentchieflou/this-next-please"]]
    assert "--force-reinstall" in calls[0] and "--no-deps" in calls[0]
    assert "Successfully installed agentdata-0.3.0" in out and "commit: aaaaaaaaaaaa" in out
    assert "install GitHub CLI (gh)" in out and "NEW Copilot chat" in out
    calls.clear()
    assert U.main(["--cli"]) == 0 and len(calls) == 1                   # --cli skips the skills half
    calls.clear()
    U.main(["--cli", "--extras", "teradata,keyring"])
    assert "agentdata[teradata,keyring] @ git+" in calls[0][-1] and "--no-deps" not in calls[0]


def test_doctor_reports_the_installed_version(capsys):
    from agentdata.setup import wizard as W
    ctx = W.Context(cfg={}, det=W.Detectors(), ask=W.AnswerPrompter({}))
    out, _ok = W.render_checks(ctx, "ad-doctor")
    assert f"version: {U.version()}" in out and "commit: " in out
    from agentdata.__main__ import COMMANDS
    assert COMMANDS["update"][0] == "agentdata.update"


def test_changelog_top_version_matches_the_package():
    """`ad-update --check` compares versions, so a release without a note (or vice versa) is a bug."""
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyproject = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()
    changelog = open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    top = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.M).group(1)
    assert top == declared, f"CHANGELOG top is {top}, pyproject says {declared}"
    assert "ad-update" in changelog and "start a new Copilot chat" in changelog


def test_newest_is_the_newest_skill_not_the_first_alphabetically(tmp_path):
    """`skills_newest` is the evidence that `gh skill install` landed: it must move when a skill is rewritten."""
    d = tmp_path / "skills"
    for name, age in (("aaa-data-adapter", 30), ("zzz-router", 0)):
        (d / name).mkdir(parents=True)
        f = d / name / "SKILL.md"
        f.write_text("x", encoding="utf-8")
        if age:
            old = time.time() - age * 86400
            os.utime(f, (old, old))
    st = U.skills_state(str(d))
    assert st["newest"] == time.strftime("%Y-%m-%d %H:%M", time.localtime(st["newest_epoch"]))
    assert st["newest"] == time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(d / "zzz-router" / "SKILL.md")))


def test_the_skills_directory_is_where_the_agent_actually_reads(tmp_path, monkeypatch):
    """`~/.agents/skills` is first, and the install command pins the agent.

    Measured for the #92 fleet spike on Copilot CLI 1.0.81: user-scope skills live in
    `~/.agents/skills`, and none of the three directories this list used to hold was it. The symptom
    was silent -- `ad-update --check` reported `skills: 0` against a directory that does not exist,
    so `stale()` could never fire, and a headless agent that asked for `session-bootstrap` got a bare
    "failure" because the skill was not installed anywhere it looks. See docs/fleet-spike.md.
    """
    assert U.SKILL_DIRS[0] == "~/.agents/skills", U.SKILL_DIRS
    assert "--agent" in U.SKILLS_CMD and "github-copilot" in U.SKILLS_CMD, U.SKILLS_CMD

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    skill = tmp_path / ".agents" / "skills" / "session-bootstrap"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: session-bootstrap\n---\n", encoding="utf-8")

    assert U.skills_dir().replace("\\", "/").endswith(".agents/skills")
    assert U.skills_state()["installed"] == 1
