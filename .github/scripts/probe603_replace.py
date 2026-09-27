"""Throwaway (#603): does `config.save` (tmp + bare os.replace) fail while another thread reads the file?

One thread loads the config in a loop, as the desk's stream and every answer do; the main thread
saves it 500 times, as a settings or theme POST does. Prints how many saves raised, and with what."""
import collections
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.getcwd())
from agentdata import config as C  # noqa: E402

d = tempfile.mkdtemp()
p = os.path.join(d, "config.json")
C.save({"fleet": {"theme": "a"}}, p)
stop = threading.Event()
reads = collections.Counter()


def reader():
    while not stop.is_set():
        try:
            C.load(p)
            reads["ok"] += 1
        except Exception as e:  # noqa: BLE001
            reads[type(e).__name__] += 1


t = threading.Thread(target=reader, daemon=True)
t.start()
saves = collections.Counter()
for i in range(500):
    try:
        C.save({"fleet": {"theme": str(i)}}, p)
        saves["ok"] += 1
    except Exception as e:  # noqa: BLE001
        saves[f"{type(e).__name__}: {e}"[:120]] += 1
stop.set()
t.join()
print("config.save x500 while another thread loads:", dict(saves))
print("loads:", dict(reads))
