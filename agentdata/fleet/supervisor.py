"""Starting, watching and stopping one agent per registered working tree.

One agent per repo, enforced by a lock file rather than by hope: two `copilot` processes in one
checkout would both edit the same working tree and both believe they owned `.agent/state.json`.

The supervisor writes only under `~/.agentdata/fleet/`. The repository belongs to the agent.
"""
from __future__ import annotations
import calendar
import json
import os
import subprocess
import sys
import time

from .. import proc
from .. import textio
from . import console as fleet_console
from . import handoff as H
from . import lifecycle
from .launch import child_env, launch_command, prompt_for, console_command
from .registry import Registry, Repo, RegistryError, agent_dir, fleet_dir

LOCK = "agent.json"
EVENTS = "events.jsonl"
STDERR = "stderr.log"
USAGE = "usage.json"
from .agentstate import TERMINAL_PHASES
DONE_CATEGORIES = ("done",)     # Jira's statusCategory key, not a status name: names vary per project


class SupervisorError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


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
    # A child of ours that has exited stays a zombie until somebody waits for it, and `kill(pid, 0)`
    # succeeds on a zombie -- so this answered "alive" forever for an agent started by a process
    # that outlives it. `ad-fleet start` exits and hands its orphan to init, which hides the bug;
    # `ad-fleet serve` does not, so an agent started from the dashboard on Linux or macOS would have
    # sat on its tile as `running` after it had finished. Reaping here is also the only thing that
    # ever reaps it, since nothing keeps the `Popen`.
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    except ChildProcessError:
        pass                      # not our child: `kill(pid, 0)` below is the whole answer
    except OSError:
        pass
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
    """The lock, if the process it names is still running; otherwise `{}`.

    **A query, and nothing else.** It used to clear a lock whose process was gone, which sounds
    tidy and was destructive: `lifecycle.reap` reads that lock to find out which ticket the agent
    died on and where its stderr is, and everything in the fleet calls `live()` constantly. So the
    first innocent status poll deleted the evidence, and a crashed agent was never reported as
    anything at all -- it simply stopped existing. Clearing a stale lock is the reaper's job,
    *after* it has said what happened.
    """
    lock = read_lock(name)
    if not lock:
        return {}
    if lock.get("external"):
        # A session the fleet did not start (#2). It is live on the same terms it was adopted on:
        # by its pid where the platform would name one, and otherwise by the checkout still being
        # written to. `adopt.still_there` holds both, and reads the path out of the lock rather than
        # the registry -- this runs on every status poll, and `Registry()` re-parses its file.
        from . import adopt

        return lock if adopt.still_there(lock) else {}
    return lock if pid_alive(int(lock.get("pid") or 0)) else {}


# --------------------------------------------------------------------------------- the events


def events_path(name: str) -> str:
    return os.path.join(agent_dir(name), EVENTS)


def _rotate(name: str, cfg: dict | None = None) -> list[str]:
    """Roll whichever of this agent's logs have grown -- only when no agent is writing to them.

    On Windows a rename of an open file fails, and on POSIX it would succeed and silently strand a
    live child writing to an unlinked inode. Both are avoided by only ever rotating between turns.
    """
    return lifecycle.rotate_all(name, cfg=cfg)


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
    """The id `--resume` takes, from the normalized stream or the last `result` event.

    `sessionId` is read from the normalized stream first so rotation does not lose it, and respects
    fresh start boundaries so a failed start does not resume yesterday's session.
    """
    from . import events as E

    if isinstance(events, str):
        try:
            E.refresh(events)
        except Exception:
            pass
        stream = E.read(events)
    else:
        stream = events

    for event in reversed(stream):
        kind = event.get("kind")
        if kind == "session_id":
            sid = (event.get("data") or {}).get("session")
            if sid:
                return str(sid)
        elif kind == "started":
            data = event.get("data") or {}
            if not data.get("resumed") or data.get("new"):
                return str(data.get("session") or "")
        elif _is_result(event) and event.get("sessionId"):
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


def _emit_started(name: str, lock: dict, *, resumed: bool = False, new: bool = False,
                  console: bool = False) -> None:
    """Put the launch itself into the normalized stream.

    Without this the stream begins mid-narrative -- the first thing anyone downstream sees is the
    agent's own first turn, with no record of what it was asked or when. A `started` event is also
    what lets the dashboard distinguish "never launched" from "launched and said nothing yet".
    """
    try:
        from . import events as E

        E.append(name, [E.event(name, "started",
                                {"pid": lock.get("pid"), "prompt": (lock.get("prompt") or "")[:400],
                                 "summary": lock.get("summary", ""),
                                 "resumed": resumed, "new": new, "session": lock.get("session", ""),
                                 **({"console": True} if console else {})},
                                ticket=lock.get("ticket", ""))])
    except Exception:  # noqa: BLE001 - a missing breadcrumb must never fail a launch
        from ..log import debug_exc

        debug_exc("fleet started event")


def check_ticket(repo: Repo, key: str, *, cross_project: bool = False, board_rows=None,
                 force: bool = False) -> str:
    """Is this ticket one this repository should be started on? Returns its summary, or "".

    Two guard rails, and both exist because the failure they prevent is expensive and quiet:

    * **Wrong project.** Starting the RDSD checkout on a DATAENG ticket produces an agent that
      branches, reads and edits the wrong repository for twenty minutes before anyone notices.
    * **A finished ticket.** An agent given a Done ticket has nothing to do and will invent
      something, because "there is nothing here" is not an answer a router is built to give.

    The board is consulted only when the fleet already has it -- being unable to reach Jira must not
    stop an operator starting an agent, which is why `board_rows` is passed in rather than fetched.
    """
    from .board import find, project_of

    key = (key or "").strip().upper()
    project = project_of(key)
    declared = (repo.jira_project or "").upper()
    if project and declared and project != declared and not cross_project:
        raise SupervisorError(
            f"{key} is a {project} ticket and {repo.name} declares jira_project {declared}",
            f"start it on the {project} checkout, or pass --cross-project if this is deliberate",
            code="cross_project")

    row = find(board_rows or [], key)
    if not row:
        return ""
    if row.get("category") in DONE_CATEGORIES and not force:
        raise SupervisorError(
            f"{key} is already {row.get('status') or 'Done'}",
            "an agent given a finished ticket has nothing to do and will invent something; "
            "pass --force if you mean to re-open the work",
            code="ticket_done")
    return str(row.get("summary") or "")


def start(name: str, *, key: str | None = None, prompt: str | None = None, force: bool = False,
          cfg: dict | None = None, registry: Registry | None = None, exe: str | None = None,
          cross_project: bool = False, board_rows=None, summary: str = "",
          resume: str | None = None, new: bool = False, brief: str | None = None,
          brief_by: str = "operator") -> dict:
    reg = registry or Registry()
    repo = reg.get(name)
    if key:
        summary = summary or check_ticket(repo, key, cross_project=cross_project,
                                          board_rows=board_rows, force=force)

    lock = live(name)
    if lock:
        if not force:
            raise SupervisorError(
                f"{name} already has a live agent (pid {lock.get('pid')}, ticket "
                f"{lock.get('ticket') or 'none'})",
                f"one agent per working tree. Use `ad-fleet send {name} \"…\"` to talk to it, or "
                f"`ad-fleet stop {name}` first",
                code="live_agent")
        # --force means "replace it", never "run a second one beside it": two agents in one
        # checkout would both edit the same working tree.
        stopped = stop(name)
        if not stopped.get("stopped"):
            raise SupervisorError(
                f"{name}'s existing agent (pid {lock.get('pid')}) would not stop",
                "stop it by hand, then start again",
                code="live_agent")

    # Resuming into a checkout that something else is already working in would put two agents in
    # one working tree -- the thing the lock exists to prevent, except that this one has no lock to
    # catch it, because the console window that owns it never took one (#174). Only where a real
    # process can be *named* in this checkout: "the folder was written to recently" is evidence of
    # somebody saving a file, and refusing a resume on that would refuse most of them. The words
    # are the adopt strip's own, because it is the same claim about the same process.
    if resume and not lock:
        from . import adopt as A

        try:
            foreign = [c for c in A.candidates(reg) if c["repo"] == name and c.get("pid")]
        except Exception:                    # noqa: BLE001 - a process listing must never block a start
            foreign = []
        if foreign:
            raise SupervisorError(
                f"something is working in {name} that the fleet did not start "
                f"(pid {foreign[0]['pid']}, {foreign[0]['how']})",
                f"close that window, or `ad-fleet adopt {name}` and then resume it — two agents in "
                f"one working tree is what this refuses",
                code="foreign_session")

    repo_state = repo.state()
    active, phase = repo_state.get("active_ticket", ""), repo_state.get("phase", "")
    if active and phase not in TERMINAL_PHASES and phase not in ("", "idle") and (key is None or active != key) and not force:
        raise SupervisorError(
            f"{name} is mid-ticket: {active} is in phase {phase!r}",
            f"finish or park it first, or pass --force to start "
            f"{key or 'a new prompt'} anyway",
            code="mid_ticket")

    # The brief is written *before* the spawn, and a failure to write it refuses the start. The
    # operator has just typed the one thing nothing else in the system knows; launching an agent
    # that was promised it and will not find it is worse than not launching at all.
    if brief is not None:
        H.write_brief(name, repo.path, key or "", brief, by=brief_by)

    text = prompt_for(key, prompt, cfg, summary=summary,
                      handoff=H.prompt_line(repo.path, key or ""))
    _rotate(name, cfg)
    directory = agent_dir(name)

    argv = launch_command("copilot", repo.path, text,
                          log_dir=os.path.join(directory, "logs"),
                          cfg=cfg, usage_file=os.path.join(directory, USAGE),
                          session=resume)
    child = _spawn(repo, name, argv, exe)

    lock = {"pid": child.pid, "repo": name, "path": repo.path, "ticket": key or "",
            "summary": summary, "prompt": text, "session": resume or "", "started": time.time(),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "launch": argv}
    write_lock(name, lock)
    _emit_started(name, lock, resumed=bool(resume), new=bool(new or not resume))
    return lock


def send(name: str, message: str, *, cfg: dict | None = None, registry: Registry | None = None,
         exe: str | None = None, force: bool = False) -> dict:
    reg = registry or Registry()
    repo = reg.get(name)

    current = live(name)
    if current.get("external") or current.get("kind") == "console":
        # An adopted session is somebody else's process. There is no pipe to its stdin, so a message
        # sent here would go nowhere -- and a Send button that silently does nothing is worse than
        # one that refuses and says where to type instead.
        raise SupervisorError(f"{name} is running a session the fleet did not start",
                              "type in that window. `ad-fleet release` hands it back, and then the "
                              "fleet can drive this repository again",
                              code="external_session")
    if current:
        raise SupervisorError(f"{name} is mid-turn",
                              "wait for the turn to finish, or `ad-fleet stop` it first",
                              code="mid_turn")

    # Before the turn, never during one: stopping an agent halfway through a thought leaves the
    # repository in whatever state it had reached, and the money is spent either way.
    over, used, budget = lifecycle.over_budget(name, cfg=cfg)
    if over and not force:
        raise SupervisorError(
            f"{name} has spent {used:g} of its {budget:g} premium-request budget",
            f"raise `fleet.budget_per_agent`, or pass --force for this one turn. "
            f"`ad-fleet history` shows where it went",
            code="budget_exceeded")

    session = session_id(name)
    if not session:
        raise SupervisorError(f"{name} has no session to continue",
                              f"start one with `ad-fleet start {name} <TICKET>`",
                              code="no_session")

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


# The console helper runs in its own process and is expected to be quick: it attaches, writes key
# events and exits. A helper that has not answered in this long is a window that is not taking input,
# which is a refusal and not something to wait out with the operator watching a spinner.
HELPER_TIMEOUT_S = 20.0
CREATE_NO_WINDOW = 0x08000000


def helper_command(verb: str, cfg: dict | None = None) -> list[str]:
    """The argv that runs one console helper verb. `fleet.console.helper` replaces the interpreter
    in front of it, which is how CI drives `say` without a console anywhere."""
    from .. import config as C

    configured = C.get(cfg if cfg is not None else C.load(), "fleet.console.helper", None)
    if isinstance(configured, (list, tuple)) and configured:
        base = [str(part) for part in configured]
    elif isinstance(configured, str) and configured.strip():
        base = [configured.strip()]
    else:
        base = [sys.executable, "-m", "agentdata", "fleet"]
    return [*base, verb]


def _helper_meta(text: str) -> dict:
    """The helper's own TOON meta, as a dict. The helper is the one that knows the Win32 number, so
    its words are the ones that reach the tile -- this reads them rather than inventing a sentence."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        key, sep, value = line.strip().partition(":")
        if not sep or not key or " " in key:
            continue
        value = value.strip()
        if len(value) > 1 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('\\"', '"')
        out[key] = value
    return out


def _run_helper(argv: list[str], name: str) -> dict:
    flags = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=HELPER_TIMEOUT_S, **flags)
    except subprocess.TimeoutExpired:
        raise SupervisorError(f"the console helper for {name} did not answer in "
                              f"{HELPER_TIMEOUT_S:.0f}s",
                              "that window may be busy or gone; type in it instead",
                              code="console_unreachable") from None
    except OSError as e:
        raise SupervisorError(f"could not run the console helper for {name}: {e}",
                              "`fleet.console.helper` overrides the interpreter it runs with",
                              code="console_unreachable") from None
    meta = _helper_meta(done.stdout)
    if done.returncode != 0:
        raise SupervisorError(meta.get("error") or f"the console helper for {name} exited "
                                                   f"{done.returncode}",
                              meta.get("hint") or "type in that window instead",
                              code=meta.get("code") or "console_unreachable")
    return meta


def _console_lock(name: str, verb: str, registry: Registry | None = None) -> dict:
    """The lock, if this repository is a console the fleet can reach. Every other case is a refusal
    that names where to type instead."""
    (registry or Registry()).get(name)
    lock = live(name)
    if not lock:
        raise SupervisorError(f"{name} has no live agent to {verb}",
                              f"`ad-fleet console {name}` opens one, or `ad-fleet send {name} "
                              f"\"...\"` continues the last session headless",
                              code="no_agent")
    if lock.get("kind") != "console":
        raise SupervisorError(f"{name} is not running in a console",
                              f"`ad-fleet send {name} \"...\"` continues this session the way it "
                              f"was started",
                              code="not_a_console")
    pid = int(lock.get("pid") or 0)
    if not pid:
        # An adopted console: the evidence was the session file, and this platform never named a
        # process for it. There is no console to attach to, and saying so is the same sentence
        # `send` has always used.
        raise SupervisorError(f"{name} is running a session the fleet did not start",
                              "type in that window. `ad-fleet release` hands it back, and then the "
                              "fleet can drive this repository again",
                              code="external_session")
    return lock


def say(name: str, text: str, *, cfg: dict | None = None,
        registry: Registry | None = None) -> dict:
    """Type one line into the console the fleet opened for this checkout (#190).

    Not `send`: that is a second `copilot -p --resume` process, which in a working tree that already
    has a console is a second agent. This types what the operator typed into the console they are
    already watching, and the session's own file carries it back to the tile as the user turn.
    """
    lock = _console_lock(name, "say to", registry)
    try:
        line = fleet_console.one_line(text)
    except fleet_console.ConsoleError as e:
        # One vocabulary: every refusal the page and the CLI see is a SupervisorError with a code,
        # whichever layer noticed. A ConsoleError escaping here would be a 500 on a typo.
        raise SupervisorError(e.msg, e.hint, code=e.code or "refused") from None
    from . import events as E

    meta = _run_helper([*helper_command("say-into", cfg), str(lock["pid"]), line], name)
    # What the fleet typed, on the fleet's own stream -- the way `started` records the window being
    # opened. Not a second record of the session: the console echoes this exact line, and what the
    # session makes of it comes back from Copilot's own file (#188), which is the only transcript.
    E.append(name, [E.event(name, "said", {"text": line, "session": lock.get("session", ""),
                                           "pid": int(lock["pid"])},
                            ticket=str(lock.get("ticket") or ""))])
    return {"repo": name, "ok": True, "pid": int(lock["pid"]), "session": lock.get("session", ""),
            "echoed": meta.get("echoed") or line}


def focus(name: str, *, cfg: dict | None = None, registry: Registry | None = None) -> dict:
    """Bring this checkout's console window to the front. The tile's *show the console*."""
    lock = _console_lock(name, "show", registry)
    _run_helper([*helper_command("focus-console", cfg), str(lock["pid"])], name)
    return {"repo": name, "ok": True, "pid": int(lock["pid"]), "focused": True}


def restart(name: str, *, cfg: dict | None = None, registry: Registry | None = None,
            exe: str | None = None, force: bool = False) -> dict:
    """Bring an agent back on the session it was already having.

    `--resume <session>` and not a fresh start: the agent has read the ticket, made a plan and
    possibly edited files, and beginning again would repeat all of it -- at full price, and with a
    second set of edits over the first.

    Bounded by `fleet.max_restarts` per session. An agent that dies twice for the same reason will
    die a third time, and an unbounded restart loop on a laptop is how a budget disappears
    overnight; the count is per session, so a human click always gets one more.
    """
    reg = registry or Registry()
    repo = reg.get(name)

    # Read the lock BEFORE reaping. Reaping clears it -- that is its job, since a lock naming a
    # dead pid is what makes the fleet report a corpse as running -- but the restart count and the
    # ticket live in it, and losing them would make `max_restarts` unenforceable and hand the
    # resumed agent no ticket.
    lock = read_lock(name) or {}
    lifecycle.reap(name)

    if live(name):
        raise SupervisorError(f"{name} is already running (pid {read_lock(name).get('pid')})",
                              f"`ad-fleet stop {name}` first if it is stuck",
                              code="live_agent")

    session = session_id(name)
    if not session:
        raise SupervisorError(f"{name} has no session to resume",
                              f"start one with `ad-fleet start {name} <TICKET>`",
                              code="no_session")

    limit = lifecycle.settings(cfg)["max_restarts"]
    done = int(lock.get("restarts") or 0)
    if not force and limit and done >= limit:
        raise SupervisorError(
            f"{name} has already been restarted {done} time(s) on session {session}",
            "an agent that fails twice the same way will fail a third time. Read "
            f"`ad-fleet logs {name}`, then pass --force if it is worth another turn",
            code="max_restarts")

    directory = agent_dir(name)
    text = lifecycle.RESUME_PROMPT
    argv = launch_command("copilot", repo.path, text,
                          log_dir=os.path.join(directory, "logs"), session=session, cfg=cfg,
                          usage_file=os.path.join(directory, USAGE))
    child = _spawn(repo, name, argv, exe)
    fresh = {"pid": child.pid, "repo": name, "path": repo.path, "session": session,
             "ticket": lock.get("ticket", ""), "summary": lock.get("summary", ""),
             "prompt": text, "restarts": done + 1, "started": time.time(),
             "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "launch": argv}
    write_lock(name, fresh)
    _emit_started(name, fresh, resumed=True)
    return fresh


def console(name: str, *, key: str | None = None, resume: str | None = None, new: bool = False,
            cfg: dict | None = None, registry: Registry | None = None, exe: str | None = None,
            cross_project: bool = False, board_rows=None) -> dict:
    """Open a real console running Copilot in this checkout, with a session id the fleet chose (#189).

    The operator's own interactive session, in their own window -- and the tile knows the session
    before the first keystroke, because the lock names it and `events.refresh` reads Copilot's own
    file for it (#188). The lock is taken the way `start` takes it, with the window's pid, so one
    agent per working tree holds for consoles too: the #174 gap, where a console the operator
    opened never took a lock, closes for every console the fleet opens.
    """
    import uuid

    from .. import config as C

    reg = registry or Registry()
    repo = reg.get(name)
    summary = check_ticket(repo, key, cross_project=cross_project, board_rows=board_rows) if key else ""
    lock = live(name)
    if lock:
        if resume and lock.get("kind") != "console" and not lock.get("external"):
            # Moving a session to a console happens *between* turns (#191). A headless `-p` run
            # ends at the turn boundary by itself, so this is a wait and not a kill: stopping it
            # here would leave the working tree wherever the thought had got to, and the premium
            # request is spent either way.
            raise SupervisorError(
                f"{name} is mid-turn",
                f"a session moves to a console between turns. Wait for this one to finish, or "
                f"`ad-fleet stop {name}` first",
                code="mid_turn")
        raise SupervisorError(
            f"{name} already has a live agent (pid {lock.get('pid')}, ticket {lock.get('ticket') or 'none'})",
            f"one agent per working tree. `ad-fleet stop {name}` first, or close its window",
            code="live_agent")
    from . import adopt as A

    try:
        foreign = [c for c in A.candidates(reg) if c["repo"] == name and c.get("pid")]
    except Exception:                        # noqa: BLE001 - a process listing must never block this
        foreign = []
    if foreign:
        raise SupervisorError(
            f"something is working in {name} that the fleet did not start "
            f"(pid {foreign[0]['pid']}, {foreign[0]['how']})",
            f"close that window, or `ad-fleet adopt {name}` — two agents in one working tree is what "
            f"this refuses", code="foreign_session")

    session = str(resume or "").strip() or uuid.uuid4().hex
    directory = agent_dir(name)
    os.makedirs(os.path.join(directory, "logs"), exist_ok=True)
    argv = console_command("copilot", repo.path, log_dir=os.path.join(directory, "logs"),
                           session=session, resume=bool(resume), cfg=cfg)
    host = str(C.get(cfg if cfg is not None else C.load(), "fleet.console.host", "") or
               ("cmd" if os.name == "nt" else "terminal"))
    child = _open_console(repo, name, argv, exe, host, key or "")
    lock = {"pid": child.pid, "kind": "console", "host": host, "repo": name, "path": repo.path,
            "ticket": key or "", "summary": summary, "session": session, "started": time.time(),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "launch": argv}
    write_lock(name, lock)
    _emit_started(name, lock, resumed=bool(resume), new=bool(new or not resume), console=True)
    return lock


def _open_console(repo: Repo, name: str, argv, exe: str | None, host: str, key: str) -> subprocess.Popen:
    """The window. `cmd` and `wt` on Windows, a terminal emulator elsewhere; `fake` runs the
    command with no window at all, which is how CI exercises everything that is not a window."""
    directory = agent_dir(name)
    command = resolved(argv, exe)
    if host == "fake":
        with open(os.path.join(directory, STDERR), "a", encoding="utf-8", newline="\n") as errors:
            # stdout to nowhere: a console session is read from Copilot's own file (#188), never
            # from a pipe -- the fleet's raw log would fold every line twice.
            return subprocess.Popen(command, cwd=repo.path, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=errors,
                                    env=child_env(name, fleet_dir()),
                                    **({"start_new_session": True} if os.name != "nt" else {}))
    line = command if isinstance(command, str) else subprocess.list2cmdline(command)
    title = f"{name} · {key}" if key else name
    if os.name == "nt":
        inner = f'title {title} & {line}'
        if host == "wt":
            return subprocess.Popen(["wt.exe", "-d", repo.path, "cmd.exe", "/k", inner],
                                    cwd=repo.path, env=child_env(name, fleet_dir()))
        return subprocess.Popen(["cmd.exe", "/k", inner], cwd=repo.path,
                                creationflags=subprocess.CREATE_NEW_CONSOLE,
                                env=child_env(name, fleet_dir()))
    import shutil

    emulator = shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal") or shutil.which("xterm")
    if not emulator:
        raise SupervisorError("no terminal emulator to open a console in on this machine",
                              "the console is for the laptop; on Windows it is `cmd.exe`. "
                              "`fleet.console.host: fake` runs the session with no window",
                              code="no_console_host")
    return subprocess.Popen([emulator, "-e", *(command if isinstance(command, list) else [command])],
                            cwd=repo.path, env=child_env(name, fleet_dir()), start_new_session=True)


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
    if lock.get("kind") == "console":
        # The window is the operator's (#189). The fleet opened it and does not close it: the lock
        # goes when the window does, and `start` refuses beside it until then.
        raise SupervisorError(
            f"{name} is a console the fleet opened (pid {pid}, session {lock.get('session') or 'none'})",
            "close that window; the fleet opened it and does not close it",
            code="console_window")
    if lock.get("external") and not pid:
        # Adopted from the evidence of a checkout being written to, on a platform that would not say
        # which process was doing it. There is nothing here to kill, and `kill_tree(0)` means "this
        # process group" -- which is the fleet, and on a CI runner was once the test suite above it.
        raise SupervisorError(
            f"{name} is running a session the fleet did not start, and this machine will not say "
            f"which process it is",
            "close that window yourself. `ad-fleet release` then hands the repository back")
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


def reset(name: str, *, cfg: dict | None = None, registry: Registry | None = None,
          exe: str | None = None, force: bool = False, wait: float = 10.0) -> dict:
    """Unblock this agent: end whatever is holding the checkout, then resume the same session.

    The two-command dance -- `ad-fleet stop <repo>` and then `ad-fleet start <repo>` -- is the thing
    the operator could not work out from the dashboard, and no wonder: neither command is named
    after the problem. What they have is an agent that has stopped answering, in a `cmd.exe` window
    they may not even be able to find, and what they want is for it to go again. That is one
    intention, so it is one call, and the page can put one button on it.

    It is `stop` and then `restart`, in that order, with the failures kept rather than smoothed
    over, because both halves can legitimately refuse:

    * a process that will not die keeps its lock, and this returns that refusal untouched. Starting
      a second agent beside a live one is the failure the lock exists to prevent, and "the reset
      button did nothing visible" is a far better outcome than two agents editing one working tree.
    * `restart` resumes rather than starts fresh -- `--resume <session>`, so the agent keeps the
      ticket it has read and the plan it has made -- and it is bounded by `fleet.max_restarts`. A
      refusal there is reported with its hint, and the caller may pass `force` to spend one more.

    Nothing here is new behaviour. It is the two verbs the operator was already expected to run,
    with the ordering and the reasons built in instead of written in a document.
    """
    reg = registry or Registry()
    reg.get(name)                       # an unknown name is a typo; say so before killing anything

    ended = stop(name, wait=wait, registry=reg)
    if ended.get("pid") and not ended.get("stopped"):
        # Still alive after the kill. `stop` kept the lock on purpose; respect it.
        raise SupervisorError(
            f"{name} would not stop: {ended.get('detail', 'the process is still running')}",
            "nothing was restarted -- a second agent beside a live one would edit the same "
            "working tree. Close that window, or end the process, and reset again")

    lock = restart(name, cfg=cfg, registry=reg, exe=exe, force=force)
    return {"repo": name, "stopped": bool(ended.get("stopped")), "pid": lock["pid"],
            "session": lock.get("session", ""), "ticket": lock.get("ticket", ""),
            "summary": lock.get("summary", ""), "restarts": lock.get("restarts", 1)}


def status(registry: Registry | None = None) -> list[dict]:
    reg = registry or Registry()
    # Notice the dead before reporting on them: a killed process leaves a lock behind, and a row
    # that said "running" about a pid that is gone is the one lie the whole fleet turns on.
    lifecycle.reap_all(registry=reg)
    rows = []
    for repo in reg.sorted():
        # `project` rides beside `repo` rather than replacing it: the lock, the agent directory and
        # the events are all per working tree, and the project is only what says two of them are
        # the same piece of work (#175). One agent per registered working tree.
        row = {"repo": repo.name, "project": repo.project, "path": repo.path,
               "worktree_of": repo.worktree_of, "jira_project": repo.jira_project}
        row.update(agent_state(repo.name, repo))
        rows.append(row)
    return rows
