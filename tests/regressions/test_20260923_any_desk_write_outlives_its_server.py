"""2026-09-23, the Windows CI leg: a slow desk.json write stalled every desk request, and outlived its server.

Symptom (four different tests on `windows · python 3.14`, each passing on the next run):

    Page.wait_for_selector: Timeout 10000ms exceeded.
      - waiting for locator(".tile") to be visible
    AssertionError: assert 'focused' in 'layout-grid'
    AssertionError: {'image': 'none', 'width': 'auto'}
    assert ('"kind": "assistant_text"' in 'id: luna:1\\nevent: agent ...')

and in the captured stderr, every time, a desk answer written only after the browser had gone:
`ConnectionAbortedError: [WinError 10053]` from `_send`.

Two faults, reproduced on Linux by making `desk.json`'s replace take 1.5 s, which is what one
`textio._replace_with_retry` costs on Windows while the antivirus holds the freshly written file:

1. `_save_desk()` wrote the file while holding `_desk_lock`, and every desk read -- a snapshot, the
   stream's tick, `fold_due` -- takes that lock. One slow write held up every request on the desk.
2. The handler threads are daemons, and the standard library's `server_close` joins only
   non-daemon ones. A write still in flight when a test closed its server carried on into the
   NEXT test's desk: its zoom, its fold slot, its fleet directory. #227's leading candidate, now
   shown.

Issue: https://github.com/agentchieflou/this-next-please/issues/227
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

import pytest

from agentdata import textio
from agentdata.fleet import serve as S

from test_fleet_column import _repos, fleet_home  # noqa: F401 - fixtures

SLOW_S = 1.0


@pytest.fixture()
def slow_desk_writes(monkeypatch):
    """desk.json's replace takes `SLOW_S`, as it does on Windows while the file is being scanned.
    `started` is set once a slow write is under way."""
    real = textio._replace_with_retry
    started = threading.Event()

    def slow(tmp, path):
        if os.path.basename(path) == S.DESK_FILE:
            started.set()
            time.sleep(SLOW_S)
        return real(tmp, path)

    monkeypatch.setattr(textio, "_replace_with_retry", slow)
    return started


def test_a_slow_desk_write_does_not_hold_up_a_read(fleet_home, tmp_path, slow_desk_writes):
    _repos(tmp_path, "alpha", "beta")
    writer = threading.Thread(target=S.update_window, args=("main",), kwargs={"open": "alpha"})
    writer.start()
    assert slow_desk_writes.wait(5), "the write never started"

    t0 = time.monotonic()
    state = S.desk_state()
    S.fold_due()
    took = time.monotonic() - t0
    writer.join(5)

    assert took < SLOW_S / 4, f"a read waited {took:.2f}s behind a desk.json write"
    assert state["windows"]["main"]["open"] == "alpha", "the change is in memory before it is on disk"


def test_writes_land_in_the_order_the_changes_were_made(fleet_home, tmp_path):
    _repos(tmp_path, "alpha")
    with S._desk_lock:
        S._selection["selected"] = "first"
        older = S._desk_snapshot()
        S._selection["selected"] = "second"
        newer = S._desk_snapshot()
    S._write_desk(newer)
    S._write_desk(older)                     # arrives late, and must not roll the file back
    with open(older[0], encoding="utf-8") as f:
        assert json.load(f)["selected"] == "second"


def test_closing_the_desk_waits_for_a_request_still_being_answered(fleet_home, tmp_path, slow_desk_writes):
    _repos(tmp_path, "alpha", "beta")
    server, token = S.build(0)
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    serving.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/window?t={token}"
    body = json.dumps({"w": "main", "open": "beta"}).encode("utf-8")

    def post():
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except OSError:
            pass

    client = threading.Thread(target=post, daemon=True)
    client.start()
    assert slow_desk_writes.wait(5), "the write never started"

    server.stopping.set()
    server.shutdown()
    server.server_close()

    assert not [t for t in server.handlers if t.is_alive()], \
        "a request was still being answered after the server had closed"
    with open(os.path.join(str(fleet_home), S.DESK_FILE), encoding="utf-8") as f:
        assert json.load(f)["windows"]["main"]["open"] == "beta"
    client.join(5)
