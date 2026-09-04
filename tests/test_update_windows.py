"""Tests for the Windows `ad-update` failures in issue #66, replayed from captured transcripts.

The bug that started this: `ad-update` reported `detail: Uninstalling agentdata-0.5.3:` with
`hint: run it yourself to see the whole output`. pip prints its uninstall banner to stdout and the
actual error to stderr, and `_run()` kept the last line of stdout — so the report threw away the one
line that said what went wrong. Every case below asserts the real error now reaches the user, with a
hint specific to that signature.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import proc, update
from agentdata.textio import write_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIP_FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes", "pip", "transcripts")
GH_FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes", "gh", "transcripts")


def transcript(directory, name):
    with open(os.path.join(directory, name), encoding="utf-8") as f:
        return json.load(f)


def replay(t):
    """A `proc.run` stand-in that answers with a captured transcript."""
    def run(argv, **kw):
        return t["returncode"], t["stdout"], t["stderr"], 1.0
    return run


# ------------------------------------------------------------------ the report keeps the error


def test_the_photographed_failure_now_shows_the_real_error(monkeypatch):
    t = transcript(PIP_FAKES, "2026-09-03-all-users-access-denied.json")
    monkeypatch.setattr(proc, "run", replay(t))

    rows = []
    assert update._run("cli", ["pip"], rows, 60) is False
    row = rows[0]

    # the line the old report showed, and the line it threw away
    assert "Uninstalling agentdata-0.5.3:" in row["detail"], "the banner is still there for context"
    assert "WinError 5" in row["detail"], "the actual error must reach the user"
    assert "Access is denied" in row["detail"]
    assert row["hint"] != "run it yourself to see the whole output (exit 1, 1.0s)"
    assert "all users" in row["hint"] and "elevated" in row["hint"]


def test_stderr_comes_first_so_the_error_is_not_pushed_out_by_pip_chatter():
    t = transcript(PIP_FAKES, "2026-09-03-all-users-access-denied.json")
    detail = update.tail_lines(t["stdout"], t["stderr"])
    lines = detail.splitlines()
    assert "WinError 5" in lines[0], "the error is the first thing, not the fifteenth"
    assert len(lines) <= update.TAIL_LINES


def test_a_long_output_is_trimmed_to_the_tail():
    out = "\n".join(f"line {i}" for i in range(200))
    detail = update.tail_lines(out, "")
    assert len(detail.splitlines()) == update.TAIL_LINES
    assert detail.splitlines()[-1] == "line 199"


# ------------------------------------------------------------------------------ the diagnoses


@pytest.mark.parametrize("fixture,needles", [
    ("2026-09-03-all-users-access-denied.json", ("all users", "elevated")),
    ("2026-09-03-locked-launcher.json", ("launcher is locked", "python -m agentdata update")),
    ("2026-09-04-requires-different-python.json", ("3.12", "interpreter")),
    ("2026-09-04-user-install-shadow.json", ("--user install", "shadows")),
])
def test_each_known_signature_gets_its_own_hint(fixture, needles):
    t = transcript(PIP_FAKES, fixture)
    hint = update.diagnose(t["returncode"], t["stdout"], t["stderr"])
    assert hint, f"{fixture} produced no diagnosis"
    for needle in needles:
        assert needle in hint, f"{fixture}: hint does not mention {needle!r}\n{hint}"


def test_the_requires_python_hint_names_the_interpreter_to_use():
    t = transcript(PIP_FAKES, "2026-09-04-requires-different-python.json")
    hint = update.diagnose(1, t["stdout"], t["stderr"])
    import sys
    assert sys.executable.replace("\\", "/") in hint.replace("\\", "/") or sys.executable in hint
    assert "py -3.14" in hint


def test_a_proxy_failure_keeps_the_existing_hint():
    hint = update.diagnose(1, "", "ERROR: Max retries exceeded with url: /agentchieflou/this-next-please")
    assert "HTTPS_PROXY" in hint


def test_an_unknown_failure_is_not_guessed_at(monkeypatch):
    monkeypatch.setattr(proc, "run", lambda argv, **kw: (1, "", "something nobody has seen before\n", 0.5))
    rows = []
    update._run("cli", ["pip"], rows, 60)
    assert update.diagnose(1, "", "something nobody has seen before") == ""
    assert "something nobody has seen before" in rows[0]["detail"], "verbatim, rather than a guess"
    assert "run it yourself" in rows[0]["hint"]


# --------------------------------------------------------------------------- the .exe launcher


def test_launcher_kind_reads_argv0():
    assert update.launcher_kind(r"C:\Python314\Scripts\ad-update.exe") == "exe"
    assert update.launcher_kind(r"C:\tools\ad-update.cmd") == "cmd"
    assert update.launcher_kind("/usr/bin/python") == "module"
    assert update.launcher_kind("") == "module"


def test_the_reexec_command_uses_the_module_form():
    cmd = update.reexec_argv(["--skills"])
    import sys
    assert cmd[:4] == [sys.executable, "-m", "agentdata", "update"]
    assert cmd[-1] == "--skills"
    assert not any(part.endswith(".exe") for part in cmd[1:]), "the launcher must not appear in the re-exec"


# ------------------------------------------------------------------- the skills half, idempotent


def test_already_installed_names_are_parsed():
    t = transcript(GH_FAKES, "2026-09-03-skills-already-installed.json")
    names = update.parse_already_installed(t["stderr"])
    assert "bitbucket-pr" in names and "jira-changelog" in names
    assert all(" " not in n for n in names)


def test_a_truncated_list_does_not_produce_a_bogus_name():
    names = update.parse_already_installed("skills already installed: bitbucket-pr, data-adapter, ...")
    assert names == ["bitbucket-pr", "data-adapter"]


def _skill(dirpath, name, frontmatter_name=None):
    os.makedirs(os.path.join(dirpath, name), exist_ok=True)
    write_text(os.path.join(dirpath, name, "SKILL.md"),
               f'---\nname: {frontmatter_name or name}\ndescription: "x"\n---\n# {name}\n')


def test_only_our_own_skills_are_removed(tmp_path):
    d = str(tmp_path / "skills")
    _skill(d, "bitbucket-pr")                       # ours: frontmatter name matches the folder
    _skill(d, "someone-elses", frontmatter_name="a-different-name")
    os.makedirs(os.path.join(d, "no-skill-md"), exist_ok=True)

    removed = update.remove_our_skills(d, ["bitbucket-pr", "someone-elses", "no-skill-md", "not-here"])
    assert removed == ["bitbucket-pr"]
    assert not os.path.isdir(os.path.join(d, "bitbucket-pr"))
    assert os.path.isdir(os.path.join(d, "someone-elses")), "a foreign skill must survive"
    assert os.path.isdir(os.path.join(d, "no-skill-md")), "a folder we cannot identify must survive"


def test_owned_by_us_requires_the_frontmatter_to_match_the_folder(tmp_path):
    d = str(tmp_path / "s")
    _skill(d, "mine")
    _skill(d, "theirs", frontmatter_name="mine")     # claims our name, but lives elsewhere
    assert update.owned_by_us(os.path.join(d, "mine")) is True
    assert update.owned_by_us(os.path.join(d, "theirs")) is False


def test_supports_force_probes_the_help():
    assert update.supports_force(run=lambda argv, **kw: (0, "  --force  overwrite\n", "", 0.1)) is True
    assert update.supports_force(run=lambda argv, **kw: (0, "no such flag\n", "", 0.1)) is False
    assert update.supports_force(run=lambda argv, **kw: (1, "", "", 0.1)) is False


# --------------------------------------------------------------- where it ran, and what is here


def test_the_environment_block_says_where_this_ran():
    env = update.environment()
    for key in ("shell", "launcher", "stdin_tty", "stdout_tty", "stderr_tty", "encoding"):
        assert key in env, f"a pasted failure has to carry {key}"
    assert env["launcher"] in ("exe", "cmd", "module")


def test_a_five_one_session_is_reported_as_unsupported_but_not_refused(monkeypatch):
    monkeypatch.setattr(update.SH, "detect", lambda *a, **k: "windows-powershell")
    env = update.environment()
    assert env["shell"] == "windows-powershell 5.1 (unsupported)"
    assert "PowerShell 7 required" in env["shell_hint"]


def test_check_lists_installs_and_pythons_without_running_anything(monkeypatch, capsys):
    monkeypatch.setattr(proc, "run", lambda *a, **k: pytest.fail("--check is a dry run"))
    assert update.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "installs[" in out and "pythons[" in out
    assert "launcher:" in out and "shell:" in out


def test_pythons_on_path_never_launches_an_interpreter(monkeypatch):
    monkeypatch.setattr(proc, "run", lambda *a, **k: pytest.fail("--check must not run anything"))
    rows = update.pythons_on_path()
    assert rows, "the interpreter running this test is on the list"
    import sys
    running = [r for r in rows if r["version_from"] == "running"]
    assert len(running) == 1 and running[0]["version"].startswith(f"{sys.version_info.major}.")


def test_an_older_python_on_the_path_is_flagged():
    assert update._version_from_path("C:/Python311/python.exe") == ("3.11", "from the path")
    assert update._version_from_path("/usr/bin/python3.9") == ("3.9", "from the path")
    assert update._version_from_path("/opt/weird/py") == ("", "unknown")


def test_two_installs_are_reported_as_shadowed(monkeypatch, capsys):
    monkeypatch.setattr(proc, "run", lambda *a, **k: pytest.fail("--check is a dry run"))
    monkeypatch.setattr(update, "installed_distributions", lambda: [
        {"name": "agentdata", "version": "0.5.3", "location": "C:/Users/x/AppData/Roaming/Python/site-packages"},
        {"name": "agentdata", "version": "0.6.1", "location": "C:/Program Files/Python314/Lib/site-packages"},
    ])
    update.main(["--check"])
    out = capsys.readouterr().out
    assert "shadowed: true" in out
    assert "uninstall the one you are not using" in out


# ------------------------------------------------------------------------------------- the docs


def test_readme_documents_what_ad_update_now_does_about_installed_skills():
    text = open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8").read()
    assert "delete that folder and re-run" not in text, "ad-update handles this now"
    assert "already installed" in text


def test_the_transcripts_record_their_provenance():
    import glob

    files = glob.glob(os.path.join(PIP_FAKES, "*.json")) + glob.glob(os.path.join(GH_FAKES, "*.json"))
    assert files
    for path in files:
        with open(path, encoding="utf-8") as f:
            t = json.load(f)
        assert t.get("source") in ("photographed", "synthesized", "captured"), path
        for key in ("argv", "returncode", "stdout", "stderr"):
            assert key in t, f"{path} has no {key}"
