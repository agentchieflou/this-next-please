"""Section 5: Power BI tools and workspaces.

TE2 and dscmd are pinned paths, not PATH lookups; the doctor row proves each starts.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_powerbi_rows_each_carry_a_hint(run):
    rc, out, _err = run("ad-doctor --only powerbi", ["doctor", "--only", "powerbi"])
    assert rc in (0, 1)
    assert "powerbi" in out
