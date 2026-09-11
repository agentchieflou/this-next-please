"""Which repositories the fleet knows about, and where its own state lives.

Registration is **explicit**. There is no directory-root discovery: a folder becomes an agent's home
because someone said so, which is the only way the operator can be sure a stray checkout under
`C:/repos` is not about to be given a ticket.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field

from .. import config as C
from .. import textio

FLEET_DIR_ENV = "AGENTDATA_FLEET_DIR"
AGENT_ENV = "AGENTDATA_FLEET_AGENT"


class RegistryError(Exception):
    """Refused, with a hint. Carries the `ok: false` wording the CLI prints."""

    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code or ("not_a_project" if "not an agent project" in msg else
                             "repo_exists" if "already registered" in msg else
                             "wrong_repo" if "no repo named" in msg else "refused")


def fleet_dir() -> str:
    """`~/.agentdata/fleet`, or `$AGENTDATA_FLEET_DIR`.

    Derived from `config.path()` rather than from `~` directly, so a test that redirects
    `AGENTDATA_CONFIG` moves the fleet with it and never touches a developer's real fleet.
    """
    override = os.environ.get(FLEET_DIR_ENV)
    if override:
        return textio.norm_path(os.path.abspath(C.expand(override)))
    return textio.norm_path(os.path.join(os.path.dirname(os.path.abspath(C.path())), "fleet"))


def agent_dir(name: str) -> str:
    return textio.norm_path(os.path.join(fleet_dir(), "agents", textio.safe_name(name)))


#: Keys the record owns. Everything else in an entry belongs to `extra` and is written back
#: untouched, so a field added by a newer build survives a round trip through an older one.
_OWN_KEYS = ("name", "path", "jira_project", "added")


@dataclass
class Repo:
    """A registered checkout. `name` is what every other command addresses it by.

    **One agent per registered working tree**, not per repository: two `git worktree` checkouts of
    one repository are two working trees, each with its own agent, its own lock and its own branch.
    `project` is what says they are the same piece of work, and it defaults to `name`, so a registry
    written before #175 groups every repository as its own project by definition (#175).
    """

    name: str
    path: str
    jira_project: str = ""
    added: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def project(self) -> str:
        """Which project this checkout is one of. Its own name unless something said otherwise."""
        return str(self.extra.get("project") or "") or self.name

    @property
    def worktree_of(self) -> str:
        """The main checkout this one was resolved from, if it is a `git worktree`.

        Recorded at the human's `repo add` and then never re-derived: the `gitdir:` pointer is
        followed once, by a person's explicit request, and nothing at runtime follows it again.
        """
        return str(self.extra.get("worktree_of") or "")

    def to_json(self) -> dict:
        return {"name": self.name, "path": self.path, "jira_project": self.jira_project,
                "added": self.added, **self.extra}

    @property
    def state_file(self) -> str:
        return os.path.join(self.path, ".agent", "state.json")

    def state(self) -> dict:
        """The repo's own `.agent/state.json`, **read only**.

        The fleet never writes here. `ad-state` is the single writer, and a supervisor that edited a
        repo's state would be the fastest way to make two sources of truth.
        """
        try:
            return json.loads(textio.read_text(self.state_file))
        except (OSError, ValueError):
            return {}


def worktree_main(path: str) -> str:
    """The main checkout a `git worktree` points back at, or `""` if this is not one (#175).

    A linked worktree's `.git` is a **file** holding one `gitdir:` line into the main checkout's
    `.git/worktrees/<name>/`; the main checkout is two directories above that. This is the only
    place in the fleet that pointer is ever followed, and it is followed at a person's explicit
    `repo add`, once, with the answer kept in `extra` so nothing at runtime follows it again.
    `scan.py`'s rule stands: an unattended walk reads no second repository's internals.
    """
    dot = os.path.join(path, ".git")
    if not os.path.isfile(dot):
        return ""                              # a normal checkout, or no checkout at all
    try:
        line = textio.read_text(dot).strip()
    except (OSError, ValueError):
        return ""
    if not line.lower().startswith("gitdir:"):
        return ""
    pointer = line.split(":", 1)[1].strip()
    if not pointer:
        return ""
    if not os.path.isabs(pointer):
        pointer = os.path.join(path, pointer)
    pointer = os.path.normpath(pointer)        # <main>/.git/worktrees/<name>
    worktrees = os.path.dirname(pointer)
    gitdir = os.path.dirname(worktrees)
    if os.path.basename(worktrees).lower() != "worktrees":
        return ""                              # a submodule, or something else entirely
    if os.path.basename(gitdir).lower() != ".git":
        return ""
    main = os.path.dirname(gitdir)
    return textio.norm_path(main) if os.path.isdir(main) else ""


def _stem(basename: str, project: str) -> str:
    """The part of a worktree's folder name that is not just the project's name again.

    `git worktree add ../luna-hotfix` is the common shape, and `<project>-<basename>` on that reads
    `luna-luna-hotfix`. The operator has to recognise this name in a tile header at a glance.
    """
    low, proj = basename.lower(), project.lower()
    for sep in ("-", "_", "."):
        if low.startswith(proj + sep):
            return basename[len(project) + 1:] or basename
    return basename


def _looks_like_a_project(path: str) -> tuple[bool, str]:
    """(ok, why not). A project is a folder an agent could actually work in."""
    if not os.path.isdir(path):
        return False, "no such directory"
    if not os.path.isfile(os.path.join(path, "AGENTS.md")):
        return False, "no AGENTS.md"
    if not os.path.isfile(os.path.join(path, ".agent", "state.json")):
        return False, "no .agent/state.json"
    return True, ""


class Registry:
    """`~/.agentdata/fleet/registry.json`, loaded and saved whole. It is a handful of entries."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(fleet_dir(), "registry.json")
        self.repos: dict[str, Repo] = {}
        self.load()

    def load(self) -> "Registry":
        self.repos = {}
        if not os.path.isfile(self.path):
            return self
        try:
            raw = json.loads(textio.read_text(self.path))
        except ValueError as e:
            raise RegistryError(f"the fleet registry is not valid JSON: {self.path} ({e})",
                                "fix or delete it; `ad-fleet repo add` will recreate it") from None
        for entry in raw.get("repos", []):
            name = entry.get("name")
            if not name:
                continue
            # Everything that is not one of the record's own four keys is kept, and written back
            # by `to_json`. Before this, `load()` dropped what it did not recognise -- so a field
            # added by a newer build was silently erased by the next `repo add` from an older one,
            # and nothing could be added to an entry at all (#175).
            self.repos[name] = Repo(name=name, path=entry.get("path", ""),
                                    jira_project=entry.get("jira_project", ""),
                                    added=entry.get("added", ""),
                                    extra={k: v for k, v in entry.items()
                                           if k not in _OWN_KEYS})
        return self

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        body = {"version": 1, "repos": [r.to_json() for r in self.sorted()]}
        textio.write_text(self.path, json.dumps(body, indent=2) + "\n")
        return textio.norm_path(self.path)

    def sorted(self) -> list[Repo]:
        return [self.repos[k] for k in sorted(self.repos)]

    def get(self, name: str) -> Repo:
        if name in self.repos:
            return self.repos[name]
        known = ", ".join(sorted(self.repos)) or "none registered"
        raise RegistryError(f"no repo named {name!r} in the fleet",
                            f"registered: {known}. Add one with `ad-fleet repo add <path>`")

    def add(self, path: str, name: str | None = None, *, project: str | None = None) -> Repo:
        full = os.path.abspath(C.expand(path))
        ok, why = _looks_like_a_project(full)
        if not ok:
            raise RegistryError(f"{textio.norm_path(full)} is not an agent project: {why}",
                                "run `ad-setup --project .` there first, so it has an AGENTS.md and "
                                "a .agent/state.json for the agent to work from")

        # A `git worktree` of a repository already registered here is a second working tree of one
        # project, not a stranger that happens to share its links. Followed here and only here, at
        # a human's add (#175).
        main = worktree_main(full)
        sibling = None
        if main:
            for repo in self.repos.values():
                if repo.path.rstrip("/\\").lower() == main.rstrip("/\\").lower():
                    sibling = repo
                    break

        basename = os.path.basename(full.rstrip("/\\"))
        chosen = name or (f"{sibling.project}-{_stem(basename, sibling.project)}"
                          if sibling else basename)
        if chosen in self.repos and self.repos[chosen].path != textio.norm_path(full):
            raise RegistryError(f"a different repo is already registered as {chosen!r}: "
                                f"{self.repos[chosen].path}",
                                "pass --name to give this one a different name")

        facts = {}
        try:
            cwd = os.getcwd()
            os.chdir(full)
            try:
                facts = C.project_facts()
            finally:
                os.chdir(cwd)
        except OSError:
            facts = {}

        import time

        was = self.repos.get(chosen)
        extra = dict(was.extra) if was and was.path == textio.norm_path(full) else {}
        named = project or (sibling.project if sibling else "")
        # `project` defaults to `name`, so it is written down only when it is something else --
        # which is what keeps every registry written before this slice unchanged by definition.
        if named and named != chosen:
            extra["project"] = named
        if main:
            extra["worktree_of"] = main

        repo = Repo(name=chosen, path=textio.norm_path(full),
                    jira_project=facts.get("jira_project", ""),
                    added=time.strftime("%Y-%m-%d %H:%M"),
                    extra=extra)
        self.repos[chosen] = repo
        self.save()
        return repo

    def remove(self, name: str) -> Repo:
        repo = self.get(name)
        del self.repos[name]
        self.save()
        return repo
