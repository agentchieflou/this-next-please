"""Linux runs the browser tier once per run in its own shards, and once more shuffled (#312).

What each Linux job runs is decided before a runner starts, by its matrix and each step's `if:`, so it
is checked here the way tests/test_hygiene_windows_shards.py checks the Windows jobs: every job is
expanded per matrix row, every `if:` is evaluated against the row, and every pytest step's `-m` is
evaluated with pytest's own marker grammar against the marker sets a test can carry. How long a job
takes only a run can say; the step budgets are tests/test_hygiene_ci_budgets.py's (#309).
"""
from __future__ import annotations
import itertools
import os
import re
import shlex

import yaml
from _pytest.mark.expression import Expression

from test_hygiene_windows_shards import holds, render, shard_of
from test_hygiene_windows_shards import selection as _selection

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")

#: The browser tier proper, as the two new jobs select it.
TIER = "browser and not slow and not measured and not scale"
#: The marker sets a browser test carries in this suite (tests/durations.json's tiers).
BROWSER_KINDS = ({"browser"}, {"browser", "measured"}, {"browser", "slow"})
SEEDS = ["1", "20260904"]


def _workflow() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)


def rows_of(job: dict) -> list[dict]:
    """The matrix rows as Actions expands them: the product of the list-valued keys, then `include`
    rows, each extending every row it matches or else added as a row of its own."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    rows = [dict(zip(axes, combo)) for combo in itertools.product(*axes.values())] if axes else []
    for extra in matrix.get("include") or []:
        hits = [r for r in rows if all(r.get(k, v) == v for k, v in extra.items() if k in axes)]
        if axes and hits:
            for r in hits:
                r.update(extra)
        else:
            rows.append(dict(extra))
    return rows or [{}]


def linux_jobs(workflow: dict | None = None) -> list[dict]:
    """Every ubuntu job, one entry per matrix row, with the steps that run on that row, rendered."""
    out = []
    for job_id, job in (workflow or _workflow())["jobs"].items():
        for row in rows_of(job):
            if "ubuntu" not in render(job.get("runs-on"), row):
                continue
            steps = [{**s, "name": render(s.get("name") or s.get("uses") or s.get("run", ""), row),
                      "run": render(s.get("run"), row),
                      "env": {k: render(v, row) for k, v in (s.get("env") or {}).items()},
                      "with": {k: render(v, row) for k, v in (s.get("with") or {}).items()}}
                     for s in job.get("steps") or [] if holds(s.get("if"), row)]
            out.append({"id": job_id, "row": row, "name": render(job.get("name", job_id), row),
                        "cap": job.get("timeout-minutes"), "steps": steps})
    return out


def pytest_steps(job: dict) -> list[dict]:
    return [s for s in job["steps"] if "-m pytest" in s["run"] and "--collect-only" not in s["run"]]


def installs_chromium(job: dict) -> bool:
    return any("playwright install" in s["run"] and "chromium" in s["run"] for s in job["steps"])


def whole_suite(run: str) -> bool:
    """A step that names no test file selects from the whole suite (the measurements and the demo
    name theirs)."""
    return not named_files(run)


def command(run: str) -> str:
    """The `python -m pytest ...` line of a step, its backslash continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", run or "")
    return next((ln.strip() for ln in joined.splitlines() if "-m pytest" in ln), "")


def selection(run: str) -> str:
    return _selection(command(run))


def named_files(run: str) -> list[str]:
    return [a for a in shlex.split(command(run)) if a.startswith("tests/")]


def selects(run: str, markers: set[str]) -> bool:
    expr = selection(run)
    return True if not expr else Expression.compile(expr).evaluate(lambda name, **_: name in markers)


def test_the_browser_tier_runs_once_on_ubuntu_3_12_in_two_shards_plus_once_shuffled():
    jobs = linux_jobs()
    plain, shuffled = [], []
    for job in jobs:
        for s in pytest_steps(job):
            if whole_suite(s["run"]) and selects(s["run"], {"browser"}):
                (shuffled if "--shuffle-seed" in s["run"] else plain).append((job["name"], s))
    assert sorted(n for n, _ in plain) == [f"ubuntu · python 3.12 · browser · shard {k}/2" for k in (1, 2)], plain
    assert sorted(n for n, _ in shuffled) == [f"suite · shuffled · browser · shard {k}/2" for k in (1, 2)], shuffled
    for runs in (plain, shuffled):
        assert sorted(shard_of(s["run"]) for _, s in runs) == [(1, 2), (2, 2)]
        for name, s in runs:
            assert selection(s["run"]) == TIER, name
            assert "-rs" in s["run"].split(), f"{name}: every skip prints its reason"
    for name, s in shuffled:
        assert " -n " not in f" {s['run']} ", f"{name}: a shuffled job under -n runs the scheduler's order"
        assert re.search(r"--shuffle-seed 1(\s|$)", s["run"]) and "-p no:cacheprovider" in s["run"], name


def test_a_job_that_installs_chromium_requires_it_and_a_job_that_does_not_selects_no_browser_test():
    for job in linux_jobs():
        if installs_chromium(job):
            first = min(i for i, s in enumerate(job["steps"]) if "playwright install" in s["run"])
            for s in pytest_steps(job):
                assert job["steps"].index(s) > first, f"{job['name']}: {s['name']} runs before the install"
                assert s["env"].get("AGENTDATA_REQUIRE_BROWSER") == "1", (
                    f"{job['name']} / {s['name']}: a `no chromium` skip could hide here")
                assert "-rs" in s["run"].split(), f"{job['name']} / {s['name']}"
        else:
            for s in pytest_steps(job):
                for name in named_files(s["run"]):
                    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
                        assert "mark.browser" not in f.read(), f"{job['name']}: runs {name} with no browser"
                for kind in BROWSER_KINDS if whole_suite(s["run"]) else ():
                    assert not selects(s["run"], kind), (
                        f"{job['name']} / {s['name']} selects {sorted(kind)} tests with no Chromium "
                        "installed: deselect them, never leave them to skip")
                assert s["env"].get("AGENTDATA_REQUIRE_BROWSER", "") == "", job["name"]


def test_the_ubuntu_legs_leave_the_browser_tier_to_its_jobs_and_3_14_runs_no_browser_test():
    legs = {j["row"]["python"]: j for j in linux_jobs() if j["id"] == "pytest"}
    assert set(legs) == {"3.12", "3.14"}
    assert installs_chromium(legs["3.12"]) and not installs_chromium(legs["3.14"])
    for python, job in legs.items():
        parallel = [s for s in pytest_steps(job) if "-n auto" in s["run"]]
        assert [selection(s["run"]) for s in parallel] == [
            "not browser and not slow and not measured and not scale"], python
        assert selects(next(s["run"] for s in pytest_steps(job) if selection(s["run"]).startswith("slow")),
                       {"browser", "slow"}) is (python == "3.12"), f"{python}: the browser+slow test"
    names = {s["name"] for s in legs["3.12"]["steps"]}
    assert {"the desk's measurements, attached", "the ownership demo, recorded"} <= names


def test_each_seed_is_its_own_serial_job_over_the_whole_non_browser_suite():
    shuffled = [j for j in linux_jobs() if j["id"] == "order-independence"]
    assert [j["name"] for j in shuffled] == [f"suite · shuffled · seed {seed}" for seed in SEEDS]
    for job, seed in zip(shuffled, SEEDS):
        runs = pytest_steps(job)
        assert len(runs) == 1, job["name"]
        run = runs[0]["run"]
        assert selection(run) == "not browser", job["name"]
        assert f"--shuffle-seed {seed} " in run + " " and " -n " not in f" {run} " and not shard_of(run), run
    coverage = [s for j in linux_jobs() if j["id"] == "coverage" for s in pytest_steps(j)]
    assert [selection(s["run"]) for s in coverage] == ["not browser"]


def test_every_new_job_is_capped_writes_its_own_junit_and_reports_it():
    """upload-artifact@v4 refuses a second artifact of the same name in one run, so every expanded
    Linux job uploads its junit files under a name of its own."""
    artifacts = []
    for job in linux_jobs():
        uploads = [s["with"]["name"] for s in job["steps"]
                   if str(s.get("uses", "")).startswith("actions/upload-artifact") and s["with"].get("path") == "junit/"]
        artifacts += uploads
        if job["id"] not in ("browser", "order-independence", "order-independence-browser"):
            continue
        assert isinstance(job["cap"], int) and job["cap"] <= 20, job["name"]
        assert len(uploads) == 1, job["name"]
        summary = [s for s in job["steps"] if "durations.py" in s["run"] and " summarize " in s["run"]]
        assert len(summary) == 1 and "always()" in str(summary[0].get("if")), job["name"]
        env = {**summary[0]["env"], "KEY": job["row"].get("key", ""), "SEED": job["row"].get("seed", "")}
        text = re.sub(r"\$(KEY|SEED)\b", lambda m: env[m.group(1)], summary[0]["run"])
        for s in pytest_steps(job):
            stem = re.search(r"--junitxml=junit/(\S+)\.xml", s["run"]).group(1)
            cap = s["timeout-minutes"]
            assert cap <= job["cap"], f"{job['name']}: {stem}"
            reported = re.search(rf'report {re.escape(stem)} "[^"]+" (\d+)', text) or re.search(
                rf'junit/{re.escape(stem)}\.xml"[^\n]*\n?[^\n]*--cap-minutes (\d+)', text)
            assert reported and int(reported.group(1)) == cap, f"{job['name']}: {stem} is not reported against {cap}"
        assert f"--cap-minutes {job['cap']}" in text, job["name"]
        assert env.get("JOB_NAME", job["name"]) == job["name"] and (
            "$JOB_NAME" in text or f'--job "{job["name"]}"' in text.replace("$SEED", "")), job["name"]
    assert len(artifacts) == len(set(artifacts)), artifacts


def test_the_matrix_reader_expands_axes_and_include_rows_as_actions_does():
    assert rows_of({}) == [{}]
    assert rows_of({"strategy": {"matrix": {"seed": ["1", "2"]}}}) == [{"seed": "1"}, {"seed": "2"}]
    assert rows_of({"strategy": {"matrix": {"include": [{"shard": "1/2", "key": "1"}]}}}) == [{"shard": "1/2", "key": "1"}]
    assert rows_of({"strategy": {"matrix": {"seed": ["1"], "include": [{"seed": "1", "key": "a"}, {"seed": "9"}]}}}) == [
        {"seed": "1", "key": "a"}, {"seed": "9"}]
