"""Throwaway (#603): loopback connects from ANOTHER process than the listener's, as Chromium's are.

A helper process makes a listener on port 0 per round, prints its port, accepts BURST connections and
answers each; this process connects BURST sockets non-blocking at once, sends a request, reads the
answer, closes. Counts connect outcomes over ITER rounds."""
import collections
import os
import select
import socket
import subprocess
import sys
import time

ITER = int(os.environ.get("CHURN_ITER", "5000"))
BURST = 6
HELPER = r'''
import random, socket, sys
FIXED = %r
def bind():
    while True:
        ls = socket.socket()
        try:
            ls.bind(("127.0.0.1", random.randint(20000, 45000) if FIXED else 0)); return ls
        except OSError:
            ls.close()
for line in sys.stdin:
    ls = bind(); ls.listen(128)
    print(ls.getsockname()[1], flush=True)
    ls.settimeout(5)
    acc = []
    for _ in range(%d):
        try:
            a = ls.accept()[0]; acc.append(a)
        except OSError:
            break
    for a in acc:
        try:
            a.settimeout(5); a.recv(100); a.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        except OSError:
            pass
    for a in acc:
        a.close()
    ls.close()
''' % (os.environ.get('LISTEN') == 'static', BURST)

h = subprocess.Popen([sys.executable, "-c", HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
out = collections.Counter()
t0 = time.time()
for _ in range(ITER):
    h.stdin.write("go\n")
    h.stdin.flush()
    port = int(h.stdout.readline())
    socks = []
    for _ in range(BURST):
        s = socket.socket()
        s.setblocking(False)
        rc = s.connect_ex(("127.0.0.1", port))
        if rc in (0, 10035, 115, 36):
            socks.append(s)
        else:
            out[f"connect_ex {rc}"] += 1
            s.close()
    for s in socks:
        _, w, x = select.select([], [s], [s], 5)
        err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) if (w or x) else -1
        out["connected" if err == 0 else f"SO_ERROR {err}"] += 1
    for s in socks:
        try:
            s.setblocking(True); s.settimeout(5); s.sendall(b"GET / HTTP/1.1\r\n\r\n"); s.recv(100)
        except OSError as e:
            out[f"io {e}"[:40]] += 1
    for s in socks:
        s.close()
h.stdin.close()
h.wait(10)
print(f"xproc[{os.environ.get('LISTEN', 'dynamic')}]: {ITER} listeners x {BURST} connects from another process in {time.time() - t0:.0f}s: {dict(out)}")
