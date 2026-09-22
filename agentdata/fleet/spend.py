"""One arithmetic for what an agent has cost, and one reader for it.

The unit is **premium requests**, because that is the only cost unit anything here has measured
(`docs/fleet-spike.md` §Cost). There are no tokens and no dollars in the Copilot CLI's stream, so
there are none here either.

Before this module there were two answers to "what has this agent spent", in two files, printed
side by side under one column name:

* `agentstate.Fold` took the **maximum** of every `cost` event, because the CLI reports a session
  total so far and adding checkpoints up would multiply the bill;
* `supervisor.agent_state` took the **sum** of `result.usage.premiumRequests` over the raw stream.

`ad-fleet status` printed the second; the tile, the history, the sessions list and the budget used
the first. Same name, two numbers. The rule is written once here and everything that prints a
number calls it:

```
per session   the high-water mark of the cost events that name it   (max -- checkpoints are totals)
per agent     the sum over its sessions                             (sessions do not overlap)
per day       the sum of the RISES: a session's mark going from a   (so a session that spans
              to b spends b - a on the day the event carrying b      midnight is not counted twice
              was written                                            on either day)
per fleet     the sum over agents, for a day or for all time
```

**What is deliberately not decided here.** Whether `result.usage.premiumRequests` is a turn's or
the whole session's is *unmeasured*: the spike says "exact and per-turn"
(`docs/fleet-spike.md`:187) and `docs/fleet-events.md` §cost says it is the session total so far,
and the fake transcript makes the two equal, so nothing in the repository can tell them apart. Both
sources fold with the max rule until the laptop answers M1. The `source` the event now carries is
what lets that rule change for `result` alone, later, without re-reading a byte of what is already
written.
"""
from __future__ import annotations
import json
import os
import re

# A cost event that arrived before any session announced itself. It still happened and it was still
# spent, so it is kept under a name rather than dropped -- a number that quietly excludes some of
# the bill is worse than one that says it does not know whose it was.
UNKNOWN = "(no session)"


def _number(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _blank_session() -> dict:
    return {"premium": 0.0, "turns": 0, "first": "", "last": "",
            "model": "", "ticket": "", "ended": ""}


def blank() -> dict:
    """An empty ledger. `session` and `turn_closed` are the fold's own place-keeping, carried in
    the state so that folding the next thousand events continues where the last fold stopped --
    which is what makes the ledger on disk equal to a fold of everything, and what makes a rotated
    log cost nothing."""
    return {"sessions": {}, "days": {}, "session": "", "turn_closed": False,
            "cursor": {"seq": 0}}


def advance(state: dict, events: list[dict]) -> dict:
    """Fold `events` into `state`, in place, continuing from wherever it left off.

    Incremental by construction: `fold(a + b)` and `advance(advance(blank(), a), b)` are the same
    ledger. That is the property the whole design rests on -- it is why the number survives a log
    rotation, and why `--rebuild` can be compared against what was written a day at a time.
    """
    sessions = state.setdefault("sessions", {})
    days = state.setdefault("days", {})
    current = str(state.get("session") or "")
    turn_closed = bool(state.get("turn_closed"))
    seq = int((state.get("cursor") or {}).get("seq") or 0)

    for ev in events:
        kind = ev.get("kind")
        data = ev.get("data") or {}
        stamp = str(ev.get("ts") or "")
        day = stamp[:10]
        seq = max(seq, int(ev.get("seq") or 0))

        if kind == "started":
            # A fresh dispatch: whatever session it resumes announces itself in a moment, and until
            # it does this run's events belong to no session we can name yet.
            current = str(data.get("session") or "")
            turn_closed = False
        elif kind == "session_id":
            said = str(data.get("session") or "")
            if said:
                current = said
        elif kind == "cost":
            value = _number(data.get("premium_requests"))
            if value is None:
                continue
            row = sessions.setdefault(current or UNKNOWN, _blank_session())
            # The max, never a sum: a checkpoint is the session's total so far, and adding two of
            # them together bills the same work twice. The RISE is what a day is charged, so a
            # session running over midnight is not counted whole on both sides of it.
            if value > row["premium"]:
                rise = value - row["premium"]
                row["premium"] = round(value, 2)
                if day:
                    bucket = days.setdefault(day, {"premium": 0.0, "turns": 0})
                    bucket["premium"] = round(bucket["premium"] + rise, 2)
        elif kind == "turn_ended":
            turn_closed = True
            sessions.setdefault(current or UNKNOWN, _blank_session())["turns"] += 1
            if day:
                days.setdefault(day, {"premium": 0.0, "turns": 0})["turns"] += 1
        elif kind == "assistant_text":
            model = str(data.get("model") or "").strip()
            if model:
                sessions.setdefault(current or UNKNOWN, _blank_session())["model"] = model
        elif kind in ("exited", "error"):
            row = sessions.setdefault(current or UNKNOWN, _blank_session())
            row["ended"] = "finished" if kind == "exited" else "fell over"
            # A headless `copilot -p` runs one turn per process, and a stream carrying no
            # `assistant.turn_end` still ended a turn when the process did. Counted only when the
            # run did not already announce one, so a normal stream is never counted twice.
            if not turn_closed:
                row["turns"] += 1
                if day:
                    days.setdefault(day, {"premium": 0.0, "turns": 0})["turns"] += 1
            turn_closed = False

        # Dating a session, but never CREATING one for a run that has not announced its id yet: a
        # nameless empty row would appear in every list of sessions as a session nobody had.
        row = sessions.setdefault(current, _blank_session()) if current \
            else sessions.get(UNKNOWN)
        if row is not None and stamp:
            row["first"] = row["first"] or stamp
            row["last"] = stamp
            if ev.get("ticket"):
                row["ticket"] = str(ev["ticket"])

    state["session"] = current
    state["turn_closed"] = turn_closed
    state["cursor"] = {"seq": seq}
    return state


def fold(events: list[dict]) -> dict:
    """`{"sessions": {id: {...}}, "days": {"YYYY-MM-DD": {...}}, ...}` from a normalized stream.

    Pure: no I/O, no clock, no config. Everything that prints a spend calls this, so a change to
    the rule is a change in one place and every printer follows it.
    """
    return advance(blank(), events)


def total(folded: dict) -> float:
    """What this agent has spent, over every session it has had."""
    return round(sum(row["premium"] for row in (folded.get("sessions") or {}).values()), 2)


def turns(folded: dict) -> int:
    return sum(row["turns"] for row in (folded.get("sessions") or {}).values())


def on_day(folded: dict, day: str) -> float:
    return round(((folded.get("days") or {}).get(day) or {}).get("premium", 0.0), 2)


# --------------------------------------------------------------- the CLI's own final usage


def from_usage_file(path: str) -> float | None:
    """What `--usage-output-file` says the session cost, or None.

    The spike called this "a simpler cost hook than parsing the stream"
    (`docs/fleet-spike.md`:199). The fleet has passed the flag on every launch since #93 and the
    file it writes has had no reader at all. It is read here for ONE purpose: to disagree out loud
    with the stream when the two do not match, which is the measurement M1 needs.
    """
    import json
    import os

    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    for key in ("premiumRequests", "totalPremiumRequests", "premium_requests"):
        value = _number(raw.get(key))
        if value is not None:
            return value
    usage = raw.get("usage")
    if isinstance(usage, dict):
        return _number(usage.get("premiumRequests"))
    return None


def disagreement(folded: dict, usage_total: float | None, *, tolerance: float = 0.005) -> dict:
    """`{}` when the CLI's own final usage and the stream agree, or what the gap is.

    Never picks a winner. Which of the two is right is unmeasured (M1), and a reader that silently
    preferred one would be deciding an open question by writing code.
    """
    if usage_total is None:
        return {}
    stream = total(folded)
    if abs(stream - usage_total) <= tolerance:
        return {}
    return {"stream": stream, "file": round(usage_total, 2),
            "delta": round(usage_total - stream, 2)}


# ------------------------------------------------------------------------------ the ledger

LEDGER = "spend.json"
SCHEMA = 1


def ledger_path(name: str) -> str:
    from .registry import agent_dir

    return os.path.join(agent_dir(name), LEDGER)


def read_ledger(name: str) -> dict:
    """What has been folded so far, or an empty ledger. Never raises: a ledger that cannot be read
    is a number that has to be rebuilt, not a dashboard that will not draw."""
    try:
        with open(ledger_path(name), encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return blank()
    if not isinstance(raw, dict) or int(raw.get("schema") or 0) != SCHEMA:
        return blank()
    out = blank()
    out.update({k: raw[k] for k in ("sessions", "days", "session", "turn_closed", "cursor")
                if k in raw})
    out["sessions"] = {str(k): dict(_blank_session(), **v)
                       for k, v in (out.get("sessions") or {}).items() if isinstance(v, dict)}
    return out


def write_ledger(name: str, state: dict) -> str:
    from .registry import agent_dir

    directory = agent_dir(name)
    os.makedirs(directory, exist_ok=True)
    path = ledger_path(name)
    body = {"schema": SCHEMA, "sessions": state.get("sessions") or {},
            "days": state.get("days") or {}, "session": state.get("session") or "",
            "turn_closed": bool(state.get("turn_closed")),
            "cursor": state.get("cursor") or {"seq": 0}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(body, handle, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return path


def update(name: str) -> dict:
    """Fold whatever has arrived since last time into this agent's ledger, and save it.

    Called on every `events.refresh`, so it costs one read of what the tick has just read anyway,
    and -- crucially -- called by `lifecycle.rotate_all` BEFORE the normalized log is rolled. That
    is the bug this exists for: rotation moved `events.norm.jsonl` aside and `events.read` opens
    only the live file, so at `fleet.log_mb` an agent's spend silently dropped to zero, the budget
    re-opened, and `ad-fleet history` forgot everything before the roll.
    """
    from . import events as E

    state = read_ledger(name)
    since = int((state.get("cursor") or {}).get("seq") or 0)
    try:
        fresh = E.read(name, since=since)
    except (OSError, ValueError):
        return state
    if not fresh:
        return state
    advance(state, fresh)
    try:
        write_ledger(name, state)
    except OSError:
        pass                                  # a ledger that cannot be written is rebuildable
    return state


def rebuild(name: str) -> dict:
    """Fold every normalized log this agent has on disk, oldest first, and save that.

    The answer must equal the incremental ledger. It is the check on the whole design, and it is
    what makes the ledger a fold rather than a source: nothing here is unrecoverable.
    """
    from . import events as E
    from .registry import agent_dir

    directory = agent_dir(name)
    live = E.NORMALIZED
    rolled = []
    try:
        for entry in os.listdir(directory):
            match = re.fullmatch(re.escape(live) + r"\.(\d+)", entry)
            if match:
                rolled.append((int(match.group(1)), entry))
    except OSError:
        pass
    # `.1` is the NEWEST rotation, so the oldest file is the highest number: read them descending,
    # then the live file last.
    order = [name for _, name in sorted(rolled, reverse=True)] + [live]

    state = blank()
    for filename in order:
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            continue
        advance(state, _read_jsonl(path))
    try:
        write_ledger(name, state)
    except OSError:
        pass
    return state


def _read_jsonl(path: str) -> list[dict]:
    from .. import textio

    out = []
    try:
        text = textio.read_text(path)
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def for_agent(name: str) -> dict:
    """This agent's ledger, brought up to date. What every printer of a number calls."""
    return update(name)


# ------------------------------------------------------------------------- what a tile shows


def per_turn(folded: dict) -> float:
    """The mean cost of a turn, over every turn this agent has had.

    A MEAN, and said to be one wherever it is printed. It is not a forecast: turns differ by an
    order of magnitude (the spike measured 0.33 for a trivial reply and 1.00 for one allowed shell
    tool), so a number dressed up as "what the next turn will cost" would be a guess with a
    decimal point on it.
    """
    n = turns(folded)
    return round(total(folded) / n, 2) if n else 0.0


def for_tile(name: str, *, budget: float = 0.0, today: str = "") -> dict:
    """What the tile's spend cell draws: this agent, its session, its day, against its budget."""
    led = for_agent(name)
    current = str(led.get("session") or "")
    session_row = (led.get("sessions") or {}).get(current) or {}
    return {"total": total(led), "turns": turns(led),
            "session": round(session_row.get("premium", 0.0), 2),
            "today": on_day(led, today) if today else 0.0,
            "budget": round(float(budget or 0.0), 2),
            "rate": per_turn(led),
            "sessions": len(led.get("sessions") or {})}


def for_fleet(names: list, *, today: str = "") -> dict:
    """Every agent summed, for a day and for all time, with the age of the oldest ledger in it.

    `ad-fleet status`'s `spent_today` was the sum of every agent's LIFETIME mark under a name that
    said today. This is the number that name was always claiming to be.
    """
    rows, all_time, day_total, oldest = [], 0.0, 0.0, ""
    for name in names:
        led = for_agent(name)
        mine = total(led)
        rows.append({"repo": name, "premium_requests": mine, "turns": turns(led),
                     "today": on_day(led, today) if today else 0.0})
        all_time += mine
        day_total += on_day(led, today) if today else 0.0
        last = str((led.get("sessions") or {}).get(str(led.get("session") or ""), {}).get("last", ""))
        if last and (not oldest or last < oldest):
            oldest = last
    return {"repos": rows, "today": round(day_total, 2), "all_time": round(all_time, 2),
            "as_of": oldest}
