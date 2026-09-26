"""No test process leaves a child behind (#317).

Every failing Windows job sampled, and one failing ubuntu job, ended with the runner's cleanup
reading `Terminate orphan process: pid (...) (python)`; green jobs did not. A child that outlives
its test can hold files, ports or the fleet directory, and on Windows a file the next test opens.

Where to look matters under xdist. A process a test leaks is a child of the **worker** that ran the
test, not of the controller: the controller's only children are the workers, and xdist tears them
down in its own `pytest_sessionfinish`. So the check runs in every process that runs tests (each
worker, or the one serial process), as the teardown of a session-scoped autouse fixture, and fails
naming the pid, name and command line of each `python`, `node`, `chrome` or `headless_shell` child
still alive. Under xdist the failure lands as a teardown error on that worker's last test. The
controller runs no test, so it never sets this fixture up and checks nothing.

The fixture is autouse and session-scoped in a plugin that `tests/conftest.py` lists in
`pytest_plugins`, so it is set up before every other session fixture and torn down after them: a
session-scoped fixture that starts a browser or a driver must leave nothing either.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

#: The children worth failing a session over: what the suite starts. Anything else (a shell a test
#: ran, a `git`) is not this guard's business, and a zombie has already exited.
WATCHED = ("python", "node", "chrome", "headless_shell")


def _watched(name: str) -> bool:
    base = os.path.basename(name or "").lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return any(base.startswith(w) for w in WATCHED)


# -- POSIX ---------------------------------------------------------------------------------------

def _read(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _stat(pid: int) -> tuple[str, str, int] | None:
    """(name, state, ppid) from `/proc/<pid>/stat`, or None when the process is gone.

    The name sits in parentheses and may itself hold spaces and parentheses, so the fields after it
    are split from the *last* `)`.
    """
    raw = _read(f"/proc/{pid}/stat")
    if ")" not in raw:
        return None
    name = raw[raw.find("(") + 1:raw.rfind(")")]
    rest = raw[raw.rfind(")") + 2:].split()
    try:
        return name, rest[0], int(rest[1])
    except (IndexError, ValueError):
        return None


def _proc_children(pid: int) -> list[int] | None:
    """Direct children from `/proc/<pid>/task/*/children`, or None when the kernel has no such file
    (it needs CONFIG_PROC_CHILDREN)."""
    tasks = f"/proc/{pid}/task"
    try:
        tids = os.listdir(tasks)
    except OSError:
        return None
    found: list[int] = []
    seen_file = False
    for tid in tids:
        path = os.path.join(tasks, tid, "children")
        if not os.path.exists(path):
            continue
        seen_file = True
        found += [int(p) for p in _read(path).split() if p.isdigit()]
    return found if seen_file else None


def _scan_children(pid: int) -> list[int]:
    """Every `/proc/*/stat` whose ppid is `pid`: the fallback when `children` is absent."""
    found = []
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            st = _stat(int(entry))
            if st and st[2] == pid:
                found.append(int(entry))
    return found


def _posix_children(pid: int) -> list[dict]:
    if not os.path.isdir("/proc"):
        return _ps_children(pid)
    pids = _proc_children(pid)
    if pids is None:
        pids = _scan_children(pid)
    rows = []
    for child in sorted(set(pids)):
        st = _stat(child)
        if st is None or st[1] == "Z":          # gone, or exited and waiting to be reaped
            continue
        argv = _read(f"/proc/{child}/cmdline").split("\0")
        rows.append({"pid": child, "name": st[0], "cmdline": " ".join(a for a in argv if a)})
    return rows


def _ps_children(pid: int) -> list[dict]:
    """macOS and any POSIX without `/proc`: one `ps` call."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,stat=,comm="], capture_output=True,
                             text=True, timeout=30, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[1] == str(pid) and not parts[2].startswith("Z"):
            rows.append({"pid": int(parts[0]), "name": os.path.basename(parts[3]), "cmdline": parts[3]})
    return rows


# -- Windows -------------------------------------------------------------------------------------

def _windows_children(pid: int) -> list[dict]:
    try:
        rows = _toolhelp_children(pid)
    except Exception:                               # noqa: BLE001 - ctypes refused: ask CIM instead
        rows = None
    if rows is None:
        return _cim_children(pid)
    for row in rows:
        row["cmdline"], row["cmdline_from"] = _windows_cmdline(row["pid"], row["name"])
    return rows


def _windows_cmdline(pid: int, name: str) -> tuple[str, str]:
    """(command line, which reader gave it) for one child, asking the process itself first (#520).

    The snapshot names the image only (`python.exe`). The command line used to come from CIM alone,
    a `powershell` per child: a 60 s cold start away, and on a loaded runner it can time out, fail
    on a WMI error it prints to stderr, or print nothing. The guard then fell back to the image name,
    and read a live `python -c ... time.sleep(300)` as bare `python.exe` (windows 3.12, train 7 and
    train 8b). The native read asks the kernel for the command line `CreateProcess` stored, with the
    same handle right the snapshot's creation-time check already uses. CIM stays as the second
    reader. When both fail, the image name is returned with each reader's reason, so a red says why.
    """
    why = []
    for label, reader in (("_native_cmdline", _native_cmdline), ("_cim_cmdline", _cim_cmdline)):
        try:
            text = reader(pid)
        except Exception as e:                      # noqa: BLE001 - recorded, then the next reader
            why.append(f"{label}: {type(e).__name__}: {e}")
            continue
        if text:
            return text, label
        why.append(f"{label}: empty")
    return name, "the image name, because " + "; ".join(why)


def _native_cmdline(pid: int) -> str:
    """The command line of `pid` from `NtQueryInformationProcess(ProcessCommandLineInformation)`.

    Windows 8.1 and later. It needs only PROCESS_QUERY_LIMITED_INFORMATION, which a process has on a
    child it started as the same user, and it reads the kernel's copy of the command line, so it
    involves no second process, no WMI and no timeout. Raises OSError on a refusal, with the code.
    """
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_void_p)]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ProcessCommandLineInformation = 60
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                                wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long          # NTSTATUS: negative is an error
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        raise OSError(ctypes.get_last_error(), f"OpenProcess({pid}) refused")
    try:
        need = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess(h, ProcessCommandLineInformation, None, 0, ctypes.byref(need))
        size = max(need.value, ctypes.sizeof(UNICODE_STRING)) or 0x10000
        buf = ctypes.create_string_buffer(size)
        status = ntdll.NtQueryInformationProcess(h, ProcessCommandLineInformation, buf, size,
                                                 ctypes.byref(need))
        if status < 0:
            raise OSError(f"NtQueryInformationProcess({pid}) gave NTSTATUS 0x{status & 0xFFFFFFFF:08X}")
        text = UNICODE_STRING.from_buffer(buf)      # its Buffer points into `buf`, just past it
        return ctypes.wstring_at(text.Buffer, text.Length // 2) if text.Buffer and text.Length else ""
    finally:
        k32.CloseHandle(h)


def _toolhelp_children(pid: int) -> list[dict] | None:
    """Children from `CreateToolhelp32Snapshot`, keeping only those created after `pid`.

    A Windows process keeps its dead parent's pid as its ParentProcessId, and pids are reused: a
    process whose long-gone parent had our pid would look like our child. Its creation time gives
    it away.
    """
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    TH32CS_SNAPPROCESS = 0x2
    # Declared, so a 64-bit handle is not squeezed through a C int on the way in or out.
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, wintypes.HANDLE(-1).value):
        return None
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    rows = []
    try:
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.th32ParentProcessID == pid and entry.th32ProcessID != pid:
                rows.append({"pid": int(entry.th32ProcessID), "name": entry.szExeFile})
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)

    def created(p: int) -> int | None:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, p)
        if not h:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            k32.CloseHandle(h)

    ours = created(pid)
    return [r for r in rows if ours is None or (created(r["pid"]) or ours + 1) > ours]


def _cim_children(pid: int) -> list[dict]:
    """The fallback when ctypes cannot take a snapshot: one CIM query for our children."""
    script = (f"Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' | "
              "ForEach-Object { \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2 and parts[0].strip().isdigit():
            text = parts[2].strip() if len(parts) > 2 else ""
            rows.append({"pid": int(parts[0]), "name": parts[1], "cmdline": text or parts[1],
                         "cmdline_from": "_cim_children" if text else
                         "the image name, because _cim_children: no CommandLine"})
    return rows


def _cim_cmdline(pid: int) -> str:
    """The command line of one process from CIM: the second reader, after `_native_cmdline`.

    Raises with powershell's exit code and the head of its stderr when it answers nothing, so
    `_windows_cmdline` can say why; a timeout or a missing powershell raises as it is.
    """
    script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    text = (done.stdout or "").strip()
    if not text and (done.returncode or (done.stderr or "").strip()):
        raise OSError(f"powershell exit {done.returncode}: {(done.stderr or '').strip()[:200]}")
    return text


# -- the guard -----------------------------------------------------------------------------------

def children(pid: int | None = None) -> list[dict]:
    """The live direct children of `pid` (default: this process), each `{pid, name, cmdline}`."""
    pid = os.getpid() if pid is None else pid
    return _windows_children(pid) if sys.platform == "win32" else _posix_children(pid)


def orphans(pid: int | None = None) -> list[dict]:
    """The children this guard fails a session over: those `WATCHED` names."""
    return [c for c in children(pid) if _watched(c["name"])]


#: A fleet agent's command line is its whole allow-list; its head names the process.
CMDLINE_SHOWN = 400


def _clip(cmdline: str) -> str:
    return cmdline if len(cmdline) <= CMDLINE_SHOWN else cmdline[:CMDLINE_SHOWN] + " ..."


def describe(rows: list[dict]) -> str:
    where = os.environ.get("PYTEST_XDIST_WORKER", "the serial process")
    lines = [f"{len(rows)} child process(es) of {where} (pid {os.getpid()}) outlived the tests "
             "that started them (#317). Its owner must kill it and wait on it at teardown, "
             "even when the test fails (agentdata.proc.kill_tree, then a bounded wait):"]
    lines += [f"  pid {r['pid']}  {r['name']}  {_clip(r['cmdline'])}"
              + (f"  [{r['cmdline_from']}]" if r.get("cmdline_from", "").startswith("the image") else "")
              for r in rows]
    return "\n".join(lines)


#: How long a test's teardown waits on an agent it killed. `kill_tree` is SIGKILL on POSIX and
#: `taskkill /F /T` on Windows, so this is a ceiling, not a wait.
AGENT_EXIT_WAIT_S = 30


@pytest.fixture(autouse=True)
def _a_test_ends_the_agents_it_started(monkeypatch):
    """Every agent `supervisor._spawn` started during a test is killed and waited on at teardown.

    The orphan in the failing jobs (#317): the fleet tests start real `copilot`s (the fake from
    `tests/fakes/`, a `python` process) through the real supervisor, and a passing test waits for
    each to exit. A failing one stops at its assert, nothing stops the agent, and it outlives the
    test, and on Windows holds the fleet directory the next test's `tmp_path` sits beside. The
    agent's own group goes (`kill_tree`), then the pid is reaped with a bounded wait: a kill
    without a wait leaves a zombie on POSIX and a handle on Windows. A test that patches `_spawn`
    itself (most of them) replaces this recording, which is right: its fake starts nothing.
    """
    from agentdata import proc
    from agentdata.fleet import supervisor

    started = []
    real = supervisor._spawn

    def spawn(*args, **kwargs):
        child = real(*args, **kwargs)
        started.append(child)
        return child

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    yield
    for child in started:
        if child.poll() is None:
            proc.kill_tree(child.pid)
        try:
            child.wait(timeout=AGENT_EXIT_WAIT_S)
        except subprocess.TimeoutExpired:
            pass                             # still alive: the session-end guard names it


@pytest.fixture(scope="session", autouse=True)
def _no_orphans_at_session_end():
    yield
    left = orphans()
    if left:
        pytest.fail(describe(left), pytrace=False)
