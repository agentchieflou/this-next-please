"""Starting, watching and stopping one agent per repository.

One agent per repo, enforced by a lock file rather than by hope: two `copilot` processes in one
checkout would both edit the same working tree and both believe they owned `.agent/state.json`.

The supervisor writes only under `~/.agentdata/fleet/`. The repository belongs to the agent.
"""
from __future__ import annotations
import calendar
import json
import os
import subprocess
import time

from .. import proc
from .. import textio
from .events import reset_raw_cursor
from .launch import child_env, launch_command, prompt_for
from .registry import Registry, Repo, RegistryError, agent_dir, fleet_dir

LOCK = "agent.json"
EVENTS = "events.jsonl"
STDERR = "stderr.log"
USAGE = "usage.json"
MAX_LOG_BYTES = 8 << 20      # rotate at 8 MB; a long session is chatty and the disk is not ours
TERMINAL_PHASES = ("", "idle", "done", "closed", "merged")


class SupervisorError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# ------------------------------------------------------------------------------- the lock file


def lock_path(name: str) -> str:
    return os.path.join(agent_dir(name), LOCK)


def read_lock(name: str) -> dict:
    try:
        return json.loads(textio.read_text(lock_path(name)))
    except (OSError, ValueError):
        return {}


def write_lock(name: str, data: dict) -> None:
    os.makedirs(agent_dir(name), exist_ok=True)
    textio.write_text(lock_path(name), json.dumps(data, indent=2) + "\n")


def clear_lock(name: str) -> None:
    try:
        os.remove(lock_path(name))
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """Is that process still running? Never raises -- callers use it to decide whether to kill.

    Deliberately not consulted for *identity*: a pid is recycled, so `stop()` also checks that the
    lock is young enough to plausibly name the process it started. Whatever this returns, a failure
    to answer is treated as "gone", because the alternative is a fleet that can never be unblocked.
    """
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=60,
                                 stdin=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001 - tasklist missing, slow, or refused
            return False
        # tasklist prints an INFO line when nothing matches, so the pid must appear in a real row.
        return any(str(pid) in line.split() for line in (out.stdout or "").splitlines())
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def live(name: str) -> dict:
    """The lock, if the process it names is still running; otherwise `{}` and the lock is cleared."""
    lock = read_lock(name)
    if lock and pid_alive(int(lock.get("pid") or 0)):
        return lock
    if lock:
        clear_lock(name)
    return {}


# --------------------------------------------------------------------------------- the events


def events_path(name: str) -> str:
    return os.path.join(agent_dir(name), EVENTS)


def _rotate(name: str) -> None:
    """Rename the event log if it has grown too big -- only when no agent is writing to it.

    On Windows a rename of an open file fails, and on POSIX it would succeed and silently strand a
    live child writing to an unlinked inode. Both are avoided by only ever rotating between turns.
    """
    path = events_path(name)
    if live(name):
        return
    try:
        if os.path.getsize(path) > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
            reset_raw_cursor(name)
    except OSError:
        pass


def read_events(name: str, *, raw: bool = False, limit: int = 200) -> list[dict]:
    """The agent's event stream, newest last.

    `ephemeral` events are dropped unless `raw`: the spike showed they are the token-by-token
    deltas and the model's own bookkeeping, and what is left is exactly the durable narrative --
    the prompt, the assistant's messages, the tool calls, the turn boundary, the cost.
    """
    path = events_path(name)
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    for line in textio.read_text(path).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not raw and event.get("ephemeral"):
            continue
        out.append(event)
    return out[-limit:] if limit else out


def _is_result(event: dict) -> bool:
    return event.get("type") == "result"


def _is_denial(event: dict) -> bool:
    """A tool the agent was not allowed to run.

    The whole reason this function exists: the CLI emits no permission *request*, and a denied tool
    does not fail the turn -- it comes back here and the turn still exits 0. See
    docs/fleet-spike.md. This is the only signal that an agent wanted something it may not have.
    """
    if event.get("type") != "tool.execution_complete":
        return False
    return ((event.get("data") or {}).get("error") or {}).get("code") == "denied"


def session_id(events: list[dict] | str) -> str:
    """The id `--resume` takes, from the last `result` event.

    `sessionId` is read at the top level, not under `data`: `result` is the one event that is not
    shaped `{type, id, parentId, timestamp, data}` -- measured, see the catalogue in
    docs/fleet-spike.md.
    """
    stream = read_events(events, raw=True, limit=0) if isinstance(events, str) else events
    for event in reversed(stream):
        if _is_result(event) and event.get("sessionId"):
            return str(event["sessionId"])
    return ""


def _last_turn(events: list[dict]) -> list[dict]:
    """The events of the most recently *completed* turn: everything after the previous `result`."""
    ends = [i for i, e in enumerate(events) if _is_result(e)]
    if not ends:
        return []
    start = ends[-2] + 1 if len(ends) > 1 else 0
    return events[start:ends[-1] + 1]


def agent_state(name: str, repo: Repo | None = None) -> dict:
    """What the operator needs to see on a tile, derived from the stream and nothing else.

    `waiting` is the interesting one. A denial always arrives *before* the `result` that ends the
    turn -- the tool is attempted, refused, and the model narrates it and finishes -- so "is the
    newest denial newer than the newest result" is always false and would never fire. What matters
    is whether the last completed turn contained one.
    """
    lock = live(name)
    events = read_events(name, limit=0)
    last = events[-1] if events else {}

    results = [e for e in events if _is_result(e)]
    denied = [e for e in events if _is_denial(e)]
    turn = _last_turn(events)

    if lock:
        state = "running"
    elif not events:
        state = "idle"
    elif not results:
        # Started, produced events, and never reached a `result`: the process died mid-turn.
        state = "crashed"
    elif any(_is_denial(e) for e in turn):
        state = "waiting"
    else:
        state = "exited"

    premium = 0.0
    for event in results:
        premium += float((event.get("usage") or {}).get("premiumRequests") or 0)

    repo_state = repo.state() if repo else {}
    return {
        "agent": state,
        "pid": int(lock.get("pid") or 0),
        "session": session_id(events),
        "ticket": repo_state.get("active_ticket", ""),
        "phase": repo_state.get("phase", ""),
        "last_event": last.get("type", ""),
        "last_event_age_s": _age(last),
        "denied_tools": len(denied),
        "premium_requests": round(premium, 2),
        "turns": len(results),
    }


def _age(event: dict) -> int:
    """Seconds since the event, from a UTC timestamp.

    `calendar.timegm`, not `time.mktime`: the timestamps end in `Z`, and mktime would read them as
    local time. Correcting that with `time.timezone` is wrong for half the year, because
    `time.timezone` never accounts for DST.
    """
    stamp = event.get("timestamp")
    if not stamp:
        return -1
    try:
        parsed = time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return -1
    return max(0, int(time.time() - calendar.timegm(parsed)))


# ---------------------------------------------------------------------------------- the verbs


def resolved(argv: list[str], exe: str | None = None):
    """What subprocess should actually be handed, for a logical argv starting with `copilot`.

    `proc.command()` and never the bare name or the shim path: `copilot` is npm-installed, so on
    Windows it exists as `copilot.cmd`. `proc` returns `node <entry point> ...` as a list for an npm
    shim, and for any other `.cmd` a whole command **string**, which subprocess must pass to Windows
    verbatim rather than through `list2cmdline`. Getting that wrong is the WinError trap this repo
    already hit with `pncli` and `az`.
    """
    try:
        return proc.command(argv, exe=exe)
    except proc.ProcError as e:
        raise SupervisorError(
            f"the Copilot CLI (`copilot`) could not be started: {e.msg}",
            "install it with `npm install -g @github/copilot`, then `copilot login`") from None


def _spawn(repo: Repo, name: str, argv, exe: str | None = None) -> subprocess.Popen:
    """Start the agent detached enough to outlive the shell that asked for it."""
    directory = agent_dir(name)
    os.makedirs(os.path.join(directory, "logs"), exist_ok=True)
    kwargs = {}
    if os.name == "nt":
        # Its own process group, so closing the console that ran `ad-fleet start` does not send the
        # agent a Ctrl-Break, and so `kill_tree` has a group to end.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    # Append, never truncate: `send` continues the same narrative, and the operator's scrollback is
    # the only record of what the agent was asked before the machine went to sleep.
    with open(os.path.join(directory, EVENTS), "a", encoding="utf-8", newline="\n") as events, \
            open(os.path.join(directory, STDERR), "a", encoding="utf-8", newline="\n") as errors:
        return subprocess.Popen(resolved(argv, exe), cwd=repo.path, stdin=subprocess.DEVNULL,
                                stdout=events, stderr=errors, text=True,
                                encoding="utf-8", errors="replace",
                                env=child_env(name, fleet_dir()), **kwargs)


def _emit_started(name: str, lock: dict, *, resumed: bool = False) -> None:
    """Put the launch itself into the normalized stream.

    Without this the stream begins mid-narrative -- the first thing anyone downstream sees is the
    agent's own first turn, with no record of what it was asked or when. A `started` event is also
    what lets the dashboard distinguish "never launched" from "launched and said nothing yet".
    """
    try:
        from . import events as E

        E.append(name, [E.event(name, "started",
                                {"pid": lock.get("pid"), "prompt": (lock.get("prompt") or "")[:400],
                                 "resumed": resumed, "session": lock.get("session", "")},
                                ticket=lock.get("ticket", ""))])
    except Exception:  # noqa: BLE001 - a missing breadcrumb must never fail a launch
        from ..log import debug_exc

        debug_exc("fleet started event")


def start(name: str, *, key: str | None = None, prompt: str | None = None, force: bool = False,
          cfg: dict | None = None, registry: Registry | None = None, exe: str | None = None) -> dict:
    reg = registry or Registry()
    repo = reg.get(name)

    lock = live(name)
    if lock:
        if not force:
            raise SupervisorError(
                f"{name} already has a live agent (pid {lock.get('pid')}, ticket "
                f"{lock.get('ticket') or 'none'})",
                f"one agent per repository. Use `ad-fleet send {name} \"…\"` to talk to it, or "
                f"`ad-fleet stop {name}` first")
        # --force means "replace it", never "run a second one beside it": two agents in one
        # checkout would both edit the same working tree.
        stopped = stop(name)
        if not stopped.get("stopped"):
            raise SupervisorError(
                f"{name}'s existing agent (pid {lock.get('pid')}) would not stop",
                "stop it by hand, then start again")

    repo_state = repo.state()
    active, phase = repo_state.get("active_ticket", ""), repo_state.get("phase", "")
    if active and phase not in TERMINAL_PHASES and (key is None or active != key) and not force:
        raise SupervisorError(
            f"{name} is mid-ticket: {active} is in phase {phase!r}",
            f"finish or park it first, or pass --force to start "
            f"{key or 'a new prompt'} anyway")

    text = prompt_for(key, prompt, cfg)
    _rotate(name)
    directory = agent_dir(name)

    argv = launch_command("copilot", repo.path, text,
                          log_dir=os.path.join(directory, "logs"),
                          cfg=cfg, usage_file=os.path.join(directory, USAGE))
    child = _spawn(repo, name, argv, exe)

    lock = {"pid": child.pid, "repo": name, "path": repo.path, "ticket": key or "",
            "prompt": text, "started": time.time(),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "launch": argv}
    write_lock(name, lock)
    _emit_started(name, lock)
    return lock


def send(name: str, message: str, *, cfg: dict | None = None, registry: Registry | None = None,
         exe: str | None = None) -> dict:
    reg = registry or Registry()
    repo = reg.get(name)

    if live(name):
        raise SupervisorError(f"{name} is mid-turn",
                              "wait for the turn to finish, or `ad-fleet stop` it first")
    session = session_id(name)
    if not session:
        raise SupervisorError(f"{name} has no session to continue",
                              f"start one with `ad-fleet start {name} <TICKET>`")

    directory = agent_dir(name)
    argv = launch_command("copilot", repo.path, message,
                          log_dir=os.path.join(directory, "logs"), session=session, cfg=cfg,
                          usage_file=os.path.join(directory, USAGE))
    child = _spawn(repo, name, argv, exe)

    lock = {"pid": child.pid, "repo": name, "path": repo.path, "session": session,
            "prompt": message, "started": time.time(),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "launch": argv}
    write_lock(name, lock)
    _emit_started(name, lock, resumed=True)
    return lock


def stop(name: str, *, wait: float = 10.0, registry: Registry | None = None) -> dict:
    """End the agent and everything it started, and report honestly whether it died.

    Through `proc.kill_tree`, which ends the child's process group -- `copilot` spawns shells and
    shells spawn `ad-*` commands, so killing only the pid we know leaves the rest holding the
    working tree. The lock is cleared **only** if the process is actually gone; a lock removed over
    a live agent would let `start` launch a second one beside it.
    """
    (registry or Registry()).get(name)     # an unknown name is a typo, and saying "no live agent"
    lock = live(name)                     # to a typo sends the operator looking in the wrong place
    if not lock:
        clear_lock(name)
        return {"repo": name, "stopped": False, "detail": "no live agent"}

    pid = int(lock.get("pid") or 0)
    proc.kill_tree(pid)

    deadline = time.time() + wait
    while time.time() < deadline:
        if not pid_alive(pid):
            clear_lock(name)
            return {"repo": name, "stopped": True, "pid": pid, "ticket": lock.get("ticket", "")}
        time.sleep(0.1)

    return {"repo": name, "stopped": False, "pid": pid,
            "detail": f"pid {pid} was still alive {wait:.0f}s after the kill; the lock is kept so "
                      f"nothing starts a second agent beside it"}


def status(registry: Registry | None = None) -> list[dict]:
    reg = registry or Registry()
    rows = []
    for repo in reg.sorted():
        row = {"repo": repo.name, "path": repo.path, "jira_project": repo.jira_project}
        row.update(agent_state(repo.name, repo))
        rows.append(row)
    return rows
