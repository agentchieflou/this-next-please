"""The desk harness's own rules (#299), without a browser: `tests/desk_harness.py`.

Decision 13 keeps the browser tier's count where it is, so the harness's browser checks fold into
`test_fleet_desk_browser.py::test_desk_browser_layouts_and_sync` (a context per page, reduced
motion, `COUNT_FETCHES`), and what can be told without Chromium is told here, with stand-ins for
the driver and the browser: the driver starts under the real environment and only once, a browser
a test closed is launched again, a test's contexts are closed and no one else's, and the desk
fixture serves and stops. (#303 took out the tests of a browser test off the harness: there is none
left, and `tests/test_hygiene_harness.py` keeps it so.)
"""
from __future__ import annotations
import os
import subprocess
import sys
import urllib.request

import pytest

import desk_harness as H
from test_fleet_events import fleet_home                        # noqa: F401 - fixture


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.closed = False

    def close(self):
        self.closed = True
        self.browser.contexts.remove(self)


class FakeBrowser:
    def __init__(self):
        self.contexts: list = []
        self.connected = True
        self.closed = 0

    def is_connected(self):
        return self.connected

    def new_context(self):
        ctx = FakeContext(self)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self.closed += 1
        self.connected = False


class FakeDriver:
    def __init__(self):
        self.stopped = 0

    def stop(self):
        self.stopped += 1


def test_the_driver_starts_under_the_real_home_and_keeps_the_browsers_path(isolated_home, monkeypatch):
    """Playwright copies `os.environ` into Node when it starts, and the driver outlives this test: it
    must see the machine's HOME, not this test's temporary one, and still the browsers' path."""
    assert os.environ["HOME"] == str(isolated_home)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/somewhere/browsers")
    monkeypatch.setenv("A_TEST_ONLY_VARIABLE", "1")
    seen = {}

    def start():
        seen.update(os.environ)
        return FakeDriver()

    held: dict = {}
    H.start_driver(held, start=start)
    assert seen.get("HOME") == H.REAL_ENVIRON.get("HOME") and seen.get("HOME") != str(isolated_home)
    assert seen["PLAYWRIGHT_BROWSERS_PATH"] == "/somewhere/browsers"
    assert "A_TEST_ONLY_VARIABLE" not in seen
    # And the test's own environment is as it was.
    assert os.environ["HOME"] == str(isolated_home) and os.environ["A_TEST_ONLY_VARIABLE"] == "1"

    driver = held["pw"]
    H.start_driver(held, start=lambda: pytest.fail("a second driver was started"))
    assert held["pw"] is driver


def test_a_browser_a_test_closed_is_launched_again_for_the_next():
    launched = []

    def launch(pw):
        launched.append(FakeBrowser())
        return launched[-1]

    held = {"pw": FakeDriver()}
    first = H.ensure_browser(held, launch=launch)
    assert H.ensure_browser(held, launch=launch) is first and len(launched) == 1
    first.close()
    second = H.ensure_browser(held, launch=launch)
    assert second is not first and second.is_connected() and len(launched) == 2


def test_a_test_closes_its_own_contexts_and_no_one_elses():
    browser = FakeBrowser()
    kept = browser.new_context()
    before = set(browser.contexts)
    mine = [browser.new_context(), browser.new_context()]
    H.close_new_contexts(browser, before)
    assert all(c.closed for c in mine) and not kept.closed and browser.contexts == [kept]
    H.close_pages(browser)
    assert kept.closed and browser.contexts == []
    # A browser that is already gone has nothing left to close, and says nothing.
    browser.connected = False
    H.close_new_contexts(browser, ())


def test_stopping_the_driver_closes_the_browser_first_and_is_safe_twice():
    browser, driver = FakeBrowser(), FakeDriver()
    held = {"pw": driver, "browser": browser}
    H.stop_driver(held)
    assert browser.closed == 1 and driver.stopped == 1 and held == {}
    H.stop_driver(held)
    assert browser.closed == 1 and driver.stopped == 1


def test_the_harness_starts_nothing_until_a_test_asks_for_the_browser():
    """A worker that runs no browser test never starts Node: importing the harness imports no
    Playwright, and only `desk_browser` starts the driver."""
    probe = ("import sys; sys.path.insert(0, {!r}); import desk_harness; "
             "print(sorted(m for m in sys.modules if m.startswith('playwright')))"
             ).format(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "[]", (out.stdout, out.stderr)
    src = open(H.__file__, encoding="utf-8").read()
    body = src.split("def desk_browser(", 1)[1].split("\n@pytest.fixture", 1)[0]
    assert "start_driver(_desk_driver)" in body
    assert src.count("start_driver(_desk_driver)") == 1, "only desk_browser starts the driver"


def test_the_desk_fixture_serves_the_page_and_stops(fleet_home, desk_server):
    with urllib.request.urlopen(desk_server.url(), timeout=10) as answer:
        assert answer.status == 200
    assert desk_server.url("&w=side").endswith(f"/?t={desk_server.token}&w=side")
    assert desk_server.base == f"http://127.0.0.1:{desk_server.port}"
