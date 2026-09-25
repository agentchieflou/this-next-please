"""2026-09-23, the desk in Chromium with any skin but glass: an idle desk was never idle.

Symptom:

    AssertionError: an idle legal pad wrote to the page: {'n': 56, 'seen': ['attributes data-theme
    HTML', 'attributes data-skin BODY', 'attributes data-skin-variant BODY', 'attributes
    data-waiting LINK', 'attributes data-waiting LINK', ...], 'renders': 10}

Seen by the legal pad's idle test (#251), and true of farmstead and voxel before it. Two writers:

* every `/api/fleet` applies the palette and the skin again, and `applyTheme` and `applySkin` wrote
  `data-theme`, `data-skin` and `data-skin-variant` with `setAttribute` -- a write of the same word
  is still a mutation, and the ink layer, which follows those attributes, drew a frame for each;
* `startGround` retries once when a skin's stylesheet arrives after it, for the glass ground -- but
  for every other skin there is never a ground to find, so the retry armed the next one and wrote
  `data-waiting` on the skin's `<link>` every 150ms for the life of the page.

Nobody saw it because no idle test ran with a skin chosen. Both now write only what changed.

Issue: https://github.com/agentchieflou/this-next-please/issues/251
"""
from __future__ import annotations

import pytest

from test_fleet_desk_browser import launch_chromium
from test_fleet_ink import (IDLE_LOOP, _desk_of, _open, _serve, _stop,  # noqa: F401
                            fleet_home)


@pytest.mark.browser
@pytest.mark.parametrize("skin", ["farmstead", "legalpad"])
def test_a_skinned_desk_at_rest_writes_nothing(fleet_home, tmp_path, skin):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path)
    (fleet_home.parent / "cfg.json").write_text('{"theme": {"skin": "%s"}}' % skin, encoding="utf-8")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page, errors, _ = _open(browser, port, token, count=True)
            family = skin.split(":")[0]
            page.wait_for_function(f"""() => document.body.dataset.skin === '{family}'
              && !!document.head.querySelector('link[data-skin]').sheet""", timeout=15000)
            count = page.evaluate(IDLE_LOOP)
            # And with nothing asked of it at all, for longer than the retry's 150ms.
            quiet = page.evaluate("""async () => { let n = 0;
              const obs = new MutationObserver(rs => { n += rs.length; });
              obs.observe(document.documentElement, { subtree: true, attributes: true, childList: true });
              await new Promise(d => setTimeout(d, 700));
              obs.disconnect();
              return n; }""")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert count["n"] == 0, f"{skin}: an idle desk wrote to the page: {count}"
    assert quiet == 0, f"{skin}: {quiet} writes in 700ms with nothing happening"
