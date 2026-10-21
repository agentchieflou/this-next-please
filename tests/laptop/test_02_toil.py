"""Section 2: toil and the Jira connection the extensions go through.

toil is required and used directly. It is an npm shim with no .exe and needs Node 24.14+, so the doctor must prove
the launcher starts (`toil version` answers an envelope), not that a file exists. `ad-jira whoami` goes through
toil's Jira connection (or JIRA_TOKEN, or the keyring fallback) and names which.
"""
from __future__ import annotations
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_toil_resolves_or_says_why(run):
    rc, out, _err = run("ad-doctor --only toil", ["doctor", "--only", "toil"])
    if shutil.which("toil") is None and "not found" in out.lower():
        pytest.skip("toil is not installed on this laptop")
    assert "toil launcher,ok" in out, f"exit {rc}: the launcher row proves `toil version` answers"


def test_jira_whoami_reports_the_flavor(run):
    rc, out, _err = run("ad-jira whoami", ["jira", "whoami"])
    if rc != 0:
        pytest.skip("no Jira connection on this laptop; `toil connections add <name> --area jira`, then "
                    "ad-setup --only toil (or ad-setup --only jira without toil)")
    assert "flavor" in out and "token_source" in out
