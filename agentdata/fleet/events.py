"""One normalized event stream per agent, merged from the three places the fleet can see.

The dashboard, the notifications and the approval gate all need the same answer -- *what is this
agent doing, and does it need me?* -- and it is scattered:

* the Copilot CLI's raw JSONL (assistant text, tool calls, turn boundaries, cost),
* the repo's `.agent/state.json` (`phase`, `active_ticket`, `open_questions`, `pr_url`),
* `.agent/friction/<stamp>-<skill>.md`, the STOP a skill writes when it is stuck.

Everything downstream reads `events.norm.jsonl` and never parses Copilot output again, so a CLI
upgrade is one mapping change here rather than a change in four slices.

**Additive only.** `schema: 1` on every line. A kind may be added; a kind's meaning may not change,
and a field may not be removed -- the dashboard replays history, and history does not get rewritten.

**Unknown kinds pass through as `raw`.** The catalogue in `docs/fleet-spike.md` is what one build
emitted on one day; the next release will add something. A reader that raised on an unfamiliar kind
would turn a Copilot upgrade into a fleet outage.
"""
from __future__ import annotations
import contextlib
import json
import os
import re
import time

from .. import textio
from .registry import agent_dir

SCHEMA = 1
NORMALIZED = "events.norm.jsonl"
CURSOR = "events.cursor.json"

# Every kind this module can emit. `docs/fleet-events.md` is the prose version; a test asserts the
# two agree, so a kind cannot be added in code and forgotten in the contract -- and nothing may be
# listed here that no writer produces, or the contract becomes a wish list.
KINDS = (
    # the supervisor
    "started",
    # the Copilot CLI's JSONL
    "turn_started", "assistant_text", "tool_call", "tool_result", "denied", "turn_ended",
    "session_id", "cost", "exited", "error", "raw",
    # .agent/state.json, via `ad-state`
    "phase_changed", "question_opened", "artifact", "pr_open",
    # .agent/friction/
    "friction",
    # reserved for the approval gate (#95); `agentstate.derive` already folds them, so the gate is
    # a writer and nothing downstream changes when it lands
    "needs_approval", "approval_resolved",
)

# The same shape `config.py` refuses to store, reused rather than re-invented: a value under a key
# that looks like a credential never reaches the normalized stream.
_SECRET_KEY = re.compile(r"(?:^|_)(password|passwd|pwd|secret|token|api_?key|pat|client_secret)$", re.I)
# ...and a value that looks like one even under an innocent key. A tool result is arbitrary text
# from a command we did not write, so the key is not always a clue.
_SECRET_VALUE = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
                           r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.)")
REDACTED = "<redacted>"


def redact(value):
    """Strip anything credential-shaped, by key and by value, at any depth."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out[k] = REDACTED if _SECRET_KEY.search(str(k)) else redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    return value


def normalized_path(name: str) -> str:
    return os.path.join(agent_dir(name), NORMALIZED)


def _cursor_path(name: str) -> str:
    return os.path.join(agent_dir(name), CURSOR)


def read_cursor(name: str) -> dict:
    try:
        return json.loads(textio.read_text(_cursor_path(name)))
    except (OSError, ValueError):
        return {}


def write_cursor(name: str, cursor: dict) -> None:
    os.makedirs(agent_dir(name), exist_ok=True)
    textio.write_text(_cursor_path(name), json.dumps(cursor, indent=2) + "\n")


def reset_raw_cursor(name: str) -> None:
    """Forget how far into the raw log we had read, because the raw log just became a new file.

    `supervisor._rotate` renames `events.jsonl` to `.1` between turns. The cursor counts *lines
    consumed*, so without this the next `refresh` would skip the opening N lines of the new log --
    the turn boundary, the prompt, and quite possibly a denial. Silent loss, months later.
    """
    cursor = read_cursor(name)
    if not cursor.get("raw_lines"):
        return
    cursor["raw_lines"] = 0
    write_cursor(name, cursor)


def stamp(ts: str | None = None) -> str:
    """One clock for the whole stream: UTC, second resolution, no zone suffix.

    Copilot timestamps its own events in UTC with a trailing `Z`. Stamping ours with local time --
    the obvious `time.strftime()` -- put 09:31 next to 05:08 on the same second of the same run,
    which reads as an event four hours in the past rather than as two clocks.
    """
    if ts:
        return str(ts).replace("Z", "").replace("+00:00", "")[:19]
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def event(repo: str, kind: str, data: dict | None = None, *, ticket: str = "", seq: int = 0,
          ts: str | None = None) -> dict:
    return {"schema": SCHEMA, "seq": seq, "ts": stamp(ts),
            "repo": repo, "ticket": ticket, "kind": kind, "data": redact(data or {})}


# ------------------------------------------------------------------- Copilot JSONL -> our kinds


def _text(data: dict) -> str:
    return str(data.get("content") or "").strip()


def from_copilot(raw: dict, repo: str, ticket: str = "") -> list[dict]:
    """Map one raw Copilot event. Returns zero, one or two normalized events.

    Ephemeral events are dropped: measured, they are token deltas and the model's own bookkeeping,
    and the durable ones are exactly the narrative a person reads.
    """
    if raw.get("ephemeral"):
        return []
    kind, data, ts = raw.get("type"), raw.get("data") or {}, raw.get("timestamp")
    make = lambda k, d: event(repo, k, d, ticket=ticket, ts=ts)   # noqa: E731 - local shorthand

    if kind == "assistant.turn_start":
        return [make("turn_started", {"turn": data.get("turnId")})]
    if kind == "assistant.turn_end":
        return [make("turn_ended", {"turn": data.get("turnId")})]
    if kind == "assistant.message":
        out = []
        if _text(data):
            out.append(make("assistant_text", {"text": _text(data), "model": data.get("model")}))
        return out
    if kind == "tool.execution_start":
        return [make("tool_call", {"tool": data.get("toolName"), "id": data.get("toolCallId"),
                                   "arguments": data.get("arguments")})]
    if kind == "tool.execution_complete":
        error = data.get("error") or {}
        result = make("tool_result", {"id": data.get("toolCallId"), "ok": bool(data.get("success")),
                                      "error": error.get("code") or "",
                                      "message": error.get("message") or ""})
        if error.get("code") == "denied":
            # The only signal there is. The CLI emits no permission *request*, and the turn still
            # exits 0 -- see docs/fleet-spike.md. #94 was written expecting a request event; there
            # is none, so this is what "the agent wanted something it may not have" looks like.
            return [result, make("denied", {"id": data.get("toolCallId"),
                                            "message": error.get("message") or ""})]
        return [result]
    if kind == "session.usage_checkpoint":
        return [make("cost", {"premium_requests": data.get("totalPremiumRequests")})]
    if kind == "result":
        # `result` is the one event not shaped {type,id,parentId,timestamp,data} -- its fields are
        # at the top level. Measured; do not "fix" this to read data.
        out = [make("session_id", {"session": raw.get("sessionId")})] if raw.get("sessionId") else []
        usage = raw.get("usage") or {}
        if usage.get("premiumRequests") is not None:
            out.append(make("cost", {"premium_requests": usage.get("premiumRequests")}))
        code = raw.get("exitCode")
        out.append(make("exited" if code == 0 else "error",
                        {"exit_code": code, "files_modified": (usage.get("codeChanges") or {})
                         .get("filesModified", [])}))
        return out
    return [make("raw", {"type": kind, "data": data})]


# --------------------------------------------------------- .agent/state.json and friction files


WATCHED = ("phase", "active_ticket", "pr_url")


def from_state(previous: dict, current: dict, repo: str) -> list[dict]:
    """What changed in the repo's own state. `ad-state` is its only writer; we only read."""
    out = []
    ticket = current.get("active_ticket", "") or ""
    if previous.get("phase") != current.get("phase"):
        out.append(event(repo, "phase_changed",
                         {"from": previous.get("phase", ""), "to": current.get("phase", "")},
                         ticket=ticket))
    grew = len(current.get("open_questions") or []) - len(previous.get("open_questions") or [])
    if grew > 0:
        for q in (current.get("open_questions") or [])[-grew:]:
            out.append(event(repo, "question_opened", {"question": q}, ticket=ticket))
    added = len(current.get("artifacts") or []) - len(previous.get("artifacts") or [])
    if added > 0:
        for a in (current.get("artifacts") or [])[-added:]:
            out.append(event(repo, "artifact", {"artifact": a}, ticket=ticket))
    if current.get("pr_url") and previous.get("pr_url") != current.get("pr_url"):
        out.append(event(repo, "pr_open", {"url": current.get("pr_url")}, ticket=ticket))
    return out


UNBLOCK = re.compile(r"##\s*What would unblock me\s*\n+(.+?)(?:\n#|\Z)", re.S | re.I)


def friction_event(path: str, repo: str, ticket: str = "") -> dict:
    """A skill wrote a STOP. The unblock sentence is what the operator needs on the tile.

    Read through `textio`, so a file PowerShell wrote with a BOM, or one written UTF-16, is the same
    event as one written cleanly -- the skills are prose files edited by whatever is to hand.
    """
    try:
        body = textio.read_text(path)
    except OSError:
        body = ""
    match = UNBLOCK.search(body)
    unblock = " ".join((match.group(1) if match else "").split())[:400]
    return event(repo, "friction", {"file": textio.norm_path(path),
                                    "skill": os.path.basename(path),
                                    "unblock": unblock}, ticket=ticket)


def friction_files(repo_path: str) -> list[str]:
    directory = os.path.join(repo_path, ".agent", "friction")
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, n) for n in os.listdir(directory) if n.endswith(".md"))


# ------------------------------------------------------------------------------ the merged read


LOCK = "events.lock"
LOCK_WAIT_S = 30.0
LOCK_STALE_S = 30.0


class Busy(OSError):
    """Another writer holds this agent's stream. Nothing was written; try again.

    An `OSError` on purpose: every caller that reads or refreshes a stream already treats an OS
    error as "not this time" and comes back on the next tick, so a busy stream needs no new
    handling anywhere.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"{name}'s event stream is held by another writer")
        self.repo = name


@contextlib.contextmanager
def writing(name: str):
    """Hold the agent's write lock for a read-modify-write of the cursor.

    Two writers is the normal case, not an edge: `ad-state` emits from inside the agent while
    `ad-fleet serve` refreshes the same stream from the operator's machine. Without this they both
    read `seq: 5` and both write a `seq: 6`, and the dense, never-reused numbering this contract
    promises is quietly untrue.

    Exclusive-create rather than `fcntl`/`msvcrt`, because it has to behave the same on both and
    because a lock that outlives its holder must be recoverable: one left by a killed agent is
    stolen after `LOCK_STALE_S`, or a crash would block that repository's stream forever.

    **If the lock cannot be taken, nothing is written.** The first version of this proceeded anyway,
    reasoning that a dropped event was worse than a duplicate `seq`. That is backwards, and CI
    proved it by producing a duplicate: a dropped append is recovered on the next `refresh`, which
    re-reads `state.json` and re-emits what changed, while a duplicate `seq` is permanent and makes
    every reader resuming from a cursor skip real events. The write is the courtesy; the numbering
    is the contract.
    """
    path = os.path.join(agent_dir(name), LOCK)
    os.makedirs(agent_dir(name), exist_ok=True)
    deadline = time.time() + LOCK_WAIT_S
    fd = None
    while fd is None:
        if time.time() >= deadline:
            raise Busy(name)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            # Not only FileExistsError. On Windows a file whose delete is still pending cannot be
            # opened at all and answers ERROR_ACCESS_DENIED -- a PermissionError, microseconds long,
            # raised by the *release* of the lock we are waiting for. Treating it as fatal turned
            # every busy moment into a crash; it is the ordinary contended case.
            if _stale_lock(path):
                _drop(path)
            time.sleep(0.01)
    try:
        os.write(fd, f"{os.getpid()} {time.time():.0f}".encode("utf-8"))
        yield
    finally:
        os.close(fd)
        _drop(path)


def _stale_lock(path: str) -> bool:
    try:
        return time.time() - os.path.getmtime(path) > LOCK_STALE_S
    except OSError:
        return True


def _drop(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def append(name: str, events: list[dict]) -> int:
    """Append normalized events, numbering them. Returns the last seq written."""
    if not events:
        return int(read_cursor(name).get("seq", 0))
    with writing(name):
        return _append(name, events)


def _append(name: str, events: list[dict]) -> int:
    """The write itself. Callers hold the lock; `refresh` holds it across its whole cycle."""
    cursor = read_cursor(name)
    seq = int(cursor.get("seq", 0))
    os.makedirs(agent_dir(name), exist_ok=True)
    with open(normalized_path(name), "a", encoding="utf-8", newline="\n") as f:
        for ev in events:
            seq += 1
            ev["seq"] = seq
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    cursor["seq"] = seq
    write_cursor(name, cursor)
    return seq


def read(name: str, *, since: int = 0, kinds: tuple[str, ...] | None = None,
         limit: int = 0) -> list[dict]:
    path = normalized_path(name)
    if not os.path.isfile(path):
        return []
    out = []
    for line in textio.read_text(path).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("seq", 0) <= since:
            continue
        if kinds and ev.get("kind") not in kinds:
            continue
        out.append(ev)
    return out[-limit:] if limit else out


def refresh(name: str, repo_path: str = "", *, repo_state: dict | None = None) -> list[dict]:
    """Bring the normalized stream up to date with everything that has happened since last time.

    Idempotent by construction: the cursor records how many raw lines have been consumed and the
    last state seen, so replaying the same inputs twice produces the same stream rather than
    doubling it.
    """
    from .supervisor import events_path

    with writing(name):
        return _refresh(name, repo_path, repo_state, events_path(name))


def _refresh(name: str, repo_path: str, repo_state: dict | None, raw_path: str) -> list[dict]:
    cursor = read_cursor(name)
    fresh: list[dict] = []

    consumed = int(cursor.get("raw_lines", 0))
    lines = textio.read_text(raw_path).splitlines() if os.path.isfile(raw_path) else []
    ticket = (repo_state or {}).get("active_ticket", "") or ""
    for line in lines[consumed:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            fresh.extend(from_copilot(json.loads(line), name, ticket))
        except ValueError:
            continue
    cursor["raw_lines"] = len(lines)

    if repo_state is not None:
        previous = cursor.get("state") or {}
        fresh.extend(from_state(previous, repo_state, name))
        cursor["state"] = {k: repo_state.get(k) for k in WATCHED}
        cursor["state"]["open_questions"] = list(repo_state.get("open_questions") or [])
        cursor["state"]["artifacts"] = list(repo_state.get("artifacts") or [])

    if repo_path:
        seen = set(cursor.get("friction") or [])
        for path in friction_files(repo_path):
            if path not in seen:
                fresh.append(friction_event(path, name, ticket))
                seen.add(path)
        cursor["friction"] = sorted(seen)

    write_cursor(name, cursor)
    _append(name, fresh)          # `_append`, not `append`: the lock is already held above
    return fresh
