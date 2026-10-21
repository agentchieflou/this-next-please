"""Where setup is being run, and so where each answer is written.

Three places, said out loud at the top of every `ad-setup` and on `tnp`'s home screen:

* **repo** -- inside a git repository. Machine-wide answers (data source connections, tool paths, toil) go to the
  machine's config; this repository's answers (which environment of each source it reads, its Power BI targets) go
  to its own `AGENTS.md`.
* **folder** -- a folder that holds repositories, such as PyCharm's `PycharmProjects`. This is a machine-wide setup:
  only the machine's config is written, and the repositories found are listed with what each one already has.
* **machine** -- anywhere else: machine-wide only, as in a folder.

`--repo <name or path>` points a folder-scope run at one of its repositories, which is how a person sitting in
`PycharmProjects` sets up the one or two repositories that need Power BI without changing directory.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .. import config as C
from .. import textio

MAX_CHILDREN = 400          # a folder of repositories is scanned one level deep, never the disk


def repo_root(path: str) -> str | None:
    """The working tree root holding `path` (a `.git` directory, or a worktree's `.git` file), or None."""
    p = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def child_repos(folder: str) -> list[str]:
    """Repositories directly inside `folder`, by name; hidden folders skipped."""
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return []
    out = []
    for n in names[:MAX_CHILDREN]:
        if n.startswith("."):
            continue
        full = os.path.join(folder, n)
        if os.path.isdir(full) and os.path.exists(os.path.join(full, ".git")):
            out.append(full)
    return out


@dataclass
class Scope:
    kind: str                 # repo | folder | machine
    cwd: str
    root: str                 # the repository for `repo`, else the folder setup runs in
    repos: list[str] = field(default_factory=list)

    @property
    def agents_md(self) -> str:
        return os.path.join(self.root, "AGENTS.md") if self.kind == "repo" else ""

    @property
    def name(self) -> str:
        return os.path.basename(self.root.rstrip("/\\")) or self.root

    def writes(self) -> list[tuple[str, str]]:
        """(what, where) for every place this run may write. Passwords and tokens are never in a file."""
        out = [("machine config", C.display_path(C.path())),
               ("passwords", "the OS keyring (never a file)")]
        if self.kind == "repo":
            out.append(("this repo", textio.norm_path(self.agents_md)))
        return out

    def summary(self) -> str:
        if self.kind == "repo":
            return f"repo {self.name} ({textio.norm_path(self.root)}): machine settings and this repo's AGENTS.md"
        if self.kind == "folder":
            return (f"folder of {len(self.repos)} repos ({textio.norm_path(self.root)}): a machine-wide setup; "
                    "a repo's own settings need `--repo <name>` or a run inside it")
        return f"machine ({textio.norm_path(self.root)}): a machine-wide setup; no repo here"


def detect(cwd: str | None = None, repo: str | None = None) -> Scope:
    """The scope for `cwd`, or for `repo` (a name under `cwd`, or a path) when given. Raises ConfigError for a
    `repo` that is not a repository."""
    cwd = os.path.abspath(cwd or os.getcwd())
    if repo:
        cand = repo if os.path.isabs(repo) else os.path.join(cwd, repo)
        root = repo_root(cand) if os.path.isdir(cand) else None
        if not root:
            names = ", ".join(os.path.basename(r) for r in child_repos(cwd)[:12]) or "none here"
            raise C.ConfigError(f"--repo {repo}: not a git repository", hint=f"repositories in this folder: {names}")
        return Scope("repo", cwd, root, [root])
    root = repo_root(cwd)
    if root:
        return Scope("repo", cwd, root, [root])
    repos = child_repos(cwd)
    return Scope("folder" if repos else "machine", cwd, cwd, repos)


SOURCE_FACT = {"teradata": "env", "hive": "hive_env", "impala": "impala_env", "oracle": "oracle_env",
               "spark": "spark_env"}


def repo_summary(root: str, cfg: dict | None = None) -> dict:
    """What one repository's AGENTS.md says about setup, for the folder listing: which source environments it reads
    (and whether the machine has them) and how many Power BI targets it has."""
    from .. import facts as F
    cfg = C.load() if cfg is None else cfg
    md = os.path.join(root, "AGENTS.md")
    if not os.path.exists(md):
        return {"name": os.path.basename(root), "agents_md": False, "sources": {}, "pbi_targets": 0, "unknown": []}
    facts = C.project_facts(md)
    sources, unknown = {}, []
    for s, key in SOURCE_FACT.items():
        env = facts.get(key)
        if env:
            sources[s] = env
            if env not in (C.get(cfg, f"sources.{s}.envs", {}) or {}):
                unknown.append(f"{s}:{env}")
    return {"name": os.path.basename(root), "agents_md": True, "sources": sources,
            "pbi_targets": len(F.pbi_targets(md, facts)), "unknown": unknown}
