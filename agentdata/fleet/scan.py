"""Proposing the repositories under one parent folder, without ever opening one.

The operator's critical projects all sit under a single folder -- `C:/Users/<user>/PycharmProjects`
on the laptop -- and registering them one `ad-fleet repo add <path>` at a time is the "spend all
night on setup" this epic exists to remove. The obvious fix, pointing something at the parent
folder, is the one thing #91 refused: directory-root discovery is how a stray checkout gets handed
a ticket, and AGENTS.md rule 3 says no agent may read a second project's `.agent/`.

So this module **only proposes**. It hands the *human* a list; it never hands an agent a folder,
and it never writes -- not the registry, not a cache, not a marker of its own. The confirmation step
calls `registry.Registry.add` unchanged, once per candidate the human said yes to, so the registry
format, its refusals and the doctor rows stay exactly as #93 left them.

What it may open is a closed list, `READS`: a candidate's `AGENTS.md` (through
`config.project_facts`, which already drops placeholders and never stores a credential) and its
`.git/HEAD`. Everything else -- `.agent/state.json`, `pyproject.toml`, a `*.pbip`, and above all a
planted `.env`, `secrets.json` or `localSettings.json` -- is decided by *name only*, with
`os.scandir` and `os.stat`. `tests/test_fleet_scan.py` records every `open()` the scan performs and
fails if a sixth path appears, because "we only read the markers" is a promise that decays the first
time someone adds a convenience.

Windows facts, all of them learned on the laptop:

* a **junction** (`Documents/My Music`) and a **OneDrive placeholder** are reparse points, and
  walking through one either loops or silently doubles a repository. A reparse point is reported
  with `reparse: true` and not descended into, so the human decides rather than the walk;
* a **mapped drive** counts as reparse too: it can be disconnected at the moment `ad-fleet` next
  runs, and a repository registered from `Z:` that is not there any more is the drift case below;
* `Application Data` and friends raise `PermissionError` from `os.scandir`. One refused subtree
  skips that subtree with its reason and never fails the scan;
* the folder argument may arrive MSYS-converted from Git Bash (`/c/Users/...`), so it goes through
  `textio.from_msys`, and every path is long-path aware through `textio`.
"""
from __future__ import annotations
import os
import re
import stat
import time
from dataclasses import dataclass

from .. import config as C
from .. import textio
from .registry import Registry

# Directory names never worth walking into. A deny-list is only safe here because it is a *speed*
# measure on top of the marker rule, not the safety rule: nothing inside these is read either way.
# `node_modules` and `site-packages` are the ones that turn a two-second scan into a two-minute one.
DENY_DIRS = frozenset({"node_modules", ".venv", "venv", "site-packages", "Downloads", "Temp",
                       "__pycache__"})
_DENY_LOWER = frozenset(d.lower() for d in DENY_DIRS)

# A directory is a candidate when it has a `.git` and at least one of these. `.git` alone is not
# enough: a bare clone of somebody's dotfiles is not a project an agent could be given work in.
MARKERS = ("AGENTS.md", ".agent", "pyproject.toml", "*.pbip")

# The complete set of files this module may open, relative to a candidate. Asserted by the suite.
READS = ("AGENTS.md", ".git/HEAD")

# `ref: refs/heads/<branch>` is the attached case; a bare 40-hex line is a detached HEAD.
_HEAD_REF = re.compile(r"^ref:\s*refs/heads/(.+?)\s*$")
_HEAD_SHA = re.compile(r"^([0-9a-f]{7,40})\s*$", re.I)

DAY_S = 86400
DRIVE_REMOTE = 4          # winbase.h, GetDriveTypeW


class ScanError(Exception):
    """Refused, with a hint. Same shape as `RegistryError`, so the CLI prints it the same way."""

    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


@dataclass
class Candidate:
    """One row of the proposal. Nothing here came from inside a file except `branch` and the facts.

    `already_registered` and `why` exist so the human can answer y/n without opening a tab: `why`
    is the one line that says either which markers matched or what would stop `repo add` from
    accepting this folder.
    """

    path: str
    name: str
    branch: str = ""
    has_agents_md: bool = False
    has_state: bool = False
    jira_project: str = ""
    pbip: str = ""
    last_commit_age_days: int | None = None
    already_registered: bool = False
    reparse: bool = False
    why: str = ""

    @property
    def ready(self) -> bool:
        """Whether `Registry.add` would accept it. It wants an AGENTS.md *and* a `.agent/state.json`."""
        return self.has_agents_md and self.has_state

    def to_json(self) -> dict:
        return {"path": self.path, "name": self.name, "branch": self.branch,
                "has_agents_md": self.has_agents_md, "has_state": self.has_state,
                "jira_project": self.jira_project, "pbip": self.pbip,
                "last_commit_age_days": self.last_commit_age_days,
                "already_registered": self.already_registered, "reparse": self.reparse,
                "why": self.why}


# ------------------------------------------------------------------------------- Windows paths


def _on_remote_drive(path: str) -> bool:
    """A UNC share or a mapped drive letter. Both can be gone by the next `ad-fleet status`."""
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    if os.name != "nt":
        return False
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_REMOTE
    except Exception:  # noqa: BLE001 - a drive we cannot classify is treated as ordinary
        return False


def _is_reparse(path: str) -> bool:
    """A symlink, a junction, or a OneDrive placeholder -- anything the walk must not follow."""
    try:
        st = os.lstat(textio.longpath(path))
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return True
    return _on_remote_drive(path)


# ------------------------------------------------------------------------------- reading names


def _entries(path: str, on_skip) -> list | None:
    """One `os.scandir` per directory, or None when the OS refuses it.

    None is not an error: `C:/Users/<user>/Application Data` is a junction the account cannot
    traverse, and it sits directly under the folder the operator will point this at.
    """
    try:
        with os.scandir(textio.longpath(path)) as it:
            return list(it)
    except OSError as e:
        if on_skip:
            on_skip(textio.norm_path(path), f"{type(e).__name__}: {e.strerror or e}")
        return None


def _is_dir(entry) -> bool:
    try:
        return entry.is_dir()
    except OSError:                              # a dangling symlink, a disconnected share
        return False


def _markers(path: str, entries: list) -> list[str]:
    """Which of `MARKERS` this directory has, or [] when it is not a candidate at all.

    Matched case-insensitively because the laptop is the target: `agents.md` and `AGENTS.md` are
    the same file there, and a scan that missed one of them would look like the folder is empty.
    """
    by_name = {e.name.lower(): e for e in entries}
    if ".git" not in by_name:
        return []
    found = [".git"]
    if "agents.md" in by_name:
        found.append("AGENTS.md")
    if ".agent" in by_name and _is_dir(by_name[".agent"]):
        found.append(".agent")
    if "pyproject.toml" in by_name:
        found.append("pyproject.toml")
    if any(n.endswith(".pbip") for n in by_name):
        found.append("*.pbip")
    return found if len(found) > 1 else []


def _pbip_names(entries: list) -> str:
    """The `*.pbip` stems, from the directory listing. No `.pbip` file is opened."""
    return ",".join(sorted(e.name[:-5] for e in entries if e.name.lower().endswith(".pbip")))


# --------------------------------------------------------------------------------- git, by name


def _branch(git_dir: str) -> str:
    """The branch from `.git/HEAD`, or "" -- including when `.git` is a worktree/submodule file.

    Following a `gitdir:` pointer would be reading a second repository's internals from inside this
    one, which is the shape of the rule this whole module is built around. Worktrees are out of
    scope (#129) and the empty branch says so honestly.
    """
    head = os.path.join(git_dir, "HEAD")
    if not os.path.isfile(head):
        return ""
    try:
        first = textio.read_text(head).splitlines()[0].strip()
    except (OSError, IndexError):
        return ""
    m = _HEAD_REF.match(first)
    if m:
        return m.group(1)
    return first[:7].lower() if _HEAD_SHA.match(first) else ""


def _last_commit_age_days(git_dir: str, branch: str) -> int | None:
    """Whole days since the ref last moved, from `os.stat` -- never from the object store.

    This is an mtime, not a commit timestamp, and that is the deliberate trade: reading the real
    author date means opening `.git/objects`, which is outside `READS`. A fresh clone therefore
    reads as zero days old, which is the right answer for "is anyone working here" anyway.
    """
    newest = 0.0
    candidates = [os.path.join(git_dir, "logs", "HEAD"),
                  os.path.join(git_dir, "packed-refs"),
                  os.path.join(git_dir, "HEAD")]
    if branch:
        candidates.insert(0, os.path.join(git_dir, "refs", "heads", *branch.split("/")))
    for p in candidates:
        try:
            newest = max(newest, os.stat(textio.longpath(p)).st_mtime)
        except OSError:
            continue
    if not newest:
        return None
    return max(0, int((time.time() - newest) // DAY_S))


# ------------------------------------------------------------------------------------ the scan


def _facts(path: str) -> dict:
    """`- key: value` from AGENTS.md. The only file content the proposal carries."""
    agents_md = os.path.join(path, "AGENTS.md")
    try:
        return C.project_facts(agents_md)
    except OSError:
        return {}


def _unique(base: str, taken: set[str], parent: str) -> str:
    """A proposed name no `Registry.add` will refuse.

    Two `PycharmProjects/*/reporting` folders both propose `reporting`, and the second confirmation
    would die on "a different repo is already registered as 'reporting'" -- halfway through a
    `--yes` run, with the first half already written. Cheaper to never propose the collision.
    """
    if base not in taken:
        return base
    if parent:
        joined = f"{parent}-{base}"
        if joined not in taken:
            return joined
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def scan(folder, depth: int = 2, registry: Registry | None = None, on_skip=None) -> list[Candidate]:
    """Propose every project under `folder`, `depth` levels down. Writes nothing.

    `depth` counts levels *below* `folder`; the folder itself is always considered, so pointing at
    a single repository proposes that repository. `on_skip(path, reason)`, when given, is called for
    every subtree the deny-list or the OS took away, so the CLI can print "3 skipped" rather than
    leaving the operator wondering where a repo went.
    """
    raw = textio.from_msys(str(folder or "."))
    root = os.path.abspath(C.expand(raw))
    if not os.path.isdir(root):
        raise ScanError(f"no such folder: {textio.norm_path(root)}",
                        "pass the parent folder your projects live under, e.g. "
                        "`ad-fleet repo add --scan ~/PycharmProjects`")
    try:
        depth = max(0, int(depth))
    except (TypeError, ValueError):
        raise ScanError(f"--depth must be a whole number, not {depth!r}",
                        "1 is the projects directly under the folder, 2 is the default") from None

    reg = registry if registry is not None else Registry()
    registered = {r.path: r.name for r in reg.sorted()}

    hits: list[tuple[str, bool, list[str], list]] = []
    seen: set[str] = set()
    queue = [(root, 0, _is_reparse(root))]
    while queue:
        path, level, in_reparse = queue.pop(0)
        try:
            real = os.path.realpath(path)
        except OSError:
            continue
        if real in seen:                      # a junction pointing back up, or two routes to one dir
            continue
        seen.add(real)

        entries = _entries(path, on_skip)
        if entries is None:
            continue
        markers = _markers(path, entries)
        if markers:
            hits.append((path, in_reparse, markers, entries))
        if level >= depth:
            continue
        for entry in entries:
            name = entry.name
            if name.lower() in _DENY_LOWER:
                if on_skip:
                    on_skip(textio.norm_path(os.path.join(path, name)), "deny-list")
                continue
            if name.startswith(".") or not _is_dir(entry):
                continue
            child = os.path.join(path, name)
            if _is_reparse(child):
                # judged on its own merits, never walked through: level = depth stops the descent
                queue.append((child, depth, True))
            else:
                queue.append((child, level + 1, in_reparse))

    hits.sort(key=lambda h: textio.norm_path(h[0]).lower())
    taken = set(registered.values())
    out: list[Candidate] = []
    for path, reparse, markers, entries in hits:
        norm = textio.norm_path(path)
        registered_as = registered.get(norm, "")
        facts = _facts(path) if "AGENTS.md" in markers else {}
        git_dir = os.path.join(path, ".git")
        branch = _branch(git_dir) if os.path.isdir(git_dir) else ""
        parent = os.path.basename(os.path.dirname(path.rstrip("/\\")))
        base = os.path.basename(path.rstrip("/\\")) or norm
        name = registered_as or _unique(base, taken, parent)
        taken.add(name)

        c = Candidate(
            path=norm,
            name=name,
            branch=branch,
            has_agents_md="AGENTS.md" in markers,
            has_state=os.path.isfile(os.path.join(path, ".agent", "state.json")),
            jira_project=facts.get("jira_project", ""),
            pbip=_pbip_names(entries),
            last_commit_age_days=_last_commit_age_days(git_dir, branch) if os.path.isdir(git_dir) else None,
            already_registered=bool(registered_as),
            reparse=reparse,
        )
        c.why = _why(c, markers, registered_as)
        out.append(c)
    return out


def _why(c: Candidate, markers: list[str], registered_as: str) -> str:
    """The one line the human decides on. Flags win over markers; markers are the fallback."""
    flags: list[str] = []
    if registered_as:
        flags.append(f"already registered as {registered_as}")
    if c.reparse:
        flags.append("mapped, junction or synced path; not followed")
    if not c.ready:
        missing = "AGENTS.md" if not c.has_agents_md else ".agent/state.json"
        flags.append(f"no {missing}; run `ad-setup --project .` there first")
    return "; ".join(flags) if flags else " + ".join(markers)


# ----------------------------------------------------------------------------------- the drift


def drift(registry: Registry | None = None) -> list[dict]:
    """Registered paths that are gone or no longer a project. **Never removes one.**

    A repository moves because the operator renamed a folder or a mapped drive was not connected
    this morning, and both look identical from here. Removing the entry would throw away the name
    every other command addresses it by -- and on a disconnected `Z:` it would throw it away for a
    repository that is perfectly fine. So this reports and offers the command; the human runs it.
    """
    reg = registry if registry is not None else Registry()
    rows: list[dict] = []
    for repo in reg.sorted():
        path = repo.path
        hint = f"`ad-fleet repo remove {repo.name}` if it is really gone; nothing is removed for you"
        if not os.path.isdir(textio.longpath(path)):
            rows.append({"name": repo.name, "path": path, "reason": "missing",
                         "detail": "the folder is gone, was renamed, or its drive is not connected",
                         "hint": hint})
            continue
        if not os.path.isfile(os.path.join(path, "AGENTS.md")):
            rows.append({"name": repo.name, "path": path, "reason": "not_a_project",
                         "detail": "the folder is there but has no AGENTS.md any more",
                         "hint": hint})
            continue
        if not os.path.isfile(os.path.join(path, ".agent", "state.json")):
            rows.append({"name": repo.name, "path": path, "reason": "not_a_project",
                         "detail": "the folder is there but has no .agent/state.json any more",
                         "hint": hint})
    return rows
