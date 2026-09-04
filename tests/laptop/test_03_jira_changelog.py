"""Section 3: Jira changelog and sprint replay.

Field ids differ per Jira instance, so pinning them is the step that makes the rest reproducible.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def _configured():
    from agentdata import config

    return bool(config.project_facts().get("jira_project")) and shutil.which("pncli")


def test_fields_can_be_pinned(run):
    if not _configured():
        pytest.skip("no jira_project fact, or pncli is absent")
    rc, out, _err = run("ad-jira fields --pin", ["jira", "fields", "--pin"])
    assert rc == 0
    assert "pinned_sprint" in out


def test_sprints_list_for_the_board(run):
    from agentdata import config

    board = config.project_facts().get("jira_board_id")
    if not (_configured() and board):
        pytest.skip("no jira_board_id fact")
    rc, out, _err = run("ad-jira sprints", ["jira", "sprints", "--board", board, "--state", "closed"])
    assert rc == 0, out
