"""`ci-ok`: one verdict over every job in the run (#595, CI-3; plan §4.4, decision 23 on #429).

    NEEDS='${{ toJSON(needs) }}' python .github/scripts/ci_ok.py

The job `needs:` every other job and runs with `if: always()`, so it sees each one's `result`. A job
that passed or was skipped (a draft's Windows and IDE jobs, the nightly job by day, a path filter's
skip once CI-4 lands) is fine; one that failed or was cancelled fails the verdict. Any other result,
or none, fails it too: a result this script has never seen is not a pass. Stdlib only, so the job
needs no setup-python and no install.
"""
from __future__ import annotations

import json
import os
import sys

#: What GitHub reports for a job that is not a problem.
PASSING = ("success", "skipped")


def verdict(needs: dict) -> tuple[bool, list[tuple[str, str]]]:
    """(passed, [(job, result)...]) for the `needs` context. No job at all is a broken wiring, not a pass."""
    rows = [(job, str((info or {}).get("result") or "")) for job, info in needs.items()]
    return bool(rows) and all(result in PASSING for _, result in rows), rows


def summary(ok: bool, rows: list[tuple[str, str]]) -> str:
    bad = [job for job, result in rows if result not in PASSING]
    lines = ["### ci-ok: " + ("every job passed or was skipped" if ok else
                              f"{len(bad)} job(s) failed or were cancelled: {', '.join(bad) or 'no jobs were needed'}"),
             "", "| job | result |", "|---|---|"]
    lines += [f"| {job} | {result or '(none)'}{'' if result in PASSING else ' **fails ci-ok**'} |" for job, result in rows]
    return "\n".join(lines) + "\n"


def main(env=None) -> int:
    env = os.environ if env is None else env
    try:
        needs = json.loads(env.get("NEEDS") or "")
    except ValueError as e:
        print(f"ci-ok: NEEDS is not the `needs` context as JSON: {e}")
        return 1
    if not isinstance(needs, dict):
        print(f"ci-ok: NEEDS is a {type(needs).__name__}, not the `needs` context")
        return 1
    ok, rows = verdict(needs)
    text = summary(ok, rows)
    print(text, end="")
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
