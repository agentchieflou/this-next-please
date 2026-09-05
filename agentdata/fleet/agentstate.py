"""What state an agent is in, derived from its normalized events and nothing else.

Deterministic on purpose. The dashboard colours a tile from this, the notifier decides whether to
raise a toast from this, and both must be able to replay history and get the same answer -- so the
rule is a fold over events, never a flag someone remembered to set.

The one rule the issue asked for that could not be written as specified: `needs_human` was to come
from "the catalogued permission-request event". There is no such event. The CLI attempts the tool,
refuses it, reports `error.code == "denied"` on `tool.execution_complete`, and the turn still exits
0 (docs/fleet-spike.md). So a denial is the signal, and it is a better one -- it names the tool the
agent wanted rather than a generic prompt.
"""
from __future__ import annotations

# Exactly what `derive` can return -- a state listed here that the fold never produces is a tile
# colour nobody will ever see, and a state it produces that is missing here is an unhandled case.
STATES = ("starting", "running", "waiting_approval", "needs_human", "blocked", "idle", "done",
          "error")

# `?` is not enough on its own -- an assistant that says "shall I proceed?" is asking, one that
# writes "the ticket asks: is X true?" is quoting. The question has to be the last thing said.
_ASK_ENDINGS = ("?",)

TERMINAL_PHASES = ("pr_open", "done", "closed", "merged")


def derive(events: list[dict], *, live: bool = False) -> dict:
    """(state, why, plus the facts a tile shows). `live` is "a process is running right now".

    Ordering matters and is deliberate: a blocked agent that also asked a question is *blocked*,
    because the friction file says what would unblock it and the question does not.
    """
    phase = ""
    ticket = ""
    session = ""
    premium = 0.0
    turns = 0
    last_text = ""
    denied: list[dict] = []
    frictions: list[dict] = []
    questions: list[str] = []
    approvals: list[dict] = []
    errors: list[dict] = []
    turn_open = False

    for ev in events:
        kind, data = ev.get("kind"), ev.get("data") or {}
        if ev.get("ticket"):
            ticket = ev["ticket"]
        if kind == "turn_started":
            turn_open = True
            # A new turn supersedes what the last one was waiting for.
            denied, questions, approvals = [], questions, approvals
        elif kind == "turn_ended":
            turn_open = False
            turns += 1
        elif kind == "assistant_text":
            last_text = str(data.get("text") or "").strip()
        elif kind == "denied":
            denied.append(ev)
        elif kind == "friction":
            frictions.append(ev)
        elif kind == "question_opened":
            questions.append(str(data.get("question") or ""))
        elif kind == "phase_changed":
            phase = str(data.get("to") or "")
        elif kind == "session_id":
            session = str(data.get("session") or "")
        elif kind == "cost":
            try:
                premium = max(premium, float(data.get("premium_requests") or 0))
            except (TypeError, ValueError):
                pass
        elif kind == "needs_approval":
            approvals.append(ev)
        elif kind == "approval_resolved":
            approvals = []
        elif kind == "error":
            errors.append(ev)

    if live or turn_open:
        state, why = "running", "a turn is in progress"
    elif errors:
        state, why = "error", str((errors[-1].get("data") or {}).get("exit_code", "non-zero exit"))
        why = f"the last turn exited {why}"
    elif approvals:
        state, why = "waiting_approval", "a write is waiting for one click"
    elif frictions:
        unblock = (frictions[-1].get("data") or {}).get("unblock") or ""
        state, why = "blocked", unblock or "a skill wrote a friction log and stopped"
    elif phase == "blocked":
        state, why = "blocked", "state.json says the phase is blocked"
    elif denied:
        message = (denied[-1].get("data") or {}).get("message") or ""
        state, why = "needs_human", message or "a tool the agent may not run was refused"
    elif questions:
        state, why = "needs_human", questions[-1]
    elif last_text.endswith(_ASK_ENDINGS):
        state, why = "needs_human", last_text[-200:]
    elif phase in TERMINAL_PHASES:
        state, why = "done", f"phase is {phase}"
    elif not events:
        state, why = "starting", "no events yet"
    else:
        state, why = "idle", "the last turn ended with nothing outstanding"

    return {"state": state, "why": why, "phase": phase, "ticket": ticket, "session": session,
            "turns": turns, "premium_requests": round(premium, 2),
            "denied": len(denied), "questions": len(questions), "frictions": len(frictions)}


def needs_the_human(state: str) -> bool:
    """The one predicate the notifier and the dashboard badge share."""
    return state in ("waiting_approval", "needs_human", "blocked", "error")
