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
    # #602, the `time.time()`/`time.monotonic()` shapes the scan could not see before. A child reading stdin
    # gets EOF at once; 20 s is `proc.run`'s own timeout, so a blocked read fails as a timeout before the
    # clock is read, and the ceiling is two orders of magnitude above a Python start.
    ("tests/test_proc.py", "test_nothing_we_spawn_can_wait_for_a_person"),
    # The listing is held for 20 s; 5 s is a ceiling on a desk answer that parks nothing and takes
    # milliseconds, not a promise about how quick it is.
    ("tests/regressions/test_20260923_any_desk_waits_for_the_process_listing.py",
     "test_a_desk_answer_does_not_wait_for_the_process_listing"),
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
                   r"|\bseconds?\b|median_ms"
                   # the clock read inline: `time.monotonic() - t0 < 0.2`, `time.time() - start < 5` (#602)
                   r"|\b(?:monotonic|time)(?:_ns)?\(\)")
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


def _test_modules() -> list[str]:
    """Every `test_*.py` under `tests/`, `regressions/` and `laptop/` included (#602: the eighth unmarked clock
    was a regression test the top-level listing never opened), fixtures and fakes left out."""
    found = []
    for dirpath, dirs, names in os.walk(os.path.join(REPO_ROOT, "tests")):
        dirs[:] = sorted(d for d in dirs if d not in ("fixtures", "fakes", "__pycache__") and not d.startswith("."))
        found += [os.path.relpath(os.path.join(dirpath, n), REPO_ROOT).replace(os.sep, "/")
                  for n in sorted(names) if n.startswith("test_") and n.endswith(".py")]
    return found


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
    for rel in _test_modules():
        source = open(os.path.join(REPO_ROOT, *rel.split("/")), encoding="utf-8").read()
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


def test_the_scan_sees_a_clock_read_inline():
    """#602: `time.monotonic() - t0 < 0.2` and `time.time() - start < 5` name no `elapsed` and no `took`, and
    the scan passed them by until a Windows runner took 0.735 s against a 0.2 s bound (#590). A poll's deadline
    and a floor on a wait are not budgets, and stay unflagged."""
    def flagged(body):
        src = f"import time\ndef test_x():\n    t0 = start = time.monotonic()\n    {body}\n"
        return [f.split(" ")[0] for f in _unmarked_durations("tests/test_synthetic.py", src)]

    for body in ("assert time.monotonic() - t0 < 0.2", "assert time.time() - start < 5, 'reading stdin blocked'",
                 "assert monotonic() - t0 <= LIMIT_S", "assert time.monotonic_ns() - t0 < 10 ** 9",
                 "assert (time.time() - start) < 30 and ok"):
        assert flagged(body) == ["tests/test_synthetic.py::test_x"], body
    for body in ("assert time.monotonic() < deadline, 'the row never came to rest'",
                 "assert time.monotonic() - t0 >= 0.25", "assert before <= time.time() <= after"):
        assert flagged(body) == [], body


#: What reaches a browser: Playwright itself, or the desk's harness (`tests/test_fleet_desk_browser.py`, whose
#: `launch_chromium` every desk test starts from).
BROWSER_DRIVERS = ("playwright", "test_fleet_desk_browser")
#: The calls that start one.
BROWSER_STARTS = {"sync_playwright", "async_playwright", "launch_chromium"}


def _reaches_a_browser(tree) -> bool:
    """The module imports Playwright or the harness, or `pytest.importorskip`s Playwright."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in BROWSER_DRIVERS for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in BROWSER_DRIVERS:
            return True
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "importorskip" and node.args
                and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith("playwright")):
            return True
    return False


def _names_browser(node) -> bool:
    return any(isinstance(m, ast.Attribute) and m.attr == "browser" for m in ast.walk(node))


def _unmarked_browser_tests(rel: str, source: str) -> list[str]:
    """In a module that reaches a browser: the module itself when nothing in it carries `browser`, and every test
    that starts Chromium -- itself, or through a function or fixture of the same module -- without the marker."""
    tree = ast.parse(source)
    if not _reaches_a_browser(tree):
        return []
    module = any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in n.targets)
                 and _names_browser(n.value) for n in tree.body)
    fns = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    starts: set[str] = set()
    grew = True
    while grew:                                  # a fixture that yields a browser starts one for whoever asks
        grew = False
        for name, fn in fns.items():
            used = ({n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
                    | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
                    | {a.arg for a in fn.args.args})
            if name not in starts and used & (BROWSER_STARTS | starts):
                starts.add(name)
                grew = True
    missing = [f"{rel}::{name}" for name, fn in fns.items() if name.startswith("test_") and name in starts
               and not module and not any(_names_browser(d) for d in fn.decorator_list)]
    anywhere = module or any(_names_browser(d) for n in ast.walk(tree)
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                             for d in n.decorator_list)
    return missing if anywhere else [f"{rel} (the module)"] + missing


def test_every_test_that_drives_a_browser_carries_the_browser_marker():
    """#602: `test_fleet_loads_page.py` drove Chromium unmarked, so it ran in the default tier, got none of the
    page diagnostics a `browser` test gets when a wait runs out, and escaped the browser shards and their budgets.
    Any module that imports Playwright or the desk harness carries the marker, and so does each of its tests that
    starts Chromium, directly or through the module's own fixtures and helpers."""
    missing = []
    for rel in _test_modules():
        missing += _unmarked_browser_tests(rel, open(os.path.join(REPO_ROOT, *rel.split("/")), encoding="utf-8").read())
    assert missing == [], f"these drive a browser without the `browser` marker: {missing}"


def test_the_browser_check_sees_a_module_and_a_fixture_without_the_marker():
    # The pre-harness fixture below is a synthetic source, not a driver: its calls are built by
    # concatenation so tests/test_hygiene_harness.py's scan (#303) does not read them as one.
    fixture = ("import pytest\nfrom test_fleet_desk_browser import launch_chromium\n"
               "@pytest.fixture(scope='module')\ndef browser():\n"
               "    with pytest.importorskip('playwright.sync_api').sync_" + "playwright() as p:\n"
               "        yield launch_" + "chromium(p)\n"
               "def test_markup():\n    assert True\n"
               "{mark}def test_page(browser):\n    browser.new_page()\n")
    rel = "tests/test_synthetic.py"
    assert _unmarked_browser_tests(rel, fixture.format(mark="")) == [f"{rel} (the module)", f"{rel}::test_page"]
    assert _unmarked_browser_tests(rel, fixture.format(mark="@pytest.mark.browser\n")) == []
    direct = ("import pytest\n@pytest.mark.browser\ndef test_a():\n"
              "    sp = pytest.importorskip('playwright.sync_api').sync_playwright\n"
              "def test_b():\n    sp = pytest.importorskip('playwright.sync_api').sync_playwright\n    sp()\n")
    assert _unmarked_browser_tests(rel, direct) == [f"{rel}::test_b"]
    assert _unmarked_browser_tests(rel, "import pytest\npytestmark = pytest.mark.browser\n" + direct) == []
    assert _unmarked_browser_tests(rel, "def test_c():\n    assert 'playwright' in 'a string'\n") == []


# ------------------------------------------------------------------ the browser tier's time budget
#
# Decision 20 (P-2, #587) turned decision 13's "no new browser test function" into a time budget.
# The budget is the browser tier's summed test time in `tests/durations.json`, measured on green
# run 36330617129 @ a8549e1, the 3.14-only job set (356 browser ids, the same 356 `main` collects
# there), plus 5%, rounded down to the second. Why 5%: on that run the slowest Windows shard's
# `pytest` step took 12.1 of its job's 20 minutes, its browser tests 7.8 of those; the two Linux
# browser shards took 6.3 and 6.8 of their step's 15. 5% is about 70 s of test time on each OS
# (about 17 browser tests at the tier's mean), spread over the shards, which absorb it without
# nearing a cap. Raising a number here is the operator's call, never a card's
# (docs/testing-this-repo.md, *The browser tier's time budget*).
BROWSER_MEASURED_S = {"linux": 1538.4, "windows": 1378.3}
BROWSER_HEADROOM = 0.05
BROWSER_BUDGET_S = {"linux": 1615, "windows": 1447}
DURATIONS = os.path.join(REPO_ROOT, "tests", "durations.json")
BROWSER_COUNTS = os.path.join(REPO_ROOT, "tests", "browser_counts.json")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _browser_seconds(files: dict) -> dict[str, float]:
    """{file: seconds} over every tier that carries `browser`, from one OS of `durations.json`."""
    return {f: sum(s for t, s in tiers.items() if "browser" in t.split("+"))
            for f, tiers in files.items() if any("browser" in t.split("+") for t in tiers)}


def projected_browser_seconds(files: dict, counts_then: dict, counts_now: dict) -> tuple[float, dict]:
    """The browser tier's time with today's tests, costed from the measured run.

    A file measured with n tests costs its measured time per test times the tests it has now; a
    file with no measured browser test costs the tier's mean per test. Returns (seconds, {file: s})."""
    measured = _browser_seconds(files)
    mean = sum(measured.values()) / max(1, sum(counts_then.values()))
    per_file = {}
    for f, n in counts_now.items():
        then = counts_then.get(f, 0)
        per_file[f] = measured.get(f, 0.0) / then * n if then else mean * n
    return sum(per_file.values()), per_file


def browser_budget_findings(durations: dict, counts_then: dict, counts_now: dict,
                            budget: dict) -> list[str]:
    """One line per OS whose projected browser time is over its budget, naming the files that grew."""
    out = []
    for os_key, cap in sorted(budget.items()):
        total, per_file = projected_browser_seconds(durations[os_key], counts_then, counts_now)
        if total > cap:
            grew = sorted(f for f, n in counts_now.items() if n > counts_then.get(f, 0))
            out.append(f"{os_key}: the browser tier would take {total:.1f} s against its budget of "
                       f"{cap} s; grown since the measured run: {', '.join(grew) or 'none'}")
    return out


def _collected_per_file(lines) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in lines:
        if "::" in line:
            f = line.split("::")[0].strip().replace("\\", "/")
            counts[f] = counts.get(f, 0) + 1
    return counts


def test_the_browser_budget_is_the_measured_time_plus_a_small_headroom():
    """The budget is never looser than the measured tier plus 5%, and today's durations fit it."""
    durations, counts = _load(DURATIONS), _load(BROWSER_COUNTS)
    for os_key, measured in BROWSER_MEASURED_S.items():
        assert BROWSER_BUDGET_S[os_key] == int(measured * (1 + BROWSER_HEADROOM)), os_key
        now = round(sum(_browser_seconds(durations[os_key]).values()), 1)
        assert now <= BROWSER_BUDGET_S[os_key], (
            f"{os_key}: tests/durations.json has the browser tier at {now} s, over its budget of "
            f"{BROWSER_BUDGET_S[os_key]} s. A refresh that grows past the budget is a finding for the "
            "operator, not a number to raise")
        total, _ = projected_browser_seconds(durations[os_key], counts, counts)
        assert abs(total - now) < 0.5, "the counts are not from the run the durations came from"
    assert set(counts) == set(_browser_seconds(durations["linux"])), (
        "tests/browser_counts.json and tests/durations.json name different browser files: refresh both "
        "from the same run")


def test_a_new_browser_function_within_the_budget_passes_and_one_over_it_fails():
    # the rule, on a two-file suite: a.py measured 10 s for 2 tests, b.py 2 s for 1 test (mean 4 s)
    durations = {"linux": {"tests/a.py": {"browser": 8.0, "browser+measured": 2.0},
                           "tests/b.py": {"browser": 2.0}, "tests/c.py": {"default": 50.0}}}
    then = {"tests/a.py": 2, "tests/b.py": 1}
    assert browser_budget_findings(durations, then, then, {"linux": 12}) == []
    assert browser_budget_findings(durations, then, {**then, "tests/a.py": 3}, {"linux": 17}) == []
    over = browser_budget_findings(durations, then, {**then, "tests/a.py": 3}, {"linux": 16})
    assert over == ["linux: the browser tier would take 17.0 s against its budget of 16 s; "
                    "grown since the measured run: tests/a.py"], over
    assert browser_budget_findings(durations, then, {**then, "tests/new.py": 1}, {"linux": 16}) == []
    assert browser_budget_findings(durations, then, {**then, "tests/new.py": 2}, {"linux": 19})[0] \
        .endswith("tests/new.py")
    # removing a browser test gives its time back
    assert browser_budget_findings(durations, then, {"tests/a.py": 1, "tests/b.py": 1, "tests/new.py": 1},
                                   {"linux": 11}) == []

    # the same on the real suite: a new file of browser tests at the tier's mean, one test past the
    # room left, fails on that OS; one test fewer fits
    real, counts = _load(DURATIONS), _load(BROWSER_COUNTS)
    for os_key, cap in BROWSER_BUDGET_S.items():
        total, _ = projected_browser_seconds(real[os_key], counts, counts)
        mean = total / sum(counts.values())
        fits = int((cap - total) // mean)
        assert fits >= 1, f"{os_key}: the budget leaves no room for one browser test at the mean"
        ok = browser_budget_findings(real, counts, {**counts, "tests/test_new.py": fits}, {os_key: cap})
        assert ok == [], ok
        over = browser_budget_findings(real, counts, {**counts, "tests/test_new.py": fits + 1}, {os_key: cap})
        assert len(over) == 1 and over[0].startswith(f"{os_key}: ") and "tests/test_new.py" in over[0], over


def test_the_collected_browser_tests_are_counted_per_file():
    lines = ["tests/test_a.py::test_one", "tests/test_a.py::test_two[x]", "tests\\test_b.py::test_z", "",
             "3/40 tests collected (37 deselected) in 1.0s"]
    assert _collected_per_file(lines) == {"tests/test_a.py": 2, "tests/test_b.py": 1}


@pytest.mark.scale
def test_the_expensive_tiers_are_a_small_part_of_the_suite():
    """A tier that holds a third of the suite is not a tier, it is the suite. If these grow, the
    inner loop stops being the thing most changes are tested with -- which is the whole point.

    Folded in (decision 13), since it needs the same whole-suite collections: `--shard=K/3` (#310)
    splits a shuffled selection, with and without `-m`, into whole-file shards whose node ids are
    disjoint, add up to exactly the selection and keep its shuffled order. And every combination of
    tier markers the suite holds is one tests/tier_matrix.py renders (#315): its plugin rides the
    slow-tiers collection, which holds every test that carries a tier marker. And the collected browser tier
    fits its time budget (decision 20, #587)."""
    tests_dir = os.path.join(REPO_ROOT, "tests")

    def collect(*args):
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(
            p for p in (tests_dir, os.environ.get("PYTHONPATH", "")) if p)}
        return subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                 "--collect-only", *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT, env=env)

    def lines(proc):
        out, err = proc.communicate(timeout=600)
        assert proc.returncode == 0, err or out
        return out.splitlines()

    inner = "not browser and not slow and not measured and not scale"
    shuffled = ("--shuffle-seed", "1")
    procs = {("", 0): collect("-m", "", *shuffled),
             ("slow tiers", 0): collect("-m", "browser or measured or scale or slow or laptop", "-p", "tier_matrix"),
             (inner, 0): collect("-m", inner, *shuffled),
             ("browser", 0): collect("-m", "browser")}
    for k in (1, 2, 3):  # all at once: eight collections one after another cost minutes
        procs[("", k)] = collect("-m", "", *shuffled, f"--shard={k}/3")
        procs[(inner, k)] = collect("-m", inner, *shuffled, f"--shard={k}/3")
    out = {key: lines(p) for key, p in procs.items()}
    ids = {key: [ln for ln in o if "::" in ln] for key, o in out.items()}

    total = len(ids[("", 0)])
    slow_tiers = len(ids[("slow tiers", 0)])
    assert total > 1000, total
    assert slow_tiers < total * 0.10, (
        f"{slow_tiers} of {total} tests are in a tier the inner loop skips; the inner loop is "
        "supposed to be nearly all of it")

    import tier_matrix
    found = {ln.split(": ", 1)[1] for ln in out[("slow tiers", 0)] if ln.startswith("tier-matrix-combination: ")}
    assert found, "tests/tier_matrix.py's plugin printed no combination"
    missing = found - {tier_matrix.label(c) for c in tier_matrix.COMBINATIONS}
    assert not missing, (f"tests carry {sorted(missing)}, which tests/tier_matrix.py's COMBINATIONS lacks: "
                         f"add them and run `{tier_matrix.REFRESH}`")

    for expr in ("", inner):
        whole = ids[(expr, 0)]
        shards = [ids[(expr, k)] for k in (1, 2, 3)]
        assert all(shards), f"-m {expr!r}: an empty shard"
        assert sum(len(s) for s in shards) == len(whole) == len(set().union(*shards)), f"-m {expr!r}"
        assert set().union(*shards) == set(whole), f"-m {expr!r}: the shards do not add up to the selection"
        files = [{i.split("::")[0] for i in s} for s in shards]
        assert not (files[0] & files[1] or files[0] & files[2] or files[1] & files[2]), "a file was split"
        for k, s in enumerate(shards, 1):
            mine = set(s)
            assert s == [i for i in whole if i in mine], f"-m {expr!r} shard {k}/3 lost the shuffled order"
            assert any(ln.startswith(f"shard {k}/3: {len(files[k - 1])} files, {len(s)} tests, ~")
                       for ln in out[(expr, k)]), out[(expr, k)][:3]

    # Decision 20 (P-2): new browser tests are allowed while the tier stays inside its time budget.
    # Folded in here, not a test of its own: its collection runs beside the others, and a new `scale`
    # id would grow the tier this test caps.
    browser = _collected_per_file(ids[("browser", 0)])
    over = browser_budget_findings(_load(DURATIONS), _load(BROWSER_COUNTS), browser, BROWSER_BUDGET_S)
    assert over == [], over


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
