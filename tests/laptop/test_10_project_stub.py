"""Section 10: project stub.

The stub is what every later session reads; a missing fact costs a round trip each time.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_the_stub_exists_and_carries_the_facts_this_repo_reads():
    from agentdata import config

    if not os.path.isfile("AGENTS.md"):
        pytest.skip("not inside a project with an AGENTS.md")
    facts = config.project_facts()
    assert facts, "AGENTS.md has no `- key: value` facts filled in"


def test_state_is_written_only_by_ad_state(run):
    if not os.path.isdir(".agent"):
        pytest.skip("no .agent directory here")
    rc, out, _err = run("ad-state show", ["state", "show"])
    assert rc == 0, out
    assert "phase" in out
