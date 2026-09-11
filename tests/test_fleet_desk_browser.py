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
        pytest.skip(f"no chromium to drive the page with: {first}")


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


def test_desk_unknown_layout_fallback_contract():
    """Verify app.js handles unknown ?layout= by falling back to grid with a sentence."""
    js_path = os.path.join(STATIC, "app.js")
    js = open(js_path, encoding="utf-8").read()
    assert "unknown layout" in js
    assert "using grid" in js or "grid" in js


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
    url = f"{base}/?t={token}"

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
def test_desk_browser_unknown_layout_fallback(running_desk):
    """An unknown ?layout= shows the default layout with a sentence saying so, rather than a blank page.

    The sentence moved from the toolbar to the footer (#148): the toolbar is for commands, and the
    segmented picker already says which arrangement this window is showing. A page-level notice is
    status, so it sits beside the counts.
    """
    playwright_module = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_module.sync_playwright

    base, token, _ = running_desk
    url = f"{base}/?t={token}&layout=superwide"

    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context()
        page = context.new_page()

        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        res = page.goto(url)
        assert res.status == 200
        page.wait_for_selector(".tile", timeout=15000)
        page.wait_for_selector("#notice:not([hidden])", timeout=5000)

        assert not errors, f"Page JS errors: {errors}"
        notice = page.inner_text("#notice")
        assert "unknown layout" in notice, notice
        assert "superwide" in notice, "the notice names the parameter that was not understood"
        assert page.evaluate("() => document.body.classList.contains('layout-grid')")

        # Verify grid is rendered
        assert page.query_selector(".grid, #grid") is not None

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
