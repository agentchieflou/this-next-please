"""The one quiescence helper stays the one (#304): `tests/desk_waits.py`.

Every idle and render-contract test waits for the desk through `desk_waits.settle` and says it wrote
nothing through `assert_idle` / `observe_quiet`, and every observer a test puts on a page is the
helper's (`record_mutations`, or `WATCH` inside page code). These scans keep a hand-written observer
or a second ceiling from coming back. What the helper does in a page is checked where the idle
tests already run (decision 13: no new browser test functions): `test_fleet_ink`'s idle desk
(`test_an_idle_desk_with_ink_on_the_paper_writes_nothing_and_draws_nothing`), its reduced-motion
chalk test, the skinned-desk regression and the trace's still ground.
"""
from __future__ import annotations

import os
import subprocess
import sys

import desk_waits as DW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
#: Built by concatenation, so this file is not a hit of its own scan.
NEEDLE = "new " + "Mutation" + "Observer"


def _hits(needle: str, root: str) -> list[str]:
    """Every `.py` file under `root` that holds `needle`, relative to `root`, sorted."""
    out = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    if needle in f.read():
                        out.append(os.path.relpath(path, root).replace(os.sep, "/"))
    return sorted(out)


def test_the_only_mutation_observer_under_tests_is_the_helpers():
    assert _hits(NEEDLE, TESTS) == ["desk_waits.py"], (
        "an observer written by hand: use desk_waits.record_mutations, or WATCH inside page code")


def test_the_scan_finds_an_observer_written_by_hand(tmp_path):
    (tmp_path / "desk_waits.py").write_text(f"X = '{NEEDLE}(f)'\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "test_x.py").write_text(f"JS = '''{NEEDLE}(rs => n += rs.length)'''\n",
                                                encoding="utf-8")
    (tmp_path / "test_y.py").write_text("JS = '__deskWaits.watch(document.body)'\n", encoding="utf-8")
    assert _hits(NEEDLE, str(tmp_path)) == ["desk_waits.py", "sub/test_x.py"]


def test_ci_never_scales_the_desk_wait():
    """`AGENTDATA_DESK_WAIT_SCALE` is for a local throttled run; a CI job that set it would be a
    second ceiling by another name."""
    workflows = os.path.join(ROOT, ".github", "workflows")
    named = [n for n in sorted(os.listdir(workflows))
             if "AGENTDATA_DESK_WAIT_SCALE" in open(os.path.join(workflows, n), encoding="utf-8").read()]
    assert named == [], named


def test_the_ceiling_is_thirty_seconds_scaled_only_by_its_variable():
    env = dict(os.environ, PYTHONPATH=TESTS)
    env.pop("AGENTDATA_DESK_WAIT_SCALE", None)
    read = [sys.executable, "-c", "import desk_waits; print(desk_waits.DESK_WAIT_MS)"]
    assert subprocess.run(read, env=env, capture_output=True, text=True, check=True).stdout.strip() == "30000.0"
    env["AGENTDATA_DESK_WAIT_SCALE"] = "2.5"
    assert subprocess.run(read, env=env, capture_output=True, text=True, check=True).stdout.strip() == "75000.0"


def test_every_desk_page_counts_what_settle_reads():
    """`desk_harness.desk_page` (and so `new_desk_page` and every `_open` built on it) installs the
    fetch counter and `COUNT_TIMERS`, which carries the refresh counter and the page side."""
    import desk_harness as H

    installed = []

    class Page:
        def add_init_script(self, script):
            installed.append(script)

    class Context:
        def new_page(self):
            return Page()

    class Browser:
        def new_context(self, **kw):
            return Context()

    H.desk_page(Browser(), init_scripts=("window.__mine = 1;",))
    assert installed == [H.COUNT_FETCHES, DW.COUNT_TIMERS, "window.__mine = 1;"]
    assert DW.COUNT_REFRESHES in DW.COUNT_TIMERS and DW.WATCH in DW.COUNT_TIMERS
    assert NEEDLE in DW.WATCH and NEEDLE not in DW.COUNT_TIMERS.replace(DW.WATCH, "")

