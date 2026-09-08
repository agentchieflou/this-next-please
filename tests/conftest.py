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
def forget_the_ribbon_probe():
    """`desktop.external_tools_writable` is memoised per process; a test is a new machine.

    The memo exists so one `ad-doctor` run creates and deletes at most one file in the folder every
    user of the machine reads its ribbon from. Inside one pytest process that would leak an answer
    measured under one tmp_path into a test that means to measure a different one.
    """
    from agentdata.pbip import desktop as DT
    DT.clear_writable_cache()
    yield
    DT.clear_writable_cache()


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


@pytest.fixture(autouse=True)
def _no_user32_in_tests(monkeypatch):
    """`winui._enum_ctypes` is unavailable to the suite, so the injected fakes drive every platform.

    `desktop_windows_source()` prefers `EnumWindows` on win32 and only falls back to the Runner. That
    is correct for the product -- `ctx.det.run` is a real bound method in production, so preferring an
    injected runner would silently downgrade a real laptop from Z-order to `Get-Process` -- but it
    means that on the Windows runners the ctypes path answered for real, found no Power BI windows,
    and returned `[]` to eighty-four tests that had carefully supplied a fake. They passed here and
    failed there, which is the exact shape this repo runs Windows CI to catch.

    So the suite removes user32 rather than the product preferring the fake. A test that wants the
    real preference order patches `_enum_ctypes` itself, and that patch wins over this one; a test
    that wants `SOURCE_ENUM` semantics patches `desktop_windows_source`, as the transport tests
    already do. Everything else now behaves identically on both platforms.
    """
    from agentdata.pbip import winui

    def _no_user32():
        raise OSError("user32 is not available to the test suite (tests/conftest.py)")

    def _source(run=None):
        """The fake's rows, labelled the way the platform's own gate needs them.

        `resolve_transport(active=True)` refuses on Windows unless `EnumWindows` answered, and
        `external_tools_row` downgrades `via` from `zorder` to `file` on the same condition. Both are
        right for the product. But for the suite the injected fake *is* the enumeration, so on
        Windows it has to count as one -- otherwise seventy-odd transport tests assert the refusal
        instead of the behaviour they were written for, which is what the runners reported.

        Off Windows the gate is inactive and the honest label is the process table, which is exactly
        what `test_off_windows_the_zorder_verdict_refuses_to_claim_anything` checks: the probe must
        never claim a Z-order it could not have measured.
        """
        source = winui.SOURCE_ENUM if sys.platform == "win32" else winui.SOURCE_TABLE
        return winui._from_runner(run), source

    monkeypatch.setattr(winui, "_enum_ctypes", _no_user32, raising=False)
    monkeypatch.setattr(winui, "desktop_windows_source", _source, raising=False)

    # The same seam for the other win32-only probe. The runners are administrators, so the real
    # `shell32!IsUserAnAdmin` answers "already elevated" and overrides whatever a test injected --
    # which turned the epic's headline assertion, that "run elevated" is never printed to someone
    # who cannot, into a Windows-only failure. The fakes drive the `whoami /groups` path instead.
    from agentdata.setup.steps import powerbi as _pbi_step

    monkeypatch.setattr(_pbi_step, "_is_user_an_admin", lambda: False, raising=False)

    # And the third one: `probe.read_key(native=True)` goes straight to `winreg` on win32 and never
    # looks at the injected Runner, so on the runners the real HKLM answered and every test that
    # described a machine with the External Tools kill-switch set was told the switch was absent.
    # Forcing `native=False` routes the registry through the same fake on both platforms. A test
    # about `winreg` itself patches `_winreg_values`, which this does not touch.
    from agentdata.pbip import probe as _probe

    real_read_key = _probe.read_key

    def _read_key(hive, subkey, run=None, native=False):
        return real_read_key(hive, subkey, run=run, native=False)

    monkeypatch.setattr(_probe, "read_key", _read_key, raising=False)


@pytest.fixture(autouse=True)
def _no_browser_in_tests(monkeypatch):
    """No test may launch a real browser. `os.startfile` is Windows-only, so nothing here saw it.

    `cli_fleet._open_browser` opens the dashboard with `os.startfile` on Windows and `webbrowser`
    everywhere else. A test that patched only the fallback still opened Edge on the runner -- the
    job's cleanup step was terminating orphaned msedge processes -- and counted one handover fewer
    than it expected. Raising `OSError` is a state `_open_browser` already handles: it returns the
    "could not open a browser" sentence, and the URL was printed before either call.
    """
    def _no_startfile(path, *a, **k):
        raise OSError("no browser may be launched from the test suite (tests/conftest.py)")

    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", _no_startfile, raising=False)
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: False, raising=False)
