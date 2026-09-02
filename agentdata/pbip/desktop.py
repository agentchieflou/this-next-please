"""Power BI Desktop instance discovery -> `localhost:<port>` for dscmd / Tabular Editor.

Behaviour (learned from pbi-tools `info`, re-implemented here; no code copied): every open Desktop document runs its
own `msmdsrv.exe`; its command line carries `-s <workspace dir>` and `-n <workspace name>`; `<workspace dir>\\msmdsrv.port.txt`
(UTF-16) holds the Analysis Services port; the parent process is `PBIDesktop.exe`, whose window title is
"<file name> - Power BI Desktop". Fallback when process info is unavailable: glob the well-known workspace root.
"""
from __future__ import annotations
import glob
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Callable

PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
CIM_MSMDSRV = "Get-CimInstance Win32_Process -Filter \"Name='msmdsrv.exe'\" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
PBIDESKTOP_TITLES = "Get-Process PBIDesktop -ErrorAction SilentlyContinue | Select-Object Id,MainWindowTitle | ConvertTo-Json -Compress"
WORKSPACE_GLOB = os.path.join("Microsoft", "Power BI Desktop", "AnalysisServicesWorkspaces", "*", "Data", "msmdsrv.port.txt")
_ARG = re.compile(r'-(?P<k>[sn])\s+(?:"(?P<q>[^"]+)"|(?P<u>\S+))')
_TITLE = re.compile(r"^(?P<name>.+?)\s+-\s+Power BI Desktop\s*$")

Runner = Callable[[list[str], int], tuple[int, str, str]]


@dataclass
class Instance:
    pid: int | None
    port: int | None
    server: str | None
    workspace_dir: str | None
    workspace_name: str | None
    title: str | None
    file: str | None
    matched: str | None
    source: str

    def row(self) -> dict:
        return asdict(self)


def default_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def _ps_json(run: Runner, script: str) -> list[dict]:
    rc, out, _err = run(PS + [script], 30)
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def parse_cmdline(cmd: str | None) -> dict:
    out: dict = {}
    for m in _ARG.finditer(cmd or ""):
        out[m.group("k")] = m.group("q") or m.group("u")
    return out


def read_port(ws_dir: str | None) -> int | None:
    if not ws_dir:
        return None
    p = os.path.join(ws_dir, "msmdsrv.port.txt")
    if not os.path.exists(p):
        return None
    raw = open(p, "rb").read()
    for enc in ("utf-16", "utf-8-sig"):
        try:
            txt = raw.decode(enc).strip().strip("\x00")
            if txt.isdigit():
                return int(txt)
        except UnicodeDecodeError:
            continue
    return None


def title_name(title: str | None) -> str | None:
    m = _TITLE.match(title or "")
    return m.group("name").strip() if m else None


def match_file(name: str | None, candidates: list[str]) -> str | None:
    if not name:
        return None
    for c in candidates:
        base = os.path.splitext(os.path.basename(c))[0]
        if base.lower() == name.lower():
            return c.replace("\\", "/")
    return None


def open_files(pid: int | None) -> list[str]:
    """Exact open-document paths when psutil is installed (optional extra `pbi`)."""
    if pid is None:
        return []
    try:
        import psutil  # optional
        files = [f.path for f in psutil.Process(pid).open_files()]
    except Exception:  # noqa: BLE001 - not installed, access denied, gone
        return []
    home = os.path.expanduser("~").lower()
    return [f for f in files if f.lower().endswith((".pbix", ".pbit", ".pbip")) and not (f.lower().startswith(home) and "tempsaves" in f.lower())]


def discover(run: Runner | None = None, localappdata: str | None = None, candidates: list[str] | None = None) -> list[Instance]:
    run = run or default_run
    candidates = candidates or []
    titles = {int(t.get("Id")): t.get("MainWindowTitle") for t in _ps_json(run, PBIDESKTOP_TITLES) if t.get("Id") is not None}
    out: list[Instance] = []
    for proc in _ps_json(run, CIM_MSMDSRV):
        args = parse_cmdline(proc.get("CommandLine"))
        ws = args.get("s")
        port = read_port(ws)
        ppid = proc.get("ParentProcessId")
        ppid = int(ppid) if ppid is not None else None
        title = titles.get(ppid) if ppid is not None else None
        files = open_files(ppid)
        name = title_name(title)
        matched = match_file(name, candidates) or (files[0] if files else None)
        out.append(Instance(ppid, port, f"localhost:{port}" if port else None, ws, args.get("n"), title,
                            files[0] if files else None, matched, "cim"))
    if not out:
        root = localappdata or os.environ.get("LOCALAPPDATA") or ""
        for pf in sorted(glob.glob(os.path.join(root, WORKSPACE_GLOB))) if root else []:
            ws = os.path.dirname(pf)
            port = read_port(ws)
            out.append(Instance(None, port, f"localhost:{port}" if port else None, ws, os.path.basename(os.path.dirname(ws)), None, None, None, "glob"))
    return out


def launch(path: str, exe: str | None = None) -> dict:
    """Open a .pbip/.pbix in Desktop. Desktop does not hot-reload files, so re-launch after TMDL/report edits."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if exe:
        subprocess.Popen([exe, os.path.abspath(path)])
        return {"launched": path, "via": exe}
    if hasattr(os, "startfile"):
        os.startfile(os.path.abspath(path))  # type: ignore[attr-defined]
        return {"launched": path, "via": "shell"}
    raise RuntimeError("no PBIDesktop.exe configured and no shell association on this OS")
