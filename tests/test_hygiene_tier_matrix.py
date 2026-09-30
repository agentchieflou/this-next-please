"""Which tier runs where in CI, as a matrix generated from tests.yml and kept honest here (#315).

tests/tier_matrix.py expands every job per matrix row, evaluates each step's `if:` and each pytest
command's `-m` with pytest's own marker grammar, and renders the table in docs/testing-this-repo.md
§What CI runs. These tests keep that block equal to the workflow, every tier on a Linux and a Windows
job, and no `browser` test selected where no Chromium is installed. That the tier combinations cover
the real collection is checked by the `scale` test in tests/test_suite_hygiene.py, which already
collects the whole suite (decision 13).
"""
from __future__ import annotations

import copy

import pytest

import tier_matrix as tm

SUITE = frozenset()
BROWSER = frozenset({"browser"})
BROWSER_SLOW = frozenset({"browser", "slow"})


def _runs(jobs: dict, durations: dict | None = None) -> list[tm.Run]:
    return tm.runs({"on": {"push": None}, "jobs": jobs}, durations or {"linux": {}, "windows": {}})


def _job(steps, *, runs_on="ubuntu-latest", name=None, matrix=None, python="3.12") -> dict:
    job = {"runs-on": runs_on, "steps": [{"uses": "actions/setup-python@v5", "with": {"python-version": python}},
                                         *steps]}
    if name:
        job["name"] = name
    if matrix:
        job["strategy"] = {"matrix": matrix}
    return job


CHROMIUM = {"run": "python -m playwright install --with-deps chromium"}


def test_the_tier_matrix_in_the_docs_is_the_workflow():
    with open(tm.DOC, encoding="utf-8") as f:
        doc = f.read()
    assert tm.block(doc) == tm.table(), (
        "docs/testing-this-repo.md §What CI runs no longer matches .github/workflows/tests.yml; "
        f"run: {tm.REFRESH}")


def test_every_tier_runs_on_both_oses():
    """Every combination but `laptop` runs on at least one Linux and one Windows job (or EXCEPTIONS
    says why not), and no cell anywhere is SKIPS."""
    runs = tm.runs()
    assert tm.problems(runs) == []
    assert all(isinstance(why, str) and why for why in tm.EXCEPTIONS.values())
    names = {r.job for r in runs}
    for shard in ("1/2", "2/2"):  # #312's jobs, read from the workflow rather than written here
        assert f"ubuntu · python 3.14 · browser · shard {shard}" in names
        assert f"suite · shuffled · browser · shard {shard}" in names
    assert {"suite · shuffled · seed 1", "suite · shuffled · seed 20260904"} <= names
    assert {f"windows · python 3.14 · shard {k}/4" for k in (1, 2, 3, 4)} <= names


def test_removing_a_chromium_install_from_a_job_that_selects_a_browser_test_is_caught():
    workflow = tm.load()
    caught = []
    for job_id, job in workflow["jobs"].items():
        installs = [i for i, s in enumerate(job.get("steps") or [])
                    if "playwright install" in str(s.get("run", "")) and "chromium" in str(s.get("run", ""))]
        if not installs:
            continue
        broken = copy.deepcopy(workflow)
        for i in reversed(installs):
            del broken["jobs"][job_id]["steps"][i]
        found = tm.problems(tm.runs(broken))
        assert any("SKIPS" in p for p in found), f"{job_id}: its Chromium install was removed unnoticed"
        caught.append(job_id)
    assert {"pytest", "browser", "windows", "order-independence-browser"} <= set(caught)


def test_a_matrix_expands_into_one_job_per_row_with_its_if_and_name():
    job = _job([{"if": "matrix.python == '3.12'", "run": "python -m pytest -q -n auto -m 'not browser'"},
                {"if": "matrix.python != '3.12'", "run": "python -m pytest -q -m slow"}],
               name="${{ matrix.os }} · python ${{ matrix.python }}", python="${{ matrix.python }}",
               runs_on="${{ matrix.os }}", matrix={"os": ["ubuntu-latest", "windows-latest"], "python": ["3.12", "3.14"]})
    runs = _runs({"pytest": job})
    assert [(r.job, r.os, r.python, r.command.expr) for r in runs] == [
        ("ubuntu-latest · python 3.12", "ubuntu", "3.12", "not browser"),
        ("ubuntu-latest · python 3.14", "ubuntu", "3.14", "slow"),
        ("windows-latest · python 3.12", "windows", "3.12", "not browser"),
        ("windows-latest · python 3.14", "windows", "3.14", "slow"),
    ]
    assert tm.summary_cell(runs, ("ubuntu", "3.12"), SUITE) == "parallel"
    assert tm.summary_cell(runs, ("windows", "3.14"), SUITE) == "—"
    with pytest.raises(tm.TierMatrixError):
        _runs({"j": _job([{"if": "github.event_name == 'push'", "run": "python -m pytest"}])})


def test_shards_and_a_shuffled_step_render_as_such():
    shards = _job([CHROMIUM, {"run": "python -m pytest -q -p no:cacheprovider --shard=${{ matrix.shard }} "
                                     "--shuffle-seed 1 -m \"browser and not slow\""}],
                  name="shuffled · ${{ matrix.shard }}", matrix={"shard": ["1/3", "2/3", "3/3"]})
    runs = _runs({"b": shards})
    assert [r.command.shard for r in runs] == [(1, 3), (2, 3), (3, 3)]
    assert {r.command.seed for r in runs} == {"1"}
    assert tm.summary_cell(runs, ("ubuntu", "3.12"), BROWSER) == "3 shards, shuffled"
    assert tm.job_cell([runs[0]], BROWSER) == "shuffled" and tm.job_cell([runs[0]], SUITE) == "—"
    seeds = _runs({"s": _job([{"run": "python -m pytest -q -m 'not browser' --shuffle-seed ${{ matrix.seed }}"}],
                             matrix={"seed": ["1", "2"]})})
    assert tm.summary_cell(seeds, ("ubuntu", "3.12"), SUITE) == "shuffled (2 seeds)"


def test_coverage_run_reads_only_a_marker_m_after_the_pytest_token():
    with_marker = tm.commands('python -m coverage run -m pytest -q -ra -m "not browser" --junitxml=j.xml\n'
                              "python -m coverage json -o coverage.json")
    without = tm.commands("python -m coverage run -m pytest -q -ra --durations=10")
    assert [c.expr for c in with_marker] == ["not browser"]
    assert [c.expr for c in without] == [""]
    assert tm.commands("python -m agentdata --help") == []
    piped = tm.commands("set -o pipefail\npython -m pytest -q -s \\\n  tests/test_a.py tests/test_b.py \\\n"
                        "  2>&1 | tee out.txt")
    assert [c.files for c in piped] == [["tests/test_a.py", "tests/test_b.py"]]
    runs = _runs({"c": _job([{"run": "python -m coverage run -m pytest -q"}])})
    assert runs[0].combos == tm.COMBINATIONS  # no marker -m: every tier
    assert tm.job_cell(runs, BROWSER) == "SKIPS"


def test_a_collect_only_laptop_step_counts_for_nothing():
    runs = _runs({"lint": _job([{"run": "python -m pytest -q --collect-only -m laptop | tee collected.txt"}])})
    assert runs == []


def test_named_files_select_only_the_tiers_they_hold():
    durations = {"linux": {"tests/test_a.py": {"browser": 1.0, "default": 0.1}}, "windows": {}}
    runs = _runs({"m": _job([CHROMIUM, {"run": "python -m pytest -q tests/test_a.py"}])}, durations)
    assert runs[0].combos == (SUITE, BROWSER)
    assert tm.job_cell(runs, BROWSER) == "serial, named files"
    with pytest.raises(tm.TierMatrixError, match="durations.json"):
        _runs({"m": _job([{"run": "python -m pytest -q tests/test_new.py"}])}, durations)


def test_a_job_without_chromium_whose_slow_step_selects_the_browser_slow_test_skips_it_alone():
    runs = _runs({"leg": _job([{"run": "python -m pytest -q -rs -m slow"}], name="no browser")})
    cells = {c: tm.job_cell(runs, c) for c in tm.COMBINATIONS}
    assert [tm.label(c) for c, word in cells.items() if word == "SKIPS"] == ["browser+slow"]
    assert cells[frozenset({"slow"})] == "serial"
    assert [p for p in tm.problems(runs) if "SKIPS" in p] == [
        "no browser / python -m pytest -q -rs -m slow: selects browser+slow with no Chromium installed (SKIPS)"]
    fixed = _runs({"leg": _job([{"run": "python -m pytest -q -rs -m 'slow and not browser'"}], name="no browser")})
    assert tm.job_cell(fixed, BROWSER_SLOW) == "—"


def test_an_expression_naming_a_marker_that_is_not_a_tier_is_refused():
    assert tm.evaluate("(measured or scale) and not slow", frozenset({"measured", "scale"}))
    assert not tm.evaluate("browser and not slow", BROWSER_SLOW)
    with pytest.raises(tm.TierMatrixError, match="windows"):
        tm.evaluate("not windows", SUITE)
