"""Section 0: baseline — the floors, before anything else.

The floors are checked first so a run started in the wrong window fails here with the fix,
rather than producing an evidence file that quietly describes an unsupported setup.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_the_python_floor_is_met():
    import sys

    assert sys.version_info >= (3, 12), (
        f"this is Python {sys.version_info.major}.{sys.version_info.minor} at {sys.executable}; "
        "agentdata 0.6+ needs 3.12 or newer -- run the suite with the newer interpreter"
    )


def test_the_shell_is_one_we_support():
    """A Windows PowerShell 5.1 window stops here, with the hint, and writes no misleading evidence."""
    from agentdata import shell

    got = shell.detect()
    assert got != "windows-powershell", shell.SWITCH_HINT
    assert got in ("pwsh", "bash", "cmd", "posix", "zsh", "unknown"), got


def test_ad_update_check_reports_the_commit(run):
    rc, out, _err = run("ad-update --check", ["update", "--check"])
    assert rc == 0
    assert "commit:" in out and "version:" in out


def test_the_suite_passes_in_a_checkout(run):
    """Only meaningful in a clone of this repo; the count is whatever CI printed for this commit."""
    import subprocess
    import sys

    if not os.path.isfile(os.path.join(os.path.dirname(__file__), "..", "test_entrypoints.py")):
        pytest.skip("not a checkout of this-next-please")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "not slow and not laptop"],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    assert p.returncode == 0, p.stdout[-3000:]


def test_the_console_can_be_switched_to_utf8(run):
    rc, out, _err = run("ad-doctor --only console", ["doctor", "--only", "console"])
    assert rc in (0, 1)
    assert "console,host" in out or "host" in out
