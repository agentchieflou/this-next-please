"""2026-09-26, CI `ubuntu-latest · python 3.14` on train 9's merge: a load record nobody sent.

Symptom, as the runner printed it (run 36242056205):

    AssertionError: assert ['desk', 'set... 'desk', None] == ['desk', 'settings', 'desk']
    posts = [{'page': 'desk', ...}, ..., {}]
    agentdata.fleet.loads.LoadError: not a shell name: 'None'
    ...
    BrokenPipeError: [Errno 32] Broken pipe

The fourth `/api/load` the server acted on was `{}`: no page, no origin, no shell, and its sender was
gone before the answer was written. The page never posts an empty record (both of its senders post
`record()`); what reached `act` was a request whose headers arrived and whose body never did. `do_POST`
read `self.rfile.read(length) or b"{}"`, and a read that meets the end of the connection returns `b""`,
so a request cut off after its headers was acted on as an empty object. A body cut off part way was
already refused (not JSON); a body that never started was not.

The fix: a body shorter than its `Content-Length` is a request that never arrived. The server acts on
nothing and answers nothing, because nobody is left to read the answer.

Issue: https://github.com/agentchieflou/this-next-please/issues/584
"""
from __future__ import annotations

import json
import socket
import time

import pytest

from agentdata import config as C
from agentdata.fleet import loads as L
from agentdata.fleet import serve as S

from test_fleet_ink import _serve, _stop, fleet_home  # noqa: F401 - fixtures

RECORD = {"page": "desk", "from": "", "shell": "browser", "how": "navigate", "origin_ms": 0.0,
          "first_paint_ms": 120.4, "longest_task_ms": 0, "fleet_ms": 88.1, "skin_first": "", "skin_settled": "",
          "ua": "Mozilla/5.0"}


@pytest.fixture()
def acted(monkeypatch):
    """Every action the server took, with the body it acted on."""
    got: list[tuple[str, dict]] = []
    act = S.act

    def counting(what, body):
        got.append((what, dict(body)))
        return act(what, body)
    monkeypatch.setattr(S, "act", counting)
    return got


def _post(port: int, token: str, length: int, body: bytes) -> bytes:
    """One POST to `/api/load` that promises `length` bytes and sends `body`, then stops writing. Returns
    everything the server answered, read until it closed the connection: the handler has finished."""
    head = (f"POST /api/load?t={token} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Type: text/plain;charset=UTF-8\r\nContent-Length: {length}\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(head + body)
        s.shutdown(socket.SHUT_WR)
        answer = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                return answer
            answer += chunk


def test_a_load_post_cut_off_after_its_headers_is_not_acted_on(fleet_home, acted):  # noqa: F811
    C.save({"fleet": {"loads": {"enabled": True}}})
    server, token, port = _serve()
    try:
        record = {**RECORD, "origin_ms": round(time.time() * 1000 - 5000, 1)}   # a page opened 5 s ago
        whole = json.dumps(record).encode("utf-8")

        # Headers, then nothing: the connection ends where the body should begin.
        assert _post(port, token, len(whole), b"") == b""
        # Headers and half a body.
        assert _post(port, token, len(whole), whole[: len(whole) // 2]) == b""
        assert acted == [], acted

        # The control: the same request, whole, is acted on and kept.
        answer = _post(port, token, len(whole), whole)
        assert answer.startswith(b"HTTP/1.1 200"), answer[:200]
        assert acted == [("load", record)]
        assert [r["page"] for r in L.load()] == ["desk"]
    finally:
        _stop(server)
