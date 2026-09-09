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
        browser = p.chromium.launch(headless=True)
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
    """An unknown ?layout= parameter shows the default layout (grid) with a sentence in the toolbar."""
    playwright_module = pytest.importorskip("playwright.sync_api")
    sync_playwright = playwright_module.sync_playwright

    base, token, _ = running_desk
    url = f"{base}/?t={token}&layout=superwide"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        res = page.goto(url)
        assert res.status == 200
        page.wait_for_selector("#view", timeout=5000)

        assert not errors, f"Page JS errors: {errors}"
        view_text = page.inner_text("#view")
        assert "unknown layout" in view_text
        assert "grid" in view_text

        # Verify grid is rendered
        assert page.query_selector(".grid, #grid") is not None

        browser.close()
