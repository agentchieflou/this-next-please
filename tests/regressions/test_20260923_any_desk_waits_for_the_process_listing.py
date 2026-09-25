"""2026-09-23, the Windows 3.14 leg of #276 (and of #270's merge to main): a desk drew no pane at all.

Symptom (`windows · python 3.14`, tests/regressions/test_20260922_any_chrome_snapback.py):

    playwright._impl._errors.TimeoutError: Page.wait_for_selector: Timeout 10000ms exceeded.
      - waiting for locator(".tile.is-solo[data-tier=\\"full\\"]") to be visible
    --- the page ---  "tiles": [], "deskVersion": null
    Thread-6 (process_request_thread):
      subprocess.py, line 557 in run
      agentdata/fleet/adopt.py, line 107 in _windows_processes
      agentdata/fleet/serve.py, line 452 in fleet_snapshot

The desk's first answer waited for the process listing behind the adopt offers, and on Windows that
listing is a PowerShell `Get-CimInstance` -- seconds to start, and on a loaded runner more than the
ten the test gives a desk to draw its first pane. Every desk request that found the ten-second cache
stale started a PowerShell of its own besides. A desk now draws with the listing it already holds
and refreshes it on one thread of its own; an explicit adopt, which has to be current, still waits.

The listing is held open here, as a PowerShell that has not answered yet, which makes the order
deterministic on every platform.

Issue: https://github.com/agentchieflou/this-next-please/issues/235
"""
from __future__ import annotations

import threading
import time

import pytest

from agentdata.fleet import adopt as A, serve as S

from test_fleet_column import _repos, fleet_home  # noqa: F401 - fixtures


@pytest.fixture()
def slow_listing(monkeypatch):
    """A listing that answers only when told to, and counts how many were started."""
    release, started = threading.Event(), []

    def listing():
        started.append(time.monotonic())
        release.wait(20)
        return [{"pid": 4242, "cmdline": "copilot --banner", "cwd": ""}]

    monkeypatch.setattr(A, "_list_now", listing)
    monkeypatch.setattr(A, "_cache", {"at": 0.0, "rows": []})
    monkeypatch.setattr(A, "_listing", {"thread": None})
    yield release, started
    release.set()


def test_a_desk_answer_does_not_wait_for_the_process_listing(fleet_home, tmp_path, slow_listing):
    release, started = slow_listing
    _repos(tmp_path, "alpha", "beta")

    t0 = time.monotonic()
    snap = S.fleet_snapshot()
    assert time.monotonic() - t0 < 5, "the snapshot waited for the listing"
    assert {r["repo"] for r in snap["repos"]} >= {"alpha", "beta"}

    # Three more desks asking while it is still out start no second listing.
    for _ in range(3):
        S.fleet_snapshot()
    assert len(started) == 1, started

    release.set()
    deadline = time.monotonic() + 10
    while A._listing["thread"] is not None:
        assert time.monotonic() < deadline, "the listing never came back"
        time.sleep(0.02)
    # And the next tick draws what it found.
    assert A.agent_processes(wait=False) == [{"pid": 4242, "cmdline": "copilot --banner", "cwd": ""}]


def test_an_explicit_adopt_still_waits_for_a_current_listing(slow_listing):
    release, started = slow_listing
    # The clock starts before the timer (#482). `Timer.start()` returns once the timer's thread
    # runs, so its 0.3 s is already counting. Read after it, t0 lost however long this thread took
    # to be scheduled again, 53-145 ms at a load average of 20-34, and a real wait measured short.
    t0 = time.monotonic()
    threading.Timer(0.3, release.set).start()
    rows = A.agent_processes(max_age=0)
    assert time.monotonic() - t0 >= 0.25, "a refusal has to be current, so this one waits"
    assert rows and rows[0]["pid"] == 4242
    assert len(started) == 1


def test_an_adopt_joins_the_listing_already_out_rather_than_starting_a_second(slow_listing):
    """A fresh desk's first answer starts the listing, and the operator's first adopt came while it
    was still out: a second PowerShell for the same answer, and the adopt's answer waiting on it.
    That adopt's answer is the one the hand-back raced on the Windows 3.14 leg of main."""
    release, started = slow_listing
    A.agent_processes(wait=False)                              # the desk's first answer
    threading.Timer(0.3, release.set).start()
    rows = A.agent_processes()                                 # the adopt, a moment later
    assert rows and rows[0]["pid"] == 4242
    assert len(started) == 1, "two listings for one answer"
