"""Node ids for tests/test_stress_one.py to stress (#307). `tests/fixtures` is in `norecursedirs`,
so the suite never collects these; `stress_one.py` names them one at a time."""
import os
import subprocess
import sys
import time


def test_passes():
    pass


def test_fails():
    assert False, "a copy that fails"


def test_sleeps_past_the_timeout():
    """Starts a grandchild, writes both pids to `$STRESS_ONE_PIDS`, and sleeps: a timeout has to
    take the whole tree."""
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["STRESS_ONE_PIDS"], "a", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {grandchild.pid}\n")
    time.sleep(120)
