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

Issue: https://github.com/agentchieflou/this-next-please/issues/227
"""
from __future__ import annotations

import os
import time

from agentdata.fleet import adopt as A, sessions as SESS
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_console import _line, fleet_home  # noqa: F401 - fixture


def test_a_session_file_stamped_a_tick_ahead_of_the_clock_is_just_now(fleet_home, tmp_path):
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    d = os.path.join(SESS.session_state_dir(), "sess-own")
    os.makedirs(d)
    with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"cwd: {path}\n")
    file = os.path.join(d, "events.jsonl")
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.message", content="thinking out loud", model="m", toolRequests=[]))
    ahead = time.time() + 0.015                  # one coarse Windows clock tick
    os.utime(file, (ahead, ahead))

    rows = SESS.session_files(path)
    assert rows and rows[0]["log_age_s"] == 0.0, rows
    assert A.fresh_session_file(path) is not None
