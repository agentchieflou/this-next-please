"""Handoff: C — the ask (issue #165). A question is a record, and a reply unblocks.

The headline defect this slice exists for: an agent that stopped on a question could not be
restarted by answering it. `open_questions` persisted until `--clear-questions`, which no skill ran
on resume, so `session-bootstrap` step 5 and `router` step 2 stopped again on the same block. The
round trip below is what failed.
"""
from __future__ import annotations
import copy
import json
import os
import subprocess
import sys

import pytest

from agentdata import state as ST
from agentdata.fleet import agentstate as A, events as E, lifecycle, registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


def _fold(*events):
    f = A.Fold()
    for ev in events:
        f.add(ev)
    return A.classify(f)


TURN_ENDED = E.event("luna", "turn_ended", {"turn": "0"})


# ------------------------------------------------------------------------ a question is a record


def test_a_blocking_ask_stops_and_an_answer_puts_the_phase_back(fleet_home, tmp_path):
    """The round trip that fails today: ask, stop, answer, continue -- without `--clear-questions`,
    which no skill runs on resume."""
    st = {"phase": "triaged", "active_ticket": "RDSD-118"}
    st = ST.apply(st, {}, asks=[{"q": "Does RDSD-118 cover the UAT workspace too?",
                                 "choices": ["yes", "no, production only"], "default": "yes"}])
    assert st["phase"] == "blocked"
    assert st["blocked_from"] == "triaged", "the phase the question interrupted is what answering restores"
    assert st["open_questions"][0]["id"] == "q1"

    st = ST.apply(st, {}, answers={"q1": "yes, and the UAT workspace too"})
    assert st["phase"] == "triaged", "answering is what leaves blocked"
    assert st["open_questions"] == []
    assert st["answered_questions"][0]["answer"] == "yes, and the UAT workspace too"
    assert "blocked_from" not in st


def test_an_assumption_does_not_stop_the_agent(fleet_home, tmp_path):
    """`--assume` is the difference between *urge* and *stop*: the agent states its default and
    carries on, and the tile shows a row the operator can overturn at leisure."""
    st = ST.apply({"phase": "triaged"}, {},
                  asks=[{"q": "Assuming the window is the last full sprint",
                         "assume": "last full sprint", "blocking": False}])
    assert st["phase"] == "triaged", "an assumption changes no phase"
    assert ST.is_blocking(st["open_questions"][0]) is False

    state = _fold(TURN_ENDED, E.event("luna", "question_opened",
                                      {"question": "Assuming the last full sprint", "id": "q1",
                                       "blocking": False, "assume": "last full sprint"}))
    assert state["state"] == "idle", "a stated assumption is not a demand for a person"
    assert len(state["assumed"]) == 1
    assert state["assumed"][0]["assume"] == "last full sprint"


def test_a_question_written_before_this_slice_still_blocks(fleet_home, tmp_path):
    """A bare string was always something the agent stopped on, and history is never rewritten."""
    st = ST.apply({"phase": "triaged"}, {}, questions=["a plain old string"])
    assert ST.is_blocking(st["open_questions"][0]) is True
    assert ST.question_text(st["open_questions"][0]) == "a plain old string"
    st = ST.apply(st, {}, clear_questions=True)
    assert st["open_questions"] == [], "--clear-questions still works for a human who wants it"


def test_three_questions_in_one_stop_are_answered_in_one_resume(fleet_home, tmp_path):
    """Acceptance criterion: three questions produce one card, one Send, one `started` with three
    ids. Here: one prompt carrying all three, because one respawn per answer is one premium request
    per answer."""
    prompt = lifecycle.answers_prompt([("q1", "yes"), ("q2", "the last full sprint"), ("q3", "b")])
    assert prompt.count(":") >= 3
    for bit in ("q1: yes", "q2: the last full sprint", "q3: b"):
        assert bit in prompt
    assert "ad-state answer" in prompt, "recording is what clears the block, so the prompt says so"
    assert "continue the ticket from where you stopped" in prompt


# ------------------------------------------------------------------------------------- the fold


def test_the_fold_tells_a_blocking_question_from_an_assumption(fleet_home, tmp_path):
    blocking = E.event("luna", "question_opened",
                       {"question": "cover UAT?", "id": "q1", "choices": ["yes", "no"],
                        "blocking": True})
    assumed = E.event("luna", "question_opened",
                      {"question": "assuming last sprint", "id": "q2", "blocking": False,
                       "assume": "last sprint"})
    assert _fold(TURN_ENDED, blocking)["state"] == "needs_human"
    assert _fold(TURN_ENDED, blocking)["why"] == "cover UAT?"
    assert _fold(TURN_ENDED, assumed)["state"] == "idle"
    # Both at once is still a demand: the blocking one outranks.
    assert _fold(TURN_ENDED, assumed, blocking)["state"] == "needs_human"


def test_an_answered_question_stops_demanding_a_person(fleet_home, tmp_path):
    asked = E.event("luna", "question_opened", {"question": "cover UAT?", "id": "q1", "blocking": True})
    answered = E.event("luna", "question_answered",
                       {"id": "q1", "question": "cover UAT?", "answer": "yes", "by": "operator"})
    assert _fold(TURN_ENDED, asked)["state"] == "needs_human"
    assert _fold(TURN_ENDED, asked, answered)["state"] == "idle"


def test_a_nit_does_not_turn_a_tile_red_and_a_blocker_does(fleet_home, tmp_path):
    """`severity` was in the friction template from the start and read by nothing, so a note left
    for later stopped an agent exactly as hard as a contradiction."""
    def friction(severity):
        return E.event("luna", "friction", {"unblock": "a decision", "severity": severity})

    assert _fold(TURN_ENDED, friction("nit"))["state"] == "idle"
    assert _fold(TURN_ENDED, friction("blocker"))["state"] == "blocked"
    assert _fold(TURN_ENDED, friction("friction"))["state"] == "blocked"
    # A friction file written before the line was required still blocks, which is what it did.
    assert _fold(TURN_ENDED, friction(""))["state"] == "blocked"


# ------------------------------------------------------------------------------- the event shape


def test_asking_and_answering_emit_the_two_kinds_with_their_payloads(fleet_home, tmp_path):
    before = {"phase": "triaged"}
    asked = ST.apply(copy.deepcopy(before), {},
                     asks=[{"q": "cover UAT?", "choices": ["yes", "no"], "default": "yes"}])
    opened = E.from_state(before, asked, "luna")
    kinds = [e["kind"] for e in opened]
    assert kinds == ["phase_changed", "question_opened"]
    data = opened[-1]["data"]
    assert data["question"] == "cover UAT?", "`question` keeps meaning the sentence a person reads"
    assert data["id"] == "q1" and data["choices"] == ["yes", "no"] and data["blocking"] is True

    answered = ST.apply(copy.deepcopy(asked), {}, answers={"q1": "yes"})
    events = E.from_state(asked, answered, "luna")
    kinds = [e["kind"] for e in events]
    assert "question_answered" in kinds
    payload = [e for e in events if e["kind"] == "question_answered"][0]["data"]
    assert payload == {"id": "q1", "question": "cover UAT?", "answer": "yes", "by": "operator"}


def test_clearing_a_question_is_not_reported_as_an_answer(fleet_home, tmp_path):
    """A human deciding a question no longer applies did not answer it, and the history must not
    say they did."""
    asked = ST.apply({"phase": "triaged"}, {}, asks=[{"q": "cover UAT?"}])
    cleared = ST.apply(copy.deepcopy(asked), {}, clear_questions=True)
    kinds = [e["kind"] for e in E.from_state(asked, cleared, "luna")]
    assert "question_answered" not in kinds


def test_a_turn_that_answers_one_and_asks_another_reports_both(fleet_home, tmp_path):
    """The old diff was by list *length*, so this exact case reported neither."""
    asked = ST.apply({"phase": "triaged"}, {}, asks=[{"q": "first?"}])
    both = ST.apply(copy.deepcopy(asked), {}, answers={"q1": "yes"})
    both = ST.apply(both, {}, asks=[{"q": "second?"}])
    assert len(both["open_questions"]) == 1 == len(asked["open_questions"]), "same length"
    kinds = [e["kind"] for e in E.from_state(asked, both, "luna")]
    assert "question_opened" in kinds and "question_answered" in kinds


# ---------------------------------------------------------------------------------- the CLI pair


def _state_cli(repo, *args):
    return subprocess.run([sys.executable, "-m", "agentdata.cli_state", *args],
                          cwd=repo, capture_output=True, text=True,
                          env=dict(os.environ, NO_COLOR="1", AGENTDATA_UI="plain"))


def test_ad_state_ask_and_answer_round_trip_from_a_terminal(fleet_home, tmp_path):
    repo = make_project(tmp_path / "luna", phase="triaged", ticket="RDSD-118")

    out = _state_cli(repo, "ask", "Does it cover UAT?", "--choice", "yes", "--choice", "no",
                     "--default", "yes")
    assert out.returncode == 0, out.stderr
    assert "phase: blocked" in out.stdout
    saved = json.loads(open(os.path.join(repo, ".agent", "state.json"), encoding="utf-8").read())
    assert saved["phase"] == "blocked" and saved["blocked_from"] == "triaged"

    refused = _state_cli(repo, "answer", "q9", "whatever")
    assert refused.returncode == 2, "a refusal is exit 2 with a hint naming the ids that are open"
    assert "no open question with id 'q9'" in refused.stdout
    assert "q1" in refused.stdout

    ok = _state_cli(repo, "answer", "q1", "yes")
    assert ok.returncode == 0, ok.stderr
    saved = json.loads(open(os.path.join(repo, ".agent", "state.json"), encoding="utf-8").read())
    assert saved["phase"] == "triaged", "answering unblocks; nobody had to run --clear-questions"
    assert saved["answered_questions"][0]["answer"] == "yes"


# ------------------------------------------------------------- the canonical rule and the skill


def test_rule_10_and_jira_triage_step_4_name_the_same_two_outcomes():
    """The canonical rule and the skill that follows it cannot drift apart: both must say that two
    divergent readings block and a safe default is assumed."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rule = open(os.path.join(root, "AGENTS.md"), encoding="utf-8").read()
    skill = open(os.path.join(root, "skills", "jira-triage", "SKILL.md"), encoding="utf-8").read()
    for text in (rule, skill):
        assert "ad-state ask" in text
        assert "--assume" in text
        assert "two readings" in text.lower()
    assert "CONTINUE" in rule and "CONTINUE" in skill


def test_the_router_only_stops_on_a_blocking_question():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    router = open(os.path.join(root, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    assert "blocking" in router
    assert "assume" in router, "an assumption is explicitly not a stop"


# --------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_the_question_card_offers_the_choices_and_one_send(fleet_home, tmp_path):
    """Acceptance criterion: three questions produce one card and one Send. Asserted on the
    rendered page, because a substring in `app.js` proves an author wrote a line, not that a
    person can see it."""
    import threading

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata.fleet import serve as S
    from test_fleet_desk_browser import launch_chromium

    repo = make_project(tmp_path / "luna", phase="blocked", ticket="RDSD-118")
    Registry().add(repo, name="luna")
    E.append("luna", [
        E.event("luna", "started", {"pid": 1, "prompt": "Ticket RDSD-118."}, ticket="RDSD-118"),
        E.event("luna", "turn_ended", {"turn": "0"}, ticket="RDSD-118"),
        E.event("luna", "question_opened",
                {"question": "Does it cover the UAT workspace?", "id": "q1",
                 "choices": ["yes", "no, production only"], "default": "yes",
                 "blocking": True}, ticket="RDSD-118"),
        E.event("luna", "question_opened",
                {"question": "Which export is the baseline?", "id": "q2", "want": "file",
                 "blocking": True}, ticket="RDSD-118"),
        E.event("luna", "question_opened",
                {"question": "Assuming the last full sprint", "id": "q3", "blocking": False,
                 "assume": "the last full sprint"}, ticket="RDSD-118"),
    ])

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.wait_for_selector('.tile[data-repo="luna"] .asks:not([hidden])', timeout=5000)

            card = page.locator('.tile[data-repo="luna"] .asks')
            # Two blocking questions on one card, and exactly one Send for both.
            assert card.locator(".ask:not([hidden])").count() == 2, "two blocking questions, one card"
            assert "2 questions" in card.locator(".asks-n").inner_text()
            assert card.locator(".asks-send").count() == 1
            assert card.locator('.ask[data-qid="q1"] .ask-choice').count() == 2
            assert "default" in card.locator('.ask[data-qid="q1"] .ask-choice').first.inner_text()
            # `--want file` says so where the answer is typed.
            placeholder = card.locator('.ask[data-qid="q2"] .ask-answer').get_attribute("placeholder")
            assert "path" in placeholder

            # The assumption is a row, not a card, and the tile is not red for it.
            assumed = page.locator('.tile[data-repo="luna"] .assumed')
            assert assumed.is_visible()
            assert "the last full sprint" in assumed.inner_text()

            # Clicking a choice fills that question's answer and nothing else's.
            card.locator('.ask[data-qid="q1"] .ask-choice').first.click()
            assert card.locator('.ask[data-qid="q1"] .ask-answer').input_value() == "yes"
            assert card.locator('.ask[data-qid="q2"] .ask-answer').input_value() == ""

            # Send with nothing typed says so rather than spending a turn.
            page.locator('.tile[data-repo="luna"] .ask[data-qid="q1"] .ask-answer').fill("")
            card.locator(".asks-send").click()
            assert "pick a choice" in card.locator(".asks-note").inner_text()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
