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
from .. import console
from .. import textio
from . import winui

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
            return textio.norm_path(c)
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


# --------------------------------------------------------- which window does the human mean (#116)
#
# The External Tools ribbon has exactly one payload nothing else supplies: *this* document, the one
# the human is looking at. Buying that answer costs a privileged write into
# `%CommonProgramFiles%\Microsoft Shared\Power BI Desktop\External Tools`, which on the machine
# epic #112 measured is Administrators-only. Two gestures the human has already made answer the same
# question for free: the window they clicked last is the highest `PBIDesktop.exe` window in Z-order,
# and when only one document is open there is nothing to disambiguate at all.

TRANSPORTS = ("zorder", "file", "te2:local", "ribbon:machine")


def windows_zorder(run: Runner | None = None) -> list[tuple[int, str]]:
    r"""Visible Power BI Desktop windows as `(pid, title)`, the one on top first.

    A one-line wrapper, deliberately. #116 names `desktop.windows_zorder`, and this is the module
    every other caller already asks about Desktop instances -- but the answer comes from `ctypes`
    against `user32.EnumWindows`, whose two ways of crashing (a callback thunk with no reference to
    it, and `ctypes.windll`'s process-wide handle) need explaining next to the code that avoids
    them. That lives in `winui.py`, which also keeps *this* module importable, and its tests
    runnable, on a machine that has no `user32` at all.
    """
    return winui.desktop_windows(run=run)


def _instance_names(inst: Instance) -> list[str]:
    """Every spelling of "which document" one instance answers to, lowercased."""
    names: list[str] = []
    for path in (inst.matched, inst.file):
        if path:
            norm = textio.norm_path(path)
            names.append(norm.lower())
            base = os.path.basename(norm)
            names.append(base.lower())
            names.append(os.path.splitext(base)[0].lower())
    name = title_name(inst.title)
    if name:
        names.append(name.lower())
    if inst.title:
        names.append(inst.title.lower())
    return names


def match_instances(insts: list[Instance], wanted: str) -> list[Instance]:
    """Instances `--file <name>` means. Exact document name first; a substring only if that finds none.

    Two passes rather than one, because a loose match that silently outranks an exact one is how
    `--file Sales` ends up handing over `Sales Archive`. If the exact pass finds anything, the
    substring pass never runs.
    """
    want = (wanted or "").strip().strip('"').lower()
    if not want:
        return []
    stem = os.path.splitext(os.path.basename(textio.norm_path(want)))[0]
    exact = [i for i in insts if any(n == want or n == stem for n in _instance_names(i))]
    if exact:
        return exact
    return [i for i in insts if any(want in n for n in _instance_names(i))]


def _choices(insts: list[Instance], rows: list[tuple[int, str]]) -> list[dict]:
    """The open documents, in the order Windows stacks them, for a refusal a human can act on."""
    order = {pid: i for i, (pid, _t) in enumerate(rows)}
    titles = dict(rows)
    out = [{
        "pid": i.pid,
        "zorder": order.get(i.pid),
        "title": i.title or titles.get(i.pid) or "",
        "file": textio.norm_path(i.file or i.matched) if (i.file or i.matched) else "",
        "server": i.server or "",
    } for i in insts]
    out.sort(key=lambda c: (c["zorder"] if c["zorder"] is not None else 1_000_000, c["pid"] or 0))
    return out


def _label(choice: dict) -> str:
    name = choice["title"] or os.path.basename(choice["file"]) or "?"
    return f'{name} (pid {choice["pid"]})'


def resolve_transport(active: bool = False, file: str | None = None, candidates: list[str] | None = None,
                      run: Runner | None = None) -> dict:
    """Decide which running instance a handoff means, or refuse. Never guess.

    #41's rule, and this is the place it earns its keep: a handoff writes a server address that the
    next twenty commands trust without re-checking, so picking the wrong window is not a wrong
    answer once, it is a wrong answer all afternoon. With two documents open and no flag, the only
    honest move is to stop and print both.

    * `--active` -> `windows_zorder()[0]`, transport `zorder`: the window the human clicked last.
    * `--file <name>` -> the instance whose file or title matches, transport `file`.
    * neither, and exactly one instance is running -> that one, transport `file`, and `why` says so.
    * neither, and two or more -> refusal with the Z-ordered list and the two flags.

    Always a dict: `ok` true with `instance`, `pid`, `server` and `transport`, or `ok` false with
    `fail`, a `hint` naming what to do next, and `choices` when there was more than one answer.
    """
    insts = status(candidates=candidates, run=run)
    rows = windows_zorder(run=run)
    choices = _choices(insts, rows)

    def refuse(fail: str, hint: str) -> dict:
        return {"ok": False, "source": "ad-pbip handoff", "fail": fail, "hint": hint, "choices": choices}

    if active:
        if not rows:
            return refuse("no_window", "no Power BI Desktop window is open (or none is visible to this "
                                       "session); open the report, click its window, and run it again")
        pid = rows[0][0]
        picked = [i for i in insts if i.pid == pid]
        if not picked:
            return refuse("no_instance", f'the window on top is pid {pid} ("{rows[0][1]}") but it has no '
                                         "Analysis Services process yet; wait for the model to finish "
                                         "loading and run it again, or check `ad-pbip desktop status`")
        inst, transport, why = picked[0], "zorder", f'the Power BI Desktop window on top: "{rows[0][1]}"'
    elif file:
        picked = match_instances(insts, file)
        if not picked:
            open_now = ", ".join(_label(c) for c in choices) or "nothing"
            return refuse("no_match", f"no open Power BI Desktop document matches --file {file!r}; "
                                      f"open now: {open_now}")
        if len(picked) > 1:
            return refuse("ambiguous", f"--file {file!r} matches {len(picked)} open documents "
                                       f"({', '.join(_label(c) for c in _choices(picked, rows))}); click the "
                                       "one you mean and use `ad-pbip handoff --active` instead")
        inst, transport, why = picked[0], "file", f"--file {file} matched {_label(_choices(picked, rows)[0])}"
    else:
        if not insts:
            return refuse("no_instance", "no Power BI Desktop instance is running; open the report "
                                         "(`ad-pbip launch <project>.pbip`) and run it again")
        if len(insts) > 1:
            return refuse("ambiguous", f"{len(insts)} Power BI Desktop instances are open and nothing says "
                                       f"which one you mean ({', '.join(_label(c) for c in choices)}); click "
                                       "the window you want and run `ad-pbip handoff --active`, or name it "
                                       "with `ad-pbip handoff --file <name>`")
        inst, transport = insts[0], "file"
        why = f"the only Power BI Desktop instance running: {_label(choices[0]) if choices else inst.title}"

    if not inst.port:
        return refuse("no_port", f"pid {inst.pid} has no Analysis Services port yet "
                                 f"(msmdsrv.port.txt under {inst.workspace_dir or 'its workspace'} is missing "
                                 "or unreadable); the document is still loading -- wait and run it again")

    return {"ok": True, "source": "ad-pbip handoff", "transport": transport, "why": why,
            "instance": inst, "pid": inst.pid, "port": inst.port,
            "server": inst.server or f"localhost:{inst.port}",
            "file": textio.norm_path(inst.file or inst.matched) if (inst.file or inst.matched) else None,
            "title": inst.title, "choices": choices}


def resolve_database(server: str, dscmd_exe: str | None = None, te2_exe: str | None = None,
                     run: Runner | None = None) -> tuple[str, str]:
    """`%database%` without the ribbon: `("<catalog>", "dmv")`, or `("", "none")`.

    A Desktop instance serves exactly one catalog, so the single row `DBSCHEMA_CATALOGS` returns
    over `localhost:<port>` *is* the value the ribbon would have substituted -- and dscmd and
    Tabular Editor 2 both run fine from `C:\\Enforce`, which is why `%database%` was never the
    payload worth a ticket.

    An empty answer is not a failure. With neither executor installed there is nothing to ask; the
    handoff is still written, `database_source` records `none`, and the caller warns once. Guessing
    a GUID here would be worse than an empty field, because a consumer can ask for a missing value
    and cannot un-trust a wrong one.
    """
    from . import dmv as DMV  # deferred: dmv imports this module
    try:
        names = DMV.catalogs(server, dscmd_exe=dscmd_exe, te2_exe=te2_exe, run=run)
    except Exception:  # noqa: BLE001 - catalogs() already swallows the executors; belt and braces
        names = []
    return (names[0], "dmv") if names else ("", "none")


NO_DATABASE_WARN = ("database is empty (database_source: none): neither dscmd nor Tabular Editor 2 could be "
                    "reached to read DBSCHEMA_CATALOGS -- set powerbi.tools.dscmd_exe or powerbi.tools.te2_exe "
                    "(`ad-setup --only powerbi`), or pass --db to the commands that need it")


def handoff(active: bool = False, file: str | None = None, project_dir: str | None = None,
            candidates: list[str] | None = None, run: Runner | None = None,
            dscmd_exe: str | None = None, te2_exe: str | None = None) -> dict:
    """Resolve the instance, read its catalog, and write `.agent/desktop.json` -- no ribbon involved.

    This is the ribbon click, performed by a gesture the human already made. `external_tool.handoff`
    stays the single writer of `.agent/desktop.json` (the ribbon and the Tabular Editor action both
    land there), so this resolves `server` and `database` and hands them over, then adds the two
    fields only a transport knows: `transport` and `database_source`. Both are additive --
    `read_handoff()` and every consumer of that file are untouched, and a `desktop.json` written
    before they existed still loads.
    """
    from . import external_tool as ET  # deferred: external_tool imports this module
    picked = resolve_transport(active=active, file=file, candidates=candidates, run=run)
    if not picked.get("ok"):
        return picked

    server = picked["server"]
    database, database_source = resolve_database(server, dscmd_exe=dscmd_exe, te2_exe=te2_exe, run=run)
    res = ET.handoff(server, database, project_dir=project_dir, run=run)

    extra = {"transport": picked["transport"], "database_source": database_source}
    path = res.get("path")
    if path and os.path.exists(path):
        try:
            payload = json.loads(textio.read_text(path))
        except (OSError, ValueError):  # a file we just wrote and cannot read back is not fatal
            payload = None
        if isinstance(payload, dict):
            payload.update(extra)
            textio.write_json(path, payload)

    out = {**res, **extra, "source": "ad-pbip handoff", "why": picked["why"], "port": picked["port"]}
    if database_source == "none":
        out["warn"] = NO_DATABASE_WARN
        console.eprint(NO_DATABASE_WARN)
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
    """Reload instance: bridge pipe when available and negotiated, else native close + open."""
    from . import bridge as BR
    b_client, b_man, b_reason = BR.get_bridge_manifest(pid=pid)
    warn_reason = None
    if b_client:
        try:
            if "reload" in b_man.get("operations", []):
                res = b_client.reload()
                b_client.close()
                return {
                    "ok": True,
                    "source": "ad-pbip desktop reload",
                    "pid": pid,
                    "reloaded": True,
                    "reloaded_via": "bridge",
                    "via": "bridge",
                    "elapsed_ms": res.get("elapsed_ms", 0),
                }
            else:
                warn_reason = "operation 'reload' not declared in bridge manifest"
        except Exception as e:
            warn_reason = f"bridge reload failed: {e}"
        finally:
            b_client.close()
    else:
        warn_reason = f"bridge not connected ({b_reason})"

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

    return {**o_res, "reloaded_via": "native", "via": "native", "bridge_fallback": warn_reason}


# ----------------------------------------------------------------- the transport ladder (#117.1)

EXT_PROBE_FILENAME = "zz-probe.pbitool.json"
KILLSWITCH_VALUE = "EnableExternalTools"
RIBBON_REGISTERED = "registered"
RIBBON_WRITABLE = "writable"
RIBBON_NEEDS_IT = "needs-it-file"
RIBBON_DISABLED = "disabled-by-policy"


def _reg_pairs(value: str) -> dict[str, str]:
    """`probe.read_key` answers "Name=value; Name=value"; this is the other half of that spelling."""
    out: dict[str, str] = {}
    for part in (value or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def external_tools_killswitch(run: Runner | None = None) -> tuple[bool, str]:
    r"""Has External Tools been turned off for this machine? `(enabled, evidence)`.

    Four reads, because the one that actually matters is the one that used to be missed:
    `Software\Policies\Microsoft\Power BI Desktop` is where Group Policy writes
    `EnableExternalTools`, and a managed laptop is exactly the machine where a policy exists and the
    product key does not. HKLM before HKCU, policy before product, and the first `0` wins.

    Read-only, through `probe.read_key`, which is `winreg` opened `KEY_READ` on Windows and the
    injected `Runner` everywhere else -- so a key this user may not read comes back as a value, not
    an exception, and "cannot read it" is never reported as "disabled".
    """
    from . import probe as PR  # deferred: probe imports this module
    native = sys.platform == "win32"
    for subkey, label in ((PR.POLICY_KEY, "policy"), (PR.PRODUCT_KEY, "product")):
        for hive in ("HKLM", "HKCU"):
            value, _reason = PR.read_key(hive, subkey, run=run, native=native)
            found = _reg_pairs(value).get(KILLSWITCH_VALUE)
            if found is not None and str(found).strip().lower() in ("0", "false"):
                return False, f"{hive} {label} key: {KILLSWITCH_VALUE}={found}"
    return True, f"no {KILLSWITCH_VALUE}=0 in the policy or product key, either hive"


def _probe_write(path: str) -> None:
    """Create the probe file, exclusively. A separate function so a test can make it fail.

    `O_EXCL` because this runs inside the folder Power BI Desktop reads its ribbon from: a name
    collision must never truncate a file this process did not create. Off Windows, and on a CI that
    runs as root, no permission this repo can set produces the `PermissionError` a managed laptop
    gives -- so the test injects it here rather than pretending a chmod means something.
    """
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)


def external_tools_writable(ext_dir: str) -> tuple[bool, str]:
    """Can this user place a file in the External Tools folder? Create one, delete it, answer.

    The refusal *is* the answer and it is the expected one on the machine #112 measured, so this
    never retries and never asks for elevation -- an `ad-doctor` line that says "run elevated" to a
    user who cannot is worse than no line at all.

    The probe file is deleted in a `finally`. A `zz-probe.pbitool.json` left behind would be a
    broken button on the ribbon of every user of this machine, which is a far bigger mess than the
    question it answers.
    """
    probe = os.path.join(ext_dir, EXT_PROBE_FILENAME)
    created = False
    removed = True
    try:
        _probe_write(probe)
        created = True
    except FileExistsError:
        # Ours, from a run that died between the create and the delete: removing it is the same right.
        created = True
    except OSError as e:
        return False, f"cannot create {EXT_PROBE_FILENAME} in {textio.norm_path(ext_dir)} ({type(e).__name__}: {e})"
    finally:
        if created:
            try:
                os.remove(probe)
            except OSError:
                removed = False
    if not removed:
        return True, (f"created {EXT_PROBE_FILENAME} in {textio.norm_path(ext_dir)} but could not delete it -- "
                      f"remove {textio.norm_path(probe)} by hand, Desktop reads every *.pbitool.json there")
    return True, f"created and deleted {EXT_PROBE_FILENAME} in {textio.norm_path(ext_dir)}"


def ribbon_state(ext_dir: str | None = None, run: Runner | None = None) -> dict:
    """Where the machine-wide ribbon file stands, as a fact rather than an instruction.

    `state` is `registered` (our file is there), `writable` (it is not, but this user could put it
    there), `needs-it-file` (only whoever owns Common Files can) or `disabled-by-policy` (the
    feature is off, so the file would change nothing). `writable` is None for the two states where
    nothing was probed -- registered needs no write, and a machine that has switched External Tools
    off should not be poked to find out who could write to it.

    The contract in #117.1 names three states; `writable` is the fourth because the doctor ladder in
    #117.2 has to tell "run `ad-pbip register-tool`" from "send the package to IT", and that is the
    only thing separating them. A consumer that knows three states reads anything but `registered`
    as not registered and is still right.
    """
    from . import external_tool as ET  # deferred: external_tool imports this module
    directory = ext_dir or ET.external_tools_dir()
    path = os.path.join(directory, ET.TOOL_FILENAME)
    row = {"state": RIBBON_NEEDS_IT, "writable": None, "dir": textio.norm_path(directory),
           "path": textio.norm_path(path), "evidence": ""}

    enabled, why = external_tools_killswitch(run=run)
    if not enabled:
        return {**row, "state": RIBBON_DISABLED,
                "evidence": f"External Tools is switched off for this machine -- {why}; no file placed there "
                            "would appear on the ribbon"}
    if os.path.exists(path):
        return {**row, "state": RIBBON_REGISTERED, "evidence": f"{textio.norm_path(path)} is in place"}
    if not os.path.isdir(directory):
        return {**row, "writable": False,
                "evidence": f"{textio.norm_path(directory)} does not exist -- Power BI Desktop is not "
                            "installed for this machine, or has never created its External Tools folder"}

    writable, detail = external_tools_writable(directory)
    if writable:
        return {**row, "state": RIBBON_WRITABLE, "writable": True,
                "evidence": f"{textio.norm_path(path)} is absent and the folder accepts a write ({detail})"}
    return {**row, "writable": False,
            "evidence": f"{textio.norm_path(path)} is absent and this user may not create it ({detail}); "
                        f"`ad-pbip register-tool --package` writes the file and the request to send with it"}


def te2_action_state(te2_exe: str | None = None, actions_path: str | None = None) -> dict:
    """Is the per-user Tabular Editor transport live: TE2 on this machine *and* our action in it.

    Both halves are needed and neither implies the other. TE2 runs fine from `C:\\Enforce` on the
    machine #112 measured, and its custom actions are a documented per-user feature -- but an
    action that is not in `%LOCALAPPDATA%\\TabularEditor\\CustomActions.json` is not a transport, it
    is an install step (`ad-pbip register-tool --te2`).

    A `CustomActions.json` that fails to parse counts as *not installed*, whatever it may contain:
    Tabular Editor loads no custom actions at all from a file it cannot read, so the menu entry does
    not exist. Judged with `external_tool`'s own parser so the reading and the refusing to rewrite
    can never disagree.
    """
    from .. import config as C
    from . import external_tool as ET  # deferred: external_tool imports this module
    cfg = C.load()
    exe = te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or shutil.which("TabularEditor") or shutil.which("TabularEditor.exe")
    present = bool(exe) and (os.path.exists(exe) or bool(shutil.which(exe)))
    path = actions_path or ET.custom_actions_path()
    installed, detail = False, ""
    if present:
        try:
            actions, _envelope = ET._load_actions(path)
        except ET.MalformedActions as e:
            actions, detail = [], f"{textio.norm_path(path)} does not parse, so Tabular Editor loads no custom action at all ({e.detail})"
        installed = any(isinstance(a, dict) and str(a.get("Name", "")).lower() == ET.TE2_ACTION_NAME.lower()
                        for a in actions)
        if not detail:
            detail = (f'"{ET.TE2_ACTION_NAME}" is in {textio.norm_path(path)}' if installed
                      else f'"{ET.TE2_ACTION_NAME}" is not in {textio.norm_path(path)} -- `ad-pbip register-tool --te2` puts it there')
    else:
        detail = "no TabularEditor.exe configured or on PATH"
    return {"present": present, "exe": textio.norm_path(exe) if exe else None,
            "installed": installed, "path": textio.norm_path(path), "evidence": detail}


def external_tools_row(run: Runner | None = None, ext_dir: str | None = None,
                       actions_path: str | None = None, te2_exe: str | None = None) -> dict:
    """The `external_tools` capability row: which transport is live, and what the ribbon is doing.

    The ladder is #117.1's, in its order: `ribbon:machine` if our file is on the ribbon, else
    `te2:local` if Tabular Editor is here with our action in it, else `zorder`/`file`, which need
    nothing installed and no privileged write and are therefore always on under Windows. The ribbon
    is reported alongside as a *state*, not as an instruction -- `available` stays true through
    `disabled-by-policy`, because that switch turns off a button, not the handoff.
    """
    ribbon = ribbon_state(ext_dir=ext_dir, run=run)
    te2 = te2_action_state(te2_exe=te2_exe, actions_path=actions_path)
    row = {"capability": "external_tools", "ribbon": ribbon["state"]}

    if ribbon["state"] == RIBBON_REGISTERED:
        return {**row, "available": True, "via": "ribbon:machine", "evidence": ribbon["evidence"]}
    if te2["present"] and te2["installed"]:
        return {**row, "available": True, "via": "te2:local",
                "evidence": f'{te2["evidence"]}; ribbon {ribbon["state"]}: {ribbon["evidence"]}'}

    wins = windows_zorder(run=run)
    if wins:
        top = wins[0]
        ev = (f'{len(wins)} Power BI Desktop window(s), on top "{top[1]}" (pid {top[0]}) -- '
              "`ad-pbip handoff --active` hands that one over")
    elif sys.platform == "win32":
        ev = "no Power BI Desktop window open; `ad-pbip handoff --active` works as soon as one is"
    else:
        return {**row, "available": False, "via": "none",
                "evidence": f'no transport: no Desktop window and this is not Windows (sys.platform={sys.platform}); '
                            f'ribbon {ribbon["state"]}: {ribbon["evidence"]}'}
    return {**row, "available": True, "via": "zorder",
            "evidence": f'{ev}; ribbon {ribbon["state"]}: {ribbon["evidence"]}'}


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

    # 3. external_tools -- the transport, not the folder. The folder used to be the whole answer,
    # which made `available` false on every machine where the handoff in fact works (#117.1).
    out.append(external_tools_row(run=run))

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

    # 7. bridge_manifest
    from . import bridge as BR
    b_client, b_man, b_reason = BR.get_bridge_manifest(pid=pid)
    if b_client and b_man:
        ops_str = ", ".join(b_man.get("operations", []))
        ver = b_man.get("version", "unknown")
        out.append({
            "capability": "bridge_manifest",
            "available": True,
            "via": "named_pipe",
            "evidence": f"operations: {ops_str} (v{ver})",
        })
        b_client.close()
    else:
        out.append({
            "capability": "bridge_manifest",
            "available": False,
            "via": "named_pipe",
            "evidence": f"manifest unavailable ({b_reason})",
        })

    # 8. developer_visual
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

    # 9. pbiviz
    pbiviz_path = shutil.which("pbiviz") or shutil.which("pbiviz.cmd")
    out.append({
        "capability": "pbiviz",
        "available": bool(pbiviz_path),
        "via": "npm",
        "evidence": pbiviz_path or "pbiviz not found on PATH",
    })

    return out


def save(pid: int | None = None, run: Runner | None = None, timeout: int = 15) -> dict[str, Any]:
    """Trigger Save on Power BI Desktop via UIAutomation / SendKeys (Ctrl+S)."""
    run_fn = run or default_run
    target_pid = pid
    if target_pid is None:
        insts = status(run=run_fn)
        if insts and insts[0].pid:
            target_pid = insts[0].pid
    if not target_pid:
        return {"ok": False, "error": "no running Power BI Desktop instance found"}

    ps_script = f"""
    try {{
        Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms -ErrorAction SilentlyContinue
        $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, {target_pid})
        $win = [System.Windows.Automation.AutomationElement]::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
        if ($win) {{
            $win.SetFocus()
            [System.Windows.Forms.SendKeys]::SendWait("^s")
            [PSCustomObject]@{{ ok = $true; pid = {target_pid}; method = "sendkeys" }} | ConvertTo-Json -Compress
            exit 0
        }}
        [PSCustomObject]@{{ ok = $false; error = "window for pid {target_pid} not found" }} | ConvertTo-Json -Compress
        exit 1
    }} catch {{
        [PSCustomObject]@{{ ok = $false; error = $_.Exception.Message }} | ConvertTo-Json -Compress
        exit 1
    }}
    """
    rc, out, err = run_fn(PS + [ps_script], timeout)
    if rc == 0 and out.strip():
        try:
            return json.loads(out.strip())
        except Exception:
            pass
    return {"ok": False, "error": err or out or "save failed"}
