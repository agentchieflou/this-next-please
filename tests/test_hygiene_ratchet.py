"""Flat waits, skips, xfail, deselection and lost tests are ratcheted (#306).

No browser test waits on a clock, nothing is marked to fail, no pytest command deselects, and the
per-file counts in `tests/hygiene_baseline.json` move one way only: skips and fall-through loops
down, `def test_*` up. The counting is `.github/scripts/hygiene_baseline.py`'s, over every file
under `tests/` parsed once with `ast` (no test module is imported); `--update` there lowers and
raises the baseline. docs/testing-this-repo.md says what counts and how to lower it.

Every needle in this file is built by concatenation, so the file never holds what it looks for.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "hygiene_baseline.py")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "tests.yml")
PYPROJECT = os.path.join(ROOT, "pyproject.toml")

WAIT = "wait_for" + "_timeout"
SLEEP = "time." + "sleep"
SKIP_MARK = "pytest.mark." + "skip"
XFAIL_MARK = "pytest.mark." + "xfail"
DESELECT = re.compile(r"(?:^|\s)(--" + r"deselect|-" + r"k|--" + r"ignore|--" + r"ignore-glob)(?:=|\s|$)")


def _load():
    spec = importlib.util.spec_from_file_location("hygiene_baseline_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _load()


@functools.cache
def _tree() -> dict:
    """Every file under tests/, scanned once for the whole module."""
    return H.scan_tree()


@functools.cache
def _baseline() -> dict:
    return H.load()


def _scan(source: str) -> dict:
    return H.scan_source(source, "tests/test_example.py")


# ------------------------------------------------------------------------------ the five ratchets


def test_no_flat_waits():
    found = [f"{path}:{line}: {what}" for path, s in _tree().items() for line, what in s["flat"]]
    assert not found, ("a browser test waits on a clock:\n  " + "\n  ".join(found)
                       + "\n" + H.FIX_WAIT)
    base = _baseline()
    more = [f"{path}:{s['loops'][-1]}: {len(s['loops'])} fall-through loop(s), the baseline has "
            f"{base.get(path, {}).get('loops', 0)}"
            for path, s in _tree().items() if len(s["loops"]) > base.get(path, {}).get("loops", 0)]
    assert not more, ("a polling loop runs out its deadline and carries on:\n  " + "\n  ".join(more)
                      + "\n" + H.FIX_LOOP)


def test_no_new_skips():
    base = _baseline()
    more = [f"{path}:{s['skips'][-1]}: {len(s['skips'])} skip(s), the baseline has "
            f"{base.get(path, {}).get('skips', 0)} (lines {s['skips']})"
            for path, s in _tree().items() if len(s["skips"]) > base.get(path, {}).get("skips", 0)]
    assert not more, "a new skip:\n  " + "\n  ".join(more) + "\n" + H.FIX_SKIP


def test_no_xfail():
    found = [f"{path}:{line}" for path, s in _tree().items() for line in s["xfail"]]
    assert not found, ("a test marked to fail: " + ", ".join(found)
                       + "\nfix the test or the code; a known failure is an open issue, not a mark")


def deselections(workflow_text: str, addopts: str, conftests: dict[str, str]) -> list[str]:
    """Where a pytest command deselects: `--deselect`, `-k`, `--ignore` or `--ignore-glob` in a
    workflow's pytest command or in `addopts`, or a `collect_ignore` in a conftest."""
    out = []
    for name, job in (yaml.safe_load(workflow_text).get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = str(step.get("run", "")).replace("\\\n", " ")
            for line in run.splitlines():
                if "pytest" in line:
                    m = DESELECT.search(line[line.index("pytest"):])
                    if m:
                        out.append(f"tests.yml job {name}: {m.group(1)} in `{line.strip()[:120]}`")
    m = DESELECT.search(" " + addopts)
    if m:
        out.append(f"pyproject.toml addopts: {m.group(1)}")
    for path, source in conftests.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Name) and node.id.startswith("collect_" + "ignore"):
                out.append(f"{path}:{node.lineno}: {node.id}")
    return out


def _conftests() -> dict[str, str]:
    out = {}
    for path in H.test_files():
        if os.path.basename(path) == "conftest.py":
            with open(path, encoding="utf-8") as f:
                out[H.rel(path)] = f.read()
    return out


def test_no_deselection():
    with open(WORKFLOW, encoding="utf-8") as f:
        workflow = f.read()
    with open(PYPROJECT, "rb") as f:
        addopts = tomllib.load(f)["tool"]["pytest"]["ini_options"].get("addopts", "")
    found = deselections(workflow, addopts if isinstance(addopts, str) else " ".join(addopts),
                         _conftests())
    assert not found, ("a test is left out of a run:\n  " + "\n  ".join(found)
                       + "\na test that must not run on a platform keeps its marker and its skipif")


def test_no_test_is_lost():
    base, tree = _baseline(), _tree()
    lost = [f"{path}: {tree.get(path, {}).get('tests', 0)} test(s), the baseline has {row['tests']}"
            for path, row in base.items() if tree.get(path, {}).get("tests", 0) < row.get("tests", 0)]
    assert not lost, ("a test went missing:\n  " + "\n  ".join(lost)
                      + "\nput it back, or lower the baseline by hand with the reason in the commit")


def test_the_baseline_is_the_tree_as_counted():
    """Nothing is lower than the tree needs and no file is listed that is not there: a count the
    ratchet let fall is written down, so it cannot quietly rise again."""
    now, base = H.counts(_tree()), _baseline()
    stale = sorted(p for p in set(now) | set(base) if now.get(p) != base.get(p))
    assert not stale, ("tests/hygiene_baseline.json is behind the tree: "
                       + ", ".join(f"{p} {base.get(p)} -> {now.get(p)}" for p in stale[:10])
                       + "\nrun `python .github/scripts/hygiene_baseline.py --update`")


# ------------------------------------------------------------------------ the counters, on source

BROWSER = "from desk_waits import settle\nimport time\n"


def test_a_wait_in_a_helper_counts_and_a_string_naming_it_does_not():
    got = _scan("def _helper(page):\n    page." + WAIT + "(100)\n")
    assert [line for line, _ in got["flat"]] == [2], got
    assert "wait_for_function" in H.FIX_WAIT and "settle" in H.FIX_WAIT and "observe_quiet" in H.FIX_WAIT
    assert _scan("NOTE = 'never call page." + WAIT + "(100)'\n")["flat"] == []
    assert _scan("x = getattr(page, " + repr(WAIT) + ")\n")["flat"] == []


def test_a_sleep_in_a_deadline_loop_counts_only_without_a_closing_raise_or_assert():
    loop = ("def wait(ready):\n"
            "    deadline = time.monotonic() + 5\n"
            "    while time.monotonic() < deadline:\n"
            "        if ready():\n"
            "            return True\n"
            "        " + SLEEP + "(0.05)\n")
    fell = _scan(BROWSER + loop + "    return False\n")
    assert fell["loops"] == [5] and fell["flat"] == [], fell
    assert _scan(BROWSER + loop + "    raise AssertionError('never')\n")["loops"] == []
    inside = ("def wait(ready):\n"
              "    deadline = time.monotonic() + 5\n"
              "    while not ready():\n"
              "        assert time.monotonic() < deadline, 'never'\n"
              "        " + SLEEP + "(0.05)\n")
    assert _scan(BROWSER + inside)["loops"] == []
    orelse = loop.replace("    while", "    while") + "    else:\n        raise AssertionError('never')\n"
    assert _scan(BROWSER + orelse)["loops"] == []
    # A bare sleep in a browser file is a flat wait; in a file with no browser it is not counted.
    bare = "def test_x(desk_browser):\n    " + SLEEP + "(0.5)\n"
    assert [line for line, _ in _scan("import time\n" + bare)["flat"]] == [3]
    assert _scan("import time\ndef test_x():\n    " + SLEEP + "(0.5)\n")["flat"] == []
    # An alias of the module, and a helper's raise that is not the loop's own, are seen through.
    alias = "import desk_harness\nimport time as _t\ndef f():\n    while True:\n        _t.sleep(1)\n"
    assert _scan(alias)["loops"] == [4]
    nested = (BROWSER + "def f(ready):\n    while not ready():\n        def g():\n"
              "            raise ValueError\n        " + SLEEP + "(0.1)\n")
    assert _scan(nested)["loops"] == [4]


def test_the_js_pattern_flags_a_fixed_timer_and_not_a_delayed_stub():
    flat = "await new Promise(d => set" + "Timeout(d, 700));"
    assert [line for line, _ in _scan("JS = '''\n  x();\n  " + flat + "\n'''\n")["flat"]] == [3]
    assert _scan("JS = 'await new Promise(go => set" + "Timeout(go, 50))'\n")["flat"] != []
    stub = "new Promise(go => set" + "Timeout(() => go({ ok: true }), 1500))"
    assert _scan("JS = " + repr(stub) + "\n")["flat"] == []
    assert H.scan_source("JS = " + repr(flat) + "\n", "tests/desk_waits.py")["flat"] == []


def test_skips_are_counted_and_a_platform_skipif_beside_its_marker_is_not():
    src = ("import os, sys, pytest\n"
           "pytestmark = pytest.mark.skipif(os.name == 'nt', reason='x')\n"
           "@" + SKIP_MARK + "(reason='flaky')\n"
           "def test_a(): pass\n"
           "def test_b():\n    pytest.skip('no')\n"
           "def test_c():\n    pytest.importorskip('numpy')\n"
           "@pytest.mark.windows\n@pytest.mark.skipif(os.name != 'nt', reason='windows only')\n"
           "def test_d(): pass\n"
           "@pytest.mark.posix\n@pytest.mark.skipif(sys.platform.startswith('win'), reason='posix')\n"
           "def test_e(): pass\n"
           "@pytest.mark.skipif(os.name != 'nt', reason='no marker')\n"
           "def test_f(): pass\n"
           "@pytest.mark.windows\n@pytest.mark.skipif(os.name != 'nt' or FAST, reason='not only')\n"
           "def test_g(): pass\n")
    got = _scan(src)
    assert got["skips"] == [2, 3, 6, 8, 15, 18], got
    assert got["tests"] == 7


def test_xfail_is_counted():
    got = _scan("import pytest\n@" + XFAIL_MARK + "\ndef test_a(): pass\n"
                "def test_b():\n    pytest.xf" + "ail('later')\n")
    assert got["xfail"] == [2, 5], got


def test_a_deselection_is_found_where_it_is_written():
    wf = ("jobs:\n  a:\n    steps:\n"
          "      - run: python -m pytest -q " + "-" + "k 'not x' tests\n"
          "      - run: sort -k 2 file.txt\n"
          "      - run: |\n          python -m pytest -q \\\n            --" + "ignore=tests/x.py\n")
    got = deselections(wf, "--strict-markers", {"tests/conftest.py": "collect_" + "ignore = ['x.py']\n"})
    assert len(got) == 3 and "-" + "k" in got[0] and "ignore" in got[1] and got[2] == "tests/conftest.py:1: collect_" + "ignore", got
    assert deselections("jobs: {}\n", "--strict-markers --" + "deselect tests/a.py::t", {}) != []
    assert deselections("jobs: {}\n", "--strict-markers", {"c": "x = 1\n"}) == []


# ----------------------------------------------------------------------------- the --update script


def _tree_with(tmp_path, files: dict[str, str]):
    root = tmp_path / "tests"
    root.mkdir()
    for name, source in files.items():
        (root / name).write_text(source, encoding="utf-8")
    return root


def _update(root, baseline, *more):
    return subprocess.run([sys.executable, SCRIPT, "--root", str(root), "--baseline", str(baseline),
                           *more], capture_output=True, text=True, timeout=60)


def test_update_lowers_a_count_after_a_skip_is_removed_and_exits_2_when_one_would_rise(tmp_path):
    two = ("import pytest\n@" + SKIP_MARK + "(reason='a')\ndef test_a(): pass\n"
           "@" + SKIP_MARK + "(reason='b')\ndef test_b(): pass\n")
    root = _tree_with(tmp_path, {"test_x.py": two})
    baseline = tmp_path / "baseline.json"
    assert _update(root, baseline, "--update").returncode == 0
    assert json.loads(baseline.read_text())["files"]["tests/test_x.py"] == {"skips": 2, "tests": 2}

    (root / "test_x.py").write_text(two.replace("@" + SKIP_MARK + "(reason='b')\n", ""), encoding="utf-8")
    assert _update(root, baseline, "--update").returncode == 0
    assert json.loads(baseline.read_text())["files"]["tests/test_x.py"] == {"skips": 1, "tests": 2}

    (root / "test_x.py").write_text(two, encoding="utf-8")        # the skip comes back
    out = _update(root, baseline, "--update")
    assert out.returncode == 2 and "tests/test_x.py: skips 1 -> 2" in out.stdout, out
    assert "hand edit" in out.stderr
    assert json.loads(baseline.read_text())["files"]["tests/test_x.py"]["skips"] == 1, "nothing was written"

    (root / "test_x.py").write_text("def test_a(): pass\n", encoding="utf-8")   # a test goes
    out = _update(root, baseline, "--update")
    assert out.returncode == 2 and "tests/test_x.py: tests 2 -> 1" in out.stdout, out
