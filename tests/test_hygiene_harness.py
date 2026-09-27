"""No test starts its own Playwright (#303): every browser test is on the desk harness.

tests/desk_harness.py starts one driver and one Chromium per worker (#299). A test that starts a
Playwright driver of its own beside it cannot run while the shared driver is up in its thread, and it
pays for a Node process and a Chromium of its own. So under `tests/` only the harness may call
`sync_playwright`, and only the harness launches Chromium with `launch_chromium` (defined there and
re-exported by tests/test_fleet_desk_browser.py).

The needles are built by concatenation, so this file matches neither its own scan nor a plain
`git grep`.
"""
from __future__ import annotations
import os

TESTS = os.path.dirname(os.path.abspath(__file__))

#: The driver: only the harness starts one.
DRIVER = "sync_" + "playwright("
#: The launcher: only the harness calls it (its definition is there too).
LAUNCH = "launch_" + "chromium("

#: Where each needle may appear, as paths relative to `tests/`.
ALLOWED = {
    DRIVER: {"desk_harness.py"},
    LAUNCH: {"desk_harness.py", "test_fleet_desk_browser.py"},
}

WHERE_TO = "use `desk_server`/`new_desk_page` from tests/desk_harness.py"


def offences(rel: str, source: str) -> list[str]:
    """`path:line: needle` for every needle in `source` (the file `rel`, relative to tests/) that is
    not allowed there."""
    found = []
    for number, line in enumerate(source.splitlines(), 1):
        for needle, allowed in ALLOWED.items():
            if needle in line and rel not in allowed:
                found.append(f"tests/{rel}:{number}: {needle}")
    return found


def scan(root: str = TESTS) -> list[str]:
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                with open(path, encoding="utf-8") as f:
                    found += offences(rel, f.read())
    return found


def test_no_test_starts_its_own_playwright_or_chromium():
    found = scan()
    assert not found, f"{WHERE_TO}; these start their own:\n" + "\n".join(found)


def test_the_scan_finds_a_driver_and_a_launch_outside_the_harness():
    """The scan on a synthetic source: what a pre-harness browser test held is found, in a test file
    and in a regression, and the same text in the harness is not."""
    source = "\n".join([
        "def test_old_style(fleet_home):",
        "    with " + DRIVER + ") as p:",
        "        browser = " + LAUNCH + "p)",
    ])
    assert offences("test_fleet_old.py", source) == [
        "tests/test_fleet_old.py:2: " + DRIVER, "tests/test_fleet_old.py:3: " + LAUNCH]
    assert offences("regressions/test_20260101_any_old.py", source) == [
        "tests/regressions/test_20260101_any_old.py:2: " + DRIVER,
        "tests/regressions/test_20260101_any_old.py:3: " + LAUNCH]
    assert offences("desk_harness.py", source) == []
    assert offences("test_fleet_desk_browser.py", source) == ["tests/test_fleet_desk_browser.py:2: " + DRIVER]
    assert offences("test_fleet_new.py", "def test_new(desk_browser):\n    page = desk_browser.new_page()\n") == []
