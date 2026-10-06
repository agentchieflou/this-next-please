"""Linux runs the browser tier once per run in its own shards, and once more shuffled (#312).

What each Linux job runs is decided before a runner starts, by its matrix and each step's `if:`, so it
is checked here the way tests/test_hygiene_windows_shards.py checks the Windows jobs: every job is
expanded per matrix row, every `if:` is evaluated against the row, and every pytest step's `-m` is
evaluated with pytest's own marker grammar against the marker sets a test can carry. How long a job
takes only a run can say; the step budgets are tests/test_hygiene_ci_budgets.py's (#309).
"""
from __future__ import annotations
import ast
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


def test_the_browser_tier_runs_once_on_ubuntu_3_14_in_two_shards_plus_once_shuffled():
    jobs = linux_jobs()
    plain, shuffled = [], []
    for job in jobs:
        for s in pytest_steps(job):
            if whole_suite(s["run"]) and selects(s["run"], {"browser"}):
                (shuffled if "--shuffle-seed" in s["run"] else plain).append((job["name"], s))
    # The shuffled tier is three shards since 2026-10-06 (shard 1 of two overran its 15-minute cap; the
    # operator's sign-off): serial, so it needs more of them than the `-n 2` plain jobs.
    assert sorted(n for n, _ in plain) == [f"ubuntu · python 3.14 · browser · shard {k}/2" for k in (1, 2)], plain
    assert sorted(n for n, _ in shuffled) == [f"suite · shuffled · browser · shard {k}/3" for k in (1, 2, 3)], shuffled
    for runs, total in ((plain, 2), (shuffled, 3)):
        assert sorted(shard_of(s["run"]) for _, s in runs) == [(k, total) for k in range(1, total + 1)]
        for name, s in runs:
            assert selection(s["run"]) == TIER, name
            assert "-rs" in s["run"].split(), f"{name}: every skip prints its reason"
    for name, s in shuffled:
        assert " -n " not in f" {s['run']} ", f"{name}: a shuffled job under -n runs the scheduler's order"
        assert re.search(r"--shuffle-seed 1(\s|$)", s["run"]) and "-p no:cacheprovider" in s["run"], name


def carries_browser_marker(rel: str) -> bool:
    """`mark.browser` in the code: a decorator, `pytestmark`, a `param(marks=...)`, `pytest.` or a bare `mark`.
    A file that only names the marker in a string or a comment (a hygiene test about it, #595's smoke) is not
    a browser test."""
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=rel)
    return any(isinstance(n, ast.Attribute) and n.attr == "browser"
               and ((isinstance(n.value, ast.Attribute) and n.value.attr == "mark")
                    or (isinstance(n.value, ast.Name) and n.value.id == "mark")) for n in ast.walk(tree))


def test_the_marker_check_reads_code_not_strings():
    assert carries_browser_marker("tests/test_fleet_settings_page.py")
    assert not carries_browser_marker("tests/test_hygiene_ci_paths.py"), "it names the marker only in a docstring"
    assert not carries_browser_marker("tests/test_entrypoints.py")


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
                    assert not carries_browser_marker(name), f"{job['name']}: runs {name} with no browser"
                for kind in BROWSER_KINDS if whole_suite(s["run"]) else ():
                    assert not selects(s["run"], kind), (
                        f"{job['name']} / {s['name']} selects {sorted(kind)} tests with no Chromium "
                        "installed: deselect them, never leave them to skip")
                assert s["env"].get("AGENTDATA_REQUIRE_BROWSER", "") == "", job["name"]


def test_one_ubuntu_leg_on_3_14_leaves_the_browser_tier_to_its_jobs_and_keeps_every_other_step():
    """#591 (decision 23): the two ubuntu legs became one, on 3.14, and it took over every step the
    old floor leg's `if:`s gave it alone: Chromium, `tsc`, the measured and slow browser tests, the
    measurements and the demo. No step on it is conditional on the Python version any more."""
    legs = [j for j in linux_jobs() if j["id"] == "pytest"]
    assert [(j["name"], j["row"]["python"]) for j in legs] == [("ubuntu-latest · python 3.14", "3.14")]
    job = legs[0]
    assert installs_chromium(job)
    parallel = [s for s in pytest_steps(job) if "-n auto" in s["run"]]
    assert [selection(s["run"]) for s in parallel] == ["not browser and not slow and not measured and not scale"]
    slow = next(s["run"] for s in pytest_steps(job) if selection(s["run"]).startswith("slow"))
    assert selects(slow, {"browser", "slow"}), "the browser+slow test"
    measured = next(s["run"] for s in pytest_steps(job) if "measured" in selection(s["run"]).split()[0])
    assert selects(measured, {"browser", "measured"}), "the measured browser tests"
    names = {s["name"] for s in job["steps"]}
    assert {"a browser, so tests/test_fleet_desk*.py run instead of skipping", "the desk's types (tsc --noEmit)",
            "the desk's measurements, attached", "the ownership demo, recorded", "upload the demo",
            "keep the reference output for the Windows byte-comparison"} <= names
    raw = _workflow()["jobs"]["pytest"]
    assert all("matrix.python" not in str(s.get("if", "")) for s in raw["steps"]), "one leg: no per-Python step"


def test_every_linux_job_runs_3_14_and_only_the_floor_job_installs_3_13():
    """#591: no job names or installs another Python, except the floor job's pip-refusal interpreter."""
    for job_id, job in _workflow()["jobs"].items():
        for s in job.get("steps") or []:
            if not str(s.get("uses", "")).startswith("actions/setup-python"):
                continue
            version = str(s["with"]["python-version"])
            if version == "${{ matrix.python }}":
                assert {r["python"] for r in rows_of(job)} == {"3.14"}, job_id
            elif job_id == "floor-python" and version == "3.13":
                continue
            else:
                assert version == "3.14", f"{job_id}: python-version {version}"
    floor = _workflow()["jobs"]["floor-python"]
    assert floor["name"] == "floor · pip refuses the wheel on Python 3.13"
    versions = [str(s["with"]["python-version"]) for s in floor["steps"]
                if str(s.get("uses", "")).startswith("actions/setup-python")]
    assert versions == ["3.14", "3.13"], "build on the floor, then refuse on the version below it"
    script = "\n".join(str(s.get("run", "")) for s in floor["steps"])
    assert '">=3.14" in m.group(1)' in script, "the wheel's Requires-Python is asserted"
    assert "python3.13 -m pip install" in script and "requires a different Python" in script
    assert "not in '>=3.14'" in script, "the refusal is for the 3.14 floor, in pip's words"


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
