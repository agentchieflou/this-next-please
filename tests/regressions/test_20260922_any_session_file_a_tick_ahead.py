"""2026-09-22, the Windows 3.12 CI leg: a console written a moment ago was not offered for adoption.

Symptom (`windows · python 3.12`, on #228 and again on #259, passing on the next run):

    offers = {c["repo"]: c for c in A.candidates(Registry(), processes=[])}
>   assert offers["luna"]["how"] == "matched by session file"
E   KeyError: 'luna'

Python 3.12's `time.time()` on Windows ticks every ~15.6 ms, while NTFS stamps a file with the
precise time, so a session file written a moment ago can read as a few milliseconds in the FUTURE.
`sessions.session_files` reported that as a negative `log_age_s`, `adopt.fresh_session_file`
requires `0 <= log_age_s`, and the checkout was not offered. From 3.13 `time.time()` is precise,
which is why only the 3.12 leg ever saw it. A stamp a tick ahead of the clock is "just now".

The clock is frozen while the file is read (#452). The first version stamped the file 15 ms ahead
of the real clock and read it with the real clock still running, so a worker descheduled for more
than 15 ms between the stamp and the read saw a file honestly in the past (`log_age_s` 0.032) and
failed. With the clock held one tick behind the stamp, the file is ahead of it on every run, however
long the read takes, and the unclamped age is exactly -0.015.

Issue: https://github.com/agentchieflou/this-next-please/issues/227
"""
from __future__ import annotations

import os
import time

from agentdata.fleet import adopt as A, sessions as SESS
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_console import _line, fleet_home  # noqa: F401 - fixture

TICK = 0.015  # one coarse Windows clock tick


def test_a_session_file_stamped_a_tick_ahead_of_the_clock_is_just_now(fleet_home, tmp_path, monkeypatch):
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    d = os.path.join(SESS.session_state_dir(), "sess-own")
    os.makedirs(d)
    with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"cwd: {path}\n")
    file = os.path.join(d, "events.jsonl")
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.message", content="thinking out loud", model="m", toolRequests=[]))
    now = time.time()
    os.utime(file, (now + TICK, now + TICK))
    assert os.path.getmtime(file) > now, "the file system kept the stamp ahead of the clock"

    with monkeypatch.context() as m:
        # the coarse clock: it reads `now` until the tick, however long the read below takes
        m.setattr(SESS.time, "time", lambda: now)
        rows = SESS.session_files(path)
        offered = A.fresh_session_file(path)
    assert rows and rows[0]["log_age_s"] == 0.0, rows
    assert offered is not None
