r"""Registering agentdata with Power BI Desktop, and the handoff it triggers.

Desktop reads external tools from exactly one folder,
`%CommonProgramFiles%\Microsoft Shared\Power BI Desktop\External Tools`, and that folder is
machine-scoped: dropping `agentdata.pbitool.json` there is an Administrators-only act. On the
laptop this was measured on (#112) the user cannot elevate, so the ribbon costs one ticket.

**The defect this module fixes is ours.** `render_tool_json()` used to bake `sys.executable` and
`--project` into that file, so the one privileged write would have to be REPEATED after every
interpreter upgrade and every new project -- a ticket per user, per Python, per repository, which
is why the ribbon looked impossible. Fixing that turns it into "one ticket, once, for everyone":
Desktop launches an external tool **as the user**, so a file whose `path` is the literal
`C:\Windows\System32\cmd.exe` and whose `arguments` are
`/c python -m agentdata pbip handoff --server "%server%" --database "%database%"` resolves `python`
from that user's own `PATH` at click time. No interpreter path, no project path, no user name and
no `%VAR%` beyond Desktop's own two substitutes -- which is exactly what makes the file byte-for-byte
identical for every user and every Python version, and therefore worth one ticket forever. Python
is enterprise-approved and on `PATH`, so the launched process is the one `ad-setup` already runs.

What used to be baked in still has to live somewhere, and it lives per-user where no ticket is
needed: `handoff()` resolves the project from the open file, and where that fails it reads
`%LOCALAPPDATA%\agentdata\pbi-handoff.json` (`{project, argv}`), which `ad-setup` writes. That is
the only part that changes over time, and changing it never touches Program Files.

**The TE2 transport (#115)** needs no privileged write at all. Tabular Editor 2 runs fine from
`C:\Enforce`; its *Local instance* picker is how a human says "this window", and its Custom Actions
are a documented per-user feature stored in `%LOCALAPPDATA%\TabularEditor\CustomActions.json`. The
action launches the same approved Python with the same verb, so `handoff()` stays the single
writer. Merging into that file is read, parse, replace-by-`Name` or append, write back -- never a
rewrite from scratch, and never a write at all when the existing file fails to parse: TE2 drops
*all* of a user's custom actions on a syntax error, so silently replacing a malformed file would
destroy work that has nothing to do with us. A refusal with a hint is the only safe answer there.
"""
from __future__ import annotations
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from typing import Callable
from . import desktop as DT
from .. import textio

Runner = Callable[[list[str], int], tuple[int, str, str]]
DEFAULT_ICON = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4nGMQqHH8TwlmGDVg1IBRA4aLAQBRu8wQ68Y02AAAAABJRU5ErkJggg=="
)
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "external-tool")
TEMPLATE_PATH = os.path.join(_TEMPLATE_DIR, "agentdata.pbitool.json")
TE2_SCRIPT_PATH = os.path.join(_TEMPLATE_DIR, "handoff.te2.csx")

TOOL_FILENAME = "agentdata.pbitool.json"
DEFAULT_PACKAGE_DIR = os.path.join(".agent", "out", "external-tool")
# Desktop substitutes these two itself, and nothing else. They are the only % in the file.
HANDOFF_FLAGS = '--server "%server%" --database "%database%"'
DIRECT_ARGS = f"-m agentdata pbip handoff {HANDOFF_FLAGS}"
# `cmd /c` flashes a console window. `start "" /min` would hide it, and it is NOT on by default:
# #113 has to measure whether the flash is actually there and whether it bothers anyone before we
# add a second process to the launch chain on a guess. `minimized=True` is the switch when it does.
MINIMIZED_PREFIX = 'start "" /min '
TE2_ACTION_NAME = "Hand off to agentdata"
TE2_ACTION_TOOLTIP = "Write .agent/desktop.json for this local instance so the agent can query it"
TE2_MODES = ("process", "file")
_BODY = re.compile(r"^// ---8<--- body: (?P<name>\w+)\s*$(?P<body>.*?)^// ---8<--- end\s*$", re.M | re.S)


class MalformedActions(RuntimeError):
    """`CustomActions.json` is not JSON we recognise, so we refuse to write it.

    TE2 loads no custom actions at all when the file fails to parse, so the user has already lost
    their menu; replacing the file would lose the actions themselves too.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{textio.norm_path(path)} is not a Tabular Editor custom-action file ({detail})")
        self.path, self.detail = path, detail
        self.hint = ("fix the JSON in that file, or move it aside and click again -- agentdata will not "
                     "rewrite it, because Tabular Editor drops every custom action in a file it cannot parse")


# ------------------------------------------------------------------------ per-user and machine paths


def _local_appdata() -> str:
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def external_tools_dir() -> str:
    """The machine-scoped folder Desktop reads external tools from. Administrators only."""
    common = os.environ.get("CommonProgramFiles") or r"C:\Program Files\Common Files"
    return os.path.join(common, "Microsoft Shared", "Power BI Desktop", "External Tools")


def custom_actions_path() -> str:
    r"""`%LOCALAPPDATA%\TabularEditor\CustomActions.json` -- TE2's documented per-user action store."""
    return os.path.join(_local_appdata(), "TabularEditor", "CustomActions.json")


def handoff_pointer_path() -> str:
    r"""`%LOCALAPPDATA%\agentdata\pbi-handoff.json` -- `{project, argv}`.

    The machine file must not name a project, so the project has to be named somewhere else. Here:
    per-user, rewritable by the user who owns it, and never the subject of a ticket.
    """
    return os.path.join(_local_appdata(), "agentdata", "pbi-handoff.json")


def system_cmd_exe() -> str:
    r"""The literal `%SystemRoot%\System32\cmd.exe`, resolved at render time.

    Resolved rather than left as `%SystemRoot%` because Desktop substitutes `%server%` and
    `%database%` and nothing else -- an unexpanded variable in `path` is a file that does not
    launch. `SystemRoot` is machine-wide, so resolving it keeps the file identical between users.
    """
    root = (os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows").rstrip("\\/")
    return root + r"\System32\cmd.exe"


def read_handoff_pointer(path: str | None = None) -> dict | None:
    """The `{project, argv}` pointer, or None when it is absent or unreadable."""
    p = path or handoff_pointer_path()
    if not os.path.exists(p):
        return None
    try:
        data = json.loads(textio.read_text(p))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------------------- the ribbon file


def is_external_tools_enabled(run: Runner | None = None) -> tuple[bool, str]:
    """Check registry HKLM/HKCU for the EnableExternalTools killswitch."""
    if run:
        script = 'Get-ItemProperty -Path "HKLM:\\SOFTWARE\\Microsoft\\Microsoft Power BI Desktop" -Name "EnableExternalTools" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty EnableExternalTools'
        rc, out, _ = run(DT.PS + [script], 5)
        if rc == 0 and out.strip() == "0":
            return False, "disabled by HKLM EnableExternalTools=0"
        return True, "enabled"

    if sys.platform == "win32":
        try:
            import winreg
            for root, root_name in [(winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")]:
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Microsoft Power BI Desktop") as key:
                        val, _ = winreg.QueryValueEx(key, "EnableExternalTools")
                        if str(val) == "0":
                            return False, f"disabled by {root_name} EnableExternalTools=0"
                except (FileNotFoundError, OSError):
                    pass
            return True, "enabled (registry ok)"
        except Exception:  # noqa: BLE001 - winreg is best effort; absence is not a failure
            pass

    return True, "enabled"


def resolve_launcher(launcher: str | None = None) -> str:
    """What follows `/c` in the ribbon file: `python`, or `py` on a machine that only has that.

    A *name*, not a path -- the whole point is that the user's own PATH resolves it. `--launcher`
    overrides for a site where agentdata lives in a venv: `ad-setup` writes
    `%LOCALAPPDATA%\\agentdata\\bin\\agentdata-handoff.cmd` and the user puts that folder on their
    own PATH, which is a user-scope environment variable and needs nobody's permission.

    **The `shutil.which` fallback is a guess, and it is the wrong measurement**: it reads *this*
    process's PATH, which inside an activated virtualenv contains a `python` that will not be there
    when Desktop launches the tool from a fresh `cmd.exe`. It survives as the default for the cheap
    per-user callers (`--te2`, whose action is re-registered for free at any time) and for a caller
    that passed `--launcher` explicitly. Anything that renders the file which costs an IT ticket
    goes through `measured_launcher()` instead, which asks `cmd.exe`.
    """
    if launcher:
        return launcher.strip().strip('"')
    if shutil.which("python"):
        return "python"
    if shutil.which("py"):
        return "py"
    return "python"


# `verdict.launcher` -> the token that belongs after `/c`. `per-user-launcher` is not in here on
# purpose: there is no name that works, which is why it is a refusal and not a default.
VERDICT_TOKEN = {"cmd-python": "python", "cmd-py": "py"}


def measured_launcher(launcher: str | None = None, run: Runner | None = None) -> dict:
    r"""What the ribbon file should say, measured in the environment Desktop launches into.

    `{"ok", "launcher", "verdict", "evidence"}`, and on `ok: False` a `hint` and a `fail`.

    The file this decides is the one worth a single IT ticket forever, and `REQUEST.md` tells the
    stranger who acts on it that "this request should never reach you a second time". That sentence
    is only true if the launcher name in the file resolves on the *user's* PATH at click time --
    and the name used to come from `shutil.which("python")` in this process, so running
    `ad-pbip register-tool --package` from an activated virtualenv wrote `python`, shipped it to
    IT, and produced a ribbon button that works for nobody. `probe.launcher_verdict()` already
    computed the right answer from a fresh `cmd.exe`; nothing consumed it. This is that wire.

    * `cmd-python` / `cmd-py` -> `python` / `py`.
    * `per-user-launcher` -> refuse. There is no bare name that reaches agentdata on this machine,
      so any file we shipped would be a ticket spent on nothing. `--launcher` is the answer, once
      the shim in `%LOCALAPPDATA%gentdatain` is on the user's PATH.
    * `unknown` -> nothing could be measured, which is every machine that is not Windows. Fall back
      to `python` and say so: the caller prints the warning rather than pretending to a verdict.

    An explicit `launcher` skips the measurement entirely -- the operator has overridden it, and
    re-measuring could only argue with them.
    """
    from . import probe as PRB  # deferred: probe imports desktop, which imports this module
    if launcher:
        return {"ok": True, "launcher": resolve_launcher(launcher), "verdict": "override",
                "evidence": f"--launcher {launcher!r} was given, so nothing was measured"}
    try:
        row = PRB.launcher_verdict(run=run)
    except Exception as e:  # noqa: BLE001 - a probe that will not run is "unknown", not a crash
        row = {"value": "unknown", "reason": f"could not measure ({type(e).__name__}: {e})"}
    verdict, evidence = row.get("value", "unknown"), row.get("reason", "")
    if verdict in VERDICT_TOKEN:
        return {"ok": True, "launcher": VERDICT_TOKEN[verdict], "verdict": verdict, "evidence": evidence}
    if verdict == "per-user-launcher":
        return {"ok": False, "fail": "per_user_launcher", "launcher": "", "verdict": verdict,
                "evidence": evidence,
                "hint": "no bare `python` or `py` on this user's PATH reaches agentdata from a fresh "
                        "cmd.exe, so a machine file naming one would spend an IT ticket on a button that "
                        "does nothing. Put a shim in %LOCALAPPDATA%\\agentdata\\bin, add that folder to "
                        "your own PATH (user scope, no permission needed), then re-run with "
                        "`--launcher agentdata-handoff.cmd`. `ad-pbip handoff --active` needs none of this"}
    return {"ok": True, "launcher": "python", "verdict": "unknown", "evidence": evidence}


def _is_interpreter(launcher: str) -> bool:
    """Whether the launcher takes `-m agentdata`, or is a shim that already carries the verb.

    `python`, `py` and `...\\python.exe` are interpreters and need `-m agentdata pbip handoff`.
    Anything else is the `agentdata-handoff.cmd` shape from `--launcher`: it already knows its venv
    interpreter and the verb, so appending them again would run the wrong Python, or agentdata
    twice.
    """
    stem = os.path.splitext(os.path.basename(textio.norm_path(launcher)))[0].lower()
    return stem == "py" or stem.startswith("python")


def _cmd_token(value: str) -> str:
    if "%" in value:
        raise ValueError(f"a launcher may not contain '%': {value} -- cmd.exe expands %VAR% on a /c command "
                         "line even inside quotes, and Desktop already owns the only two % in this file; "
                         "pass a name on the user's PATH, or a path with no environment variable in it")
    return f'"{value}"' if " " in value else value


def render_arguments(mode: str = "agnostic", launcher: str | None = None, minimized: bool = False) -> str:
    """The `arguments` string for the given mode. See `render_tool_json` for what the modes mean."""
    if mode == "direct":
        return DIRECT_ARGS
    token = resolve_launcher(launcher)
    tail = f"-m agentdata pbip handoff {HANDOFF_FLAGS}" if _is_interpreter(token) else HANDOFF_FLAGS
    lead = MINIMIZED_PREFIX if minimized else ""
    return f"/c {lead}{_cmd_token(token)} {tail}"


def render_tool_json(mode: str | None = None, launcher: str | None = None, python_exe: str | None = None,
                     project_dir: str | None = None, minimized: bool = False) -> dict:
    r"""The `.pbitool.json` body.

    `mode="agnostic"` (the default, #114) is the file worth one ticket: `path` is the literal
    `C:\Windows\System32\cmd.exe` and `arguments` name only a launcher the user's own PATH
    resolves. Two users on two interpreters render one byte-identical file.

    `mode="direct"` is the pre-#114 shape -- `path` is this interpreter, `--project` may be baked
    in -- kept for `--target-dir` tests and for a machine whose capability row says the External
    Tools folder is writable, where re-registering costs nothing. A caller that passes
    `python_exe` or `project_dir` without naming a mode means that older shape and gets it.
    """
    mode = mode or ("direct" if (python_exe or project_dir) else "agnostic")
    if mode not in ("agnostic", "direct"):
        raise ValueError(f"unknown mode {mode!r}: pass 'agnostic' (the ticket-once file) or 'direct'")

    data = None
    if os.path.exists(TEMPLATE_PATH):
        try:
            data = json.loads(textio.read_text(TEMPLATE_PATH))
        except (OSError, ValueError):
            data = None
    if not isinstance(data, dict):
        data = {
            "version": "1.0.0",
            "name": "agentdata",
            "description": "Antigravity data agent bridge for Power BI Desktop",
            "path": "",
            "arguments": "",
            "iconData": DEFAULT_ICON,
        }

    if mode == "direct":
        data["path"] = textio.norm_path(python_exe or sys.executable)
        args = DIRECT_ARGS
        if project_dir:
            args = f'{args} --project "{textio.norm_path(project_dir)}"'
        data["arguments"] = args
    else:
        data["path"] = system_cmd_exe()
        data["arguments"] = render_arguments("agnostic", launcher=launcher, minimized=minimized)
    return data


def render_tool_text(data: dict) -> str:
    """One serialisation for every writer, so idempotence can be content-addressed."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _windows_path(p: str) -> str:
    """One spelling of a Windows path for a person to retype. See `render_request_md`."""
    return textio.norm_path(p).replace("/", "\\")


def render_request_md(source: str, destination: str, data: dict, digest: str) -> str:
    """The ticket attachment. Written for a stranger in IT who has never heard of this project.

    The destination is spelled with backslashes whatever machine rendered this, because the person
    who acts on it is standing at a Windows shell and will paste the line as it is written.
    """
    destination = _windows_path(destination)
    dest_dir = os.path.dirname(destination)
    return f"""# Request: place one file in the Power BI Desktop External Tools folder

**What is being asked for:** copy one small JSON file into the machine-wide Power BI Desktop
External Tools folder. That is the entire request. Nothing is installed, nothing runs as
Administrator afterwards, and no other change is needed.

**Why it needs you:** that folder is machine-scoped and writable only by Administrators. It is the
only folder Power BI Desktop reads external tools from.

## The file

| | |
|---|---|
| source | `{source}` |
| destination | `{destination}` |
| SHA-256 | `{digest}` |

## Place it

```powershell
Copy-Item -LiteralPath "{source}" -Destination "{destination}" -Force
```

## Undo it

```powershell
Remove-Item -LiteralPath "{destination}" -Force
```

Removing the file removes the ribbon button and nothing else.

## What happens when a user clicks it

Power BI Desktop shows a button named *{data.get('name', 'agentdata')}* on its External
Tools ribbon. Clicking it runs this **as that signed-in user**, never elevated:

```
{data.get('path', '')} {data.get('arguments', '')}
```

`%server%` and `%database%` are substituted by Power BI Desktop itself; they are the local
Analysis Services address of the report the user has open. The command writes one file,
`.agent/desktop.json`, inside that user's own project folder.

## Why this file never needs replacing

This file is identical for every user and every Python version. It launches only `cmd.exe` and the
enterprise-approved Python already on the user's PATH -- it contains no interpreter path, no
project path, no user name, and no environment variable other than the two Power BI Desktop
substitutes above. A Python upgrade, a new starter or a new project changes nothing here, so this
request should never reach you a second time.

## What it does not do

No network access. No credentials: none appear in this file, and none are written by what it
launches. No service, no scheduled task, no driver, no registry change, no resident process.

## Verify before you place it

```powershell
Get-Content -LiteralPath "{source}" -Raw | ConvertFrom-Json
Get-FileHash -LiteralPath "{source}" -Algorithm SHA256
Test-Path -LiteralPath "{dest_dir}"
```
"""


def package(out_dir: str | None = None, launcher: str | None = None, minimized: bool = False,
            run: Runner | None = None) -> dict:
    """Write the user-agnostic tool file and the request that asks someone to place it.

    This is the honest front door: we never write the machine file ourselves, and this folder is
    what gets attached to the ticket.

    The launcher is *measured* first (`measured_launcher`), not guessed from this process's PATH,
    and a machine where no bare name reaches agentdata is a refusal rather than a package -- a
    ticket is a person's afternoon, and spending it on a file that cannot work is the one failure
    this whole epic exists to avoid. `verdict` and `evidence` come back either way so the caller can
    print what was measured.
    """
    measured = measured_launcher(launcher, run=run)
    if not measured["ok"]:
        return {"ok": False, "source": "ad-pbip register-tool --package", "fail": measured["fail"],
                "verdict": measured["verdict"], "evidence": measured["evidence"], "hint": measured["hint"]}

    out = out_dir or DEFAULT_PACKAGE_DIR
    data = render_tool_json(mode="agnostic", launcher=measured["launcher"], minimized=minimized)
    text = render_tool_text(data)
    digest = content_hash(text)
    tool_json = textio.write_text(os.path.join(out, TOOL_FILENAME), text)
    destination = os.path.join(external_tools_dir(), TOOL_FILENAME)
    # absolute: the request is read on someone else's screen, where "the out folder" means nothing
    request = textio.write_text(os.path.join(out, "REQUEST.md"),
                                render_request_md(textio.norm_path(os.path.abspath(tool_json)),
                                                  destination, data, digest))
    return {
        "ok": True,
        "dir": textio.norm_path(out),
        "tool_json": tool_json,
        "request": request,
        "destination": textio.norm_path(destination),
        "sha256": digest,
        "path": data["path"],
        "arguments": data["arguments"],
        "launcher": measured["launcher"],
        "verdict": measured["verdict"],
        "evidence": measured["evidence"],
    }


def register_tool(target_dir: str | None = None, python_exe: str | None = None,
                  project_dir: str | None = None, mode: str | None = None,
                  launcher: str | None = None, run: Runner | None = None) -> tuple[bool, str, str | None]:
    r"""Write `agentdata.pbitool.json` into the External Tools folder, or say who can.

    A `PermissionError` here is the expected answer on a managed laptop, not a bug: the hint names
    the package, because the fix is a ticket with one file attached and not an elevated shell we
    have no evidence the user can open.

    The machine folder is never *created*, only written into. `os.makedirs(exist_ok=True)` used to
    run before the copy, so on a machine where `%CommonProgramFiles%` is unset -- this repo's Linux
    CI, and any box without Power BI Desktop -- it built a literal
    `C:\Program Files\Common Files\Microsoft Shared\...` tree *inside the current working
    directory* and reported `ok`. That is a write into the user's repo, under a name nobody would
    ever look for, plus a false "registered". Only Desktop's own installer owns that folder, so its
    absence is a refusal with the package as the next step. `target_dir` is the test/`--target-dir`
    seam and keeps the create, because there the caller named the folder.
    """
    machine = target_dir is None
    dest_dir = target_dir or external_tools_dir()
    dest_file = os.path.join(dest_dir, TOOL_FILENAME)

    # A direct write into the machine folder produces the same file the ticket would have carried,
    # and every user of the machine clicks it -- so it gets the same measured launcher, not this
    # process's PATH. `--target-dir` is the test seam and skips the measurement, which is five
    # `cmd.exe` reads it has no use for.
    if machine and not launcher and not python_exe and not project_dir and mode in (None, "agnostic"):
        measured = measured_launcher(None, run=run)
        if not measured["ok"]:
            return False, dest_file, measured["hint"]
        launcher = measured["launcher"]

    tool_data = render_tool_json(mode=mode, launcher=launcher, python_exe=python_exe, project_dir=project_dir)

    if machine and not os.path.isdir(dest_dir):
        return False, dest_file, (
            f"{textio.norm_path(dest_dir)} does not exist, so Power BI Desktop is not installed for this "
            f"machine (or this is not Windows) -- agentdata will not create a machine-scoped folder. Run "
            f"`ad-pbip register-tool --package` to write the file and the request instead")

    tmp_file = os.path.join(tempfile.gettempdir(), f"agentdata_{os.getpid()}.pbitool.json")
    with open(tmp_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_tool_text(tool_data))

    try:
        if not machine:
            os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(tmp_file, dest_file)
        try:
            os.remove(tmp_file)
        except OSError:
            pass
        return True, dest_file, None
    except (PermissionError, OSError):
        hint = (f'that folder is machine-scoped, so this is whoever owns it: run `ad-pbip register-tool '
                f'--package` and send the REQUEST.md it writes. The one line in it is PowerShell: '
                f'Copy-Item -LiteralPath "{tmp_file}" -Destination "{dest_file}" -Force')
        return False, dest_file, hint


# ------------------------------------------------------------- the Tabular Editor custom action


def render_te2_script(mode: str = "process", launcher: str | None = None) -> str:
    """One of the two bodies of `handoff.te2.csx`, with `{{launcher}}` substituted.

    `process` launches the approved Python, so `handoff()` stays the single writer. `file` is the
    documented fallback (config `te2_action: file`) for a site where a script may not start a
    process; it writes the payload with `System.IO` and finds the project through the per-user
    pointer.
    """
    if mode not in TE2_MODES:
        raise ValueError(f"unknown te2_action {mode!r}: pass 'process' (launch python) or 'file' (write it here)")
    script = textio.read_text(TE2_SCRIPT_PATH)
    bodies = {m.group("name"): m.group("body").strip("\n") for m in _BODY.finditer(script)}
    if mode not in bodies:
        raise ValueError(f"{textio.norm_path(TE2_SCRIPT_PATH)} has no '{mode}' body -- the packaged "
                         "script is damaged; reinstall agentdata")
    # The launcher lands inside a C# string literal, where `C:\venv\Scripts\python.exe` is not a path
    # but four invalid escape sequences and a script that will not compile.
    token = resolve_launcher(launcher).replace("\\", "\\\\").replace('"', '\\"')
    return bodies[mode].replace("{{launcher}}", token) + "\n"


def te2_custom_action(mode: str = "process", launcher: str | None = None,
                      name: str = TE2_ACTION_NAME) -> dict:
    """One entry for TE2's `CustomActions.json`. `ValidContexts` is `Model`: the action needs a
    connected database and nothing narrower."""
    return {
        "Name": name,
        "Enabled": True,
        "Execute": render_te2_script(mode, launcher),
        "Tooltip": TE2_ACTION_TOOLTIP,
        "ValidContexts": "Model",
    }


def _load_actions(path: str) -> tuple[list, dict | None]:
    """(actions, envelope). Envelope is the wrapper object when TE2 wrote one, else None.

    Raises MalformedActions for anything we do not recognise, so no caller can turn "I cannot read
    this" into "I will replace it".
    """
    if not os.path.exists(path):
        return [], None
    try:
        data = json.loads(textio.read_text(path))
    except (OSError, ValueError) as e:
        raise MalformedActions(path, str(e).split("\n")[0]) from None
    if isinstance(data, list):
        return list(data), None
    if isinstance(data, dict):
        for key in ("Actions", "actions"):
            if isinstance(data.get(key), list):
                return list(data[key]), data
    raise MalformedActions(path, "expected a JSON array of actions")


def _store(actions: list, envelope: dict | None):
    if envelope is None:
        return actions
    out = dict(envelope)
    out["Actions" if "Actions" in envelope else "actions"] = actions
    return out


def merge_custom_action(payload: dict, path: str | None = None) -> dict:
    """Replace our action by `Name`, or append it, leaving every other action exactly as it was."""
    p = path or custom_actions_path()
    name = payload.get("Name") or TE2_ACTION_NAME
    try:
        actions, envelope = _load_actions(p)
    except MalformedActions as e:
        return {"ok": False, "path": textio.norm_path(p), "action": name, "changed": "refused",
                "error": str(e), "hint": e.hint}

    changed, kept = "added", []
    for entry in actions:
        if isinstance(entry, dict) and str(entry.get("Name", "")).lower() == name.lower():
            changed = "unchanged" if entry == payload else "replaced"
            kept.append(payload)
        else:
            kept.append(entry)
    if changed == "added":
        kept.append(payload)

    if changed != "unchanged":
        textio.write_json(p, _store(kept, envelope))
    return {"ok": True, "path": textio.norm_path(p), "action": name, "changed": changed, "count": len(kept)}


def remove_custom_action(name: str = TE2_ACTION_NAME, path: str | None = None) -> dict:
    """Take our action out again, and only ours. A missing file is already the wanted state."""
    p = path or custom_actions_path()
    try:
        actions, envelope = _load_actions(p)
    except MalformedActions as e:
        return {"ok": False, "path": textio.norm_path(p), "action": name, "changed": "refused",
                "error": str(e), "hint": e.hint}
    if not os.path.exists(p):
        return {"ok": True, "path": textio.norm_path(p), "action": name, "changed": "absent", "count": 0}

    kept = [e for e in actions
            if not (isinstance(e, dict) and str(e.get("Name", "")).lower() == name.lower())]
    changed = "removed" if len(kept) != len(actions) else "absent"
    if changed == "removed":
        textio.write_json(p, _store(kept, envelope))
    return {"ok": True, "path": textio.norm_path(p), "action": name, "changed": changed, "count": len(kept)}


def resolve_workspace(server: str, root: str | None = None) -> dict | None:
    r"""The Desktop workspace behind `localhost:<port>`, by the rule `desktop.py` already uses.

    Every open document runs its own `msmdsrv.exe` whose workspace folder holds
    `Data\msmdsrv.port.txt` (UTF-16) with the port, under
    `%LOCALAPPDATA%\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces\*`. This mirrors the
    fallback body of `handoff.te2.csx` in Python so the rule is exercised on every CI run, on a
    laptop or not.

    `pid` is None on purpose: msmdsrv records the port, never its own pid, and the parent
    `PBIDesktop.exe` pid needs the process table, which this rule deliberately does not touch.
    `read_handoff()` tolerates that -- it only checks liveness when a pid is present.
    """
    port = str(server).rsplit(":", 1)[-1].strip()
    base = root or _local_appdata()
    for port_file in sorted(glob.glob(os.path.join(base, DT.WORKSPACE_GLOB))):
        data_dir = os.path.dirname(port_file)
        found = DT.read_port(data_dir)
        if found is not None and str(found) == port:
            return {
                "port": found,
                "server": f"localhost:{found}",
                "workspace_dir": textio.norm_path(data_dir),
                "workspace_name": os.path.basename(os.path.dirname(data_dir)),
                "pid": None,
                "file": None,
            }
    return None


# ------------------------------------------------------------------------------------- the handoff


def is_pid_alive(pid: int | None) -> bool:
    """Check if process id is still alive."""
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 - optional extra
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def handoff(server: str, database: str, project_dir: str | None = None,
            run: Runner | None = None) -> dict:
    """Process Desktop external tool launch and write .agent/desktop.json."""
    inst = None
    target_pid = None
    target_file = None
    port_str = server.split(":")[-1] if ":" in server else server

    try:
        insts = DT.status(run=run)
        for i in insts:
            if str(i.port) == str(port_str) or (i.server and i.server.endswith(str(port_str))):
                inst = i
                target_pid = i.pid
                target_file = i.file or i.matched
                break
    except Exception:  # noqa: BLE001 - discovery is best effort; the handoff still has server/database
        pass

    # Resolve project directory
    resolved_proj = project_dir
    if not resolved_proj and target_file:
        cand = os.path.dirname(target_file)
        while cand and cand != os.path.dirname(cand):
            if os.path.exists(os.path.join(cand, ".agent")) or os.path.exists(os.path.join(cand, "AGENTS.md")):
                resolved_proj = cand
                break
            cand = os.path.dirname(cand)

    # The machine file names no project, by design (#114). This per-user pointer is where the
    # project went, so a ribbon click for a file in no known project still lands somewhere real.
    if not resolved_proj:
        pointer = read_handoff_pointer()
        candidate = (pointer or {}).get("project")
        if candidate and os.path.isdir(candidate):
            resolved_proj = candidate

    if not resolved_proj:
        # Never `"."`. Two of the four transports launch this from a working directory that is not
        # the user's: Desktop hands `cmd.exe` its own `...\\Microsoft Power BI Desktop\\bin`, and the
        # TE2 `process` body sets no `WorkingDirectory` at all, so it inherits Tabular Editor's --
        # `C:\\Enforce` on the machine #112 measured. A `"."` fallback therefore wrote
        # `.agent/desktop.json` into a folder outside every allowed root and printed
        # "handed off to bin", a false success no consumer would ever find. The `file` body of
        # `handoff.te2.csx` already refuses here; this is the same refusal for the single writer.
        return {
            "ok": False,
            "source": "ad-pbip handoff",
            "fail": "no_project",
            "server": server,
            "database": database,
            "pid": target_pid,
            "file": target_file,
            "hint": "this model belongs to no known project: run `ad-setup --project <folder>` once "
                    "(it writes the per-user pointer), or pass `ad-pbip handoff --project <folder>`, "
                    "then click again",
        }

    agent_dir = os.path.join(resolved_proj, ".agent")
    os.makedirs(agent_dir, exist_ok=True)
    desktop_json = os.path.join(agent_dir, "desktop.json")

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "server": server,
        "database": database,
        "pid": target_pid,
        "file": target_file,
        "handed_off_at": now_iso,
    }

    with open(desktop_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    proj_name = os.path.basename(os.path.abspath(resolved_proj))
    print(f"handed off to {proj_name} ({server})")

    return {
        "ok": True,
        "project": resolved_proj,
        "server": server,
        "database": database,
        "pid": target_pid,
        "file": target_file,
        "handed_off_at": now_iso,
        "path": desktop_json,
    }


def read_handoff(project_dir: str | None = None, max_age_seconds: float = 8 * 3600) -> dict | None:
    """Read .agent/desktop.json if it is fresh and the Desktop pid is still alive."""
    base = project_dir or "."
    desktop_json = os.path.join(base, ".agent", "desktop.json")
    if not os.path.exists(desktop_json):
        return None

    try:
        with open(desktop_json, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 - a half-written file is a stale handoff, not a crash
        return None

    handed_off = data.get("handed_off_at")
    if handed_off:
        try:
            ts = datetime.fromisoformat(handed_off.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > max_age_seconds:
                return None
        except Exception:  # noqa: BLE001 - an unparseable stamp is not evidence of staleness
            pass

    pid = data.get("pid")
    if pid and not is_pid_alive(pid):
        return None

    return data
