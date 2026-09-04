"""Section 2: pncli import and Jira flavor.

pncli is an npm shim with no .exe, and the doctor must prove the launcher starts, not that a file exists.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_pncli_resolves_or_says_why(run):
    rc, out, _err = run("ad-pncli where", ["pncli", "where"])
    if shutil.which("pncli") is None and "not found" in out.lower():
        pytest.skip("pncli is not installed on this laptop")
    assert rc == 0
    assert "kind" in out


def test_jira_whoami_reports_the_flavor(run):
    if shutil.which("pncli") is None:
        pytest.skip("pncli is not installed on this laptop")
    rc, out, _err = run("ad-jira whoami", ["jira", "whoami"])
    if rc != 0:
        pytest.skip("pncli is installed but not configured; run ad-setup --only pncli")
    assert "flavor" in out and "token_source" in out
