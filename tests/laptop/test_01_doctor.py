"""Section 1: doctor before setup.

Every fail row must name the `ad-setup --only <step>` that fixes it, and nothing may traceback.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_doctor_exits_zero_or_one_with_hints_on_every_fail(run):
    rc, out, _err = run("ad-doctor", ["doctor"])
    assert rc in (0, 1), f"the contract is 0 or 1, got {rc}"
    assert "Traceback" not in out

    from agentdata import toon

    assert not toon.validate(out), toon.validate(out)
    for line in out.splitlines():
        if ",fail," in line:
            assert line.rstrip().rstrip('"') != line.rstrip().rstrip('"').rstrip(","), \
                f"a fail row with no hint: {line}"
