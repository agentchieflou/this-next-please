"""Computed theme tokens in a real browser (Issue #325).

Acceptance criteria:
- Browser, notebook:light and glass:smoke with ?ink=on:
  getComputedStyle(document.querySelector('.runline')).color equals the served --muted
  converted to rgb(r, g, b), and the reply input's ::placeholder colour equals it too.
"""
from __future__ import annotations

import pytest

from agentdata import theme
from agentdata.fleet import skins

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (  # noqa: F401 - fixtures used by name
    _desk_of, _open, _serve, _stop, fleet_home, _own_desk_globals
)


def _hex_to_rgb(hex_str: str) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgb({r}, {g}, {b})"


@pytest.mark.browser
@pytest.mark.parametrize("skin_name", ["notebook:light", "glass:smoke"])
def test_computed_muted_and_placeholder_tokens(fleet_home, tmp_path, skin_name):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path, ("alpha", "beta"))

    # Write skin configuration
    (fleet_home.parent / "cfg.json").write_text(f'{{"theme": {{"skin": "{skin_name}"}}}}', encoding="utf-8")

    skin, variant = skin_name.split(":")
    t = theme.get(skins.SKINS[skin]["variants"][variant]["base"])
    expected_muted = theme.to_css(t)["--muted"]
    expected_rgb = _hex_to_rgb(expected_muted)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, extra="&ink=on", panes=2)

            page.wait_for_function(
                """() => !!document.querySelector('.runline') && !!document.querySelector('input.say')""",
                timeout=10000,
            )
            page.wait_for_function(
                f"""() => getComputedStyle(document.querySelector('.runline')).color === '{expected_rgb}'""",
                timeout=10000,
            )
            page.wait_for_function(
                f"""() => getComputedStyle(document.querySelector('input.say'), '::placeholder').color === '{expected_rgb}'""",
                timeout=10000,
            )

            runline_color = page.evaluate("() => getComputedStyle(document.querySelector('.runline')).color")
            placeholder_color = page.evaluate("() => getComputedStyle(document.querySelector('input.say'), '::placeholder').color")

            assert runline_color == expected_rgb
            assert placeholder_color == expected_rgb
            assert not errors, errors
            page.close()
            browser.close()
    finally:
        _stop(server)
