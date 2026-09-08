"""How this copy of agentdata was installed, and the exact command that adds an optional dependency group.

Skills print `hint` verbatim, so a wrong install command sends the agent (and its user) down a dead end: a Power BI
report repo holds PBIP folders and TMDL, not Python, and `pip install -e .` there fails by design with
"neither 'setup.py' nor 'pyproject.toml' found". The CLI is a laptop-wide tool; project repos install nothing.
"""
from __future__ import annotations
import os
import agentdata
from . import textio

REPO_URL = "https://github.com/agentchieflou/this-next-please.git"
REPO_URL_ENV = "AGENTDATA_REPO_URL"


def repo_url() -> str:
    """Where `ad-update` installs the CLI from.

    Overridable, because two real situations need it: a team running a fork or an internal mirror
    (the enterprise laptop this whole package is shaped around cannot always reach github.com), and
    the lifecycle test, which points it at a `git+file://` clone so the real `pip` and the real
    `ad-update` can be driven end to end without a network.
    """
    return os.environ.get(REPO_URL_ENV) or REPO_URL


def source_checkout() -> str | None:
    """Repo root when running from a clone (editable install or the checkout itself), else None."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(agentdata.__file__)))
    return root if os.path.exists(os.path.join(root, "pyproject.toml")) else None


def cli_spec(extras: str | None = None) -> str:
    """The pip argument that installs this package from `repo_url()`.

    `agentdata @ git+<url>` is the documented form and the one a person reads. It is a PEP 508
    direct reference, and PEP 508 requires an *authority* in the URL -- so `git+file:///srv/mirror`
    is rejected outright ("Invalid requirement"), which is what an air-gapped team pointing
    `AGENTDATA_REPO_URL` at a file share would hit. pip accepts a bare URL for any scheme, so that
    is what a URL without an authority becomes.

    Extras cannot be attached to a bare URL; a file mirror that needs them wants a directory
    install (`pip install "<path>[dev]"`) rather than a git one, so `--extras` keeps the PEP 508
    form and lets pip say what is wrong.
    """
    from urllib.parse import urlsplit

    url = f"git+{repo_url()}"
    if not urlsplit(url.split("+", 1)[1]).netloc:
        return url
    return f"agentdata{f'[{extras}]' if extras else ''} @ {url}"


def install_cmd(extras: str | None = None) -> str:
    """`pip install …` for this install kind: editable in a checkout, else the git spec (no clone needed)."""
    suffix = f"[{extras}]" if extras else ""
    root = source_checkout()
    if root:
        return f'pip install -e ".{suffix}"  (in the this-next-please checkout, {textio.norm_path(root)})'
    return f'pip install "agentdata{suffix} @ git+{repo_url()}"'


def editable_cmd(extras: str = "dev") -> str:
    """The runnable editable form, with no explanatory suffix (ad-update composes it with `git pull`)."""
    return 'pip install -e ".[%s]"' % extras


def templates_dir() -> str:
    """Packaged project-stub templates. Ships in the wheel, so every install kind can run `ad-setup --project`."""
    return os.path.join(os.path.dirname(os.path.abspath(agentdata.__file__)), "templates", "project-stub")
