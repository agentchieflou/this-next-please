"""Every `ad-*` command, read from its own argparse parser, so `tnp` can list, search and run all of them.

The parsers come from `complete.parser_for`, which runs a command's `main()` only until it builds its parser (the
same walk tab-completion uses), so nothing here can drift from the real commands: a new subcommand or flag shows
up in `tnp` the day it lands. A command runs as `python -m agentdata <name> ...` with the person's own terminal,
so its own dry run, approval prompt and output are exactly what `ad-<name>` shows.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass, field

from .. import __main__ as M
from .. import complete

SUPPRESS = argparse.SUPPRESS


@dataclass
class Arg:
    dest: str
    flags: list[str]
    help: str
    takes_value: bool
    choices: list[str]
    required: bool
    nargs: object
    metavar: str

    @property
    def name(self) -> str:
        return self.flags[0] if self.flags else (self.metavar or self.dest)


@dataclass
class Command:
    path: tuple[str, ...]                    # ("pbip", "check")
    help: str
    parser: argparse.ArgumentParser | None
    children: list["Command"] = field(default_factory=list)

    @property
    def title(self) -> str:
        return " ".join(("ad-" + self.path[0], *self.path[1:]))

    @property
    def usage(self) -> str:
        if self.parser is None:
            return self.title
        from .. import color
        text = color.strip(self.parser.format_usage()).strip()    # 3.14's argparse colours it on a terminal
        return re.sub(r"^usage:\s*", "", text)

    def arguments(self) -> tuple[list[Arg], list[Arg]]:
        """(positionals, options), help and version left out."""
        pos, opt = [], []
        if self.parser is None:
            return pos, opt
        for a in self.parser._actions:                         # noqa: SLF001 - argparse has no public walk
            if isinstance(a, (argparse._HelpAction, argparse._VersionAction, argparse._SubParsersAction)):  # noqa: SLF001
                continue
            if a.help == SUPPRESS:
                continue
            arg = Arg(a.dest, list(a.option_strings), a.help or "", a.nargs != 0,
                      [str(c) for c in a.choices] if a.choices else [], bool(getattr(a, "required", False)),
                      a.nargs, a.metavar if isinstance(a.metavar, str) else "")
            (opt if a.option_strings else pos).append(arg)
        return pos, opt


def _children(parser: argparse.ArgumentParser | None, path: tuple[str, ...]) -> list[Command]:
    out: list[Command] = []
    if parser is None:
        return out
    for a in parser._actions:                                  # noqa: SLF001
        if not isinstance(a, argparse._SubParsersAction):     # noqa: SLF001
            continue
        helps = {c.dest: (c.help or "") for c in a._choices_actions}  # noqa: SLF001
        seen: set[int] = set()
        for name, sub in a.choices.items():
            if id(sub) in seen or helps.get(name) == SUPPRESS:  # an alias of one already listed, or hidden
                continue
            seen.add(id(sub))
            cmd = Command((*path, name), helps.get(name, "") or (sub.description or "").split("\n")[0], sub)
            cmd.children = _children(sub, cmd.path)
            out.append(cmd)
    return out


_CATALOG: list[Command] | None = None


def catalog() -> list[Command]:
    """The top-level commands, each with its subcommands, in the order `ad-help` lists them."""
    global _CATALOG
    if _CATALOG is None:
        roots = []
        for name, (_module, _func, help_text) in M.COMMANDS.items():
            if name in M.HIDDEN:
                continue
            parser = complete.parser_for(f"ad-{name}")
            cmd = Command((name,), help_text, parser)
            cmd.children = _children(parser, cmd.path)
            roots.append(cmd)
        _CATALOG = roots
    return _CATALOG


def walk(cmds: list[Command] | None = None):
    for c in cmds if cmds is not None else catalog():
        yield c
        yield from walk(c.children)


def find(words: str) -> list[Command]:
    """Commands whose name or help holds every word; a match in the name ranks first."""
    terms = [w for w in words.lower().split() if w]
    if not terms:
        return []
    hits = []
    for c in walk():
        name, text = c.title.lower(), (c.title + " " + c.help).lower()
        if not all(t in text for t in terms):
            continue
        words = name.replace("ad-", "").split()
        if all(t in words for t in terms):
            rank = 0                                  # every word is a part of the name: `pr` -> `ad-git pr`
        elif all(any(w.startswith(t) for w in words) for t in terms):
            rank = 1                                  # ... or starts one: `pre` -> `ad-fleet preflight`
        elif all(t in name for t in terms):
            rank = 2
        else:
            rank = 3                                  # only the description says it
        hits.append((rank, len(c.path), c.title, c))
    return [h[-1] for h in sorted(hits, key=lambda h: h[:3])]


def argv(cmd: Command, values: list[str]) -> list[str]:
    """What actually runs: the module form, so it works where `ad-*` is not on PATH."""
    return [sys.executable, "-m", "agentdata", cmd.path[0], *cmd.path[1:], *values]


def shown(cmd: Command, values: list[str]) -> str:
    """What a person would type."""
    return " ".join([cmd.title, *(shlex.quote(v) for v in values)])


def reset() -> None:
    global _CATALOG
    _CATALOG = None
