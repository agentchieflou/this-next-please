""".github/scripts/stress_one.py (#307): many copies of one test at once, as a TOON table and an
exit code. Driven with the node ids in tests/fixtures/stress_one/target.py; not a browser test."""
from __future__ import annotations
import importlib.util
import os
import sys

import pytest

from agentdata import toon

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, ".github", "scripts", "stress_one.py")
TARGET = "tests/fixtures/stress_one/target.py"


@pytest.fixture(scope="module")
def stress_one():
    spec = importlib.util.spec_from_file_location("stress_one_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _running(pid: int) -> bool:
    """Whether `pid` is a process that has not exited (a zombie has)."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    if os.path.isdir("/proc"):
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_every_copy_is_a_row_and_the_exit_code_says_whether_all_passed(stress_one, capsys):
    """Two copies over two rounds of a passing node: four `passed` rows and exit 0. One copy of a
    failing node: a `failed` row and exit 1."""
    assert stress_one.main([f"{TARGET}::test_passes", "--copies", "2", "--rounds", "2",
                            "--timeout", "120"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "copies[4]{round,copy,outcome,seconds}:", out
    rows = [[toon.read_cell(c) for c in line.strip().split(",")] for line in out.splitlines()[1:]]
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("1", "1", "passed"), ("1", "2", "passed"), ("2", "1", "passed"), ("2", "2", "passed")], out
    assert all(float(r[3]) > 0 for r in rows), out

    assert stress_one.main([f"{TARGET}::test_fails", "--copies", "1", "--rounds", "1",
                            "--timeout", "120"]) == 1
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 2 and out.splitlines()[0].startswith("copies[1]"), out
    assert out.splitlines()[1].strip().split(",")[:3] == ["1", "1", "failed"], out


def test_a_copy_that_runs_out_of_time_is_a_timeout_row_and_leaves_no_process(stress_one, tmp_path,
                                                                             monkeypatch, capsys):
    """A node that sleeps past a 2 s `--timeout`: `timeout` rows, exit 1, and the copy's whole tree
    gone -- the pytest copy and the grandchild it started (`agentdata.proc.run` kills the tree)."""
    pids = tmp_path / "pids.txt"
    pids.write_text("", encoding="utf-8")
    monkeypatch.setenv("STRESS_ONE_PIDS", str(pids))
    assert stress_one.main([f"{TARGET}::test_sleeps_past_the_timeout", "--copies", "2", "--rounds", "1",
                            "--timeout", "2"]) == 1
    out = capsys.readouterr().out
    assert [line.strip().split(",")[2] for line in out.splitlines()[1:]] == ["timeout", "timeout"], out
    left = [int(p) for line in pids.read_text(encoding="utf-8").splitlines() for p in line.split()]
    assert [p for p in left if _running(p)] == [], (left, out)


def test_the_script_refuses_what_it_cannot_run(stress_one):
    for bad in (["--copies", "0"], ["--rounds", "0"], ["--timeout", "0"], ["--throttle", "0.5"]):
        with pytest.raises(SystemExit) as caught:
            stress_one.main([f"{TARGET}::test_passes", *bad])
        assert caught.value.code == 2, bad


def test_each_copy_is_a_pytest_of_the_node_under_the_throttle_by_way_of_proc_run(stress_one, monkeypatch):
    """The copies go through `agentdata.proc.run` (its own session, the tree killed on a timeout),
    from the repository root, with the throttle on the command line."""
    calls = []

    def run(argv, *, timeout, cwd):
        calls.append((argv, timeout, cwd))
        return 0, "", "", 0.1

    monkeypatch.setattr(stress_one.proc, "run", run)
    rows = stress_one.stress("tests/test_x.py::test_y", copies=3, rounds=1, throttle=4, timeout=30)
    assert [r[:3] for r in rows] == [[1, 1, "passed"], [1, 2, "passed"], [1, 3, "passed"]]
    assert calls == [([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "tests/test_x.py::test_y", "--desk-cpu-throttle=4"], 30, REPO_ROOT)] * 3
