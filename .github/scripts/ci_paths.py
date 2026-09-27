"""Which CI groups a change touches, and which jobs a filter would skip (#593, CI-1; decision 23 on #429).

The map is `.github/ci-paths.json`. A changed file turns on every group whose `paths` name it (less
its `except`); a group with `only` is on when *every* changed file matches it; a group with
`everything` turns every group on. A file that no group names turns every group on as well (fail
open), and so do an empty diff, a diff git could not compute, and every event in FULL_EVENTS.

Report only (D2): the `changes` job writes one output per group and a job-summary table that names each
job a filter *would* have skipped. No job reads the outputs yet; CI-4 (#596) is the card that does.
Stdlib only, so it runs before anything is installed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

FULL_EVENTS = ("push", "schedule", "workflow_dispatch")
_TOKEN = re.compile(r"\*\*/|\*\*|\*|\?|\{[^}]*\}|[^*?{]+")


def pattern(glob: str) -> re.Pattern:
    """`**/` any directories, `**` anything, `*` and `?` within one segment, `{a,b}` either word."""
    out = []
    for tok in _TOKEN.findall(glob):
        if tok == "**/":
            out.append("(?:.*/)?")
        elif tok == "**":
            out.append(".*")
        elif tok == "*":
            out.append("[^/]*")
        elif tok == "?":
            out.append("[^/]")
        elif tok.startswith("{"):
            out.append("(?:" + "|".join(re.escape(t) for t in tok[1:-1].split(",")) + ")")
        else:
            out.append(re.escape(tok))
    return re.compile("".join(out) + r"\Z")


def matches(globs, path: str) -> bool:
    return any(pattern(g).match(path) for g in globs)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def names(spec: dict, path: str) -> bool:
    return matches(spec.get("paths", ()), path) and not matches(spec.get("except", ()), path)


def groups_for(files, cmap: dict) -> tuple[set, list]:
    """The groups `files` turn on, and the files no group names. Unmapped or `everything` means all."""
    groups, unmapped = set(), []
    for f in files:
        hit = {g for g, spec in cmap["groups"].items() if names(spec, f)}
        unmapped += [] if hit else [f]
        groups |= hit
    for g, spec in cmap["groups"].items():
        if spec.get("only") and files and all(matches(spec["only"], f) for f in files):
            groups.add(g)
    if not files or unmapped or any(cmap["groups"][g].get("everything") for g in groups):
        groups = set(cmap["groups"])
    return groups, unmapped


def jobs_for(groups: set, cmap: dict) -> set:
    return {j for j, spec in cmap["jobs"].items() if spec.get("always") or groups & set(spec.get("groups", ()))}


def changed_files(event: str, env: dict) -> tuple[list | None, str]:
    """The changed paths and the range they came from; None when git could not say."""
    if event == "pull_request" and env.get("GITHUB_BASE_REF"):
        rng = [f"origin/{env['GITHUB_BASE_REF']}...HEAD"]
    elif event == "push" and env.get("BEFORE", "").strip("0"):
        rng = [env["BEFORE"], "HEAD"]
    else:
        rng = ["origin/main...HEAD"]
    try:
        out = subprocess.run(["git", "diff", "--name-only", *rng], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        return None, f"{' '.join(rng)} (git failed: {e})"
    return sorted({line.strip() for line in out.splitlines() if line.strip()}), " ".join(rng)


def report(event: str, files, rng: str, cmap: dict) -> tuple[dict, str]:
    """The step outputs and the job-summary markdown."""
    groups, unmapped = groups_for(files or [], cmap)
    run = jobs_for(groups, cmap)
    skip = [n for j, spec in cmap["jobs"].items() if j not in run for n in spec["names"]]
    forced = event in FULL_EVENTS
    outputs = {g: "true" if forced or g in groups else "false" for g in cmap["groups"]}
    outputs["all"] = "true" if forced or groups == set(cmap["groups"]) else "false"
    would = "would skip: " + (", ".join(skip) if skip else "nothing")
    lines = ["### changes · report only (#593)", "",
             f"Event `{event}`, diff `{rng}`: {len(files) if files is not None else 'unknown'} file(s).",
             "Nothing is skipped in this run (decision 23, D2: report only)."]
    if forced:
        lines.append(f"`{event}` always runs everything; as a pull request with this diff it " + would)
    else:
        lines.append(would)
    if unmapped:
        lines.append("No group names " + ", ".join(f"`{f}`" for f in unmapped[:20]) + ", so every group is on.")
    lines += ["", "| group | changed |", "|---|---|"]
    lines += [f"| `{g}` | {'yes' if g in groups else 'no'} |" for g in cmap["groups"]]
    lines += ["", "| job | a filter would | turned on by |", "|---|---|---|"]
    for j, spec in cmap["jobs"].items():
        why = "always" if spec.get("always") else ", ".join(f"`{g}`" for g in spec["groups"])
        for n in spec["names"]:
            lines.append(f"| {n} | {'run' if j in run else '**skip**'} | {why} |")
    return outputs, "\n".join(lines) + "\n"


def main(argv=None, env=None) -> int:
    env = dict(os.environ if env is None else env)
    argv = sys.argv[1:] if argv is None else argv
    event = env.get("GITHUB_EVENT_NAME", "workflow_dispatch")
    here = os.path.dirname(os.path.abspath(__file__))
    cmap_path = argv[0] if argv else os.path.join(here, "..", "ci-paths.json")
    try:
        cmap = load(cmap_path)
        files, rng = changed_files(event, env)
        outputs, summary = report(event, files, rng, cmap)
    except Exception as e:  # report only: a broken map must never stop the jobs that need this one
        outputs, summary = {"all": "true"}, f"### changes · report only (#593)\n\nfailed open: {e!r}\n"
    print(summary)
    for key, text in (("GITHUB_OUTPUT", "".join(f"{k}={v}\n" for k, v in outputs.items())),
                      ("GITHUB_STEP_SUMMARY", summary)):
        if env.get(key):
            with open(env[key], "a", encoding="utf-8") as f:
                f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
