"""The friction scan of 2026-10 (FRICTION-SCAN-REPORT.md §1), pinned where the router reads it.

Each test names the cluster it answers. They read skill text on purpose: the router is prose a
model follows, and a sentence removed in a tidy-up is how each of these came back last time.
"""
from __future__ import annotations
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skill(name: str) -> str:
    return open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8").read()


def step(text: str, n: int) -> str:
    """Numbered step `n` of a skill, with its indented continuation lines."""
    m = re.search(rf"(?ms)^{n}\. .*?(?=^\d+\. |^\| |\Z)", text)
    assert m, f"step {n} not found"
    return m.group(0)


def test_1_1_the_router_asks_ad_state_what_blocks_this_ticket_not_the_whole_list():
    two = step(skill("router"), 2)
    assert "ad-state blocking" in two
    assert "ad-state answer" in two and "ad-state supersede" in two
    assert "parked" in two
    # a question already logged is not logged again on every later request
    assert "Do not run `friction-log` again" in two


def test_1_1_session_bootstrap_leaves_the_blocked_decision_to_the_router():
    five = step(skill("session-bootstrap"), 5)
    assert "router's step 2" in five and "do not stop here" in five
    assert "ad-graph status" in five


def test_1_3_operational_run_requests_route_ahead_of_tickets_and_uat():
    rows = re.findall(r"^\|[^|]*\|\s*`([a-z0-9\-]+)`\s*\|$", skill("router"), re.M)
    assert rows[0] == "run-control"
    assert rows.index("run-control") < rows.index("uat-jira-vs-source") < rows.index("jira-changelog")


def test_1_3_code_changes_have_a_fallback_and_bootstrap_only_requests_end_cleanly():
    router = skill("router")
    assert "`code-change`" in step(router, 7)
    assert "ready —" in step(router, 4)
    assert "## Project routes" in router


def test_1_4_environment_errors_are_their_own_outcome():
    eight = step(skill("router"), 8)
    assert "--want access" in eight and "tool-error" in eight
    assert "never fixed by re-running a skill" in eight


def test_1_2_success_is_proven_not_inferred_from_an_exit_code():
    assert "Exit 0 is not a deploy" in skill("pbi-deploy-te2")
    assert "refresh_not_observed" in skill("pbi-refresh-xmla")
    assert "Indeterminate" in skill("pbi-publish")
    assert "Exit 0 is not success" in skill("run-control")
    assert "no_tests" in skill("perf-optimize")


def test_2_x_test_regress_has_a_scoped_mode_for_a_dirty_worktree():
    text = skill("test-regress")
    assert "scoped mode" in text and "git stash push --include-untracked --" in text
