r"""The Downloads folder, made visible to the fleet without ever opening a file.

Downloads is the desk's shared memory. The exports the operator saves out of Jira, Confluence, a
Power BI workspace or a chat window land there -- `RDSD-22449-export.md`, `velocity (3).json`,
today's and yesterday's -- and are then carried by hand into a repository or pasted into an agent.
The skills already consume exactly those files (`ad-uat expect <file>` takes CSV/TSV/XLSX/MD/DOCX,
`ad-confluence html <file.md>`), so the missing piece was never reading them: it was **routing**.
This module is the routing, and nothing else.

**Matching is on the name.** `look()` uses `os.scandir` and `os.stat` and never opens a candidate.
That is not an optimisation, it is the safety rule of epic #122 applied to the one folder that is
outside every project: Downloads holds bank statements, a `secrets.json` somebody was mailed, an
installer, and the exports we care about, all in one listing. A watcher that read a file to decide
where it belongs would be reading all of them. `tests/test_fleet_inbox.py` records every `open()`
`look()` performs and fails if there is one, because "we only look at names" is a comment and that
is a test.

**The one write into a repository, and why it is not a bug.** `attach()` copies the file to
`<repo>/.agent/in/<KEY>/<filename>`. The fleet is otherwise forbidden to write inside a repository
-- the repository belongs to the agent, and `ad-state` is the only writer of its `state.json` -- so
the next reader who finds this write should know it is deliberate and how narrow it is:

* it happens **only on a click**; nothing here is triggered by a poll or a match,
* it only ever writes under `.agent/in/`, never elsewhere in the repository and never to
  `state.json`,
* it **copies**: the original stays in Downloads, nothing is moved, renamed or deleted, ever,
* it is logged as an `inbox.attached` event on #94's contract, so the write is in the history,
* and the `inputs` line in `state.json` is asked of `ad-state` (`_ask_ad_state`), never written
  here, which is what keeps `ad-state` the single writer of that file.

**Nothing is guessed.** A file whose name names no registered project stays in the unsorted tray
until a human says where it goes. A file that is not an offered type, or is over `SIZE_CAP`, is
listed *with its reason* rather than dropped -- a laptop where `setup.exe` silently vanished from a
listing is a laptop where the operator stops trusting the listing.

**A link is not a file.** `stat` and `copy2` both follow one, so an entry in Downloads pointing at
something outside every watched folder would show that file's size and age under the link's name and
copy that file's bytes on the click -- the row would be describing one file and attaching another.
Such an entry is listed with where it leads and has no attach button (`_leads_outside`); a link that
stays inside a watched folder is just the same file under a second name, and is offered.

Windows facts this is shaped by:

* a browser writes `<name>.crdownload` (Chrome/Edge) or `<name>.partial` (Firefox) while the
  download is in flight, so those are ignored outright rather than offered half-written;
* `os.stat` on a file another program holds raises `PermissionError`, and antivirus makes that a
  routine event on a fresh download. It is not fatal and it is not news: the file is left for the
  next tick, epic #63/#69 semantics;
* Downloads is not always `~/Downloads`. It is redirected to OneDrive or to `D:` often enough that
  the shell folder API (`SHGetKnownFolderPath`, FOLDERID_Downloads) is the only honest answer on
  Windows; every other platform gets `~/Downloads`. More than one folder may be watched.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass

from .. import proc
from .. import textio
from . import events as E
from .registry import Registry, Repo, fleet_dir

# What may be offered. Everything a skill can already consume, and nothing that is executable or
# opaque. Adding a type here is a code change with a test, never a config knob -- the same rule the
# catalogue's allow-list is under, for the same reason.
OFFER_TYPES = frozenset({"md", "json", "csv", "tsv", "xlsx", "docx", "pdf", "txt"})
SIZE_CAP = 25 * 1024 * 1024

# Jira's own spelling, searched in the name as it stands. Upper-casing the name first would turn
# `notes-v2-3.md` into the ticket key `V2-3`; a real export keeps the key as Jira wrote it.
TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


def _within(tied, key: str, tickets: dict):
    """One of several checkouts of **one** project, or `None` (#175).

    A tie between two *projects* is a question with no answer, and unsorted is the honest
    reply -- a wrong attach is a file in the wrong agent's inputs and there is no undo for the
    confusion. A tie between two working trees of one project is a different thing entirely:
    it is the same work, and it has an answer. Whichever checkout is on that ticket, and
    failing that the primary -- the one the project is named after. A worktree is not an
    ambiguity.
    """
    if len({r.project for r in tied}) != 1:
        return None
    if key:
        on_it = [r for r in tied if tickets.get(r.name) == key]
        if len(on_it) == 1:
            return on_it[0]
    primary = [r for r in tied if r.name == r.project]
    return primary[0] if len(primary) == 1 else None

# A download still in flight. Offering one produces a truncated file in a repository and a confused
# agent, and the file will be along in a second under its real name anyway.
PARTIAL_SUFFIXES = (".crdownload", ".partial", ".part", ".download", ".tmp", ".!ut")

# Named so the row can say *why*, rather than "not offered" with no follow-up.
EXECUTABLE_TYPES = frozenset({"exe", "msi", "bat", "cmd", "ps1", "psm1", "com", "scr", "dll",
                              "vbs", "js", "jar", "sh", "reg", "apk", "pkg", "dmg", "appx"})
ARCHIVE_TYPES = frozenset({"zip", "7z", "rar", "gz", "bz2", "xz", "tar", "tgz", "cab", "iso"})

ATTACHED = "inbox.attached"                    # the kind, on #94's contract
IN_DIR = ".agent/in"                           # the only path in a repository this module writes
UNSORTED_KEY = "unsorted"                      # the `<KEY>` for an attach with no ticket anywhere

# How far back a look reaches, and how many rows it will build. A Downloads folder holds five years
# of files; the ones being carried by hand are this week's, and a listing of four thousand rows is
# not a listing. Both are generous enough that nothing an operator is actually working on is missed.
LOOK_BACK_S = 14 * 86400
MAX_FILES = 200

STATE_FILE = "inbox.json"
STATE_VERSION = 1
DISMISSED_CAP = 500                            # oldest fall off; a dismissal is not an archive

_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"

# Every Windows Downloads folder has a hidden `desktop.ini`, and a browser leaves hidden bookkeeping
# beside a download. Listing them as "not offered: .ini is not an offered type" is noise on the one
# screen that has to stay readable, and a hidden file is never something a person saved on purpose.
_HIDDEN = (getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
           | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0))


class InboxError(Exception):
    """Refused, with a hint. Same shape as `RegistryError`, so the CLI prints it the same way."""

    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


@dataclass
class Offer:
    """One file in the tray. Every field came from the directory entry, not from the file.

    `offered` is whether there is an attach button; `reason` is the sentence beside the row either
    way -- why it matched the project it matched, or why it cannot be offered. It is never empty,
    because a row a human cannot act on and cannot explain is worse than no row.
    """

    path: str
    name: str
    size: int = 0
    ext: str = ""
    age_s: float = 0.0
    project: str = ""
    ticket: str = ""
    offered: bool = False
    reason: str = ""

    @property
    def id(self) -> str:
        """A short handle for `ad-fleet inbox --attach <ID>`, stable across processes.

        `hash()` would have been the obvious thing and is wrong here: it is salted per process, so
        an id printed by one `ad-fleet inbox` would not resolve in the next one -- the only two
        commands that ever use it. Derived from the path and the size, never from the age, because
        an id that changed every second could not be typed back at all.
        """
        raw = f"{textio.norm_path(self.path).lower()}|{self.size}".encode("utf-8")
        return hashlib.blake2s(raw, digest_size=3).hexdigest()

    def to_json(self) -> dict:
        return {"id": self.id, "path": self.path, "name": self.name, "size": self.size,
                "ext": self.ext, "age_s": round(self.age_s, 1), "project": self.project,
                "ticket": self.ticket, "offered": self.offered, "reason": self.reason}


# --------------------------------------------------------------------------- where Downloads is


def _windows_downloads() -> str:
    """FOLDERID_Downloads from the shell, or "".

    `~/Downloads` is a guess on Windows: the folder is routinely redirected to OneDrive or to a
    second drive, and the operator whose Downloads is `C:/Users/x/OneDrive/Downloads` would get an
    empty tray with no explanation. `USERPROFILE` is still honoured first by `default_folders`, so
    a test with a temporary home is not at the mercy of the real machine's shell.
    """
    try:
        import ctypes

        clsid = (ctypes.c_byte * 16)()
        if ctypes.windll.ole32.CLSIDFromString(ctypes.create_unicode_buffer(_FOLDERID_DOWNLOADS),
                                               ctypes.byref(clsid)) != 0:
            return ""
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(clsid), 0, None,
                                                      ctypes.byref(out)) != 0:
            return ""
        path = out.value or ""
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except Exception:  # noqa: BLE001 - a shell that will not answer is not a reason to fail a tick
        return ""


def _real(path: str) -> str:
    """`os.path.realpath`, never raising. A path the OS will not resolve is returned as it stands."""
    try:
        return os.path.realpath(path)
    except OSError:                              # a drive that went away mid-tick, a cycle, a race
        return path


def default_folders() -> list[str]:
    """The folders watched when nobody said otherwise: the user's Downloads, if it exists."""
    home = os.path.expanduser("~")
    guess = os.path.join(home, "Downloads")
    if os.path.isdir(guess):
        return [textio.norm_path(guess)]
    shell = _windows_downloads() if os.name == "nt" else ""
    return [textio.norm_path(shell)] if shell and os.path.isdir(shell) else []


# ------------------------------------------------------------------------------------ the tray


class Inbox:
    """The watcher. Holds the dismissals; holds no opinion about what is in a file.

    `state_path` is `~/.agentdata/fleet/inbox.json` -- outside every repository, like everything
    else the fleet remembers.
    """

    def __init__(self, folders: list[str] | None = None, registry: Registry | None = None,
                 state_path: str | None = None):
        raw = folders if folders is not None else default_folders()
        self.folders = [textio.norm_path(os.path.abspath(textio.from_msys(str(f)))) for f in raw]
        # The watched folders with every link on the way to them already followed, so a link *inside*
        # one can be compared against them. Downloads itself is often a redirection -- OneDrive, a
        # second drive, `/tmp` -> `/private/tmp` on a Mac -- and comparing the spelling rather than
        # the destination would call every file in it an escape.
        self._roots = [os.path.normcase(_real(f)) for f in self.folders]
        self.registry = registry if registry is not None else Registry()
        self.state_path = state_path or os.path.join(fleet_dir(), STATE_FILE)

        # Files the OS refused this tick, so a caller can say "1 file is still being written"
        # instead of leaving the operator wondering where their download went.
        self.retry: list[dict] = []

        self._tickets: dict[str, str] = {}
        self._dismissed: dict[str, dict] = {}
        self._load()

    # ---- looking ---------------------------------------------------------------------------

    def look(self, now: float | None = None) -> list[Offer]:
        """Everything worth showing, newest first. Opens nothing.

        A file the OS will not `stat` has no size and no mtime, which means it has no identity to
        offer or to dismiss, so it is left for the next tick and recorded in `retry`. That is the
        ordinary case for a download antivirus is still scanning, not an error.
        """
        moment = time.time() if now is None else float(now)
        self.retry = []
        # One read of each repository's state.json per look, not one per row: a Downloads folder
        # with two hundred files and four registered repositories would otherwise open the same
        # four files eight hundred times, on every tick of the supervisor.
        self._tickets = {r.name: (r.state().get("active_ticket") or "") for r in self.registry.sorted()}
        rows: list[tuple[float, Offer]] = []
        seen: set[str] = set()

        for folder in self.folders:
            for entry in self._entries(folder):
                path = os.path.join(folder, entry.name)
                key = textio.norm_path(path).lower()
                if key in seen:
                    continue
                seen.add(key)
                built = self._row(entry, path, moment)
                if built:
                    rows.append(built)

        rows.sort(key=lambda r: (-r[0], r[1].name.lower()))
        return [offer for _mtime, offer in rows[:MAX_FILES]]

    def _entries(self, folder: str) -> list:
        try:
            with os.scandir(textio.longpath(folder)) as it:
                return list(it)
        except OSError as e:
            self.retry.append({"path": textio.norm_path(folder), "name": os.path.basename(folder),
                               "reason": f"{type(e).__name__}: {e.strerror or e}"})
            return []

    def _row(self, entry, path: str, now: float) -> tuple[float, Offer] | None:
        """One directory entry to one row, or None when it is not a row at all."""
        name = entry.name
        if name.startswith(".") or name.lower().endswith(PARTIAL_SUFFIXES):
            return None
        try:
            leads = self._leads_outside(path, entry.is_symlink())
            if entry.is_dir():                   # folders are ignored; a `.pbip` tree is not a file
                return None
            # `follow_symlinks=False` for a link that leads out: the size and the age on the row then
            # describe the entry in Downloads, not the file it points at somewhere else on the disk.
            st = entry.stat(follow_symlinks=not leads)
        except OSError as e:
            self.retry.append({"path": textio.norm_path(path), "name": name,
                               "reason": f"{type(e).__name__}: {e.strerror or e}"})
            return None

        if getattr(st, "st_file_attributes", 0) & _HIDDEN:
            return None                          # `desktop.ini` and the browser's own bookkeeping
        age = max(0.0, now - st.st_mtime)
        if age > LOOK_BACK_S:
            return None
        if self._is_dismissed(name, st.st_mtime):
            return None

        offer = Offer(path=textio.norm_path(path), name=name, size=int(st.st_size),
                      ext=os.path.splitext(name)[1].lstrip(".").lower(), age_s=age)
        refusal = f"not offered: {leads}" if leads else self._refuse(offer)
        if refusal:
            offer.offered, offer.reason = False, refusal
            return st.st_mtime, offer
        offer.offered = True
        offer.project, offer.ticket, offer.reason = self._match(name)
        return st.st_mtime, offer

    def _leads_outside(self, path: str, is_link: bool) -> str:
        """Why a link here cannot be offered, or "" -- for anything that is not a link, always "".

        `os.stat` and `shutil.copy2` both follow a link, and that is the whole problem. With
        `Downloads/RDSD-1-report.md -> C:/Users/x/tax/2025.md` the row's size and age describe the
        *target* while the operator reads the name of the link, so the row lies to the person
        clicking it, and the click then copies a file from outside every watched folder into a
        repository. One click, and the thing that arrived in `.agent/in/` was never in Downloads.

        A link that stays inside a watched folder is the harmless case -- the same file under a
        second name, with the size and age the row already shows -- and is offered as usual.

        The refusal is a row with a reason, in the style of `not offered: executable`, never a
        silent drop: a file that disappears from the listing is one the operator goes hunting for.
        """
        if not is_link:
            return ""
        target = _real(path)
        real = os.path.normcase(target)
        for root in self._roots:
            trimmed = root.rstrip("\\/")
            if real == trimmed or real.startswith(trimmed + os.sep):
                return ""
        return f"a link that leads out of the watched folder, to {textio.norm_path(target)}"

    def _refuse(self, offer: Offer) -> str:
        """Why this file has no attach button, or "". Judged on the name and the size alone."""
        if offer.ext in EXECUTABLE_TYPES:
            return "not offered: executable"
        if offer.ext in ARCHIVE_TYPES:
            return "not offered: archive; unpack it first and attach what you need"
        if offer.ext not in OFFER_TYPES:
            spelled = ".{}".format(offer.ext) if offer.ext else "no extension"
            return (f"not offered: {spelled} is not an offered type "
                    f"({', '.join('.' + t for t in sorted(OFFER_TYPES))})")
        if offer.size > SIZE_CAP:
            return (f"not offered: {offer.size / 1048576:.1f} MB is over the "
                    f"{SIZE_CAP // 1048576} MB cap")
        return ""

    # ---- matching, on the name -----------------------------------------------------------------

    def _match(self, name: str) -> tuple[str, str, str]:
        """(project, ticket, why). The resolution order the epic fixed, and no fourth guess.

        A ticket key is the strong signal, because Jira put it in the filename itself: it is
        resolved first against the project actually working that ticket, then against the project
        that owns the key's prefix. Only then is the project's own name looked for. Anything left
        is unsorted -- and two projects that match equally well are unsorted too, because a wrong
        attach is a file in the wrong agent's inputs and there is no undo for the confusion.
        """
        repos = self.registry.sorted()
        tickets = self._tickets or {r.name: (r.state().get("active_ticket") or "") for r in repos}
        keys = TICKET_RE.findall(name)
        # A key nobody is working and nobody owns still travels with the row: it is what the file
        # is *about*, so the unsorted tray can say so and an attach filed under `.agent/in/<KEY>/`
        # gets the right folder even when the human, not the match, chose the repository.
        seen_key = keys[0] if keys else ""
        for key in keys:
            on_it = [r for r in repos if tickets.get(r.name) == key]
            if on_it:
                # Two working trees of one project can both be on this ticket. That is not an
                # ambiguity about which project, so it is not a coin toss either (#175).
                chosen = (_within(on_it, key, tickets) or on_it[0]) if len(on_it) > 1 else on_it[0]
                return chosen.name, key, f"{key} is {chosen.name}'s active ticket"
            prefix = key.split("-", 1)[0]
            owners = [r for r in repos if (r.jira_project or "").upper() == prefix]
            if len(owners) == 1:
                return owners[0].name, key, f"{prefix} is {owners[0].name}'s jira_project"
            if len(owners) > 1:
                pick = _within(owners, key, tickets)
                if pick is not None:
                    return pick.name, key, (f"{prefix} is {pick.project}'s jira_project, and "
                                            f"{pick.name} is the checkout of it that answers")
                listed = " and ".join(r.name for r in owners)
                return "", key, f"unsorted: {listed} both use the jira_project {prefix}"

        lowered = name.lower()
        named = [r for r in repos if r.name and len(r.name) >= 3 and r.name.lower() in lowered]
        if named:
            # The longest name wins, so `velocity-reports-export.json` goes to `velocity-reports`
            # and not to `velocity`. Only a genuine tie -- two different projects both named in the
            # file -- is ambiguous, and an ambiguity is unsorted rather than a coin toss.
            longest = max(len(r.name) for r in named)
            best = [r for r in named if len(r.name) == longest]
            if len(best) == 1:
                return best[0].name, seen_key, f"the name contains the project name {best[0].name}"
            pick = _within(best, seen_key, tickets)
            if pick is not None:
                return pick.name, seen_key, (f"the name contains {pick.project}, and {pick.name} "
                                             f"is the checkout of it that answers")
            listed = " and ".join(r.name for r in best)
            return "", seen_key, f"unsorted: {listed} both match the name"
        return "", seen_key, "unsorted: nothing in the name names a registered project"

    # ---- the one write ---------------------------------------------------------------------

    def attach(self, offer: Offer, repo) -> dict:
        """Copy the file into `<repo>/.agent/in/<KEY>/`, and return the `inbox.attached` event.

        The copy is the whole action. The original is untouched, `state.json` is not written here
        -- `_ask_ad_state` asks for the `inputs` line, so `ad-state` stays its only writer -- and
        the same file attached twice is a no-op rather than a second copy, because an operator who
        clicks twice meant it once.
        """
        target = self._repo(repo)
        if not offer.offered:
            # `reason` already begins "not offered: "; saying it twice made the refusal read as
            # though something had gone wrong on top of the refusal.
            raise InboxError(f"{offer.name} is {offer.reason}",
                             "attach one of the offered rows, or copy this one in yourself")
        # Asked again here, at the only moment it can do harm: the row was built by an earlier look,
        # and a link put in its place since then would be followed by `copy2` all the same.
        leads = self._leads_outside(offer.path, os.path.islink(textio.longpath(offer.path)))
        if leads:
            raise InboxError(f"{offer.name} is not offered: {leads}",
                             "attach the file it points at from a folder that is watched, or copy "
                             "it in yourself; nothing is copied out of a folder nobody named")

        # The key in the name wins over the repository's current ticket: the file says what it is
        # about, and a human attaching yesterday's export to a repository that has moved on should
        # get yesterday's folder rather than today's.
        ticket = offer.ticket or (target.state().get("active_ticket") or "")
        key = textio.safe_name(ticket or UNSORTED_KEY)
        folder = os.path.join(target.path, *IN_DIR.split("/"), key)
        dest = os.path.join(folder, textio.safe_name(offer.name))
        root = textio.norm_path(os.path.join(target.path, *IN_DIR.split("/")))
        if not textio.norm_path(dest).startswith(root + "/"):
            raise InboxError(f"refusing to write {offer.name} outside {IN_DIR}",
                             "rename the file to something without path separators and retry")

        data = {"file": textio.norm_path(dest), "name": offer.name,
                "dir": textio.norm_path(os.path.join(IN_DIR, key)),
                "source": offer.path, "size": offer.size, "project": target.name}

        if self._already_there(dest, offer):
            data.update(attached=False, recorded=False,
                        why=f"already attached: {offer.name} is there with the same size and time")
            return E.event(target.name, ATTACHED, data, ticket=ticket)

        try:
            os.makedirs(textio.longpath(folder), exist_ok=True)
            shutil.copy2(textio.longpath(offer.path), textio.longpath(dest))
        except OSError as e:
            raise InboxError(f"could not copy {offer.name} into {IN_DIR}/{key}: {e.strerror or e}",
                             "close the program that has the file open, or check the disk, and "
                             "click attach again; nothing was changed") from None

        why = self._ask_ad_state(target, dest, key)
        data.update(attached=True, recorded=not why, why=why)
        event = E.event(target.name, ATTACHED, data, ticket=ticket)
        try:
            E.append(target.name, [event])
        except OSError:
            pass          # the stream is held by the agent; the copy stands, the row will show it
        return event

    def _repo(self, repo) -> Repo:
        """A `Repo`, from a `Repo` or from the name every other command addresses it by."""
        if isinstance(repo, Repo):
            return repo
        return self.registry.get(str(repo))

    @staticmethod
    def _already_there(dest: str, offer: Offer) -> bool:
        """Whether this exact download is already attached: same name, same size, same second.

        Both mtimes are read now rather than reconstructed from `offer.age_s`, which is only as
        fresh as the look that built it -- a tray left open for ten minutes would have compared a
        ten-minute-old reckoning against the real file and copied it a second time. `copy2`
        preserves the mtime, which is what makes the comparison possible at all.
        """
        try:
            there = os.stat(textio.longpath(dest))
            source = os.stat(textio.longpath(offer.path))
        except OSError:
            return False
        return (int(there.st_size) == int(source.st_size)
                and int(there.st_mtime) == int(source.st_mtime))

    @staticmethod
    def _ask_ad_state(repo: Repo, dest: str, key: str) -> str:
        """Ask `ad-state` to record the input. Returns "" on success, else why it did not happen.

        The fleet must never write `state.json`, so this is a request, not a write: `ad-state set
        --input <path>` in the repository's own directory. A failure is reported and never raised
        -- the file is in `.agent/in/<KEY>/` where the skills look for it either way, and losing
        the attach because a console script was not on PATH would be the wrong trade.
        """
        rel = textio.norm_path(os.path.join(IN_DIR, key, os.path.basename(dest)))
        try:
            code, out, err, _elapsed = proc.run(["ad-state", "set", "--input", rel],
                                                cwd=repo.path, timeout=60)
        except proc.ProcError as e:
            return f"ad-state could not be run ({e.code}); the file is in {IN_DIR}/{key}/ regardless"
        except OSError as e:
            return f"ad-state could not be run ({e}); the file is in {IN_DIR}/{key}/ regardless"
        if code == 0:
            return ""
        tail = (err or out or "").strip().splitlines()
        return (f"ad-state exited {code}: {tail[-1][:160] if tail else 'no output'}; "
                f"the file is in {IN_DIR}/{key}/ regardless")

    # ---- dismissals --------------------------------------------------------------------------

    def dismiss(self, offer: Offer) -> None:
        """Stop offering this file. Remembered by name and mtime, so a re-download is offered again.

        The identity is deliberately *not* the path: Downloads gets tidied, and a file dismissed in
        the morning should not come back because it was moved to a second watched folder. A newer
        file with the same name is a different file and is offered -- that is the operator saving
        `velocity (3).json` again after the numbers changed, which is the case that matters.
        """
        mtime = self._mtime_of(offer)
        self._dismissed[self._key(offer.name, mtime)] = {
            "name": offer.name, "mtime": int(mtime), "at": E.stamp()}
        if len(self._dismissed) > DISMISSED_CAP:
            for stale in sorted(self._dismissed, key=lambda k: self._dismissed[k]["at"])[
                    :len(self._dismissed) - DISMISSED_CAP]:
                del self._dismissed[stale]
        self._save()

    def dismissed(self) -> list[dict]:
        """What is being hidden, so it can be shown and undone rather than being a black hole."""
        return sorted(self._dismissed.values(), key=lambda d: (d["name"].lower(), d["mtime"]))

    def _mtime_of(self, offer: Offer) -> float:
        # The same follow-or-not rule `look` used to build the row, so the dismissal is keyed to the
        # time the operator was shown. Keyed to the target's mtime instead, a dismissed link-out row
        # would come straight back on the next tick.
        follow = not self._leads_outside(offer.path, os.path.islink(textio.longpath(offer.path)))
        try:
            return os.stat(textio.longpath(offer.path), follow_symlinks=follow).st_mtime
        except OSError:
            return time.time() - offer.age_s          # already gone: the row's own reckoning

    @staticmethod
    def _key(name: str, mtime: float) -> str:
        return f"{name.lower()}|{int(mtime)}"

    def _is_dismissed(self, name: str, mtime: float) -> bool:
        return self._key(name, mtime) in self._dismissed

    def _load(self) -> None:
        try:
            saved = json.loads(textio.read_text(self.state_path))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict) or saved.get("version") != STATE_VERSION:
            return
        for row in saved.get("dismissed") or []:
            if not isinstance(row, dict) or not row.get("name"):
                continue
            name, mtime = str(row["name"]), int(row.get("mtime") or 0)
            self._dismissed[self._key(name, mtime)] = {"name": name, "mtime": mtime,
                                                       "at": str(row.get("at") or "")}

    def _save(self) -> None:
        payload = {"version": STATE_VERSION, "dismissed": self.dismissed()}
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            textio.write_text(self.state_path, json.dumps(payload, indent=2) + "\n")
        except OSError:
            pass          # a tray that cannot remember a dismissal still lists the folder
