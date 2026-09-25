"""Definitions of run and dispatch across the fleet.

A run begins at every `started` event (fresh launches, replies, and restarts).
A dispatch is a run whose `started` event is not `resumed`.
"""
from __future__ import annotations


def is_run_start(event: dict) -> bool:
    """Does this event begin a run?"""
    return event.get("kind") == "started"


def is_dispatch_start(event: dict) -> bool:
    """Does this event begin a dispatch (a fresh start, not a resumed turn)?"""
    return is_run_start(event) and not bool((event.get("data") or {}).get("resumed"))


def count_runs(stream: list[dict]) -> int:
    """Number of runs in an event stream."""
    return sum(1 for e in stream if is_run_start(e))


def count_dispatches(stream: list[dict]) -> int:
    """Number of dispatches in an event stream."""
    return sum(1 for e in stream if is_dispatch_start(e))


def is_session_start(event: dict) -> bool:
    """Does this `started` begin a *session* (#499)?

    A Send and a Reset write `started` with `resumed: true`, so every one of them is a run and none
    is a session. A session begins at a `started` that is not a resume, or is marked `new`, or
    adopted a session from outside -- the rule `supervisor.session_id()` uses. A console resume is
    a resume.
    """
    if not is_run_start(event):
        return False
    data = event.get("data") or {}
    return bool(not data.get("resumed") or data.get("new") or data.get("adopted") or data.get("external"))


def session_start(stream: list[dict]) -> dict:
    """The newest `started` that began a session, or `{}` when it has rolled out of the stream."""
    for event in reversed(stream or []):
        if is_session_start(event):
            return event
    return {}
