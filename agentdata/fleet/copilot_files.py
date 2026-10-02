"""Copilot CLI's own settings and per-repository permissions, read and written for the fleet screen.

The operator, 2026-10-02: "When a user does /config in an individual repository in regular copilot
cli, they're first setting global permissions. What we're trying to do is have the repo permissions
be accessible from the fleet screen in addition to the global settings." And, asked where each
should live: Copilot's own files, so a change on the fleet screen is the change a Copilot window
would make, and the operator's own windows and the fleet's agents read the same thing.

Copilot CLI's configuration directory reference (docs.github.com, "GitHub Copilot CLI
configuration directory") names both files:

* `settings.json` -- "your personal configuration settings", what `/settings`, `/config KEY VALUE`
  and `/config unset KEY` write, whatever repository the window is in. The global layer: the
  repository's `.github/copilot/settings.json` and `settings.local.json`, the environment and the
  command line all override it, in that order.
* `permissions-config.json` -- the approvals a window saves, under `locations`, "keyed by an absolute
  path ... For a Git repository, use the Git root used for permission scoping":
  `{"locations": {"<git root>": {"tool_approvals": [{"kind": "commands", "commandIdentifiers":
  ["git:*"]}], "allowed_directories": ["<path>"]}}}`.

Both live in `$COPILOT_HOME`, else `~/.copilot`. Three rules for touching them, because the
operator's own Copilot reads them on every start:

* **Never write what could not be read.** A file that is not JSON (or not an object) is refused
  `copilot_file_unreadable`, and nothing is written over it.
* **Change one thing, keep everything else.** A write reads the file afresh, changes the one key or
  entry asked for, and writes it back with every key this module does not know about intact, through
  `textio.write_json` (atomic), after copying the previous content to `<file>.bak`.
* **Write only what the reference documents.** An approval the fleet adds is `commands` (with its
  `commandIdentifiers`), `read` or `write`; the other kinds Copilot saves for itself are shown and
  can be removed, never composed here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading

from .. import textio

SETTINGS = "settings.json"
PERMISSIONS = "permissions-config.json"

# Every kind the reference lists for a tool approval; only the first three are written from here.
KINDS = ("commands", "read", "write", "mcp", "mcp-sampling", "memory", "custom-tool",
         "extension-management", "extension-permission-access")
WRITABLE_KINDS = ("commands", "read", "write")

# `settings.json` keys the documentation names, with the shape its tables give them. Any other key in
# the file is still shown and editable, as raw JSON.
KNOWN = {
    "model": ("str", "AI model to use; `auto` lets Copilot pick"),
    "effortLevel": ("str", "reasoning effort for the model"),
    "askUser": ("bool", "allow the agent to ask clarifying questions"),
    "experimental": ("bool", "enable experimental features"),
    "autoUpdate": ("bool", "update the CLI automatically"),
    "theme": ("str", "the CLI's colour theme"),
    "renderMarkdown": ("bool", "render Markdown in the terminal"),
    "beep": ("bool", "beep when a turn needs you"),
    "includeCoAuthoredBy": ("bool", "add a Co-authored-by line to commits"),
    "footer.showBranch": ("bool", "show the git branch in the footer"),
    "sandbox.enabled": ("bool", "restrict shell commands and MCP/LSP servers"),
    "allowedUrls": ("list", "URLs or domains allowed without prompting"),
    "deniedUrls": ("list", "URLs or domains always denied"),
    "permissions.disableBypassPermissionsMode": ("str", "`disable` suppresses every allow-all flag"),
}

_LOCK = threading.Lock()


class CopilotFileError(Exception):
    def __init__(self, code: str, msg: str, hint: str = ""):
        super().__init__(msg)
        self.code, self.msg, self.hint = code, msg, hint


def home() -> str:
    """`$COPILOT_HOME`, else `~/.copilot` -- where Copilot itself looks."""
    configured = os.environ.get("COPILOT_HOME", "").strip()
    return os.path.abspath(os.path.expanduser(configured or os.path.join("~", ".copilot")))


def path_of(name: str) -> str:
    return os.path.join(home(), name)


def _read(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        data = json.loads(textio.read_text(path) or "{}")
    except (OSError, ValueError) as e:
        raise CopilotFileError("copilot_file_unreadable", f"{textio.norm_path(path)} is not JSON ({e})",
                               "fix or move it by hand; the fleet will not write over it") from None
    if not isinstance(data, dict):
        raise CopilotFileError("copilot_file_unreadable", f"{textio.norm_path(path)} is not a JSON object",
                               "fix or move it by hand; the fleet will not write over it")
    return data


def _write(path: str, data: dict) -> None:
    if os.path.isfile(path):
        shutil.copyfile(path, path + ".bak")
    textio.write_json(path, data)


# ------------------------------------------------------------------------------- settings.json


def _flatten(data: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value and name not in KNOWN:
            out.update(_flatten(value, name + "."))
        else:
            out[name] = value
    return out


def global_settings() -> dict:
    """`{path, exists, rows}`: every key in `settings.json` (nested objects by dotted name) and every
    documented key, each with its value (None when unset), its shape and what it is."""
    path = path_of(SETTINGS)
    flat = _flatten(_read(path))
    rows = []
    for key in list(KNOWN) + sorted(k for k in flat if k not in KNOWN):
        kind, about = KNOWN.get(key, ("json", ""))
        rows.append({"key": key, "value": flat.get(key), "set": key in flat, "type": kind, "about": about})
    return {"path": textio.norm_path(path), "exists": os.path.isfile(path), "rows": rows}


def _coerce(key: str, value):
    kind = KNOWN.get(key, ("json", ""))[0]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise CopilotFileError("bad_value", f"{key} is true or false, got {value!r}")
    if kind == "list":
        items = value if isinstance(value, list) else str(value or "").replace(",", "\n").splitlines()
        return [str(v).strip() for v in items if str(v).strip()]
    if kind == "str":
        return str(value)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _check_key(key: str) -> list[str]:
    parts = str(key or "").strip().split(".")
    if not all(p and p.replace("_", "").replace("-", "").isalnum() for p in parts):
        raise CopilotFileError("bad_key", f"{key!r} is not a settings key",
                               "letters and digits, dotted for a nested key: footer.showBranch")
    return parts


def set_global(key: str, value) -> dict:
    """What `/config KEY VALUE` does: one key of `settings.json`, the rest untouched."""
    parts = _check_key(key)
    value = _coerce(key, value)
    with _LOCK:
        path = path_of(SETTINGS)
        data = _read(path)
        if key in data and len(parts) > 1:
            data[key] = value                     # the file already spells it flat: keep its spelling
        else:
            node = data
            for part in parts[:-1]:
                node = node.setdefault(part, {}) if isinstance(node.get(part, {}), dict) else None
                if node is None:
                    raise CopilotFileError("bad_key", f"{key}: {part} is not an object in {SETTINGS}")
            node[parts[-1]] = value
        _write(path, data)
    return global_settings()


def unset_global(key: str) -> dict:
    """What `/config unset KEY` does."""
    parts = _check_key(key)
    with _LOCK:
        path = path_of(SETTINGS)
        data = _read(path)
        if key in data:
            data.pop(key)
        else:
            node = data
            for part in parts[:-1]:
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, dict):
                node.pop(parts[-1], None)
        _write(path, data)
    return global_settings()


def setting(key: str, repo_path: str | None = None):
    """One key's effective value, as Copilot layers it: user, then the repository's
    `.github/copilot/settings.json`, then its `settings.local.json`. None when no file sets it."""
    files = [path_of(SETTINGS)]
    if repo_path:
        files += [os.path.join(repo_path, ".github", "copilot", "settings.json"),
                  os.path.join(repo_path, ".github", "copilot", "settings.local.json")]
    found = None
    for path in files:
        try:
            flat = _flatten(_read(path))
        except CopilotFileError:
            continue
        if key in flat:
            found = flat[key]
    return found


# ---------------------------------------------------------------------- permissions-config.json


def git_root(repo_path: str) -> str:
    """The Git root Copilot scopes a repository's permissions by, in this OS's spelling."""
    try:
        done = subprocess.run(["git", "-C", repo_path, "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=15)
        root = (done.stdout or "").strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        root = ""
    return os.path.normpath(root or os.path.abspath(repo_path))


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _location(data: dict, root: str) -> tuple[str, dict]:
    """The key under `locations` for `root` (an existing one spelled differently is reused) and its
    entry."""
    locations = data.get("locations") if isinstance(data.get("locations"), dict) else {}
    for key, entry in locations.items():
        if _same_path(key, root):
            return key, entry if isinstance(entry, dict) else {}
    return root, {}


def repo_permissions(repo_path: str) -> dict:
    """`{path, location, tool_approvals, allowed_directories}` for one checkout."""
    root = git_root(repo_path)
    key, entry = _location(_read(path_of(PERMISSIONS)), root)
    approvals = [a for a in entry.get("tool_approvals") or [] if isinstance(a, dict)]
    dirs = [str(d) for d in entry.get("allowed_directories") or []]
    return {"path": textio.norm_path(path_of(PERMISSIONS)), "location": key,
            "tool_approvals": approvals, "allowed_directories": dirs}


def approval(kind: str, identifiers=None) -> dict:
    """One tool approval in the shape the reference documents, or a refusal."""
    kind = str(kind or "").strip()
    if kind not in WRITABLE_KINDS:
        raise CopilotFileError("kind_unsupported", f"the fleet adds commands, read or write approvals, not {kind!r}",
                               "Copilot saves the other kinds itself when you approve one in a window")
    if kind != "commands":
        return {"kind": kind}
    items = identifiers if isinstance(identifiers, list) else str(identifiers or "").replace(",", "\n").splitlines()
    ids = [str(i).strip() for i in items if str(i).strip()]
    if not ids or any(len(i) > 200 or "\n" in i for i in ids):
        raise CopilotFileError("bad_value", "a commands approval names its commands",
                               "e.g. git:* for every git command, as Copilot writes them")
    return {"kind": "commands", "commandIdentifiers": ids}


def _same_approval(a: dict, b: dict) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _edit_location(repo_path: str, change) -> dict:
    root = git_root(repo_path)
    with _LOCK:
        path = path_of(PERMISSIONS)
        data = _read(path)
        locations = data.setdefault("locations", {})
        if not isinstance(locations, dict):
            raise CopilotFileError("copilot_file_unreadable", f"{PERMISSIONS}: locations is not an object",
                                   "fix or move it by hand; the fleet will not write over it")
        key, entry = _location(data, root)
        entry = dict(entry)
        change(entry)
        locations[key] = entry
        _write(path, data)
    return repo_permissions(repo_path)


def add_approval(repo_path: str, item: dict) -> dict:
    """Add one approval to this repository's location, once."""
    def change(entry):
        approvals = [a for a in entry.get("tool_approvals") or [] if isinstance(a, dict)]
        if not any(_same_approval(a, item) for a in approvals):
            approvals.append(item)
        entry["tool_approvals"] = approvals
    return _edit_location(repo_path, change)


def remove_approval(repo_path: str, item: dict) -> dict:
    """Remove the approvals equal to `item` (any kind: removing is always safe)."""
    def change(entry):
        entry["tool_approvals"] = [a for a in entry.get("tool_approvals") or []
                                   if not (isinstance(a, dict) and _same_approval(a, item))]
    return _edit_location(repo_path, change)


def set_directories(repo_path: str, dirs) -> dict:
    """This repository's `allowed_directories`, replaced: absolute paths, each once."""
    out = []
    for d in dirs or []:
        text = str(d or "").strip()
        if not text:
            continue
        if not (os.path.isabs(text) or (len(text) > 2 and text[1] == ":")):
            raise CopilotFileError("bad_value", f"{text!r} is not an absolute path",
                                   "Copilot resolves a relative one against wherever it was started")
        if text not in out:
            out.append(text)

    def change(entry):
        entry["allowed_directories"] = out
    return _edit_location(repo_path, change)
