"""Guards for the suite's own plumbing: markers, isolation, coverage floors, the regression convention.

These are the tests that keep the tests honest. Without them the isolation quietly stops isolating
the first time someone adds a fixture, and a coverage floor becomes a number nobody looks at.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOORS = os.path.join(REPO_ROOT, ".github", "scripts", "coverage-floors.json")


# ------------------------------------------------------------------------------------ isolation


def test_the_home_is_temporary(isolated_home):
    """A test must not be able to touch the developer's own config."""
    assert isolated_home is not None
    assert os.path.realpath(os.path.expanduser("~")) == os.path.realpath(str(isolated_home)),         "`~` must resolve inside the temporary home, or a test could write to the real one"
    assert os.environ["AGENTDATA_CONFIG"].startswith(str(isolated_home))


def test_writing_the_config_lands_in_the_temporary_home(isolated_home):
    from agentdata import config

    cfg = config.load()
    config.put(cfg, "graph.min_coverage", 0.9)
    written = config.save(cfg)
    assert str(isolated_home).replace("\\", "/") in written, \
        f"a test wrote to {written}, outside its temporary home"


@pytest.mark.real_home
def test_the_escape_hatch_gives_back_the_real_home():
    """`real_home` exists for the few tests that are about this checkout, not about a temp dir."""
    assert os.environ.get("AGENTDATA_CONFIG") is None or "pytest" not in os.environ["AGENTDATA_CONFIG"]


def test_colour_is_off_and_output_is_plain():
    from agentdata import color, ui

    assert os.environ["NO_COLOR"] == "1"
    assert os.environ["AGENTDATA_UI"] == "plain"
    color.reset_cache()
    assert color.enabled() is False
    assert ui.on() is False


# -------------------------------------------------------------------------------------- markers


def test_every_marker_used_is_declared():
    """--strict-markers turns a typo into a collection error rather than a silent no-op."""
    text = open(os.path.join(REPO_ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert "--strict-markers" in text
    for marker in ("slow", "laptop", "windows", "posix", "real_home", "network"):
        assert f'"{marker}:' in text, f"marker {marker} is not declared"


def test_an_unknown_marker_fails_collection(tmp_path):
    probe = tmp_path / "test_bad_marker.py"
    probe.write_text("import pytest\n\n\n@pytest.mark.definitely_not_declared\ndef test_x():\n    pass\n",
                     encoding="utf-8")
    # -c so the probe is judged by *our* config: a file in tmp_path would otherwise get its own
    # rootdir, where --strict-markers is not set and the assertion would prove nothing
    p = subprocess.run([sys.executable, "-m", "pytest", "-q",
                        "-c", os.path.join(REPO_ROOT, "pyproject.toml"), str(probe)],
                       capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode != 0, p.stdout
    message = (p.stdout + p.stderr).lower()
    assert "definitely_not_declared" in message and "markers" in message, message[:400]


def test_the_laptop_suite_does_not_execute_without_the_flag():
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "laptop", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, cwd=REPO_ROOT,
                       env={k: v for k, v in os.environ.items() if k != "AGENTDATA_LAPTOP"})
    assert " passed" not in p.stdout, "a laptop test ran without AGENTDATA_LAPTOP=1"
    assert "skipped" in p.stdout


# ------------------------------------------------------------------------------ coverage floors


def test_the_floors_cover_the_modules_the_laptop_keeps_breaking():
    with open(FLOORS, encoding="utf-8") as f:
        floors = json.load(f)
    # Per platform: these modules' Windows branches (the console API through ctypes, msvcrt, the
    # long-path prefix, the MSYS pty probe) are unreachable on Linux, so one set of numbers would
    # fail on the other OS for nobody's fault -- which is how a floor becomes a thing people disable.
    assert set(floors) == {"windows", "posix"}
    for platform, per_module in floors.items():
        for module in ("agentdata/proc.py", "agentdata/textio.py", "agentdata/update.py",
                       "agentdata/console.py", "agentdata/color.py", "agentdata/state.py",
                       "agentdata/config.py"):
            assert module in per_module, f"{module} has no {platform} coverage floor"
            assert 0 < per_module[module] <= 100


def test_there_is_no_repo_wide_floor():
    """A single percentage invites padding; the point is the modules that break on Windows."""
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    assert "--fail-under" not in workflow, "a repo-wide floor crept in"
    assert "coverage_floors.py" in workflow


def test_the_floor_checker_fails_when_a_module_drops(tmp_path):
    """The guard has to be able to fail."""
    fake = tmp_path / "coverage.json"
    fake.write_text(json.dumps({"files": {
        "agentdata/proc.py": {"summary": {"percent_covered": 1.0}},
        "agentdata/textio.py": {"summary": {"percent_covered": 99.0}},
        "agentdata/update.py": {"summary": {"percent_covered": 99.0}},
        "agentdata/console.py": {"summary": {"percent_covered": 99.0}},
        "agentdata/color.py": {"summary": {"percent_covered": 99.0}},
        "agentdata/state.py": {"summary": {"percent_covered": 99.0}},
        "agentdata/config.py": {"summary": {"percent_covered": 99.0}},
    }}), encoding="utf-8")
    p = subprocess.run([sys.executable, os.path.join(REPO_ROOT, ".github", "scripts", "coverage_floors.py"),
                        "--coverage-json", str(fake)], capture_output=True, text=True, cwd=REPO_ROOT)
    assert p.returncode == 1
    assert "below its floor" in p.stderr


# ------------------------------------------------------------------------------------- the docs


def test_the_suite_is_documented():
    text = open(os.path.join(REPO_ROOT, "docs", "testing-this-repo.md"), encoding="utf-8").read()
    for needle in ("## Markers", "## Isolation", "## Coverage floors",
                   "## The regression convention", "## What CI runs"):
        assert needle in text
    assert "about two minutes" in text, "record how long the suite takes"


def test_shuffling_is_available_and_wired_into_ci():
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    assert "--shuffle-seed" in workflow
    conftest = open(os.path.join(REPO_ROOT, "tests", "conftest.py"), encoding="utf-8").read()
    assert "shuffle-seed" in conftest
