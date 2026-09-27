"""Who holds the TCP sockets after the Windows serial suite, and which browsers are still alive (#435).

Late in the serial `pytest` step on `windows · python 3.14`, Chromium has failed to fetch a page or a
script with `net::ERR_NO_BUFFER_SPACE` (Winsock WSAENOBUFS), and the desk's server has logged
`WinError 10053`. #465's step counted the sockets in TIME_WAIT after the suite: 4 on a green run and
2 on a red one (train 7), so the port range running dry is not it. This names the owners instead:

    python .github/scripts/sockets.py [--netstat FILE] [--tasklist FILE] [--top N]

It prints the TCP connection count and the TIME_WAIT count, the N PIDs that own the most TCP sockets
(with the image name from `tasklist` and a count per state), and the number of live `chrome.exe` and
`node.exe` processes. On Windows it runs `netstat -ano -p tcp` and `tasklist /fo csv /nh` itself;
`--netstat` and `--tasklist` read saved output instead, which is how tests/test_sockets_script.py
runs it off Windows. It always exits 0: a diagnostic never fails the job.
"""
from __future__ import annotations
import argparse
import csv
import io
import subprocess
import sys
from collections import Counter, defaultdict

BROWSERS = ("chrome.exe", "node.exe")


def parse_netstat(text: str) -> list[tuple[str, int]]:
    """(state, pid) for each TCP row of `netstat -ano -p tcp`."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "TCP" and parts[4].isdigit():
            rows.append((parts[3], int(parts[4])))
    return rows


def parse_tasklist(text: str) -> dict[int, str]:
    """pid -> image name, from `tasklist /fo csv /nh`."""
    images = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[1].isdigit():
            images[int(row[1])] = row[0]
    return images


def report(netstat: str, tasklist: str, top: int = 10) -> str:
    rows = parse_netstat(netstat)
    images = parse_tasklist(tasklist)
    waiting = sum(1 for state, _ in rows if state == "TIME_WAIT")
    out = [f"TCP connections: {len(rows)}; in TIME_WAIT: {waiting}",
           f"TCP connections in TIME_WAIT: {waiting}"]

    # TIME_WAIT sockets belong to no process (netstat shows PID 0): they are the line above.
    per_pid: dict[int, Counter] = defaultdict(Counter)
    for state, pid in rows:
        if state != "TIME_WAIT":
            per_pid[pid][state] += 1
    ranked = sorted(per_pid.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:top]
    out.append(f"The {top} PIDs that own the most TCP sockets (PID, sockets, image, per state):")
    for pid, states in ranked:
        detail = ", ".join(f"{s} {n}" for s, n in sorted(states.items()))
        out.append(f"  {pid} {sum(states.values())} {images.get(pid, '?')}  ({detail})")
    if not ranked:
        out.append("  (none)")

    live = Counter(name.lower() for name in images.values())
    out += [f"live {name}: {live[name]}" for name in BROWSERS]
    return "\n".join(out) + "\n"


def _run(argv: list[str]) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60).stdout


def _read(path: str | None, argv: list[str]) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    if sys.platform != "win32":
        return ""
    return _run(argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--netstat", help="saved `netstat -ano -p tcp` output (default: run it, on Windows)")
    ap.add_argument("--tasklist", help="saved `tasklist /fo csv /nh` output (default: run it, on Windows)")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args(argv)
    try:
        netstat = _read(args.netstat, ["netstat", "-ano", "-p", "tcp"])
        tasklist = _read(args.tasklist, ["tasklist", "/fo", "csv", "/nh"])
        sys.stdout.write(report(netstat, tasklist, args.top))
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as e:
        print(f"sockets.py could not read the sockets: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
