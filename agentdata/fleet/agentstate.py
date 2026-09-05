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


class Fold:
    """The accumulators `classify` reads. One object so the whole-stream and the event-by-event
    callers cannot drift: #97 has to know *when* a state changed, not only what it is now, and a
    second implementation of these rules would eventually disagree with this one about whether an
    agent needs the human -- which is the only question the fleet exists to answer.
    """

    __slots__ = ("phase", "ticket", "session", "premium", "turns", "last_text", "denied",
                 "frictions", "questions", "approvals", "errors", "turn_open", "seen", "last_ts")

    def __init__(self) -> None:
        self.phase = self.ticket = self.session = self.last_text = ""
        self.premium = 0.0
        self.turns = self.seen = 0
        self.denied: list[dict] = []
        self.frictions: list[dict] = []
        self.questions: list[str] = []
        self.approvals: list[dict] = []
        self.errors: list[dict] = []
        self.turn_open = False
        self.last_ts = ""

    def add(self, ev: dict) -> "Fold":
        kind, data = ev.get("kind"), ev.get("data") or {}
        self.seen += 1
        if ev.get("ts"):
            self.last_ts = str(ev["ts"])
        if ev.get("ticket"):
            self.ticket = ev["ticket"]
        if kind in ("exited", "error"):
            # A standalone `if`, not part of the chain below, because these two must both close the
            # turn *and* be classified. A process that ended has no turn in flight, whatever the
            # last `turn_start` implied -- and without this a crashed agent reads as `running`
            # forever, since its turn never ended and `turn_open` outranks everything in
            # `classify`. Reporting a corpse as working is the exact failure the reaper exists to
            # prevent, and the fold was quietly undoing it.
            self.turn_open = False
        if kind == "turn_started":
            self.turn_open = True
            # A new turn supersedes what the last one was refused, but not what it asked: a
            # question and an approval both outlive the turn that raised them.
            self.denied = []
        elif kind == "turn_ended":
            self.turn_open = False
            self.turns += 1
        elif kind == "assistant_text":
            self.last_text = str(data.get("text") or "").strip()
        elif kind == "denied":
            self.denied.append(ev)
        elif kind == "friction":
            self.frictions.append(ev)
        elif kind == "question_opened":
            self.questions.append(str(data.get("question") or ""))
        elif kind == "phase_changed":
            self.phase = str(data.get("to") or "")
        elif kind == "session_id":
            self.session = str(data.get("session") or "")
        elif kind == "cost":
            try:
                self.premium = max(self.premium, float(data.get("premium_requests") or 0))
            except (TypeError, ValueError):
                pass
        elif kind == "needs_approval":
            self.approvals.append(ev)
        elif kind == "approval_resolved":
            self.approvals = []
        elif kind == "error":
            self.errors.append(ev)
        return self


def classify(f: Fold, *, live: bool = False) -> dict:
    """(state, why, plus the facts a tile shows). `live` is "a process is running right now".

    Ordering matters and is deliberate: a blocked agent that also asked a question is *blocked*,
    because the friction file says what would unblock it and the question does not.
    """
    if live or f.turn_open:
        state, why = "running", "a turn is in progress"
    elif f.errors:
        code = str((f.errors[-1].get("data") or {}).get("exit_code", "non-zero exit"))
        state, why = "error", f"the last turn exited {code}"
    elif f.approvals:
        state, why = "waiting_approval", "a write is waiting for one click"
    elif f.frictions:
        unblock = (f.frictions[-1].get("data") or {}).get("unblock") or ""
        state, why = "blocked", unblock or "a skill wrote a friction log and stopped"
    elif f.phase == "blocked":
        # An agent asking a question sets `phase=blocked --question "…"` in one command, so the
        # question is usually right here. Preferring it keeps the state honest -- the agent said it
        # was blocked -- while giving the operator the sentence they can act on instead of
        # "something is blocked, go and look".
        state = "blocked"
        why = f.questions[-1] if f.questions else "state.json says the phase is blocked"
    elif f.denied:
        message = (f.denied[-1].get("data") or {}).get("message") or ""
        state, why = "needs_human", message or "a tool the agent may not run was refused"
    elif f.questions:
        state, why = "needs_human", f.questions[-1]
    elif f.last_text.endswith(_ASK_ENDINGS):
        state, why = "needs_human", f.last_text[-200:]
    elif f.phase in TERMINAL_PHASES:
        state, why = "done", f"phase is {f.phase}"
    elif not f.seen:
        state, why = "starting", "no events yet"
    else:
        state, why = "idle", "the last turn ended with nothing outstanding"

    return {"state": state, "why": why, "phase": f.phase, "ticket": f.ticket,
            "session": f.session, "turns": f.turns, "premium_requests": round(f.premium, 2),
            "denied": len(f.denied), "questions": len(f.questions),
            "frictions": len(f.frictions), "at": f.last_ts}


def derive(events: list[dict], *, live: bool = False) -> dict:
    """What state this agent is in, from its whole stream."""
    fold = Fold()
    for ev in events:
        fold.add(ev)
    return classify(fold, live=live)


def transitions(events: list[dict]) -> list[dict]:
    """Every moment the state *changed*, in order, with the event that changed it.

    This is what a notifier needs and `derive` cannot give it. Notifying on events would mean a
    toast per `tool_call`; notifying on the current state would mean a toast every time anyone
    looked. A transition happens once, when it happens.
    """
    fold, previous, out = Fold(), "starting", []
    for ev in events:
        now = classify(fold.add(ev))
        if now["state"] != previous:
            out.append({**now, "from": previous, "seq": ev.get("seq", 0), "kind": ev.get("kind")})
            previous = now["state"]
    return out


def needs_the_human(state: str) -> bool:
    """The one predicate the notifier and the dashboard badge share."""
    return state in ("waiting_approval", "needs_human", "blocked", "error")
