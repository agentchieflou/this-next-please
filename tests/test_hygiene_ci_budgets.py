"""Every pytest step in CI has a budget and reports what it cost (#309).

The Windows job's cap was raised three times in one day, each time after a run was cancelled, and no
job said which test files had grown. A step with its own `timeout-minutes` names itself when it runs
long; a step with `--junitxml` feeds `.github/scripts/durations.py`, whose table lands in the job
summary. Jobs with no pytest step (`lint ·`, `ide ·`, `floor ·`) are out of scope.
"""
from __future__ import annotations
import copy
import os
import re

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")


def _is_pytest_step(step: dict) -> bool:
    run = step.get("run") or ""
    # the `floor-lints` laptop check only collects: it runs nothing, so it has nothing to report
    return "-m pytest" in run and "--collect-only" not in run


def _is_summary_step(step: dict) -> bool:
    run = step.get("run") or ""
    return "durations.py" in run and " summarize " in run and "always()" in str(step.get("if", ""))


def budget_problems(workflow: dict) -> list[str]:
    problems = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        steps = job.get("steps") or []
        pytest_steps = [s for s in steps if _is_pytest_step(s)]
        if not pytest_steps:
            continue
        job_cap = job.get("timeout-minutes")
        if not isinstance(job_cap, int):
            problems.append(f"{job_id}: a job that runs pytest has no timeout-minutes")
        if not any(_is_summary_step(s) for s in steps):
            problems.append(f"{job_id}: no `if: always()` step runs durations.py summarize")
        for s in pytest_steps:
            name = s.get("name") or s["run"].strip().splitlines()[0][:60]
            cap = s.get("timeout-minutes")
            if not isinstance(cap, int):
                problems.append(f"{job_id} / {name}: a pytest step with no timeout-minutes")
            elif isinstance(job_cap, int) and cap > job_cap:
                problems.append(f"{job_id} / {name}: its cap {cap} exceeds the job's {job_cap}")
            if "--junitxml" not in s["run"]:
                problems.append(f"{job_id} / {name}: a pytest step with no --junitxml")
    return problems


def _load() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_every_pytest_step_has_a_budget_and_reports_it():
    workflow = _load()
    assert "workflow_dispatch" in workflow[True], "`on:` loads as True; a run on demand is wired"
    assert budget_problems(workflow) == []
    jobs_in_scope = [j for j, job in workflow["jobs"].items()
                     if any(_is_pytest_step(s) for s in job.get("steps") or [])]
    assert {"pytest", "windows", "floor-lints", "coverage", "order-independence"} <= set(jobs_in_scope)


def _first_pytest_step(workflow: dict, job_id: str) -> dict:
    return next(s for s in workflow["jobs"][job_id]["steps"] if _is_pytest_step(s))


def test_the_budget_check_fails_when_a_cap_or_a_junit_file_is_removed():
    for job_id in ("pytest", "windows", "floor-lints", "coverage", "order-independence"):
        no_cap = copy.deepcopy(_load())
        del _first_pytest_step(no_cap, job_id)["timeout-minutes"]
        assert any("no timeout-minutes" in p for p in budget_problems(no_cap)), job_id

        no_junit = copy.deepcopy(_load())
        step = _first_pytest_step(no_junit, job_id)
        step["run"] = re.sub(r"\s--junitxml=\S+", "", step["run"])
        assert any("no --junitxml" in p for p in budget_problems(no_junit)), job_id

        no_job_cap = copy.deepcopy(_load())
        del no_job_cap["jobs"][job_id]["timeout-minutes"]
        assert any(p.startswith(f"{job_id}: a job") for p in budget_problems(no_job_cap)), job_id

        no_summary = copy.deepcopy(_load())
        steps = no_summary["jobs"][job_id]["steps"]
        steps[:] = [s for s in steps if not _is_summary_step(s)]
        assert any("summarize" in p for p in budget_problems(no_summary)), job_id

    over = copy.deepcopy(_load())
    _first_pytest_step(over, "coverage")["timeout-minutes"] = over["jobs"]["coverage"]["timeout-minutes"] + 1
    assert any("exceeds the job's" in p for p in budget_problems(over))


def test_the_collect_only_laptop_check_is_out_of_scope():
    workflow = _load()
    collect = [s for s in workflow["jobs"]["floor-lints"]["steps"] if "--collect-only" in (s.get("run") or "")]
    assert collect and not any(_is_pytest_step(s) for s in collect)
