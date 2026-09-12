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


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


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
    page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
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
def test_the_pickers_are_behind_one_button_and_still_work(fleet_home, tmp_path):
    """The palette and skin pickers are off the bar and one press away; `Esc` closes the popover
    and puts the keyboard back on the button; clicking anywhere else closes it too."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _repos(tmp_path, "alpha")

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _page(p, port, token)
            assert not page.locator("#theme").is_visible()
            assert not page.locator("#skin").is_visible()

            page.locator("#lookbtn").click()
            assert page.locator("#theme").is_visible() and page.locator("#skin").is_visible()
            assert page.locator("#lookbtn").get_attribute("aria-expanded") == "true"

            # It still drives the page: choosing a skin from inside the popover paints it.
            page.select_option("#skin", "voxel:overworld")
            page.wait_for_function(
                """() => document.body.getAttribute('data-skin') === 'voxel'""", timeout=5000)

            page.keyboard.press("Escape")
            assert not page.locator("#theme").is_visible()
            assert page.evaluate("() => document.activeElement.id") == "lookbtn"
            # ...and the sidebar was not closed in the same keystroke -- it was never open.
            assert page.evaluate("() => document.getElementById('side').hidden")

            page.locator("#lookbtn").click()
            page.locator("#counts").click()                       # anywhere else
            assert not page.locator("#theme").is_visible()
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
            assert groups == ["tiles", "sessions", "the sidebar", "this page"]

            page.keyboard.press("Escape")
            assert not page.locator("#keymap").is_visible()

            page.locator("#keysbtn").click()
            assert page.locator("#keymap").is_visible()
            page.locator("#lookbtn").click()                      # one at a time
            assert not page.locator("#keymap").is_visible()
            assert page.locator("#look").is_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


KEY_LABEL = {"Escape": "Esc", "ArrowLeft": "←", "ArrowRight": "→"}


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
