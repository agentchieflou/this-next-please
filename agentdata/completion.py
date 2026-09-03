# PYTHON_ARGCOMPLETE_OK
"""Shell tab-completion for ad-* commands and python -m agentdata."""
from __future__ import annotations
import argparse
import sys

ALL_COMMANDS = [
    "ad-pncli", "ad-td", "ad-ora", "ad-hive", "ad-impala", "ad-diff", "ad-view",
    "ad-setup", "ad-doctor", "ad-sql-check", "ad-jira", "ad-pbip", "ad-uat",
    "ad-dpm", "ad-state", "ad-confluence", "ad-update", "ad-help",
]


def autocomplete(parser: argparse.ArgumentParser) -> None:
    """Activate argcomplete if installed and completing; inert otherwise."""
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except Exception:
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
