"""One place a swallowed exception can go, so "we ignore this on purpose" stays checkable.

There are ~180 `except Exception` handlers in this package, and most are right: a missing optional
tool, a console API that is not there, a config file someone deleted. What is wrong is that when one
of them swallows something unexpected, there is nothing to look at — the symptom arrives three steps
later as an empty result.

`debug_exc()` costs nothing in normal use (it returns immediately unless `AGENTDATA_DEBUG=1`) and,
when the flag is set, appends the traceback to `.agent/out/agentdata-debug.log`. It never raises: a
logger that can fail inside an exception handler is a new bug in the same place.
"""
from __future__ import annotations
import os
import sys
import traceback
from datetime import datetime

ENV_FLAG = "AGENTDATA_DEBUG"
LOG_PATH = os.path.join(".agent", "out", "agentdata-debug.log")


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def debug_exc(where: str, exc: BaseException | None = None) -> None:
    """Record a swallowed exception. Silent unless AGENTDATA_DEBUG=1; never raises."""
    if not enabled():
        return
    try:
        exc = exc or sys.exc_info()[1]
        if exc is None:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"--- {stamp} {where}\n{text}\n")
    except Exception:  # noqa: BLE001  a logger must never add a failure to the one it is recording
        pass
