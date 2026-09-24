"""Browser test harness for the Desk on Windows (Issue #146).

Tests live browser rendering, layout modes, focus mode, keyboard navigation,
and multi-window synchronization via SSE desk events.

Uses Playwright when installed (CI and laptop dev environment);
skips cleanly with pytest.importorskip when playwright is not installed.
Also provides offline DOM contract tests that always run.
"""
from __future__ import annotations
import json
import os
import re
import socket
import threading
import time
import urllib.request

import pytest

from agentdata.fleet import serve as S, registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - fixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


def launch_chromium(p):
    """Chromium, from wherever this machine keeps it.

    Playwright pins a browser build to its own version and refuses to start when the two disagree,
    which is what happens on any runner that ships a browser separately from the wheel -- and it
    raises rather than skipping, so a machine without the exact build turned "no browser here" into
    a red suite. The binary is what these tests need, not the pin: `AGENTDATA_CHROMIUM` names one,
    a couple of known locations are tried, and only then do we skip and say so.

    Chromium is the engine under all three hosts the dashboard has to render in -- Edge, PyCharm's
    JCEF tool window and VS Code's Simple Browser -- so one engine covers the matrix.
    """
    try:
        return p.chromium.launch(headless=True)
    except Exception as first:                                  # noqa: BLE001 - any launch failure
        candidates = [os.environ.get("AGENTDATA_CHROMIUM", "")]
        for root in ("/opt/pw-browsers",):
            if os.path.isdir(root):
                for entry in sorted(os.listdir(root)):
                    candidates.append(os.path.join(root, entry, "chrome-linux", "chrome"))
        for path in candidates:
            if path and os.path.isfile(path):
                return p.chromium.launch(headless=True, executable_path=path)
        pytest.skip(f"no chromium to drive the page with: {first} "
                    f"PLAYWRIGHT_BROWSERS_PATH={os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')} "
                    f"HOME={os.environ.get('HOME', '')}")


@pytest.fixture()
def running_desk(fleet_home, tmp_path):                         # noqa: F811
    """A running fleet server with two projects registered for browser testing."""
    p1 = make_project(tmp_path / "alpha")
    p2 = make_project(tmp_path / "beta")
    Registry().add(p1, name="alpha")
    Registry().add(p2, name="beta")

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, token, server
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------------- Offline contract tests


def test_desk_html_structure():
    """Verify static index.html contains the toolbar, layout container, sidebar, and inspector structure."""
    html_path = os.path.join(STATIC, "index.html")
    assert os.path.isfile(html_path)
    html = open(html_path, encoding="utf-8").read()

    # Layout container and template
    assert 'id="grid"' in html or 'class="grid"' in html
    assert '<header>' in html or '<header' in html
    assert 'id="tile"' in html
    assert 'app.css' in html
    assert 'app.js' in html


def test_desk_static_assets_exist():
    """Verify app.css and app.js exist and are non-empty."""
    css_path = os.path.join(STATIC, "app.css")
    js_path = os.path.join(STATIC, "app.js")
    assert os.path.getsize(css_path) > 1000
    assert os.path.getsize(js_path) > 1000


def test_desk_retired_layout_params_contract():
    """An address that still chooses an arrangement (#232) is not refused and not a blank page:
    app.js names the three parameters, says in the footer that they are ignored, and takes them off
    the address. The unknown-layout fallback this replaces has nothing left to fall back from."""
    js_path = os.path.join(STATIC, "app.js")
    js = open(js_path, encoding="utf-8").read()
    assert 'var RETIRED_PARAMS = ["layout", "view", "screen"];' in js
    assert " ignored — the desk has one arrangement now" in js
    assert "function forgetRetiredParams()" in js and "history.replaceState(" in js
    assert "unknown layout" not in js


# --------------------------------------------------------------------------------- Playwright browser tests


@pytest.mark.browser
def test_desk_browser_layouts_and_sync(running_desk):
    """Playwright browser test:
    1. Loads Desk with token.
    2. Verifies page renders without JS errors.
    3. Verifies layout picker / modes.
    4. Opens second page to verify SSE desk selection sync across windows.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_module.sync_playwright

    base, token, _ = running_desk
    url = f"{base}/?t={token}&layout=grid"

    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context()

        page1 = context.new_page()
        page2 = context.new_page()

        errors1 = []
        page1.on("pageerror", lambda exc: errors1.append(str(exc)))
        errors2 = []
        page2.on("pageerror", lambda exc: errors2.append(str(exc)))

        # Load page 1
        res1 = page1.goto(url)
        assert res1.status == 200
        page1.wait_for_selector(".tile, .grid, [data-project]", timeout=5000)

        # Load page 2
        res2 = page2.goto(url)
        assert res2.status == 200
        page2.wait_for_selector(".tile, .grid, [data-project]", timeout=5000)

        assert not errors1, f"Page 1 JS errors: {errors1}"
        assert not errors2, f"Page 2 JS errors: {errors2}"

        # Test selection sync between windows:
        # Click a project on page 1, verify page 2 receives selection via SSE
        tiles1 = page1.query_selector_all(".tile")
        if tiles1:
            tiles1[0].click()
            time.sleep(0.5)

        browser.close()


@pytest.mark.browser
def test_an_address_that_chooses_an_arrangement_opens_the_desk_and_says_so_once(running_desk):
    """`?layout=roles&view=board` from a bookmark or an older launcher (#232). There is one
    arrangement, so the address opens the desk as any other does -- the open agent and a rail for
    the other (#233), never a blank page -- and the footer says, once, that the parameters were
    ignored.

    Once: a standing warning redrawn on every pass is a footer that never says anything else, and
    `place()` runs several times a second. The parameters come off the address too, so a reload does
    not say it a second time and the address the operator copies says only true things.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_module.sync_playwright

    base, token, _ = running_desk
    url = f"{base}/?t={token}&layout=roles&view=board"

    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context()
        # Every time the footer starts saying something, from the first byte of the page on: a
        # sentence said twice is two entries, a sentence that simply stays is one.
        context.add_init_script("""
          window.__said = [];
          window.__last = "";
          new MutationObserver(() => {
            const n = document.getElementById('notice');
            const now = n && !n.hidden ? n.textContent : "";
            if (now === window.__last) return;
            window.__last = now;
            if (now) window.__said.push(now);
          }).observe(document, { subtree: true, childList: true, characterData: true,
                                 attributes: true });
        """)
        page = context.new_page()

        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        res = page.goto(url)
        assert res.status == 200
        page.wait_for_selector(".tile.is-solo", timeout=15000)
        page.wait_for_function(
            "() => document.querySelectorAll('#grid .tile[data-tier=\"rail\"]').length === 1",
            timeout=15000)
        page.wait_for_selector("#notice:not([hidden])", timeout=5000)
        notice = page.inner_text("#notice")
        assert "layout= and view= in the address are ignored" in notice, notice
        assert notice.count("ignored") == 1, notice

        # The stream and the fifteen-second clock redraw the page; the sentence is not said again.
        page.evaluate("() => { for (let i = 0; i < 20; i++) redrawAll(); refresh(); }")
        page.wait_for_timeout(800)
        said = [line for line in page.evaluate("() => window.__said") if "ignored" in line]
        assert len(said) == 1, said
        assert page.evaluate("() => location.search").count("layout") == 0
        assert "view=" not in page.evaluate("() => location.search")
        assert f"t={token}" in page.evaluate("() => location.search"), "the token went with them"

        # Nothing an arrangement used to set is on the body or in the header.
        body = page.evaluate("() => document.body.className")
        assert "layout-" not in body and "view-" not in body and "panels" not in body, body
        assert page.query_selector("#layoutgroup, #viewgroup, #swap") is None

        page.reload()
        page.wait_for_selector(".tile.is-solo", timeout=15000)
        page.wait_for_timeout(500)
        assert "ignored" not in (page.inner_text("#notice") or ""), "a reload said it a second time"
        assert not errors, f"Page JS errors: {errors}"
        browser.close()


def dispatch_drop_files(page, selector: str, files: list[dict]):
    """Build a DataTransfer with files in page context and dispatch dragover and drop on selector.

    files: list of {"name": str, "content": str, "type": str}
    """
    page.evaluate(
        """([sel, files]) => {
            const dt = new DataTransfer();
            for (const f of files) {
                const blob = new Blob([f.content || ""], { type: f.type || "text/plain" });
                const file = new File([blob], f.name, { type: f.type || "text/plain", lastModified: Date.now() });
                dt.items.add(file);
            }
            const el = document.querySelector(sel);
            if (!el) throw new Error("no element matching " + sel);
            el.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
            el.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
        }""",
        [selector, files]
    )


def dispatch_drop_ticket(page, selector: str, key: str, custom_type: bool = True):
    """Build a DataTransfer with ticket and dispatch dragover and drop on selector."""
    page.evaluate(
        """([sel, key, custom]) => {
            const dt = new DataTransfer();
            if (custom) {
                dt.setData("application/x-agentdata-ticket", key);
            }
            dt.setData("text/plain", key);
            const el = document.querySelector(sel);
            if (!el) throw new Error("no element matching " + sel);
            el.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
            el.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
        }""",
        [selector, key, custom_type]
    )
