"""Section 7: Desktop discovery and live evaluation.

Needs Power BI Desktop open; the prompt says so rather than failing mysteriously.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_desktop_is_discovered_when_open(run, ask):
    answer = ask("Open the project's PBIP in Power BI Desktop and wait for the model to load")
    if str(answer).strip().lower() == "skip":
        pytest.skip("Desktop step skipped by the operator")
    rc, out, _err = run("ad-pbip desktop", ["pbip", "desktop"])
    assert rc in (0, 1)
    assert "Traceback" not in out


def test_desktop_2157_answers_the_bridge_in_its_documented_words(run):
    """0.18.0's acceptance on the laptop: with the PBIP open in Desktop 2.157 (the step above), the
    Desktop Bridge answers `bridge.manifest` with the four documented methods, and `desktop status`
    places the release against the one this package was verified with (2.157)."""
    rc, out, _err = run("ad-pbip bridge probe", ["pbip", "bridge", "probe"])
    assert rc == 0 and "Traceback" not in out
    assert "pipe_present: true" in out, f"no Desktop Bridge pipe -- Options > Security > Desktop Bridge, or the policy:\n{out}"
    assert "dialect: documented" in out, out
    for method in ("application.state.get/v1", "file.reload/v1", "report.snapshot.capture/v1"):
        assert method in out, f"{method} not declared:\n{out}"
    rc, out, _err = run("ad-pbip desktop status", ["pbip", "desktop", "status"])
    assert rc == 0 and "Traceback" not in out
    assert "documented" in out, f"status did not read the bridge's state:\n{out}"
    assert "older" not in out, f"Desktop is older than 2.157:\n{out}"
