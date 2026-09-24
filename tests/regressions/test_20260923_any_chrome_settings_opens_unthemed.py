"""2026-09-23, /settings in Chrome: the page opens in the system palette under the chosen skin.

Symptom:

    --bg stayed #f6f7f8 on 3 of 4 loads of /settings with theme.default nfl-browns

and, sampled frame by frame with voxel:nether chosen:

    (83 ms voxel --bg #400000) -> (150 ms voxel, --bg removed)

`/api/themes` answered `current` with names and no css, and `loadThemes()` handed that `undefined`
to `applyTheme`, which reads a falsy css as "no palette" and removes every token. Whenever the
stream's first `theme` frame landed before `/api/themes`, the palette it had just painted was wiped
and stayed wiped until config.json next changed. This forces that order.

Issue: https://github.com/agentchieflou/this-next-please/issues/346
"""
from __future__ import annotations

import pytest

from agentdata.fleet import serve as S

from test_fleet_ink import _desk_of, _serve, _stop, fleet_home, _own_desk_globals  # noqa: F401
from test_fleet_settings_theme import ORDER, _config, _page, _settings
from test_fleet_theme_switch import browser  # noqa: F401


@pytest.mark.browser
@pytest.mark.parametrize("theme", [{"default": "nfl-browns"}, {"skin": "voxel:nether"}],
                         ids=["palette", "skin"])
def test_settings_keeps_its_palette_when_the_stream_speaks_first(browser, fleet_home, tmp_path, theme):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, **theme)
    want = S.theme_state()["css"]["--bg"]
    server, token, port = _serve()
    try:
        page, errors = _page(browser, ORDER % "stream")
        _settings(page, port, token)
        page.wait_for_function("() => window.__applied === true", timeout=15000)
        bg = page.evaluate("() => document.documentElement.style.getPropertyValue('--bg')")
        assert bg == want, f"--bg is {bg!r} after both answers, not the chosen palette's {want}"
        assert not errors, errors
        page.close()
    finally:
        _stop(server)
