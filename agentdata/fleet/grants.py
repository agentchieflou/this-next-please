"""A refused tool, named, and the one allow-list entry that would have let it run.

A headless turn has nobody to ask (`--no-ask-user`): a tool the allow-list does not cover is refused,
the turn goes on, and the CLI's only record is `error.code == "denied"` with the sentence "Permission
denied and could not request permission from user" (docs/fleet-spike.md). That sentence was all the
tile showed. In a terminal of their own the operator answers the same prompt with *yes* -- which is
why work like a Jira-to-Power BI UAT got done by closing the fleet and resuming the session in a
local `copilot` (operator report, 2026-10-02).

This module is the desk's half of that *yes*. `refusal()` joins a denial to the tool call it refused
and proposes the narrowest entry that would have allowed it: `write` for the CLI's file tools,
`shell(<command>)` for a shell command, `shell(git <verb>)` / `shell(python -m <module>)` where the
first word alone would allow far more. `grant()` adds that entry to one agent's
`fleet.copilot.allow_extra` (or every agent's), through the settings page's own validation; the next
turn launches with it, and the settings page lists it with the rest, revocable there.

What it never does: grant anything on the deny floor (`launch.DEFAULT_DENY` -- a deny wins over an
allow, so the grant would be a lie), or anything the operator denied themselves; there the refusal
says what to use instead. And it never makes a grant look smaller than it is: an interpreter or the
`write` tool is marked broad, with the reason.
"""
from __future__ import annotations

import re
import shlex

from .. import config as C
from . import launch as LAUNCH
from . import overrides as OV

KEY = "fleet.copilot.allow_extra"

# The CLI's own file tools, as a denial names them. `apply_patch` is measured (docs/fleet-spike.md);
# the others are the names the CLI's tools carry in its event stream and docs. All of them are
# allowed by the one permission `write`.
WRITE_TOOLS = ("apply_patch", "write", "edit", "create", "str_replace_editor", "str_replace", "insert")

# A command whose first word runs anything at all. Allowing it is allowing a shell.
INTERPRETERS = ("python", "python3", "py", "pythonw", "node", "npx", "powershell", "pwsh", "cmd",
                "bash", "sh", "wsl", "deno", "ruby", "perl")

# What the deny floor is for, and what an agent uses instead. Keyed by the floor entry's first word.
INSTEAD = {
    "pncli": "pncli is reached through `ad-pncli`: `ad-pncli help <product>` for its usage, "
             "`ad-pncli raw …` for a call (a write waits on the approval gate)",
    "git": "history is the operator's; the one push is `ad-git push`, which refuses a force and waits "
           "on the approval gate",
    "curl": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "wget": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "Invoke-RestMethod": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "Invoke-WebRequest": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "iwr": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "irm": "a system of record is reached through its `ad-*` command, never a raw HTTP call",
    "rm": "nothing is deleted from an agent's turn; the map's cleanup guide commits, branches or stashes",
    "del": "nothing is deleted from an agent's turn; the map's cleanup guide commits, branches or stashes",
    "pip": "installing is the operator's (`ad-update`, `ad-setup`)",
    "npm": "installing is the operator's (`ad-update`, `ad-setup`)",
    "ad-fleet": "the fleet is the operator's to drive",
    "ad-update": "installing is the operator's (`ad-update` in their own terminal)",
    "ad-setup": "setup is the operator's (`ad-setup` in their own terminal)",
    "python": "the fleet, setup and update module forms are the operator's",
}

_SEPARATORS = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")


class GrantError(Exception):
    def __init__(self, code: str, msg: str, hint: str = ""):
        super().__init__(msg)
        self.code, self.msg, self.hint = code, msg, hint


def _prefixes(patterns) -> list[str]:
    return [p[len("shell("):-1] for p in patterns if p.startswith("shell(") and p.endswith(")")]


def _covered(command: str, patterns) -> str:
    """The `shell(…)` entry among `patterns` whose prefix `command` starts with, or "". A plain
    prefix, because that is the CLI's own rule (docs/fleet-spike.md §3)."""
    for prefix in _prefixes(patterns):
        if command.startswith(prefix):
            return f"shell({prefix})"
    return ""


def _head(segment: str) -> list[str]:
    text = re.sub(r"^&\s*", "", segment.strip())          # PowerShell's call operator
    try:
        tokens = shlex.split(text, posix=False)
    except ValueError:
        tokens = text.split()
    return [t.strip("\"'") for t in tokens]


def shell_pattern(segment: str) -> str:
    """The narrowest `shell(…)` entry that allows this one command, or "" when none can name it."""
    tokens = _head(segment)
    if not tokens:
        return ""
    first = tokens[0]
    if first == "git" and len(tokens) > 1 and not tokens[1].startswith("-"):
        pattern = f"shell(git {tokens[1]})"
    elif first.lower() in ("python", "python3", "py") and len(tokens) > 2 and tokens[1] == "-m":
        pattern = f"shell({first} -m {tokens[2]})"
    else:
        pattern = f"shell({first})"
    return pattern if LAUNCH.SHELL_PATTERN.match(pattern) else ""


def is_broad(pattern: str) -> bool:
    if LAUNCH.is_broad(pattern):
        return True
    inner = _prefixes([pattern])
    return bool(inner) and inner[0].split(" ")[0].lower() in INTERPRETERS and " -m " not in f" {inner[0]} "


def _why_broad(pattern: str) -> str:
    if pattern == "write":
        return ("edits any file in the checkout -- and with `git commit -m` allowed, an edited "
                "`.git/hooks` file runs at the next commit, so this is as wide as a shell")
    return "runs any program or script it is handed: as wide as a shell"


def _instead(floor: str) -> str:
    inner = _prefixes([floor])
    first = inner[0].split(" ")[0] if inner else floor
    return INSTEAD.get(first, "it is on the fleet's deny floor, which no setting removes")


def _what(tool: str, arguments) -> tuple[str, str]:
    """(the command or path refused, a short sentence naming it)."""
    args = arguments if isinstance(arguments, dict) else {}
    command = args.get("command")
    if isinstance(command, str) and command.strip():
        return command.strip(), f"{tool or 'shell'}: {command.strip()[:160]}"
    path = next((args[k] for k in ("path", "file_path", "filePath", "file") if isinstance(args.get(k), str)), "")
    if not (tool or path):
        return "", ""                    # a denial whose call this fold never saw: its message says it
    return path, f"{tool or 'a tool'}{': ' + path[:160] if path else ''}"


def refusal(tool: str, arguments, message: str = "") -> dict:
    """What was refused, and what would allow it.

    `patterns` is every entry the call needs that the shipped allow-list lacks (a `cd x && python y`
    needs one per command); `floor` names a deny-floor entry it hit, in which case nothing is
    grantable and `instead` says what to use. Pure: the effective allow-list is checked again by
    `grant()`, which has the configuration.
    """
    tool = str(tool or "")
    subject, what = _what(tool, arguments)
    out = {"tool": tool, "what": what, "message": str(message or "")[:300], "patterns": [],
           "floor": "", "instead": "", "broad": False, "why_broad": "", "grantable": False}
    if tool in WRITE_TOOLS:
        out["patterns"] = ["write"]
    elif isinstance((arguments or {}).get("command") if isinstance(arguments, dict) else None, str):
        for segment in [s for s in _SEPARATORS.split(subject) if s.strip()]:
            floor = _covered(segment.strip(), LAUNCH.DEFAULT_DENY)
            if floor:
                out.update(floor=floor, instead=_instead(floor), patterns=[])
                return out
            if _covered(segment.strip(), LAUNCH.DEFAULT_ALLOW):
                continue
            pattern = shell_pattern(segment)
            if not pattern:
                out.update(patterns=[], instead="no allow-list entry can name this command; open the agent "
                                                "as a console to approve it as you go")
                return out
            if pattern not in out["patterns"]:
                out["patterns"].append(pattern)
    elif tool and LAUNCH.TOOL_NAME.match(tool):
        out["patterns"] = [tool]
    broad = [p for p in out["patterns"] if is_broad(p)]
    out.update(grantable=bool(out["patterns"]), broad=bool(broad),
               why_broad=_why_broad(broad[0]) if broad else "")
    return out


def grant(cfg: dict, repo: str, patterns, *, scope: str = "agent", known=None) -> dict:
    """Add `patterns` to the agent's own (or every agent's) extra allowed tools. Mutates `cfg`; the
    caller saves it. Refuses a pattern the deny floor or the operator's own denies would override."""
    from . import settings as SET

    patterns = [str(p or "").strip() for p in (patterns or []) if str(p or "").strip()]
    if not patterns:
        raise GrantError("no_pattern", "nothing to allow", "the refusal names the entry to allow")
    if scope not in ("agent", "fleet"):
        raise GrantError("bad_scope", f"scope {scope!r}", "agent (this one) or fleet (every agent)")
    effective = OV.for_agent(cfg, repo) if repo else cfg
    denied = LAUNCH.deny_tools(effective)
    for pattern in patterns:
        try:
            LAUNCH.check_tool_pattern(pattern)
        except LAUNCH.LaunchError as e:
            raise GrantError("bad_pattern", e.msg, e.hint) from None
        inner = _prefixes([pattern])
        floor = _covered(inner[0], denied) if inner else (pattern if pattern in denied else "")
        if floor:
            mine = floor not in LAUNCH.DEFAULT_DENY
            raise GrantError("denied_by_floor" if not mine else "denied_by_you",
                             f"{pattern} is overridden by the deny entry {floor}",
                             ("remove it from *also denied* in settings first" if mine
                              else _instead(floor)))
    if scope == "fleet":
        current = [str(v) for v in (C.get(cfg, KEY) or [])]
        value = SET.set_list(cfg, KEY, current + [p for p in patterns if p not in current])
    else:
        name = repo
        current = [str(v) for v in (OV.own(cfg, name).get(KEY) or [])]
        SET.apply_agent(cfg, name, KEY, current + [p for p in patterns if p not in current], known=known)
        value = [str(v) for v in (OV.own(cfg, name).get(KEY) or [])]
    return {"key": KEY, "scope": scope, "repo": repo if scope == "agent" else "", "allowed": patterns,
            "now": value, "broad": [p for p in patterns if is_broad(p)]}


def approval_for(pattern: str) -> dict | None:
    """The Copilot approval (`permissions-config.json`) that allows what `pattern` allows, or None.

    `write` is the `write` kind. A `shell(<command> …)` is a `commands` approval on the command, in
    the one identifier form the reference documents (`git:*`): the whole command, so it is never
    narrower than what the card offered, and the card names it before anyone presses."""
    text = str(pattern or "").strip()
    if text == "write":
        return {"kind": "write"}
    inner = _prefixes([text])
    if inner and inner[0].split(" ")[0]:
        return {"kind": "commands", "commandIdentifiers": [inner[0].split(" ")[0] + ":*"]}
    return None


def describe_approval(item: dict) -> str:
    """`commands git:*`, `write`: an approval in one short phrase."""
    ids = item.get("commandIdentifiers") or []
    return " ".join([str(item.get("kind") or "?"), *[str(i) for i in ids]])


def retry_message(patterns) -> str:
    """What the agent is told after a grant, so the turn picks up where the refusal stopped it."""
    named = ", ".join(f"`{p}`" for p in patterns)
    return (f"The operator allowed {named} for you. Retry the step that was refused, once; "
            "if it is refused again, say so and stop.")
