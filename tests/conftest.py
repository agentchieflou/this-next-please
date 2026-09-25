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
import copy
import importlib
import os
import random
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback

import pytest

# Plugins of the suite's own: tests/orphans.py fails a test process that leaves a child behind (#317).
pytest_plugins = ["orphans"]

from subproc import agentdata_env  # noqa: E402 - after pytest_plugins, which #317 puts right after pytest

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


def playwright_browsers_dir(environ, platform, home):
    """Where Playwright looks for its browsers on this machine, before any test moves `~` (#296).

    Playwright finds its browsers relative to the *home* on Linux and macOS, and `isolated_home`
    points `HOME` at an empty temp dir -- so without this every browser test skipped on Linux CI
    ("no chromium to drive the page with"), and only the Windows leg, whose browsers live under
    `%LOCALAPPDATA%`, ran the browser tier at all. `PLAYWRIGHT_BROWSERS_PATH` wins when it is set.
    """
    preset = environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if preset:
        return preset
    if platform.startswith("win"):
        local = environ.get("LOCALAPPDATA")
        return os.path.join(local, "ms-playwright") if local else None
    if platform == "darwin":
        return os.path.join(home, "Library", "Caches", "ms-playwright")
    cache = environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(cache, "ms-playwright")


# The real machine's browsers, resolved once at import, before `isolated_home` moves `~`. None when
# that directory does not exist, so a laptop with no Chromium still skips with a named reason.
REAL_PLAYWRIGHT_BROWSERS = playwright_browsers_dir(os.environ, sys.platform, os.path.expanduser("~"))
if REAL_PLAYWRIGHT_BROWSERS and not os.path.isdir(REAL_PLAYWRIGHT_BROWSERS):
    REAL_PLAYWRIGHT_BROWSERS = None


def pytest_addoption(parser):  # pragma: no cover - CLI plumbing
    parser.addoption("--shuffle-seed", action="store", default=None,
                     help="shuffle test order with this seed, to catch order dependence")


def pytest_collection_modifyitems(config, items):  # pragma: no cover - collection hook
    seed = config.getoption("--shuffle-seed")
    if seed is None:
        return
    random.Random(int(seed)).shuffle(items)


# The declared dependencies whose absence fails tests rather than skipping them by name (#297; the
# operator's answer on #288). Imported, not `find_spec`-ed: a shadow package is found without being
# run, so a dependency that cannot actually import would pass a spec check.
DECLARED_DEPENDENCIES = ("rich", "yaml")


def missing_dependencies(names=DECLARED_DEPENDENCIES):
    missing = []
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def pytest_configure(config):  # pragma: no cover - session hook
    """A sandbox without a declared dependency gets one line, not fourteen wrong failures."""
    missing = missing_dependencies()
    if missing:
        pytest.exit("the suite runs against its declared dependencies; missing: "
                    f"{', '.join(missing)}. Run: python -m pip install -e \".[dev]\"", returncode=4)


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


def pytest_runtest_setup(item):  # pragma: no cover - setup hook
    """Every testcase in a junit file carries its file and markers (#309).

    `.github/scripts/durations.py` keys a test's time by its file and tier. pytest's default
    `junit_family` (xunit2) drops the `file` attribute from `<testcase>`, but it still writes
    `user_properties` as `<properties>`, so the file travels there, with `/` on every OS so one
    file has one key in `tests/durations.json` (`item.location` is `tests\\x.py` on Windows).
    """
    item.user_properties.append(("file", item.location[0].replace(os.sep, "/")))
    item.user_properties.append(("markers", ",".join(sorted({m.name for m in item.iter_markers()}))))


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
    # #296: HOME moves, the browsers stay where they are. Set only when the machine has them and
    # nobody named a path already.
    if REAL_PLAYWRIGHT_BROWSERS and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", REAL_PLAYWRIGHT_BROWSERS)
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


def browser_skip_is_a_failure(has_browser_marker, skipped, environ):
    """A browser test may not skip in a job that installed a browser (#296).

    `AGENTDATA_REQUIRE_BROWSER=1` is that job's promise that Chromium is there; a skip under it is a
    browser that went missing, which is exactly what hid the whole tier on Linux for days.
    """
    return bool(has_browser_marker and skipped and environ.get("AGENTDATA_REQUIRE_BROWSER") == "1")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # pragma: no cover - report hook
    outcome = yield
    report = outcome.get_result()
    skipped = report.skipped and not hasattr(report, "wasxfail")
    if browser_skip_is_a_failure(item.get_closest_marker("browser") is not None, skipped, os.environ):
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        report.outcome = "failed"
        report.longrepr = f"a browser test may not skip in a job that installed a browser: {reason}"


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
        environment = agentdata_env(env)
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


@pytest.fixture(autouse=True)
def _no_process_listing_in_tests(monkeypatch):
    """No test lists this machine's processes. The Copilots running on it are not a test's input.

    Every desk a test serves offers adoptions, and those come from `adopt.agent_processes` -- which
    on Windows is a PowerShell `Get-CimInstance Win32_Process`: seconds to start, and past ten on a
    loaded runner (the regression #282 fixed). #282 moved it off the desk's request path, but not
    out of the suite: every snapshot that found the ten-second cache stale still started one, so the
    serial Windows browser leg ran a PowerShell and a CIM query every ten seconds from its first
    desk to its last, beside SwiftShader drawing the ink skins on the same four cores. And `adopt`,
    `start` and a resume still list synchronously, inside the request a test is waiting on. None of
    it was asked for: a runner has no Copilot, and on a laptop that has one, a desk test would offer
    to adopt the developer's own session.

    So the suite sees no processes. A test about the listing replaces `_windows_processes`,
    `_posix_processes`, `_list_now` or `agent_processes` itself, as the ones that exist already do,
    and its patch wins over this one. The memo is a fresh one per test, so no listing carries over.
    """
    from agentdata.fleet import adopt as A

    monkeypatch.setattr(A, "_windows_processes", lambda: [])
    monkeypatch.setattr(A, "_posix_processes", lambda: [])
    monkeypatch.setattr(A, "_cache", {"at": 0.0, "rows": []})
    monkeypatch.setattr(A, "_listing", {"thread": None})


@pytest.fixture(autouse=True)
def _a_test_closes_the_catalogue_it_opened():
    """The desk's sqlite catalogue is closed by the test that opened it, not inside the next one.

    `serve` keeps its handles in a module global, so a desk fixture that does not swap `_desk` for
    its own copy (`running_desk`, for one) left its catalogue open when it finished. The next test
    to touch a desk found handles for another fleet and dropped them in `_fresh()` -- closing the
    last test's sqlite, which on Windows is a WAL checkpoint, an fsync and two file deletes, under
    `_desk_lock`, inside whatever that test was waiting on. On the Windows 3.14 leg of e705117 that
    was `GET /api/fleet` in `test_desk_browser_layouts_and_sync`, still in `catalogue.close` at
    three seconds of the five it had to draw a tile. Closing here moves the cost to the teardown of
    the test that paid for the handle; `dir` is left alone, so the next test still forgets the old
    fleet exactly as it did.
    """
    yield
    close_the_desk_catalogue()


def close_the_desk_catalogue() -> None:
    """Close and forget the catalogue `serve` holds, if it has been imported and holds one."""
    serve = sys.modules.get("agentdata.fleet.serve")
    if serve is None:
        return
    with serve._desk_lock:
        cat, serve._desk["catalogue"] = serve._desk.get("catalogue"), None
    if cat is not None:
        try:
            cat.close()
        except Exception:                    # noqa: BLE001 - a handle already closed is the point
            pass


# The desk's process state, reset for every test by this one owner (#298, the root of #227).
# `agentdata/fleet` keeps these in module globals: right for one long-running `ad-fleet serve`, wrong
# for a suite where every test has its own fleet directory. Thirty-five modules used to reset parts of
# it by hand, eight different ways; serially a file ran contiguously and hid the gaps, and
# `--dist load` interleaved modules in one worker and showed them. `tests/test_hygiene_process_state.py`
# fails on a new mutable global in `agentdata/fleet` that is neither here nor allow-listed there.
FLEET_PROCESS_STATE = {
    "agentdata.fleet.serve": ("_desk", "_selection", "_desk_loaded", "_refreshed_at", "_measure_asks",
                              "_desk_written", "_read_order", "LOADED", "_SERVING"),
    "agentdata.fleet.fingerprint": ("_cache",),
    "agentdata.fleet.poll": ("_branches_cache",),
    "agentdata.fleet.trace": ("_SECONDS_CACHE",),
}
# Each name's import-time value, copied once per process before any test runs.
_FLEET_PRISTINE: dict[str, dict[str, object]] = {}


def snapshot_fleet_process_state() -> None:
    for module, names in FLEET_PROCESS_STATE.items():
        mod = importlib.import_module(module)
        _FLEET_PRISTINE[module] = {name: copy.deepcopy(getattr(mod, name)) for name in names}


def pytest_sessionstart(session):  # pragma: no cover - session hook
    snapshot_fleet_process_state()


@pytest.fixture(autouse=True)
def _fresh_fleet_process_state(monkeypatch):
    """Every test starts with the desk's globals as a fresh process has them, and gives them back.

    A fresh deep copy each time, so nothing one test put in a dict reaches the next; `_read_order`
    gets a new run id, as a new process would. `_a_test_closes_the_catalogue_it_opened` closes the
    test's own catalogue at teardown, before monkeypatch puts the originals back.
    """
    if not _FLEET_PRISTINE:
        snapshot_fleet_process_state()
    for module, values in _FLEET_PRISTINE.items():
        mod = sys.modules[module]
        for name, value in values.items():
            fresh = ({"run": secrets.token_hex(4), "n": 0} if (module, name) == ("agentdata.fleet.serve", "_read_order")
                     else copy.deepcopy(value))
            monkeypatch.setattr(mod, name, fresh)


# The threads a desk server leaves behind: `ThreadingHTTPServer.serve_forever` on a thread of its own,
# a request handler (`process_request_thread`) still running, or the desk's process listing.
SERVER_THREAD_MARKS = ("(serve_forever)", "(process_request_thread)")
SERVER_THREAD_NAMES = ("adopt-listing",)
THREAD_GUARD_WAIT_S = 10.0
THREAD_GUARD_POLL_S = 0.05


def _is_server_thread(thread: threading.Thread) -> bool:
    return thread.name in SERVER_THREAD_NAMES or any(mark in thread.name for mark in SERVER_THREAD_MARKS)


def server_threads_left(before: set, *, wait: float = THREAD_GUARD_WAIT_S) -> list:
    """The desk server threads started since `before` that are still alive after up to `wait` s."""
    deadline = time.monotonic() + wait
    while True:
        left = [t for t in threading.enumerate()
                if t not in before and t.is_alive() and _is_server_thread(t)]
        if not left or time.monotonic() >= deadline:
            return left
        time.sleep(THREAD_GUARD_POLL_S)


@pytest.fixture(autouse=True)
def _a_test_leaves_no_server_thread_running():
    """A test that leaves a desk server thread behind fails, naming it and where it is.

    A server a test does not shut down keeps serving into the next test's clock, and under
    `--dist load` into another module's. The thread is found where it was left, not three tests later.
    """
    before = set(threading.enumerate())
    yield
    left = server_threads_left(before)
    if left:
        frames = sys._current_frames()
        stacks = "\n".join(
            f"--- {t.name}\n" + "".join(traceback.format_stack(frames[t.ident])) if t.ident in frames
            else f"--- {t.name} (no frame)"
            for t in left)
        pytest.fail(f"this test left a desk server thread running: {', '.join(t.name for t in left)}\n"
                    f"{stacks}", pytrace=False)


# What the page and the server were doing when a wait on the desk ran out. A browser test that
# times out says only "waiting for locator('.tile') to be visible", which is the one fact nobody
# needed. The Windows browser leg has failed that way on two tests since #237 while passing on the
# same code the next run, and never locally -- so the next failure has to explain itself.
_PAGE_STATE = """() => {
  const g = (name) => { try { return eval(name); } catch (e) { return '<' + e.name + '>'; } };
  const d = g('desk');
  return {
    url: location.href, ready: document.readyState, body: document.body && document.body.className,
    layout: g('LAYOUT'), window: g('W_NAME'), open: g('openTile'), focused: g('focused'),
    widths: g('myWidths'), gutterHeld: g('!!gutterHeld'), windowWrites: g('windowWrites'),
    streamDead: g('streamDead'),
    deskVersion: d && d.desk ? d.desk.version : null,
    windows: d && d.desk ? d.desk.windows : null,
    tiles: Array.from(document.querySelectorAll('.tile')).map((t) => {
      const r = t.getBoundingClientRect();
      return [t.dataset.repo, t.className, getComputedStyle(t).display, Math.round(r.width), Math.round(r.height)];
    }),
  };
}"""

# Twice on the Windows 3.14 leg a desk page never finished booting: `app.js` ran, but nothing from
# `common.js` had (#435). The page state cannot say whether a script failed to load, was answered
# with an error, or threw. So every page a browser test opens keeps its failed requests, its
# uncaught errors and the answer to each `/static/*` request, and a wait that runs out prints them.
#: How many failed requests and page errors a timeout prints, the latest ones.
PAGE_EVENTS_SHOWN = 40


def _record_what_the_page_loads(page) -> None:
    """Listen on `page` for `requestfailed`, `pageerror` and each `/static/*` request's answer, and
    keep them on the page for `_explain_the_page`. A listener never raises into the test."""
    from urllib.parse import urlsplit

    events: list[str] = []
    statics: dict[str, str] = {}

    def is_static(url: str) -> bool:
        return urlsplit(url).path.startswith("/static/")

    def quietly(listen):
        def listener(arg):
            try:
                listen(arg)
            except Exception:                            # noqa: BLE001 - diagnostics never break a test
                pass
        return listener

    unanswered = "sent, no answer"

    def request(r):
        if is_static(r.url):
            statics[r.url] = unanswered

    def response(r):
        if is_static(r.url):
            statics[r.url] = str(r.status)

    def failed(r):
        events.append(f"requestfailed {r.method} {r.url}: {r.failure}")
        if is_static(r.url):
            # Chromium aborts a script answered 404 after its response: keep the status too.
            answered = statics.get(r.url, unanswered)
            statics[r.url] = (f"failed: {r.failure}" if answered == unanswered
                              else f"{answered}, then failed: {r.failure}")

    def error(e):
        stack = (getattr(e, "stack", None) or str(e)).strip().splitlines()
        events.append("pageerror " + "\n    ".join(stack[:6]))

    try:
        page.on("request", quietly(request))
        page.on("response", quietly(response))
        page.on("requestfailed", quietly(failed))
        page.on("pageerror", quietly(error))
        page._explain_record = (events, statics)
    except Exception:                                    # noqa: BLE001 - diagnostics never break a test
        pass


def _explain_what_the_page_loaded(page) -> None:
    record = getattr(page, "_explain_record", None)
    if record is None:
        print("(this page's requests were not recorded: it was not opened with browser.new_page or "
              "context.new_page)", file=sys.stderr)
        return
    events, statics = record
    print(f"--- failed requests and page errors ({len(events)}; the last {PAGE_EVENTS_SHOWN} shown) ---",
          file=sys.stderr)
    for line in events[-PAGE_EVENTS_SHOWN:] or ["(none)"]:
        print(line, file=sys.stderr)
    print("--- /static/* answers ---", file=sys.stderr)
    for url, status in list(statics.items()) or [("", "(no /static/ request was made)")]:
        print(f"{status}  {url}", file=sys.stderr)


def _explain_the_page(page, selector: str) -> None:
    import faulthandler
    import json

    print(f"\n--- the page, when the wait for {selector!r} ran out ---", file=sys.stderr)
    try:
        print(json.dumps(page.evaluate(_PAGE_STATE), indent=1, default=str), file=sys.stderr)
    except Exception as e:                                   # noqa: BLE001 - diagnostics never mask the failure
        print(f"(the page could not be read: {e})", file=sys.stderr)
    try:
        _explain_what_the_page_loaded(page)
    except Exception as e:                                   # noqa: BLE001 - diagnostics never mask the failure
        print(f"(the page's requests could not be listed: {e})", file=sys.stderr)
    print("--- every thread in this process: the desk server's handlers are among them ---",
          file=sys.stderr, flush=True)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


# Three different browser tests have failed on the Windows leg with the same sign in their stderr:
# a desk answer written only after the browser had gone. A stack taken while the request is still
# stuck says what it is waiting on; one taken afterwards says nothing.
SLOW_REQUEST_S = 3.0


def _explain_a_slow_request(method: str, path: str) -> None:
    import faulthandler

    print(f"\n--- the desk has been answering {method} {path} for {SLOW_REQUEST_S:g} s; every thread ---",
          file=sys.stderr, flush=True)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


def _watch_the_desk_for_slow_answers(monkeypatch) -> None:
    import threading

    try:
        from agentdata.fleet import serve
    except ImportError:
        return

    def watched(real):
        def answer(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/events":                  # the stream is meant to stay open
                return real(self)
            timer = threading.Timer(SLOW_REQUEST_S, _explain_a_slow_request, (self.command, path))
            timer.daemon = True
            timer.start()
            try:
                return real(self)
            finally:
                timer.cancel()
        return answer

    monkeypatch.setattr(serve.Handler, "do_GET", watched(serve.Handler.do_GET))
    monkeypatch.setattr(serve.Handler, "do_POST", watched(serve.Handler.do_POST))


@pytest.fixture(autouse=True)
def _explain_a_desk_wait_that_ran_out(request, monkeypatch):
    """On a `browser` test, a `wait_for_selector` or `wait_for_function` that times out prints the
    page's own state, its failed requests, its uncaught errors and its `/static/*` answers, and a
    stack for every thread first, then raises exactly as it would have. And a desk request that
    has not been answered after `SLOW_REQUEST_S` prints every thread's stack while it is still
    stuck. Both print to stderr, which pytest shows only for a test that failed. Nothing else
    changes."""
    if request.node.get_closest_marker("browser") is None:
        yield
        return
    _watch_the_desk_for_slow_answers(monkeypatch)
    try:
        from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout
    except ImportError:
        yield
        return
    real_selector, real_function = Page.wait_for_selector, Page.wait_for_function

    def wait_for_selector(self, selector, *args, **kwargs):
        try:
            return real_selector(self, selector, *args, **kwargs)
        except PlaywrightTimeout:
            _explain_the_page(self, selector)
            raise

    def wait_for_function(self, expression, *args, **kwargs):
        try:
            return real_function(self, expression, *args, **kwargs)
        except PlaywrightTimeout:
            _explain_the_page(self, f"wait_for_function({expression})")
            raise

    def recorded(real):
        # `Browser.new_page` makes its context below the sync API, so both doors are watched.
        def new_page(self, *args, **kwargs):
            page = real(self, *args, **kwargs)
            _record_what_the_page_loads(page)
            return page
        return new_page

    monkeypatch.setattr(Page, "wait_for_selector", wait_for_selector)
    monkeypatch.setattr(Page, "wait_for_function", wait_for_function)
    monkeypatch.setattr(Browser, "new_page", recorded(Browser.new_page))
    monkeypatch.setattr(BrowserContext, "new_page", recorded(BrowserContext.new_page))
    yield
