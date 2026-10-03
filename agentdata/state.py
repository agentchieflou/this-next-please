"""`.agent/state.json` — machine-owned session state. Only `ad-state` (skill state-update) writes it: validated keys and
phases, `last_updated` stamped, artifacts pruned, UTF-8 without BOM, atomic. Reads tolerate whatever an earlier
PowerShell one-liner wrote (BOM / UTF-16) and rewrite the file clean."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from . import textio

PATH = os.path.join(".agent", "state.json")
# The shape of `state.json`, stamped on every write (friction scan 1.6, §3 item 6). 1 is everything
# before the number existed: questions as bare strings. 2: questions as records with ids, answered
# and superseded questions kept, and each question scoped to its ticket. A file stamped newer than
# this `ad-state` knows is refused rather than half-understood: a skill and the CLI that disagree
# about the file is the drift the scan found, and it should fail by name, not as a missing key.
SCHEMA = 2
# Working phases name what the agent is doing so a tile, a notification and `ad-fleet history` can
# say it: `researching` (a spike), `planning` (a report plan, a sort plan), `mapping` (the code
# graph), `editing` (code, TMDL, PBIR), `testing` (cover / regress), `deploying` (XMLA, Fabric, a
# refresh). Terminal ones (`agentdata/fleet/agentstate.TERMINAL_PHASES`) are unchanged.
PHASES = ("idle", "triaged", "researching", "planning", "mapping", "querying", "editing", "testing", "optimizing",
          "validating", "deploying", "documenting", "pr_open", "blocked", "done", "closed", "merged")
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
# A record: {id, q, choices[], default, want, about, blocking, asked, answer, answered, ticket, kind}
#
# `ticket` is the scope (friction scan 1.1): the ticket a question was asked under, `""` for untracked
# work, and absent on a record written before scopes existed -- which therefore still blocks every
# scope, exactly as it always did. A question asked on RDSD-1 stops RDSD-1's work and nothing else's.


def apply_ticket_answer(state: dict, text: str) -> str:
    """What an answer to a `kind: ticket` question does to `active_ticket` (#ticket-match).

    A key moves the work there; `none` (or `untracked`) makes it untracked; `new` changes nothing
    here, because the ticket does not exist yet -- the router hands the next turn to `jira-create`,
    which sets the key it made. Any other words are a remark, not a decision. Returns one word
    for the report: `moved`, `untracked`, `create` or `kept`.
    """
    from . import jira_match as JM

    key = JM.is_key(text)
    if key:
        state["active_ticket"] = key
        return "moved"
    if JM.is_none(text):
        state["active_ticket"] = None
        return "untracked"
    if str(text or "").strip().lower() == "new":
        return "create"
    return "kept"


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


def question_scope(q) -> str | None:
    """The ticket a question belongs to: a key, `""` for untracked work, `None` for every scope."""
    if not isinstance(q, dict) or "ticket" not in q or q.get("ticket") is None:
        return None
    return str(q.get("ticket") or "")


def blocks_scope(q, ticket: str | None) -> bool:
    """Does this question stop work on `ticket` (`None` or `""`: untracked work)?

    A blocking question asked under another ticket is *parked*, not lost: it is still open, still
    answerable from the tile, and it blocks again the moment that ticket is active. What it no longer
    does is stop unrelated work, which is how a stale question on one ticket used to send every later
    request in the checkout to `friction-log`.
    """
    if not is_blocking(q):
        return False
    scope = question_scope(q)
    return scope is None or scope == str(ticket or "")


def blocking_for(state: dict, ticket: str | None = None, *, use_active: bool = True) -> list:
    """The open questions that stop work on `ticket` (default: the active ticket)."""
    if ticket is None and use_active:
        ticket = state.get("active_ticket")
    return [q for q in state.get("open_questions") or [] if blocks_scope(q, ticket)]


def parked_for(state: dict, ticket: str | None = None) -> list:
    """Blocking questions that belong to another ticket's scope: open, but not in the way."""
    if ticket is None:
        ticket = state.get("active_ticket")
    return [q for q in state.get("open_questions") or [] if is_blocking(q) and not blocks_scope(q, ticket)]


def next_question_id(state: dict) -> str:
    """`q1`, `q2`, … per session. Short enough to type at a terminal, which is where they get typed.

    From a counter that only rises (`question_seq`), not from the lists alone. An id that got reused
    would mean two different things in one session -- and the operator answering `q1` from a tile
    drawn a moment earlier would answer the wrong one. Consulting the open and answered lists was
    not enough: a *cleared* question is in neither, so the next ask got its id back (#231). The
    lists are still read, so a file written before the counter existed never issues an id it holds.
    """
    top = int(state.get("question_seq") or 0)
    for existing in (state.get("open_questions") or [], state.get("answered_questions") or []):
        for q in existing:
            qid = str(q.get("id") or "") if isinstance(q, dict) else ""
            if qid[:1] == "q" and qid[1:].isdigit():
                top = max(top, int(qid[1:]))
    state["question_seq"] = top + 1
    return f"q{top + 1}"


def give_ids(state: dict, today: str | None = None) -> dict:
    """Every open question a record with an id, including the bare strings (#231).

    A bare string -- what `set --question` wrote, and what a skill written before #165 still asks
    with -- had no id, so neither `ad-state answer` nor the tile's card could name it, and
    `--clear-questions` was the only way out. The text, the order and the blocking are kept; only
    the shape changes, and only here, in the one writer.
    """
    oq = state.get("open_questions")
    if not oq:
        return state
    out = []
    for q in oq:
        if isinstance(q, dict):
            if not str(q.get("id") or ""):
                q = dict(q, id=next_question_id(state))
            out.append(q)
        elif str(q or "").strip():
            out.append({"id": next_question_id(state), "q": str(q).strip(),
                        "asked": stamp_for(today), "blocking": True})
    state["open_questions"] = out
    return state


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
    try:
        written = int(data.get("schema") or 1)
    except (TypeError, ValueError):
        written = 1
    if written > SCHEMA:
        raise StateError(f"{path} was written by a newer ad-state (schema {written}; this one reads up to {SCHEMA})",
                         hint="`ad-update` brings the CLI and the skills to the same version, then start a new chat")
    return data


def apply(state: dict, sets: dict, *, artifacts: list[dict] | None = None, questions: list[str] | None = None,
          clear_questions: bool = False, tools: dict | None = None, inputs: list[str] | None = None,
          asks: list[dict] | None = None, answers: dict | None = None,
          superseded: dict | None = None, today: str | None = None) -> dict:
    """Validate and merge. `sets` keys: phase, active_ticket, branch, pr_url, confluence_url, project."""
    was_phase = state.get("phase") or ""
    was_ticket = state.get("active_ticket")
    state["schema"] = SCHEMA
    give_ids(state, today)
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
        for text in questions:
            text = str(text or "").strip()
            if not text or any(question_text(q) == text for q in oq):
                continue
            oq.append({"id": next_question_id(state), "q": text, "asked": stamp_for(today),
                       "blocking": True, "ticket": str(state.get("active_ticket") or "")})
        # `set phase=blocked --question …` is one command, so the phase it interrupted is gone by
        # the time the question is added. Remembered from before the sets, exactly as `ask` keeps
        # it: without it an answer could never put the phase back, and the tile stayed blocked.
        if state.get("phase") == "blocked" and was_phase != "blocked":
            state.setdefault("blocked_from", was_phase or "idle")
    if asks:
        oq = state.setdefault("open_questions", [])
        for record in asks:
            record = dict(record)
            if any(question_text(q) == question_text(record) for q in oq):
                continue
            if not str(record.get("id") or ""):
                record["id"] = next_question_id(state)
            record.setdefault("asked", stamp_for(today))
            # A ticket question with an assumption is the assumption applied: the agent said
            # "this is RDSD-118's" or "this is untracked" and carried on, so the work is scoped
            # there now and the question sits on the tile under that scope for the operator to
            # overturn. `rescope` keeps `blocked` honest across the switch.
            if record.get("kind") == "ticket" and record.get("assume"):
                moved = apply_ticket_answer(state, str(record["assume"]))
                if moved in ("moved", "untracked"):
                    record["ticket"] = str(state.get("active_ticket") or "")
                    rescope(state)
            record.setdefault("ticket", str(state.get("active_ticket") or ""))
            oq.append(record)
        # A blocking question is what stops the agent, so the phase it came *from* is remembered
        # here: that is what `answer` puts back, and it is why answering can unblock at all. A
        # non-blocking one -- an assumption the agent stated and continued on -- changes no phase,
        # and must not steal the one a later blocking question will need. Nor does one parked on
        # another ticket: it blocks that ticket's work, not this one's.
        if blocking_for(state):
            if state.get("phase") != "blocked":
                state.setdefault("blocked_from", state.get("phase") or "idle")
            state["phase"] = "blocked"
    closing = [(qid, text, False) for qid, text in (answers or {}).items()]
    closing += [(qid, text, True) for qid, text in (superseded or {}).items()]
    if closing:
        oq = state.get("open_questions") or []
        moved_ticket = False
        for qid, text, replaced in closing:
            for record in oq:
                if isinstance(record, dict) and str(record.get("id") or "") == str(qid):
                    record["answer"] = text
                    record["answered"] = stamp_for(today)
                    # The operator's answer to "track it under RDSD-118?" is the move itself.
                    if record.get("kind") == "ticket" and not replaced:
                        moved_ticket = apply_ticket_answer(state, text) in ("moved", "untracked") or moved_ticket
                    # Superseded: the operator never answered it, they gave an instruction that made
                    # it moot. Closed the same way, so it unblocks the same way, and marked so that
                    # nobody later reads the instruction as the answer to the question.
                    if replaced:
                        record["superseded"] = True
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
        if not blocking_for(state):
            back = state.pop("blocked_from", "")
            if state.get("phase") == "blocked" and back:
                state["phase"] = back
        if moved_ticket:
            rescope(state)
    if "active_ticket" in sets and state.get("active_ticket") != was_ticket:
        rescope(state, explicit_phase=sets.get("phase"))
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


def rescope(state: dict, explicit_phase: str | None = None) -> dict:
    """Keep `phase == blocked` meaning *a question stops the active ticket*, across a ticket switch.

    Switching to a ticket with no blocker of its own leaves `blocked` (for the phase the same command
    named, else `idle`: the interrupted phase belonged to the other ticket). Switching to a ticket
    whose question is still open blocks again, remembering the phase it would have had.
    """
    stops = blocking_for(state)
    if state.get("phase") == "blocked" and not stops:
        state.pop("blocked_from", None)
        state["phase"] = explicit_phase if explicit_phase and explicit_phase != "blocked" else "idle"
    elif stops and state.get("phase") != "blocked":
        state["blocked_from"] = state.get("phase") or "idle"
        state["phase"] = "blocked"
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
