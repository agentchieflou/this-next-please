"""2026-09-08, Windows CI (python 3.12 and 3.14): `ad-jira cache --clear` could not delete a corrupt cache.

Symptom, from the `windows · python 3.12` job:

    FAILED tests/test_jira_cache.py::test_clearing_a_corrupt_cache_is_how_a_human_recovers -
    agentdata.jira_cache.CacheError: could not delete the changelog cache: [WinError 32] The process
    cannot access the file because it is being used by another process:
    '.../out/.jira-changelog-cache/changelog.sqlite3'

`_db()` opened the connection and only then ran the schema. `sqlite3.connect()` on a corrupt file
succeeds -- it is the first statement that raises -- so the failure left an open handle on a
connection the method had not yet stored in `self._conn`. `_disable()` closes `self._conn`, which was
still `None`, so nothing was closed.

POSIX unlinks a file out from under an open handle without complaint, so the leak was invisible on
every Linux run and on every developer machine. Windows refuses, which meant the one recovery this
module's own hint tells a human to run -- `ad-jira cache --clear` -- failed on precisely the corrupt
file it exists to remove, and the operator was told to "close whatever is holding it open" when the
thing holding it open was us.

Issue: https://github.com/agentchieflou/this-next-please/issues/125
"""
from __future__ import annotations
import os
import sys

import pytest

from agentdata.jira_cache import ChangelogCache


def _corrupt(out_dir: str) -> str:
    """A file that is not a database, where the cache expects one."""
    cache_dir = os.path.join(out_dir, ".jira-changelog-cache")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "changelog.sqlite3")
    with open(path, "w", encoding="utf-8") as f:
        f.write("this is not a database, it is a text file someone restored over one\n")
    return path


def test_a_corrupt_cache_leaves_no_open_handle(tmp_path):
    """The platform-independent half: after the cache disables itself, nothing of ours holds the file.

    Asserted through `/proc/self/fd` because that is the only portable-enough way to see a leaked
    handle from inside the process -- and Linux is where this suite runs, which is exactly why the
    bug survived. The Windows half is `test_clearing_a_corrupt_cache_is_how_a_human_recovers` in
    `tests/test_jira_cache.py`, which is what actually went red on the runner.
    """
    if not sys.platform.startswith("linux"):
        pytest.skip("reads /proc/self/fd; the Windows behaviour is covered by the clear() test")

    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    path = _corrupt(out)

    cache = ChangelogCache.open(out)
    assert cache.disabled, "a file that is not a database must disable the cache"

    fd_dir = "/proc/self/fd"
    held = []
    for fd in os.listdir(fd_dir):
        try:
            target = os.readlink(os.path.join(fd_dir, fd))
        except OSError:
            continue
        if os.path.realpath(target) == os.path.realpath(path):
            held.append(fd)

    assert not held, (
        f"{len(held)} open handle(s) on the corrupt cache after it disabled itself. On Windows this "
        "is WinError 32 and `ad-jira cache --clear` cannot delete the file it is meant to remove."
    )


def test_clear_removes_a_corrupt_cache_and_the_next_run_recreates_it(tmp_path):
    """The behaviour the operator depends on, on every platform: clear, then keep working."""
    out = str(tmp_path / "out")
    os.makedirs(out, exist_ok=True)
    _corrupt(out)

    cache = ChangelogCache.open(out)
    assert cache.disabled
    cache.clear()                                   # this raised CacheError on Windows
    assert not os.path.exists(cache.path)
    assert not cache.disabled, "a cleared cache is usable again, not dead"

    cache.begin_issue("RDSD-1", "10001", "2026-09-08T09:00:00Z")
    cache.finish_issue("RDSD-1")
    assert cache.partition({"RDSD-1": "2026-09-08T09:00:00Z"}) == (["RDSD-1"], [])
    cache.close()
