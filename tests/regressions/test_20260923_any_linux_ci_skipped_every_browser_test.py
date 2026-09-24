"""Linux CI skipped every browser test: the isolated home hid Playwright's browsers.

Symptom: main run 35907338054, ubuntu 3.12, printed `3570 passed, 337 skipped`, and the ownership-demo
step printed `1 skipped in 0.91s` with a 208-byte artifact, while windows 3.14 on the same commit ran
`3792 passed, 82 skipped`. `isolated_home` points `HOME` at a temp dir, Linux Playwright looks for
its browsers under `$HOME/.cache/ms-playwright`, and `launch_chromium` turned the miss into
`no chromium to drive the page with`. Now the real browsers directory is resolved before `HOME`
moves and survives the isolated home as `PLAYWRIGHT_BROWSERS_PATH`, and with
`AGENTDATA_REQUIRE_BROWSER=1` a browser test that skips fails instead.

https://github.com/agentchieflou/this-next-please/issues/296
"""
from __future__ import annotations
import os

import conftest


def test_linux_looks_under_the_home_cache_or_xdg_cache_home():
    assert conftest.playwright_browsers_dir({}, "linux", "/home/u") == \
        os.path.join("/home/u", ".cache", "ms-playwright")
    assert conftest.playwright_browsers_dir({"XDG_CACHE_HOME": "/xdg"}, "linux", "/home/u") == \
        os.path.join("/xdg", "ms-playwright")


def test_macos_looks_under_library_caches():
    assert conftest.playwright_browsers_dir({}, "darwin", "/Users/u") == \
        os.path.join("/Users/u", "Library", "Caches", "ms-playwright")


def test_windows_looks_under_localappdata():
    local = r"C:\Users\u\AppData\Local"
    assert conftest.playwright_browsers_dir({"LOCALAPPDATA": local}, "win32", r"C:\Users\u") == \
        os.path.join(local, "ms-playwright")


def test_a_preset_variable_wins_everywhere():
    env = {"PLAYWRIGHT_BROWSERS_PATH": "/opt/pw", "XDG_CACHE_HOME": "/xdg", "LOCALAPPDATA": "C:/l"}
    for platform in ("linux", "darwin", "win32"):
        assert conftest.playwright_browsers_dir(env, platform, "/home/u") == "/opt/pw"


def test_inside_a_test_the_browsers_survive_the_isolated_home(tmp_path):
    assert os.environ["HOME"].startswith(str(tmp_path)), "HOME is still redirected"
    if conftest.REAL_PLAYWRIGHT_BROWSERS is None:
        return  # a machine with no browsers: nothing to carry over, and the tests skip by name
    seen = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    assert seen == conftest.REAL_PLAYWRIGHT_BROWSERS
    assert not os.path.abspath(seen).startswith(str(tmp_path))


def test_a_browser_skip_fails_only_with_the_marker_a_skip_and_the_variable():
    on = {"AGENTDATA_REQUIRE_BROWSER": "1"}
    assert conftest.browser_skip_is_a_failure(True, True, on) is True
    assert conftest.browser_skip_is_a_failure(False, True, on) is False
    assert conftest.browser_skip_is_a_failure(True, False, on) is False
    assert conftest.browser_skip_is_a_failure(True, True, {}) is False
    for other in ("0", "", "true", "yes"):
        assert conftest.browser_skip_is_a_failure(True, True, {"AGENTDATA_REQUIRE_BROWSER": other}) is False
