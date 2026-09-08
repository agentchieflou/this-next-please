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

    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


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


@dataclass
class Repo:
    """A registered checkout. `name` is what every other command addresses it by."""

    name: str
    path: str
    jira_project: str = ""
    added: str = ""
    extra: dict = field(default_factory=dict)

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
            self.repos[name] = Repo(name=name, path=entry.get("path", ""),
                                    jira_project=entry.get("jira_project", ""),
                                    added=entry.get("added", ""))
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

    def add(self, path: str, name: str | None = None) -> Repo:
        full = os.path.abspath(C.expand(path))
        ok, why = _looks_like_a_project(full)
        if not ok:
            raise RegistryError(f"{textio.norm_path(full)} is not an agent project: {why}",
                                "run `ad-setup --project .` there first, so it has an AGENTS.md and "
                                "a .agent/state.json for the agent to work from")

        chosen = name or os.path.basename(full.rstrip("/\\"))
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

        repo = Repo(name=chosen, path=textio.norm_path(full),
                    jira_project=facts.get("jira_project", ""),
                    added=time.strftime("%Y-%m-%d %H:%M"))
        self.repos[chosen] = repo
        self.save()
        return repo

    def remove(self, name: str) -> Repo:
        repo = self.get(name)
        del self.repos[name]
        self.save()
        return repo
