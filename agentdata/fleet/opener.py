"""Getting the dashboard in front of the operator, with nothing to install.

A PyCharm plugin and a VS Code extension are two more things to build, sign, ship and update.
Before paying that (#100), this slice uses only what both IDEs already have — and records honestly,
in `docs/fleet-ide.md`, exactly where that falls short.

**One measured finding shapes the whole VS Code path.** `code --command <id>` does not exist:
VS Code 1.129.1's CLI offers `--goto`, `--diff`, `--merge`, `--add`, extension management and
`--agents`, and nothing that invokes a command by id. So nothing outside the editor can open Simple
Browser, and the honest answer is a keybinding or the command palette — with the URL on the
clipboard so the paste is one keystroke rather than a transcription.

**Which forces `/open`.** A per-run token cannot be written into a keybinding, so the server serves
a stable, tokenless, loopback-only `GET /open` that redirects to the real URL. That is not a hole:
any local process can already read `~/.agentdata/fleet/serve.json`, loopback is still enforced, and
a cross-origin page that navigates a window there cannot read where it landed. What it buys is a
URL a person can bookmark, bind to a key, or type.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from .. import proc, textio
from .registry import fleet_dir
from .serve import SERVE_FILE

WHERE = ("browser", "vscode", "pycharm", "edge")
PING_TIMEOUT_S = 2.0

LAUNCHER = "fleet.html"

# A page whose only job is to be somewhere an IDE will open, and to leave immediately for the real
# one. It carries no token: it asks the server for it through the loopback-only redirect.
LAUNCHER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>fleet</title>
<meta http-equiv="refresh" content="0; url={url}">
<style>body{{font:14px system-ui;margin:3rem;color:#444}}</style>
</head>
<body>
<p>Opening the <a href="{url}">fleet dashboard</a>…</p>
<p>If nothing happens, the dashboard is not running: <code>ad-fleet serve</code>.</p>
</body>
</html>
"""


class OpenError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


# ------------------------------------------------------------------------- is one already up?


def serve_record() -> dict:
    try:
        return json.loads(textio.read_text(os.path.join(fleet_dir(), SERVE_FILE)))
    except (OSError, ValueError):
        return {}


def ping(port: int, timeout: float = PING_TIMEOUT_S) -> bool:
    """Is *our* dashboard on that port? Not "is the port open" -- something else may hold it.

    Tokenless on purpose: this answers "is ad-fleet listening" and nothing else, which is what a
    launcher needs before deciding whether to start a second one.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            return json.loads(r.read()).get("service") == "ad-fleet"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def running() -> dict:
    """The live dashboard's record, or `{}`. A stale `serve.json` is not a running server."""
    record = serve_record()
    port = int(record.get("port") or 0)
    return record if port and ping(port) else {}


def start_server(port: int = 8765) -> dict:
    """Start `ad-fleet serve` detached, and wait for it to answer. Returns its record.

    Detached deliberately: `ad-fleet open` is a launcher, and an operator who closes the shell they
    typed it in should not take the dashboard down with it.
    """
    import time

    argv = [sys.executable, "-m", "agentdata", "fleet", "serve", "--port", str(port)]
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=proc.child_env(), **kwargs)

    deadline = time.time() + 20
    while time.time() < deadline:
        record = running()
        if record:
            return record
        time.sleep(0.2)
    raise OpenError("`ad-fleet serve` did not come up within 20 seconds",
                    "start it in its own window to see why: `ad-fleet serve`")


def url_of(record: dict) -> str:
    return str(record.get("url") or "")


def open_url(record: dict) -> str:
    """The stable, tokenless address: bookmarkable, bindable to a key, and safe to write down."""
    port = int(record.get("port") or 0)
    return f"http://127.0.0.1:{port}/open" if port else ""


# ---------------------------------------------------------------------------- the clipboard


def clipboard(text: str) -> bool:
    """Best effort, and honestly reported. A URL nobody can paste is a URL nobody will type."""
    tools = {"nt": [["clip"]], "darwin": [["pbcopy"]]}.get(os.name if os.name == "nt" else sys.platform,
                                                           [["wl-copy"], ["xclip", "-selection", "clipboard"]])
    for argv in tools:
        try:
            p = subprocess.run(argv, input=text.encode("utf-8"), timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if p.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


# ------------------------------------------------------------------------------ the launcher


def write_launcher(directory: str, url: str) -> str:
    """A one-line HTML file that redirects to the dashboard.

    PyCharm's built-in preview opens files *in the project*, not arbitrary URLs. This is the file
    to open — attempt (b) in `docs/fleet-ide.md`. It holds no token: it goes to `/open`, which the
    server resolves.
    """
    path = os.path.join(directory, LAUNCHER)
    textio.write_text(path, LAUNCHER_HTML.format(url=url))
    return textio.norm_path(path)


# --------------------------------------------------------------------------------- opening it


def vscode_exe() -> str:
    return proc.which("code") or ""


def edge_exe() -> str:
    """Edge is rarely on PATH on Windows even though it is always installed."""
    found = proc.which("msedge")
    if found:
        return found
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        candidate = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
        if os.path.isfile(candidate):
            return candidate
    return ""


def open_in(where: str, record: dict, *, launcher_dir: str = "") -> dict:
    """Put the dashboard in front of the operator, and say exactly what was done.

    Every branch returns a row rather than printing one, so `ad-fleet open` and any later caller
    report the same thing -- including the branches that could not do it and fell back.
    """
    url, stable = url_of(record), open_in_url(record)
    if where == "browser":
        import webbrowser

        webbrowser.open(url)
        return {"opened": "default browser", "url": url}

    if where == "edge":
        exe = edge_exe()
        if not exe:
            return _fallback(stable, "Edge was not found",
                             "open the URL in any browser; `--in browser` uses the default one")
        # `--app` gives a chromeless window, which is what a fourth monitor wants. `--new-window`
        # keeps it out of the operator's ordinary browsing session.
        subprocess.Popen([exe, f"--app={url}", "--new-window"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"opened": "Edge, chromeless (--app)", "url": url}

    if where == "vscode":
        if not vscode_exe():
            return _fallback(stable, "VS Code was not found on PATH",
                             "install the `code` command, or use `--in browser`")
        # Measured on 1.129.1: the CLI has no `--command`, so nothing outside the editor can invoke
        # `simpleBrowser.show`. The URL goes on the clipboard and the operator pastes it once.
        return _fallback(stable, "VS Code's CLI cannot invoke a command (no `--command` in 1.129.x)",
                         "Ctrl+Shift+P → `Simple Browser: Show` → paste. `docs/fleet-ide.md` has a "
                         "keybinding that skips the paste.")

    if where == "pycharm":
        if launcher_dir:
            path = write_launcher(launcher_dir, stable)
            return {"opened": "nothing; wrote a launcher to open from the IDE", "url": stable,
                    "launcher": path,
                    "hint": "right-click it in the Project tool window → Open In → Browser"}
        return _fallback(stable, "PyCharm cannot be told to open a URL from outside",
                         "use the External Tool in `docs/fleet-ide.md`, or "
                         "`ad-fleet open --in pycharm --write-launcher .` for a file to open")

    raise OpenError(f"unknown target {where!r}", "one of " + " | ".join(WHERE))


def open_in_url(record: dict) -> str:
    """What to hand a person: the stable address, falling back to the tokened one."""
    return open_url(record) or url_of(record)


def _fallback(url: str, why: str, hint: str) -> dict:
    return {"opened": "nothing", "url": url, "why": why, "hint": hint,
            "clipboard": clipboard(url) if url else False}
