"""Epic #162's acceptance sentence, as one test (issue #169).

A thin ticket is dropped, the card says *thin* and why; a brief and two files are given; the agent
asks one blocking question with two choices and assumes one detail; the question is answered from
the tile in one *Send*; the agent works; and the tile ends with a scope report of
`edited 2 · 0 outside`.

A real `copilot` -- the fake from `tests/fakes/`, launched by the real supervisor, running the real
`ad-state` against real files. Nothing inside the fleet is stubbed: the questions are records
because a subprocess wrote them, and the scope report is a comparison of two things that were
really written down.

**Driven through the API, not a browser**, for `tests/test_fleet_e2e.py`'s reason: the page's
buttons do one thing each, and what a browser adds is whether the layout looks right, which is a
person's judgement. `tests/test_fleet_desk_*.py` covers the rendered page.
"""
from __future__ import annotations
import json
import os
import time

import pytest

import fakes
from agentdata.fleet import events as E, preflight as PF, scope as SCOPE, serve as S, supervisor
from agentdata.fleet.registry import Registry

pytestmark = pytest.mark.slow

TICKET = "RDSD-402"
SETTLE_S = 90


def _project(root: str, project: str = "RDSD") -> str:
    os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Project\n\n- jira_project: {project}\n")
    with open(os.path.join(root, ".agent", "state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"project": project, "phase": "idle", "active_ticket": None,
                   "open_questions": [], "artifacts": []}, f)
    for rel in ("model/measures.tmdl", "model/tables.tmdl"):
        os.makedirs(os.path.join(root, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"// {os.path.basename(rel)}\n")
    return root


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    path = _project(str(tmp_path / "luna"))
    Registry().add(path, name="luna")
    return path


def _settle(name: str, seconds: float = SETTLE_S) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not supervisor.live(name):
            return
        time.sleep(0.2)
    raise AssertionError(f"{name} was still running after {seconds}s")


def _fold(name: str, path: str) -> dict:
    E.refresh(name, path, repo_state=Registry().get(name).state())
    return [r for r in S.fleet_snapshot()["repos"] if r["repo"] == name][0]


def test_a_thin_ticket_is_handed_over_asked_about_answered_and_reported_on(desk, monkeypatch):
    """The epic's acceptance sentence, end to end."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "handoff-demo")

    # 1. The drop opens a card rather than launching. The ticket is thin, and the card says which
    #    row made it thin -- and it spent no premium request finding out.
    monkeypatch.setattr(PF, "fetch_issue", lambda key, **kw: {
        "key": TICKET, "summary": "Refresh is slow", "description": "", "status": "To Do",
        "assignee": "", "comments": 0, "attachments": 0})
    card = PF.preflight(TICKET, "luna")
    assert card["verdict"] == "thin", card
    thin = {r["row"]: r for r in card["rows"] if r["verdict"] != "ready"}
    assert thin, "a thin verdict with every row ready would say nothing about why"
    assert thin["criteria"]["why"] == "the agent will have to infer what done means"
    assert thin["description"]["why"] == "there is nothing for the agent to read"

    # 2. The operator gives it the two files they already had open, and a brief.
    ev = SCOPE.add("luna", desk, TICKET,
                   ["model/measures.tmdl", "model/tables.tmdl"],
                   why="the two files this lives in", how=SCOPE.BY_HASH, queued=False)
    assert (ev.get("data") or {}).get("paths") == ["model/measures.tmdl", "model/tables.tmdl"]
    given = SCOPE.read_scope(desk, TICKET)
    assert sorted(r["path"] for r in given) == ["model/measures.tmdl", "model/tables.tmdl"]

    supervisor.start("luna", key=TICKET, cfg={"fleet": {"notify": {"toast": False}}},
                     brief="the nightly window is the one that matters")
    _settle("luna")

    # 3. It asked one blocking question with two choices, and assumed one detail rather than
    #    stopping on it. The tile says both, and only one of them holds it up.
    row = _fold("luna", desk)
    assert row["needs_human"], row["state"]
    blocking = [q for q in row["asked"] if q.get("blocking", True)]
    assert len(blocking) == 1, row["asked"]
    assert blocking[0]["q"] == "Which workspace is UAT?"
    assert blocking[0]["choices"] == ["UAT", "PROD"]
    # The other one is an assumption it stated and carried on with. It is on the tile to overturn
    # at leisure, and it is not what is holding the agent up.
    assert [a["assume"] for a in row["assumed"]] == ["the nightly one"], row["assumed"]
    assert all(q.get("blocking", True) is False for q in row["assumed"])

    # The brief reached the checkout, and it is the only thing the fleet wrote inside it.
    brief = os.path.join(desk, ".agent", "in", TICKET, "brief.md")
    assert os.path.isfile(brief)
    assert "nightly window" in open(brief, encoding="utf-8").read()

    # 4. One Send answers it. One respawn, not one per question.
    before = sum(1 for e in E.read("luna") if e["kind"] == "started")
    S.act("answer", {"repo": "luna", "answers": [{"id": blocking[0]["id"], "answer": "UAT"}]})
    _settle("luna")
    after = sum(1 for e in E.read("luna") if e["kind"] == "started")
    assert after == before + 1, "one resume for the answer, not one per question"

    # 5. It worked, and the tile says what it edited against what it was given.
    row = _fold("luna", desk)
    assert not [q for q in row["asked"] if q.get("blocking", True)], \
        "answering it is what unblocked it"
    assert not row["needs_human"]
    report = row["scope_report"]
    assert report, "a run that was given a scope ends with a report on it"
    assert report["given"] == 2 and report["edited"] == 2 and report["outside"] == []
    assert sorted(report["inside"]) == ["model/measures.tmdl", "model/tables.tmdl"]


def test_the_fleet_wrote_nothing_in_the_repository_but_the_handoff_directory(desk, monkeypatch):
    """The one documented exception, and nothing beside it. `.agent/state.json` changes because the
    agent's own `ad-state` changed it, which is a different thing from the fleet writing there."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "handoff-demo")
    SCOPE.add("luna", desk, TICKET, ["model/measures.tmdl"], why="one file", how=SCOPE.BY_HASH,
              queued=False)
    supervisor.start("luna", key=TICKET, cfg={"fleet": {"notify": {"toast": False}}},
                     brief="one line")
    _settle("luna")

    written = set()
    for dirpath, _dirs, files in os.walk(os.path.join(desk, ".agent")):
        for name in files:
            written.add(os.path.relpath(os.path.join(dirpath, name), desk).replace("\\", "/"))
    outside_handoff = {w for w in written
                       if not w.startswith(f".agent/in/{TICKET}/") and w != ".agent/state.json"}
    assert not outside_handoff, outside_handoff


def test_one_answer_is_reported_once_however_often_the_stream_is_refreshed(desk, monkeypatch):
    """`ad-state` emits a state change the moment it saves -- so the dashboard does not wait for a
    poll -- and `events.refresh` diffs the same change again against its own cursor. That is by
    design and the stream is additive, so both stay; what must not happen is the *second* one
    repeating for ever, which it did because the cursor remembered open questions and not answered
    ones."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "handoff-demo")
    supervisor.start("luna", key=TICKET, cfg={"fleet": {"notify": {"toast": False}}})
    _settle("luna")
    blocking = [q for q in _fold("luna", desk)["asked"] if q.get("blocking", True)]
    S.act("answer", {"repo": "luna", "answers": [{"id": blocking[0]["id"], "answer": "UAT"}]})
    _settle("luna")

    state = Registry().get("luna").state()
    for _ in range(5):
        E.refresh("luna", desk, repo_state=state)
    answered = [e for e in E.read("luna") if e["kind"] == "question_answered"]
    assert len(answered) <= 2, [e["data"] for e in answered]

    # And the fold says it once, however many times it was reported.
    row = _fold("luna", desk)
    assert [q["q"] for q in row["asked"] if q.get("blocking", True)] == []
