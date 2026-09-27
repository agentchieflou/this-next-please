"""What Winsock looked like at the moment a test failed with #435's signature (Windows only).

#435: on the Windows jobs a browser test fails now and then with `net::ERR_NO_BUFFER_SPACE`
(WSAENOBUFS), with the desk's server logging `WinError 10053`, or with a page load that times out.
The step that runs after the suite (.github/scripts/sockets.py) sees nothing left over: a few dozen
sockets, no browser alive. So whatever runs out does so inside the test, and only a snapshot taken
at the failure can say what it was.

`tests/conftest.py`'s report hook calls `section()` for every failed test. On Windows, when the
failure's text (its traceback and captured output) carries one of `SIGNATURES`, it runs three
read-only commands and returns their summary, which the hook adds to the report as a section:

* `netstat -ano -p tcp`, counted by state and by owning PID (the ten busiest);
* the handle count of every live `python`, `chrome` and `node` process;
* the kernel's nonpaged pool, which WSAENOBUFS draws on.

It never changes a test's outcome: a command that fails or times out is reported as such.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter, defaultdict

SIGNATURES = re.compile(r"ERR_NO_BUFFER_SPACE|WSAENOBUFS|WinError 1005[35]|Timeout \d+ms exceeded")
TITLE = "#435 winsock at the failure"
NETSTAT = ["netstat", "-ano", "-p", "tcp"]
PROCESSES = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-Process python,chrome,node -ErrorAction SilentlyContinue | "
             "Select-Object Name,Id,Handles | ConvertTo-Json -Compress; "
             "'POOL ' + (Get-CimInstance Win32_PerfRawData_PerfOS_Memory).PoolNonpagedBytes"]
TIMEOUT_S = 20


def matches(text: str) -> bool:
    return bool(SIGNATURES.search(text or ""))


def summarise_netstat(text: str, top: int = 10) -> list[str]:
    """`netstat -ano -p tcp` as a count per state and the `top` PIDs owning the most sockets."""
    rows = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[0] == "TCP" and parts[4].isdigit():
            rows.append((parts[3], int(parts[4])))
    states = Counter(state for state, _ in rows)
    per_pid: dict[int, Counter] = defaultdict(Counter)
    for state, pid in rows:
        per_pid[pid][state] += 1
    ranked = sorted(per_pid.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:top]
    out = [f"TCP sockets: {len(rows)}; by state: " + (", ".join(f"{s} {n}" for s, n in sorted(states.items())) or "none")]
    for pid, counts in ranked:
        out.append(f"  pid {pid}: {sum(counts.values())} (" + ", ".join(f"{s} {n}" for s, n in sorted(counts.items())) + ")")
    return out


def summarise_processes(text: str) -> list[str]:
    """The PowerShell answer: a JSON object or list of {Name, Id, Handles}, then a `POOL <bytes>` line."""
    procs, pool = [], None
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("POOL "):
            value = line[5:].strip()
            pool = int(value) if value.isdigit() else None
        elif line.startswith(("[", "{")):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            procs = data if isinstance(data, list) else [data]
    procs = sorted(procs, key=lambda p: (-(p.get("Handles") or 0), p.get("Id") or 0))
    out = [f"live python/chrome/node: {len(procs)}; handles in all: {sum(p.get('Handles') or 0 for p in procs)}"]
    out += [f"  {p.get('Name')} pid {p.get('Id')}: {p.get('Handles')} handles" for p in procs[:15]]
    out.append("nonpaged pool: " + (f"{pool} bytes ({pool / 2**20:.1f} MiB)" if pool is not None else "not read"))
    return out


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, errors="replace").stdout
    except (OSError, subprocess.SubprocessError) as e:
        return f"<{argv[0]} failed: {e}>"


def capture(run=_run) -> str:
    """The snapshot, as text. `run(argv) -> stdout` is replaceable so the summary is testable anywhere."""
    lines = summarise_netstat(run(NETSTAT)) + summarise_processes(run(PROCESSES))
    return "\n".join(lines)


def section(text: str, os_name: str = os.name, run=_run) -> str | None:
    """The report section for a failure whose `text` carries #435's signature, on Windows; else None."""
    if os_name != "nt" or not matches(text):
        return None
    return capture(run)
