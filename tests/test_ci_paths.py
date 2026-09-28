"""The `changes` job's path map, report only (#593, CI-1; decision 23 on #429).

`.github/scripts/ci_paths.py` maps a change's files to the groups in `.github/ci-paths.json` and names the
jobs a path filter would skip. In this card nothing is skipped: every job `needs: changes` and no `if:`
reads its outputs. `tests/test_hygiene_ci_paths.py` (CI-2) re-checks FIXTURE_DIFFS and covers the map.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import subprocess

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "ci_paths.py")
MAP = os.path.join(ROOT, ".github", "ci-paths.json")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

ALL = "all"
#: The issue's four cases, each a diff and the groups it turns on.
FIXTURE_DIFFS = [
    (["docs/setup.md", "README.md"], {"docs"}),
    (["no-such-area/notes.txt", "docs/setup.md"], ALL),
    (["agentdata/fleet/static/app.js"], {"static-only", "desk"}),
    (["tests/test_fleet_ink.py"], {"desk", "py"}),
]
#: The four Linux browser jobs, the first a filter skips (decision 23's browser path filter).
LINUX_BROWSER_JOBS = ["ubuntu · python 3.14 · browser · shard 1/2", "ubuntu · python 3.14 · browser · shard 2/2",
                      "suite · shuffled · browser · shard 1/2", "suite · shuffled · browser · shard 2/2"]
#: The jobs before #593; it adds `changes` and nothing else.
JOBS_BEFORE = ["pytest", "browser", "windows", "floor-python", "lint-shell-scripts", "floor-lints", "coverage",
               "order-independence", "order-independence-browser", "vscode-extension", "jetbrains-plugin"]


@pytest.fixture(scope="module")
def cp():
    spec = importlib.util.spec_from_file_location("ci_paths_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cmap(cp):
    return cp.load(MAP)


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize("files,expected", FIXTURE_DIFFS, ids=["docs-only", "unknown", "static", "browser-test"])
def test_the_issues_four_diffs_turn_on_the_groups_they_name(cp, cmap, files, expected):
    groups, unmapped = cp.groups_for(files, cmap)
    assert groups == (set(cmap["groups"]) if expected == ALL else expected)
    assert bool(unmapped) == (expected == ALL)


def test_the_glob_rules(cp):
    assert cp.matches(["agentdata/**"], "agentdata/fleet/static/app.js")
    assert cp.matches(["tests/**/x.py"], "tests/x.py") and cp.matches(["tests/**/x.py"], "tests/a/b/x.py")
    assert cp.matches(["*.md"], "README.md") and not cp.matches(["*.md"], "docs/setup.md")
    assert not cp.matches(["tests/test_fleet_*.py"], "tests/regressions/test_fleet_x.py")
    assert cp.matches([".github/scripts/smoke.{sh,ps1,cmd}"], ".github/scripts/smoke.ps1")
    assert not cp.matches([".github/scripts/smoke.{sh,ps1,cmd}"], ".github/scripts/smoke.bat")
    assert cp.matches(["a?.txt"], "ab.txt") and not cp.matches(["a?.txt"], "a/.txt")
    assert not cp.matches(["docs/fleet-ide.md"], "docs/fleet-ide.mdx"), "anchored at the end"
    spec = {"paths": [".github/scripts/**"], "except": [".github/scripts/smoke.*"]}
    assert cp.names(spec, ".github/scripts/durations.py") and not cp.names(spec, ".github/scripts/smoke.sh")


def test_static_only_needs_every_file_to_be_static(cp, cmap):
    groups, _ = cp.groups_for(["agentdata/fleet/static/app.js", "docs/setup.md"], cmap)
    assert "static-only" not in groups and {"desk", "docs"} <= groups


def test_mobile_alone_turns_on_no_job_but_the_ones_that_always_run(cp, cmap):
    groups, _ = cp.groups_for(["mobile/README.md"], cmap)
    assert groups == {"mobile"}
    assert cp.jobs_for(groups, cmap) == {j for j, s in cmap["jobs"].items() if s.get("always")}


def test_a_ci_file_an_empty_diff_or_an_unknown_path_turns_everything_on(cp, cmap):
    for files in ([".github/workflows/tests.yml"], ["pyproject.toml"], [], ["LICENSE.old"]):
        groups, _ = cp.groups_for(files, cmap)
        assert groups == set(cmap["groups"]), files
        assert cp.jobs_for(groups, cmap) == set(cmap["jobs"]), files


def test_the_answer_does_not_depend_on_the_order_of_the_files(cp, cmap):
    files = ["docs/setup.md", "agentdata/fleet/static/app.js", "mobile/README.md", "ide/vscode/package.json"]
    first = cp.report("pull_request", files, "origin/main...HEAD", cmap)
    for seed in range(5):
        shuffled = files[:]
        random.Random(seed).shuffle(shuffled)
        assert cp.report("pull_request", shuffled, "origin/main...HEAD", cmap) == first


def test_a_docs_only_pr_reports_the_browser_jobs_as_would_skip_and_skips_nothing(cp, cmap):
    outputs, summary = cp.report("pull_request", ["docs/setup.md"], "origin/main...HEAD", cmap)
    assert outputs["docs"] == "true" and outputs["all"] == "false"
    assert {g for g, v in outputs.items() if v == "true"} == {"docs"}
    would = next(line for line in summary.splitlines() if line.startswith("would skip: "))
    for name in LINUX_BROWSER_JOBS:
        assert name in would and f"| {name} | **skip** |" in summary
    assert "ubuntu-latest · python 3.14" not in would, "docs are test inputs: ubuntu 3.14 runs"
    assert "Nothing is skipped in this run" in summary
    for group in cmap["groups"]:
        assert f"| `{group}` |" in summary
    for spec in cmap["jobs"].values():
        for name in spec["names"]:
            assert f"| {name} |" in summary


def test_the_summary_tells_a_group_that_changed_from_one_that_everything_turned_on(cp, cmap):
    _, summary = cp.report("pull_request", [".github/workflows/tests.yml", "docs/setup.md"], "r", cmap)
    assert "`ci` changed, and it turns every group on." in summary
    assert "| `ci` | yes | yes |" in summary and "| `docs` | yes | yes |" in summary
    assert "| `desk` | no | yes |" in summary and "would skip: nothing" in summary
    _, summary = cp.report("pull_request", ["docs/setup.md"], "r", cmap)
    assert "| `docs` | yes | yes |" in summary and "| `desk` | no | no |" in summary
    _, summary = cp.report("pull_request", [], "r", cmap)
    assert "No changed file was found, so every group is on." in summary


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule"])
def test_a_push_a_dispatch_and_the_nightly_run_output_all(cp, cmap, event):
    outputs, summary = cp.report(event, ["docs/setup.md"], "origin/main...HEAD", cmap)
    assert set(outputs.values()) == {"true"} and set(outputs) == set(cmap["groups"]) | {"all"}
    assert f"`{event}` always runs everything; as a pull request with this diff it would skip: " in summary


def test_the_command_line_writes_outputs_and_the_summary_and_fails_open(cp, tmp_path, capsys):
    out, summary = tmp_path / "out", tmp_path / "summary"
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
    assert cp.main([str(tmp_path / "missing.json")], env) == 0
    assert out.read_text(encoding="utf-8") == "all=true\n"
    assert "failed open" in summary.read_text(encoding="utf-8")
    assert "failed open" in capsys.readouterr().out


def test_the_push_range_is_read_from_git(cp, tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run([*GIT, *a], cwd=repo, check=True, capture_output=True, text=True).stdout
    run("init", "-q")
    (repo / "README.md").write_text("a\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "one")
    before = run("rev-parse", "HEAD").strip()
    (repo / "docs").mkdir()
    (repo / "docs" / "x.md").write_text("b\n", encoding="utf-8")
    (repo / "mobile").mkdir()
    (repo / "mobile" / "y.json").write_text("{}\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "two")
    monkeypatch.chdir(repo)
    files, rng = cp.changed_files("push", {"BEFORE": before})
    assert files == ["docs/x.md", "mobile/y.json"] and rng == f"{before} HEAD"
    files, rng = cp.changed_files("push", {"BEFORE": "0" * 40})
    assert files is None and "origin/main...HEAD" in rng, "no origin here: git fails, and the report fails open"


def test_every_job_needs_changes_and_nothing_reads_its_outputs_yet():
    jobs = _workflow()["jobs"]
    assert list(jobs) == ["changes", "smoke", *JOBS_BEFORE[:-2], "order-independence-nightly", *JOBS_BEFORE[-2:],
                          "ci-ok"], "the job count and names are unchanged apart from `changes` and CI-3's (#595)"
    for job_id in ["smoke", *JOBS_BEFORE, "order-independence-nightly"]:
        assert jobs[job_id]["needs"] == "changes", job_id
        assert "needs." not in str(jobs[job_id].get("if", "")), f"{job_id}: report only (D2)"
        for step in jobs[job_id].get("steps") or []:
            assert "needs.changes" not in str(step.get("if", "")), f"{job_id}: never a step-level filter (#315)"


def test_the_changes_job_fetches_history_caps_its_time_caches_pip_and_outputs_every_group(cmap):
    job = _workflow()["jobs"]["changes"]
    assert "needs" not in job and "if" not in job
    assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 5
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout") and checkout["with"]["fetch-depth"] == 0
    setup = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert setup["with"]["cache"] == "pip"
    mapper = next(s for s in job["steps"] if s.get("id") == "map")
    assert ".github/scripts/ci_paths.py .github/ci-paths.json" in mapper["run"]
    assert mapper.get("continue-on-error") is True, "report only: a failure here must not skip every job"
    assert set(job["outputs"]) == set(cmap["groups"]) | {"all"}
    for key, value in job["outputs"].items():
        assert value == f"${{{{ steps.map.outputs.{key} }}}}", key


def test_the_map_and_its_script_are_in_the_ci_lane():
    with open(os.path.join(ROOT, ".github", "agent-lanes.json"), encoding="utf-8") as f:
        lanes = json.load(f)["lanes"]
    assert ".github/ci-paths.json" in lanes["ci"]["paths"]
    assert ".github/scripts/ci_paths.py" in lanes["ci"]["paths"], "it decides what CI runs: CI config in effect"
    assert ".github/scripts/ci_ok.py" in lanes["ci"]["paths"], "it decides whether CI passed: CI config in effect"
