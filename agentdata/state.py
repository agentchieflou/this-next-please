"""`.agent/state.json` — machine-owned session state. Only `ad-state` (skill state-update) writes it: validated keys and
phases, `last_updated` stamped, artifacts pruned, UTF-8 without BOM, atomic. Reads tolerate whatever an earlier
PowerShell one-liner wrote (BOM / UTF-16) and rewrite the file clean."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from . import textio

PATH = os.path.join(".agent", "state.json")
PHASES = ("idle", "triaged", "querying", "optimizing", "validating", "documenting", "pr_open", "blocked", "done")
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


class StateError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


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
    if questions:
        oq = state.setdefault("open_questions", [])
        oq += [q for q in questions if q and q not in oq]
    if inputs:
        # Same spelling as an artifact path, for the same reason: `.agent\in\X\y.md` and
        # `.agent/in/X/y.md` are one file, and two spellings of it in the list would be offered,
        # attached and reported twice. The key is only materialised when there is one to record.
        current = state.setdefault("inputs", [])
        for raw in inputs:
            item = textio.norm_path(str(raw).strip())
            if not item:
                raise StateError("--input expects a path", hint="example: --input .agent/in/RDSD-1234/export.md")
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
