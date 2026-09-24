""".github/scripts/durations.py on synthetic xunit2 junit files (#309).

Each testcase carries the `file` and `markers` properties `tests/conftest.py` records, the way
pytest's default `junit_family` writes them: no `file` attribute, a `<properties>` block instead.
"""
from __future__ import annotations
import importlib.util
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, ".github", "scripts", "durations.py")


@pytest.fixture(scope="module")
def durations():
    spec = importlib.util.spec_from_file_location("durations_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def junit(path, cases, wall):
    """cases: (file, name, markers, seconds). An xunit2 file, as pytest writes it."""
    rows = []
    for file, name, markers, seconds in cases:
        rows.append(
            f'<testcase classname="{file[:-3].replace("/", ".")}" name="{name}" time="{seconds}">'
            f'<properties><property name="file" value="{file}" />'
            f'<property name="markers" value="{markers}" /></properties></testcase>')
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="{len(cases)}" '
        f'time="{wall}" timestamp="2026-09-24T18:00:00" hostname="runner">'
        + "".join(rows) + "</testsuite></testsuites>", encoding="utf-8")
    return str(path)


CASES = [
    ("tests/test_a.py", "test_one", "", 1.0),
    ("tests/test_a.py", "test_two", "parametrize", 2.0),
    ("tests/test_b.py", "test_page", "browser", 5.0),
    ("tests/test_b.py", "test_page_fast", "browser,measured", 0.5),
    ("tests/test_c.py", "test_venv", "slow,usefixtures", 7.5),
]


def test_tier_is_the_sorted_tier_markers_or_default(durations):
    assert durations.tier_of("") == "default"
    assert durations.tier_of("parametrize,usefixtures") == "default"
    assert durations.tier_of("slow,browser") == "browser+slow"
    assert durations.tier_of("measured,browser,real_home") == "browser+measured"


def test_summarize_sums_per_tier_and_orders_the_top_files_and_tests(tmp_path, durations):
    path = junit(tmp_path / "j.xml", CASES, wall=20.0)
    out = durations.summarize([path], "the suite", 5)
    assert out.startswith("### `the suite`: 0m20s of its 5-minute cap (7%)")
    assert "| default | 2 | 3.0 s |" in out
    assert "| browser | 1 | 5.0 s |" in out
    assert "| browser+measured | 1 | 0.5 s |" in out
    assert "| slow | 1 | 7.5 s |" in out
    files = [ln.split("`")[1] for ln in out.splitlines() if ln.startswith("| `tests/test_") and "::" not in ln]
    assert files == ["tests/test_c.py", "tests/test_b.py", "tests/test_a.py"]
    tests = [ln.split("`")[1] for ln in out.splitlines() if ln.startswith("| `") and "::" in ln]
    assert tests == ["tests/test_c.py::test_venv", "tests/test_b.py::test_page", "tests/test_a.py::test_two",
                     "tests/test_a.py::test_one", "tests/test_b.py::test_page_fast"]
    assert "::warning" not in out


def test_the_top_lists_stop_at_fifteen(tmp_path, durations):
    cases = [(f"tests/test_{i:02d}.py", "test_x", "", float(i)) for i in range(20)]
    out = durations.summarize([junit(tmp_path / "j.xml", cases, wall=1.0)], "s", 5)
    files = [ln for ln in out.splitlines() if ln.startswith("| `tests/test_") and "::" not in ln]
    tests = [ln for ln in out.splitlines() if ln.startswith("| `") and "::" in ln]
    assert len(files) == 15 and len(tests) == 15
    assert files[0].startswith("| `tests/test_19.py`") and files[-1].startswith("| `tests/test_05.py`")


def test_the_warning_is_printed_above_three_quarters_of_the_cap_only(tmp_path, durations):
    cap = 10  # minutes: 600 s
    at_76 = durations.summarize([junit(tmp_path / "a.xml", CASES, wall=456.0)], "pytest", cap)
    at_74 = durations.summarize([junit(tmp_path / "b.xml", CASES, wall=444.0)], "pytest", cap)
    assert at_76.rstrip().splitlines()[-1] == "::warning title=pytest near its cap::pytest took 456 s of 10 min"
    assert "::warning" not in at_74


def test_the_job_line_warns_the_same_way(tmp_path, durations):
    a = junit(tmp_path / "a.xml", CASES, wall=1200.0)
    b = junit(tmp_path / "b.xml", CASES, wall=620.0)
    out = durations.job_line([a, b], "windows · python 3.14", 40)
    assert "30m20s of the job's 40-minute cap (76%)" in out
    assert "::warning title=windows · python 3.14 near its cap::" in out
    assert "::warning" not in durations.job_line([b], "w", 40)


def test_update_sums_within_one_file_and_takes_the_max_across_files(tmp_path, durations):
    one = junit(tmp_path / "one.xml", CASES, wall=20.0)
    two = junit(tmp_path / "two.xml", [("tests/test_a.py", "test_one", "", 4.0),
                                       ("tests/test_b.py", "test_page", "browser", 1.25)], wall=6.0)
    assert durations.durations([one, two]) == {
        "tests/test_a.py": {"default": 4.0},                         # max(1 + 2, 4), not 7
        "tests/test_b.py": {"browser": 5.0, "browser+measured": 0.5},  # max(5, 1.25)
        "tests/test_c.py": {"slow": 7.5},
    }


def test_update_keeps_the_other_os_and_is_byte_stable(tmp_path, durations):
    one = junit(tmp_path / "one.xml", CASES, wall=20.0)
    out = tmp_path / "durations.json"
    out.write_text(json.dumps({"windows": {"tests/test_z.py": {"default": 9.0}}}), encoding="utf-8")
    run = [sys.executable, SCRIPT, "update", one, "--os", "linux", "--out", str(out)]
    subprocess.run(run, check=True)
    first = out.read_bytes()
    subprocess.run(run, check=True)
    assert out.read_bytes() == first
    data = json.loads(first)
    assert data["windows"] == {"tests/test_z.py": {"default": 9.0}}
    assert list(data["linux"]) == sorted(data["linux"])
    assert data["linux"]["tests/test_a.py"] == {"default": 3.0}


def test_the_values_are_rounded_to_a_tenth(tmp_path, durations):
    path = junit(tmp_path / "j.xml", [("tests/test_a.py", "t", "", 1.234), ("tests/test_a.py", "u", "", 0.01)], 1)
    assert durations.durations([path]) == {"tests/test_a.py": {"default": 1.2}}


def test_a_missing_junit_file_is_named(tmp_path):
    p = subprocess.run([sys.executable, SCRIPT, "summarize", str(tmp_path / "nope.xml"), "--step", "s",
                        "--cap-minutes", "5"], capture_output=True, text=True)
    assert p.returncode == 2 and "nope.xml" in p.stderr


def test_the_suite_records_the_file_and_the_markers_on_every_test(request):
    props = dict(request.node.user_properties)
    assert props["file"] == "tests/test_durations_script.py"
    assert "markers" in props
