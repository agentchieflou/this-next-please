"""Surviving a laptop.

Four unattended agents on a machine that sleeps, locks, changes network and sits behind a proxy
fail in ways one attended chat never did, and every one of them is quiet: the process is simply
gone, or the token expired, or the turn cost more than anyone meant to spend. None of that raises
an exception anybody sees.

So this module is about noticing. It holds the parts of the fleet's lifecycle that are about
*failure* rather than about work:

* a process that ended without saying so, and what its stderr was;
* a laptop that slept, which looks exactly like four agents thinking for two hours;
* an expired Copilot login, which must produce one clear answer and never a retry loop;
* a budget, so an agent left running overnight cannot spend without limit;
* logs, which are the one thing here that grows forever if nobody prunes it.

Everything it learns is written as normalized events (#94), so the tiles, the notifications and the
history all see it without a second channel.
"""
from __future__ import annotations
import os
import re
import time

from .. import config as C
from .. import textio
from . import agentstate, events as E
from .registry import Registry, RegistryError, agent_dir

# How long a gap between two heartbeats means the machine slept rather than the fleet being busy.
# Two minutes: a turn can legitimately take that long, an idle poll never can.
SLEEP_GAP_S = 120

STDERR_LINES = 20                # what an `error` event carries; enough to see the last traceback
DEFAULT_MAX_RESTARTS = 1
DEFAULT_LOG_MB = 20
DEFAULT_LOG_KEEP = 5
DEFAULT_GC_DAYS = 14

# What a resumed agent is told. Deliberately not the original ticket prompt: the agent already has
# the ticket in its session, and repeating it invites a second plan over the first.
RESUME_PROMPT = ("You were interrupted. Read your own last messages, say in one line where you got "
                 "to, and continue. Do not start the ticket again.")

# The Copilot CLI's own words when the token has expired, measured in the #92 spike. Matched
# loosely on purpose: the wording moves between releases and the *class* of failure is what matters.
AUTH_TROUBLE = re.compile(
    r"(not (?:logged in|authenticated)|authentication (?:failed|required|expired)|"
    r"401 unauthorized|please (?:run )?`?copilot login|token (?:has )?expired|invalid credentials)",
    re.I)


def settings(cfg: dict | None = None) -> dict:
    cfg = C.load() if cfg is None else cfg

    def number(key, default):
        try:
            return max(0, int(C.get(cfg, f"fleet.{key}", default)))
        except (TypeError, ValueError):
            return default

    budget = C.get(cfg, "fleet.budget_per_agent")
    try:
        budget = float(budget) if budget not in (None, "", False) else 0.0
    except (TypeError, ValueError):
        budget = 0.0
    return {"max_restarts": number("max_restarts", DEFAULT_MAX_RESTARTS),
            "log_mb": number("log_mb", DEFAULT_LOG_MB),
            "log_keep": number("log_keep", DEFAULT_LOG_KEEP),
            "budget_per_agent": budget}


# ----------------------------------------------------------------------- what stderr was saying


def tail_stderr(name: str, lines: int = STDERR_LINES) -> str:
    """The last lines of an agent's stderr, redacted.

    Redacted through the same rule the event stream uses, because a crash dump is exactly where a
    token ends up: a proxy failure prints the request, and the request carries the header.
    """
    path = os.path.join(agent_dir(name), "stderr.log")
    try:
        text = textio.read_text(path)
    except OSError:
        return ""
    kept = [line for line in text.splitlines() if line.strip()][-lines:]
    return str(E.redact({"t": "\n".join(kept)})["t"])


def looks_like_auth_trouble(text: str) -> bool:
    return bool(AUTH_TROUBLE.search(text or ""))


# ------------------------------------------------------------------- a process that just stopped


def reap(name: str, *, cfg: dict | None = None) -> list[dict]:
    """Notice an agent whose process is gone, and say why in its own stream.

    Called wherever the fleet looks at an agent. It is idempotent: an agent already reaped has no
    lock, and one still running is left alone.

    The distinction that matters is between an agent that *finished* -- the CLI wrote a `result`,
    so the stream already ends in `exited` -- and one that simply stopped existing. The second is
    what a killed process, a closed console or a slept laptop looks like, and nothing else in the
    fleet would ever report it.
    """
    from . import supervisor

    lock = supervisor.read_lock(name)
    if not lock or supervisor.pid_alive(int(lock.get("pid") or 0)):
        return []

    supervisor.clear_lock(name)
    stream = E.read(name)
    if stream and stream[-1].get("kind") in ("exited", "error"):
        return []                                   # it ended properly; nothing to report

    stderr = tail_stderr(name)
    ticket = lock.get("ticket", "")
    if looks_like_auth_trouble(stderr):
        # One clear answer and no retry: relaunching an agent whose token expired burns premium
        # requests in a loop and produces the same failure every time.
        fresh = [E.event(name, "error", {"exit_code": None, "reason": "copilot login expired",
                                         "stderr": stderr}, ticket=ticket),
                 E.event(name, "question_opened",
                         {"question": "Copilot is no longer logged in. Run `copilot login`, then "
                                      f"`ad-fleet restart {name}`."}, ticket=ticket)]
    elif stderr:
        fresh = [E.event(name, "error", {"exit_code": None, "reason": "the process ended without "
                                         "reporting a result", "stderr": stderr}, ticket=ticket)]
    else:
        # No exit code and nothing on stderr: the machine slept, or the console was closed. Not an
        # error -- an agent that stopped -- and saying "error" would send someone hunting a bug.
        fresh = [E.event(name, "exited", {"exit_code": None,
                                          "reason": "the process is gone and left no output"},
                         ticket=ticket)]
    try:
        E.append(name, fresh)
    except OSError:
        return []
    return fresh


def reap_all(*, registry: Registry | None = None) -> dict[str, list[dict]]:
    out = {}
    try:
        names = [r.name for r in (registry or Registry()).sorted()]
    except RegistryError:
        return out
    for name in names:
        found = reap(name)
        if found:
            out[name] = found
    return out


# --------------------------------------------------------------------------- the laptop slept


def slept(previous: float, now: float | None = None, gap: int = SLEEP_GAP_S) -> bool:
    """Did wall-clock jump further than any poll interval could explain?

    A slept laptop looks exactly like four agents thinking for two hours, and the difference
    matters: the second is fine, the first means every process may be gone.
    """
    if not previous:
        return False
    return ((now or time.time()) - previous) > gap


# ------------------------------------------------------------------------------- the budget


def spent(name: str) -> float:
    """What this agent has cost so far, from its own stream. The CLI reports a session total, so
    the high-water mark is the answer and a sum would multiply the bill."""
    return float(agentstate.derive(E.read(name))["premium_requests"])


def over_budget(name: str, *, cfg: dict | None = None) -> tuple[bool, float, float]:
    """(over, spent, budget). A budget of 0 is off, which is the default.

    Checked before a turn is *sent*, never in the middle of one: stopping an agent halfway through
    a thought leaves the repository in whatever state it had reached, and the money is spent either
    way.
    """
    budget = settings(cfg)["budget_per_agent"]
    if budget <= 0:
        return False, spent(name), 0.0
    used = spent(name)
    return used >= budget, used, budget


# ------------------------------------------------------------------------------ housekeeping


def rotate(path: str, *, mb: int, keep: int) -> bool:
    """Roll one log if it has grown too big. Returns whether it rolled.

    `.1` is newest. The oldest is deleted rather than kept forever: these are transcripts of
    machine chatter, and the normalized stream is the record worth keeping.
    """
    if mb <= 0 or keep <= 0:
        return False
    try:
        if os.path.getsize(path) <= mb * 1024 * 1024:
            return False
    except OSError:
        return False

    oldest = f"{path}.{keep}"
    try:
        if os.path.exists(oldest):
            os.remove(oldest)
    except OSError:
        pass
    for n in range(keep - 1, 0, -1):
        try:
            if os.path.exists(f"{path}.{n}"):
                os.replace(f"{path}.{n}", f"{path}.{n + 1}")
        except OSError:
            pass
    try:
        os.replace(path, f"{path}.1")
    except OSError:
        return False
    return True


def rotate_all(name: str, *, cfg: dict | None = None) -> list[str]:
    """Roll whichever of an agent's logs have grown. Only between turns -- a rename under a live
    writer strands it on Windows and silently orphans the inode on POSIX."""
    from . import supervisor

    if supervisor.live(name):
        return []
    s = settings(cfg)
    rolled = []
    directory = agent_dir(name)
    for filename in ("events.jsonl", "stderr.log", E.NORMALIZED):
        path = os.path.join(directory, filename)
        if rotate(path, mb=s["log_mb"], keep=s["log_keep"]):
            rolled.append(filename)
            if filename == "events.jsonl":
                E.reset_raw_cursor(name)          # the line counter now points into a different file
    return rolled


def gc(days: int = DEFAULT_GC_DAYS, *, registry: Registry | None = None,
       now: float | None = None) -> dict:
    """Prune what a finished agent left behind. Never touches a running one.

    Rotated logs and answered approvals only. The live `events.norm.jsonl` is not a candidate at
    any age: it is what `ad-fleet history` reads, and a report that silently loses last month is
    worse than a directory that is slightly too big.
    """
    from . import approval, supervisor

    cutoff = (now or time.time()) - days * 86400
    removed, kept_running = [], []
    try:
        names = [r.name for r in (registry or Registry()).sorted()]
    except RegistryError:
        names = []

    for name in names:
        if supervisor.live(name):
            kept_running.append(name)
            continue
        directory = agent_dir(name)
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            # Rotated logs only: `events.jsonl.3`, `stderr.log.1`. Never the live file.
            if not re.search(r"\.\d+$", entry):
                continue
            path = os.path.join(directory, entry)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed.append(textio.norm_path(path))
            except OSError:
                pass

    approval._prune(days)
    return {"removed": removed, "days": days, "kept_running": kept_running}
