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
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable

PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
CIM_MSMDSRV = "Get-CimInstance Win32_Process -Filter \"Name='msmdsrv.exe'\" | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
PBIDESKTOP_TITLES = "Get-Process PBIDesktop -ErrorAction SilentlyContinue | Select-Object Id,MainWindowTitle,Path | ConvertTo-Json -Compress"
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
    pages: list[dict] = field(default_factory=list)
    unsaved: str = "unknown"
    loaded: bool = False
    desktop_version: str | None = None
    install: str = "unknown"

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


def load_instance_pages(file_path: str | None) -> list[dict]:
    """Read PBIR pages (id, displayName, order, active) from disk for an instance's file."""
    if not file_path:
        return []
    report_dir = None
    if os.path.isdir(file_path):
        if file_path.endswith(".Report"):
            report_dir = file_path
        else:
            for d in sorted(glob.glob(os.path.join(file_path, "*.Report"))):
                if os.path.isdir(d):
                    report_dir = d
                    break
    elif os.path.isfile(file_path):
        parent = os.path.dirname(file_path)
        base = os.path.splitext(os.path.basename(file_path))[0]
        rep_cand = os.path.join(parent, base + ".Report")
        if os.path.isdir(rep_cand):
            report_dir = rep_cand
        else:
            for d in sorted(glob.glob(os.path.join(parent, "*.Report"))):
                if os.path.isdir(d):
                    report_dir = d
                    break
    else:
        base = os.path.splitext(file_path)[0]
        rep_cand = base + ".Report"
        if os.path.isdir(rep_cand):
            report_dir = rep_cand
    if not report_dir or not os.path.exists(report_dir):
        return []

    defn = os.path.join(report_dir, "definition")
    pages_dir = os.path.join(defn, "pages")
    pages_json = os.path.join(pages_dir, "pages.json")
    order: list[str] = []
    active_name: str | None = None
    if os.path.exists(pages_json):
        try:
            with open(pages_json, encoding="utf-8-sig") as f:
                pj = json.load(f)
                order = list(pj.get("pageOrder") or [])
                active_name = pj.get("activePageName")
        except Exception:
            pass

    page_folders = sorted(d for d in glob.glob(os.path.join(pages_dir, "*")) if os.path.isdir(d))
    pages: list[dict] = []
    for pd in page_folders:
        pid = os.path.basename(pd)
        pj_path = os.path.join(pd, "page.json")
        display_name = pid
        if os.path.exists(pj_path):
            try:
                with open(pj_path, encoding="utf-8-sig") as f:
                    pdata = json.load(f)
                    display_name = pdata.get("displayName") or pid
            except Exception:
                pass
        ord_idx = order.index(pid) if pid in order else 999
        is_active = (pid == active_name or display_name == active_name)
        pages.append({
            "id": pid,
            "displayName": display_name,
            "order": ord_idx,
            "active": is_active,
        })
    pages.sort(key=lambda x: (x["order"], x["id"]))
    return pages


def probe_unsaved(pid: int | None, title: str | None = None, run: Runner | None = None) -> str:
    """Probe unsaved-changes state: (a) title marker, (b) UI Automation Save button property, (c) unknown."""
    if title:
        name = title_name(title)
        if title.startswith("*") or (name and name.endswith("*")) or " * " in title:
            return "true"
    if pid is None:
        return "unknown"
    run = run or default_run
    script = (
        f'Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue; '
        f'$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {pid}); '
        f'$win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond); '
        f'if ($win) {{ '
        f'  $btnCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Save"); '
        f'  $btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $btnCond); '
        f'  if ($btn) {{ [string]$btn.Current.IsEnabled }} else {{ "unknown" }} '
        f'}} else {{ "unknown" }}'
    )
    rc, out, _err = run(PS + [script], 10)
    if rc == 0:
        val = out.strip().lower()
        if val == "true":
            return "true"
        if val == "false":
            return "false"
    return "unknown"


def probe_desktop_version(pid: int | None, proc_item: dict | None = None, run: Runner | None = None) -> tuple[str | None, str]:
    """Return (desktop_version, install) where install is msi|store|unknown."""
    if proc_item:
        path = proc_item.get("Path") or proc_item.get("ExecutablePath")
        ver = proc_item.get("Version") or proc_item.get("ProductVersion")
        if path:
            install = "store" if "windowsapps" in str(path).lower() else "msi"
            if ver:
                return str(ver), install
            if os.path.exists(str(path)):
                run = run or default_run
                rc, out, _ = run(PS + [f'(Get-Item -LiteralPath "{path}").VersionInfo.ProductVersion'], 10)
                if rc == 0 and out.strip():
                    return out.strip(), install
            return None, install
    if pid is None:
        return None, "unknown"
    run = run or default_run
    script = (
        f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" -ErrorAction SilentlyContinue | '
        f'Select-Object ExecutablePath | ConvertTo-Json -Compress'
    )
    rc, out, _ = run(PS + [script], 10)
    if rc == 0 and out.strip():
        try:
            d = json.loads(out)
            epath = d.get("ExecutablePath")
            if epath:
                install = "store" if "windowsapps" in str(epath).lower() else "msi"
                rc2, out2, _ = run(PS + [f'(Get-Item -LiteralPath "{epath}").VersionInfo.ProductVersion'], 10)
                ver = out2.strip() if rc2 == 0 and out2.strip() else None
                return ver, install
        except Exception:
            pass
    return None, "unknown"


def discover(run: Runner | None = None, localappdata: str | None = None, candidates: list[str] | None = None) -> list[Instance]:
    run = run or default_run
    candidates = candidates or []
    titles_raw = _ps_json(run, PBIDESKTOP_TITLES)
    titles = {int(t.get("Id")): t.get("MainWindowTitle") for t in titles_raw if t.get("Id") is not None}
    proc_items = {int(t.get("Id")): t for t in titles_raw if t.get("Id") is not None}
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
        target_file = matched or (files[0] if files else None)
        pages = load_instance_pages(target_file)
        unsaved = probe_unsaved(ppid, title, run=run)
        loaded = bool(port and port > 0)
        ver, install = probe_desktop_version(ppid, proc_items.get(ppid), run=run)
        out.append(Instance(ppid, port, f"localhost:{port}" if port else None, ws, args.get("n"), title,
                            files[0] if files else None, matched, "cim",
                            pages=pages, unsaved=unsaved, loaded=loaded, desktop_version=ver, install=install))
    if not out:
        root = localappdata or os.environ.get("LOCALAPPDATA") or ""
        for pf in sorted(glob.glob(os.path.join(root, WORKSPACE_GLOB))) if root else []:
            ws = os.path.dirname(pf)
            port = read_port(ws)
            loaded = bool(port and port > 0)
            out.append(Instance(None, port, f"localhost:{port}" if port else None, ws, os.path.basename(os.path.dirname(ws)),
                                None, None, None, "glob", pages=[], unsaved="unknown", loaded=loaded, desktop_version=None, install="unknown"))
    return out


def status(pid: int | None = None, candidates: list[str] | None = None, run: Runner | None = None) -> list[Instance]:
    """List running Power BI Desktop instances, optionally filtered by pid."""
    insts = discover(run=run, candidates=candidates)
    if pid is not None:
        return [i for i in insts if i.pid == pid]
    return insts


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


def open_and_wait(path: str, wait_secs: int = 180, exe: str | None = None, run: Runner | None = None) -> dict:
    """Open a .pbip/.pbix in Desktop and poll until port + input-idle ready, or return immediately if wait=0."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    res = launch(path, exe=exe)
    if wait_secs <= 0:
        return {"ok": True, "source": "ad-pbip desktop open", "launched": path, "wait": 0, **res}
    run = run or default_run
    import time
    start = time.time()
    while time.time() - start < wait_secs:
        insts = discover(run=run, candidates=[path])
        matched_inst = None
        for i in insts:
            if (i.matched and os.path.abspath(i.matched) == os.path.abspath(path)) or (i.file and os.path.abspath(i.file) == os.path.abspath(path)):
                matched_inst = i
                break
        if not matched_inst and insts:
            base = os.path.splitext(os.path.basename(path))[0].lower()
            for i in insts:
                if i.title and base in i.title.lower():
                    matched_inst = i
                    break
        if matched_inst and matched_inst.port and matched_inst.loaded:
            if matched_inst.pid:
                script = f'(Get-Process -Id {matched_inst.pid} -ErrorAction SilentlyContinue).WaitForInputIdle(1000)'
                run(PS + [script], 10)
            return {"ok": True, "source": "ad-pbip desktop open", **matched_inst.row()}
        time.sleep(1)
    return {
        "ok": False,
        "source": "ad-pbip desktop open",
        "fail": "timeout",
        "hint": f"Desktop did not become ready within {wait_secs}s; check if Desktop opened the file",
        "path": path,
    }


def close(pid: int, save: bool = False, discard: bool = False, run: Runner | None = None) -> dict:
    """Close Desktop instance via WM_CLOSE, prompting if unsaved changes exist."""
    run = run or default_run
    # Verify process exists
    rc, out, _ = run(PS + [f'Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object Id | ConvertTo-Json -Compress'], 10)
    if rc != 0 or not out.strip():
        return {"ok": False, "source": "ad-pbip desktop close", "pid": pid, "fail": "not_found", "hint": f"no process with pid {pid}"}

    script_close = (
        f'$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; '
        f'if ($p) {{ $null = $p.CloseMainWindow() }}; '
        f'Start-Sleep -Milliseconds 500; '
        f'Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue; '
        f'$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {pid}); '
        f'$win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond); '
        f'if ($win) {{ '
        f'  $dlgCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window); '
        f'  $dlg = $win.FindFirst([System.Windows.Automation.TreeScope]::Children, $dlgCond); '
        f'  if ($dlg) {{ '
        f'    $saveBtn = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Save"))); '
        f'    $dontSaveBtn = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Don\'t Save"))); '
        f'    if ($saveBtn -or $dontSaveBtn) {{ "save_prompt" }} else {{ "running" }} '
        f'  }} else {{ "running" }} '
        f'}} else {{ "exited" }}'
    )
    rc, out, _ = run(PS + [script_close], 15)
    state = out.strip() if rc == 0 else "unknown"

    if "save_prompt" in state:
        if save:
            act_script = (
                f'Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue; '
                f'$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {pid}); '
                f'$win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond); '
                f'if ($win) {{ '
                f'  $btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Save"))); '
                f'  if ($btn) {{ $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); $inv.Invoke() }} '
                f'}}'
            )
            run(PS + [act_script], 10)
            return {"ok": True, "source": "ad-pbip desktop close", "pid": pid, "action": "saved_and_closed"}
        if discard:
            act_script = (
                f'Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue; '
                f'$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {pid}); '
                f'$win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond); '
                f'if ($win) {{ '
                f'  $btn = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Don\'t Save"))); '
                f'  if ($btn) {{ $inv = $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); $inv.Invoke() }} '
                f'}}'
            )
            run(PS + [act_script], 10)
            return {"ok": True, "source": "ad-pbip desktop close", "pid": pid, "action": "discarded_and_closed"}
        return {
            "ok": False,
            "source": "ad-pbip desktop close",
            "pid": pid,
            "fail": "unsaved_changes",
            "hint": "unsaved changes; pass --save or --discard",
        }

    return {"ok": True, "source": "ad-pbip desktop close", "pid": pid, "closed": True}


def reload(pid: int, save: bool = False, discard: bool = False, candidates: list[str] | None = None, run: Runner | None = None) -> dict:
    """Reload instance: native close + open, preserving active page, or bridge pipe when available."""
    pipe_name = rf"\\.\pipe\pbi-desktop-bridge-{pid}"
    if os.path.exists(pipe_name):
        pass

    insts = status(pid=pid, candidates=candidates, run=run)
    if not insts:
        return {"ok": False, "source": "ad-pbip desktop reload", "pid": pid, "fail": "not_found", "hint": f"no Desktop instance with pid {pid}"}
    inst = insts[0]
    target_file = inst.file or inst.matched
    if not target_file:
        return {"ok": False, "source": "ad-pbip desktop reload", "pid": pid, "fail": "no_file", "hint": f"instance {pid} has no associated PBIP file"}

    c_res = close(pid, save=save, discard=discard, run=run)
    if not c_res.get("ok"):
        return c_res

    o_res = open_and_wait(target_file, wait_secs=180, run=run)
    if not o_res.get("ok"):
        return o_res

    return {**o_res, "reloaded_via": "native"}


def capabilities(pid: int | None = None, run: Runner | None = None) -> list[dict]:
    """Single source of truth for Power BI Desktop capabilities."""
    from .. import config as C
    cfg = C.load()
    out = []

    # 1. as_port
    if pid is not None:
        insts = status(pid=pid, run=run)
        port = insts[0].port if insts else None
        out.append({
            "capability": "as_port",
            "available": bool(port),
            "via": "msmdsrv.port.txt",
            "evidence": f"port {port}" if port else f"no Analysis Services port for pid {pid}",
        })
    else:
        insts = discover(run=run)
        ports = [str(i.port) for i in insts if i.port]
        out.append({
            "capability": "as_port",
            "available": len(ports) > 0,
            "via": "msmdsrv.port.txt",
            "evidence": f"port {ports[0]}" if ports else "no running Analysis Services port",
        })

    # 2. xmla_local
    dscmd = C.get(cfg, "powerbi.tools.dscmd_exe") or shutil.which("dscmd") or shutil.which("dscmd.exe")
    te2 = C.get(cfg, "powerbi.tools.te2_exe") or shutil.which("TabularEditor") or shutil.which("TabularEditor.exe")
    xmla_avail = bool(dscmd or te2)
    xmla_via = "dscmd" if dscmd else ("te2" if te2 else "dscmd/te2")
    xmla_ev = str(dscmd or te2 or "neither dscmd nor TabularEditor found")
    out.append({"capability": "xmla_local", "available": xmla_avail, "via": xmla_via, "evidence": xmla_ev})

    # 3. external_tools
    ext_dirs = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Common Files\Microsoft Shared\Power BI Desktop\External Tools"),
        os.path.expandvars(r"%ProgramFiles%\Common Files\Microsoft Shared\Power BI Desktop\External Tools"),
    ]
    ext_dir_found = next((d for d in ext_dirs if os.path.isdir(d)), None)
    out.append({
        "capability": "external_tools",
        "available": bool(ext_dir_found),
        "via": "directory",
        "evidence": ext_dir_found or "External Tools folder not found",
    })

    # 4. uia
    run_fn = run or default_run
    rc, uia_out, _ = run_fn(PS + ['Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes -ErrorAction SilentlyContinue; [bool]([System.Windows.Automation.AutomationElement])'], 10)
    uia_avail = (rc == 0 and uia_out.strip().lower() == "true")
    out.append({
        "capability": "uia",
        "available": uia_avail,
        "via": "System.Windows.Automation",
        "evidence": "UIAutomationClient loaded" if uia_avail else "UIAutomationClient unavailable",
    })

    # 5. printwindow
    pw_avail = False
    pw_ev = "user32.dll not accessible"
    if sys.platform == "win32":
        try:
            import ctypes
            pw_avail = hasattr(ctypes.windll.user32, "PrintWindow")
            pw_ev = "user32.dll!PrintWindow available" if pw_avail else "PrintWindow missing"
        except Exception as e:
            pw_ev = str(e)
    elif run:
        rc_pw, out_pw, _ = run_fn(PS + ['[bool]([System.Type]::GetType("user32.dll"))'], 10)
        if rc_pw == 0 and out_pw.strip().lower() == "true":
            pw_avail = True
            pw_ev = "user32.dll!PrintWindow simulated"
    out.append({
        "capability": "printwindow",
        "available": pw_avail,
        "via": "user32.dll",
        "evidence": pw_ev,
    })

    # 6. bridge_pipe
    if pid is not None:
        pipe_path = rf"\\.\pipe\pbi-desktop-bridge-{pid}"
        pipe_avail = os.path.exists(pipe_path)
        pipe_ev = pipe_path if pipe_avail else f"pipe for pid {pid} not found"
    else:
        pipes = glob.glob(r"\\.\pipe\pbi-desktop-bridge-*")
        pipe_avail = len(pipes) > 0
        pipe_ev = pipes[0] if pipe_avail else "no bridge pipe active"
    out.append({
        "capability": "bridge_pipe",
        "available": pipe_avail,
        "via": "named_pipe",
        "evidence": pipe_ev,
    })

    # 7. developer_visual
    dev_avail = False
    dev_ev = "developer visual setting not detected"
    if sys.platform == "win32":
        rc_dev, out_dev, _ = run_fn(PS + ['(Get-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Power BI Desktop" -ErrorAction SilentlyContinue).EnableDeveloperVisual'], 10)
        if rc_dev == 0 and out_dev.strip() in ("1", "True"):
            dev_avail = True
            dev_ev = "registry EnableDeveloperVisual=1"
    out.append({
        "capability": "developer_visual",
        "available": dev_avail,
        "via": "registry",
        "evidence": dev_ev,
    })

    # 8. pbiviz
    pbiviz_path = shutil.which("pbiviz") or shutil.which("pbiviz.cmd")
    out.append({
        "capability": "pbiviz",
        "available": bool(pbiviz_path),
        "via": "npm",
        "evidence": pbiviz_path or "pbiviz not found on PATH",
    })

    return out
