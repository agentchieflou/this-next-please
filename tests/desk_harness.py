"""The desk harness: one Playwright driver and one Chromium per worker, a fresh context per test (#299).

Every browser test used to start its own Playwright driver (a Node process) and its own Chromium:
about 0.65 s per test on an idle 4-core Linux box, against under 0.1 s for a new context on a
browser that is already up. Here the driver and the browser are started once per process (per
xdist worker, or the one serial process), lazily, on the first test that asks for `desk_browser`,
so a worker that runs no browser test never starts Node. Every page gets its own context, and a
test's contexts are closed when it ends, so nothing one test stored reaches the next.

`tests/conftest.py` lists this module in `pytest_plugins`, so its fixtures reach `tests/` and
`tests/regressions/` alike:

* `desk_server` -- a desk (`S.build(0)`) served on a daemon thread; `.url(extra)`, `.token`,
  `.port`, `.server`. It is always stopped at teardown.
* `desk_browser` -- the worker's Chromium, relaunched if a test closed it. Contexts the test
  created are closed at teardown; `close_pages(browser)` does it early, where a test used to call
  `browser.close()` before stopping its desk.
* `new_desk_page` -- `open(desk, extra="", *, width=1400, height=900, reduced=False,
  init_scripts=())` returns `(page, record)`: a page in a fresh context, with `COUNT_FETCHES` and
  `init_scripts` installed, at the desk's address, and a record of its page errors, console errors
  and warnings, failed requests and non-2xx answers.
* `no_desk_driver` -- stops the worker's driver for a test that needs `asyncio.run`.

A sync Playwright started in a thread and a `with sync_playwright()` in the same thread cannot both
be alive (Playwright raises "using Playwright Sync API inside the asyncio loop"), so while some
browser tests are not on the harness yet, `_one_driver_at_a_time` stops the shared driver before any
browser test that does not use `desk_browser`; the next harness test starts it again. #303 removes
it once every browser test is here.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

#: The environment this process started with, before `isolated_home` moves `~` for a test. The driver
#: is started under it: Playwright copies `os.environ` when it spawns Node, and a driver that lives
#: for the whole worker must not keep the first test's temporary HOME.
REAL_ENVIRON = dict(os.environ)

#: Every fetch the page makes, counted while it is in flight -- so the idle loop in
#: `test_fleet_ink.IDLE_LOOP` starts only once no answer the page asked for before the replay can
#: still land in the middle of it.
COUNT_FETCHES = """
  window.__inflight = 0;
  const realFetch = window.fetch;
  window.fetch = function () {
    window.__inflight += 1;
    return realFetch.apply(this, arguments).finally(() => { window.__inflight -= 1; });
  };
"""


def launch_chromium(p, args=()):
    """Chromium, from wherever this machine keeps it.

    Playwright pins a browser build to its own version and refuses to start when the two disagree,
    which is what happens on any runner that ships a browser separately from the wheel -- and it
    raises rather than skipping, so a machine without the exact build turned "no browser here" into
    a red suite. The binary is what these tests need, not the pin: `AGENTDATA_CHROMIUM` names one,
    a couple of known locations are tried, and only then do we skip and say so.

    Chromium is the engine under all three hosts the dashboard has to render in -- Edge, PyCharm's
    JCEF tool window and VS Code's Simple Browser -- so one engine covers the matrix.

    `args` are extra command-line switches for this one launch (#384 passes a Blink feature flag
    to measure an API no shell ships yet); every other caller passes none.

    The only launcher in the suite: the harness's shared browser comes from here too (#299).
    `tests/test_fleet_desk_browser.py` re-exports it for the tests that still import it from there.
    """
    try:
        return p.chromium.launch(headless=True, args=list(args))
    except Exception as first:                                  # noqa: BLE001 - any launch failure
        candidates = [os.environ.get("AGENTDATA_CHROMIUM", "")]
        for root in ("/opt/pw-browsers",):
            if os.path.isdir(root):
                for entry in sorted(os.listdir(root)):
                    candidates.append(os.path.join(root, entry, "chrome-linux", "chrome"))
        for path in candidates:
            if path and os.path.isfile(path):
                return p.chromium.launch(headless=True, executable_path=path, args=list(args))
        pytest.skip(f"no chromium to drive the page with: {first} "
                    f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')} "
                    f"HOME={os.environ.get('HOME', '')}")


# ------------------------------------------------------------------------------------ the desk


class Desk:
    """A desk served on a daemon thread, for one test."""

    def __init__(self, server, token):
        self.server = server
        self.token = token
        self.port = server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def url(self, extra: str = "") -> str:
        """The desk's page with its token, and `extra` (`"&w=side"`, say) after it."""
        return f"{self.base}/?t={self.token}{extra}"

    def stop(self) -> None:
        self.server.stopping.set()
        self.server.shutdown()
        self.server.server_close()


def serve_desk() -> Desk:
    """`S.build(0)` served on a daemon thread, polling at 0.05 s as every desk test has."""
    from agentdata.fleet import serve as S

    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    return Desk(server, token)


@pytest.fixture()
def desk_server():
    """A desk for this test, stopped at teardown whatever the test did. Request it after the
    fixtures that point the fleet somewhere (`fleet_home`)."""
    desk = serve_desk()
    try:
        yield desk
    finally:
        desk.stop()


# ------------------------------------------------------------------------ the driver and browser


def _real_environment(mp: pytest.MonkeyPatch) -> None:
    """Put the process environment back to `REAL_ENVIRON` inside `mp`, keeping only the browsers'
    path from the test's own: `isolated_home` names the real one there (#296)."""
    browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    for name in list(os.environ):
        if name not in REAL_ENVIRON:
            mp.delenv(name)
    for name, value in REAL_ENVIRON.items():
        if os.environ.get(name) != value:
            mp.setenv(name, value)
    if browsers:
        mp.setenv("PLAYWRIGHT_BROWSERS_PATH", browsers)


def _start_sync_playwright():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def start_driver(held: dict, start=_start_sync_playwright) -> None:
    """Start the worker's driver into `held["pw"]`, once, under the real environment."""
    if held.get("pw") is not None:
        return
    with pytest.MonkeyPatch.context() as mp:
        _real_environment(mp)
        held["pw"] = start()


def ensure_browser(held: dict, launch=launch_chromium):
    """The worker's browser, launched on first use and again if it is no longer connected."""
    browser = held.get("browser")
    if browser is not None and not browser.is_connected():
        print("desk_harness: the shared browser was disconnected (closed by a test, or it crashed); "
              "launching another", file=sys.stderr)
        browser = None
    if browser is None:
        browser = held["browser"] = launch(held["pw"])
    return browser


def stop_driver(held: dict) -> None:
    """Close the worker's browser and stop its driver, if they are up. Safe to call twice."""
    browser, pw = held.pop("browser", None), held.pop("pw", None)
    try:
        if browser is not None and browser.is_connected():
            browser.close()
    finally:
        if pw is not None:
            pw.stop()


def close_new_contexts(browser, before) -> None:
    """Close every context `browser` has that was not in `before`: a test's own pages."""
    if browser is None or not browser.is_connected():
        return
    for context in set(browser.contexts) - set(before):
        try:
            context.close()
        except Exception:                                   # noqa: BLE001 - already gone is closed
            pass


def close_pages(browser) -> None:
    """Close every page and context on the shared browser: what `browser.close()` did for a test's
    pages before the harness, where a test closes them before it stops its desk. Contexts from an
    earlier test were closed when it ended, so every one left is this test's."""
    close_new_contexts(browser, ())


@pytest.fixture(scope="session")
def _desk_driver():
    """This process's driver and browser, held for every test in it; started by `desk_browser`
    on first use, and stopped here at the end of the session (before `orphans` looks)."""
    held: dict = {}
    yield held
    stop_driver(held)


@pytest.fixture()
def desk_browser(_desk_driver):
    """The worker's Chromium. The contexts this test creates are closed when it ends."""
    start_driver(_desk_driver)
    browser = ensure_browser(_desk_driver)
    before = set(browser.contexts)
    yield browser
    close_new_contexts(_desk_driver.get("browser"), before)


def off_the_harness(browser_marked: bool, fixturenames) -> bool:
    """A browser test that does not use `desk_browser`: it opens its own `sync_playwright()`."""
    return browser_marked and "desk_browser" not in fixturenames


@pytest.fixture(autouse=True)
def _one_driver_at_a_time(request, _desk_driver):
    """A test off the harness cannot start its own driver while the shared one is up in this
    thread: stop the shared one first. The next harness test starts it again."""
    if off_the_harness(request.node.get_closest_marker("browser") is not None, request.fixturenames):
        stop_driver(_desk_driver)
    yield


@pytest.fixture()
def no_desk_driver(_desk_driver):
    """For a test that needs `asyncio.run` (or its own Playwright) in this thread: no shared driver."""
    stop_driver(_desk_driver)


# ------------------------------------------------------------------------------------ the pages


def desk_page(browser, *, width=1400, height=900, reduced=False, init_scripts=()):
    """A page in a fresh context of its own: `browser.new_page()` as the tests always had it, with
    the viewport, reduced motion or not, and `init_scripts` added before anything loads."""
    context = browser.new_context(viewport={"width": width, "height": height},
                                  reduced_motion="reduce" if reduced else "no-preference")
    page = context.new_page()
    for script in init_scripts:
        page.add_init_script(script)
    return page


def record_page(page) -> dict:
    """What went wrong on `page`, kept as it happens: uncaught errors, console errors and warnings,
    failed requests and answers outside 2xx (a 304 is a cache answer, not a failure)."""
    record: dict = {"errors": [], "console": [], "failed": [], "answers": []}
    page.on("pageerror", lambda e: record["errors"].append(str(e)))
    page.on("console", lambda m: record["console"].append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning") else None)
    page.on("requestfailed", lambda r: record["failed"].append(f"{r.method} {r.url}: {r.failure}"))
    page.on("response", lambda r: record["answers"].append(f"{r.status} {r.request.method} {r.url}")
            if not (200 <= r.status < 300 or r.status == 304) else None)
    return record


def open_desk(browser, url, *, width=1400, height=900, reduced=False, init_scripts=()):
    """`url` in a fresh page (`desk_page`), recorded (`record_page`): `(page, record)`."""
    page = desk_page(browser, width=width, height=height, reduced=reduced, init_scripts=init_scripts)
    record = record_page(page)
    page.goto(url, wait_until="domcontentloaded")
    return page, record


@pytest.fixture()
def new_desk_page(desk_browser):
    """`open(desk, extra="", *, width=1400, height=900, reduced=False, init_scripts=())`: a desk
    (or an address) in a fresh context with `COUNT_FETCHES` installed, as `(page, record)`."""
    def open_(desk, extra="", *, width=1400, height=900, reduced=False, init_scripts=()):
        url = desk if isinstance(desk, str) else desk.url(extra)
        return open_desk(desk_browser, url, width=width, height=height, reduced=reduced,
                         init_scripts=(COUNT_FETCHES,) + tuple(init_scripts))
    return open_
