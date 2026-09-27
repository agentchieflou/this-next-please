"""Throwaway (#603): what a loopback connect gets when the listener's accept queue is full.

For backlog 5 (socketserver's default) and 128, a listener that never accepts is sent N concurrent
non-blocking connects; each one's outcome (connected, or the errno) is counted. Then the same with
blocking connects that time out, one at a time."""
import collections
import errno
import select
import socket
import sys
import time


def burst(backlog: int, n: int = 64):
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(backlog)
    port = ls.getsockname()[1]
    outcomes = collections.Counter()
    socks = []
    for _ in range(n):
        s = socket.socket()
        s.setblocking(False)
        rc = s.connect_ex(("127.0.0.1", port))
        socks.append((s, rc))
    deadline = time.monotonic() + 5
    for s, rc in socks:
        if rc in (0,):
            outcomes["connected at once"] += 1
            continue
        if rc not in (errno.EINPROGRESS, errno.EWOULDBLOCK, 10035, 115):
            outcomes[f"connect_ex {rc} {errno.errorcode.get(rc, '')}"] += 1
            continue
        left = max(0.0, deadline - time.monotonic())
        _, w, x = select.select([], [s], [s], left)
        if not w and not x:
            outcomes["still pending after 5 s"] += 1
            continue
        err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        outcomes["connected" if err == 0 else f"SO_ERROR {err} {errno.errorcode.get(err, '')}"] += 1
    for s, _ in socks:
        s.close()
    ls.close()
    return outcomes


for backlog in (5, 128):
    print(f"backlog {backlog}, 64 concurrent connects, never accepted: {dict(burst(backlog))}")
    sys.stdout.flush()
