# PYTHON_ARGCOMPLETE_OK
"""Shell tab-completion for ad-* commands and python -m agentdata."""
from __future__ import annotations
import argparse
import os
import sys

ALL_COMMANDS = [
    "ad-pncli", "ad-td", "ad-ora", "ad-hive", "ad-impala", "ad-diff", "ad-view",
    "ad-setup", "ad-doctor", "ad-sql-check", "ad-jira", "ad-pbip", "ad-uat",
    "ad-dpm", "ad-state", "ad-confluence", "ad-update", "ad-help",
]


PARSE_ONLY = "AGENTDATA_PARSE_ONLY"


def _parse_only_wrapper(parser: argparse.ArgumentParser) -> None:
    """With AGENTDATA_PARSE_ONLY=1, stop after parsing and print what was parsed.

    This is how every command line printed in a skill, a doc or the README is checked against the
    real parser: the arguments are validated, and then nothing is read, launched or written. Wiring
    it here rather than into each `main()` means a new command cannot forget it -- every parser in
    this package already calls `autocomplete()` immediately before `parse_args()`.
    """
    if os.environ.get(PARSE_ONLY) != "1":
        return
    original = parser.parse_args

    def parse_and_stop(args=None, namespace=None):
        parsed = original(args, namespace)
        from . import toon

        payload = {k: ("" if v is None else v) for k, v in sorted(vars(parsed).items())
                   if not callable(v)}
        print(toon.encode({"meta": {"ok": True, "source": parser.prog, "parse_only": True},
                           "args": payload}))
        raise SystemExit(0)

    parser.parse_args = parse_and_stop           # type: ignore[method-assign]


def autocomplete(parser: argparse.ArgumentParser) -> None:
    """Activate argcomplete if installed and completing; inert otherwise.

    Also the single place `AGENTDATA_PARSE_ONLY` is honoured -- see `_parse_only_wrapper`.
    """
    _parse_only_wrapper(parser)
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except Exception:  # noqa: BLE001  argcomplete is optional and must never break a real run
        pass


def completion_script(shell: str, commands: list[str] | None = None) -> str:
    cmds = commands or ALL_COMMANDS
    cmd_str = " ".join(cmds)
    shell = shell.lower().strip()
    if shell == "bash":
        return f"""# bash completion for agentdata ad-* commands
# Activate with: eval "$(ad-setup --print-completion bash)"
# Requires: pip install "agentdata[completion]"
if command -v register-python-argcomplete >/dev/null 2>&1; then
    eval "$(register-python-argcomplete {cmd_str})"
fi
"""
    elif shell == "zsh":
        return f"""# zsh completion for agentdata ad-* commands
# Activate with: eval "$(ad-setup --print-completion zsh)"
# Requires: pip install "agentdata[completion]"
autoload -U +X bashcompinit && bashcompinit
if command -v register-python-argcomplete >/dev/null 2>&1; then
    eval "$(register-python-argcomplete {cmd_str})"
fi
"""
    elif shell == "powershell":
        return f"""# PowerShell completion for agentdata ad-* commands
# Note: argcomplete is primarily designed for bash/zsh; for PowerShell,
# you can register argument completers using Register-ArgumentCompleter:
$commands = @({", ".join(f'"{c}"' for c in cmds)})
foreach ($c in $commands) {{
    Register-ArgumentCompleter -Native -CommandName $c -ScriptBlock {{
        param($wordToComplete, $commandAst, $cursorPosition)
        # Tab-completion placeholder; native argcomplete support is bash/zsh-only.
        # Run `$c --help` to view available options.
    }}
}}
"""
    else:
        raise ValueError(f"unknown shell: {shell!r} (choose bash, zsh, powershell)")


def print_completion(shell: str) -> None:
    sys.stdout.write(completion_script(shell))
    sys.stdout.flush()
