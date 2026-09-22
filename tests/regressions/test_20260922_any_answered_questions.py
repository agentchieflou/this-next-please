"""2026-09-22, the desk in Chrome (`ad-fleet serve --open`): a tile counted twelve questions, all answered.

Symptom:

    "Agents are retaining historical questions that have already been answered and presenting them
    as if they haven't been answered. One of our agents in fleet is showing that we have 12
    questions, but all of them have been answered."

The tile's count was a fold of the event stream, and only `question_answered` -- which only
`ad-state answer` emits -- took a question off it. `--clear-questions` emitted nothing, bare
`--question` strings had no id to answer, and a console session is one run for its whole life, so
twelve ask-and-clear cycles in one console read `needs_human · 12 questions` while `state.json` had
`open_questions: []`.

Issue: https://github.com/agentchieflou/this-next-please/issues/231
"""
from __future__ import annotations
import copy

from agentdata import state as ST
from agentdata.fleet import agentstate as A, events as E


def _twelve_ask_and_clear_cycles() -> tuple[list[dict], dict]:
    """What `friction-log` and the state-update skill had an agent do, twelve times in one console."""
    state = {"phase": "querying"}
    stream = [E.event("luna", "started", {"pid": 1, "kind": "console"})]
    for n in range(1, 13):
        asked = ST.apply(copy.deepcopy(state), {"phase": "blocked"}, questions=[f"what unblocks step {n}?"])
        stream += E.from_state(state, asked, "luna")
        cleared = ST.apply(copy.deepcopy(asked), {"phase": "querying"}, clear_questions=True)
        stream += E.from_state(asked, cleared, "luna")
        stream.append(E.event("luna", "turn_ended", {"turn": str(n)}))
        state = cleared
    return stream, state


def test_twelve_questions_asked_and_cleared_in_one_console_run_read_none():
    stream, state = _twelve_ask_and_clear_cycles()
    assert state["open_questions"] == []
    out = A.derive(stream, live=True)
    assert out["questions"] == 0 and out["asked"] == []
    assert out["state"] != "needs_human", out["why"]


def test_a_stream_folded_before_the_fix_is_healed_by_state_json():
    """The laptop's stream already holds the twelve opens with no clears, and its cursor has seen
    `open_questions` empty, so no new event will ever arrive. `state.json` settles it."""
    stream, state = _twelve_ask_and_clear_cycles()
    before_the_fix = [ev for ev in stream if ev["kind"] != "question_cleared"]
    assert A.derive(before_the_fix, live=True)["questions"] == 12, "the symptom, as the laptop has it"
    healed = A.derive(before_the_fix, live=True, open_questions=state["open_questions"])
    assert healed["questions"] == 0 and healed["state"] != "needs_human"
