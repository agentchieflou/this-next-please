from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (_desk_of, _facts, _open, _own_desk_globals, _serve,  # noqa: F401
                            _stop, fleet_home)  # noqa: F401


@pytest.mark.browser
def test_the_settings_round_trip_keeps_the_window_and_the_shell(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    PR.record(_facts(shell="pycharm"))
    _desk_of(tmp_path)
    S.update_window("pycharm", open="alpha", widths={"alpha": 1, "beta": 1})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, extra="&w=pycharm")

            # Model card link check
            page.evaluate("() => openModelCard('alpha')")
            mc_href = page.locator("#mc-all").get_attribute("href")
            assert "w=pycharm" in mc_href, mc_href
            assert mc_href.endswith("#model-alpha"), mc_href

            # Click settings
            page.locator("#setbtn").click()
            page.wait_for_function("() => document.querySelectorAll('#skin option').length > 3", timeout=15000)

            # Click back
            page.locator("#backbtn").click()
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                     && !document.body.classList.contains('is-stale')""", timeout=15000)

            info = page.evaluate("""() => ({
                search: location.search,
                shell: document.body.dataset.inkShell,
                inkEnabled: window.Ink && window.Ink.enabled,
                inkOff: document.body.classList.contains('ink-off'),
                wName: typeof W_NAME !== 'undefined' ? W_NAME : '',
                localW: localStorage.getItem('w'),
                sessionW: sessionStorage.getItem('w'),
                cookie: document.cookie,
            })""")
            assert "w=pycharm" in info["search"], info
            assert info["shell"] == "pycharm", info
            assert info["inkEnabled"] is True, info
            assert not info["inkOff"], info
            assert info["wName"] == "pycharm", info
            # w is not stored anywhere
            assert info["localW"] is None, info
            assert info["sessionW"] is None, info
            assert "w=" not in info["cookie"], info
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_only_the_window_the_shell_and_ink_travel(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            # Open desk with ink=off, shell=vscode, x=1
            page, errors, _ = _open(browser, port, token, extra="&ink=off&shell=vscode&x=1")

            set_href = page.locator("#setbtn").get_attribute("href")
            set_params = parse_qs(urlparse(set_href).query)
            assert set_params.get("t") == [token], set_params
            assert set_params.get("ink") == ["off"], set_params
            assert set_params.get("shell") == ["vscode"], set_params
            assert "x" not in set_params, set_params

            # Navigate to /settings with the same params
            page.goto(set_href, wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelectorAll('#skin option').length > 3", timeout=15000)

            back_href = page.locator("#backbtn").get_attribute("href")
            back_params = parse_qs(urlparse(back_href).query)
            assert back_params.get("t") == [token], back_params
            assert back_params.get("ink") == ["off"], back_params
            assert back_params.get("shell") == ["vscode"], back_params
            assert "x" not in back_params, back_params

            assert not errors, errors
            browser.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_desk_with_no_w_round_trips_to_the_exact_url_and_rehome_preserves_carried_params(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            # 1. Desk opened with no w
            page, errors, _ = _open(browser, port, token)
            set_href = page.locator("#setbtn").get_attribute("href")
            set_parsed = urlparse(set_href)
            assert set_parsed.path == "/settings"
            assert set_parsed.query == f"t={token}"

            page.locator("#setbtn").click()
            page.wait_for_function("() => document.querySelectorAll('#skin option').length > 3", timeout=15000)
            back_href = page.locator("#backbtn").get_attribute("href")
            back_parsed = urlparse(back_href)
            assert back_parsed.path == "/"
            assert back_parsed.query == f"t={token}"

            page.locator("#backbtn").click()
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                     && !document.body.classList.contains('is-stale')""", timeout=15000)
            assert page.evaluate("() => location.search") == f"?t={token}"
            page.close()

            # 2. rehome() test with w, shell, ink
            S.update_window("pycharm", open="alpha", widths={"alpha": 1, "beta": 1})
            page, errors2, _ = _open(browser, port, token, extra="&w=pycharm&shell=pycharm&ink=on")
            page.evaluate("() => rehome()")
            page.wait_for_function(
                """() => document.querySelectorAll('#grid .tile.is-solo').length === 2
                     && !document.body.classList.contains('is-stale')""", timeout=15000)
            search = page.evaluate("() => location.search")
            qs = parse_qs(search.lstrip("?"))
            assert qs.get("w") == ["pycharm"]
            assert qs.get("shell") == ["pycharm"]
            assert qs.get("ink") == ["on"]
            assert "t" in qs
            assert not errors2, errors2

            browser.close()
    finally:
        _stop(server)
