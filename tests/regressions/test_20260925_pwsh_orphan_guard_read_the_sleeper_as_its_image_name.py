"""2026-09-25, windows · python 3.12 on train 7 (#518 @ a3149ba, job 108229044605), and again on train
8b (#528 @ 2f7ef0d): the orphan guard read a live sleeper's command line as its bare image name.

Symptom (`tests/regressions/test_20260924_any_orphan_guard_read_the_sleeper_mid_exec.py:70`):

    E  AssertionError: ('start_a_sleeper returned before its sleeper ran as itself, ...',
                        {'pid': 1688, 'name': 'python.exe', 'cmdline': 'python.exe'})
    E  assert 'time.sleep(300)' in 'python.exe'

The sleeper had already printed `ready`, so it was running as itself: this is not #459's exec window.
On Windows the toolhelp snapshot names only the image, and the command line came from one CIM query
per child, a `powershell Get-CimInstance` that swallowed every failure (a timeout, a WMI error on
stderr, an empty answer) and handed back `""`. The guard then fell back to the image name. The fix
asks the process first (`NtQueryInformationProcess(ProcessCommandLineInformation)`, no second
process, no WMI), keeps CIM second, and records which reader answered, or why none did.

These tests run the Windows branch of `orphans.children()` on any OS. The snapshot is emulated from
the real children (image name only, as toolhelp gives), CIM answers nothing, and the native reader
is emulated by the kernel's copy of the command line: `/proc/<pid>/cmdline` here, the process
parameters' `CommandLine` there. The Windows CI legs run the real readers through the two tests this
regression names.

Issue: https://github.com/agentchieflou/this-next-please/issues/520
"""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

import orphans

SLEEPER = [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(300)"]


def _snapshot(pid):
    return [{"pid": r["pid"], "name": "python.exe"} for r in orphans._posix_children(pid)]


def _kernel_copy(pid):
    return " ".join(a for a in orphans._read(f"/proc/{pid}/cmdline").split("\0") if a)


def _cim_says_nothing(pid):
    return ""


@pytest.fixture
def sleeper():
    child = subprocess.Popen(SLEEPER, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        yield child
    finally:
        child.kill()
        child.wait(timeout=30)
        child.stdout.close()


@pytest.fixture
def windows_branch(monkeypatch):
    if not sys.platform.startswith("linux"):
        pytest.skip("the emulation reads /proc; on Windows the real readers run in the tests named above")
    monkeypatch.setattr(orphans, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(orphans, "_toolhelp_children", _snapshot)
    monkeypatch.setattr(orphans, "_cim_cmdline", _cim_says_nothing)
    return monkeypatch


def test_a_child_cim_cannot_read_is_named_by_its_own_command_line(windows_branch, sleeper):
    windows_branch.setattr(orphans, "_native_cmdline", _kernel_copy)
    row = {r["pid"]: r for r in orphans.children()}.get(sleeper.pid)
    assert row, orphans.children()
    assert row["name"] == "python.exe", row
    assert "time.sleep(300)" in row["cmdline"], row
    assert row["cmdline_from"] == "_native_cmdline", row


def test_when_no_reader_answers_the_row_and_the_guard_say_why(windows_branch, sleeper):
    def refused(pid):
        raise OSError(5, f"OpenProcess({pid}) refused")

    windows_branch.setattr(orphans, "_native_cmdline", refused)
    row = {r["pid"]: r for r in orphans.children()}.get(sleeper.pid)
    assert row, orphans.children()
    assert row["cmdline"] == "python.exe", row
    assert row["cmdline_from"] == (f"the image name, because _native_cmdline: OSError: [Errno 5] "
                                   f"OpenProcess({sleeper.pid}) refused; _cim_cmdline: empty"), row
    text = orphans.describe([row])
    assert f"pid {sleeper.pid}  python.exe  python.exe  [the image name, because _native_cmdline" in text, text
