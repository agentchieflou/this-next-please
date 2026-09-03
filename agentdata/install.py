"""How this copy of agentdata was installed, and the exact command that adds an optional dependency group.

Skills print `hint` verbatim, so a wrong install command sends the agent (and its user) down a dead end: a Power BI
report repo holds PBIP folders and TMDL, not Python, and `pip install -e .` there fails by design with
"neither 'setup.py' nor 'pyproject.toml' found". The CLI is a laptop-wide tool; project repos install nothing.
"""
from __future__ import annotations
import os
import agentdata

REPO_URL = "https://github.com/agentchieflou/this-next-please.git"


def source_checkout() -> str | None:
    """Repo root when running from a clone (editable install or the checkout itself), else None."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(agentdata.__file__)))
    return root if os.path.exists(os.path.join(root, "pyproject.toml")) else None


def install_cmd(extras: str | None = None) -> str:
    """`pip install …` for this install kind: editable in a checkout, else the git spec (no clone needed)."""
    suffix = f"[{extras}]" if extras else ""
    root = source_checkout()
    if root:
        return f'pip install -e ".{suffix}"  (in the this-next-please checkout, {root.replace(os.sep, "/")})'
    return f'pip install "agentdata{suffix} @ git+{REPO_URL}"'


def editable_cmd(extras: str = "dev") -> str:
    """The runnable editable form, with no explanatory suffix (ad-update composes it with `git pull`)."""
    return 'pip install -e ".[%s]"' % extras


def templates_dir() -> str:
    """Packaged project-stub templates. Ships in the wheel, so every install kind can run `ad-setup --project`."""
    return os.path.join(os.path.dirname(os.path.abspath(agentdata.__file__)), "templates", "project-stub")
