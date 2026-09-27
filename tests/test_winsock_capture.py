"""The #435 capture: a snapshot of Winsock at the moment a test fails with its signature.

Diagnostics only. It runs on Windows, and only for a failure whose text says ERR_NO_BUFFER_SPACE,
WinError 10053/10055 or a Playwright timeout; it never changes an outcome. The commands are faked
here, so the summary is checked on any OS."""
from __future__ import annotations
import json
import os

import winsock_capture as W

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       980
  TCP    127.0.0.1:50001        127.0.0.1:50002        ESTABLISHED     4242
  TCP    127.0.0.1:50002        127.0.0.1:50001        ESTABLISHED     5151
  TCP    127.0.0.1:50003        127.0.0.1:50004        TIME_WAIT       0
  TCP    127.0.0.1:50005        127.0.0.1:50006        ESTABLISHED     4242
"""
PROCS = json.dumps([{"Name": "chrome", "Id": 4242, "Handles": 900},
                    {"Name": "python", "Id": 5151, "Handles": 1200}]) + "\nPOOL 268435456\n"


def fake(argv):
    return NETSTAT if argv[0] == "netstat" else PROCS


def test_it_fires_only_on_windows_and_only_on_the_signature():
    for text in ("Page.goto: net::ERR_NO_BUFFER_SPACE at http://127.0.0.1:1/",
                 "ConnectionAbortedError: [WinError 10053] An established connection was aborted",
                 "OSError: [WinError 10055] An operation on a socket could not be performed",
                 "Page.wait_for_function: Timeout 15000ms exceeded."):
        assert W.section(text, os_name="nt", run=fake), text
        assert W.section(text, os_name="posix", run=fake) is None, text
    assert W.section("AssertionError: assert 1 == 2", os_name="nt", run=fake) is None


def test_the_snapshot_counts_states_owners_handles_and_the_pool():
    out = W.section("net::ERR_NO_BUFFER_SPACE", os_name="nt", run=fake).splitlines()
    assert out[0] == "TCP sockets: 5; by state: ESTABLISHED 3, LISTENING 1, TIME_WAIT 1"
    assert out[1] == "  pid 4242: 2 (ESTABLISHED 2)"
    assert "live python/chrome/node: 2; handles in all: 2100" in out
    assert out.index("  python pid 5151: 1200 handles") < out.index("  chrome pid 4242: 900 handles")
    assert out[-1] == "nonpaged pool: 268435456 bytes (256.0 MiB)"


def test_a_command_that_fails_is_reported_and_never_raises():
    def broken(argv):
        return f"<{argv[0]} failed: boom>"
    out = W.section("WinError 10053", os_name="nt", run=broken)
    assert out.startswith("TCP sockets: 0; by state: none")
    assert out.endswith("nonpaged pool: not read")
    assert "<" in W._run(["a-command-that-does-not-exist-435"])


def test_the_report_hook_adds_the_snapshot_to_a_failed_test():
    """Read from the source, as the other conftest guards are: the hook passes the failure's own
    text (traceback and captured output) to `section` and adds what it returns as a report section."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py"), encoding="utf-8").read()
    hook = src[src.index("def pytest_runtest_makereport"):]
    hook = hook[:hook.index("\n\n\n")]
    assert "winsock_capture.section(" in hook and "report.sections.append((winsock_capture.TITLE" in hook
    assert "report.failed" in hook
