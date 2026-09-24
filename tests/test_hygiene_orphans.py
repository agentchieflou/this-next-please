"""The suite's own guard against a child process that outlives its test (#317, tests/orphans.py).

Each test here runs an inner pytest session (a subprocess through `agentdata.proc.run`) whose only
test starts a sleeping `python` from a test-local helper. When that test does not clean up, the
inner session must name the sleeper and exit non-zero, serially and under `-n 2`, where the sleeper
is a child of a worker and only the worker can see it. When it does clean up, `-n 2` exits 0: the
guard never reports a worker, which is what the controller's own children are.
"""
from __future__ import annotations
import os
import re
import sys
import time

import pytest

from agentdata import proc
from agentdata.fleet.supervisor import pid_alive

HERE = os.path.dirname(os.path.abspath(__file__))

CONFTEST = f"""\
import sys
sys.path.insert(0, {HERE!r})
pytest_plugins = ["orphans"]
"""

#: The sleeper says `ready` once it runs its own code, and `start_a_sleeper` reads that line before
#: it returns. `Popen` returns while the child can still be inside `execve`: the kernel releases a
#: vfork parent before it swaps the child's memory, and sets the new argv after the swap. So a read of
#: the child's command line straight after `Popen` sees its parent's (under xdist, execnet's bootstrap
#: `python -u -c import sys;exec(eval(sys.stdin.readline()))`) or nothing. This inner test ends at
#: once, so the guard read it in that window on a loaded runner (ubuntu 3.14 on #455), and named the
#: right pid with the worker's command line.
TEST = """\
import subprocess
import sys


def start_a_sleeper():
    child = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(300)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    with open({pidfile!r}, "w") as f:
        f.write(str(child.pid))
    assert child.stdout.readline().strip() == "ready"
    return child


def test_starts_a_sleeper():
    child = start_a_sleeper()
    if {clean}:
        child.kill()
        child.wait(timeout=30)
"""


def _inner(tmp_path, *, clean: bool, workers: int | None):
    """Run the inner session; return (exit code, output, the sleeper's pid)."""
    pidfile = str(tmp_path / "sleeper.pid")
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(TEST.format(pidfile=pidfile, clean=clean), encoding="utf-8")
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_inner.py"]
    if workers:
        argv += ["-n", str(workers)]
    try:
        code, out, err, _ = proc.run(argv, cwd=str(tmp_path), timeout=180)
    finally:
        pid = int(open(pidfile).read()) if os.path.exists(pidfile) else None
    return code, out + err, pid


def _end(pid):
    """Kill the sleeper this test provoked, and wait until it is gone. It is no child of ours (its
    parent, the inner session, has exited), so there is nothing to `wait` on: poll, bounded."""
    if not pid:
        return
    proc.kill_tree(pid)
    deadline = time.time() + 30
    while pid_alive(pid) and time.time() < deadline:
        time.sleep(0.1)
    assert not pid_alive(pid), f"the sleeper {pid} survived its kill"


@pytest.mark.parametrize("workers", [None, 2], ids=["serial", "n2"])
def test_a_test_that_leaves_a_child_fails_its_session_and_names_it(tmp_path, workers):
    code, output, pid = None, "", None
    try:
        code, output, pid = _inner(tmp_path, clean=False, workers=workers)
    finally:
        _end(pid)
    assert pid, output
    assert code != 0, output
    assert "outlived the tests that started them" in output, output
    assert re.search(rf"pid {pid}\s+python", output), output
    assert "time.sleep(300)" in output, output                       # the command line
    if workers:
        assert re.search(r"child process\(es\) of gw\d", output), output   # the worker, not the controller


def test_a_test_that_cleans_up_passes_under_xdist(tmp_path):
    code, output, pid = None, "", None
    try:
        code, output, pid = _inner(tmp_path, clean=True, workers=2)
    finally:
        _end(pid)
    assert code == 0, output
    assert "outlived" not in output, output


def test_the_guard_lists_a_live_child_and_not_a_reaped_one():
    """`children()` itself: a live `python` child is listed with its command line; once it has been
    killed and waited on, it is not."""
    import subprocess

    import orphans

    # `ready` first, as in TEST: read straight after `Popen`, the child can still be inside `execve`
    # and show its parent's command line (ubuntu 3.14 on main, e93cbf2; #459)
    child = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(300)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        rows = {r["pid"]: r for r in orphans.orphans()}
        assert child.pid in rows, orphans.children()
        assert "time.sleep(300)" in rows[child.pid]["cmdline"]
    finally:
        child.kill()
        child.wait(timeout=30)
        child.stdout.close()
    assert child.pid not in {r["pid"] for r in orphans.children()}
