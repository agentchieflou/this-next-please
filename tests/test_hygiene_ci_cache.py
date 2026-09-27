"""pip is cached on every job that sets Python up, and the IDE builds skip draft PRs (#592, decision 23).

Both are properties of `.github/workflows/tests.yml` alone, so they are read from it here rather than
waited for in a run: a new job that calls `actions/setup-python` without the cache fails this file, and so
does an IDE job that loses its draft gate or a `pull_request` trigger that stops listing
`ready_for_review` (without it, marking a draft ready would never run the jobs it skipped).
"""
from __future__ import annotations
import os

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")

#: The Windows job's condition (decision 7): a draft PR skips the job; a push, a dispatch and a
#: ready PR run it.
DRAFT_GATE = "github.event_name != 'pull_request' || github.event.pull_request.draft == false"
IDE_JOBS = ("vscode-extension", "jetbrains-plugin")


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _setup_python_steps(workflow: dict):
    for job_id, job in workflow["jobs"].items():
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/setup-python"):
                yield job_id, step


def test_every_setup_python_caches_pip_keyed_on_pyproject():
    steps = list(_setup_python_steps(_workflow()))
    jobs = {job_id for job_id, _ in steps}
    # the jobs #592 names, so a rename cannot quietly shrink what this checks
    assert {"pytest", "browser", "windows", "floor-python", "lint-shell-scripts", "floor-lints", "coverage",
            "order-independence", "order-independence-browser"} <= jobs, jobs
    for job_id, step in steps:
        with_ = step.get("with") or {}
        assert with_.get("cache") == "pip", f"{job_id}: setup-python without `cache: pip`"
        assert with_.get("cache-dependency-path") == "pyproject.toml", (
            f"{job_id}: the pip cache is keyed on pyproject.toml, where the dependencies are declared")


def test_every_job_that_installs_the_package_sets_python_up_with_the_cache():
    """`pip install` with no cached setup-python before it would download everything on every run."""
    wf = _workflow()
    cached = {job_id for job_id, _ in _setup_python_steps(wf)}
    for job_id, job in wf["jobs"].items():
        steps = job.get("steps") or []
        if any("pip install" in str(s.get("run", "")) for s in steps):
            assert job_id in cached, f"{job_id} runs pip install without a cached setup-python"


def test_the_ide_jobs_skip_draft_prs_and_run_everywhere_else():
    wf = _workflow()
    for job_id in IDE_JOBS:
        assert wf["jobs"][job_id].get("if") == DRAFT_GATE, job_id
    assert wf["jobs"]["windows"].get("if") == DRAFT_GATE, "the IDE jobs share the Windows job's gate"


def test_marking_a_draft_ready_runs_what_it_skipped():
    wf = _workflow()
    on = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on` key as True
    assert "ready_for_review" in on["pull_request"]["types"], on["pull_request"]
    assert on["push"]["branches"] == ["main"], "a push to main runs every job, drafts or not"
