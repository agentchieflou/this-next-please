"""2026-09-24, windows · python 3.14 on PR #436 (a679398): a window write took more than five
seconds, and the stream stood still with it.

Symptom (`tests/test_fleet_desk_actions.py::test_the_tile_you_just_acted_on_does_not_vanish_after_needs_me`):

    page.wait_for_function("() => windowWrites === 0", timeout=5000)
    TimeoutError: Page.wait_for_function: Timeout 5000ms exceeded.
    --- the desk has been answering POST /api/window for 3 s; every thread ---
    Thread-2012 (POST /api/window): serve.py:1448 update_window      `with _desk_lock:`
    Thread-2017 (GET /api/events):  serve.py:970 poller              `with _desk_lock:`
    Thread-2018 (GET /api/desk):    serve.py:1029 catalogue -> catalogue.py:537 PRAGMA journal_mode = WAL

`serve.catalogue()` opened the sqlite catalogue while holding `_desk_lock`. The first open creates
the file, turns on WAL and runs the schema, which took seconds on a Windows runner that scans every
new file. Every window write, arrangement and the stream's poller waited on the same lock for all of
it, though none of them reads the catalogue. The open now happens outside the desk lock.

Here the open is held on an event rather than made slow: while it is held, a window write, an
arrangement and a desk read all still answer.

Issue: https://github.com/agentchieflou/this-next-please/issues/439
"""
from __future__ import annotations

import threading

from agentdata.fleet import catalogue as CAT, serve as S

from test_fleet_ink import _own_desk_globals, fleet_home  # noqa: F401 - fixtures

#: How long each desk call may take while the catalogue is still opening. The calls are in-memory
#: work under a lock; before the fix they did not return until the open was released.
ANSWER_S = 5.0


def test_a_window_write_does_not_wait_for_the_catalogue_to_open(fleet_home, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = CAT.Catalogue.open

    def held_open(*a, **kw):
        entered.set()
        release.wait(30)
        return real(*a, **kw)

    monkeypatch.setattr(CAT.Catalogue, "open", held_open)
    got = {}
    opener = threading.Thread(target=lambda: got.setdefault("cat", S.catalogue()), daemon=True)
    opener.start()
    try:
        assert entered.wait(10), "the catalogue open never started"

        done = {}

        def desk_calls():
            done["window"] = S.update_window("main", open="alpha")
            done["arrange"] = S.arrange(order=["alpha"])
            done["desk"] = S.desk_state()

        writer = threading.Thread(target=desk_calls, daemon=True)
        writer.start()
        writer.join(ANSWER_S)
        assert not writer.is_alive(), "a window write waited for the catalogue's sqlite open"
        assert set(done) == {"window", "arrange", "desk"}, done
    finally:
        release.set()
        opener.join(30)
    assert got.get("cat") is not None, "the catalogue did not open once it was let go"
    assert S.catalogue() is got["cat"], "a second call opened it again"
