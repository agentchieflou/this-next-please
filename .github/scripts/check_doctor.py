"""Assert `ad-doctor`'s documented contract, from whichever shell invoked us.

Kept in Python rather than written three times in bash, PowerShell and cmd: the parsing is fiddly
and three near-copies would drift. Each smoke script pipes `ad-doctor --quiet` in here.

The contract (docs/setup.md, and `ad-doctor`'s own --help):
  * exit 0 when everything passes, exit 1 when a row fails -- never anything else
  * stdout is TOON, always, whatever the shell or code page
  * every `fail` row carries a `hint`, because `ad-setup --patch` re-asks exactly those
"""
from __future__ import annotations
import argparse
import sys

sys.path.insert(0, ".")
from agentdata import toon  # noqa: E402  (after the path fix, so a checkout without install works)


def rows(text: str) -> tuple[list[str], list[list[str]]]:
    """(columns, data rows) of the `checks[...]` table, or ([], []) when --quiet printed none."""
    cols: list[str] = []
    out: list[list[str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("checks[") and stripped.endswith(":"):
            cols = stripped.split("{", 1)[1].split("}", 1)[0].split(",")
            in_table = True
            continue
        if in_table:
            if not line.startswith("  ") or not stripped:
                in_table = False
                continue
            out.append([f.strip().strip('"') for f in toon._split_row(stripped)])
    return cols, out


def main() -> int:
    ap = argparse.ArgumentParser(description="Check ad-doctor's exit code and TOON contract.")
    ap.add_argument("--exit-code", type=int, required=True, help="the code ad-doctor actually returned")
    ap.add_argument("--shell", default="?", help="the shell this ran under, for the failure message")
    a = ap.parse_args()

    text = sys.stdin.read()
    problems: list[str] = []

    if a.exit_code not in (0, 1):
        problems.append(f"exited {a.exit_code}; the contract is 0 (clean) or 1 (a row failed)")

    for p in toon.validate(text):
        problems.append(f"stdout is not TOON: {p}")

    cols, data = rows(text)
    if cols:
        try:
            i_status, i_hint = cols.index("status"), cols.index("hint")
        except ValueError:
            problems.append(f"checks table has no status/hint column: {cols}")
        else:
            failed = [r for r in data if len(r) > max(i_status, i_hint) and r[i_status] == "fail"]
            for r in failed:
                if not r[i_hint]:
                    problems.append(f"fail row {r[0]}/{r[1]} carries no hint")
            if failed and a.exit_code != 1:
                problems.append(f"{len(failed)} fail row(s) but exit code {a.exit_code}")
            if not failed and a.exit_code == 1:
                problems.append("exit 1 with no fail row to explain it")

    if problems:
        print(f"ad-doctor contract broken under {a.shell}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"ad-doctor contract ok under {a.shell} (exit {a.exit_code}, {len(data)} row(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
