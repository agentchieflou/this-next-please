"""The cleanup guide end to end: the map pops it out, it walks the dirty trees one decision at a time,
the recommendation is pre-selected, and nothing changes until *do it* is pressed.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.fleet import fleetmap as M

from test_fleet_cleanup import fleet_home, identity, two  # noqa: F401
from test_fleet_ink import _serve, _stop
from test_fleet_map import row, snap
from test_fleet_tidy import git

READY = "() => !!window.FleetMap && FleetMap.graph !== null"
CARD = "() => !document.getElementById('tidycard').hidden && document.getElementById('tc-repo').textContent"

pytestmark = pytest.mark.usefixtures("identity")


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


def _dirty_graph():
    def dirty(branch):
        return {"git": {"value": {"branch": branch, "dirty": True}}}
    return M.graph(snap(row("luna", polls=dirty("feature/RDSD-1-old")),
                        row("luna-hotfix", polls=dirty("feature/RDSD-2-fresh"))))


@pytest.mark.browser
def test_the_map_pops_out_the_guide_and_it_walks_each_tree(two, browser):
    main, wt = two
    server, token, port = _serve()
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/map?t={token}", wait_until="domcontentloaded")
        page.wait_for_function(READY, timeout=15000)
        page.evaluate("g => FleetMap.draw(g)", json.loads(json.dumps(_dirty_graph())))
        assert page.text_content("#maptidy") == "clean up 2 dirty trees"
        assert page.eval_on_selector_all("#maptree .maptidy:not([hidden])", "els => els.length") == 2

        with page.expect_popup() as popped:
            page.click("#maptree [data-node='c:luna'] > .maptidy")
        guide = popped.value
        guide.on("pageerror", lambda e: errors.append(str(e)))
        assert "/tidy?" in guide.url and "repo=luna" in guide.url
        guide.wait_for_function(CARD, timeout=15000)

        # opened on luna, so luna first; its recommendation is pre-selected and nothing has changed yet
        card = guide.evaluate("""() => ({
            repo: document.getElementById('tc-repo').textContent,
            says: document.getElementById('tc-says').textContent,
            picked: document.querySelector('input[name=tc-choice]:checked').value,
            marked: [...document.querySelectorAll('.tc-opt')].filter(l => !l.querySelector('.tc-rec').hidden)
                       .map(l => l.querySelector('input').value),
            steps: [...document.querySelectorAll('#tidysteps li .ts-repo')].map(e => e.textContent) })""")
        assert card["repo"] == "luna" and card["picked"] == "stash" and card["marked"] == ["stash"], card
        assert "less tech debt" in card["says"] and card["steps"] == ["luna-hotfix", "luna"], card
        assert "edit in luna" in open(os.path.join(main, "a.py"), encoding="utf-8").read()

        guide.click("#tc-apply")
        guide.wait_for_function(f"() => ({CARD})() === 'luna-hotfix'", timeout=15000)
        assert "edit in luna" not in open(os.path.join(main, "a.py"), encoding="utf-8").read()
        assert "cleanup guide" in git(main, "stash", "list")

        # the next tree: commit, with a message of the operator's own
        assert guide.evaluate("() => document.querySelector('input[name=tc-choice]:checked').value") == "commit"
        guide.fill("#tc-message", "fix: RDSD-2 keep the hotfix edit")
        guide.click("#tc-apply")
        guide.wait_for_function("() => !document.getElementById('tidydone').hidden", timeout=15000)
        done = guide.eval_on_selector_all("#td-list li code", "els => els.map(e => e.textContent)")
        assert any(d.startswith("luna: stashed") and "undo: git stash pop" in d for d in done), done
        assert any(d.startswith("luna-hotfix: committed") for d in done), done
        assert git(wt, "log", "-1", "--format=%s").strip() == "fix: RDSD-2 keep the hotfix edit"
        assert git(wt, "status", "--porcelain").strip() == "?? .agent/" or git(wt, "status", "--porcelain") == ""
        assert not errors, errors
        guide.close()
        page.close()
    finally:
        _stop(server)


@pytest.mark.browser
def test_a_tree_that_moved_under_the_guide_is_shown_again_not_acted_on(two, browser):
    main, _ = two
    server, token, port = _serve()
    try:
        page = browser.new_page(viewport={"width": 900, "height": 900})
        page.goto(f"http://127.0.0.1:{port}/tidy?t={token}&repo=luna", wait_until="domcontentloaded")
        page.wait_for_function(f"() => ({CARD})() === 'luna'", timeout=15000)
        with open(os.path.join(main, "b.py"), "a", encoding="utf-8") as f:
            f.write("an edit after the guide looked\n")
        page.click("#tc-apply")
        page.wait_for_function("""() => document.getElementById('tc-result').textContent
                .includes('changed since')""", timeout=15000)
        assert git(main, "stash", "list") == "", "nothing was applied to a tree the guide had not seen"
        page.close()
    finally:
        _stop(server)
