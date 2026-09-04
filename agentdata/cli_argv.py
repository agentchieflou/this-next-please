# PYTHON_ARGCOMPLETE_OK
"""ad-argv: print the argv Python actually received, plus the shell and host it came from.

A diagnostic, not a workflow command, and hidden from the `ad-help` catalog for that reason.

It exists because the same command line means different things in different shells and nobody can
hold all of it in their head: Git Bash rewrites anything that looks like a POSIX path before Python
starts, pwsh expands `$x` inside double quotes, cmd expands `%VAR%`. When a `--jql` or a `--sql`
arrives mangled, this says what arrived rather than what was typed -- and it is the oracle the
per-shell argv tests assert against.
"""
from __future__ import annotations
import argparse
import sys

from . import completion
from . import console as CON
from . import toon
from .console import utf8_stdout
from .version import add_version, version_string
from . import textio


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    raw = list(sys.argv[1:] if argv is None else argv)

    # everything after a bare `--` is data, however shell-like it looks
    if "--" in raw:
        cut = raw.index("--")
        flags, values = raw[:cut], raw[cut + 1:]
    else:
        flags, values = raw, []

    ap = argparse.ArgumentParser(
        prog="ad-argv",
        description="Print the argv Python received. Put the arguments to inspect after `--`.",
    )
    add_version(ap)
    ap.add_argument("--raw", action="store_true", help="print one argument per line, nothing else")
    completion.autocomplete(ap)
    a = ap.parse_args(flags)

    if a.raw:
        for value in values:
            print(value)
        return 0

    payload = {
        "meta": {
            "ok": True,
            "source": "ad-argv",
            "count": len(values),
            "shell": CON.shell(),
            "host": CON.host(),
            "code_page": CON.code_page(),
            "executable": textio.norm_path(sys.executable),
        },
        "argv": values,
    }
    print(toon.encode(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
