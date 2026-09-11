"""What the operator hands an agent, written into `.agent/in/<KEY>/`. (#162)

The fleet writes under `~/.agentdata/fleet/` and nowhere else, with exactly one exception: this
directory. #132 opened it for an attached Downloads file; #164 puts the operator's brief in it and
#166 the scope. They are one exception rather than three because they inherit one set of rules,
which this module owns and every writer here obeys:

1. **Only on a click or a start.** Nothing here runs on a timer or a poll.
2. **Only under `<repo>/.agent/in/<KEY>/`.** The destination is recomputed from the repository root
   and checked, never taken from a caller.
3. **A copy, never a move.** Nothing is taken away from where the operator left it.
4. **Always an event.** A write the operator did not type themselves has to be as visible as one
   they did, so it lands in `events.norm.jsonl` like everything else.
5. **`ad-state` writes `state.json`, not us.** The `inputs` line is *asked for*, exactly as
   `Inbox._ask_ad_state` asks for it, and a failure to ask is reported rather than raised: the file
   is in the directory the skills read either way.
"""
from __future__ import annotations
import os
import time
from typing import Any

from .. import proc
from .. import textio
from . import events as E

IN_DIR = ".agent/in"                           # the one path in a repository this module writes
UNSORTED_KEY = "unsorted"                      # the `<KEY>` for a handoff with no ticket anywhere
BRIEF = "brief.md"
SCOPE = "scope.toon"
BRIEF_KIND = "handoff.brief"
SCOPE_KIND = "scope.added"
# A brief is the operator's own words at dispatch. Longer than this is not a brief, it is a
# document, and a document belongs in the ticket or in an attached file where it can be revised.
BRIEF_CAP = 20_000


class HandoffError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


def key_for(ticket: str) -> str:
    """The `<KEY>` folder a ticket gets, or `unsorted` when there is no ticket."""
    return textio.safe_name((ticket or "").strip() or UNSORTED_KEY)


def in_dir(repo_path: str, ticket: str) -> str:
    """`<repo>/.agent/in/<KEY>/`, absolute."""
    return os.path.join(repo_path, *IN_DIR.split("/"), key_for(ticket))


def rel_in_dir(ticket: str) -> str:
    """The same directory as the repository-relative path `state.json` records."""
    return textio.norm_path(os.path.join(IN_DIR, key_for(ticket)))


def _inside(repo_path: str, dest: str) -> None:
    """Rule 2, enforced rather than intended."""
    root = textio.norm_path(os.path.join(repo_path, *IN_DIR.split("/")))
    if not textio.norm_path(dest).startswith(root + "/"):
        raise HandoffError(f"refusing to write outside {IN_DIR}",
                           "the destination is computed from the repository root; this one escaped it",
                           code="handoff_outside")


def ask_ad_state(repo_path: str, rel: str) -> str:
    """Ask `ad-state` to record an input. Returns "" on success, else why it did not happen.

    A request, not a write. `ad-state` is the only writer of `state.json` and stays so; a failure
    here costs the `inputs` line and nothing else, because the file is in the directory the skills
    read regardless.
    """
    try:
        code, out, err, _elapsed = proc.run(["ad-state", "set", "--input", rel],
                                            cwd=repo_path, timeout=60)
    except proc.ProcError as e:
        return f"ad-state could not be run ({e.code}); the file is in {rel} regardless"
    except OSError as e:
        return f"ad-state could not be run ({e}); the file is in {rel} regardless"
    if code == 0:
        return ""
    tail = (err or out or "").strip().splitlines()
    return (f"ad-state exited {code}: {tail[-1][:160] if tail else 'no output'}; "
            f"the file is in {rel} regardless")


def read_brief_file(path: str) -> str:
    """`--brief-file`, read through `textio` like every other external file.

    A brief written by Notepad or an older PowerShell arrives with a BOM or in UTF-16; reading it
    any other way would put those bytes in front of the operator's first sentence.
    """
    try:
        return textio.read_text(path)
    except OSError as e:
        raise HandoffError(f"could not read the brief from {path}: {e.strerror or e}",
                           "check the path, or pass the text with --brief instead",
                           code="brief_unreadable") from None


def write_brief(repo_name: str, repo_path: str, ticket: str, text: str, *,
                by: str = "operator", now: float | None = None) -> dict:
    """Write `.agent/in/<KEY>/brief.md` and return the `handoff.brief` event.

    Raises `HandoffError` when it cannot be written, and the caller refuses the start on that:
    launching an agent that was promised a brief it will not find is worse than not launching, and
    the operator has just typed the one thing nothing else in the system knows.
    """
    body = (text or "").strip()
    if not body:
        raise HandoffError("the brief is empty",
                           "type what the agent should know, or start without --brief",
                           code="brief_empty")
    if len(body) > BRIEF_CAP:
        raise HandoffError(f"the brief is {len(body)} characters; the cap is {BRIEF_CAP}",
                           "attach it as a file instead -- a brief is the operator's own words at "
                           "dispatch, not a document",
                           code="brief_too_long")

    folder = in_dir(repo_path, ticket)
    dest = os.path.join(folder, BRIEF)
    _inside(repo_path, dest)
    key = key_for(ticket)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now if now is not None else time.time()))

    # Front matter so the file says what it is without the reader having to be told, and so a
    # second brief on the same ticket is visibly a second brief rather than an edit of the first.
    head = (f"---\nticket: {ticket or ''}\nby: {by}\nat: {stamp}\n---\n\n")
    previous = ""
    try:
        if os.path.isfile(textio.longpath(dest)):
            previous = textio.read_text(dest).rstrip() + "\n\n"
    except OSError:
        previous = ""
    try:
        os.makedirs(textio.longpath(folder), exist_ok=True)
        textio.write_text(dest, previous + head + body + "\n")
    except OSError as e:
        raise HandoffError(f"could not write the brief into {IN_DIR}/{key}: {e.strerror or e}",
                           "check the disk and the repository's permissions; nothing was started",
                           code="brief_unwritable") from None

    rel = textio.norm_path(os.path.join(IN_DIR, key, BRIEF))
    why = ask_ad_state(repo_path, rel)
    data: dict[str, Any] = {"path": rel, "file": textio.norm_path(dest),
                            "words": len([w for w in body.split() if w]),
                            "by": by, "recorded": not why, "why": why}
    event = E.event(repo_name, BRIEF_KIND, data, ticket=ticket or "")
    try:
        E.append(repo_name, [event])
    except OSError:
        pass          # the stream is held by the agent; the brief stands, the row will show it
    return event


def offered(repo_path: str, ticket: str) -> dict:
    """What is already waiting for an agent in this ticket's directory.

    Read-only, and cheap enough to ask on every dispatch card: `{files, brief, scope}`.
    """
    folder = in_dir(repo_path, ticket)
    try:
        names = sorted(n for n in os.listdir(textio.longpath(folder))
                       if os.path.isfile(os.path.join(folder, n)))
    except OSError:
        names = []
    return {"files": names, "brief": BRIEF in names, "scope": SCOPE in names,
            "dir": rel_in_dir(ticket)}


def prompt_line(repo_path: str, ticket: str) -> str:
    """The `{handoff}` sentence, or "" when there is nothing to say.

    Deliberately a count and a directory, never the content: the prompt stays one line, and a fleet
    that pasted the brief into it would hand the agent a copy to trust instead of a file to read.
    """
    here = offered(repo_path, ticket)
    if not here["files"]:
        return ""
    bits = []
    if here["brief"]:
        bits.append("a brief")
    if here["scope"]:
        bits.append("a scope")
    others = len(here["files"]) - len([b for b in (here["brief"], here["scope"]) if b])
    if others > 0:
        bits.append(f"{others} file{'s' if others != 1 else ''}")
    what = " and ".join(", ".join(bits).rsplit(", ", 1)) if len(bits) > 1 else (bits[0] if bits else "")
    it = "it" if len(here["files"]) == 1 else "them"
    return f" The operator left {what} under {here['dir']}/; read {it} before the ticket."
