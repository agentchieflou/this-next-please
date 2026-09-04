"""Tab-completion, proven by running the shells rather than by reading the script.

The old tests asserted that the emitted text *contained* `register-python-argcomplete` and
`Register-ArgumentCompleter`. Both assertions passed while completion did nothing at all: the bash
script was wrapped in `if command -v register-python-argcomplete`, which is in the `Scripts`
directory that is usually not on PATH on Windows, and the PowerShell completer's body was a comment.
A string check cannot tell a working completer from a decorative one, so these press Tab instead.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys

import pytest

from agentdata import complete, completion, textio
from agentdata.setup import wizard

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------------ the completer itself


@pytest.mark.parametrize("line,cursor,expected", [
    ("ad-pbip ch", 10, "check"),
    ("ad-setup --pri", 14, "--print-completion"),
    ("ad-graph ", 9, "summary"),
    ("ad-state se", 11, "set"),
    ("ad-test run --sel", 17, "--select"),
    ("ad-", 3, "ad-graph"),
])
def test_the_completer_offers_what_the_parser_accepts(line, cursor, expected):
    assert expected in complete.complete(line, cursor)


def test_completing_a_subcommand_offers_its_own_flags_not_the_parents():
    flags = complete.complete("ad-test run --", 14)
    assert "--select" in flags, "a subcommand's own options must be offered"


def test_an_option_with_choices_completes_its_values():
    """`--color auto|always|never` is a fixed set; the completer should know that."""
    assert "always" in complete.complete("ad-doctor --color al", 20)


def test_the_completer_never_runs_the_command(tmp_path, monkeypatch):
    """It stops at `autocomplete()`, before the parser has parsed anything.

    A completer that ran the command would, on every keypress, read config, hit a network or write
    a file. `ad-state` is the sharpest case: it is the only writer of `.agent/state.json`.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agent").mkdir()
    assert complete.complete("ad-state se", 11) == ["set"]
    assert not list((tmp_path / ".agent").iterdir()), "completion wrote a file"


def test_an_unknown_command_completes_to_nothing_rather_than_crashing():
    assert complete.complete("ad-nope --any", 13) == []


def test_every_command_has_a_reachable_parser():
    """The completer walks a parser; a command whose parser it cannot reach silently offers nothing."""
    from agentdata import __main__ as M

    unreachable = []
    for name in M.COMMANDS:
        if name in M.HIDDEN or name == "help":     # ad-help hand-rolls its arguments, by design
            continue
        if complete.parser_for(name) is None:
            unreachable.append(name)
    assert not unreachable, f"no parser reachable for: {', '.join(unreachable)}"


def test_the_command_list_cannot_drift_from_the_dispatcher():
    """It had: `ad-pbi`, `ad-pbiviz`, `ad-graph` and `ad-test` were missing from the hand-kept list,
    so four commands had no completion at all and nothing said so."""
    from agentdata import __main__ as M

    expected = {f"ad-{n}" for n in M.COMMANDS if n not in M.HIDDEN}
    assert set(completion.all_commands()) == expected


def test_a_hidden_verb_is_never_offered():
    assert "ad-_complete" not in completion.all_commands()
    assert "ad-argv" not in completion.all_commands()


def test_the_complete_verb_prints_one_candidate_per_line():
    out = subprocess.run([sys.executable, "-m", "agentdata", "_complete",
                          "--line", "ad-pbip ch", "--cursor", "10"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert out.stdout.splitlines() == ["check"]
    assert not out.stderr.strip(), "a keypress must never print to stderr"


def test_the_complete_verb_reads_the_bash_protocol():
    """`complete -F` exports COMP_LINE and COMP_POINT and reads stdout."""
    env = {**os.environ, "COMP_LINE": "ad-pbip ch", "COMP_POINT": "10"}
    out = subprocess.run([sys.executable, "-m", "agentdata", "_complete"],
                         capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    assert out.returncode == 0, out.stderr
    assert "check" in out.stdout.split()


# ---------------------------------------------------------------------------- the bash script


def _bash() -> str | None:
    """Git Bash on Windows, /bin/bash elsewhere.

    `shutil.which("bash")` finds the WSL stub in System32 on a Windows runner, which is UTF-16 and
    exits 1 -- the same trap `tests/test_shell_argv.py` documents.
    """
    if os.name != "nt":
        return shutil.which("bash")
    for candidate in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which("bash")
    if found and "system32" in found.lower():
        return None
    return found


BASH = _bash()
bash_only = pytest.mark.skipif(not BASH, reason="no usable bash (Git Bash on Windows, /bin/bash elsewhere)")


def _drive_bash(line: str, point: int) -> list[str]:
    script = (
        f'eval "$("{sys.executable}" -m agentdata setup --print-completion bash)"\n'
        f'COMP_LINE={line!r} COMP_POINT={point} _agentdata_complete\n'
        'printf "%s\\n" "${COMPREPLY[@]}"\n'
    )
    out = subprocess.run([BASH, "-c", script], capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


@bash_only
@pytest.mark.parametrize("line,point,expected", [
    ("ad-pbip ch", 10, "check"),
    ("ad-setup --pri", 14, "--print-completion"),
    ("ad-graph ", 9, "summary"),
    ("ad-test run --sel", 17, "--select"),
])
def test_bash_really_completes(line, point, expected):
    assert expected in _drive_bash(line, point)


@bash_only
def test_the_bash_script_needs_nothing_on_path():
    """It used to be a no-op unless `register-python-argcomplete` was on PATH -- which on Windows
    it is not, because it installs into the same Scripts directory that `python -m` exists for."""
    script = completion.completion_script("bash")
    assert "register-python-argcomplete" not in script
    # The interpreter is named with forward slashes and quoted: bash eats the backslashes of a
    # Windows path, which is exactly why the emitted script bakes in `textio.norm_path` too.
    py = textio.norm_path(sys.executable)
    out = subprocess.run([BASH, "-c", f'PATH=/usr/bin:/bin; eval "$("{py}" -m agentdata '
                                      f'setup --print-completion bash)"; complete -p ad-pbip'],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert "_agentdata_complete" in out.stdout


@bash_only
def test_sourcing_the_bash_script_twice_is_harmless():
    script = (f'src="$("{sys.executable}" -m agentdata setup --print-completion bash)"\n'
              'eval "$src"\neval "$src"\n'
              'COMP_LINE="ad-pbip ch" COMP_POINT=10 _agentdata_complete\n'
              'printf "%s\\n" "${COMPREPLY[@]}"\n')
    out = subprocess.run([BASH, "-c", script], capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["check"], "a second source changed the answer"


@bash_only
def test_the_bash_script_parses_under_the_floor():
    """bash 4.4 is the floor; `bash -n` on the runner's bash is the cheap half of that check, and
    `tests/test_bash_floor.py` owns the construct-level half."""
    script = completion.completion_script("bash")
    out = subprocess.run([BASH, "-n", "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.mark.skipif(not shutil.which("zsh"), reason="no zsh here")
def test_the_zsh_script_parses():
    out = subprocess.run([shutil.which("zsh"), "-n", "-c", completion.completion_script("zsh")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ------------------------------------------------------------------------ the PowerShell script


def _powershell() -> str | None:
    return shutil.which("pwsh") or (shutil.which("powershell") if os.name == "nt" else None)


PS = _powershell()
ps_only = pytest.mark.skipif(not PS, reason="no PowerShell here")


@ps_only
@pytest.mark.parametrize("line,cursor,expected", [
    ("ad-pbip ch", 10, "check"),
    ("ad-graph ", 9, "summary"),
    ("ad-setup --pri", 14, "--print-completion"),
    ("ad-test run --sel", 17, "--select"),
])
def test_powershell_really_completes(line, cursor, expected):
    """Driven through `TabExpansion2`, which is what a Tab press calls.

    A bare `--` is deliberately not a case: PowerShell does not invoke a native argument completer
    for it at all, so `--sel` is the shortest thing that can be asserted. Noted in README.
    """
    ps = (f"Invoke-Expression (& '{sys.executable}' -m agentdata setup --print-completion powershell "
          f"| Out-String); "
          f"$r = TabExpansion2 -inputScript '{line}' -cursorColumn {cursor}; "
          f"$r.CompletionMatches | ForEach-Object {{ $_.CompletionText }}")
    out = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", ps],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.returncode == 0, out.stderr
    assert expected in out.stdout.split(), out.stdout


@ps_only
def test_the_powershell_completer_has_a_body_that_returns_something():
    """It was a comment. `Register-ArgumentCompleter` was there, the completion never was."""
    script = completion.completion_script("powershell")
    assert "placeholder" not in script.lower()
    assert "CompletionResult" in script
    assert "_complete" in script, "the completer has to call something"


# ------------------------------------------------------------------------------ --print-completion


@pytest.mark.parametrize("shell", ["bash", "zsh", "powershell"])
def test_print_completion_emits_the_script(shell, capsys):
    assert wizard.run_setup(["--print-completion", shell]) == 0
    out = capsys.readouterr().out
    assert completion.MARKER in out
    assert "ad-pbip" in out


def test_an_unknown_shell_is_refused():
    with pytest.raises(ValueError, match="unknown shell"):
        completion.completion_script("fish")


# ------------------------------------------------------------------------------------- --install


def test_install_is_idempotent(tmp_path):
    target = str(tmp_path / ".bashrc")
    first = completion.install("bash", target)
    assert first["changed"] and not first["replaced"]
    body = open(target, encoding="utf-8").read()

    second = completion.install("bash", target)
    assert not second["changed"], "a second install rewrote the file"
    assert open(target, encoding="utf-8").read() == body
    assert body.count(completion.MARKER) == 1


def test_install_keeps_what_was_already_in_the_file(tmp_path):
    target = tmp_path / ".bashrc"
    target.write_text("export PATH=/x:$PATH\nalias ll='ls -l'\n", encoding="utf-8")
    completion.install("bash", str(target))
    body = target.read_text(encoding="utf-8")
    assert "export PATH=/x:$PATH" in body and "alias ll='ls -l'" in body


def test_install_replaces_a_stale_line_rather_than_adding_a_second(tmp_path):
    """The interpreter moves -- a new Python, a rebuilt venv -- and the old line would answer for
    an install that is gone."""
    target = tmp_path / ".bashrc"
    target.write_text(f'eval "$("/old/python" -m agentdata setup --print-completion bash)"  '
                      f'{completion.MARKER}\n', encoding="utf-8")
    result = completion.install("bash", str(target))
    body = target.read_text(encoding="utf-8")
    assert result["replaced"] and body.count(completion.MARKER) == 1
    assert "/old/python" not in body


def test_install_without_print_completion_is_a_usage_error(capsys):
    assert wizard.run_setup(["--install"]) == 2
    assert "--print-completion" in capsys.readouterr().err


def test_the_doctor_reports_where_completion_is_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from agentdata.setup.steps.console import ConsoleStep

    step = ConsoleStep()
    assert completion.where_installed() == []
    completion.install("bash", str(tmp_path / ".bashrc"))
    found = completion.where_installed()
    assert found and found[0][0] == "bash"
    assert step  # the row itself is asserted through the doctor's own tests


def test_the_doctor_row_never_spawns_a_shell(monkeypatch):
    """`ad-doctor` is a dry run; asking PowerShell for `$PROFILE` would break that contract."""
    from agentdata import proc

    def boom(*_a, **_k):
        raise AssertionError("the doctor row spawned a process")

    monkeypatch.setattr(proc, "run", boom)
    completion.where_installed()


# --------------------------------------------------------------------------- argcomplete marker


def test_autocomplete_is_inert_without_env():
    import argparse

    parser = argparse.ArgumentParser(prog="test")
    parser.add_argument("--foo")
    completion.autocomplete(parser)          # must not raise, exit, or complete


def test_python_argcomplete_ok_marker_present_in_entrypoint_files():
    import agentdata

    pkg_dir = os.path.dirname(agentdata.__file__)
    for name in ("cli.py", "cli_setup.py", os.path.join("setup", "wizard.py"), "cli_sqlcheck.py",
                 "cli_jira.py", "cli_pbip.py", "cli_uat.py", "cli_dpm.py", "cli_state.py",
                 "cli_confluence.py", "update.py", "complete.py"):
        path = os.path.join(pkg_dir, name)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "# PYTHON_ARGCOMPLETE_OK" in content, f"{path} missing PYTHON_ARGCOMPLETE_OK marker"
