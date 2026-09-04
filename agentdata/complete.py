# PYTHON_ARGCOMPLETE_OK
"""`python -m agentdata _complete` — the completer every shell calls.

argcomplete only speaks bash and zsh, and only when `register-python-argcomplete` is on PATH, which
on a Windows laptop it usually is not (it lands in the `Scripts` directory that is the reason
`python -m agentdata` exists at all). So the completion lives here instead: one hidden verb that
walks the argparse tree and prints one candidate per line, and three tiny shell scripts that call
it. Nothing to install, nothing extra to import, and the same answers in Git Bash, pwsh 7 and
Windows PowerShell 5.1.

Two protocols, because bash and PowerShell disagree about who tokenises:

* **bash** exports `COMP_LINE` and `COMP_POINT` and reads lines from stdout. Called with no
  arguments, that is what this reads.
* **PowerShell** hands a completer the command AST and a cursor offset, so its script passes
  `--line` and `--cursor`.

The parser is obtained by running the command's own `main()` until it calls
`completion.autocomplete()`, which every parser in this package does immediately before
`parse_args()`. That call raises `ParserCaptured` when this module asks it to, so nothing after it
runs: no config is read, no file is opened, no network is touched. It is the same seam
`AGENTDATA_PARSE_ONLY` uses, for the same reason -- a new command cannot forget to be completable.
"""
from __future__ import annotations
import argparse
import io
import os
import sys
from typing import Iterable

# Both live in `completion`, next to the `autocomplete()` that raises: the raiser owns the contract,
# and importing them from there keeps this module off every command's start-up path.
from .completion import COMPLETE_ENV as ENV, ParserCaptured, all_commands


# --------------------------------------------------------------------------------- the argv seam


def _split(line: str, cursor: int) -> tuple[list[str], str]:
    """(words before the cursor, the partial word under it).

    Quoting is deliberately shallow: a completer that guessed at quotes would be wrong in a
    different way in each of the three shells. What matters is the word boundary.
    """
    head = line[:cursor] if cursor >= 0 else line
    words = head.split()
    partial = "" if not head or head[-1].isspace() else (words.pop() if words else "")
    return words, partial


def _from_environment() -> tuple[list[str], str] | None:
    line, point = os.environ.get("COMP_LINE"), os.environ.get("COMP_POINT")
    if line is None:
        return None
    try:
        cursor = int(point) if point is not None else len(line)
    except ValueError:
        cursor = len(line)
    return _split(line, cursor)


# ------------------------------------------------------------------------------ the parser walk


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:                     # noqa: SLF001 - argparse has no public API
        if isinstance(action, argparse._SubParsersAction):   # noqa: SLF001
            return dict(action.choices)
    return {}


def _options(parser: argparse.ArgumentParser) -> list[str]:
    out: list[str] = []
    for action in parser._actions:                     # noqa: SLF001
        if action.help == argparse.SUPPRESS:
            continue
        out += list(action.option_strings)
    return out


def _value_choices(parser: argparse.ArgumentParser, previous: str) -> list[str]:
    """The choices of the option `previous` expects a value for, if it has any."""
    if not previous.startswith("-"):
        return []
    for action in parser._actions:                     # noqa: SLF001
        if previous in action.option_strings and action.nargs != 0 and action.choices:
            return [str(c) for c in action.choices]
    return []


def _descend(parser: argparse.ArgumentParser, words: Iterable[str]) -> tuple[argparse.ArgumentParser, str]:
    """Follow the subcommands in `words`. Returns the deepest parser and the last word seen."""
    current, previous = parser, ""
    for word in words:
        subs = _subparsers(current)
        if word in subs:
            current, previous = subs[word], ""
        else:
            previous = word
    return current, previous


def candidates(parser: argparse.ArgumentParser, words: list[str], partial: str) -> list[str]:
    """Everything that could follow, filtered by what has been typed so far."""
    deepest, previous = _descend(parser, words)
    values = _value_choices(deepest, previous)
    if values:                                   # an option that takes one of a fixed set wins
        pool = values
    else:
        pool = sorted(_subparsers(deepest)) + _options(deepest)
        for action in deepest._actions:          # noqa: SLF001 - a positional with choices
            if not action.option_strings and action.choices and not isinstance(
                    action, argparse._SubParsersAction):    # noqa: SLF001
                pool += [str(c) for c in action.choices]
    seen, out = set(), []
    for item in pool:
        if item.startswith(partial) and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# -------------------------------------------------------------------------- getting to a parser


def parser_for(command: str) -> argparse.ArgumentParser | None:
    """The parser `ad-<command>` builds, without letting the command run.

    Returns None for a command that has no argparse parser (`ad-help` hand-rolls its arguments), so
    a caller can fall back to the command list rather than print a traceback into a completion.
    """
    from . import __main__ as M

    name = command[3:] if command.startswith("ad-") else command
    entry = M.COMMANDS.get(name)
    if not entry:
        return None
    module, func, _help = entry
    __import__(module)
    main = getattr(sys.modules[module], func)

    saved_argv, saved_env = sys.argv, os.environ.get(ENV)
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.argv = [f"ad-{name}"]
    os.environ[ENV] = "1"
    # Anything the prologue prints would land in the middle of the candidate list -- `ad-help` has
    # no parser at all and printed its whole catalog into a tab press before this was here.
    sys.stdout = sys.stderr = io.StringIO()
    try:
        try:
            main([])
        except TypeError:
            # `ad-setup` and `ad-doctor` take no argv and read `sys.argv` themselves; the same
            # fallback `ad-help` uses, and the reason `sys.argv` is set above rather than passed.
            main()
    except ParserCaptured as captured:
        return captured.parser
    except BaseException:                        # noqa: BLE001 - a keypress must never traceback
        return None
    finally:
        sys.argv, sys.stdout, sys.stderr = saved_argv, saved_out, saved_err
        if saved_env is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = saved_env
    return None


def complete(line: str, cursor: int | None = None) -> list[str]:
    """The candidates for a command line, as the shell scripts ask for them."""
    words, partial = _split(line, len(line) if cursor is None else cursor)
    if not words:                                # completing the command name itself
        return [c for c in all_commands() if c.startswith(partial)]
    parser = parser_for(words[0])
    if parser is None:
        # `ad-help` hand-rolls its arguments, and what it takes is a command name.
        if words[0].endswith("help") and len(words) == 1:
            every = all_commands()
            names = sorted(set(every) | {c[3:] for c in every})
            return [c for c in names if c.startswith(partial)]
        return []
    return candidates(parser, words[1:], partial)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    line, cursor = None, None
    i = 0
    while i < len(args):
        if args[i] == "--line" and i + 1 < len(args):
            line, i = args[i + 1], i + 2
        elif args[i] == "--cursor" and i + 1 < len(args):
            try:
                cursor = int(args[i + 1])
            except ValueError:
                cursor = None
            i += 2
        elif args[i] in ("-h", "--help"):
            print("usage: python -m agentdata _complete [--line LINE --cursor N]\n\n"
                  "Prints one completion candidate per line. With no arguments it reads COMP_LINE\n"
                  "and COMP_POINT, which is the protocol bash's `complete -F` wrapper uses.")
            return 0
        else:
            i += 1

    if line is None:
        from_env = _from_environment()
        if from_env is None:
            return 0                             # nothing to complete; silence is the right output
        words, partial = from_env
        line, cursor = " ".join(words + [partial]), None
        if partial == "":
            line += " "

    # LF, always. On Windows `print()` writes CRLF, and bash's `mapfile -t` strips only the newline
    # -- so every candidate came back as `check\r` and the shell would have inserted the carriage
    # return into the command line. CI caught it with `got: check` failing a comparison against
    # "check", which is exactly the kind of thing a string test on the script cannot see.
    rc = getattr(sys.stdout, "reconfigure", None)
    if rc is not None:
        try:
            rc(newline="\n")
        except Exception:  # noqa: BLE001 - a keypress must never traceback
            pass
    for item in complete(line, cursor):
        sys.stdout.write(item + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
