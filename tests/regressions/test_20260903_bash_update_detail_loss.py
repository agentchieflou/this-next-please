"""2026-09-03, Git Bash (MINGW64) and PowerShell alike: ad-update threw away the real pip error.

Symptom, photographed in PyCharm's MINGW64 terminal:

    part    status   detail                                              hint
    cli     x fail   Uninstalling agentdata-0.5.3:                       run it yourself to see the whole output (exit 1, 17.1s)

`_run()` kept the last non-empty line of stdout, and pip prints its uninstall banner to stdout while
the actual error goes to stderr. So the one line that said what went wrong was discarded, and the
user was told to run the command again themselves.

Issue: https://github.com/agentchieflou/this-next-please/issues/66
"""
from __future__ import annotations

from agentdata import proc, update

# the two streams exactly as pip produces them for a non-elevated uninstall of an all-users install
PIP_STDOUT = (
    "Installing collected packages: agentdata\n"
    "  Attempting uninstall: agentdata\n"
    "    Found existing installation: agentdata 0.5.3\n"
    "    Uninstalling agentdata-0.5.3:"
)
PIP_STDERR = (
    "ERROR: Could not install packages due to an OSError: [WinError 5] Access is denied\n"
    "Consider using the `--user` option or check the permissions.\n"
)


def test_the_real_error_reaches_the_row(monkeypatch):
    monkeypatch.setattr(proc, "run", lambda argv, **kw: (1, PIP_STDOUT, PIP_STDERR, 17.1))
    rows = []
    update._run("cli", ["pip"], rows, 600)

    detail = rows[0]["detail"]
    assert "WinError 5" in detail, "the regression: the error was replaced by pip's banner"
    assert "Access is denied" in detail
    assert rows[0]["hint"] != "run it yourself to see the whole output (exit 1, 17.1s)"
    assert "all users" in rows[0]["hint"]
