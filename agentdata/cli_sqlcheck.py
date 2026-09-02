"""ad-sql-check: dialect pre-flight lint (also runs automatically inside ad-td / ad-ora / ad-hive / ad-impala)."""
from __future__ import annotations
import argparse
import sys
from . import config as C
from . import toon
from .console import utf8_stdout
from .sqlcheck import DIALECTS, check, to_toon


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-sql-check", description="Lint SQL for a dialect before running it. "
                                 "Exit 2 when an error would make the query fail; warnings exit 0.")
    ap.add_argument("--dialect", required=True, choices=DIALECTS)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql")
    g.add_argument("file", nargs="?", help="path to a .sql file")
    ap.add_argument("--env", default=None, help="env whose recorded capabilities gate some rules (default: AGENTS.md fact)")
    a = ap.parse_args()
    sql = a.sql if a.sql is not None else open(a.file, encoding="utf-8").read()
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
