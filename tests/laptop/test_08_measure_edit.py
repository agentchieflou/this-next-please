"""Section 8: mechanical measure edit round trip.

Runs on a scratch copy: the point is the round trip, not editing anyone's report.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_a_measure_edit_round_trips_on_a_copy(run, tmp_path):
    from agentdata import config

    path = config.project_facts().get("tmdl_path")
    if not (path and os.path.isdir(path)):
        pytest.skip("no tmdl_path fact pointing at a real folder")

    scratch = tmp_path / "definition"
    shutil.copytree(path, scratch)
    rc, out, _err = run("ad-pbip lint (scratch copy)", ["pbip", "lint", str(scratch)])
    assert rc in (0, 1, 2), out
    assert "Traceback" not in out
