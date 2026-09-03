r"""Starting other programs, correctly, on Windows.

Windows `CreateProcess` only ever appends `.exe`: handing it the bare name of a tool installed by npm
(`pncli` -> `pncli.cmd`) fails with `[WinError 2] The system cannot find the file specified`, which is what
`ad-pncli jira search` hit on the laptop. `cmd.exe` resolves `.cmd`/`.bat` through `PATHEXT`; Python does not.

So every subprocess in this package goes through `command()`:
  1. resolve the name over PATH honouring PATHEXT (.exe, .cmd, .bat, extension-less shim), plus the npm global
     prefix, which is where npm-installed CLIs live and is often not on a locked-down laptop's PATH;
  2. an npm `.cmd` shim is unwrapped to `node <script>` so arguments keep exact argv semantics -- a JQL such as
     `updated >= '2026-01-01'` must never be re-parsed by `cmd.exe`, where `>` is a redirection;
  3. only if the shim cannot be unwrapped (az.cmd calls python, not node), fall back to `cmd.exe /d /s /c` with
     cmd-safe quoting, and refuse rather than corrupt an argument that cmd.exe would expand (`%VAR%`). That command
     line is returned as a STRING: handing subprocess a list would put it through list2cmdline, which escapes inner
     quotes with backslashes (`\"\"C:\Program Files\...`) and makes cmd.exe answer "The filename, directory name,
     or volume label syntax is incorrect".
Failures raise ProcError, which carries the fix in `hint`; nothing here ever prints a traceback at an agent."""
from __future__ import annotations
import os
import subprocess
import time

from . import textio

WINDOWS = os.name == "nt"
# preferred order: a real executable, then npm/pip command shims, then the extension-less sh shim npm also writes
WIN_EXTS = (".exe", ".com", ".cmd", ".bat", "")
NPM_DIRS = (r"%APPDATA%\npm", r"%ProgramFiles%\nodejs", r"%ProgramFiles(x86)%\nodejs", r"%LOCALAPPDATA%\npm",
            "~/.npm-global/bin", "~/.nvm/current/bin", "/usr/local/bin", "/usr/bin")
# installers that do not always leave their directory on PATH (or leave it only for new shells)
TOOL_DIRS = {
    "az": (r"%ProgramFiles%\Microsoft SDKs\Azure\CLI2\wbin", r"%ProgramFiles(x86)%\Microsoft SDKs\Azure\CLI2\wbin",
           r"%LOCALAPPDATA%\Programs\Microsoft SDKs\Azure\CLI2\wbin"),
}
CMD_UNSAFE = "%"          # cmd.exe expands %VAR% even inside quotes; there is no escape on a /c command line
SHIM_EXTS = (".cmd", ".bat")
NODE_EXTS = (".js", ".cjs", ".mjs")


class ProcError(Exception):
    """A program could not be started or resolved. `code` is machine-readable; `hint` is the fix."""

    def __init__(self, code: str, msg: str, hint: str = "", detail: dict | None = None):
        super().__init__(msg)
        self.code, self.msg, self.hint, self.detail = code, msg, hint, detail or {}


def _exts(windows: bool, pathext: str | None) -> tuple[str, ...]:
    if not windows:
        return ("",)
    raw = pathext if pathext is not None else os.environ.get("PATHEXT", "")
    known = [e.lower() for e in raw.split(os.pathsep) if e.strip()]
    extra = tuple(e for e in known if e not in WIN_EXTS)
    return WIN_EXTS + extra


def _dirs(path: str | None, windows: bool, name: str = "") -> list[str]:
    raw = path if path is not None else os.environ.get("PATH", "")
    out = [d for d in raw.split(os.pathsep) if d]
    for d in TOOL_DIRS.get(os.path.splitext(name)[0].lower(), ()) + NPM_DIRS:   # installers that skip PATH
        e = os.path.expandvars(os.path.expanduser(d))
        if "%" in e or "$" in e:
            continue
        if os.path.isdir(e) and e not in out:
            out.append(e)
    return out


def which(name: str, *, path: str | None = None, windows: bool | None = None, pathext: str | None = None) -> str | None:
    """PATHEXT-aware resolution. A name with a separator is treated as a path (extensions still tried)."""
    windows = WINDOWS if windows is None else windows
    exts = _exts(windows, pathext)
    if os.path.dirname(name):
        base = os.path.abspath(os.path.expanduser(name))
        for e in ("",) + exts if os.path.splitext(name)[1] else exts:
            if os.path.isfile(base + e):
                return base + e
        return None
    if os.path.splitext(name)[1] and windows:             # explicit extension: try it first
        exts = (os.path.splitext(name)[1].lower(),) + exts
        name = os.path.splitext(name)[0]
    for d in _dirs(path, windows, name):
        for e in exts:
            p = os.path.join(d, name + e)
            if os.path.isfile(p) and (windows or os.access(p, os.X_OK)):
                return os.path.normpath(p)
    return None


def _script_from(text: str) -> str | None:
    """The JS entry point an npm shim runs, relative to the shim directory (%~dp0 / %dp0% / $basedir)."""
    import re
    for rx in (r'"%~?dp0%?[\\/]+([^"]+?\.[cm]?js)"', r'"\$basedir/([^"]+?\.[cm]?js)"', r'%~?dp0%?[\\/]+(\S+?\.[cm]?js)'):
        m = re.search(rx, text, re.I)
        if m:
            return m.group(1).replace("\\", "/")
    return None


SHIM_HEAD = 16384      # a command shim is a few hundred bytes; never read a 100 MB binary looking for one


def _head(path: str) -> str | None:
    """First SHIM_HEAD bytes as text, or None for a binary (a real executable is not a shim)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(SHIM_HEAD)
    except OSError:
        return None
    return None if b"\x00" in raw[:1024] else textio.decode(raw)


def unwrap_shim(shim: str, *, windows: bool | None = None) -> tuple[str, str] | None:
    """(node executable, script path) for an npm command shim, else None. Lets us skip cmd.exe entirely."""
    windows = WINDOWS if windows is None else windows
    text = _head(shim)
    if text is None:
        return None
    rel = _script_from(text)
    if not rel:
        return None
    script = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(shim)), rel))
    if not os.path.isfile(script):
        return None
    local = os.path.join(os.path.dirname(os.path.abspath(shim)), "node.exe" if windows else "node")
    node = local if os.path.isfile(local) else which("node", windows=windows)
    return (node, script) if node else None


def cmd_line(argv: list[str]) -> str:
    """Command line for `cmd.exe /d /s /c`. Refuses arguments cmd.exe would expand or split."""
    parts = []
    for a in argv:
        a = str(a)
        if CMD_UNSAFE in a or "\r" in a or "\n" in a:
            raise ProcError("cmd_unsafe_argument", f"argument cannot be passed through cmd.exe: {a[:60]!r}",
                            "install Node.js so the npm shim runs directly, or pin the tool's entry point "
                            "(for pncli: the `pncli.exe` config key or PNCLI_EXE, pointed at the .js file)")
        parts.append('"' + a.replace('"', '""') + '"')   # quote every part: paths hold spaces, JQL holds >, & and |
    return '"' + " ".join(parts) + '"'


def resolve(name: str, *, exe: str | None = None, windows: bool | None = None, path: str | None = None) -> dict:
    """What starting `name` would actually run. Never raises: `found` says whether it resolved."""
    windows = WINDOWS if windows is None else windows
    tried: list[str] = []
    p = None
    if exe:
        p = which(exe, windows=windows, path=path)
        tried.append(f"{exe} (configured)")
        if not p:
            return {"found": False, "name": name, "tried": tried, "kind": "", "path": "",
                    "error": f"configured path not found: {exe}"}
    if not p:
        p = which(name, windows=windows, path=path)
        tried.append(f"{name} on PATH" + (f" + PATHEXT ({', '.join(e for e in _exts(windows, None) if e)})" if windows else ""))
        if windows:
            extra = TOOL_DIRS.get(name.lower(), ())
            tried.append("npm global prefix (%APPDATA%\\npm, %ProgramFiles%\\nodejs)" if not extra else "; ".join(extra))
    if not p:
        return {"found": False, "name": name, "tried": tried, "kind": "", "path": ""}
    info = {"found": True, "name": name, "path": p.replace("\\", "/"), "tried": tried, "kind": "executable",
            "node": "", "script": ""}
    if p.lower().endswith(NODE_EXTS):        # a pinned entry point (the escape hatch cmd_line's hint offers)
        node = which("node", windows=windows)
        if node:
            info.update(kind="node script", node=node.replace("\\", "/"), script=info["path"])
        else:
            info["error"] = "no `node` on PATH to run " + info["path"]
    elif windows and p.lower().endswith(SHIM_EXTS):
        info["kind"] = "cmd shim"
        target = unwrap_shim(p, windows=windows)
        if target:
            info.update(kind="npm shim", node=target[0].replace("\\", "/"), script=target[1].replace("\\", "/"))
    elif not windows and os.path.splitext(p)[1] == "":
        target = unwrap_shim(p, windows=windows)
        if target:
            info.update(kind="npm shim", node=target[0].replace("\\", "/"), script=target[1].replace("\\", "/"))
    return info


def prepare(argv: list[str], *, exe: str | None = None, windows: bool | None = None, path: str | None = None,
            hint: str = "") -> tuple[list[str] | str, dict]:
    """(what to hand subprocess, resolution info). A `.cmd`/`.bat` that is not an npm shim comes back as a STRING:
    subprocess must pass that command line to Windows verbatim, never through list2cmdline."""
    windows = WINDOWS if windows is None else windows
    info = resolve(argv[0], exe=exe, windows=windows, path=path)
    if not info["found"]:
        raise ProcError("not_found", info.get("error") or f"{argv[0]}: executable not found",
                        hint or f"install {argv[0]} and put it on PATH", {"tried": info["tried"], "name": argv[0]})
    if info["kind"] in ("npm shim", "node script"):
        return [info["node"], info["script"], *argv[1:]], info
    if info["kind"] == "cmd shim":
        comspec = os.path.normpath(os.environ.get("COMSPEC") or "cmd.exe")
        return f'"{comspec}" /d /s /c {cmd_line([os.path.normpath(info["path"]), *argv[1:]])}', info
    return [info["path"], *argv[1:]], info


def command(argv: list[str], **kw) -> list[str] | str:
    """What to hand subprocess: a list, or a Windows command line string for a non-npm `.cmd` shim."""
    return prepare(argv, **kw)[0]


def run(argv: list[str], *, exe: str | None = None, timeout: int = 120, hint: str = "", check: bool = False,
        cwd: str | None = None, progress: str | None = None) -> tuple[int, str, str, float]:
    """(returncode, stdout, stderr, elapsed). Raises ProcError for start failures and, with check, for exit != 0."""
    real, info = prepare(argv, exe=exe, hint=hint)
    launched = info["path"]
    t0 = time.time()
    try:
        if progress:
            from . import ui
            with ui.progress(progress):
                p = subprocess.run(real, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                                   encoding="utf-8", errors="replace")
        else:
            p = subprocess.run(real, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                               encoding="utf-8", errors="replace")
    except FileNotFoundError as e:      # resolved, then vanished, or a broken shim target
        raise ProcError("start_failed", f"{argv[0]}: cannot start {launched} ({e.strerror or e})",
                        hint or "re-run `ad-setup --patch`", {"executable": launched, "kind": info["kind"]}) from None
    except OSError as e:
        raise ProcError("start_failed", f"{argv[0]}: cannot start {launched} ({e})", hint,
                        {"executable": launched, "kind": info["kind"]}) from None
    except subprocess.TimeoutExpired:
        raise ProcError("timeout", f"{argv[0]}: no answer after {timeout}s",
                        hint or "raise --timeout, or run the command yourself to see where it hangs") from None
    el = time.time() - t0
    if check and p.returncode != 0:
        tail = (p.stderr or p.stdout or "").strip().splitlines()
        raise ProcError("exit_code", f"{argv[0]} exited {p.returncode}: " + (tail[-1][:200] if tail else "no output"),
                        hint, {"exit_code": p.returncode, "executable": launched})
    return p.returncode, p.stdout, p.stderr, el
