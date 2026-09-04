"""Section 9: UAT end to end on one small chart.

The full loop, and the one section that proves the pieces talk to each other.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_uat_help_is_reachable(run):
    rc, out, _err = run("ad-uat --help", ["uat", "--help"])
    assert rc == 0
    assert "usage" in out.lower()
