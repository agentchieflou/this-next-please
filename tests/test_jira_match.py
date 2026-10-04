"""Which ticket a prompt belongs to (`agentdata/jira_match.py`, `ad-jira match`, 2026-10-03).

The operator wanted to prompt an agent however they like and still have the work ticketed: the
agent finds the open ticket the prompt is most like and offers it, or `new`, or `none`. The match
is word overlap, computed in the CLI, because a cheap model asked "does this fit RDSD-118?" says
yes to anything. These tests hold the verdict table, the one `ad-state ask` line it prints, and
that answering the question is what moves the work.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import cli_jira, cli_state, jira_match as JM, state as S


ROWS = [
    {"key": "RDSD-118", "status": "To Do", "summary": "Committed points wrong on the sprint chart", "project": "RDSD"},
    {"key": "RDSD-101", "status": "In Progress", "summary": "Six measures are unused", "project": "RDSD"},
    {"key": "RDSD-77", "status": "To Do", "summary": "Teradata history table missing a column", "project": "RDSD"},
    {"key": "DATAENG-9", "status": "To Do", "summary": "Somebody else's problem", "project": "DATAENG"},
]


# ------------------------------------------------------------------------------- the verdicts


def test_a_prompt_that_names_a_key_is_that_ticket():
    out = JM.verdict("rdsd-77: add the missing column", ROWS)
    assert out["verdict"] == "named" and out["ticket"] == "RDSD-77" and out["next"] == "continue"


def test_a_prompt_that_fits_an_open_ticket_is_assumed_there_with_the_runners_up_as_choices():
    out = JM.verdict("the committed points on the sprint chart look wrong again", ROWS, active="RDSD-101")
    assert out["verdict"] == "match" and out["ticket"] == "RDSD-118" and out["next"] == "ask-and-continue"
    assert out["candidates"][0]["key"] == "RDSD-118" and out["candidates"][0]["score"] >= JM.MATCH_SCORE
    ask = out["ask"]
    assert ask.startswith('ad-state ask "This reads like RDSD-118 (')
    assert "--kind ticket" in ask and "--assume RDSD-118" in ask
    assert "--choice RDSD-118" in ask and "--choice new --choice none" in ask
    assert "RDSD-101" in ask, "the active ticket stays on offer as a choice"


def test_the_active_ticket_keeps_the_work_when_it_fits_as_well_as_anything():
    out = JM.verdict("rename the unused measures", ROWS, active="RDSD-101")
    assert out["verdict"] == "active" and out["next"] == "continue" and out["ticket"] == "RDSD-101"


def test_a_prompt_the_active_ticket_has_nothing_to_do_with_is_not_charged_to_it():
    """The friction this exists for: a one-off prompt silently landing on whatever was open."""
    out = JM.verdict("why does the Teradata history table lack the status column", ROWS, active="RDSD-101")
    assert out["verdict"] == "match" and out["ticket"] == "RDSD-77"


def test_nothing_fits_is_untracked_under_optional_and_a_stop_under_required():
    loose = JM.verdict("rotate the fleet's logs faster", ROWS, active="RDSD-101")
    assert loose["verdict"] == "none" and loose["next"] == "ask-and-continue" and loose["ticket"] == ""
    assert "--assume none" in loose["ask"] and "--choice new --choice none" in loose["ask"]
    strict = JM.verdict("rotate the fleet's logs faster", ROWS, policy="required")
    assert strict["next"] == "ask-and-stop" and "--assume" not in strict["ask"]
    assert JM.verdict("anything", [])["verdict"] == "none", "no open tickets is `none`, not a crash"


def test_the_operators_new_becomes_jira_create_on_the_next_turn():
    out = JM.verdict("rotate the fleet's logs faster", ROWS, active=None, last_answer="new")
    assert out["verdict"] == "create" and out["next"] == "jira-create"
    # ... unless a ticket is active by then: `new` was answered and acted on already.
    assert JM.verdict("rotate the fleet's logs faster", ROWS, active="RDSD-5", last_answer="new")["verdict"] != "create"


def test_stop_words_and_the_words_every_ticket_shares_do_not_make_a_match():
    assert JM.tokens("Update the Jira ticket for the report") == set()
    assert JM.tokens("Committed points wrong on the sprint chart") == {"committed", "point", "wrong", "sprint", "chart"}
    assert JM.verdict("please update the ticket", ROWS)["verdict"] == "none"


# ------------------------------------------------------------------ ad-state: the answer is the move


def _init(tmp_path, monkeypatch, **state):
    monkeypatch.chdir(tmp_path)
    os.makedirs(".agent")
    body = {"project": "RDSD", "phase": "querying", "active_ticket": "RDSD-101", "open_questions": [], "artifacts": []}
    body.update(state)
    with open(os.path.join(".agent", "state.json"), "w", encoding="utf-8") as f:
        json.dump(body, f)
    return os.path.join(".agent", "state.json")


def _state(p):
    return json.load(open(p, encoding="utf-8"))


def test_an_assumed_ticket_question_moves_the_work_and_the_operator_can_move_it_back(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch)
    rc = cli_state.main(["ask", "This reads like RDSD-118. Track it there?", "--kind", "ticket",
                         "--choice", "RDSD-118", "--choice", "RDSD-101", "--choice", "new", "--choice", "none",
                         "--assume", "RDSD-118"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "active_ticket: RDSD-118" in out and "ticket_was: RDSD-101" in out and "next: continue" in out
    st = _state(p)
    assert st["active_ticket"] == "RDSD-118" and st["phase"] == "querying", "assumed, so nothing blocks"
    q = st["open_questions"][0]
    assert q["kind"] == "ticket" and q["ticket"] == "RDSD-118" and q["blocking"] is False

    assert cli_state.main(["answer", q["id"], "RDSD-101"]) == 0
    out = capsys.readouterr().out
    assert "ticket_answer: moved" in out and "active_ticket: RDSD-101" in out
    st = _state(p)
    assert st["active_ticket"] == "RDSD-101" and st["open_questions"] == []


def test_answering_none_untracks_and_new_hands_the_next_turn_to_jira_create(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch, active_ticket=None)
    assert cli_state.main(["ask", "No open ticket matches. Track it under one?", "--kind", "ticket",
                           "--choice", "RDSD-118", "--choice", "new", "--choice", "none", "--assume", "none"]) == 0
    qid = _state(p)["open_questions"][0]["id"]
    assert cli_state.main(["answer", qid, "new"]) == 0
    out = capsys.readouterr().out
    assert "next: jira-create" in out and "ticket_answer: create" in out
    assert _state(p)["active_ticket"] is None, "`new` changes nothing until jira-create makes the key"
    assert JM.last_ticket_answer(_state(p)) == "new"

    assert cli_state.main(["ask", "Track it?", "--kind", "ticket", "--choice", "new", "--choice", "none",
                           "--assume", "RDSD-118"]) == 0
    assert _state(p)["active_ticket"] == "RDSD-118"
    qid = _state(p)["open_questions"][0]["id"]
    assert cli_state.main(["answer", qid, "none"]) == 0
    assert "ticket_answer: untracked" in capsys.readouterr().out
    assert _state(p)["active_ticket"] is None


def test_a_blocking_ticket_question_blocks_and_its_answer_unblocks_onto_the_key(tmp_path, monkeypatch, capsys):
    """`ticket_policy: required`: the printed ask has no --assume, so the agent stops; the key the
    operator answers is where the work resumes."""
    p = _init(tmp_path, monkeypatch, active_ticket=None)
    assert cli_state.main(["ask", "Which ticket?", "--kind", "ticket", "--choice", "RDSD-118", "--choice", "new"]) == 0
    st = _state(p)
    assert st["phase"] == "blocked" and st["active_ticket"] is None
    assert cli_state.main(["answer", st["open_questions"][0]["id"], "rdsd-118"]) == 0
    st = _state(p)
    assert st["active_ticket"] == "RDSD-118" and st["phase"] == "querying"


def test_kind_ticket_and_followup_are_refused_together(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    assert cli_state.main(["ask", "x?", "--kind", "ticket", "--followup"]) == 2


# ----------------------------------------------------------------------- ad-jira match, end to end


def test_ad_jira_match_reads_the_board_narrows_to_the_project_and_prints_the_ask_line(tmp_path, monkeypatch, capsys):
    _init(tmp_path, monkeypatch, active_ticket="RDSD-101")
    with open("AGENTS.md", "w", encoding="utf-8") as f:
        f.write("# Project\n\n- jira_project: RDSD\n- ticket_policy: optional\n")
    seen = {}

    def fake_board(cfg, force):
        seen["force"] = force
        return {"rows": ROWS, "cached": True, "age_s": 41, "jql": "assignee = currentUser()"}

    monkeypatch.setattr(cli_jira, "_board_rows", fake_board)
    assert cli_jira.main(["match", "the", "committed", "points", "on", "the", "sprint", "chart", "look", "wrong"]) == 0
    out = capsys.readouterr().out
    assert "verdict: match" in out and "next: ask-and-continue" in out and "ticket: RDSD-118" in out
    assert "tickets: 3" in out, "DATAENG-9 is another project's"
    assert 'ask: ad-state ask "This reads like RDSD-118' in out and "--assume RDSD-118" in out
    assert "candidates[3]{key,status,score,shared,summary}" in out and "cache, 41s old" in out
    assert seen["force"] is False

    assert cli_jira.main(["match", "--all", "--refresh", "somebody", "else's", "problem"]) == 0
    out = capsys.readouterr().out
    assert "ticket: DATAENG-9" in out and "tickets: 4" in out and seen["force"] is True


def test_ad_jira_match_without_a_board_still_prints_a_usable_ask(tmp_path, monkeypatch, capsys):
    from agentdata.fleet import board as B

    _init(tmp_path, monkeypatch)
    with open("AGENTS.md", "w", encoding="utf-8") as f:
        f.write("# Project\n\n- jira_project: RDSD\n- ticket_policy: required\n")

    def down(cfg, force):
        raise B.BoardError("Jira is not reachable: no token", "`ad-jira whoami` checks the token")

    monkeypatch.setattr(cli_jira, "_board_rows", down)
    assert cli_jira.main(["match", "anything", "at", "all"]) == 2
    out = capsys.readouterr().out
    assert "refused: board_unreachable" in out and "next: ask-and-stop" in out
    assert 'ask: ad-state ask "Track this under a ticket?" --kind ticket --choice new --choice none' in out
    with pytest.raises(SystemExit):
        cli_jira.main(["match"])                  # no words is argparse's usage error


def test_the_router_runs_the_match_and_follows_next():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    three = text.split("\n3. ")[1].split("\n4. ")[0]
    assert "ad-jira match" in three and "also when `active_ticket` is set" in three
    for word in ("ask-and-continue", "ask-and-stop", "jira-create", "--kind ticket"):
        assert word in three, word
    assert "Never guess a key yourself" in three
