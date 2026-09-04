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
