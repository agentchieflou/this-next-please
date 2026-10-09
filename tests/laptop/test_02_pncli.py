"""Section 2: Jira credentials and flavor; pncli is the optional backend.

pncli is an npm shim with no .exe, and the doctor must prove the launcher starts, not that a file exists.
`ad-jira whoami` needs no pncli at all: `ad-setup --only jira` (keyring), JIRA_TOKEN, or pncli's file last.
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
    rc, out, _err = run("ad-jira whoami", ["jira", "whoami"])
    if rc != 0:
        pytest.skip("no Jira credentials on this laptop; run ad-setup --only jira (or --only pncli with pncli installed)")
    assert "flavor" in out and "token_source" in out
