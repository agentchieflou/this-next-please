"""Sitting: E — the caution, exercised (issue #184).

A real `copilot` -- the fake from `tests/fakes/`, launched by the real supervisor with the real
allow-list -- on two real checkouts. On the one with seven branches it looks, names the three that
never reached main, states that it continues on the branch that already carries its ticket, and
creates nothing. On the clean one it looks, finds nothing, and creates the ticket's branch. The
same two reads the fleet's tile makes, so the count in the transcript is the count on the tile.
"""
from __future__ import annotations
import time

import pytest

from agentdata.fleet import events as E, supervisor
from agentdata.fleet.registry import Registry

import fakes
from test_fleet import make_project
from test_fleet_branches import seven_branches, two_branches, git

SETTLE_S = 90


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    return tmp_path


def _settle(name: str, seconds: float = SETTLE_S) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not supervisor.live(name):
            return
        time.sleep(0.2)
    raise AssertionError(f"{name} was still running after {seconds}s")


def _fold(name: str, path: str) -> list[dict]:
    """The agent's JSONL is folded into the stream on a read, the way the page's snapshot does it."""
    E.refresh(name, path, repo_state=Registry().get(name).state())
    return E.read(name)


def _calls(name: str) -> list[str]:
    return [((e.get("data") or {}).get("arguments") or {}).get("command", "")
            for e in E.read(name) if e["kind"] == "tool_call"]


def _kinds(name: str, kind: str) -> int:
    return sum(1 for e in E.read(name) if e["kind"] == kind)


def test_on_seven_branches_the_agent_creates_none_and_continues_on_the_tickets_own(desk, monkeypatch):
    """Acceptance criterion. Counting `started` events and `git checkout -b` calls: one start,
    no branch created, and the look was permitted -- both reads succeeded under the real
    allow-list, which is what proves the two new prefixes are enough."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "branches-caution")
    path = make_project(desk / "luna", ticket="RDSD-7", phase="triaged")
    seven_branches(path)
    Registry().add(path, name="luna")

    supervisor.start("luna", key="RDSD-7", cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    _fold("luna", path)

    calls = _calls("luna")
    assert _kinds("luna", "started") == 1
    assert not [c for c in calls if c.startswith("git checkout -b")], calls
    assert _kinds("luna", "denied") == 0, "the look must be permitted"
    assert [c for c in calls if c.startswith("git for-each-ref refs/heads")]
    assert [c for c in calls if c.startswith("git branch --no-merged main")]
    results = [e for e in E.read("luna") if e["kind"] == "tool_result"]
    assert all(e["data"]["ok"] for e in results), results

    # It said the count, the fleet's count -- and the assumption it carried on with is on record.
    said = " ".join((e.get("data") or {}).get("text", "") for e in E.read("luna") if e["kind"] == "assistant_text")
    assert "branches=7 (3 unmerged)" in said
    state = Registry().get("luna").state()
    assert state["branch"] == "feature/RDSD-7-part-2"
    assert state["phase"] == "optimizing", "cautious, not stopped"
    assert any("continue on feature/RDSD-7-part-2" in str(q.get("assume", "")) for q in state.get("open_questions", []))
    # And the checkout still has exactly the seven it had: the agent deleted nothing either.
    assert len(git(path, "for-each-ref", "refs/heads", "--format=%(refname:short)").split()) == 7


def test_on_a_clean_checkout_the_agent_creates_the_tickets_branch(desk, monkeypatch):
    """Acceptance criterion, the other half: on a clean fixture it creates one."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "branches-clean")
    path = make_project(desk / "luna", ticket="RDSD-7", phase="triaged")
    git(path, "init", "-q", "-b", "main")
    git(path, "commit", "-q", "--allow-empty", "-m", "the beginning")
    Registry().add(path, name="luna")

    supervisor.start("luna", key="RDSD-7", cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    _fold("luna", path)

    calls = _calls("luna")
    assert _kinds("luna", "started") == 1
    assert [c for c in calls if c.startswith("git checkout -b")] == ["git checkout -b feature/RDSD-7"]
    assert _kinds("luna", "denied") == 0
    assert git(path, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature/RDSD-7"
    assert Registry().get("luna").state()["branch"] == "feature/RDSD-7"
