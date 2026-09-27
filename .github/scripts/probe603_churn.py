"""Throwaway (#603): can plain loopback connects get WSAENOBUFS (10055) on this runner, and when?

Mimics the suite: per "test" a new listener on port 0 (a new dynamic port), a burst of N concurrent
non-blocking connects to it (a page load), each accepted, then closed by the CLIENT first (a context
closed at teardown), then the listener closed. Variants change one thing each:
  client-first   the suite today: the client closes first, so its end goes to TIME_WAIT
  server-first   the server closes first (Connection: close), TIME_WAIT on the listener's end
  rst            the client closes with SO_LINGER 0: a reset, no TIME_WAIT anywhere
Counts connect outcomes per variant, and the TIME_WAIT count when a 10055 happens."""
import collections
import errno
import os
import select
import socket
import struct
import subprocess
import sys
import time

ITER = int(os.environ.get("CHURN_ITER", "1500"))
BURST = 6


def tw():
    try:
        out = subprocess.run(["netstat", "-an", "-p", "tcp"], capture_output=True, text=True, timeout=30).stdout
        return sum(1 for l in out.splitlines() if "TIME_WAIT" in l)
    except Exception:  # noqa: BLE001
        return -1


def one(variant, outcomes, events):
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(128)
    port = ls.getsockname()[1]
    cs = []
    for _ in range(BURST):
        s = socket.socket()
        s.setblocking(False)
        rc = s.connect_ex(("127.0.0.1", port))
        if rc in (0, errno.EWOULDBLOCK, 10035, errno.EINPROGRESS):
            cs.append(s)
        else:
            outcomes[f"connect_ex {rc}"] += 1
            if rc == 10055 and len(events) < 10:
                events.append((variant, port, tw()))
            s.close()
    ok = []
    for s in cs:
        _, w, x = select.select([], [s], [s], 5)
        err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) if (w or x) else -1
        if err == 0:
            outcomes["connected"] += 1
            ok.append(s)
        else:
            outcomes[f"SO_ERROR {err}"] += 1
            if err == 10055 and len(events) < 10:
                events.append((variant, port, tw()))
            s.close()
    ls.setblocking(True)
    ls.settimeout(2)
    acc = []
    for _ in ok:
        try:
            acc.append(ls.accept()[0])
        except OSError:
            outcomes["accept failed"] += 1
    for s in ok:
        s.send(b"GET / HTTP/1.1\r\n\r\n")
    for a in acc:
        try:
            a.recv(100)
            a.send(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        except OSError:
            pass
    first, second = (acc, ok) if variant == "server-first" else (ok, acc)
    if variant == "rst":
        for s in ok:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    for s in first:
        s.close()
    time.sleep(0.002)
    for s in second:
        s.close()
    ls.close()


print("excluded port ranges:")
if os.name == "nt": print(subprocess.run(["netsh", "int", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                     capture_output=True, text=True).stdout)
for variant in ("client-first", "server-first", "rst"):
    outcomes, events = collections.Counter(), []
    t0 = time.time()
    for _ in range(ITER):
        one(variant, outcomes, events)
    print(f"{variant}: {ITER} listeners x {BURST} connects in {time.time() - t0:.0f}s: {dict(outcomes)}; "
          f"TIME_WAIT after: {tw()}; first 10055s (variant, port, TIME_WAIT then): {events}")
    sys.stdout.flush()
    time.sleep(5)
