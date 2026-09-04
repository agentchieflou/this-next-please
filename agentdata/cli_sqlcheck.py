# PYTHON_ARGCOMPLETE_OK
"""ad-sql-check: dialect pre-flight lint (also runs automatically inside ad-td / ad-ora / ad-hive / ad-impala)."""
from __future__ import annotations
import argparse
import sys
from .textio import read_text
from . import completion
from . import config as C
from . import toon
from . import version
from .console import utf8_stdout
from .policy import error
from .sqlcheck import DIALECTS, check, to_toon

import re

# a variable the shell was supposed to expand and did not: the SQL will be wrong in a way the
# database reports as a syntax error a hundred lines later
_UNEXPANDED = re.compile(r"(\$env:[A-Za-z_][\w]*|%[A-Za-z_][\w]*%|\$\{[A-Za-z_][\w]*\})")
SHELL_QUOTING_HINT = {
    "$": "pwsh expands $x inside double quotes only: use \"...$env:X...\" to interpolate, or single quotes to keep it literal",
    "%": "cmd expands %X% only when the variable is set; in pwsh and bash %X% is literal text -- use the shell's own syntax",
}


def unexpanded_variable(sql: str) -> str:
    m = _UNEXPANDED.search(sql or "")
    return m.group(1) if m else ""


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-sql-check", description="Lint SQL for a dialect before running it. "
                                 "Exit 2 when an error would make the query fail; warnings exit 0.")
    version.add_version(ap)
    ap.add_argument("--dialect", required=True, choices=DIALECTS)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql")
    g.add_argument("file", nargs="?", help="path to a .sql file")
    ap.add_argument("--env", default=None, help="env whose recorded capabilities gate some rules (default: AGENTS.md fact)")
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    sql = a.sql if a.sql is not None else read_text(a.file)

    if a.sql is not None:
        leaked = unexpanded_variable(a.sql)
        if leaked:
            print(error(f"--sql still contains {leaked!r}: your shell did not expand it",
                        SHELL_QUOTING_HINT[leaked[:1]], "ad-sql-check"))
            return 2
    facts = C.project_facts()
    env = a.env or facts.get(f"{a.dialect}_env") or (facts.get("env") if a.dialect == "teradata" else None)
    caps = {}
    try:
        if env:
            caps = C.capabilities(C.load(), a.dialect, env)
    except C.ConfigError:
        caps = {}
    findings = check(sql, a.dialect, caps)
    print(to_toon(findings, a.dialect, {"env": env or "", "capabilities": len(caps)}))
    sys.exit(2 if any(f.severity == "error" for f in findings) else 0)


if __name__ == "__main__":
    sys.exit(main())
