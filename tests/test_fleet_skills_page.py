"""The skills marketplace in a browser (operator request, 2026-10): the page lists what the server
says, the filter narrows it, a row expands to its repositories, and a second draw of the same rows
makes no DOM mutation (docs/desk-components.md, rule 1).

One browser test, deliberately: the browser tier is budgeted, and the fold, the route and the page's
markup are held without a browser in `tests/test_fleet_skills.py`.
"""
from __future__ import annotations

import pytest

from agentdata.fleet import events as E, skills as SK

from desk_harness import close_pages
from desk_waits import record_mutations
from agentdata.fleet import serve as S

from test_fleet_skills import (_call, _marketplace, _result, _serve, _skill, _stop, _three_calls,  # noqa: F401
                               fleet_home, two_dirs)

READY = "() => !!window.FleetSkills && FleetSkills.rows.length > 0"
NAMES = "() => [...document.querySelectorAll('#skillrows .sk')].map(li => li.querySelector('.sk-n').textContent)"


@pytest.mark.browser
def test_the_page_lists_the_skills_filters_expands_a_row_and_an_idle_redraw_writes_nothing(
        fleet_home, tmp_path, two_dirs, desk_browser):
    first, _second = two_dirs
    _skill(first, "quiet", "never called")
    _three_calls(tmp_path)
    E.append("alpha", [_call("alpha", "gone", "c7", ticket="RDSD-9", ts="2026-01-01T00:00:00"),
                       _result("alpha", "c7", True, ticket="RDSD-9", ts="2026-01-01T00:00:01")])
    SK.update("alpha")
    market = _marketplace(tmp_path / "market", {"triage": "sort the inbox", "fresh": "not yet installed"})
    S.act("settings", {"set": [{"key": "fleet.skills.source", "value": market}]})
    SK.catalog()
    server, token, port = _serve()
    try:
        page = desk_browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/skills?t={token}", wait_until="domcontentloaded")
        page.wait_for_function(READY, timeout=15000)

        # every skill, by uses then name: the two used, the missing one, the never-called one, the shadowed copy
        assert page.evaluate(NAMES) == ["triage", "gone", "publish", "quiet", "triage"]
        pills = page.evaluate("""() => [...document.querySelectorAll('#skillrows .sk')].map(li =>
            [...li.querySelectorAll('.sk-pill')].filter(p => !p.hidden).map(p => p.textContent).join(','))""")
        assert pills == ["", "missing", "", "unused", "shadowed"], pills
        row = page.locator("#skillrows .sk").first
        assert row.locator(".sk-uses").text_content() == "2"
        assert row.locator(".sk-okf").text_content() == "1 / 1"
        assert row.locator(".sk-repos").text_content() == "alpha"
        assert row.locator(".sk-last").get_attribute("title") == "2026-10-08T10:00:00"
        line = page.text_content("#skillsline")
        assert line.startswith("3 skills installed, 3 used, 1 never, 1 used but gone"), line
        assert f"/settings?t={token}" in page.get_attribute("#backbtn", "href")

        # the marketplace box: the source, its kind, never synced yet, the two buttons and the door to settings;
        # and what the source offers that is not installed
        box = page.evaluate("""() => ({ src: document.getElementById('sksrc').textContent,
            kind: document.getElementById('sksrckind').textContent, synced: document.getElementById('sksynced').textContent,
            sync: document.getElementById('sksync').disabled, refresh: document.getElementById('skrefresh').disabled,
            settings: document.getElementById('sksettings').getAttribute('href'),
            fresh: [...document.querySelectorAll('#sknewrows li .sk-n')].map(e => e.textContent) })""")
        assert box["src"] == market and box["kind"] == "path" and box["synced"] == "never synced", box
        assert box["sync"] is False and box["refresh"] is False and box["fresh"] == ["fresh"], box
        assert box["settings"].endswith("#cfg-fleet-skills-source") and f"t={token}" in box["settings"], box

        # an idle redraw writes nothing (rule 1), rows open or closed
        seen = record_mutations(page, target="body")
        page.evaluate("() => { FleetSkills.draw(); FleetSkills.draw(); }")
        assert seen.stop().count() == 0, seen.records()

        # a row expands to its repositories and tickets, and a redraw of that writes nothing either
        page.click("#skillrows .sk:first-child .sk-row")
        page.wait_for_function("() => document.querySelector('#skillrows .sk:first-child').classList.contains('is-open')",
                               timeout=15000)
        assert page.get_attribute("#skillrows .sk:first-child .sk-row", "aria-expanded") == "true"
        repos = page.eval_on_selector_all("#skillrows .sk:first-child .sk-repolist li",
                                          "els => els.map(e => e.textContent)")
        assert len(repos) == 1 and repos[0].startswith("alpha 2 uses "), repos
        assert page.text_content("#skillrows .sk:first-child .sk-tickets") == "tickets: RDSD-2, RDSD-1"
        assert "2 by fleet agents, 0 in your own Copilot sessions" in page.text_content("#skillrows .sk:first-child .sk-facts")
        seen = record_mutations(page, target="body")
        page.evaluate("() => { FleetSkills.draw(); FleetSkills.draw(); }")
        assert seen.stop().count() == 0, seen.records()

        # the filter narrows, the sort flips, and clearing the filter brings every row back
        page.fill("#skillq", "pub")
        page.wait_for_function(f"() => ({NAMES})().length === 1", timeout=15000)
        assert page.evaluate(NAMES) == ["publish"]
        page.fill("#skillq", "")
        page.wait_for_function(f"() => ({NAMES})().length === 5", timeout=15000)
        page.click(".sk-sort[data-sort='name']")
        page.wait_for_function(f"() => ({NAMES})()[0] === 'gone'", timeout=15000)
        assert page.evaluate(NAMES) == ["gone", "publish", "quiet", "triage", "triage"]
        assert page.get_attribute(".sk-sort[data-sort='name']", "aria-sort") == "ascending"
        assert page.get_attribute(".sk-sort[data-sort='uses']", "aria-sort") is None
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        _stop(server)
