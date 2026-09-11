"""Sessions the fleet did not start, and how it comes to know about them (#2).

An operator with a `copilot` session already going in a `cmd.exe` window has an agent working in a
registered checkout that the fleet knows nothing about. The dashboard's tile for that repository
therefore shows the last run the *fleet* started -- which may be days old -- and says nothing is
supervised, while the operator is watching an agent work in the next window. That is the
"cached/historical session" complaint in #133: the page was not wrong about what it knew, it simply
did not know the thing the operator was looking at.

**What can actually be known, and how confidently.** Nothing here guesses:

* On POSIX, `/proc/<pid>/cwd` is the process's real working directory, so a session can be matched
  to a checkout *exactly*. That is `matched by working directory`.
* On Windows -- which is where this problem was reported -- a process's working directory is not
  readable without native calls that this package will not make. What is readable is the command
  line, via CIM. So a Copilot process can be found, but not placed. The placing comes from the
  checkout instead: `.agent/state.json` is written by `ad-state` and by nothing else, so a state
  file that changed in the last few minutes is a session somebody is having in that repository
  right now. That is `inferred from recent activity`, and it is labelled as such everywhere it is
  shown, because it is a weaker claim and the operator is entitled to know which one they have.

**Adoption supersedes, it does not supervise.** Taking an external session on makes the fleet
report it as the current run for that repository -- the tile stops showing a stale one -- and that
is the whole of the promise. The fleet did not start that process, has no pipe to its stdin and, on
Windows, may not even know its pid, so `send` and `stop` are refused for it rather than offered and
quietly ignored. One repository still holds one agent: a checkout the fleet is already running an
agent in cannot adopt a second one, which is the same lock rule, enforced in the same place.
"""
from __future__ import annotations
import json
import os
import subprocess
import threading
import time

from .. import textio
from . import events as E
from .registry import Registry

# How recently `.agent/state.json` must have been written for the fleet to believe somebody is
# working in that checkout now. Long enough to cover a model thinking, short enough that yesterday's
# session is not reported as live: a Copilot turn writes state at its boundaries, not continuously.
FRESH_S = 15 * 60

# The process names a Copilot CLI session runs under. `copilot` is the shim; on Windows it is a
# `node` process launched from one, which is why the command line is matched rather than the image.
AGENT_HINTS = ("copilot",)


class AdoptError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# ------------------------------------------------------------------------------- what is running


def _posix_processes() -> list[dict]:
    """From `/proc`, including each process's real working directory.

    The cwd is the whole point: it is what turns "a Copilot is running somewhere" into "a Copilot is
    running *in this checkout*". Anything unreadable is skipped rather than raised on -- a process
    that belongs to another user is not this operator's session.
    """
    out = []
    if not os.path.isdir("/proc"):
        return out
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = open(f"/proc/{entry}/cmdline", "rb").read().decode("utf-8", "replace")
        except OSError:
            continue
        line = raw.replace("\x00", " ").strip()
        if not line or not any(h in line.lower() for h in AGENT_HINTS):
            continue
        try:
            cwd = os.readlink(f"/proc/{entry}/cwd")
        except OSError:
            cwd = ""
        out.append({"pid": int(entry), "cmdline": line, "cwd": cwd})
    return out


def _windows_processes() -> list[dict]:
    """From CIM, which gives the command line and not the working directory.

    `Get-CimInstance` rather than `wmic`: wmic is deprecated and is absent from current Windows
    images, so a fleet that depended on it would simply stop finding anything one update from now.
    """
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -match 'copilot' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    except Exception:      # noqa: BLE001 - no PowerShell, refused, or slow: report nothing found
        return []
    body = (done.stdout or "").strip()
    if not body:
        return []
    try:
        rows = json.loads(body)
    except ValueError:
        return []
    if isinstance(rows, dict):        # ConvertTo-Json emits an object, not an array, for one row
        rows = [rows]
    out = []
    for row in rows:
        try:
            pid = int(row.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid:
            out.append({"pid": pid, "cmdline": str(row.get("CommandLine") or ""), "cwd": ""})
    return out


# The process listing, and when it was taken. `fleet_snapshot` runs several times a second for every
# window on every screen, and on Windows this listing is a PowerShell process -- spawning one per
# poll would cost more than everything else the dashboard does put together. A session that started
# ten seconds ago is offered ten seconds late, which nobody will notice.
PROCESS_CACHE_S = 10.0
_cache = {"at": 0.0, "rows": []}
_cache_lock = threading.Lock()


def agent_processes(*, max_age: float = PROCESS_CACHE_S) -> list[dict]:
    """Every Copilot session running on this machine, as far as this platform will say.

    Best effort by design, and never raises: a fleet that could not draw a dashboard because a
    process listing was refused would be worse than one that reports nothing found. Pass
    `max_age=0` to force a fresh listing -- what an explicit `ad-fleet adopt` should do.
    """
    now = time.time()
    with _cache_lock:
        if max_age and _cache["rows"] is not None and (now - _cache["at"]) < max_age:
            return list(_cache["rows"])
    try:
        rows = _windows_processes() if os.name == "nt" else _posix_processes()
    except Exception:      # noqa: BLE001 - see above
        rows = []
    with _cache_lock:
        _cache["at"], _cache["rows"] = now, rows
    return list(rows)


# ------------------------------------------------------------ what is happening in a checkout


def _touched(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def activity_age(repo_path: str) -> int:
    """Seconds since anything in this checkout said an agent was working in it, or -1.

    `.agent/state.json` has exactly one writer -- `ad-state`, the agent's own command -- so its
    modification time is the last moment an agent reported something about this repository. The
    friction directory counts too: a skill that stopped and wrote a STOP is also an agent at work.

    Takes a path rather than a `Repo` because `live()` calls this on every status poll, and building
    a `Repo` means re-reading `registry.json`. The lock already carries the path.
    """
    newest = _touched(os.path.join(repo_path, ".agent", "state.json"))
    friction = os.path.join(repo_path, ".agent", "friction")
    try:
        for entry in os.listdir(friction):
            newest = max(newest, _touched(os.path.join(friction, entry)))
    except OSError:
        pass
    if not newest:
        return -1
    return max(0, int(time.time() - newest))


def candidates(registry: Registry | None = None, *, processes: list[dict] | None = None) -> list[dict]:
    """Registered repositories that appear to have a session the fleet did not start.

    A repository is only a candidate if the fleet is *not* already running an agent in it. That is
    not a nicety: the whole point of the lock is that one checkout holds one agent, and offering to
    adopt a second session into a repo the fleet is already driving would be offering to break it.
    """
    from . import supervisor

    reg = registry or Registry()
    running = agent_processes() if processes is None else processes
    out = []
    for repo in reg.sorted():
        if supervisor.live(repo.name):
            continue                        # ours, and already the current session
        lock = supervisor.read_lock(repo.name)
        if lock.get("external"):
            continue                        # already adopted; `adopted()` reports on those
        age = activity_age(repo.path)
        if age < 0 or age > FRESH_S:
            continue

        # Exact where the platform allows it: a process whose working directory *is* this checkout.
        here = textio.norm_path(repo.path).rstrip("/\\").lower()
        exact = [p for p in running
                 if p.get("cwd") and textio.norm_path(p["cwd"]).rstrip("/\\").lower() == here]
        if exact:
            chosen = exact[0]
            how = "matched by working directory"
        elif running:
            # A Copilot is running and this checkout is being written to, but this platform will not
            # say which process is in which directory. Adoptable, without a pid, and labelled.
            chosen = {"pid": 0, "cmdline": running[0].get("cmdline", ""), "cwd": ""}
            how = "inferred from recent activity"
def _session_for_adopt(repo_name: str, repo_path: str, jira_project: str = "") -> str:
    from . import sessions, supervisor
    store_sess = sessions.read_store_sessions(repo_path, repo_name=repo_name, jira_project=jira_project)
    if store_sess:
        return store_sess[0]["id"]
    return supervisor.session_id(repo_name)


def discover(*, registry: Registry | None = None) -> list[dict]:
    reg = registry or Registry()
    out = []
    for repo in reg.sorted():
        age = activity_age(repo.path)
        if age < 0 or age > FRESH_S:
            continue
        here = textio.norm_path(repo.path).rstrip("/\\").lower()
        matched = [r for r in agent_processes()
                   if r.get("cwd") and textio.norm_path(r["cwd"]).rstrip("/\\").lower() == here]
        if matched:
            chosen = matched[0]
            how = "matched by working directory"
        else:
            # No process listing at all (refused, or none matched) and yet the checkout is being
            # written to. Still worth offering: the writing is the evidence, not the listing.
            chosen = {"pid": 0, "cmdline": "", "cwd": ""}
            how = "inferred from recent activity"

        out.append({"repo": repo.name, "path": repo.path, "pid": chosen["pid"],
                    "cmdline": chosen["cmdline"][:200], "how": how, "active_age_s": age,
                    "session": _session_for_adopt(repo.name, repo.path, getattr(repo, "jira_project", ""))})
    return out


# ------------------------------------------------------------------------------- taking one on


def adopt(name: str, *, registry: Registry | None = None, pid: int = 0) -> dict:
    """Make an external session the current one for this repository.

    Writes the same lock file the supervisor writes, marked `external`, so every reader that already
    knows what a lock means -- `live`, the reaper, the status rows -- keeps working unchanged. The
    `started` event gives the run a boundary, which is what stops the tile drawing this session's
    transcript as a continuation of the last one the fleet ran.
    """
    from . import supervisor

    reg = registry or Registry()
    repo = reg.get(name)

    if supervisor.live(name):
        raise AdoptError(f"the fleet is already running an agent in {name}",
                         "one checkout holds one agent. `ad-fleet stop` it first, or adopt a "
                         "different repository")

    age = activity_age(repo.path)
    if age < 0 or age > FRESH_S:
        raise AdoptError(
            f"nothing has been written in {name} for "
            f"{'a long time' if age < 0 else str(age) + 's'}",
            "an external session is recognised by its checkout being written to. Ask the agent "
            "something in that window, then adopt again")

    if not pid:
        here = textio.norm_path(repo.path).rstrip("/\\").lower()
        for row in agent_processes():
            if row.get("cwd") and textio.norm_path(row["cwd"]).rstrip("/\\").lower() == here:
                pid = row["pid"]
                break

    how = "matched by working directory" if pid else "inferred from recent activity"
    session = _session_for_adopt(name, repo.path, getattr(repo, "jira_project", ""))
    lock = {"pid": int(pid or 0), "how": how, "repo": name, "path": repo.path,
            "session": session, "ticket": repo.state().get("active_ticket", ""),
            "external": True, "adopted_at": E.stamp(), "started": time.time(),
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "restarts": 0, "launch": []}
    supervisor.write_lock(name, lock)
    E.append(name, [E.event(name, "started",
                            {"external": True, "pid": lock["pid"], "adopted": True,
                             "session": lock["session"],
                             "why": "a session the fleet did not start was adopted"},
                            ticket=lock["ticket"])])
    return {"repo": name, "pid": lock["pid"], "session": lock["session"], "how": how,
            "ticket": lock["ticket"], "external": True, "active_age_s": age}


def release(name: str, *, registry: Registry | None = None) -> dict:
    """Hand an adopted session back. Only ever removes a lock the fleet did not create.

    Refusing to clear a lock the supervisor wrote is the important half: `stop` is what ends one of
    those, and it only clears the lock once the process is genuinely gone. A release that could
    delete a real lock would let `start` launch a second agent over a live one.
    """
    from . import supervisor

    (registry or Registry()).get(name)
    lock = supervisor.read_lock(name)
    if not lock:
        return {"repo": name, "released": False, "detail": "nothing was adopted"}
    if not lock.get("external"):
        raise AdoptError(f"{name} is running an agent the fleet started",
                         "`ad-fleet stop` ends that one; release is only for adopted sessions")
    supervisor.clear_lock(name)
    return {"repo": name, "released": True, "pid": int(lock.get("pid") or 0)}


def is_external(name: str) -> bool:
    from . import supervisor

    return bool(supervisor.read_lock(name).get("external"))


def still_there(lock: dict) -> bool:
    """Is the adopted session still going?

    Two answers, in order of how much they are worth. A pid we were given is checked directly --
    that is the process, and if it is gone the session is over. Without one, the evidence that made
    the session adoptable in the first place is the evidence that it is still running: a checkout
    nobody has written to for a quarter of an hour is not being worked in.
    """
    pid = int(lock.get("pid") or 0)
    if pid:
        return proc_alive(pid)
    path = str(lock.get("path") or "")
    if not path:
        return False
    age = activity_age(path)
    return 0 <= age <= FRESH_S


def proc_alive(pid: int) -> bool:
    from . import supervisor

    return supervisor.pid_alive(pid)
