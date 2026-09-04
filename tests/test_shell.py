"""Tests for shell detection, the `console` doctor step, and the TOON validator.

The point of the shell row is that a Windows PowerShell 5.1 session is told to switch instead of
quietly getting behaviour nobody tests. The point of the validator is that CI can assert, from every
shell, that a command's stdout really is the format the docs promise.
"""
from __future__ import annotations
import io
import os
import subprocess
import sys

import pytest

from agentdata import shell, toon
from agentdata.setup.wizard import run_doctor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, ".github", "scripts")


# ------------------------------------------------------------------------------ shell detection


def _fake_run(names):
    """A stand-in for the Win32_Process walk, returning `names` as the ancestor chain."""
    import json

    def run(argv, timeout):
        return 0, json.dumps(names), ""
    return run


@pytest.mark.skipif(os.name != "nt", reason="the parent-process walk is Windows-only")
def test_detects_windows_powershell_as_unsupported():
    assert shell.detect(run=_fake_run(["powershell.exe", "explorer.exe"]), env={}) == "windows-powershell"


@pytest.mark.skipif(os.name != "nt", reason="the parent-process walk is Windows-only")
def test_detects_pwsh_and_cmd():
    assert shell.detect(run=_fake_run(["pwsh.exe"]), env={}) == "pwsh"
    assert shell.detect(run=_fake_run(["cmd.exe"]), env={}) == "cmd"


@pytest.mark.skipif(os.name != "nt", reason="MSYSTEM only means Git Bash on Windows")
def test_git_bash_is_recognised_by_its_environment():
    """Python launched through a shim is not a child of bash.exe, so the env is the reliable signal."""
    assert shell.detect(run=_fake_run(["python.exe"]), env={"MSYSTEM": "MINGW64"}) == "bash"


@pytest.mark.skipif(os.name != "nt", reason="the parent-process walk is Windows-only")
def test_an_unrecognisable_chain_is_unknown_not_a_crash():
    assert shell.detect(run=_fake_run(["something-else.exe"]), env={}) == "unknown"
    assert shell.detect(run=lambda argv, timeout: (1, "", "boom"), env={}) == "unknown"


def test_the_row_warns_but_never_fails():
    """An unsupported shell is something to change, not a broken install."""
    for names in (["powershell.exe"], ["nothing-we-know.exe"], ["pwsh.exe"]):
        row = shell.check_row(run=_fake_run(names), env={})
        assert row["status"] in ("ok", "warn")
        assert row["status"] != "fail", "a fail here would hide every other row the user needs"


@pytest.mark.skipif(os.name != "nt", reason="the 5.1 hint is a Windows concern")
def test_the_five_one_hint_names_the_way_out():
    row = shell.check_row(run=_fake_run(["powershell.exe"]), env={})
    assert row["status"] == "warn"
    assert "PowerShell 7 required" in row["hint"], "CI asserts on this exact phrase"
    assert "winget install Microsoft.PowerShell" in row["hint"] and "Git Bash" in row["hint"]


def test_doctor_reports_the_console_step(capsys):
    rc = run_doctor(["--only", "console"])
    out = capsys.readouterr().out
    assert rc in (0, 1)
    assert "console,shell," in out or "console,encoding," in out
    assert not toon.validate(out), toon.validate(out)


# ----------------------------------------------------------------------------- the TOON validator


def test_valid_toon_passes():
    text = toon.encode({"meta": {"ok": True, "source": "x"}, "cols": ["a", "b"]})
    assert toon.validate(text) == []
    assert toon.validate(toon.table("rows", ["a", "b"], [[1, 2], [3, 4]])) == []


def test_a_traceback_reaching_stdout_is_caught():
    problems = toon.validate("Traceback (most recent call last):\n  File \"x\", line 1\n")
    assert any("traceback" in p for p in problems)


def test_ansi_in_piped_output_is_caught():
    assert any("ANSI" in p for p in toon.validate("meta:\n  ok: \x1b[32mtrue\x1b[0m\n"))


def test_empty_output_is_caught():
    assert toon.validate("") == ["empty output"]
    assert toon.validate("   \n\n") == ["empty output"]


def test_a_row_count_that_lies_is_caught():
    assert any("declared 2 rows" in p for p in toon.validate("t[2]{a,b}:\n  1,2\n"))
    assert any("header declares 2" in p for p in toon.validate("t[1]{a,b}:\n  only-one\n"))


def test_quoted_commas_do_not_split_a_row():
    assert toon.validate('t[1]{a,b}:\n  "x,y",z\n') == []


def test_the_validator_has_a_module_entry_point(tmp_path):
    """`python -m agentdata.toon --validate -` is what the smoke scripts call."""
    good = toon.encode({"meta": {"ok": True}})
    p = subprocess.run([sys.executable, "-m", "agentdata.toon", "--validate", "-"],
                       input=good, capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 0, p.stderr

    p = subprocess.run([sys.executable, "-m", "agentdata.toon", "--validate", "-"],
                       input="Traceback (most recent call last):\n", capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 1
    assert "not TOON" in p.stderr

    f = tmp_path / "x.toon"
    f.write_text(good, encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "agentdata.toon", "--validate", str(f)],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 0, p.stderr


# --------------------------------------------------------------------------- the module form gap


def test_every_cli_module_is_runnable_with_dash_m():
    """cli_test had no __main__ guard, so `python -m agentdata.cli_test detect` exited 0 printing
    nothing -- a swallowed exit code of exactly the kind this epic exists to catch."""
    import glob

    missing = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "agentdata", "cli*.py"))):
        text = open(path, encoding="utf-8").read()
        if '__name__ == "__main__"' not in text:
            missing.append(os.path.basename(path))
    assert not missing, f"no `python -m` entry guard in: {', '.join(missing)}"


def test_the_ad_test_module_form_actually_prints():
    p = subprocess.run([sys.executable, "-m", "agentdata.cli_test", "detect", REPO_ROOT],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip(), "the module form printed nothing"
    assert not toon.validate(p.stdout), toon.validate(p.stdout)


# ------------------------------------------------------------------------------ the smoke scripts


def test_the_smoke_scripts_exist_and_declare_their_floors():
    ps1 = open(os.path.join(SCRIPTS, "smoke.ps1"), encoding="utf-8").read()
    assert ps1.startswith("#Requires -Version 7.0"), "CI runs this under 5.1 and asserts the refusal"

    sh = open(os.path.join(SCRIPTS, "smoke.sh"), encoding="utf-8").read()
    code = "\n".join(ln for ln in sh.splitlines() if not ln.lstrip().startswith("#"))
    for banned in ("${var@Q}", "EPOCHSECONDS", "wait -n"):
        assert banned not in code, f"{banned} is newer than the bash 4.4 floor"

    assert os.path.isfile(os.path.join(SCRIPTS, "smoke.cmd"))
    assert os.path.isfile(os.path.join(SCRIPTS, "check_doctor.py"))


def test_the_workflow_runs_all_three_shells_and_swallows_nothing():
    import yaml

    wf = yaml.safe_load(open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8"))
    raw = open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()

    assert "|| true" not in raw, "never `|| true` a check whose exit code is documented"

    win = wf["jobs"]["windows"]
    shells = {s.get("shell") for s in win["steps"] if isinstance(s, dict)}
    assert {"pwsh", "bash", "cmd", "powershell"} <= shells, f"missing a shell: {shells}"
    rows = win["strategy"]["matrix"]["include"]
    assert [r["python"] for r in rows] == ["3.12", "3.14"], "the floor and the laptop"
    # a Windows checkout's line endings depend on core.autocrlf, and fixture bytes are the point of
    # several tests, so the matrix runs it both ways rather than pinning one
    assert {r["autocrlf"] for r in rows} == {"true", "false"}
    assert win["strategy"]["fail-fast"] is False

    # the 5.1 step exists only to prove the refusal
    five_one = [s for s in win["steps"] if isinstance(s, dict) and s.get("shell") == "powershell"]
    assert len(five_one) == 1, "exactly one 5.1 step, and only to prove it is refused"
    assert "refused" in five_one[0]["name"].lower()


def test_the_doctor_contract_checker_catches_a_hintless_fail_row():
    """The helper the smoke scripts pipe into, exercised directly."""
    text = toon.encode({"meta": {"ok": False}}) + "\n" + toon.table(
        "checks", ["step", "check", "status", "detail", "hint"],
        [["pncli", "exe", "fail", "not found", ""]],
    )
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_doctor.py"),
                        "--exit-code", "1", "--shell", "test"],
                       input=text, capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 1
    assert "carries no hint" in p.stderr


def test_the_doctor_contract_checker_rejects_a_wrong_exit_code():
    text = toon.encode({"meta": {"ok": True}})
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_doctor.py"),
                        "--exit-code", "2", "--shell", "test"],
                       input=text, capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 1
    assert "the contract is 0" in p.stderr


def test_the_doctor_contract_checker_passes_a_clean_report():
    text = toon.encode({"meta": {"ok": True}}) + "\n" + toon.table(
        "checks", ["step", "check", "status", "detail", "hint"],
        [["console", "shell", "ok", "pwsh", ""]],
    )
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_doctor.py"),
                        "--exit-code", "0", "--shell", "test"],
                       input=text, capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 0, p.stderr


def test_docs_say_what_ci_proves_per_shell():
    text = open(os.path.join(REPO_ROOT, "docs", "setup.md"), encoding="utf-8").read()
    assert "### What CI proves per shell" in text
    assert "use `[IO.File]::WriteAllText" not in text, "the 5.1-era write instruction should be gone"
    assert "workaround is gone" in text, "and the docs should say so, not just drop it"
    assert "PowerShell 7 (`pwsh`) is the floor" in text


def test_shell_scripts_have_pinned_line_endings():
    """A CRLF .sh dies under Git Bash with `$'
': command not found`; cmd.exe wants CRLF.

    Left to whatever core.autocrlf a checkout happens to have, the smoke scripts are a coin flip.
    """
    attrs = open(os.path.join(REPO_ROOT, ".gitattributes"), encoding="utf-8").read()
    for pattern, eol in (("*.sh", "lf"), ("*.ps1", "lf"), ("*.cmd", "crlf"), ("*.bat", "crlf")):
        assert f"{pattern} text eol={eol}" in attrs, f"{pattern} has no pinned line ending"

    # and the bytes on disk match, so a checkout that ignored the attribute is caught too
    with open(os.path.join(SCRIPTS, "smoke.sh"), "rb") as f:
        assert b"\r\n" not in f.read(), "smoke.sh has CRLF line endings"


@pytest.mark.skipif(os.name != "nt", reason="the snapshot walk is Windows-only")
def test_shell_detection_launches_nothing(monkeypatch):
    """Regression: `ad-update --check` is a dry run, and detection used to shell out to PowerShell.

    It passed on a Git Bash laptop for the wrong reason -- MSYSTEM short-circuits before the walk --
    and only went red on CI's Windows runner.
    """
    monkeypatch.setattr(shell.proc, "run", lambda *a, **k: pytest.fail("detection must not spawn"))
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.delenv("SHELL", raising=False)
    assert shell.detect() in ("pwsh", "windows-powershell", "bash", "cmd", "zsh", "unknown")
    assert shell.check_row()["status"] in ("ok", "warn")


@pytest.mark.skipif(os.name != "nt", reason="the snapshot walk is Windows-only")
def test_the_snapshot_walk_finds_real_ancestors():
    names = shell.parent_names()
    assert names, "the process snapshot returned no ancestors"
    assert all(isinstance(n, str) and n for n in names)
