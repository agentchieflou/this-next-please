"""Per-module coverage floors for the files the laptop keeps breaking.

There is deliberately **no repo-wide number**. A single percentage invites padding -- a test that
imports a module and asserts nothing raises the figure without proving anything -- and it says
nothing about the modules that actually go wrong on Windows. These seven do:

    proc.py     launching npm shims, PATHEXT, cmd quoting
    textio.py   BOMs, UTF-16, code pages, locked targets, long paths
    update.py   pip and gh failures nobody sees the real text of
    console.py  hosts, code pages, secret input
    color.py    VT enabling, the piped-output contract
    state.py    the only writer of state.json
    config.py   where every setting comes from

Floors ratchet: `--update` writes the current numbers back, rounded down to the nearest 5, and the
file is committed. They never go down without someone editing it deliberately.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

FLOORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coverage-floors.json")
MODULES = ["agentdata/proc.py", "agentdata/textio.py", "agentdata/update.py",
           "agentdata/console.py", "agentdata/color.py", "agentdata/state.py", "agentdata/config.py"]


def load_floors() -> dict[str, int]:
    if not os.path.isfile(FLOORS_PATH):
        return {m: 0 for m in MODULES}
    with open(FLOORS_PATH, encoding="utf-8") as f:
        return json.load(f)


def measured(coverage_json: str) -> dict[str, float]:
    with open(coverage_json, encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, float] = {}
    for path, entry in (data.get("files") or {}).items():
        normal = path.replace("\\", "/")
        for module in MODULES:
            if normal.endswith(module):
                out[module] = float(entry["summary"]["percent_covered"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coverage-json", default="coverage.json")
    ap.add_argument("--update", action="store_true", help="ratchet the floors up to the current numbers")
    a = ap.parse_args()

    if not os.path.isfile(a.coverage_json):
        print(f"no {a.coverage_json}; run `coverage json` first", file=sys.stderr)
        return 2

    floors, now = load_floors(), measured(a.coverage_json)
    missing = [m for m in MODULES if m not in now]
    if missing:
        print("not measured: " + ", ".join(missing), file=sys.stderr)
        return 2

    if a.update:
        ratcheted = {m: max(floors.get(m, 0), int(now[m] // 5) * 5) for m in MODULES}
        with open(FLOORS_PATH, "w", encoding="utf-8", newline="\n") as f:
            json.dump(ratcheted, f, indent=2, sort_keys=True)
            f.write("\n")
        for m in MODULES:
            print(f"{m:24} {now[m]:5.1f}%  floor {ratcheted[m]}%")
        return 0

    failures = []
    for module in MODULES:
        floor = floors.get(module, 0)
        pct = now[module]
        flag = "ok " if pct >= floor else "LOW"
        print(f"{flag} {module:24} {pct:5.1f}%  floor {floor}%")
        if pct < floor:
            failures.append(f"{module}: {pct:.1f}% is below its floor of {floor}%")

    if failures:
        print("\ncoverage fell below a floor:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        print("\nAdd a test, or lower the floor deliberately in "
              f"{os.path.relpath(FLOORS_PATH)} and say why in the commit.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
