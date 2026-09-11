"""`.agent/state.json` — machine-owned session state. Only `ad-state` (skill state-update) writes it: validated keys and
phases, `last_updated` stamped, artifacts pruned, UTF-8 without BOM, atomic. Reads tolerate whatever an earlier
PowerShell one-liner wrote (BOM / UTF-16) and rewrite the file clean."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from . import textio

PATH = os.path.join(".agent", "state.json")
PHASES = ("idle", "triaged", "querying", "optimizing", "validating", "documenting", "pr_open", "blocked", "done", "closed", "merged")
STRING_KEYS = ("active_ticket", "branch", "pr_url", "confluence_url", "project")
TOOL_KEYS = ("doctor_verified", "pncli_verified", "graph_approved")
ARTIFACT_DAYS = 7
NULLS = ("null", "none", "")
# Files a human handed to this session: `.agent/in/<KEY>/<name>`, put there by a click on the fleet's
# Downloads tray (#132) and recorded here so the agent finds them on its next turn without being told.
# They are *not* pruned the way artifacts are: an artifact is something the run produced and can produce
# again, an input is something a person went and fetched, and dropping it from the list after a week
# would leave a file on disk that nothing points at. The cap is the only bound, generous enough that
# nobody clicking attach reaches it in a project's life, and it drops the oldest rather than refusing
# the newest -- the file itself stays under `.agent/in/` either way.
INPUTS_CAP = 200
# Questions the operator has answered, kept so the next turn can read what it already asked and
# was told. Bounded because it is a convenience, not a record -- `events.norm.jsonl` is the record.
ANSWERED_CAP = 50


class StateError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


# ------------------------------------------------------------------- questions, as records (#165)
#
# `open_questions` used to be a list of strings, and a string is the wrong shape for what the agent
# is actually doing: it has no id to answer, no choices to pick from, no way to say *I need a file*,
# and no way to distinguish "two readings lead to different work, so I stopped" from "I assumed the
# obvious thing and carried on". It is a list of records now -- and a plain string is still accepted
# and still read, because a skill written before this change must keep working and history is never
# rewritten.
#
# A record: {id, q, choices[], default, want, about, blocking, asked, answer, answered}


def question_text(q) -> str:
    """The question itself, whichever shape it is stored in."""
    return str(q.get("q") or "") if isinstance(q, dict) else str(q or "")


def is_blocking(q) -> bool:
    """Does this question stop the agent?

    A bare string blocks, because every question written before #165 was one the agent stopped on.
    A record blocks unless it carries an assumption -- that is the difference between *stop* and
    *urge*, and it is the agent's to choose per question under one rule: two readings that lead to
    different work block; a safe, reversible default does not.
    """
    if not isinstance(q, dict):
        return True
    if is_answered(q):
        return False
    return bool(q.get("blocking", True))


def is_answered(q) -> bool:
    return isinstance(q, dict) and bool(q.get("answered"))


def next_question_id(*lists: list) -> str:
    """`q1`, `q2`, … per session. Short enough to type at a terminal, which is where they get typed.

    Every list that has ever held a question is consulted, not only the open one. An id that got
    reused after its question was answered would mean two different things in one session -- and the
    operator answering `q1` from a tile drawn a moment earlier would answer the wrong one.
    """
    used = {str(q.get("id") or "") for existing in lists for q in existing if isinstance(q, dict)}
    n = 1
    while f"q{n}" in used:
        n += 1
    return f"q{n}"


def stamp_for(today: str | None) -> str:
    return today or now_iso()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path: str = PATH) -> dict:
    if not os.path.isfile(path):
        raise StateError(f"{path} not found", hint="run `ad-setup --project .` (writes the stub), then retry")
    try:
        data = textio.read_json(path, "state.json")
    except ValueError as e:
        raise StateError(str(e), hint="restore the file from git, or delete it and run `ad-setup --project .`") from None
    if not isinstance(data, dict):
        raise StateError(f"{path}: top level must be an object", hint="delete it and run `ad-setup --project .`")
    return data


def apply(state: dict, sets: dict, *, artifacts: list[dict] | None = None, questions: list[str] | None = None,
          clear_questions: bool = False, tools: dict | None = None, inputs: list[str] | None = None,
          asks: list[dict] | None = None, answers: dict | None = None,
          today: str | None = None) -> dict:
    """Validate and merge. `sets` keys: phase, active_ticket, branch, pr_url, confluence_url, project."""
    for k, v in sets.items():
        if k == "phase":
            if v not in PHASES:
                raise StateError(f"phase {v!r} is not allowed", hint="one of " + " | ".join(PHASES))
            state["phase"] = v
        elif k in STRING_KEYS:
            state[k] = None if str(v).strip().lower() in NULLS else str(v)
        else:
            raise StateError(f"unknown state key {k!r}", hint="allowed: phase, " + ", ".join(STRING_KEYS) + "; artifacts via --artifact, questions via --question")
    if tools:
        t = state.setdefault("tools", {})
        for k, v in tools.items():
            if k not in TOOL_KEYS:
                raise StateError(f"unknown tools key {k!r}", hint="allowed: " + ", ".join(TOOL_KEYS))
            t[k] = None if str(v).strip().lower() in NULLS else str(v)
    if clear_questions:
        state["open_questions"] = []
        state.pop("blocked_from", None)
    if questions:
        oq = state.setdefault("open_questions", [])
        existing = {question_text(q) for q in oq}
        oq += [q for q in questions if q and question_text(q) not in existing]
    if asks:
        oq = state.setdefault("open_questions", [])
        for record in asks:
            record = dict(record)
            record.setdefault("id", next_question_id(oq, state.get("answered_questions") or []))
            record.setdefault("asked", stamp_for(today))
            if any(question_text(q) == question_text(record) for q in oq):
                continue
            oq.append(record)
        # A blocking question is what stops the agent, so the phase it came *from* is remembered
        # here: that is what `answer` puts back, and it is why answering can unblock at all. A
        # non-blocking one -- an assumption the agent stated and continued on -- changes no phase,
        # and must not steal the one a later blocking question will need.
        if any(is_blocking(q) for q in state.get("open_questions") or []):
            if state.get("phase") != "blocked":
                state.setdefault("blocked_from", state.get("phase") or "idle")
            state["phase"] = "blocked"
    if answers:
        oq = state.get("open_questions") or []
        for qid, text in answers.items():
            for record in oq:
                if isinstance(record, dict) and str(record.get("id") or "") == str(qid):
                    record["answer"] = text
                    record["answered"] = stamp_for(today)
        # An answered question leaves `open_questions` and lands here rather than vanishing. Two
        # reasons: the event stream needs the answer's text to report it, and the next turn should
        # be able to read what it already asked and was told without asking again.
        done = state.setdefault("answered_questions", [])
        done += [q for q in oq if is_answered(q)]
        del done[:max(0, len(done) - ANSWERED_CAP)]
        state["open_questions"] = [q for q in oq if not is_answered(q)]
        # When nothing blocking is left, the phase goes back to where the question interrupted it.
        # That is the whole of "a reply unblocks": it is still `ad-state` writing the file, and it
        # is still deliberate -- an answer, not a side effect of somebody typing anything at all.
        if not any(is_blocking(q) for q in state["open_questions"]):
            back = state.pop("blocked_from", "")
            if state.get("phase") == "blocked" and back:
                state["phase"] = back
    # Normalised to one spelling, for the reason an artifact path is: `.agent\in\X\y.md` and
    # `.agent/in/X/y.md` are one file, and two spellings of it would be listed, read and reported
    # twice. An empty value is skipped rather than refused, exactly as an empty `--question` is, and
    # the key is only materialised when there is something to put in it.
    wanted = [p for p in (textio.norm_path(str(i).strip()) for i in inputs or []) if p]
    if wanted:
        current = state.setdefault("inputs", [])
        for item in wanted:
            if item not in current:
                current.append(item)
        del current[:max(0, len(current) - INPUTS_CAP)]
    stamp = today or now_iso()
    if artifacts:
        arts = state.setdefault("artifacts", [])
        for a in artifacts:
            arts.append({"path": textio.norm_path(a["path"]), "what": a.get("what", ""), "run_id": a.get("run_id", ""), "added": stamp[:10]})
    state["artifacts"] = prune(state.get("artifacts") or [], stamp[:10])
    # open questions persist until --clear-questions: leaving a blocked phase is a deliberate act, never a side effect
    state["last_updated"] = stamp
    return state


def prune(artifacts: list, today: str) -> list:
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=ARTIFACT_DAYS)).strftime("%Y-%m-%d")
    out = []
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        added = str(a.get("added") or today)[:10]
        if added >= cutoff:
            out.append(a)
    return out


def save(state: dict, path: str = PATH) -> str:
    """Write the state, and tell the fleet if one is watching.

    `ad-state` stays the only writer of `state.json`; the fleet only ever reads it. The emit below
    is the reverse direction and is additive: when this process was launched by a supervisor -- the
    two `AGENTDATA_FLEET_*` markers -- the change is appended to that agent's normalized stream so
    the dashboard sees a phase change immediately instead of discovering it on the next poll.

    Outside a fleet the behaviour is byte-identical to before: no markers, no emit, and a failure to
    emit never fails the save. The state file is the contract; the event is a courtesy.
    """
    previous = load(path) if os.path.exists(path) else {}
    written = textio.write_json(path, state)
    _emit_to_fleet(previous, state)
    return written


def _emit_to_fleet(previous: dict, current: dict) -> None:
    from .fleet.registry import AGENT_ENV, FLEET_DIR_ENV

    name = os.environ.get(AGENT_ENV)
    if not name or not os.environ.get(FLEET_DIR_ENV):
        return
    try:
        from .fleet import events as E

        E.append(name, E.from_state(previous, current, name))
    except Exception:  # noqa: BLE001 - a dashboard that misses an event must never fail a save
        from .log import debug_exc

        debug_exc("fleet emit")


def line(state: dict) -> str:
    return f"state: phase={state.get('phase')} ticket={state.get('active_ticket')}"
