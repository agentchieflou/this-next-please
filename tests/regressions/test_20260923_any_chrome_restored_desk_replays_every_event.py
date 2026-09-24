"""2026-09-23, Chrome, measured going /settings -> desk with 9 agents x 403 events: the desk came back
from its snapshot and asked the server for every agent's whole history again.

Symptom (the page's `EventSource` URL, and what it was sent before its first tick):

    since=proj0%3A0%2Cproj1%3A0%2Cproj2%3A0...
    agentFrames= 3627
    longtasks= [2987, 1907]

and the ink layer switched to the new skin only 5.2-7.1 s later. `restoreCached()` drew the tiles
from snapshot rows with an empty `recent`, so they were made with `seq: 0`; the real `/api/fleet`
row then took the existing-tile path, which neither appended its `recent` nor moved the cursor, and
`connect()` opened the stream from 0. A restored tile now takes its transcript and its cursor from
its first real row.

Here the fleet is small (2 agents x 60 events), because the frames are counted, not timed.

Issue: https://github.com/agentchieflou/this-next-please/issues/347
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_instant import _own_desk_globals, _serve, fleet_home  # noqa: F401 - fixtures
from test_fleet_stream_resume import browser, busy_fleet, restored, since  # noqa: F401 - fixture


@pytest.mark.browser
def test_a_desk_back_from_its_snapshot_is_not_sent_its_history_again(browser, fleet_home, tmp_path):  # noqa: F811
    newest = busy_fleet(tmp_path, names=("proj0", "proj1"), events=60)
    S.arrange(order=["proj0", "proj1"])
    server, token, port = _serve()
    try:
        back = restored(browser, port, token)
        cursors = since(back["url"])
        assert all(cursors[name] >= newest[name] for name in newest), f"asked from 0: {back['url']}"
        assert back["agent"] == 0, f"agentFrames= {back['agent']}"
        assert not back["errors"], back["errors"]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
