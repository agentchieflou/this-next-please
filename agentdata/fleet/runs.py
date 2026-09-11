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
