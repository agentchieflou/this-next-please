"""CI-3 (#595; plan §4.4, decision 23 on #429): `ci-ok`, `smoke`, the nightly run and a concurrency group per event.

- `.github/scripts/ci_ok.py` is the verdict: failed or cancelled fails it, skipped does not;
- the `ci-ok` job runs whatever happened (`if: always()`) and `needs:` every other job, in the workflow's
  order, so a job added later cannot be left out of the one check a READY post names;
- `smoke` installs, runs the doctor contract and the module form, then the fast tests on every core,
  and its file list is every `tests/test_hygiene_*.py`;
- the nightly run is 03:17 UTC and adds one shuffled job seeded with the date, on nightly runs only;
- each event has its own concurrency group, so the nightly run and a push do not cancel each other.
"""
from __future__ import annotations

import copy
import glob
import importlib.util
import json
import os
import shlex

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "ci_ok.py")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")
SMOKE_NAMED = ["tests/test_entrypoints.py", "tests/test_refusals.py", "tests/test_agent_onramp.py",
               "tests/test_agent_pr_check.py"]


@pytest.fixture(scope="module")
def ok():
    spec = importlib.util.spec_from_file_location("ci_ok_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _needs(**results) -> dict:
    return {job: {"result": r, "outputs": {}} for job, r in results.items()}


def ci_ok_problems(workflow: dict) -> list[str]:
    """What is wrong with the `ci-ok` job: it must exist, run always, and need every other job in order."""
    jobs = workflow["jobs"]
    job = jobs.get("ci-ok")
    if job is None:
        return ["no ci-ok job"]
    problems = []
    if str(job.get("if", "")).strip() != "always()":
        problems.append(f"ci-ok runs if {job.get('if')!r}, not always()")
    needs = job.get("needs") or []
    needs = [needs] if isinstance(needs, str) else list(needs)
    others = [j for j in jobs if j != "ci-ok"]
    if needs != others:
        problems.append(f"ci-ok needs {needs}, not every other job in order {others}")
    for job_id in others:
        theirs = jobs[job_id].get("needs") or []
        if "ci-ok" in ([theirs] if isinstance(theirs, str) else theirs):
            problems.append(f"{job_id} needs ci-ok")
    return problems


# ------------------------------------------------------------------------------------------ the verdict


def test_every_job_green_passes(ok):
    passed, rows = ok.verdict(_needs(changes="success", smoke="success", pytest="success"))
    assert passed and rows == [("changes", "success"), ("smoke", "success"), ("pytest", "success")]


def test_a_skipped_job_passes(ok):
    assert ok.verdict(_needs(changes="success", windows="skipped", **{"order-independence-nightly": "skipped"}))[0]


@pytest.mark.parametrize("bad", ["failure", "cancelled"])
def test_a_failed_or_cancelled_job_fails_it(ok, bad):
    assert not ok.verdict(_needs(changes="success", smoke="skipped", browser=bad))[0]


@pytest.mark.parametrize("odd", ["", "neutral", None])
def test_a_result_it_does_not_know_or_none_fails_it(ok, odd):
    assert not ok.verdict({"changes": {"result": "success"}, "pytest": {"result": odd}})[0]
    assert not ok.verdict({"changes": {"result": "success"}, "pytest": {}})[0]


def test_no_job_at_all_fails_it(ok):
    assert ok.verdict({}) == (False, [])


def test_the_command_line_exits_by_the_verdict_and_writes_the_summary(ok, tmp_path, capsys):
    summary = tmp_path / "summary.md"
    env = {"NEEDS": json.dumps(_needs(changes="success", windows="skipped")), "GITHUB_STEP_SUMMARY": str(summary)}
    assert ok.main(env) == 0
    assert "### ci-ok: every job passed or was skipped" in summary.read_text(encoding="utf-8")
    env["NEEDS"] = json.dumps(_needs(changes="success", browser="failure", coverage="cancelled", windows="skipped"))
    assert ok.main(env) == 1
    text = summary.read_text(encoding="utf-8")
    assert "2 job(s) failed or were cancelled: browser, coverage" in text
    assert "| browser | failure **fails ci-ok** |" in text and "| windows | skipped |" in text
    assert "failed or were cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["", "not json", "[]", "null"])
def test_a_needs_that_is_not_the_context_fails_it(ok, raw):
    assert ok.main({"NEEDS": raw}) == 1


# ------------------------------------------------------------------------------------------ the ci-ok job


def test_ci_ok_runs_always_and_needs_every_other_job():
    assert ci_ok_problems(_workflow()) == []


def test_a_new_job_left_out_of_ci_ok_is_caught():
    wf = _workflow()
    added = copy.deepcopy(wf)
    jobs = list(added["jobs"].items())
    added["jobs"] = dict(jobs[:-1] + [("new-job", {"name": "new", "needs": "changes"}), jobs[-1]])
    assert any("not every other job" in p for p in ci_ok_problems(added))
    dropped = copy.deepcopy(wf)
    dropped["jobs"]["ci-ok"]["needs"] = [j for j in dropped["jobs"]["ci-ok"]["needs"] if j != "windows"]
    assert any("not every other job" in p for p in ci_ok_problems(dropped))
    gated = copy.deepcopy(wf)
    gated["jobs"]["ci-ok"]["if"] = "success()"
    assert any("not always()" in p for p in ci_ok_problems(gated))


def test_ci_ok_is_last_and_hands_the_needs_context_to_the_script():
    jobs = _workflow()["jobs"]
    assert list(jobs)[-1] == "ci-ok"
    job = jobs["ci-ok"]
    assert job["name"] == "ci-ok", "the one stable check name (D5)"
    assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 5
    step = next(s for s in job["steps"] if "ci_ok.py" in str(s.get("run", "")))
    assert step["env"]["NEEDS"] == "${{ toJSON(needs) }}"


# ------------------------------------------------------------------------------------------ smoke


def _smoke_pytest(job: dict) -> list[str]:
    step = next(s for s in job["steps"] if "-m pytest" in str(s.get("run", "")))
    return shlex.split(step["run"])


def test_smoke_installs_runs_the_doctor_and_the_module_form_then_pytest_on_every_core():
    job = _workflow()["jobs"]["smoke"]
    assert job["needs"] == "changes" and "if" not in job, "smoke always runs"
    assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 10
    runs = [str(s.get("run", "")) for s in job["steps"]]
    order = [next(i for i, r in enumerate(runs) if needle in r) for needle in
             ("pip install -e .", "ad-doctor", "python -m agentdata --help", "-m pytest")]
    assert order == sorted(order), runs
    assert runs[order[0]].strip() == "pip install -e .", "the plain install first, as a user makes it"
    assert "check_doctor.py" in runs[order[1]]
    setup = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert setup["with"]["python-version"] == "3.14" and setup["with"]["cache"] == "pip"
    args = _smoke_pytest(job)
    assert "-n" in args and args[args.index("-n") + 1] == "auto"
    assert any(a.startswith("--junitxml=") for a in args)


def test_smoke_names_the_four_files_and_every_hygiene_file():
    args = _smoke_pytest(_workflow()["jobs"]["smoke"])
    files = [a for a in args if a.startswith("tests/")]
    hygiene = sorted(os.path.relpath(p, ROOT).replace(os.sep, "/")
                     for p in glob.glob(os.path.join(ROOT, "tests", "test_hygiene_*.py")))
    assert "tests/test_hygiene_ci_paths.py" in hygiene
    assert files == SMOKE_NAMED + hygiene, "a new tests/test_hygiene_*.py joins smoke's list"


# ------------------------------------------------------------------------------------------ nightly


def test_the_nightly_run_is_03_17_utc_and_adds_one_shuffled_job_seeded_with_the_date():
    wf = _workflow()
    on = wf[True]  # `on:` loads as True
    assert on["schedule"] == [{"cron": "17 3 * * *"}]
    assert on["workflow_dispatch"]["inputs"]["nightly"]["default"] is False
    job = wf["jobs"]["order-independence-nightly"]
    assert job["if"] == "github.event_name == 'schedule' || inputs.nightly == true", "nightly runs only"
    seed = next(s for s in job["steps"] if s.get("id") == "seed")
    assert "date -u +%Y%m%d" in seed["run"]
    step = next(s for s in job["steps"] if "-m pytest" in str(s.get("run", "")))
    assert "--shuffle-seed ${{ steps.seed.outputs.seed }}" in step["run"]
    others = [j for j, spec in wf["jobs"].items() if j != "order-independence-nightly"]
    for job_id in others:
        assert "schedule" not in str(wf["jobs"][job_id].get("if", "")), f"{job_id}: the nightly run is a full run"


def test_each_event_has_its_own_concurrency_group():
    conc = _workflow()["concurrency"]
    assert conc["group"] == "tests-${{ github.event_name }}-${{ github.ref }}"
    assert conc["cancel-in-progress"] is True, "a newer push still cancels the run it supersedes (decision 7)"
