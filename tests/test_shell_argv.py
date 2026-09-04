"""What argv actually arrives, per shell, for the arguments `ad-*` commands really take.

Every row here was run before it was written down. The table is the contract: where a shell mangles
something, either the code was fixed or `docs/shells.md` states the rule — and this file is what
stops either drifting.

Shells absent from the machine are skipped, so the same file runs on Linux CI (bash only) and on the
Windows matrix (bash, pwsh, cmd).
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"


def _argv_via(shell: str, inner: str) -> list[str]:
    """Run `python -m agentdata argv --raw -- <inner>` through `shell` and return the argv seen."""
    py = sys.executable.replace("\\", "/")
    command = f'"{py}" -m agentdata argv --raw -- {inner}'
    if shell == "bash":
        argv = ["bash", "-c", command]
    elif shell == "pwsh":
        argv = ["pwsh", "-NoProfile", "-Command", command]
    elif shell == "cmd":
        # a STRING, not a list: through list2cmdline the inner quotes get backslash-escaped and
        # cmd.exe answers "is not recognized" (HANDOFF.md documents this; proc.py does the same)
        argv = f'cmd /d /s /c "{command}"'
    else:
        raise AssertionError(shell)

    p = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT, encoding="utf-8", errors="replace")
    assert p.returncode == 0, f"{shell}: {p.stderr}"
    return p.stdout.replace("\r\n", "\n").split("\n")[:-1]


def _have(shell: str) -> bool:
    return shutil.which(shell) is not None


requires_bash = pytest.mark.skipif(not _have("bash"), reason="bash is not installed")
requires_pwsh = pytest.mark.skipif(not _have("pwsh"), reason="pwsh 7 is not installed")
requires_cmd = pytest.mark.skipif(not WINDOWS, reason="cmd.exe is Windows-only")


# --------------------------------------------------------------------------------- Git Bash / MSYS


@requires_bash
def test_bash_passes_ordinary_arguments_through():
    assert _argv_via("bash", "'a >= b' 'project = X' 'SELECT 1'") == ["a >= b", "project = X", "SELECT 1"]


@requires_bash
def test_bash_keeps_a_dollar_literal_in_single_quotes():
    assert _argv_via("bash", "'literal $KEY'") == ["literal $KEY"]


@requires_bash
def test_bash_expands_a_dollar_in_double_quotes():
    assert _argv_via("bash", 'KEY=RDSD; "$0" >/dev/null 2>&1; echo') != []   # keep the shell honest
    out = subprocess.run(
        ["bash", "-c", f'KEY=RDSD; "{sys.executable}" -m agentdata argv --raw -- "project = $KEY"'],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.strip() == "project = RDSD"


@requires_bash
def test_bash_survives_non_ascii_and_an_empty_argument():
    assert _argv_via("bash", "'é→' '' 'x'") == ["é→", "", "x"]


@pytest.mark.skipif(not (WINDOWS and _have("bash")), reason="MSYS path conversion is a Git Bash on Windows thing")
def test_msys_rewrites_a_posix_looking_argument():
    """The documented hazard, and the exact example in tests/test_entrypoints.py.

    `-s /nope` does not reach Python as `/nope`: MSYS decides it is a path and prefixes the Git
    installation root. This is not a bug we can fix from inside Python -- it happens before the
    process starts -- so it is a rule, and `docs/shells.md` states it.
    """
    got = _argv_via("bash", "-s /nope")
    assert got[0] == "-s"
    assert got[1] != "/nope", "MSYS converted nothing; the rule in docs/shells.md may be stale"
    assert got[1].lower().endswith("/nope") and ":" in got[1]


@pytest.mark.skipif(not (WINDOWS and _have("bash")), reason="MSYS path conversion is a Git Bash on Windows thing")
def test_msys_no_pathconv_is_the_escape_hatch():
    out = subprocess.run(
        ["bash", "-c", f'MSYS_NO_PATHCONV=1 "{sys.executable}" -m agentdata argv --raw -- -s /nope'],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.replace("\r\n", "\n").split("\n")[:-1] == ["-s", "/nope"]


@pytest.mark.skipif(not (WINDOWS and _have("bash")), reason="MSYS path conversion is a Git Bash on Windows thing")
def test_a_c_slash_path_is_converted_helpfully():
    got = _argv_via("bash", "/c/Users")
    assert got == ["C:/Users"], "this conversion is the useful half, and config.expand does it too"


# -------------------------------------------------------------------------------------- pwsh 7


@requires_pwsh
def test_pwsh_expands_a_variable_inside_double_quotes():
    """The JQL hazard: `--jql "project = $KEY"` silently empties when KEY is unset."""
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-Command",
         f'$KEY = "RDSD"; & "{sys.executable}" -m agentdata argv --raw -- "project = $KEY"'],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.strip() == "project = RDSD"


@requires_pwsh
def test_pwsh_keeps_single_quotes_literal():
    out = subprocess.run(
        ["pwsh", "-NoProfile", "-Command",
         f"& '{sys.executable}' -m agentdata argv --raw -- 'literal $KEY'"],
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.strip() == "literal $KEY"


@requires_pwsh
def test_pwsh_passes_comparison_operators_and_percent_literally():
    got = _argv_via("pwsh", "'a >= b' '%PATH%'")
    assert got == ["a >= b", "%PATH%"], "only cmd expands %VAR%"


@requires_pwsh
def test_pwsh_native_argument_passing_keeps_an_embedded_quote():
    """pwsh 7.3+ defaults `$PSNativeCommandArgumentPassing` to `Standard` on Windows, which stops
    re-quoting native arguments. Windows PowerShell 5.1 strips the inner quotes; pwsh 7 keeps them.
    Pinned here so an upgrade that changes it is visible rather than mysterious."""
    got = _argv_via("pwsh", """'say "hi"'""")
    assert got == ['say "hi"'], f"embedded quotes did not survive: {got!r}"


@requires_pwsh
def test_pwsh_survives_non_ascii():
    assert _argv_via("pwsh", "'é→'") == ["é→"]


# ---------------------------------------------------------------------------------------- cmd


@requires_cmd
def test_cmd_expands_a_variable_from_the_environment():
    env = dict(os.environ, MYVAR="hello")
    out = subprocess.run(
        f'cmd /d /s /c ""{sys.executable}" -m agentdata argv --raw -- %MYVAR%"',
        capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    assert out.stdout.replace("\r\n", "\n").split("\n")[:-1] == ["hello"]


@requires_cmd
def test_cmd_expands_at_parse_time_not_at_run_time():
    """`set X=v && use %X%` does not work: cmd substitutes the whole line before `set` runs.

    Worth pinning rather than working around -- it is the reason a one-liner that "obviously" should
    work quietly passes the literal text through instead.
    """
    out = subprocess.run(
        f'cmd /d /s /c "set LATE=hello&& "{sys.executable}" -m agentdata argv --raw -- %LATE%"',
        capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.replace("\r\n", "\n").split("\n")[:-1] == ["%LATE%"]


@requires_cmd
def test_cmd_passes_a_quoted_argument_with_spaces():
    assert _argv_via("cmd", '"a >= b"') == ["a >= b"]


@requires_cmd
def test_cmd_handles_a_program_files_path():
    got = _argv_via("cmd", '"C:\\Program Files\\Git\\bin"')
    assert got == ["C:\\Program Files\\Git\\bin"]


# --------------------------------------------------------------------- the fixes those forced


def test_config_expand_accepts_an_msys_path():
    from agentdata import config

    if WINDOWS:
        assert config.expand("/c/Users/x") == "C:/Users/x"
        assert config.expand("/d/data") == "D:/data"
    assert config.expand("C:/already") == "C:/already"
    assert config.expand("relative/path") == "relative/path"


def test_children_we_spawn_are_not_path_converted():
    """A person typing `-s /nope` gets MSYS's conversion; an argv *we* built must arrive intact."""
    from agentdata import proc

    env = proc.child_env({"PATH": os.environ.get("PATH", "")})
    if WINDOWS:
        assert env["MSYS_NO_PATHCONV"] == "1"
        assert env["MSYS2_ARG_CONV_EXCL"] == "*"
    assert "PATH" in env


def test_an_existing_setting_is_not_overridden():
    from agentdata import proc

    env = proc.child_env({"MSYS_NO_PATHCONV": "0"})
    assert env["MSYS_NO_PATHCONV"] == "0", "a caller that set it deliberately wins"


def test_sql_check_refuses_an_unexpanded_variable():
    from agentdata.cli_sqlcheck import main, unexpanded_variable

    assert unexpanded_variable("SELECT * FROM %DB%.t") == "%DB%"
    assert unexpanded_variable("SELECT $env:DB") == "$env:DB"
    assert unexpanded_variable("SELECT 1") == ""
    assert main(["--dialect", "teradata", "--sql", "SELECT * FROM %DB%.t"]) == 2


# ------------------------------------------------------------------------------- the argv verb


def test_the_argv_verb_reports_what_it_received(capsys):
    from agentdata.cli_argv import main

    assert main(["--", "a >= b", "$KEY", ""]) == 0
    out = capsys.readouterr().out
    assert "shell:" in out and "host:" in out
    assert "count: 3" in out


def test_the_argv_verb_is_hidden_from_the_catalog():
    from agentdata import __main__ as M

    assert "argv" in M.COMMANDS, "it is a real command"
    assert "argv" in M.HIDDEN
    assert "ad-argv" not in M.USAGE, "and it stays out of the list a person reads"


def test_raw_mode_prints_one_argument_per_line(capsys):
    from agentdata.cli_argv import main

    assert main(["--raw", "--", "one", "two three"]) == 0
    assert capsys.readouterr().out == "one\ntwo three\n"


# --------------------------------------------------------------------------------------- docs


def test_shells_doc_covers_every_shell_and_surface():
    text = open(os.path.join(REPO_ROOT, "docs", "shells.md"), encoding="utf-8").read()
    for needle in ("pwsh", "Git Bash", "cmd.exe", "Copilot chat", "MSYS_NO_PATHCONV",
                   "PSNativeCommandArgumentPassing", "Windows PowerShell 5.1"):
        assert needle in text, f"docs/shells.md does not mention {needle}"


def test_readme_links_the_shells_doc():
    text = open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8").read()
    assert "docs/shells.md" in text


def test_ad_help_explains_a_copilot_chat_command(capsys):
    from agentdata.cli_help import main

    assert main(["/plugin"]) == 0
    out = capsys.readouterr().out
    assert "Copilot" in out and "chat" in out.lower()

    assert main(["plugin marketplace"]) == 0
    assert "Copilot" in capsys.readouterr().out
