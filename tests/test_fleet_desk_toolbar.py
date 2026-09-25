"""Sitting: A — the toolbar, said less (issue #180).

Eleven controls in one bar that wrapped to two rows, a fourteen-item key map that wrapped to two
lines under the grid, and a hide toggle that painted as a blank or black square because it was left
out of the two rules that give the pin and width buttons their stroke. HIG *Toolbars*: commands for
the current context on the bar; a choice that rarely changes behind one button.

Same rules as `tests/test_fleet_desk_regressions.py`: assert on the rendered page and on the
consequence, not on the source text -- except the one test that compares two source files, which is
how the markup and the script are kept in step everywhere else on this page.
"""
from __future__ import annotations
import os
import re
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S, skins as K
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _repos(tmp_path, *names):
    for name in names:
        path = make_project(tmp_path / name, ticket="RDSD-1")
        Registry().add(path, name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
                        E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-1")])


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _looks():
    """`none` and every skin variant: the set of chromes the page can be drawn in."""
    return ["none"] + [f"{skin}:{variant}" for skin, variant, _spec in K.every_variant()]


def _page(p, port, token, width=1280, height=800):
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
    page.wait_for_selector(".tile:visible", timeout=15000)
    return browser, page, errors


def _wear(page, look):
    page.evaluate("(name) => post('theme', { skin: name })", look)
    page.wait_for_timeout(450)


# ------------------------------------------------------------------------------- the one row


@pytest.mark.browser
def test_the_toolbar_is_one_row_at_1280_in_every_look(fleet_home, tmp_path):
    """Acceptance criterion. The header's height is measured against the tallest control on it:
    a wrapped bar is at least two of those plus the gap."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha", "beta")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            for look in _looks():
                _wear(page, look)
                got = page.evaluate("""() => {
                    const h = document.querySelector('header');
                    const kids = Array.from(h.children).filter(c => !c.hidden && c.offsetHeight > 0);
                    return { header: h.offsetHeight, tallest: Math.max(...kids.map(c => c.offsetHeight)) };
                }""")
                assert got["header"] < got["tallest"] * 2, f"{look}: the toolbar wrapped: {got}"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# ----------------------------------------------------------------------------- the popovers


@pytest.mark.browser
def test_the_settings_control_is_a_link_to_its_own_page(fleet_home, tmp_path):
    """The operator's report: *the settings button isn't functional at all.*

    It was a popover holding two pickers, and it became a page -- so what is asserted here is that
    the control leaves the desk rather than opening something. The href cannot be static: the run
    token lives in the query string and `_authorized` reads it from nowhere else, so a plain
    `href="/settings"` is a 403 that looks exactly like the dead button that was reported.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            link = page.locator("#setbtn")
            href = link.get_attribute("href")
            assert href and "/settings" in href, f"the settings control goes nowhere: {href!r}"
            assert f"t={token}" in href, "the link carries no token and would 403"
            assert page.locator("#settings").count() == 0, "the popover is still on the desk"

            link.click()
            page.wait_for_url(re.compile(r"/settings"), timeout=10000)
            page.wait_for_selector("#theme", timeout=10000)
            assert page.locator("#skin").is_visible(), "the pickers did not arrive with the page"

            # #407: the map is the same kind of door, and it must keep the window the desk was
            # opened in -- a map reached from PyCharm's tool window that forgets `shell` reads the
            # `browser` probe. Folded in here rather than a test of its own: the slow tier is capped.
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid&w=pycharm&shell=pycharm",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            assert page.locator("#mapbtn").count() == 1, "the desk has no map control"
            href = page.locator("#mapbtn").get_attribute("href")
            assert href and "/map" in href, f"the map control goes nowhere: {href!r}"
            for part in (f"t={token}", "w=pycharm", "shell=pycharm"):
                assert part in href, f"the map link lost {part}: {href!r}"

            page.locator("#mapbtn").click()
            page.wait_for_url(re.compile(r"/map\?"), timeout=10000)
            page.wait_for_selector("#maptree [data-node]", timeout=10000)
            assert page.evaluate("document.body.dataset.inkShell") == "pycharm", "the map forgot the shell"

            # `g` typed into the search box is text; `g` on the desk itself is the door.
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)
            page.locator("#find").press("g")
            assert page.locator("#find").input_value() == "g", "g in the search box was not text"
            assert "/map" not in page.url, "g typed into the search box left the desk"
            page.locator("#find").blur()
            page.keyboard.press("g")
            page.wait_for_url(re.compile(r"/map\?"), timeout=10000)
            page.wait_for_selector("#maptree [data-node]", timeout=10000)
            assert "shell=pycharm" in page.url, page.url
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_the_key_map_is_behind_a_question_mark_and_the_footer_keeps_what_changes(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            footer = page.locator("footer")
            assert "1 agents" in footer.inner_text() or "agent" in footer.inner_text()
            assert not page.locator("#keymap").is_visible()

            page.keyboard.press("?")
            assert page.locator("#keymap").is_visible()
            groups = page.eval_on_selector_all("#keymap .keys-group strong", "els => els.map(e => e.textContent)")
            assert groups == ["the row", "widths", "panes", "sessions", "the sidebar", "this page"]

            page.keyboard.press("Escape")
            assert not page.locator("#keymap").is_visible()

            page.locator("#keysbtn").click()
            assert page.locator("#keymap").is_visible()
            # "One open at a time" used to be shown against the settings popover, which is a page
            # now. Clicking anywhere else says the same thing and does not need a second popover.
            page.locator("#counts").click()
            assert not page.locator("#keymap").is_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


KEY_LABEL = {"Escape": "Esc", "ArrowLeft": "←", "ArrowRight": "→",
             "ArrowUp": "↑", "ArrowDown": "↓"}


def test_every_key_the_script_binds_is_in_the_map():
    """Acceptance criterion. The popover's `<kbd>` set against the keys `app.js` binds, so a
    shortcut added to the script without a line in the map fails here rather than being a secret."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()

    bound = set(re.findall(r'e\.key === "([^"]+)"', js))
    if re.search(r"/\^\[1-9\]\$/\.test\(e\.key\)", js):
        bound |= {"1", "9"}
    assert bound, "the script binds no keys?"

    keymap = re.search(r'id="keymap".*?</footer>', html, re.S)
    assert keymap, "the key map is not in the footer"
    shown = set(re.findall(r"<kbd>([^<]+)</kbd>", keymap.group(0)))

    missing = sorted(KEY_LABEL.get(k, k) for k in bound if KEY_LABEL.get(k, k) not in shown)
    assert missing == [], f"bound in app.js and not in the key map: {missing}"


# ----------------------------------------------------------------------------- the hide icon


@pytest.mark.browser
def test_the_hide_toggle_has_the_stroke_the_pin_has_in_every_look(fleet_home, tmp_path):
    """Acceptance criterion. #173's eye icon painted as a blank or black square in every theme
    because `.hidetoggle` was missing from the two rules that give the pin and width buttons their
    stroke. Compared with the pin rather than with a literal, so a skin that recolours both is fine
    and one that recolours one is not."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            for look in _looks():
                _wear(page, look)
                got = page.evaluate("""() => {
                    const pin = getComputedStyle(document.querySelector('.tile .pintoggle svg'));
                    const eye = getComputedStyle(document.querySelector('.tile .hidetoggle svg'));
                    return { pin: [pin.stroke, pin.fill, pin.width], eye: [eye.stroke, eye.fill, eye.width] };
                }""")
                assert got["eye"] == got["pin"], f"{look}: {got}"
                assert got["eye"][1] == "none", f"{look}: the eye is filled, not stroked: {got}"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def test_a_palette_the_config_names_but_no_longer_exists_still_shows_something():
    """A theme removed from the package leaves a saved name that matches no option. A `select` set
    to a value it does not have shows *nothing* — not the old name, not the default — so the
    operator can neither see what is on nor tell that anything is wrong."""
    script = open(os.path.join(STATIC, "settings.js"), encoding="utf-8").read()
    assert "if (sel && sel.selectedIndex < 0) sel.selectedIndex = 0;" in script
