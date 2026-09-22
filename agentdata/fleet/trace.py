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


#: Parsed stamps, kept between folds. The same second recurs across every poll of every window,
#: and `strptime` is the most expensive thing in this module by an order of magnitude. Bounded
#: rather than unbounded: a day is 86,400 distinct seconds and this is a dashboard, not a store.
_SECONDS_CACHE: dict[str, float] = {}
_CACHE_MAX = 20000


def _seconds(ts: str) -> float:
    """A stamp as epoch seconds, or -1.

    `calendar.timegm`, not `time.mktime`: the stamps are UTC and mktime would read them as local,
    which puts every event an offset away from its minute.

    The fixed-width form is sliced rather than parsed. `events.stamp()` writes exactly
    `YYYY-MM-DDTHH:MM:SS` and nothing else, and `strptime` re-reads that format string for every
    one of tens of thousands of events; `int()` on seven slices is the same answer for a tenth of
    the cost. Anything that does not fit the shape falls back to the parser rather than guessing.
    """
    if not ts:
        return -1.0
    got = _SECONDS_CACHE.get(ts)
    if got is not None:
        return got
    text = str(ts)[:19]
    out = -1.0
    if len(text) == 19 and text[4] == "-" and text[7] == "-" and text[13] == ":":
        try:
            out = float(calendar.timegm((
                int(text[0:4]), int(text[5:7]), int(text[8:10]),
                int(text[11:13]), int(text[14:16]), int(text[17:19]), 0, 1, -1)))
        except (ValueError, TypeError):
            out = -1.0
    if out < 0:
        try:
            out = float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%S")))
        except (ValueError, TypeError):
            out = -1.0
    if len(_SECONDS_CACHE) >= _CACHE_MAX:
        _SECONDS_CACHE.clear()
    _SECONDS_CACHE[ts] = out
    return out


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


#: How many events older than the window to see before giving up on the rest of the stream.
#: The scan runs backwards because a stream is chronological and an hour is its tail -- but
#: "chronological" is arrival order, and a Copilot log replayed out of a file can carry a handful
#: of stamps that step backwards. A short run of them does not end the scan; a long one does,
#: because past that the stream really is older than the hour.
STOP_AFTER = 64


def trace(events, *, now: float | None = None, minutes: int = MINUTES) -> dict:
    """The last `minutes` minutes of a stream, bucketed.

    `n` is how many events landed in each minute and `needs` is 1 where at least one of them was
    an agent stopping for a person. Both are the same length and both are oldest first, so the
    canvas draws them left to right without needing to know what o'clock it is.

    Scanned from the newest event backwards and stopped once the stream is properly out of the
    window. This is on every row of every snapshot, several times a second, and an agent that has
    been running all day has tens of thousands of events: parsing every stamp in all of them to
    find the last sixty minutes would be the most expensive thing the server does.
    """
    at = time.time() if now is None else float(now)
    # The bucket boundaries are whole minutes back from now, so a bar does not change width as the
    # second hand moves -- only the whole row shifts when a minute turns over.
    edge = int(at // 60) * 60
    first = edge - (minutes - 1) * 60

    counts = [0] * minutes
    needs = [0] * minutes
    total = said_n = needed_n = 0
    old_run = 0
    rows = events or ()
    for i in range(len(rows) - 1, -1, -1):
        ev = rows[i]
        when = _seconds(ev.get("ts", ""))
        if when < first:
            old_run += 1
            if old_run >= STOP_AFTER:
                break
            continue
        old_run = 0
        if when >= edge + 60:
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
