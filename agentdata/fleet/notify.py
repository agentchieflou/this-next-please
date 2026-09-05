"""When to interrupt a person, and when to stay quiet.

Epic #91's acceptance is that the operator is *told, in one window, when an agent has a status
update*. The hard part is not delivery -- it is restraint. Four agents emitting a toast per tool
call is worse than no toasts at all, because the operator learns to dismiss them without reading,
and then misses the one that mattered.

So three rules govern everything here:

**Notify on transitions, never on events.** A toast per `tool_call` is noise; a toast every time
anyone looks at the current state is worse. A state *change* happens once, when it happens. That is
`agentstate.transitions`, which folds with exactly the same rules the tile is coloured by -- a
second implementation would eventually disagree with the first about whether an agent needs the
human, which is the only question the fleet exists to answer.

**Nothing fires twice.** A per-agent, per-state key with a cooldown, kept on disk, so a restarted
dashboard does not re-announce what the operator already dismissed. And a repository seen for the
first time records where its stream is and announces nothing: attaching to four agents mid-flight
must not produce forty toasts about things that already happened.

**Quiet hours downgrade, never suppress.** Out of hours the toast is withheld and the badge is
still recorded, so the morning shows what happened rather than hiding it.
"""
from __future__ import annotations
import json
import os
import time

from .. import config as C
from .. import textio
from . import agentstate, events as E
from .registry import Registry, RegistryError, fleet_dir

LOG = "notifications.jsonl"
STATE = "notify.state.json"
KEEP = 200                 # what the drawer can page back through; the page shows the last 50

DEFAULT_COOLDOWN_S = 300
DEFAULT_IDLE_MINUTES = 20

# Which agent states are worth a person's attention, and how loudly. A state not in here -- running,
# starting, and idle before it has been idle long enough -- never notifies at all.
RULES = {
    "waiting_approval": ("action", "needs approval"),
    "needs_human": ("action", "needs you"),
    "blocked": ("action", "blocked"),
    "error": ("alert", "fell over"),
    "done": ("info", "finished"),
    "idle_stalled": ("info", "stopped without finishing"),
}
SEVERITIES = ("action", "alert", "info")


# ------------------------------------------------------------------------------ configuration


def _cfg(cfg: dict | None, key: str, default):
    value = C.get(cfg if cfg is not None else C.load(), f"fleet.notify.{key}")
    return default if value is None else value


def _flag(cfg: dict | None, key: str, default: bool) -> bool:
    value = _cfg(cfg, key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _number(cfg: dict | None, key: str, default: int) -> int:
    try:
        return max(0, int(_cfg(cfg, key, default)))
    except (TypeError, ValueError):
        return default


def settings(cfg: dict | None = None) -> dict:
    return {"dashboard": _flag(cfg, "dashboard", True),
            "toast": _flag(cfg, "toast", True),
            "chime": _flag(cfg, "chime", False),
            "cooldown": _number(cfg, "cooldown", DEFAULT_COOLDOWN_S),
            "idle_minutes": _number(cfg, "idle_minutes", DEFAULT_IDLE_MINUTES),
            "quiet_hours": str(_cfg(cfg, "quiet_hours", "") or "")}


def in_quiet_hours(spec: str, when: time.struct_time | None = None) -> bool:
    """`"18:00-08:00"` -- and yes, it wraps midnight, which is the case anyone actually wants."""
    if not spec or "-" not in spec:
        return False
    start, _, end = spec.partition("-")
    try:
        s = tuple(int(x) for x in start.strip().split(":"))
        e = tuple(int(x) for x in end.strip().split(":"))
        now = when or time.localtime()
    except (TypeError, ValueError):
        return False
    if len(s) != 2 or len(e) != 2:
        return False
    minutes = now.tm_hour * 60 + now.tm_min
    a, b = s[0] * 60 + s[1], e[0] * 60 + e[1]
    return (a <= minutes < b) if a <= b else (minutes >= a or minutes < b)


# ------------------------------------------------------------------------------- the ledger


def log_path() -> str:
    return os.path.join(fleet_dir(), LOG)


def _state_path() -> str:
    return os.path.join(fleet_dir(), STATE)


def read_state() -> dict:
    try:
        return json.loads(textio.read_text(_state_path()))
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    os.makedirs(fleet_dir(), exist_ok=True)
    textio.write_text(_state_path(), json.dumps(state, indent=2, sort_keys=True) + "\n")


def read_log(limit: int = 50) -> list[dict]:
    path = log_path()
    if not os.path.isfile(path):
        return []
    out = []
    for line in textio.read_text(path).splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out[-limit:] if limit else out


def _append_log(items: list[dict]) -> None:
    if not items:
        return
    os.makedirs(fleet_dir(), exist_ok=True)
    kept = (read_log(0) + items)[-KEEP:]
    # Rewritten rather than appended so the file cannot grow without bound on a machine that is
    # never restarted. It is a drawer, not an audit log -- `events.norm.jsonl` is the record.
    textio.write_text(log_path(), "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in kept))


# ------------------------------------------------------------------------------- the rules


def notification(repo: str, state: str, why: str, *, ticket: str = "", seq: int = 0,
                 at: str = "") -> dict:
    severity, phrase = RULES[state]
    return {"repo": repo, "state": state, "severity": severity, "ticket": ticket,
            "title": f"{repo}{' · ' + ticket if ticket else ''} — {phrase}",
            "body": (why or "")[:300], "seq": seq,
            "at": at or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "key": f"{repo}:{state}"}


def scan(repo: str, events: list[dict], *, since_seq: int = 0, idle_minutes: int = DEFAULT_IDLE_MINUTES,
         live: bool = False, now: float | None = None) -> list[dict]:
    """What this agent's stream says is worth announcing, past `since_seq`.

    `since_seq` is what stops a fleet attached to four running agents from announcing everything
    that ever happened to them. The transitions before it are still computed -- the state machine
    needs the history to be correct -- they are simply not announced.
    """
    out = []
    for change in agentstate.transitions(events):
        if change["seq"] <= since_seq or change["state"] not in RULES:
            continue
        out.append(notification(repo, change["state"], change["why"], ticket=change["ticket"],
                                seq=change["seq"], at=change.get("at", "")))

    # The one rule that is not a transition: an agent holding a ticket that simply stopped. Nothing
    # happened, which is exactly why nothing would otherwise be reported.
    if not live and events and idle_minutes:
        current = agentstate.derive(events)
        idle_for = _age(events[-1].get("ts", ""), now)
        if (current["state"] == "idle" and current["ticket"]
                and idle_for >= idle_minutes * 60 and events[-1].get("seq", 0) > since_seq):
            out.append(notification(repo, "idle_stalled",
                                    f"nothing for {idle_for // 60} minutes, and {current['ticket']} "
                                    f"is still open", ticket=current["ticket"],
                                    seq=events[-1].get("seq", 0)))
    return out


def _age(stamp: str, now: float | None = None) -> int:
    import calendar

    try:
        parsed = time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return 0
    return max(0, int((now or time.time()) - calendar.timegm(parsed)))


def suppress(items: list[dict], state: dict, *, cooldown: int, now: float | None = None) -> list[dict]:
    """Drop what has already been said recently. Mutates `state` with what survives."""
    now = now or time.time()
    fired = state.setdefault("fired", {})
    out = []
    for item in items:
        last = fired.get(item["key"])
        if isinstance(last, (int, float)) and now - last < cooldown:
            continue
        fired[item["key"]] = now
        out.append(item)
    return out


# ------------------------------------------------------------------------------ the channels


def toast_status(cfg: dict | None = None) -> str:
    """`ready`, `off` or `unavailable` -- which `ad-fleet status` prints verbatim."""
    if not settings(cfg)["toast"]:
        return "off"
    if os.name != "nt":
        return "unavailable (Windows toasts; this is not Windows)"
    try:
        import windows_toasts                                     # noqa: F401
    except Exception:                                             # noqa: BLE001 - any import failure
        return 'unavailable (pip install "agentdata[fleet-win]")'
    return "ready"


def send_toast(item: dict, url: str = "") -> bool:
    """One Action Center toast. Never raises: a notifier that can crash the fleet is worse than one
    that stays quiet, and the dashboard has the same information either way."""
    try:
        from windows_toasts import Toast, WindowsToaster

        toast = Toast()
        toast.text_fields = [item["title"], item["body"]]
        if url:
            # The click takes the operator to the tile, not just to the page: with four agents,
            # "something needs you" without saying which is a notification that costs time.
            toast.launch_action = f"{url}#tile={item['repo']}"
        WindowsToaster("ad-fleet").show_toast(toast)
        return True
    except Exception:                                             # noqa: BLE001 - see the docstring
        from ..log import debug_exc

        debug_exc("fleet toast")
        return False


def deliver(items: list[dict], *, cfg: dict | None = None, url: str = "",
            when: time.struct_time | None = None) -> list[dict]:
    """Record every notification; toast the ones the rules allow. Returns them, marked up."""
    s = settings(cfg)
    quiet = in_quiet_hours(s["quiet_hours"], when)
    for item in items:
        item["quiet"] = quiet
        item["toasted"] = bool(
            s["toast"] and not quiet and toast_status(cfg) == "ready" and send_toast(item, url))
    if s["dashboard"]:
        _append_log(items)
    return items


# ------------------------------------------------------------------------------- the driver


def sweep(*, cfg: dict | None = None, url: str = "", dry_run: bool = False,
          registry: Registry | None = None, now: float | None = None) -> list[dict]:
    """Look at every registered agent once and announce what changed. The dashboard calls this on
    its own tick; `ad-fleet notify tail` calls it with `dry_run` to tune a rule without waiting."""
    from . import supervisor

    s = settings(cfg)
    state = read_state()
    seen = state.setdefault("seen", {})
    fresh: list[dict] = []
    try:
        names = [r.name for r in (registry or Registry()).sorted()]
    except RegistryError:
        names = []

    for name in names:
        stream = E.read(name)
        if not stream:
            continue
        last = stream[-1].get("seq", 0)
        if name not in seen:
            # First sight. Attaching to an agent that has been running for an hour must not
            # announce the hour; it must announce what happens next.
            if not dry_run:
                seen[name] = last
            continue
        found = scan(name, stream, since_seq=int(seen[name] or 0),
                     idle_minutes=s["idle_minutes"],
                     live=bool(supervisor.live(name)), now=now)
        if not dry_run:
            seen[name] = last
        fresh.extend(found)

    kept = suppress(fresh, state, cooldown=s["cooldown"], now=now) if not dry_run else fresh
    if not dry_run:
        write_state(state)
        deliver(kept, cfg=cfg, url=url)
    return kept


def samples() -> list[dict]:
    """One of each severity, for `ad-fleet notify test`. Real shapes, invented content."""
    return [notification("luna", "waiting_approval", "transition RDSD-101 to In Review",
                         ticket="RDSD-101"),
            notification("luna", "error", "the last turn exited 1", ticket="RDSD-101"),
            notification("luna", "done", "phase is pr_open", ticket="RDSD-101")]
