"""The runbook's §Mobile rows (#570): what only the laptop, the tenant and the phone can answer.

Nothing here runs a row: the mobile sitting (#582) does. These hold the shape the sitting fills in. Twelve
rows, each with a command or a gesture, an expectation and *not yet measured*; every row named under "The
open questions these rows answer"; the defaults the rows could move (`expire_s`, the heartbeat, `TICK_S`)
named as such; and the scriptable rows in one `laptop` function (P-14), skipped by an ordinary run.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNBOOK = os.path.join(REPO_ROOT, "docs", "windows-verification.md")
MODULE = os.path.join(REPO_ROOT, "tests", "laptop", "test_12_mobile.py")
HEADING = "## Mobile (#538, #539): the bridge, the phone and the tenant"
ROWS = [f"M{n}" for n in range(1, 13)]
SCRIPTED = ("M2", "M5", "M6", "M7", "M12")


def _section() -> str:
    text = open(RUNBOOK, encoding="utf-8").read()
    assert HEADING in text, "the runbook has no §Mobile section"
    tail = text.split(HEADING, 1)[1]
    nxt = re.search(r"^## ", tail, flags=re.M)
    return tail[:nxt.start()] if nxt else tail


def _rows(section: str) -> dict[str, list[str]]:
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| M") and cells and re.fullmatch(r"M\d+", cells[0]):
            rows[cells[0]] = cells
    return rows


def test_the_mobile_rows_are_all_there_unmeasured_and_each_names_the_question_it_closes():
    section = _section()
    rows = _rows(section)
    assert list(rows) == ROWS, list(rows)
    for name, cells in rows.items():
        assert len(cells) == 5, (name, cells)
        _, run, expect, host, date = cells
        assert run and expect, name
        assert host.strip("_* ") == "not yet measured" and date == "—", (name, host, date)
    # No row makes a claim: the numbers a row could move are named as defaults the sitting decides.
    for default in ("`fleet.mobile.expire_s`", "`HEARTBEAT_S`", "`TICK_S`"):
        assert default in section, default

    assert "### The open questions these rows answer" in section
    questions = section.split("### The open questions these rows answer", 1)[1]
    named = set(re.findall(r"\bM\d+\b", questions))
    assert named == set(ROWS), sorted(set(ROWS) ^ named)
    for note in ("laptop_bridge_design.md", "flows_and_onedrive_bridge.md", "notifications_intune_powerapps.md"):
        assert note in questions, note

    page = open(os.path.join(REPO_ROOT, "docs", "fleet-mobile.md"), encoding="utf-8").read()
    assert "windows-verification.md#mobile-538-539-the-bridge-the-phone-and-the-tenant" in page


def test_the_scriptable_rows_are_one_laptop_function_an_ordinary_run_skips():
    src = open(MODULE, encoding="utf-8").read()
    assert re.search(r"^pytestmark = \[pytest\.mark\.laptop, pytest\.mark\.real_home\]$", src, flags=re.M)
    functions = re.findall(r"^def (test_\w+)", src, flags=re.M)
    assert len(functions) == 1, functions                     # P-14: one function against the slow-tier cap
    for row in SCRIPTED:
        assert f'"{row}"' in src, row

    env = {k: v for k, v in os.environ.items() if k != "AGENTDATA_LAPTOP"}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs", MODULE],
                       capture_output=True, text=True, cwd=REPO_ROOT, env=env)
    assert "1 skipped" in p.stdout and "AGENTDATA_LAPTOP=1" in p.stdout, p.stdout[-800:]
