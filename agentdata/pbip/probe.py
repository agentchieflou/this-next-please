r"""Read-only discovery for the Power BI handoff: five questions, one run, one paste-able block.

Issue #113 asked the operator to open a fresh `cmd.exe`, paste five blocks of PowerShell and Python,
click into a Desktop window during a five-second sleep, and paste the output back. That is five
chances to run the wrong block in the wrong shell -- and the *shell matters here more than anywhere
else in this package*: Desktop launches an external tool through `cmd.exe` with the **user's** PATH,
so an answer measured inside an activated virtualenv, or inside PowerShell with a profile that edits
PATH, is not the answer that decides what goes in `agentdata.pbitool.json`. This module runs the
same reads itself, in the same environments, and returns them as rows.

Everything here is a **read**. No file is written, `%CommonProgramFiles%` is not touched, no
elevation is attempted and nothing is installed -- the whole point of #112 is that the one
privileged write belongs to IT, so a probe that needed one would be arguing with its own premise.
That has a consequence worth stating plainly: **a refusal is a result.** A registry key an
unprivileged user may not read, a `where python` that finds nothing, a `C:\Enforce` that does not
exist -- each comes back as a row with its reason, because "access denied" pasted into the ticket is
evidence, and a traceback is not.

Two answers are deliberately *not* automated, and are printed as instructions instead: whether
Tabular Editor's *File > Open > From DB* dialog offers **Local instance**, and whether its Advanced
Scripting tab has **Save as Custom Action**. Both are pixels in someone else's dialog. Clicking them
for the operator would need UI Automation, which #112 withdrew for good, so the honest thing is to
name the two clicks and let a person answer them.

Off Windows -- this repo's CI, and the machine most of this was written on -- the in-process facts
(`sys.executable`, whether `user32` loads) answer truthfully with "n/a" and the reason, and every
external read goes through the injected `Runner`, the same seam `desktop.discover` uses, so the
fakes in `tests/` drive the whole report. What comes back there is the *shape* of the report, never
a claim about a Windows laptop: only the laptop can answer #113.

Row shape is fixed and boring on purpose: `q`, `name`, `value`, `reason`. Uniform keys make
`AgentTable.from_records` render one clean TOON table, and the report carries no timestamps, no
durations and no dict ordering surprises, so two runs on an unchanged machine diff to nothing.
"""
from __future__ import annotations
import json
import os
import sys
from typing import Callable

from .. import proc, textio
from . import desktop as DT
from . import winui

Runner = Callable[[list[str], int], tuple[int, str, str]]

# A fresh cmd.exe, the environment Desktop hands an external tool. `/d` skips AutoRun (a machine
# with a HKCU\...\Command Processor\AutoRun entry would otherwise run it before every probe and
# print its output into ours), `/s` fixes the quoting rules for the string that follows `/c`.
CMD = ["cmd", "/d", "/s", "/c"]
ENFORCE_ROOT = r"C:\Enforce"
TE2_EXE = "TabularEditor.exe"
TE2_LOCAL_DIR = "TabularEditor"
CUSTOM_ACTIONS = "CustomActions.json"
LAUNCHER_DIR = os.path.join("agentdata", "bin")
PRODUCT_KEY = r"SOFTWARE\Microsoft\Microsoft Power BI Desktop"
POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Power BI Desktop"
PYTHONCORE_KEY = r"SOFTWARE\Python\PythonCore"
# PowerShell staples every provider item with these; they are noise in a registry dump.
PS_NOISE = ("PSPath", "PSParentPath", "PSChildName", "PSDrive", "PSProvider")
DENIED = ("denied", "not allowed", "unauthorized", "requested registry access")
HUMAN = "ask-a-human"
# The two answers no probe can give, quoted from #113 Q3 so the operator can act without the issue.
HUMAN_QUESTIONS = (
    ("te2.local_instance",
     "with a model open in Desktop, start Tabular Editor, File > Open > From DB: does the dialog "
     "offer 'Local instance' and list the Desktop window by file name?"),
    ("te2.save_as_custom_action",
     "in Tabular Editor, connect and open Advanced Scripting: does the tab have a "
     "'Save as Custom Action' button?"),
)
MAX_WALK_DIRS = 20000   # C:\Enforce is a tool folder, not a drive; a misconfigured root must not hang


def default_run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Launch through `proc.py`, and never raise.

    `proc.run` is used rather than `subprocess` for one reason that matters on the laptop:
    `CreateProcess` only ever appends `.exe`, and the things this module starts (`cmd`, `powershell`)
    are resolved over PATH honouring PATHEXT there. A program that will not start at all is not an
    exception here -- it is a row whose reason carries `ProcError.hint`, which is the sentence that
    tells the operator what to do next.
    """
    try:
        code, out, err, _elapsed = proc.run(list(args), timeout=timeout)
    except proc.ProcError as e:
        return 127, "", f"{e.msg} -- {e.hint}" if e.hint else str(e.msg)
    except Exception as e:  # noqa: BLE001 - a probe that raises is a probe nobody runs twice
        return 127, "", str(e)
    return code, out, err


def _one_line(text: object) -> str:
    """One line, so a value never breaks the table it is printed in.

    `where python` answers with one path per line and a registry dump can carry a newline inside a
    value; TOON would quote either, but a quoted line break still reads as two lines to anything
    that splits, and this report exists to be pasted.
    """
    if text is None:
        return ""
    parts = [p.strip() for p in str(text).splitlines()]
    return "; ".join(p for p in parts if p)


def _row(q: str, name: str, value: object, reason: object = "") -> dict:
    return {"q": q, "name": name, "value": _one_line(value), "reason": _one_line(reason)}


def _cmd(run: Runner, command: str, timeout: int = 30) -> tuple[int, str, str]:
    """(exit code, one-line stdout, one-line stderr) for one command line in a fresh `cmd.exe`."""
    code, out, err = run(CMD + [command], timeout)
    return code, _one_line(out), _one_line(err)


def _ps(run: Runner, script: str, timeout: int = 30) -> tuple[int, str, str]:
    """The same, through the `desktop.PS` prefix, so an existing fake runner already matches on it."""
    code, out, err = run(DT.PS + [script], timeout)
    return code, _one_line(out), _one_line(err)


# ----------------------------------------------------------------------------------- the registry


def _denied(text: str) -> bool:
    low = (text or "").lower()
    return any(word in low for word in DENIED)


def _winreg_values(hive: str, subkey: str) -> tuple[str, str]:
    """Values under one key through `winreg`, opened `KEY_READ` and nothing else."""
    import winreg  # win32 only; every caller reaches this behind a sys.platform check

    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    try:
        with winreg.OpenKey(roots[hive], subkey, 0, winreg.KEY_READ) as key:
            _subkeys, count, _written = winreg.QueryInfoKey(key)
            pairs = []
            for i in range(count):
                name, value, _kind = winreg.EnumValue(key, i)
                pairs.append(f"{name or '(default)'}={value}")
    except FileNotFoundError:
        return "(key not present)", ""
    except PermissionError as e:
        return "access denied", f"{hive}\\{subkey}: {e}"
    except OSError as e:
        return "unreadable", f"{hive}\\{subkey}: {e}"
    return "; ".join(sorted(pairs)) or "(no values)", ""


def _ps_values(run: Runner, hive: str, subkey: str) -> tuple[str, str]:
    """The same key through PowerShell, which is how a fake answers it off Windows."""
    code, out, err = _ps(run, f"Get-ItemProperty -Path '{hive}:\\{subkey}' -ErrorAction SilentlyContinue "
                              f"| ConvertTo-Json -Compress")
    if _denied(err):
        return "access denied", err
    if code != 0:
        return "unreadable", err or f"powershell exited {code}"
    if not out:
        return "(key not present)", ""
    try:
        data = json.loads(out)
    except ValueError:
        return out, "powershell did not answer JSON"
    items = data if isinstance(data, list) else [data]
    pairs = sorted(f"{k}={v}" for item in items if isinstance(item, dict)
                   for k, v in item.items() if k not in PS_NOISE)
    return "; ".join(pairs) or "(no values)", ""


def read_key(hive: str, subkey: str, run: Runner | None = None, native: bool = False) -> tuple[str, str]:
    """(value, reason) for one registry key. Read-only, and a refusal comes back as the value."""
    if native and sys.platform == "win32":
        return _winreg_values(hive, subkey)
    if run is None:
        return "unreadable", f"no runner and no winreg on this platform (sys.platform={sys.platform})"
    return _ps_values(run, hive, subkey)


def _python_installs(hive: str, run: Runner, native: bool) -> tuple[str, str]:
    """`PythonCore\\<version>\\InstallPath` under one hive -- HKLM means per-machine, HKCU per-user.

    #113 records this for the ticket text: an interpreter only this user has is a different sentence
    to IT than one the image already ships.
    """
    if native and sys.platform == "win32":
        import winreg

        roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
        found = []
        try:
            with winreg.OpenKey(roots[hive], PYTHONCORE_KEY, 0, winreg.KEY_READ) as key:
                subkeys, _values, _written = winreg.QueryInfoKey(key)
                for i in range(subkeys):
                    tag = winreg.EnumKey(key, i)
                    try:
                        with winreg.OpenKey(key, tag + r"\InstallPath", 0, winreg.KEY_READ) as ip:
                            found.append(f"{tag}={winreg.QueryValueEx(ip, '')[0]}")
                    except OSError:
                        continue
        except FileNotFoundError:
            return "(no PythonCore key)", ""
        except PermissionError as e:
            return "access denied", str(e)
        except OSError as e:
            return "unreadable", str(e)
        return "; ".join(sorted(found)) or "(no InstallPath)", ""

    code, out, err = _ps(run, f"Get-ItemProperty -Path '{hive}:\\{PYTHONCORE_KEY}\\*\\InstallPath' "
                              f"-ErrorAction SilentlyContinue | ConvertTo-Json -Compress")
    if _denied(err):
        return "access denied", err
    if code != 0:
        return "unreadable", err or f"powershell exited {code}"
    if not out:
        return "(no PythonCore key)", ""
    try:
        data = json.loads(out)
    except ValueError:
        return out, "powershell did not answer JSON"
    items = data if isinstance(data, list) else [data]
    paths = sorted(str(item.get("(default)")) for item in items
                   if isinstance(item, dict) and item.get("(default)"))
    return "; ".join(paths) or "(no InstallPath)", ""


# ------------------------------------------------------------------------- Q1: python, PATH, cmd


def _user32() -> tuple[str, str]:
    """Whether `user32.dll` loads in *this* interpreter -- the floor `handoff --active` stands on."""
    if sys.platform != "win32":
        return "n/a", f"not Windows (sys.platform={sys.platform}); only the laptop can answer this"
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)  # not windll: it is a process-wide cache
        if hasattr(user32, "EnumWindows"):
            return "EnumWindows available", ""
        return "loaded without EnumWindows", "user32 answered but has no EnumWindows"
    except Exception as e:  # noqa: BLE001
        return "unavailable", str(e)


def _split_path(value: str) -> list[str]:
    """PATH entries. Semicolons when the value came from cmd, the platform separator otherwise."""
    if not value:
        return []
    sep = ";" if ";" in value else os.pathsep
    return [p.strip().strip('"') for p in value.split(sep) if p.strip()]


def _same_dir(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _under(path: str, root: str) -> bool:
    """Is `path` inside `root`? Both spellings first, because `where python` answers in backslashes.

    `textio.norm_path` rather than a separator swap here: this compares a path cmd.exe printed
    against `sys.prefix`, and the two arrive with different separators on the same machine. One
    canonicaliser for both is the only way the answer cannot depend on which one printed it.
    """
    if not path or not root:
        return False
    a = os.path.normcase(textio.norm_path(os.path.normpath(path)))
    b = os.path.normcase(textio.norm_path(os.path.normpath(root))).rstrip("/")
    return a == b or a.startswith(b + "/")


def measure_launcher(run: Runner | None = None) -> dict:
    """The five fresh-`cmd.exe` reads `verdict.launcher` is decided from, as raw measurements.

    Split out of `_q1` so it has a second caller. `external_tool` renders the one file that costs an
    IT ticket, and the launcher name in it used to come from `shutil.which("python")` *in this
    process* -- inside an activated virtualenv that answers `python`, and the file that reaches IT
    then names an interpreter that exists on nobody's PATH at click time. This is the same question
    asked in the environment Desktop actually launches into, and it is the only measurement allowed
    to decide what goes in the file (#113/#114).
    """
    run = run or default_run
    venv = sys.prefix if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else ""
    where_python_c, where_python_o, where_python_e = _cmd(run, "where python")
    where_py_c, where_py_o, where_py_e = _cmd(run, "where py")
    ver_c, ver_o, ver_e = _cmd(run, "python -V")
    help_c, help_o, help_e = _cmd(run, "python -m agentdata --help", timeout=60)
    help_py_c, help_py_o, help_py_e = _cmd(run, "py -m agentdata --help", timeout=60)
    return {
        "venv": venv,
        "where_python": where_python_o if where_python_c == 0 and where_python_o else "",
        "where_python_reason": where_python_e or f"cmd exited {where_python_c} with no output",
        "where_py": where_py_o if where_py_c == 0 and where_py_o else "",
        "where_py_reason": where_py_e or f"cmd exited {where_py_c} with no output",
        "version": ver_o, "version_reason": ver_e or f"cmd exited {ver_c}", "version_ok": ver_c == 0 and bool(ver_o),
        "help_ok": help_c == 0 and bool(help_o),
        "help_out": help_o, "help_reason": help_e or help_o or f"cmd exited {help_c}",
        "help_py_ok": help_py_c == 0 and bool(help_py_o),
        "help_py_out": help_py_o, "help_py_reason": help_py_e or help_py_o or f"cmd exited {help_py_c}",
    }


def launcher_verdict(run: Runner | None = None, measured: dict | None = None) -> dict:
    """The `verdict.launcher` row on its own, for a caller that has to *act* on it rather than print it.

    `cmd-python` / `cmd-py` / `per-user-launcher` / `unknown`; see `_launcher_verdict` for what each
    one means and `external_tool.measured_launcher` for what is done about it.
    """
    m = measured if measured is not None else measure_launcher(run)
    return _launcher_verdict(m["where_python"], m["where_py"], m["help_ok"], m["help_py_ok"], m["venv"])


def _q1(run: Runner, native: bool, localappdata: str | None) -> list[dict]:
    rows: list[dict] = []
    rows.append(_row("Q1", "python.executable", textio.norm_path(sys.executable)))
    rows.append(_row("Q1", "python.version", "%d.%d.%d" % sys.version_info[:3],
                     "" if sys.version_info >= (3, 12) else "agentdata needs Python >= 3.12"))

    m = measure_launcher(run)
    venv = m["venv"]
    rows.append(_row("Q1", "python.venv", textio.norm_path(venv) if venv else "none",
                     "a virtualenv is active: what resolves here is not what Desktop resolves" if venv else ""))

    value, reason = _user32()
    rows.append(_row("Q1", "python.ctypes_user32", value, reason))

    where_python, where_py = m["where_python"], m["where_py"]
    rows.append(_row("Q1", "where.python", where_python or "not found",
                     "" if where_python else m["where_python_reason"]))
    rows.append(_row("Q1", "where.py", where_py or "not found",
                     "" if where_py else m["where_py_reason"]))
    rows.append(_row("Q1", "cmd.python_version", m["version"] or "unreadable",
                     "" if m["version_ok"] else m["version_reason"]))

    help_ok, help_py_ok = m["help_ok"], m["help_py_ok"]
    rows.append(_row("Q1", "cmd.agentdata_help",
                     f'answers: {m["help_out"][:120]}' if help_ok else "no answer",
                     "" if help_ok else m["help_reason"]))
    rows.append(_row("Q1", "cmd.agentdata_help_py",
                     f'answers: {m["help_py_out"][:120]}' if help_py_ok else "no answer",
                     "" if help_py_ok else m["help_py_reason"]))

    code, out, err = _cmd(run, "echo %PATH%")
    path_value = out if code == 0 and out else ""
    rows.append(_row("Q1", "cmd.path", path_value or "unreadable",
                     "" if path_value else (err or f"cmd exited {code}")))

    code, out, err = _ps(run, "'ps ' + $PSVersionTable.PSVersion + ' / ' + "
                              "$ExecutionContext.SessionState.LanguageMode")
    rows.append(_row("Q1", "powershell.mode", out or "unreadable",
                     "" if code == 0 and out else (err or f"powershell exited {code}")))

    for hive in ("HKLM", "HKCU"):
        value, reason = _python_installs(hive, run, native)
        rows.append(_row("Q1", f"registry.python.{hive.lower()}", value, reason))

    base = localappdata if localappdata is not None else (os.environ.get("LOCALAPPDATA") or "")
    if base:
        launcher = os.path.join(base, LAUNCHER_DIR)
        entries = _split_path(path_value) or _split_path(os.environ.get("PATH", ""))
        on_path = any(_same_dir(entry, launcher) for entry in entries)
        rows.append(_row("Q1", "launcher.dir",
                         f"{textio.norm_path(launcher)} "
                         f"({'exists' if os.path.isdir(launcher) else 'missing'}, "
                         f"{'on PATH' if on_path else 'not on PATH'})"))
    else:
        launcher = ""
        rows.append(_row("Q1", "launcher.dir", "unknown", "%LOCALAPPDATA% is not set"))

    rows.append(_launcher_verdict(where_python, where_py, help_ok, help_py_ok, venv))
    return rows


def _launcher_verdict(where_python: str, where_py: str, help_ok: bool, help_py_ok: bool,
                      venv: str) -> dict:
    """The shape of #114's machine file, decided by measurement rather than by preference.

    The file is worth one IT ticket forever only if it names no interpreter path, so the question is
    exactly: does a bare `python` (or `py`), resolved from this user's PATH by `cmd.exe`, reach an
    interpreter that can import agentdata? If the only `python` on PATH is the one a virtualenv put
    there, the answer is no however well it works right now -- Desktop launches the tool with the
    user's PATH, in which the venv does not appear.
    """
    first = (where_python.split("; ")[0] if where_python else "")
    in_venv = bool(venv) and _under(first, venv)
    if not where_python and not where_py:
        return _row("Q1", "verdict.launcher", "unknown",
                    "neither `where python` nor `where py` answered; run `ad-pbip probe` in a fresh "
                    "cmd.exe on the laptop -- this is the one row nobody can fill in off Windows")
    if where_python and not in_venv and help_ok:
        return _row("Q1", "verdict.launcher", "cmd-python",
                    f"`python` on PATH is {first} and `python -m agentdata --help` answers, so the "
                    f"machine file can stay user-agnostic: cmd.exe /c python -m agentdata ...")
    if not where_python and where_py and help_py_ok:
        return _row("Q1", "verdict.launcher", "cmd-py",
                    "`python` is not on PATH but `py -m agentdata --help` answers, so the machine "
                    "file must say `py -m agentdata` (register-tool picks this shape up)")
    if in_venv:
        return _row("Q1", "verdict.launcher", "per-user-launcher",
                    f"the only `python` on PATH is inside the active virtualenv ({textio.norm_path(venv)}); "
                    f"Desktop launches with the user's PATH, where it will not be -- ship a launcher in "
                    f"%LOCALAPPDATA%\\agentdata\\bin and put that on PATH")
    return _row("Q1", "verdict.launcher", "per-user-launcher",
                "`python` resolves but `-m agentdata` does not answer from a fresh cmd.exe, so no "
                "user-agnostic file can work yet -- ship a launcher in %LOCALAPPDATA%\\agentdata\\bin "
                "and put that on PATH")


# --------------------------------------------------------------------------------- Q4: Z-order


def _q4(run: Runner) -> list[dict]:
    rows: list[dict] = []
    try:
        windows, source = winui.desktop_windows_source(run=run)
    except Exception as e:  # noqa: BLE001 - one broken read must not cost the other four questions
        return [_row("Q4", "zorder", "unavailable", str(e))]

    # Which measurement answered is itself a probe row: `verdict.zorder: yes` used to be printed on
    # any Windows box with a window open, including one whose `EnumWindows` call had just failed and
    # fallen through to the process table. The probe exists to send evidence to the issue, and "the
    # rows are in the order Get-Process gave" is a different piece of evidence from "Z-order".
    rows.append(_row("Q4", "zorder.source", source,
                     "user32.EnumWindows walked the Z-order" if source == winui.SOURCE_ENUM else
                     "the process table, which has no Z-order -- these rows are not stacking order"))

    off_windows = "" if sys.platform == "win32" else (
        f"off Windows (sys.platform={sys.platform}) winui falls back to the process table, which has "
        f"no Z-order: this is the shape of the answer, not the answer")
    rows.append(_row("Q4", "zorder.count", str(len(windows)),
                     off_windows or ("" if windows else
                                     "no visible window whose title ends in 'Power BI Desktop'")))
    top_reason = ("highest in Z-order: the window the human touched last" if source == winui.SOURCE_ENUM
                  else "first row the process table gave, NOT the window on top")
    for i, (pid, title) in enumerate(windows):
        rows.append(_row("Q4", f"zorder.{i}", f"pid {pid}  {title}", top_reason if i == 0 else ""))

    if sys.platform != "win32":
        rows.append(_row("Q4", "verdict.zorder", "unknown",
                         "Z-order can only be measured on the laptop; run `ad-pbip probe` there, "
                         "click the other Desktop window, and run it again -- line zorder.0 must flip"))
    elif source != winui.SOURCE_ENUM:
        rows.append(_row("Q4", "verdict.zorder", "no",
                         "this is Windows and the ctypes call to user32.EnumWindows did not answer, so "
                         "`handoff --active` refuses here (no_zorder); hand off with `--file <name>` and "
                         "paste line python.ctypes_user32 into the issue"))
    elif not windows:
        rows.append(_row("Q4", "verdict.zorder", "no",
                         "no Desktop window is open; open a report and re-run"))
    else:
        rows.append(_row("Q4", "verdict.zorder", "yes",
                         f"{len(windows)} Desktop window(s), highest first -- `handoff --active` "
                         f"needs nothing beyond ctypes"))
    return rows


# --------------------------------------------------------------------- Q3: Tabular Editor 2


def _walk_for(root: str, filename: str) -> tuple[str, str]:
    """First match under `root`, walked in sorted order so two runs agree. (path, reason)."""
    problems: list[str] = []
    target = filename.lower()
    seen = 0
    for base, dirs, files in os.walk(root, onerror=lambda e: problems.append(str(e))):
        seen += 1
        if seen > MAX_WALK_DIRS:
            return "", f"gave up after {MAX_WALK_DIRS} directories under {root}"
        dirs.sort()
        for name in sorted(files):
            if name.lower() == target:
                return os.path.join(base, name), ""
    return "", ("; ".join(problems[:3]) if problems else "")


def _find_te2(run: Runner, enforce_root: str) -> tuple[str, str]:
    """TabularEditor.exe under the developer folder. Locally when the folder is there, else the runner."""
    if os.path.isdir(enforce_root):
        hit, reason = _walk_for(enforce_root, TE2_EXE)
        if hit:
            return textio.norm_path(hit), ""
        return "", reason or f"no {TE2_EXE} under {enforce_root}"
    code, out, err = _ps(run, f"Get-ChildItem -LiteralPath '{enforce_root}' -Recurse -Filter {TE2_EXE} "
                              f"-ErrorAction SilentlyContinue | Select-Object -First 1 "
                              f"-ExpandProperty FullName", timeout=120)
    if code == 0 and out:
        return textio.norm_path(out.split("; ")[0]), ""
    return "", err or f"{enforce_root} is not a directory here and PowerShell found nothing"


def _custom_actions(path: str) -> tuple[str, str]:
    """What TE2's per-user custom actions file holds -- read only, and unforgiving about syntax.

    #115 will merge one action into this file, and TE2 drops **all** custom actions when it fails to
    parse. So the probe records "unparseable" as a first-class answer: that is the state in which the
    register verb must refuse rather than rewrite.
    """
    if not os.path.exists(path):
        return "missing", ""
    try:
        raw = textio.read_text(path)
    except OSError as e:
        return "unreadable", str(e)
    try:
        data = json.loads(raw) if raw.strip() else []
    except ValueError as e:
        return "unparseable", f"TE2 drops ALL custom actions when this file fails to parse: {e}"
    items = data if isinstance(data, list) else [data]
    names = sorted(str(item.get("Name")) for item in items
                   if isinstance(item, dict) and item.get("Name"))
    return f"{len(items)} action(s)" + (f": {', '.join(names)}" if names else ""), ""


def _q3(run: Runner, enforce_root: str, localappdata: str | None) -> list[dict]:
    rows: list[dict] = []

    configured = ""
    try:
        from .. import config as C

        configured = C.get(C.load(), "powerbi.tools.te2_exe") or ""
    except Exception as e:  # noqa: BLE001 - a broken config must not stop a read-only probe
        rows.append(_row("Q3", "te2.configured", "unreadable", str(e)))
    else:
        rows.append(_row("Q3", "te2.configured", textio.norm_path(configured) if configured
                         else "(not configured)"))

    exe, reason = _find_te2(run, enforce_root)
    rows.append(_row("Q3", "te2.exe", exe or "not found", "" if exe else reason))

    if exe:
        code, out, err = _ps(run, f'(Get-Item -LiteralPath "{exe}").VersionInfo.ProductVersion')
        rows.append(_row("Q3", "te2.version", out or "unreadable",
                         "" if code == 0 and out else (err or f"powershell exited {code}")))
    else:
        rows.append(_row("Q3", "te2.version", "n/a", f"no {TE2_EXE} to ask"))

    base = localappdata if localappdata is not None else (os.environ.get("LOCALAPPDATA") or "")
    if base:
        te_dir = os.path.join(base, TE2_LOCAL_DIR)
        if os.path.isdir(te_dir):
            names = sorted(os.listdir(te_dir))
            rows.append(_row("Q3", "te2.localappdata_dir",
                             f"{textio.norm_path(te_dir)}: " + (", ".join(names) if names else "(empty)")))
        else:
            rows.append(_row("Q3", "te2.localappdata_dir", f"{textio.norm_path(te_dir)} (missing)",
                             "TE2 creates it on first run; a missing folder is not a failure"))
        value, reason = _custom_actions(os.path.join(te_dir, CUSTOM_ACTIONS))
        rows.append(_row("Q3", "te2.custom_actions", value, reason))
    else:
        rows.append(_row("Q3", "te2.localappdata_dir", "unknown", "%LOCALAPPDATA% is not set"))
        rows.append(_row("Q3", "te2.custom_actions", "unknown", "%LOCALAPPDATA% is not set"))

    for name, question in HUMAN_QUESTIONS:
        rows.append(_row("Q3", name, HUMAN, question))

    if exe:
        rows.append(_row("Q3", "verdict.te2", "machine side ready",
                         "TabularEditor.exe found; the two ask-a-human rows above still decide "
                         "whether te2:local ships (#115)"))
    else:
        rows.append(_row("Q3", "verdict.te2", "no",
                         f"no {TE2_EXE} under {enforce_root}: te2:local has nothing to register into"))
    return rows


# ------------------------------------------------------------------------------- Q5: the registry


def _q5(run: Runner, native: bool) -> list[dict]:
    """The product key and the policy key, both hives.

    The ribbon kill-switch may live in either: `EnableExternalTools` under the product key is the
    documented one, and a managed laptop is exactly the machine where the same setting arrives as
    policy instead. Reading only one hive is how a probe reports "enabled" on a machine where the
    ribbon is off.
    """
    rows: list[dict] = []
    for label, subkey in (("product", PRODUCT_KEY), ("policy", POLICY_KEY)):
        for hive in ("HKLM", "HKCU"):
            value, reason = read_key(hive, subkey, run=run, native=native)
            rows.append(_row("Q5", f"registry.{label}.{hive.lower()}", value, reason))
    return rows


# ------------------------------------------------------------------------------------ the report


def report(run: Runner | None = None, *, localappdata: str | None = None,
           enforce_root: str | None = None) -> list[dict]:
    """Every #113 question as rows: `q`, `name`, `value`, `reason`. Reads only; writes nothing.

    Pass `run` to drive the whole report from fakes -- when a runner is injected the registry is read
    through PowerShell rather than `winreg`, so a Linux CI machine exercises the same rows a laptop
    produces. With no runner and on Windows, `winreg` answers the registry directly: it needs no
    subprocess, returns value names without parsing PowerShell's output, and is opened `KEY_READ`.
    """
    native = run is None
    runner = run or default_run
    root = ENFORCE_ROOT if enforce_root is None else enforce_root
    return [
        *_q1(runner, native, localappdata),
        *_q4(runner),
        *_q3(runner, root, localappdata),
        *_q5(runner, native),
    ]
