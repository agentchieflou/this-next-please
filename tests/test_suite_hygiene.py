"""Guards for the suite's own plumbing: markers, isolation, coverage floors, the regression convention.

These are the tests that keep the tests honest. Without them the isolation quietly stops isolating
the first time someone adds a fixture, and a coverage floor becomes a number nobody looks at.
"""
from __future__ import annotations
import ast
import json
import os
import re
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


def test_pip_caches_outside_the_repository(isolated_home):
    """The slow tests really run `pip wheel` and `pip install`.

    Redirecting the profile without setting this makes pip fall back to a *relative* cache
    directory, so those runs wrote 3.8 MB of HTTP cache into `<repo>/pip/cache` -- inside the
    repository under test, staged by the next `git add -A`. Found when it very nearly was.
    """
    cache = os.environ.get("PIP_CACHE_DIR", "")
    assert cache.startswith(str(isolated_home)), f"pip would cache to {cache!r}"
    out = subprocess.run([sys.executable, "-m", "pip", "cache", "dir"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    if out.returncode == 0:
        resolved = os.path.realpath(out.stdout.strip())
        assert not resolved.startswith(os.path.realpath(REPO_ROOT)), \
            f"pip resolves its cache to {resolved}, inside the checkout"


@pytest.mark.real_home
def test_the_escape_hatch_gives_back_the_real_home():
    """`real_home` exists for the few tests that are about this checkout, not about a temp dir."""
    assert os.environ.get("AGENTDATA_CONFIG") is None or "pytest" not in os.environ["AGENTDATA_CONFIG"]


def test_no_test_lists_the_machines_processes(monkeypatch):
    """The desk's adopt offers come from this machine's process table: a PowerShell CIM query on
    Windows, `/proc` elsewhere. The suite sees an empty one and never asks for the real one."""
    from agentdata.fleet import adopt as A

    # Recorded rather than raised: the listing swallows every exception by design, so a refusal
    # raised in here would read as "no processes" and pass without the fixture.
    asked = []
    real_listdir = os.listdir

    def listdir(path="."):
        if str(path) == "/proc":
            asked.append("/proc")
        return real_listdir(path)

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: asked.append(a[0] if a else "run"))
    monkeypatch.setattr(os, "listdir", listdir)
    assert A.agent_processes(max_age=0) == []
    assert A.agent_processes(wait=False) == []
    assert asked == [], f"a test listed the machine's processes: {asked}"


def test_the_desk_catalogue_is_closed_by_the_test_that_opened_it(tmp_path, monkeypatch):
    """`serve` holds its sqlite catalogue in a module global. Left open, the next test's first desk
    request closed it -- a WAL checkpoint under the desk lock, on that test's clock. The conftest
    closes it at teardown instead; this is that close, on a catalogue put where a desk keeps it."""
    import sqlite3

    from agentdata.fleet import catalogue as CAT, serve as S
    from conftest import close_the_desk_catalogue

    cat = CAT.Catalogue.open(str(tmp_path / "catalogue.sqlite"))
    monkeypatch.setattr(S, "_desk", dict(S._desk, catalogue=cat))
    close_the_desk_catalogue()
    assert S._desk["catalogue"] is None
    with pytest.raises(sqlite3.ProgrammingError):
        cat.conn.execute("SELECT 1")


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
    # rootdir, where --strict-markers is not set and the assertion would prove nothing.
    # --rootdir so the collection starts at the probe's own folder: with the rootdir on another
    # drive, pytest walks the probe's ancestors from the filesystem root, and a stray entry in
    # the runner's Temp (a junction it cannot stat) is then a collection error that says nothing
    # about markers.
    p = subprocess.run([sys.executable, "-m", "pytest", "-q",
                        "-c", os.path.join(REPO_ROOT, "pyproject.toml"),
                        "--rootdir", str(tmp_path), str(probe)],
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
    assert re.search(r"takes \*\*[^*]+\*\*", text), "record how long the suite actually takes"
    assert "budget" in text, "and what the budget is"


#: Assertions that compare a clock to a number and are *not* performance budgets: they prove a
#: timeout fires or a kill lands, with a ceiling an order of magnitude above what they need. A
#: loaded machine does not make them wrong, so they do not have to run alone.
NOT_A_BUDGET = {
    # Ceilings on a hang, an order of magnitude above what they need: 30s for a call that should
    # return at once, 60s for a 5s timeout. A loaded machine does not make them wrong.
    ("tests/test_proc.py", "test_a_surviving_grandchild_does_not_hold_the_call_open"),
    ("tests/test_proc.py", "test_a_child_that_never_finishes_is_a_timeout_not_a_hang"),
    # A minute each for a `pip install` of this package and for resolving the clone's objects,
    # both of which take about a second. Same shape -- and a helper rather than a test, which is
    # the reason this scan looks at every function in a test file and not only at `test_*`: a
    # budget moved into a helper would otherwise stop being seen.
    ("tests/test_lifecycle.py", "_assert_pip_can_clone_this"),
    # Not a clock at all: `getComputedTiming().duration` is the duration the stylesheet DECLARED,
    # read back off the animation. A loaded machine cannot change it, and `<= 1` there means "this
    # did not animate" rather than "this was quick".
    ("tests/test_fleet_motion.py",
     "test_the_gestures_animate_for_the_base_duration_and_not_at_all_under_reduced_motion"),
}

#: A budget is an *upper* bound on a clock: `assert <something with a clock in it> <= <ceiling>`.
#: `>= 0` and `> 0` are sanity checks on a measurement, not promises about how long it took, and
#: a comparison with nothing bounding on the right is comparing something else entirely.
#:
#: This is a backstop for the common shape, not a proof. A test that computes its own list of
#: over-budget gestures and asserts the list is empty has no clock and no ceiling on any one line,
#: and no pattern is going to find it -- `test_every_local_gesture_is_inside_the_budget` is exactly
#: that, and carries the marker because its author put it there. What the scan does catch is the
#: shape somebody reaches for without thinking, which is the one that gets forgotten.
CLOCK = re.compile(r"\belapsed\b|\btook\b|\bduration\b|perf_counter|\blatency\b|\bms\b"
                   r"|\bseconds?\b|median_ms")
#: `< 50`, `<= 0.05`, and `< LOCAL_BUDGET_MS` -- a ceiling that was given a name is still a ceiling.
UPPER_BOUND = re.compile(r"<=?\s*(?:[0-9]|[A-Z][A-Z0-9_]{2,}\b)")
#: The other shape a duration takes: a verdict on real timings. `row["verdict"] == "faster"` has no
#: clock and no ceiling on its line, but when the row came out of `bench_node(` it is a judgement on
#: two measured runs, and on a busy runner it judges the contention (#314: 8.3 ms against 1.2 ms
#: judged `same`). The same assertion on rows `compare_bench` read from fixture TSVs, or from TSVs
#: the test wrote itself, measures nothing -- so it counts only in a function that calls `bench_node(`.
VERDICT = re.compile(r"""\[\s*['"]verdict['"]\s*\]\s*[!=]=\s*['"](?:faster|slower|same)['"]"""
                     r"""|['"](?:faster|slower|same)['"]\s*[!=]=\s*\w+\s*\[\s*['"]verdict['"]\s*\]""")


def _calls_bench_node(node) -> bool:
    return any(isinstance(c, ast.Call) and (getattr(c.func, "id", None) == "bench_node"
                                           or getattr(c.func, "attr", None) == "bench_node")
               for c in ast.walk(node))


def _unmarked_durations(rel: str, source: str) -> list[str]:
    """Every function in `source` that asserts a duration and neither carries `measured` nor is
    listed in `NOT_A_BUDGET`, one line each."""
    try:
        tree = ast.parse(source)
    except SyntaxError:                                  # pragma: no cover - a broken test file
        return []
    missing = []
    # Top level, plus one level into a class: a function nested *inside* another is already
    # part of its parent's text, and reporting both would name the same assertion twice.
    top = list(tree.body) + [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body]
    for node in top:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        measures = _calls_bench_node(node)
        timed = []
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assert):
                continue
            text = ast.unparse(stmt)
            if (CLOCK.search(text) and UPPER_BOUND.search(text)) or (measures and VERDICT.search(text)):
                timed.append(text)
        if not timed:
            continue
        if (rel, node.name) in NOT_A_BUDGET:
            continue
        has = "measured" in {m.id if isinstance(m, ast.Name) else getattr(m, "attr", "")
                             for d in node.decorator_list for m in ast.walk(d)}
        if has and node.name.startswith("test_"):
            continue
        how = ("carries `measured`" if node.name.startswith("test_")
               else "is listed in NOT_A_BUDGET -- a helper cannot carry a marker")
        missing.append(f"{rel}::{node.name} ({how}) -> {timed[0][:70]}")
    return missing


def test_every_test_that_asserts_a_duration_carries_the_measured_marker():
    """`measured` is not a taxonomy, it is a scheduling instruction: these tests run with the
    machine to themselves because under `-n` they measure the contention and not the code. One of
    them found that out the hard way -- the 50ms paint budget passes serially and fails on four
    workers, which is the load talking.

    So the marker cannot be a thing somebody remembers. Every assertion that compares a clock to a
    number, or a verdict on real timings, either carries it or is listed in `NOT_A_BUDGET` with a
    reason -- for the common shapes, which are the ones that get forgotten. See the note on
    `CLOCK` for what it cannot see.
    """
    missing = []
    for name in sorted(os.listdir(os.path.join(REPO_ROOT, "tests"))):
        if not name.startswith("test_") or not name.endswith(".py"):
            continue
        rel = f"tests/{name}"
        source = open(os.path.join(REPO_ROOT, "tests", name), encoding="utf-8").read()
        missing += _unmarked_durations(rel, source)
    assert missing == [], (
        "these assert a duration and nothing says they may: each one either "
        f"carries `measured` or is listed in NOT_A_BUDGET with a reason: {missing}")


def _function_source(rel: str, name: str, *, drop_markers: bool) -> str:
    """One function out of a real test file, as source -- optionally with its decorators gone, so
    the scan is tested on the assertion the suite actually carries rather than on a paraphrase."""
    tree = ast.parse(open(os.path.join(REPO_ROOT, *rel.split("/")), encoding="utf-8").read())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    if drop_markers:
        fn.decorator_list = []
    return ast.unparse(fn)


def test_the_scan_sees_a_verdict_on_real_timings_without_the_marker():
    """An unmarked copy of the perf loop's assertion is flagged; the marked original is not."""
    rel, name = "tests/test_perf_loop.py", "test_the_full_loop_on_a_covered_node"
    unmarked = _function_source(rel, name, drop_markers=True)
    assert 'cmp_row["verdict"] == "faster"' in unmarked.replace("'", '"'), "the assertion #314 is about"
    flagged = _unmarked_durations(rel, unmarked)
    assert len(flagged) == 1 and flagged[0].startswith(f"{rel}::{name} (carries `measured`)"), flagged
    assert _unmarked_durations(rel, _function_source(rel, name, drop_markers=False)) == []

    # the smallest shape, each way round and with `!=`, in a helper as well as a test
    for body in ('assert row["verdict"] == "same"', "assert 'slower' == row['verdict']",
                 'assert row["verdict"] != "faster"'):
        src = ("def test_x(root):\n    row = bench_node(root, node='n')['row']\n    " + body + "\n"
               "def _helper(root):\n    row = testing.bench_node(root, node='n')['row']\n    " + body + "\n")
        assert [f.split(" ")[0] for f in _unmarked_durations("tests/test_synthetic.py", src)] == [
            "tests/test_synthetic.py::test_x", "tests/test_synthetic.py::_helper"], body


def test_the_scan_leaves_verdicts_on_files_alone():
    """`compare_bench` on fixture TSVs, or on TSVs a test wrote itself, judges no clock: those
    verdict tests stay in the parallel tier, and the scan must not ask them to move."""
    rel = "tests/test_testing_bench.py"
    for name in ("test_a_real_speedup_is_faster", "test_an_unstable_baseline_has_to_clear_a_higher_bar"):
        src = _function_source(rel, name, drop_markers=True)
        assert re.search(r"\[['\"]verdict['\"]\] == ['\"](faster|same)['\"]", src), name
        assert _unmarked_durations(rel, src) == [], name
    src = ("def test_y(tmp_path):\n    row = compare_bench(_fx('before.tsv'), _fx('after_faster.tsv'))['row']\n"
           "    assert row['verdict'] == 'faster'\n")
    assert _unmarked_durations("tests/test_synthetic.py", src) == []


@pytest.mark.scale
def test_the_expensive_tiers_are_a_small_part_of_the_suite():
    """A tier that holds a third of the suite is not a tier, it is the suite. If these grow, the
    inner loop stops being the thing most changes are tested with -- which is the whole point."""
    def count(expr):
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            "--collect-only", "-m", expr],
                           capture_output=True, text=True, cwd=REPO_ROOT)
        return len([l for l in p.stdout.splitlines() if "::" in l])

    total = count("")
    slow_tiers = count("browser or measured or scale or slow or laptop")
    assert total > 1000, total
    assert slow_tiers < total * 0.10, (
        f"{slow_tiers} of {total} tests are in a tier the inner loop skips; the inner loop is "
        "supposed to be nearly all of it")


def test_parallelism_is_available_and_the_measured_tier_is_kept_out_of_it():
    """The property, not the spelling. An earlier version of this test matched the exact string
    `-m "measured or scale"`, which said nothing about what the command selected and broke the
    moment the expression grew an `and not slow`."""
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    project = open(os.path.join(REPO_ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert "pytest-xdist" in project, "the dev extra has to carry it or `-n` is a typo"

    runs = [ln.strip() for ln in workflow.splitlines() if "-m pytest" in ln]
    parallel = [ln for ln in runs if "-n auto" in ln]
    assert parallel, "CI runs the bulk in parallel"
    for ln in parallel:
        assert "not measured" in ln and "not scale" in ln, (
            f"a parallel pass that does not hold the measured tier out: {ln}")

    serial = [ln for ln in runs if "-n " not in ln and "measured or scale" in ln]
    assert serial, ("no serial pass selects the measured tier -- under `-n` a latency budget "
                    "measures the contention, so it has to run somewhere on its own")


def test_shuffling_is_available_and_wired_into_ci():
    workflow = open(os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    assert "--shuffle-seed" in workflow
    conftest = open(os.path.join(REPO_ROOT, "tests", "conftest.py"), encoding="utf-8").read()
    assert "shuffle-seed" in conftest
