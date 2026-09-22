"""The last hour of an agent, as sixty numbers (issue #218).

A tile says what an agent is doing *now* and carries the last forty events for its transcript.
What it could not say was the shape of the hour: whether this quiet minute follows fifty busy
ones or four hundred quiet ones, and whether the operator has already been asked something in
that time. Those are the two questions somebody scanning nine tiles is actually asking, and
"idle · 3m" answers neither.

Sixty buckets, one a minute, oldest first. Small integers and nothing else -- no text ever leaves
here, because the trace is drawn on every tile of every window several times a minute and a
transcript on that path is the payload problem this repository keeps having.
"""
from __future__ import annotations
import calendar
import time

MINUTES = 60

#: Kinds that mean the agent said something to the operator, rather than worked. Counted apart
#: because "it has been talking" and "it has been running tools" are different hours.
SAID = ("assistant_text", "said")

#: Kinds that mean it stopped and wants a person. The red minutes.
NEEDS = ("question_opened", "denied", "error")


def _seconds(ts: str) -> float:
    """A stamp as epoch seconds, or -1. `calendar.timegm`, not `time.mktime`: the stamps are UTC
    and mktime would read them as local, which puts every event an offset away from its minute."""
    if not ts:
        return -1.0
    try:
        return float(calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return -1.0


def _says(total: int, needed: int, said: int) -> str:
    """The sentence the canvas carries. A picture with no text twin is a picture a screen reader
    cannot read and a test cannot assert -- `docs/desk-rendering.md` makes that a rule."""
    if not total:
        return "nothing in the last hour"
    events = "1 event" if total == 1 else f"{total} events"
    out = f"{events} in the last hour"
    if said:
        out += f", said something {'once' if said == 1 else 'twice' if said == 2 else f'{said} times'}"
    if needed:
        out += f", needed you {'once' if needed == 1 else 'twice' if needed == 2 else f'{needed} times'}"
    return out


def trace(events, *, now: float | None = None, minutes: int = MINUTES) -> dict:
    """The last `minutes` minutes of a stream, bucketed.

    `n` is how many events landed in each minute and `needs` is 1 where at least one of them was
    an agent stopping for a person. Both are the same length and both are oldest first, so the
    canvas draws them left to right without needing to know what o'clock it is.
    """
    at = time.time() if now is None else float(now)
    # The bucket boundaries are whole minutes back from now, so a bar does not change width as the
    # second hand moves -- only the whole row shifts when a minute turns over.
    edge = int(at // 60) * 60
    first = edge - (minutes - 1) * 60

    counts = [0] * minutes
    needs = [0] * minutes
    total = said_n = needed_n = 0
    for ev in events or ():
        when = _seconds(ev.get("ts", ""))
        if when < first or when >= edge + 60:
            continue
        slot = int((when - first) // 60)
        if slot < 0 or slot >= minutes:
            continue
        kind = ev.get("kind", "")
        counts[slot] += 1
        total += 1
        if kind in SAID:
            said_n += 1
        if kind in NEEDS:
            if not needs[slot]:
                needed_n += 1
            needs[slot] = 1
    return {"minutes": minutes, "n": counts, "needs": needs,
            "total": total, "needed": needed_n, "said": said_n,
            "peak": max(counts) if counts else 0,
            "says": _says(total, needed_n, said_n)}


def blank(minutes: int = MINUTES) -> dict:
    """An hour with nothing in it. What a repository with no stream gets, so the page never has to
    ask whether the key is there."""
    return {"minutes": minutes, "n": [0] * minutes, "needs": [0] * minutes,
            "total": 0, "needed": 0, "said": 0, "peak": 0,
            "says": "nothing in the last hour"}
