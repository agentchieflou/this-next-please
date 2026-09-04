"""Section 6: PBIP projection and validator (no Desktop needed).

The one Power BI section that needs no Desktop, so it is the one that can always run.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def _pbip():
    from agentdata import config

    return config.project_facts().get("pbip_path")


def test_pbip_check_runs_on_the_projects_pbip(run):
    path = _pbip()
    if not (path and os.path.exists(path)):
        pytest.skip("no pbip_path fact pointing at a real PBIP")
    rc, out, _err = run("ad-pbip check", ["pbip", "check", os.path.dirname(path)])
    assert rc in (0, 1, 2), out
    assert "Traceback" not in out
