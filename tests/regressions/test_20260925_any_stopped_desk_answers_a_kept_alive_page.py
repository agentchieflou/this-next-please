"""2026-09-25, any: a closed desk server went on answering a page that kept its connection open.

Symptom (#298's thread guard, twice, at teardown of the #513 test: the builder's `--shuffle-seed
20260904` run at b202830, and run 5 of the #298 investigation's A/B at 8e4095a):

    _ ERROR at teardown of test_choosing_and_leaving_at_once_never_paints_the_old_skin _
    this test left a desk server thread running: Thread-1500 (process_request_thread), Thread-1503 (process_request_thread), Thread-1532 (process_request_thread)
      File "/usr/lib/python3.13/http/server.py", line 415, in handle_one_request
        self.raw_requestline = self.rfile.readline(65537)

and, reproduced without a browser on main 7c0fb78 (one kept connection, the desk stopped as `_stop`
does, the fleet directory moved on as the next test's would be):

    server_close() returned after 5.1s; handler threads alive: ['Thread-2 (process_request_thread)']
    after stop, same connection: 200 3474 bytes; repos in the answer: ['nexttest']
    files the stopped server wrote into the next test's fleet dir: ['fleet/agents/nexttest/events.cursor.json', ...]

HTTP/1.1 keeps a connection open between requests, and its handler waits in `readline` for the next
one. Closing the server set `stopping`, which ends streams, and closed the listening socket, which
refuses new connections -- neither reaches that wait. So `server_close()` waited its full five
seconds and returned with the handler alive, and the next request the page sent on that connection
was answered from whatever fleet directory and desk the process had moved on to. #227's
contamination, through a kept connection rather than a timer.

Issue: https://github.com/agentchieflou/this-next-please/issues/515 (refs #227, #298)
"""
from __future__ import annotations

import http.client
import threading

import pytest

from agentdata.fleet import serve as S

from test_fleet_ink import fleet_home  # noqa: F401 - fixtures


def test_closing_the_desk_ends_a_connection_a_page_kept_open(fleet_home):
    _kept_connection_ends(*S.build(0))


def test_it_ends_where_a_shut_read_side_wakes_no_reader(fleet_home):
    """Windows: `shutdown(SD_RECEIVE)` does not wake a read already waiting, and train 7's Windows
    leg failed the test above with this file's message. With the shut read side taken away, the
    handler's own wait must still see `stopping` and go -- on every OS, so Linux CI guards it too."""
    server, token = S.build(0)
    server._end_reads = lambda sockets: None
    _kept_connection_ends(server, token)


def _kept_connection_ends(server, _token):
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", "/api/ping")
    first = conn.getresponse()
    first.read()
    assert first.status == 200 and not first.will_close, "the connection is kept open, as a browser keeps it"
    conn.request("GET", "/api/ping")
    again = conn.getresponse()
    again.read()
    assert again.status == 200 and not again.will_close, "a running desk answers the kept connection again"

    server.stopping.set()
    server.shutdown()
    server.server_close()

    assert not [t for t in server.handlers if t.is_alive()], \
        "a kept-alive connection's handler outlived its server"
    with pytest.raises((http.client.HTTPException, OSError)):
        conn.request("GET", "/api/ping")
        conn.getresponse().read()
    conn.close()
