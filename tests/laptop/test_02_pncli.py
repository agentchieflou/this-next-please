"""Section 2: pncli and the Jira credentials it lends.

pncli is required and used directly. It is an npm shim with no .exe, and the doctor must prove the launcher
starts, not that a file exists. `ad-jira whoami` borrows pncli's token (or JIRA_TOKEN, or the keyring fallback).
"""
from __future__ import annotations
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_pncli_resolves_or_says_why(run):
    rc, out, _err = run("ad-doctor --only pncli", ["doctor", "--only", "pncli"])
    if shutil.which("pncli") is None and "not found" in out.lower():
        pytest.skip("pncli is not installed on this laptop")
    assert "pncli launcher,ok" in out, f"exit {rc}: the launcher row is what `where` used to answer"


def test_jira_whoami_reports_the_flavor(run):
    rc, out, _err = run("ad-jira whoami", ["jira", "whoami"])
    if rc != 0:
        pytest.skip("no Jira credentials on this laptop; run ad-setup --only pncli (or ad-setup --only jira without pncli)")
    assert "flavor" in out and "token_source" in out
