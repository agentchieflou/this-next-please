"""One click between an unattended agent and a write to a system of record.

`AGENTS.md` rule 8 -- run with `--dry-run`, read `"ok"`, then execute -- assumes a human is reading
the chat between the two steps. Headless, nobody is. So the agent runs unattended for everything
read-only and **stops here** at each write to Jira, Confluence or Bitbucket: the dry-run result is
written out as the payload, the operator sees exactly what will be sent, and one click releases it.

Three properties this has to have, in order of how badly each one bites:

**Invisible outside a fleet.** With `AGENTDATA_FLEET_AGENT` unset -- a person in PyCharm, a CI job,
every existing test -- `require()` returns `approved` before touching the disk. Nothing changes.

**Fails closed.** If the request cannot be recorded, the answer is *refused*, never "proceed
anyway". A gate that fails open on a full disk is not a gate; it is a delay.

**Not the only layer.** The launch allow-list (#93) is the other half: the agent may run `ad-*` and
may not run `curl`, `Invoke-RestMethod` or `pncli` directly, so it cannot route around this by
picking a different tool. Neither layer is sufficient alone -- the spike measured Copilot's own
classifier allowing a .NET file write after refusing three plainer spellings of the same thing
(docs/fleet-spike.md), which is exactly why the gate lives in our commands and not in its
permission prompt.
"""
from __future__ import annotations
import os
import secrets
import time

from .. import config as C
from .. import textio
from .registry import AGENT_ENV, FLEET_DIR_ENV, fleet_dir

APPROVED = "approved"
DENIED = "denied"
TIMEOUT = "timeout"
UNAVAILABLE = "unavailable"

# What a gated command puts in `meta.refused`. `docs/refusals.md` carries the same three.
REFUSALS = {DENIED: "approval_denied", TIMEOUT: "approval_timeout", UNAVAILABLE: "approval_unavailable"}

DEFAULT_TIMEOUT_S = 30 * 60
POLL_S = 2.0
KEEP_DECIDED_DAYS = 30


class Decision:
    """What came back. `auto` marks the outside-a-fleet path, which is not a decision anyone made."""

    def __init__(self, state: str, *, id: str = "", reason: str = "", by: str = "", auto: bool = False):
        self.state, self.id, self.reason, self.by, self.auto = state, id, reason, by, auto

    @property
    def ok(self) -> bool:
        return self.state == APPROVED

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"Decision({self.state!r}, id={self.id!r})"


def in_fleet() -> str:
    """The agent name, if this process was launched by a supervisor. Both markers or neither."""
    name = os.environ.get(AGENT_ENV, "")
    return name if name and os.environ.get(FLEET_DIR_ENV) else ""


def approvals_dir() -> str:
    return os.path.join(fleet_dir(), "approvals")


def _request_path(id: str) -> str:
    return os.path.join(approvals_dir(), f"{id}.json")


def _decision_path(id: str) -> str:
    return os.path.join(approvals_dir(), f"{id}.decision.json")


def new_id(agent: str, kind: str) -> str:
    """Readable at a glance and unique enough to race: the operator reads these in a list."""
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return textio.safe_name(f"{agent}-{kind}-{stamp}-{secrets.token_hex(2)}")


def timeout_seconds(cfg: dict | None = None) -> int:
    value = C.get(cfg if cfg is not None else C.load(), "fleet.approval_timeout")
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


# ------------------------------------------------------------------------------- the agent side


def require(kind: str, summary: str, payload=None, *, ticket: str = "", cfg: dict | None = None,
            timeout: int | None = None, poll: float = POLL_S) -> Decision:
    """Block until an operator approves this write, or refuse. Outside a fleet, approve at once.

    `payload` is the dry-run result, so the operator approves *exactly* what will be sent rather
    than a description of it.
    """
    agent = in_fleet()
    if not agent:
        return Decision(APPROVED, auto=True)

    id = new_id(agent, kind)
    record = {"id": id, "repo": agent, "ticket": ticket, "kind": kind, "summary": summary,
              "payload": payload, "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
              "pid": os.getpid()}
    try:
        os.makedirs(approvals_dir(), exist_ok=True)
        textio.write_json(_request_path(id), record)
    except (OSError, ValueError):
        # Fails closed. The operator never saw this, so nobody can have approved it.
        from ..log import debug_exc

        debug_exc("approval request")
        return Decision(UNAVAILABLE, id=id)

    _emit(agent, "needs_approval", {"id": id, "kind": kind, "summary": summary}, ticket)

    deadline = time.time() + (timeout if timeout is not None else timeout_seconds(cfg))
    while True:
        decided = read_decision(id)
        if decided:
            state = str(decided.get("decision") or DENIED)
            _emit(agent, "approval_resolved", {"id": id, "kind": kind, "decision": state,
                                               "by": decided.get("by", "")}, ticket)
            return Decision(state if state in (APPROVED, DENIED) else DENIED, id=id,
                            reason=str(decided.get("reason") or ""), by=str(decided.get("by") or ""))
        if time.time() >= deadline:
            return Decision(TIMEOUT, id=id)
        time.sleep(poll)


def refusal(decision: Decision, source: str) -> dict:
    """The `meta` fields a gated command prints. One shape, so every gated command reads alike."""
    code = REFUSALS.get(decision.state, "approval_denied")
    if decision.state == DENIED:
        error = f"the operator denied this write ({decision.id})"
        hint = decision.reason or "ask for the reason, then either fix the request or stop"
    elif decision.state == TIMEOUT:
        error = f"no operator answered within the approval window ({decision.id})"
        hint = f"approve it with `ad-fleet approve {decision.id}` and re-run the same command"
    else:
        error = "the approval could not be recorded, so the write was not attempted"
        hint = (f"check that {approvals_dir()} is writable; nothing was sent, and re-running is "
                f"safe")
    return {"ok": False, "source": source, "refused": code, "error": error, "hint": hint,
            "approval": decision.id}


def _emit(agent: str, kind: str, data: dict, ticket: str) -> None:
    try:
        from . import events as E

        E.append(agent, [E.event(agent, kind, data, ticket=ticket)])
    except Exception:  # noqa: BLE001 - a missing breadcrumb must never change a decision
        from ..log import debug_exc

        debug_exc("approval event")


# ---------------------------------------------------------------------------- the operator side


def read_request(id: str) -> dict:
    try:
        return textio.read_json(_request_path(id), "approval")
    except (OSError, ValueError):
        return {}


def read_decision(id: str) -> dict:
    try:
        return textio.read_json(_decision_path(id), "approval decision")
    except (OSError, ValueError):
        return {}


def pending() -> list[dict]:
    """Every request nobody has answered, oldest first -- the order they should be worked."""
    directory = approvals_dir()
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.endswith(".decision.json"):
            continue
        id = name[:-5]
        if read_decision(id):
            continue
        record = read_request(id)
        if record:
            record["waiting_s"] = _age(record.get("created", ""))
            out.append(record)
    return sorted(out, key=lambda r: r.get("created", ""))


def history(limit: int = 50) -> list[dict]:
    directory = approvals_dir()
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".decision.json"):
            continue
        id = name[: -len(".decision.json")]
        out.append({**read_request(id), **read_decision(id)})
    return out[-limit:] if limit else out


class ApprovalError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def decide(id: str, state: str, *, reason: str = "", by: str = "") -> dict:
    """Answer one request. Idempotent-ish: a second answer is refused rather than silently ignored."""
    if state not in (APPROVED, DENIED):
        raise ApprovalError(f"{state!r} is not a decision", f"one of {APPROVED} | {DENIED}")
    record = read_request(id)
    if not record:
        known = [r["id"] for r in pending()]
        raise ApprovalError(f"no approval called {id!r} is waiting",
                            ("waiting: " + ", ".join(known)) if known else
                            "`ad-fleet approvals` lists what is waiting")
    existing = read_decision(id)
    if existing:
        raise ApprovalError(f"{id} was already {existing.get('decision')}",
                            "an approval is answered once; the agent has already been told")
    if state == DENIED and not reason.strip():
        # The agent logs friction with this sentence in it. "denied" with no reason gives whoever
        # picks the ticket up nothing to act on.
        raise ApprovalError("a denial needs a reason", 'pass --reason "…"; the agent quotes it')

    decision = {"id": id, "decision": state, "reason": reason, "by": by or _who(),
                "decided": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
    os.makedirs(approvals_dir(), exist_ok=True)
    textio.write_json(_decision_path(id), decision)
    _prune()
    return {**record, **decision}


def _who() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "operator"


def _age(created: str) -> int:
    import calendar

    try:
        return max(0, int(time.time() - calendar.timegm(time.strptime(created[:19], "%Y-%m-%dT%H:%M:%S"))))
    except (ValueError, TypeError):
        return 0


def _prune(days: int = KEEP_DECIDED_DAYS) -> None:
    """Answered requests are history, and history that grows without limit is a directory nobody
    can read. Pending ones are never touched, however old -- an unanswered write is not litter."""
    directory = approvals_dir()
    cutoff = time.time() - days * 86400
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not name.endswith(".decision.json"):
            continue
        id = name[: -len(".decision.json")]
        for path in (_decision_path(id), _request_path(id)):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
