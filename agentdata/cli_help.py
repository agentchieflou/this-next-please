# PYTHON_ARGCOMPLETE_OK
"""ad-help: overview of every ad-* command, or detailed help for one command."""
from __future__ import annotations
import difflib
import importlib
import sys

from .console import utf8_stdout
from .version import version_string


# commands that belong to the Copilot chat window, not to a shell. The first word is what people
# actually type; the value says what it is for.
CHAT_COMMANDS = {
    "plugin": "manage Copilot plugins and marketplaces (`/plugin marketplace add <owner>/<repo>`)",
    "skill": "list or invoke a Copilot skill",
    "agent": "switch the Copilot agent",
    "clear": "clear the Copilot conversation",
    "model": "switch the Copilot model",
}


def _chat_surface(target: str, args: list[str]) -> str:
    """A one-screen answer for a Copilot-chat command typed into a terminal, or ""."""
    word = target.lstrip("/").split()[0].lower() if target.strip() else ""
    if word not in CHAT_COMMANDS:
        return ""
    rest = " ".join(args[1:])
    typed = f"/{word}" + (f" {rest}" if rest else "")
    return (
        f"`{typed}` is a Copilot chat command, not a shell command.\n\n"
        f"  what it does   {CHAT_COMMANDS[word]}\n"
        f"  where to type  the Copilot chat window (PyCharm, VS Code, or the CLI's chat), never a terminal\n\n"
        "A terminal answers `bash: /plugin: No such file or directory` or "
        "`'/plugin' is not recognized`, which reads like a missing tool rather than a wrong window.\n"
        "Everything this package installs is an `ad-*` command or `python -m agentdata <command>`, "
        "and those run in any shell -- see docs/shells.md for which command belongs where."
    )


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

    if target.startswith("-"):
        # a mistyped flag used to print the catalogue and exit 0, so a typo looked like success
        sys.stderr.write(
            f"unknown option {target!r}. `ad-help` takes a command name, not a flag.\n"
            "Run 'ad-help' for the catalog, or 'ad-help --help' for its own usage.\n")
        return 2

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

    # Not a shell command at all: a Copilot-chat slash command typed into a terminal. This has
    # actually happened (`/plugin marketplace add ...` in a MINGW64 tab, answered with
    # "bash: /plugin: No such file or directory"), so say where it belongs instead of guessing at
    # a near-miss among the ad-* names.
    chat = _chat_surface(target, args)
    if chat:
        print(chat)
        return 0

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
