"""Run one test many times at once, to reproduce a slow CI runner on a laptop (#307).

    python .github/scripts/stress_one.py NODEID [--copies 8] [--rounds 2] [--throttle 1] [--timeout 600]

Per round, `--copies` copies of `NODEID` run at the same time, each its own
`python -m pytest -q -p no:cacheprovider NODEID --desk-cpu-throttle=T` from the repository root.
Many processes contending for the CPU is what a loaded runner does to a test; `--throttle` also
slows each desk page's main thread (tests/desk_harness.py). It prints a TOON table
(`round, copy, outcome, seconds`) and exits 1 when any copy did not pass.

Every copy is started with `agentdata.proc.run`, never `subprocess` directly: on POSIX it puts the
copy in a session of its own and, on a timeout, kills the whole tree, so a copy that ran out of
time leaves no Node driver or Chromium behind. A local tool: CI never runs it.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agentdata import proc, toon  # noqa: E402 - after the path fix, so a checkout without install works

COLUMNS = ["round", "copy", "outcome", "seconds"]


def one_copy(nodeid: str, *, throttle: float, timeout: int, cwd: str = ROOT) -> tuple[str, float]:
    """`(outcome, seconds)` for one copy: `passed` on exit 0, `failed` on any other exit, and
    `timeout` when `proc.run` gave up on it (and killed its tree)."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", nodeid,
            f"--desk-cpu-throttle={throttle:g}"]
    t0 = time.monotonic()
    try:
        code, _out, _err, _elapsed = proc.run(argv, timeout=timeout, cwd=cwd)
    except proc.ProcError as e:
        if e.code == "timeout":
            return "timeout", time.monotonic() - t0
        raise
    return ("passed" if code == 0 else "failed"), time.monotonic() - t0


def stress(nodeid: str, *, copies: int = 8, rounds: int = 2, throttle: float = 1.0, timeout: int = 600,
           cwd: str = ROOT) -> list[list]:
    """Every copy of every round, as `[round, copy, outcome, seconds]` rows."""
    rows = []
    for r in range(1, rounds + 1):
        with ThreadPoolExecutor(max_workers=copies) as pool:
            futures = [pool.submit(one_copy, nodeid, throttle=throttle, timeout=timeout, cwd=cwd)
                       for _ in range(copies)]
            for c, f in enumerate(futures, start=1):
                outcome, seconds = f.result()
                rows.append([r, c, outcome, round(seconds, 1)])
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nodeid", help="a pytest node id, relative to the repository root")
    ap.add_argument("--copies", type=int, default=8, help="copies run at once, per round (8)")
    ap.add_argument("--rounds", type=int, default=2, help="rounds, one after the other (2)")
    ap.add_argument("--throttle", type=float, default=1.0,
                    help="each copy's --desk-cpu-throttle (1: none)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds one copy may take (600)")
    a = ap.parse_args(argv)
    if a.copies < 1 or a.rounds < 1 or a.timeout < 1 or a.throttle < 1:
        ap.error("--copies, --rounds and --timeout must be 1 or more, and --throttle at least 1")
    rows = stress(a.nodeid, copies=a.copies, rounds=a.rounds, throttle=a.throttle, timeout=a.timeout)
    print(toon.table("copies", COLUMNS, rows))
    return 0 if all(row[2] == "passed" for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
