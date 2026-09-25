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
                 "frictions", "questions", "approvals", "errors", "turn_open", "seen", "last_ts",
                 "asked", "files", "from_state", "subagents", "launch", "replied")

    def __init__(self) -> None:
        self.phase = self.ticket = self.session = self.last_text = ""
        self.premium = 0.0
        self.turns = self.seen = 0
        self.denied: list[dict] = []
        self.frictions: list[dict] = []
        self.questions: list[str] = []
        self.asked: list[dict] = []
        # The keys of the questions `ad-state` reported, which `state.json` therefore has the last
        # word on (#231). The fleet's own questions -- "Copilot is no longer logged in" -- are not
        # in `state.json` at all, and it must not close them.
        self.from_state: set[str] = set()
        self.files: list[str] = []
        self.approvals: list[dict] = []
        self.errors: list[dict] = []
        self.turn_open = False
        self.last_ts = ""
        # The sub-agents started and not yet ended, id -> agent name (#402). From the SDK docs, not
        # measured; a count only, which no state and no notification reads.
        self.subagents: dict[str, str] = {}
        # The newest run's `--model`/`--effort` (#492 records them on `started`) and whether it has
        # replied: a run that ended before its first reply, launched with an effort, may have been
        # refused that pair by the CLI (#493).
        self.launch: dict = {}
        self.replied = False

    def add(self, ev: dict) -> "Fold":
        kind, data = ev.get("kind"), ev.get("data") or {}
        self.seen += 1
        if ev.get("ts"):
            self.last_ts = str(ev["ts"])
        if ev.get("ticket"):
            self.ticket = ev["ticket"]
        if kind in ("exited", "error"):
            # What the run edited, kept so the tile can compare it with what it was *given* (#168).
            # The CLI reports this on the way out; nothing else has to be written for the report.
            self.files = [str(f) for f in (data.get("files_modified") or [])]
            # A standalone `if`, not part of the chain below, because these two must both close the
            # turn *and* be classified. A process that ended has no turn in flight, whatever the
            # last `turn_start` implied -- and without this a crashed agent reads as `running`
            # forever, since its turn never ended and `turn_open` outranks everything in
            # `classify`. Reporting a corpse as working is the exact failure the reaper exists to
            # prevent, and the fold was quietly undoing it.
            self.turn_open = False
        if kind in ("started", "exited", "error"):
            # A new run, or a process that ended: no sub-agent of it is still running (#402).
            self.subagents = {}
        if kind == "started":
            self.launch = {"model": str(data.get("model") or ""), "effort": str(data.get("effort") or "")}
            self.replied = False
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
            self.replied = True
        elif kind == "denied":
            self.denied.append(ev)
        elif kind == "friction":
            self.frictions.append(ev)
        elif kind == "question_opened":
            # The record, not only the sentence (#165): `classify` has to tell a question the agent
            # stopped on from an assumption it stated and carried on with, and the tile has to show
            # the choices. `question` keeps meaning the sentence, so an older event still folds.
            record = {"id": str(data.get("id") or ""),
                      "q": str(data.get("question") or ""),
                      "choices": list(data.get("choices") or []),
                      "default": str(data.get("default") or ""),
                      "want": str(data.get("want") or "decision"),
                      "assume": str(data.get("assume") or ""),
                      "blocking": bool(data.get("blocking", True))}
            # Replaced by id, never appended twice. One state change is reported by two writers on
            # purpose -- `ad-state` emits it the moment it saves, so the dashboard does not wait for
            # a poll, and `events.refresh` diffs the same change again against its own cursor -- and
            # the stream is additive, so both stay. A fold that appended showed the operator one
            # question twice and asked them to answer it twice (#169).
            for i, existing in enumerate(self.asked):
                if (existing["id"] or existing["q"]) == (record["id"] or record["q"]):
                    self.asked[i] = record
                    break
            else:
                self.asked.append(record)
            # `events._q_payload` always writes `want`; the fleet's own questions never carry it.
            # That is how a question from `state.json` is told apart in a stream written before
            # anything marked it.
            if "want" in data:
                self.from_state.add(record["id"] or record["q"])
            self.questions = [q["q"] for q in self.asked]
        elif kind in ("question_answered", "question_cleared"):
            # An answer and a clear both close the question; only the first is an answer, and
            # nothing here needs to know which. `questions` is rebuilt from `asked` rather than
            # edited beside it: a question replaced by id used to leave its old sentence behind,
            # and `blocking_questions` fell back to that sentence once `asked` emptied (#231).
            qid, text = str(data.get("id") or ""), str(data.get("question") or "")
            self.asked = [q for q in self.asked
                          if (q["id"] or q["q"]) != (qid or text)]
            self.questions = [q["q"] for q in self.asked]
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
        elif kind == "subagent_started":
            self.subagents[str(data.get("id") or "")] = str(data.get("agent") or "")
        elif kind == "subagent_ended":
            self.subagents.pop(str(data.get("id") or ""), None)
        return self

    def reconcile(self, open_questions: list) -> "Fold":
        """`state.json` is what is open; the stream is what happened (#231).

        A question `ad-state` reported that `state.json` no longer lists is closed, however it was
        closed. This heals a tile that folded a clear before `question_cleared` existed -- the
        cursor has already seen that `open_questions` emptied, so no new event will ever arrive to
        say so. A question `state.json` lists that this run never opened is *not* added: it is
        usually one the operator has just answered from the tile, in the turn that records the
        answer, and drawing it again with an empty box asked them to answer it twice (#169).
        """
        from .events import _q_key

        open_now = {_q_key(q) for q in open_questions or []}
        self.asked = [q for q in self.asked
                      if (q["id"] or q["q"]) not in self.from_state or (q["id"] or q["q"]) in open_now]
        self.questions = [q["q"] for q in self.asked]
        return self


# A friction log says how much it hurts. Until #165 nothing read it, so a `nit` stopped an agent
# exactly as hard as a `blocker` -- one tile, one red chip, one interruption, for a note somebody
# left for later. Only these two fold as `blocked`.
BLOCKING_SEVERITIES = ("blocker", "friction", "")


def blocking_frictions(f: "Fold") -> list[dict]:
    return [ev for ev in f.frictions
            if str((ev.get("data") or {}).get("severity") or "").strip().lower()
            in BLOCKING_SEVERITIES]


def blocking_questions(f: "Fold") -> list[dict]:
    """The open questions the agent actually stopped on."""
    return [q for q in f.asked if q.get("blocking", True)] or (
        [{"id": "", "q": q, "choices": [], "blocking": True} for q in f.questions] if not f.asked else [])


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
        if f.launch.get("effort") and not f.replied:
            # It never said a word, and it was launched with an effort: the CLI may have refused
            # that pair (#493, decision 15). Name the effort, and where to change it.
            why += (f" · ran with effort {f.launch['effort']} on "
                    f"{f.launch.get('model') or 'the CLI’s own model'} — if the CLI refused that "
                    "pair, pick another effort (m)")
    elif f.approvals:
        state, why = "waiting_approval", "a write is waiting for one click"
    elif blocking_frictions(f):
        data = blocking_frictions(f)[-1].get("data") or {}
        unblock = data.get("unblock") or ""
        state, why = "blocked", unblock or "a skill wrote a friction log and stopped"
    elif f.phase == "blocked":
        # An agent asking a question sets `phase=blocked --question "…"` in one command, so the
        # question is usually right here. Preferring it keeps the state honest -- the agent said it
        # was blocked -- while giving the operator the sentence they can act on instead of
        # "something is blocked, go and look".
        state = "blocked"
        open_now = blocking_questions(f)
        why = (open_now[-1]["q"] if open_now
               else (f.questions[-1] if f.questions else "state.json says the phase is blocked"))
    elif f.denied:
        message = (f.denied[-1].get("data") or {}).get("message") or ""
        state, why = "needs_human", message or "a tool the agent may not run was refused"
    elif blocking_questions(f):
        state, why = "needs_human", blocking_questions(f)[-1]["q"]
    elif f.asked and not blocking_questions(f):
        # Every open question is an assumption the agent stated and continued on. That is *not*
        # a state: the tile shows the assumption as a row the operator can overturn at leisure,
        # and the agent is doing exactly what it said it would. Falling through here is the
        # difference between "urge" and "stop", and it is the whole point of `--assume`.
        state, why = ("idle", "the last turn ended with nothing outstanding") \
            if not f.last_text.endswith(_ASK_ENDINGS) else ("needs_human", f.last_text[-200:])
    elif f.last_text.endswith(_ASK_ENDINGS):
        state, why = "needs_human", f.last_text[-200:]
    elif f.phase in TERMINAL_PHASES:
        state, why = "done", f"phase is {f.phase}"
    elif not f.seen:
        state, why = "starting", "no events yet"
    else:
        state, why = "idle", "the last turn ended with nothing outstanding"

    return {"state": state, "why": why, "phase": f.phase, "ticket": f.ticket,
            # The last thing the agent actually said, for a surface that has one line to spend on
            # it (#204's band). `why` answers "what does this need from me" and is empty of news
            # when the answer is "nothing"; this answers "what is it doing", which is what an idle
            # agent in a column of ten has to be able to say for itself.
            "last_said": f.last_text[-200:],
            "session": f.session, "turns": f.turns, "premium_requests": round(f.premium, 2),
            "denied": len(f.denied), "questions": len(blocking_questions(f)),
            "asked": [dict(q) for q in f.asked],
            "files_modified": list(f.files),
            "assumed": [dict(q) for q in f.asked if not q.get("blocking", True)],
            "frictions": len(f.frictions), "at": f.last_ts,
            # Live sub-agents (#402): none when no process runs, whatever the stream left open.
            "subagents": len(f.subagents) if live else 0}


def derive(events: list[dict], *, live: bool = False, open_questions: list | None = None) -> dict:
    """What state this agent is in, from its whole stream.

    The STATE is this module's; the SPEND is `spend.py`'s, and is overlaid here so that every
    caller of `derive` -- the tile, the history, the sessions list, the budget -- gets the one
    arithmetic rather than `Fold`'s per-agent high-water mark. `Fold` keeps its own mark because
    `classify` reads it while deciding, and because a fold that suddenly needed the whole stream
    twice would be a different shape for no gain.

    `open_questions` is the repo's own `state.json` list, when the caller has read it: the
    questions that file no longer lists are dropped before anything is classified (#231).
    """
    from . import spend as SPEND

    fold = Fold()
    for ev in events:
        fold.add(ev)
    if open_questions is not None:
        fold.reconcile(open_questions)
    out = classify(fold, live=live)
    folded = SPEND.fold(events)
    out["premium_requests"] = SPEND.total(folded)
    out["turns"] = SPEND.turns(folded)
    return out


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


def pending_tool(events: list[dict]) -> str:
    """When the tool call still waiting for its result started, or "" if nothing is waiting (#190).

    For a console, how *long* that has been is the only clue there is that the session is asking its
    operator something. The CLI emits no permission *request* event -- `docs/fleet-spike.md`
    measured that, and it is why `denied` is the only signal the fleet has, after the fact -- so a
    `y/n` waiting in a console looks exactly like a tool taking its time. The caller turns this
    stamp into an age and labels the sentence a guess; runbook row C2 replaces it with whatever the
    file really carries while a prompt is pending.
    """
    pending, at = "", ""
    for ev in events:
        kind, data = ev.get("kind"), ev.get("data") or {}
        if kind == "tool_call":
            pending, at = str(data.get("id") or ""), str(ev.get("ts") or "")
        elif kind == "tool_result" and str(data.get("id") or "") == pending:
            pending, at = "", ""
        elif kind in ("turn_ended", "exited", "error"):
            pending, at = "", ""
    return at if pending else ""


def needs_the_human(state: str) -> bool:
    """The one predicate the notifier and the dashboard badge share."""
    return state in ("waiting_approval", "needs_human", "blocked", "error")


STATE_ROLES: dict[str, str] = {
    "running": "running",
    "waiting_approval": "waiting",
    "needs_human": "human",
    "blocked": "human",
    "error": "human",
    "done": "done",
    "starting": "idle",
    "idle": "idle",
}
