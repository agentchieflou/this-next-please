"""The desk harness's own rules (#299), without a browser: `tests/desk_harness.py`.

Decision 13 keeps the browser tier's count where it is, so the harness's browser checks fold into
`test_fleet_desk_browser.py::test_desk_browser_layouts_and_sync` (a context per page, reduced
motion, `COUNT_FETCHES`), and what can be told without Chromium is told here, with stand-ins for
the driver and the browser: the driver starts under the real environment and only once, a browser
a test closed is launched again, a test's contexts are closed and no one else's, and the desk
fixture serves and stops. (#303 took out the tests of a browser test off the harness: there is none
left, and `tests/test_hygiene_harness.py` keeps it so.)

The CPU throttle (#307): where its rate comes from, and that a page is throttled again when its main
frame navigates. Whether Chromium really runs slower is a verdict on real timings, so that check
folds into `test_fleet_ink.py::test_a_gesture_keeps_its_budget_while_the_ink_draws` (measured).
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


class FakeChromium:
    """`p.chromium` for `launch_chromium`: records every launch's keyword arguments."""

    def __init__(self):
        self.launches: list[dict] = []

    def launch(self, **kwargs):
        self.launches.append(kwargs)
        return FakeBrowser()


def test_every_chromium_is_launched_without_windows_tcp_port_randomization():
    """#603: Chromium 139+ sets SO_RANDOMIZE_PORT on every outbound socket on Windows, and a random
    local port that collides fails the connect with WSAENOBUFS -- `net::ERR_NO_BUFFER_SPACE` on a
    desk's page or one of its modules, about one page load in 2,500 on the runner, and none in
    16,912 with the feature off. The shared browser is launched with it off; a test's own switches
    (`desk_chromium_with`) keep theirs and gain it, and a test's own `--disable-features` is extended,
    since Chromium reads only the last one."""
    held = {"pw": type("P", (), {"chromium": FakeChromium()})()}
    H.ensure_browser(held)
    assert held["pw"].chromium.launches == [
        {"headless": True, "args": ["--disable-features=TcpPortRandomizationWin"]}]
    assert H._with_port_randomization_off(("--enable-blink-features=CanvasDrawElement",)) == [
        "--enable-blink-features=CanvasDrawElement", "--disable-features=TcpPortRandomizationWin"]
    assert H._with_port_randomization_off(("--disable-features=Foo",)) == [
        "--disable-features=Foo,TcpPortRandomizationWin"]


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


# ------------------------------------------------------------------ the CPU throttle (#307)


def test_the_throttle_rate_is_the_option_then_the_environment_then_none():
    """`--desk-cpu-throttle`, else `AGENTDATA_DESK_THROTTLE`, else 1; under 1, or not a number, is a
    usage error rather than a run that quietly measures nothing."""
    env = H.THROTTLE_ENV
    assert env == "AGENTDATA_DESK_THROTTLE"
    assert H.throttle_rate(None, {}) == 1.0
    assert H.throttle_rate(None, {env: " "}) == 1.0
    assert H.throttle_rate(None, {env: "2.5"}) == 2.5
    assert H.throttle_rate(4.0, {env: "2"}) == 4.0
    assert H.throttle_rate(1.0, {}) == 1.0
    for option, environ in ((0.5, {}), (None, {env: "0"}), (None, {env: "fast"})):
        with pytest.raises(pytest.UsageError):
            H.throttle_rate(option, environ)


class CdpSession:
    def __init__(self, sent):
        self.sent = sent

    def send(self, method, params):
        self.sent.append((method, params))

    def detach(self):
        self.sent.append(("detach", None))


class ThrottledContext:
    def __init__(self):
        self.sent: list = []
        self.sessions = 0
        self.kwargs: dict = {}

    def new_page(self):
        self.page = ThrottledPage(self)
        return self.page

    def new_cdp_session(self, page):
        assert page is self.page
        self.sessions += 1
        return CdpSession(self.sent)


class ThrottledPage:
    def __init__(self, context):
        self.context = context
        self.handlers: dict = {}
        self.main_frame = type("Frame", (), {"parent_frame": None})()

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers[event].remove(handler)

    def add_init_script(self, script):
        pass

    def navigate(self, frame):
        for handler in self.handlers.get("framenavigated", []):
            handler(frame)


class ThrottledBrowser:
    def __init__(self):
        self.context = ThrottledContext()

    def new_context(self, **kwargs):
        self.context.kwargs = kwargs
        return self.context


def test_a_throttled_page_is_throttled_again_whenever_its_main_frame_navigates(monkeypatch):
    """`desk_page` sends `Emulation.setCPUThrottlingRate` when the rate is over 1, and again on each
    navigation of the main frame (a new site is a new renderer process), not of a frame inside it.
    At the default rate it opens no CDP session at all."""
    rate = ("Emulation.setCPUThrottlingRate", {"rate": 4.0})
    browser = ThrottledBrowser()
    page = H.desk_page(browser, throttle=4)
    assert browser.context.sessions == 1 and browser.context.sent == [rate]
    page.navigate(page.main_frame)
    assert browser.context.sent == [rate, rate]
    page.navigate(type("Frame", (), {"parent_frame": page.main_frame})())
    assert browser.context.sent == [rate, rate], "a subframe's navigation is not the page's"
    assert browser.context.kwargs == {"viewport": {"width": 1400, "height": 900},
                                      "reduced_motion": "no-preference"}

    monkeypatch.setitem(H.THROTTLE, "rate", 1.0)
    plain = ThrottledBrowser()
    H.desk_page(plain)
    assert plain.context.sessions == 0 and plain.context.sent == []

    monkeypatch.setitem(H.THROTTLE, "rate", 2.0)
    slowed = ThrottledBrowser()
    H.desk_page(slowed)
    assert slowed.context.sent == [("Emulation.setCPUThrottlingRate", {"rate": 2.0})]
    unslowed = ThrottledBrowser()
    H.desk_page(unslowed, throttle=1)
    assert unslowed.context.sessions == 0, "an explicit rate of 1 overrides the option"


def test_a_throttle_that_slows_nothing_is_refused_once_per_process(monkeypatch):
    """#307: on a host where CDP throttling has no effect (Windows on an AMD EPYC 9V45 ran the loop
    1.04-1.23x slower at rate 4), `--desk-cpu-throttle` fails the tests rather than run them
    unthrottled. The slowdown is the median throttled run over the quickest unthrottled one, it is
    measured once per process, and a throttle that works (3.5x and more on every other runner) passes."""
    assert H.throttle_ratio({1: [30.0, 25.0, 40.0], 4: [110.0, 100.0, 400.0]}) == 110.0 / 25.0
    assert H.throttle_refusal(4.5, 4) is None
    assert H.throttle_refusal(H.THROTTLE_TAKES_EFFECT, 4) is None
    refusal = H.throttle_refusal(1.07, 3)
    assert refusal and "--desk-cpu-throttle=3 would slow nothing here" in refusal and "1.07x" in refusal
    assert "stress_one.py" in refusal

    measured = []
    monkeypatch.setattr(H, "throttle_effect", lambda browser: measured.append(browser) or 1.07)
    held: dict = {}
    for _ in range(2):
        with pytest.raises(pytest.fail.Exception, match="would slow nothing here"):
            H.check_throttle(held, "browser", 4)
    assert measured == ["browser"], "measured once, refused every time"

    monkeypatch.setattr(H, "throttle_effect", lambda browser: 4.6)
    H.check_throttle({}, "browser", 4)
    assert H.cpu_name().strip()


def test_a_throttle_released_sets_the_page_back_and_stays_released():
    """`throttle_page` returns `release()` (#304's settle check throttles for a while): it sends rate 1,
    stops re-sending the rate on a navigation, and detaches the session."""
    browser = ThrottledBrowser()
    page = browser.new_context().new_page()
    release = H.throttle_page(page, 4)
    release()
    page.navigate(page.main_frame)
    assert browser.context.sent == [("Emulation.setCPUThrottlingRate", {"rate": 4}),
                                    ("Emulation.setCPUThrottlingRate", {"rate": 1}), ("detach", None)]
