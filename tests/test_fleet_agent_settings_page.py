"""`/settings?agent=<repo>`: one agent's own settings, drawn and written from the page.

The rendered page and its consequence in `config.json`, not the source: picking an agent shows each
of its values with where it comes from, a change writes under `fleet.agents.<repo>` and nowhere
else, and *also allowed* given to that agent shows up in what it may run -- and not in its
neighbour's.
"""
from __future__ import annotations
import json

import pytest

from agentdata import config as C
from desk_harness import close_pages
from test_fleet_settings_page import _repos, _serve, _settings, fleet_home  # noqa: F401


def _cfg(tmp_path):
    return json.loads((tmp_path / "cfg.json").read_text(encoding="utf-8"))


@pytest.mark.browser
def test_one_agent_gets_its_own_values_and_its_own_permissions(fleet_home, tmp_path, desk_browser):
    _repos(tmp_path, "luna", "uat")
    C.save({"fleet": {"approval_timeout": 600}})
    server, token, port = _serve()
    try:
        browser, page, errors = _settings(desk_browser, port, token)
        page.wait_for_selector("#scope option[value=luna]", state="attached", timeout=10000)

        # every agent: the per-agent rows are all there, and nobody overrides anything yet
        assert page.eval_on_selector_all("#cfgrows .setrow", "els => els.length") > 5
        assert page.eval_on_selector_all("#cfgrows .source", "els => els.length") == 0

        page.select_option("#scope", "luna")
        page.wait_for_function("() => location.search.includes('agent=luna')", timeout=5000)
        drawn = page.evaluate("""() => [...document.querySelectorAll('#cfgrows .setrow')].map(r => [
                r.querySelector('label').title, r.querySelector('.source').textContent])""")
        keys = [k for k, _ in drawn]
        assert "fleet.approval_timeout" in keys and "fleet.copilot.context" in keys
        assert "fleet.port" not in keys, "a fleet-only setting is not offered per agent"
        assert dict(drawn)["fleet.approval_timeout"] == "every agent"

        with page.expect_response(lambda r: r.url.split("?")[0].endswith("/api/settings")
                                  and r.request.method == "POST"):
            page.fill("#cfg-fleet-approval_timeout", "90")
            page.dispatch_event("#cfg-fleet-approval_timeout", "change")
        page.wait_for_function("""() => [...document.querySelectorAll('#cfgrows .setrow')]
                .some(r => r.querySelector('label').title === 'fleet.approval_timeout'
                           && r.querySelector('.source').textContent === 'this agent'
                           && r.querySelector('.inherit'))""", timeout=10000)
        saved = _cfg(tmp_path)["fleet"]
        assert saved["approval_timeout"] == 600, "the fleet's value is untouched"
        assert saved["agents"]["luna"]["fleet.approval_timeout"] == 90

        # also allowed, for luna alone
        page.fill("#list-fleet-copilot-allow_extra-add", "powershell")
        page.press("#list-fleet-copilot-allow_extra-add", "Enter")
        page.wait_for_function("""() => [...document.querySelectorAll('#allowlist li')]
                .some(li => li.querySelector('code').textContent === 'powershell'
                            && li.querySelector('.from').textContent === 'agent'
                            && li.classList.contains('broad'))""", timeout=10000)
        assert _cfg(tmp_path)["fleet"]["agents"]["luna"]["fleet.copilot.allow_extra"] == ["powershell"]

        page.select_option("#scope", "uat")
        page.wait_for_function("() => location.search.includes('agent=uat')", timeout=5000)
        uat = page.eval_on_selector_all("#allowlist li code", "els => els.map(e => e.textContent)")
        assert "powershell" not in uat

        # back on luna, `use every agent's` drops its own window
        page.select_option("#scope", "luna")
        page.click("#cfgrows .setrow:has(label[title='fleet.approval_timeout']) .inherit")
        page.wait_for_function("""() => [...document.querySelectorAll('#cfgrows .setrow')]
                .some(r => r.querySelector('label').title === 'fleet.approval_timeout'
                           && r.querySelector('.source').textContent === 'every agent')""", timeout=10000)
        assert "fleet.approval_timeout" not in _cfg(tmp_path)["fleet"]["agents"]["luna"]
        assert not errors, errors
        close_pages(browser)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_refused_pattern_is_said_on_the_box_and_nothing_is_written(fleet_home, tmp_path, desk_browser):
    _repos(tmp_path, "luna")
    server, token, port = _serve()
    try:
        browser, page, errors = _settings(desk_browser, port, token)
        page.wait_for_selector("#list-fleet-copilot-allow_extra-add", timeout=10000)
        before = (tmp_path / "cfg.json").read_bytes() if (tmp_path / "cfg.json").exists() else b""
        page.fill("#list-fleet-copilot-allow_extra-add", "--allow-all")
        page.click("#list-fleet-copilot-allow_extra .addone")
        page.wait_for_function("""() => {
                const b = document.getElementById('list-fleet-copilot-allow_extra-add');
                return b.classList.contains('bad') && b.title.includes('blanket'); }""", timeout=10000)
        after = (tmp_path / "cfg.json").read_bytes() if (tmp_path / "cfg.json").exists() else b""
        assert after == before
        assert not errors, errors
        close_pages(browser)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
