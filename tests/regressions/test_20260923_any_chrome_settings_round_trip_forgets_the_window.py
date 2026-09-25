"""2026-09-23, Chrome/Chromium settings round trip drops w, shell, and ink parameters.

Symptom:

    before: {url: ?t=…&w=pycharm, shell: pycharm, probe: hardware, ink: true}
    after : {url: ?t=…,          shell: browser, probe: unmeasured, ink: false, body.ink-off}

The IDE hosts and `ad-fleet open --in edge` open the desk as `/?t=…&w=<host>`.
The links between the desk and /settings are built with `q()`, which carries only `t`,
so the round trip drops `w`, `shell` and `ink`. The desk comes back as window `main`
and the ink gate reads the unmeasured `browser` probe, falling back to CSS ink-off.

Issue: https://github.com/agentchieflou/this-next-please/issues/344
"""
from __future__ import annotations

import pytest

from agentdata.fleet import probe as PR
from agentdata.fleet import serve as S  # noqa: F401
from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (_desk_of, _facts, _open, _serve,  # noqa: F401
                            _stop, fleet_home)  # noqa: F401


@pytest.mark.browser
def test_settings_round_trip_preserves_window_and_shell(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    PR.record(_facts(shell="pycharm"))
    _desk_of(tmp_path)
    S.update_window("pycharm", open="alpha", widths={"alpha": 1, "beta": 1})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, extra="&w=pycharm")
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
            })""")
            assert "w=pycharm" in info["search"], info
            assert info["shell"] == "pycharm", info
            assert info["inkEnabled"] is True, info
            assert not info["inkOff"], info
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
