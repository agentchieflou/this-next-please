"""What each pytest step and each test file cost, from the junit files CI writes (#309).

The Windows job's cap went 15 -> 20 -> 25 -> 40 minutes in one day, each time after a run was
cancelled, because no job said which files cost what. Every pytest step now writes a junit file,
and this script reads them:

    summarize JUNIT... --step NAME --cap-minutes N
        Markdown for `$GITHUB_STEP_SUMMARY`: the step's wall time against its cap, the summed test
        time per tier, and the most expensive files and tests. Above 75% of the cap it also prints a
        `::warning` line. It never fails the build: a warning is a budget talking, not a verdict.

    job JUNIT... --job NAME --cap-minutes N
        One line: every pytest step of the job, summed, against the job's cap, with the same warning.

    update JUNIT... --os windows|linux --out tests/durations.json
        `{os: {file: {tier: seconds}}}`. Within one junit file a file's testcases are summed per tier;
        across junit files the max is taken, never the sum (both Windows legs run the same files).

A testcase is keyed by the `file` property `tests/conftest.py` records, never by `classname`: the
default `junit_family` (xunit2) writes no `file` attribute, and a classname is a dotted guess.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

TIERS = ("browser", "laptop", "measured", "scale", "slow")
WARN_AT = 0.75
TOP = 15


def tier_of(markers: str) -> str:
    """`browser+measured`, `slow`, ... or `default`: the tier markers a test carries, sorted."""
    names = sorted({m for m in markers.split(",") if m in TIERS})
    return "+".join(names) or "default"


def read(path: str) -> tuple[float, list[dict]]:
    """(the suites' wall time, one dict per testcase: file, name, tier, seconds)."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    wall = sum(float(s.get("time") or 0) for s in suites)
    cases = []
    for suite in suites:
        for case in suite.iter("testcase"):
            props = {p.get("name"): p.get("value") or "" for p in case.iter("property")}
            file = props.get("file") or "(no file property)"
            cases.append({"file": file.replace("\\", "/"), "name": case.get("name") or "",
                          "tier": tier_of(props.get("markers", "")),
                          "seconds": float(case.get("time") or 0)})
    return wall, cases


def near_cap(seconds: float, cap_minutes: float) -> bool:
    return seconds > WARN_AT * cap_minutes * 60


def warning(title: str, seconds: float, cap_minutes: float) -> str:
    return f"::warning title={title} near its cap::{title} took {seconds:.0f} s of {cap_minutes:g} min"


def _minutes(seconds: float) -> str:
    return f"{int(seconds // 60)}m{int(round(seconds % 60)):02d}s"


def summarize(paths: list[str], step: str, cap_minutes: float) -> str:
    wall, cases = 0.0, []
    for path in paths:
        w, c = read(path)
        wall, cases = wall + w, cases + c
    share = wall / (cap_minutes * 60) if cap_minutes else 0.0
    out = [f"### `{step}`: {_minutes(wall)} of its {cap_minutes:g}-minute cap ({share:.0%})", ""]

    tiers: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    files: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for c in cases:
        tiers[c["tier"]][0] += 1
        tiers[c["tier"]][1] += c["seconds"]
        files[c["file"]][0] += 1
        files[c["file"]][1] += c["seconds"]
    total = sum(t[1] for t in tiers.values()) or 1.0
    out += ["| Tier | Tests | Test time | Share of test time |", "|---|---:|---:|---:|"]
    for name, (n, s) in sorted(tiers.items(), key=lambda kv: (-kv[1][1], kv[0])):
        out.append(f"| {name} | {n} | {s:.1f} s | {s / total:.0%} |")

    out += ["", f"The {TOP} most expensive files:", "", "| File | Tests | Seconds |", "|---|---:|---:|"]
    for name, (n, s) in sorted(files.items(), key=lambda kv: (-kv[1][1], kv[0]))[:TOP]:
        out.append(f"| `{name}` | {n} | {s:.1f} |")

    out += ["", f"The {TOP} most expensive tests:", "", "| Test | Tier | Seconds |", "|---|---|---:|"]
    for c in sorted(cases, key=lambda c: (-c["seconds"], c["file"], c["name"]))[:TOP]:
        out.append(f"| `{c['file']}::{c['name']}` | {c['tier']} | {c['seconds']:.1f} |")
    out.append("")
    if near_cap(wall, cap_minutes):
        out.append(warning(step, wall, cap_minutes))
    return "\n".join(out) + "\n"


def job_line(paths: list[str], job: str, cap_minutes: float) -> str:
    wall = sum(read(p)[0] for p in paths)
    share = wall / (cap_minutes * 60) if cap_minutes else 0.0
    out = [f"**`{job}`**: its pytest steps took {_minutes(wall)} of the job's {cap_minutes:g}-minute cap "
           f"({share:.0%}); setup and the other steps come on top.", ""]
    if near_cap(wall, cap_minutes):
        out.append(warning(job, wall, cap_minutes))
    return "\n".join(out) + "\n"


def durations(paths: list[str]) -> dict[str, dict[str, float]]:
    """Sum within one junit file, max across junit files."""
    best: dict[str, dict[str, float]] = {}
    for path in paths:
        mine: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for c in read(path)[1]:
            mine[c["file"]][c["tier"]] += c["seconds"]
        for file, tiers in mine.items():
            slot = best.setdefault(file, {})
            for tier, s in tiers.items():
                slot[tier] = max(slot.get(tier, 0.0), s)
    return {f: {t: round(s, 1) for t, s in sorted(tiers.items())} for f, tiers in sorted(best.items())}


def update(paths: list[str], os_key: str, out: str) -> None:
    data = {}
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
    data[os_key] = durations(paths)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summarize", help="a step's table, for $GITHUB_STEP_SUMMARY")
    s.add_argument("junit", nargs="+")
    s.add_argument("--step", required=True)
    s.add_argument("--cap-minutes", type=float, required=True)
    j = sub.add_parser("job", help="a job's pytest steps against the job's cap")
    j.add_argument("junit", nargs="+")
    j.add_argument("--job", required=True)
    j.add_argument("--cap-minutes", type=float, required=True)
    u = sub.add_parser("update", help="write tests/durations.json")
    u.add_argument("junit", nargs="+")
    u.add_argument("--os", required=True, choices=["windows", "linux"])
    u.add_argument("--out", default=os.path.join("tests", "durations.json"))
    a = ap.parse_args(argv)

    # The Windows runner's stdout is cp1252, and the job names carry a middle dot: write UTF-8, the
    # encoding `$GITHUB_STEP_SUMMARY` is read in.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    missing = [p for p in a.junit if not os.path.isfile(p)]
    if missing:
        print("no such junit file: " + ", ".join(missing), file=sys.stderr)
        return 2
    if a.cmd == "summarize":
        sys.stdout.write(summarize(a.junit, a.step, a.cap_minutes))
    elif a.cmd == "job":
        sys.stdout.write(job_line(a.junit, a.job, a.cap_minutes))
    else:
        update(a.junit, a.os, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
