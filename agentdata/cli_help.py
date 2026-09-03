# PYTHON_ARGCOMPLETE_OK
"""ad-help: overview of every ad-* command, or detailed help for one command."""
from __future__ import annotations
import difflib
import importlib
import sys

from .console import utf8_stdout
from .version import version_string


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    args = list(sys.argv[1:] if argv is None else argv)
    from . import __main__ as M
    commands = M.COMMANDS

    if not args:
        M.usage()
        return 0

    target = args[0].strip()

    if target in ("-v", "--version"):
        print(version_string())
        return 0

    if target in ("-h", "--help") and len(args) == 1:
        print("usage: ad-help [command]\n\n"
              "Print the agentdata command catalog, or detailed help for a specific command.\n\n"
              "Examples:\n"
              "  ad-help          # list all commands\n"
              "  ad-help pbip     # show help for ad-pbip\n"
              "  ad-help jira     # show help for ad-jira\n")
        return 0

    # Strip optional ad- prefix if user typed e.g. ad-pbip
    cmd_name = target[3:] if target.startswith("ad-") else target

    if cmd_name in commands:
        mod_name, func_name, _ = commands[cmd_name]
        try:
            mod = importlib.import_module(mod_name)
            func = getattr(mod, func_name)
            try:
                rc = func(["--help"])
            except TypeError:
                # If function does not accept argv
                old_argv = sys.argv
                sys.argv = [f"ad-{cmd_name}", "--help"]
                try:
                    rc = func()
                finally:
                    sys.argv = old_argv
            return rc if isinstance(rc, int) else 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0

    # Command not found: look for close matches
    candidates = list(commands.keys()) + [f"ad-{k}" for k in commands.keys()]
    matches = difflib.get_close_matches(target, candidates, n=1, cutoff=0.5)
    if matches:
        suggestion = matches[0]
        if not suggestion.startswith("ad-"):
            suggestion = f"ad-{suggestion}"
        sys.stderr.write(f"unknown command {target!r}. Did you mean {suggestion!r}?\n"
                         f"Run 'ad-help' to see all available commands.\n")
    else:
        sys.stderr.write(f"unknown command {target!r}. Run 'ad-help' to see all available commands.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
