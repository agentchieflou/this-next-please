"""The bash 4.4 floor, guarded where the floor shell is not installed.

GitHub's Git Bash is 5.x and the laptop's is 4.4, so CI cannot run the floor. What it *can* do is
refuse a feature that only exists after 4.4 — in a `.sh` we ship, and in anything a command emits
for a user to source. The PowerShell floor needs no such lint (CI's pwsh *is* the floor), only the
`#Requires -Version 7.0` declaration in every script.
"""
from __future__ import annotations
import glob
import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# introduced after bash 4.4. `${var,,}`, associative arrays, `readarray -d` and `mapfile` are 4.x
# and therefore fine -- the list is deliberately the things that are not.
POST_44 = {
    r"\$\{\w+@[QEPAaKk]\}": "${var@Q} parameter transformation (bash 4.4 has @Q only in 4.4+, and @K/@a later)",
    r"\bEPOCHSECONDS\b": "EPOCHSECONDS (bash 5.0)",
    r"\bEPOCHREALTIME\b": "EPOCHREALTIME (bash 5.0)",
    r"\bwait\s+-n\b": "wait -n (bash 4.3+, unreliable before 5.0)",
    r"\bBASH_ARGV0\b": "BASH_ARGV0 (bash 5.0)",
    r"\bSRANDOM\b": "SRANDOM (bash 5.1)",
}


# `agentdata/pbip/win32.ps1` is deliberately launched with Windows PowerShell, not pwsh: it drives
# Power BI Desktop through UIAutomation, whose assemblies are not reachable the same way from 7.
# Declaring a 7.0 floor there would stop the one thing it does. It is the single exception, and it
# is an exception to the *script* rule, not to the shell floor -- nobody types into it.
REQUIRES_EXEMPT = {"win32.ps1"}


# Directories that hold somebody else's files. `node_modules` arrived with the VS Code shell
# (#100) and brought TypeScript's own `tsc.ps1` with it -- which we do not ship, do not maintain,
# and cannot make declare our shell floor.
NOT_OURS = (".git", "build", "dist", "__pycache__", ".pytest_cache", "agentdata.egg-info",
            "node_modules", ".gradle", "out")


def _files(suffix: str) -> list[str]:
    """Every script we ship. `glob` skips dot-directories, so `.github/scripts` needs os.walk."""
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in NOT_OURS]
        for name in filenames:
            if name.endswith(suffix):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def shell_scripts() -> list[str]:
    return _files(".sh")


def powershell_scripts() -> list[str]:
    return _files(".ps1")


def _code_lines(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def test_there_are_scripts_to_lint():
    assert shell_scripts(), "no .sh files found; this lint would pass vacuously"
    assert powershell_scripts(), "no .ps1 files found"


@pytest.mark.parametrize("path", shell_scripts(), ids=lambda p: os.path.basename(p))
def test_no_shell_script_uses_a_post_44_feature(path):
    code = _code_lines(open(path, encoding="utf-8").read())
    for pattern, what in POST_44.items():
        assert not re.search(pattern, code), f"{os.path.basename(path)} uses {what}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash to parse with")
@pytest.mark.parametrize("path", shell_scripts(), ids=lambda p: os.path.basename(p))
def test_every_shell_script_parses(path):
    bash = os.environ.get("GIT_BASH") or shutil.which("bash")
    if bash and "system32" in bash.lower():
        pytest.skip("only the WSL stub is available")
    p = subprocess.run([bash, "-n", path], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


@pytest.mark.parametrize("path", powershell_scripts(), ids=lambda p: os.path.basename(p))
def test_every_powershell_script_declares_the_floor(path):
    name = os.path.basename(path)
    if name in REQUIRES_EXEMPT:
        pytest.skip(f"{name} runs under Windows PowerShell by design (UIAutomation)")
    first = open(path, encoding="utf-8").read().splitlines()[0].strip()
    assert first == "#Requires -Version 7.0", f"{name} does not declare the pwsh 7 floor"


def test_the_one_exempt_script_is_the_one_we_think_it_is():
    """An exemption that grows silently is not an exemption, it is a hole."""
    names = {os.path.basename(p) for p in powershell_scripts()}
    assert REQUIRES_EXEMPT <= names, "the exemption names a script that no longer exists"
    assert len(REQUIRES_EXEMPT) == 1


def test_the_emitted_completion_scripts_respect_the_floors():
    """A user sources these; they are as much ours as the files in the repo."""
    from agentdata.completion import completion_script

    bash_script = _code_lines(completion_script("bash"))
    for pattern, what in POST_44.items():
        assert not re.search(pattern, bash_script), f"the bash completion script uses {what}"

    ps_script = completion_script("powershell")
    assert "Register-ArgumentCompleter" in ps_script


@pytest.mark.skipif(shutil.which("bash") is None, reason="no bash to parse with")
def test_the_emitted_bash_completion_parses(tmp_path):
    from agentdata.completion import completion_script

    bash = os.environ.get("GIT_BASH") or shutil.which("bash")
    if bash and "system32" in bash.lower():
        pytest.skip("only the WSL stub is available")
    path = tmp_path / "completion.sh"
    path.write_text(completion_script("bash"), encoding="utf-8")
    p = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_lint_would_catch_a_planted_violation(tmp_path):
    """The guard has to be able to fail, or it is decoration."""
    planted = tmp_path / "bad.sh"
    planted.write_text('#!/usr/bin/env bash\necho "${var@Q}"\n', encoding="utf-8")
    code = _code_lines(planted.read_text(encoding="utf-8"))
    assert any(re.search(pattern, code) for pattern in POST_44), "the lint cannot see @Q"

    planted_ps = tmp_path / "bad.ps1"
    planted_ps.write_text('Write-Host "no requires line"\n', encoding="utf-8")
    assert planted_ps.read_text(encoding="utf-8").splitlines()[0].strip() != "#Requires -Version 7.0"
