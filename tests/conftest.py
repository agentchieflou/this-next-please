"""Shared fixtures and isolation for this repository's own suite.

Two problems this solves.

**Isolation.** Several modules read the real `~/.agentdata/config.json`, the real `AGENTS.md`, the
real keyring and the real `PATH`. A test that happens to pass on a laptop with pncli installed and
fails on one without it is not a test, and a test that writes to the developer's own config is worse.
Everything here runs against a temporary home unless it asks not to.

**Order independence.** The suite is shuffled in one CI job; a fixture that leaks state shows up
there rather than three months later as "works on my machine".
"""
from __future__ import annotations
import os
import random
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# Where `~` resolves, and therefore where `~/.agentdata` and `~/.copilot/skills` are looked for.
#
# APPDATA and LOCALAPPDATA are deliberately NOT here. On Windows they hold per-user *installed
# packages* (`%APPDATA%/Python/PythonXY/site-packages`), so redirecting them makes every subprocess
# answer "No module named pytest" on a machine that has a --user install -- which is exactly the
# shadowed-install situation `ad-update --check` warns about. `appdata_isolation` opts in for the
# few tests that are about the npm prefix.
HOME_VARS = ("HOME", "USERPROFILE", "XDG_CONFIG_HOME")


def pytest_addoption(parser):  # pragma: no cover - CLI plumbing
    parser.addoption("--shuffle-seed", action="store", default=None,
                     help="shuffle test order with this seed, to catch order dependence")


def pytest_collection_modifyitems(config, items):  # pragma: no cover - collection hook
    seed = config.getoption("--shuffle-seed")
    if seed is None:
        return
    random.Random(int(seed)).shuffle(items)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch, request):
    """A temporary home, config, and a quiet, machine-shaped environment.

    Opt out with `@pytest.mark.real_home` for the few tests that are *about* the real checkout.
    """
    if request.node.get_closest_marker("real_home"):
        yield None
        return

    home = tmp_path / "home"
    home.mkdir()
    for var in HOME_VARS:
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(home / ".agentdata" / "config.json"))

    # Redirecting the profile without this makes pip fall back to a *relative* cache directory, so
    # the slow tests -- which really do run `pip wheel` and `pip install` -- wrote 3.8 MB of HTTP
    # cache into `<repo>/pip/cache`, in the repository under test, where `git add -A` would have
    # committed it. PIP_CACHE_DIR is the supported knob and works on every OS; LOCALAPPDATA stays
    # untouched for the reason above.
    monkeypatch.setenv("PIP_CACHE_DIR", str(home / "pip-cache"))

    # a machine is reading: no colour, no rich, and UTF-8 whatever the console is
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("AGENTDATA_UI", "plain")
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.delenv("AGENTDATA_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    from agentdata import color, ui

    color.reset_cache()
    ui.reset_cache()
    yield home
    color.reset_cache()
    ui.reset_cache()


@pytest.fixture()
def appdata_isolation(tmp_path, monkeypatch):
    """Redirect APPDATA / LOCALAPPDATA, for tests about the npm global prefix or Desktop's data dir.

    Opt-in, because it also hides per-user installed Python packages from any subprocess.
    """
    d = tmp_path / "appdata"
    d.mkdir(exist_ok=True)
    for var in ("APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(d))
    return str(d)


@pytest.fixture()
def isolated_path(monkeypatch, fakes_dir):
    """PATH reduced to the interpreter's directory plus the fake tools.

    Not autouse: most tests never launch anything, and stripping PATH for them would only make
    failures confusing.
    """
    entries = [fakes_dir, os.path.dirname(sys.executable)]
    monkeypatch.setenv("PATH", os.pathsep.join(entries))
    return entries


@pytest.fixture()
def fakes_dir(tmp_path):
    """A directory the fake-tool harness (#72) installs stand-ins into."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    return str(d)


@pytest.fixture()
def state_file(tmp_path):
    """A `.agent/state.json` in the shape `ad-state` writes."""
    from agentdata import textio

    path = tmp_path / ".agent" / "state.json"
    textio.write_json(str(path), {
        "project": "TEST", "phase": "idle", "active_ticket": None, "branch": None,
        "pr_url": None, "confluence_url": None, "open_questions": [], "artifacts": [],
        "tools": {}, "last_updated": None,
    })
    return str(path)


@pytest.fixture()
def pbip(tmp_path):
    """A writable copy of the sample PBIP, so a test may edit it."""
    src = os.path.join(FIXTURES, "sample.pbip")
    if not os.path.exists(src):
        pytest.skip("tests/fixtures/sample.pbip is not present")
    dst = tmp_path / "sample.pbip"
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return str(dst)


@pytest.fixture()
def run_cmd(tmp_path):
    """Run an `ad-*` command as a real subprocess and parse what a caller would see.

    Returns `(returncode, stdout, stderr)`. Used by the black-box contract and no-traceback slices:
    in-process `main()` calls cannot catch a bare `sys.exit`, an import-time crash, or an escape
    sequence that only appears when stdout is a pipe.
    """
    def _run(args: list[str], *, cwd: str | None = None, timeout: int = 120, env: dict | None = None):
        environment = dict(os.environ)
        environment.update(env or {})
        p = subprocess.run([sys.executable, "-m", "agentdata", *args],
                           capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or str(tmp_path), encoding="utf-8", errors="replace",
                           env=environment)
        return p.returncode, p.stdout, p.stderr

    return _run
