"""Throwaway (#603): socket and handle counts at every test boundary, while the browser is open.

Loaded with `-p probe603`. Writes one JSON line per test to $PROBE603_OUT (default probe603.jsonl):
for this process and every descendant (the Playwright driver, the browser and its children), grouped
by image name -- TCP connections per state, UDP endpoints, handles (Windows) or fds, RSS -- plus
the machine's TCP states and, on Windows, the kernel's nonpaged pool. A failed call phase is
snapshotted before teardown too. Nothing here changes a test's outcome.
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from collections import Counter, defaultdict

import psutil

#: Decided once, at import: tests patch `os.name` and `sys.platform`.
WIN = sys.platform == "win32"

OUT = os.environ.get("PROBE603_OUT", "probe603.jsonl")
ME = psutil.Process()
START = time.time()
_n = 0
#: Every port a desk of this process has listened on, seen at a snapshot.
OURS: set[int] = set()


def _nonpaged():
    if not WIN:
        return None

    class PI(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
                    ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
                    ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
                    ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
                    ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
                    ("HandleCount", ctypes.c_ulong), ("ProcessCount", ctypes.c_ulong),
                    ("ThreadCount", ctypes.c_ulong)]
    pi = PI()
    pi.cb = ctypes.sizeof(PI)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
        return None
    return {"nonpaged_mib": round(pi.KernelNonpaged * pi.PageSize / 2**20, 1),
            "sys_handles": pi.HandleCount, "procs": pi.ProcessCount}


def snapshot(nodeid: str, phase: str, outcome: str) -> dict:
    procs = [ME]
    try:
        procs += ME.children(recursive=True)
    except psutil.Error:
        pass
    pids = {p.pid: p for p in procs}
    names = {}
    for pid, p in pids.items():
        try:
            names[pid] = "python" if pid == ME.pid else p.name().lower().removesuffix(".exe")
        except psutil.Error:
            names[pid] = "?"
    by = defaultdict(lambda: {"n": 0, "tcp": Counter(), "udp": 0, "handles": 0, "rss_mib": 0.0})
    for pid, p in pids.items():
        g = by[names[pid]]
        g["n"] += 1
        try:
            g["handles"] += p.num_handles() if WIN else p.num_fds()
            g["rss_mib"] += p.memory_info().rss / 2**20
        except psutil.Error:
            pass
    machine = Counter()
    listen_ports = set()
    conns = []
    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.Error:
        pass
    for c in conns:
        machine[c.status] += 1
        if c.status == "LISTEN":
            listen_ports.add(c.laddr.port)
            if c.pid == ME.pid:
                OURS.add(c.laddr.port)
        if c.pid in pids:
            by[names[c.pid]]["tcp"][c.status] += 1
    ours = Counter(c.status for c in conns if c.status != "LISTEN" and c.raddr
                   and (c.laddr.port in OURS or c.raddr.port in OURS))
    # A browser connection whose server end is gone: established/close_wait to a port nobody listens on.
    orphan = Counter()
    for c in conns:
        if c.pid in pids and names[c.pid] != "python" and c.raddr and c.raddr.port not in listen_ports:
            orphan[c.status] += 1
    try:
        udp = psutil.net_connections(kind="udp")
        for c in udp:
            if c.pid in pids:
                by[names[c.pid]]["udp"] += 1
    except psutil.Error:
        pass
    groups = {k: {**v, "tcp": dict(v["tcp"]), "rss_mib": round(v["rss_mib"], 1)} for k, v in by.items()}
    return {"i": _n, "t": round(time.time() - START, 1), "id": nodeid, "phase": phase, "outcome": outcome,
            "machine_tcp": dict(machine), "desk_ports_tcp": dict(ours), "py_threads": threading.active_count(), "browser_to_dead_port": dict(orphan), "groups": groups,
            "sys": _nonpaged()}


def _write(rec: dict) -> None:
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def pytest_runtest_logreport(report):
    global _n
    if report.when == "call":
        try:
            _write(snapshot(report.nodeid, "call-failed" if report.failed else "during", report.outcome))
        except Exception as e:                      # noqa: BLE001 - a probe never fails the run
            _write({"i": _n, "id": report.nodeid, "phase": "probe-error", "error": repr(e)})
    if report.when == "teardown":
        _n += 1
        try:
            _write(snapshot(report.nodeid, "after", report.outcome))
        except Exception as e:                      # noqa: BLE001 - a probe never fails the run
            _write({"i": _n, "id": report.nodeid, "phase": "probe-error", "error": repr(e)})


def pytest_sessionfinish(session):
    """A table of the browser-side counts over the run, every 25th test and every failure."""
    try:
        rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    except OSError:
        return
    sys.stderr.write("\n#603 probe: per-test socket counts (every 25th row, and failures)\n")
    for r in rows:
        if "groups" not in r:
            continue
        if r["phase"] == "during" and not r["groups"].get("chrome", r["groups"].get("chrome-headless-shell", {})).get("tcp"):
            continue
        if r["phase"] == "after" and r["i"] % 25:
            continue
        g = r["groups"]
        br = {k: v for k, v in g.items() if k not in ("python",)}
        sys.stderr.write(f"{r['i']:5} {r['t']:7} {r['phase']:11} machine={r['machine_tcp']} desks={r['desk_ports_tcp']} dead={r['browser_to_dead_port']} "
                         f"py={g.get('python', {}).get('tcp')} h={g.get('python', {}).get('handles')} "
                         + " ".join(f"{k}[n={v['n']} tcp={v['tcp']} udp={v['udp']} h={v['handles']} rss={v['rss_mib']}]"
                                    for k, v in sorted(br.items()))
                         + f" sys={r['sys']} {r['id'][-60:]}\n")


# ------------------------------------------------------------------ a sampler, for bursts between tests


SAMPLES = os.environ.get("PROBE603_SAMPLES", "probe603-samples.jsonl")
CURRENT = {"id": ""}


def pytest_runtest_logstart(nodeid, location):
    CURRENT["id"] = nodeid


def _netstat_q():
    """`netstat -anoq -p tcp`: every TCP port by state, BOUND ones too (which the TCP table omits),
    counted by state and, for BOUND, by owning PID."""
    import subprocess
    out = subprocess.run(["netstat", "-anoq", "-p", "tcp"], capture_output=True, text=True, timeout=20,
                         errors="replace").stdout
    states, bound = Counter(), Counter()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "TCP":
            states[parts[3]] += 1
            if parts[3] == "BOUND":
                bound[parts[4]] += 1
    return {"states": dict(states), "bound_by_pid": dict(bound.most_common(5))}


def _sampler():
    k = 0
    while True:
        k += 1
        t0 = time.time()
        try:
            conns = psutil.net_connections(kind="tcp")
            machine = Counter(c.status for c in conns)
            try:
                kids = {p.pid: p for p in ME.children(recursive=True)}
            except psutil.Error:
                kids = {}
            mine = Counter(c.status for c in conns if c.pid in kids or c.pid == ME.pid)
            rec = {"t": round(t0 - START, 2), "id": CURRENT["id"], "machine": dict(machine), "ours": dict(mine),
                   "threads": threading.active_count(), "sys": _nonpaged(), "took_ms": round((time.time() - t0) * 1000)}
            if WIN and k % 8 == 0:
                rec["netstat_q"] = _netstat_q()
                rec["mine_pids"] = [ME.pid] + list(kids)
            with open(SAMPLES, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception as e:                      # noqa: BLE001 - a probe never fails the run
            with open(SAMPLES, "a", encoding="utf-8") as f:
                f.write(json.dumps({"error": repr(e)}) + "\n")
        time.sleep(0.25)


def pytest_sessionstart(session):
    try:
        _wrap_refuse()
    except Exception:                               # noqa: BLE001 - a probe never fails the run
        pass
    threading.Thread(target=_sampler, daemon=True, name="probe603-sampler").start()


# ------------------------------------------------------------------ every 5xx the desk answers, with why
def _wrap_refuse():
    from agentdata.fleet import serve as S

    real = S.Handler._refuse

    def _refuse(self, code, msg, *args, **kwargs):
        if int(code) >= 500:
            with open(OUT + ".5xx", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(time.time() - START, 2), "id": CURRENT["id"], "code": code,
                                    "path": getattr(self, "path", "")[:80], "msg": str(msg)[:400]}) + "\n")
        return real(self, code, msg, *args, **kwargs)

    S.Handler._refuse = _refuse

