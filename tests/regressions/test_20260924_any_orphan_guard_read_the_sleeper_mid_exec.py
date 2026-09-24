"""2026-09-24, ubuntu-latest · python 3.14 on PR #455 (bc934db): the orphan guard's own test named the
right pid with the xdist worker's command line, not the sleeper's.

Symptom (`tests/test_hygiene_orphans.py::test_a_test_that_leaves_a_child_fails_its_session_and_names_it[n2]`):

    1 child process(es) of gw0 (pid 22490) outlived the tests that started them (#317). ...
      pid 22512  python  /opt/hostedtoolcache/Python/3.14.7/x64/bin/python -u -c import sys;exec(eval(sys.stdin.readline()))
    >       assert "time.sleep(300)" in output, output

Pid 22512 was the sleeper. `Popen` returns while the child can still be inside `execve`. The kernel
releases a vfork parent before it swaps in the child's new memory, and it writes the new argv after
the swap. Until then, `/proc/<pid>/cmdline` gives the parent's command line (under xdist, execnet's
bootstrap) or nothing. On this machine, reading straight after `Popen` came back empty 177 to 264
times out of 300 (Python 3.11 and 3.14, idle and loaded). The inner test ended at once, and on a
loaded runner the session-end guard read the sleeper inside that window. The guard named the right
process. The harness was at fault: it returned a sleeper that was not yet running as itself. It now
waits for the sleeper to say `ready` before it returns.

Here the window is made wide on purpose. `Popen` is swapped for one that starts a stand-in, which
waits half a second and then `execv`s the real sleeper, keeping its pid and its pipes. That is the
same state a slow `execve` leaves: the pid is live and its command line is not the sleeper's yet.
`start_a_sleeper` has to return a sleeper that already shows its own command line to
`orphans.children()`, which is what the guard reads.

Issue: https://github.com/agentchieflou/this-next-please/issues/459
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types

import orphans
import test_hygiene_orphans as H

#: How long the stand-in holds the pid before it becomes the sleeper: far longer than any read.
EXEC_DELAY_S = 0.5

STAND_IN = ("import json, os, sys, time; time.sleep(float(os.environ['EXEC_DELAY_S'])); "
            "argv = json.loads(os.environ['EXEC_ARGV']); os.execv(argv[0], argv)")


def slow_exec_popen(argv, **kwargs):
    """`subprocess.Popen`, except that the process becomes `argv` only after `EXEC_DELAY_S`."""
    env = dict(kwargs.pop("env", None) or os.environ)
    env["EXEC_DELAY_S"] = str(EXEC_DELAY_S)
    env["EXEC_ARGV"] = json.dumps(list(argv))
    return subprocess.Popen([sys.executable, "-c", STAND_IN], env=env, **kwargs)


def test_start_a_sleeper_returns_a_sleeper_already_running_as_itself(tmp_path):
    scope: dict = {}
    exec(H.TEST.format(pidfile=str(tmp_path / "sleeper.pid"), clean=True), scope)
    if sys.platform != "win32":
        # Windows has no such window to widen: `CreateProcess` sets the command line as it creates
        # the process, and `os.execv` there starts a new pid rather than becoming the program.
        scope["subprocess"] = types.SimpleNamespace(Popen=slow_exec_popen, PIPE=subprocess.PIPE,
                                                    DEVNULL=subprocess.DEVNULL)
    child = scope["start_a_sleeper"]()
    try:
        row = {r["pid"]: r for r in orphans.children()}.get(child.pid)
    finally:
        child.kill()
        child.wait(timeout=30)
        if child.stdout:
            child.stdout.close()
    assert row, (child.pid, orphans.children())
    assert "time.sleep(300)" in row["cmdline"], (
        "start_a_sleeper returned before its sleeper ran as itself, so the guard would name it by "
        "another command line", row)
