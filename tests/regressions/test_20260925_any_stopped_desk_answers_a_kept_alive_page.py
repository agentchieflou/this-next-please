"""2026-09-25, any: a closed desk server went on answering a page that kept its connection open.

Symptom (#298's shuffled run at b202830, after the test itself had timed out with its page still open
in a module-scoped browser):

    _ ERROR at teardown of test_choosing_and_leaving_at_once_never_paints_the_old_skin _
    this test left a desk server thread running: Thread-7831 (process_request_thread),
    Thread-7835 (process_request_thread), Thread-7901 (process_request_thread)
    --- Thread-7831 (process_request_thread)
      File "/usr/lib/python3.13/http/server.py", line 415, in handle_one_request
        self.raw_requestline = self.rfile.readline(65537)
      File "/usr/lib/python3.13/socket.py", line 719, in readinto
        return self._sock.recv_into(b)

HTTP/1.1 keeps a connection open between requests, and its handler waits in `readline` for the next
one. Closing the server set `stopping`, which ends streams, and closed the listening socket, which
refuses new connections -- neither reaches that wait. So `server_close()` waited its full five
seconds and returned with the handler alive, and the next request the page sent on that connection
was answered, from whatever fleet directory and desk the process had moved on to: reproduced, a
stopped desk answered `/api/fleet` with the next test's agent and wrote that agent's cursor, events
and spend into the next test's fleet directory. #227's mechanism, through a connection rather than
a timer.

Issue: https://github.com/agentchieflou/this-next-please/issues/227
"""
from __future__ import annotations

import http.client
import threading

import pytest

from agentdata.fleet import serve as S

from test_fleet_ink import fleet_home  # noqa: F401 - fixtures


def test_closing_the_desk_ends_a_connection_a_page_kept_open(fleet_home):
    server, _token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", "/api/ping")
    first = conn.getresponse()
    first.read()
    assert first.status == 200 and not first.will_close, "the connection is kept open, as a browser keeps it"

    server.stopping.set()
    server.shutdown()
    server.server_close()

    assert not [t for t in server.handlers if t.is_alive()], \
        "a kept-alive connection's handler outlived its server"
    with pytest.raises((http.client.HTTPException, OSError)):
        conn.request("GET", "/api/ping")
        conn.getresponse().read()
    conn.close()
