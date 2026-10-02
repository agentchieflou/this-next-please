"""The map says which branch each agent is on, and every agent has a way to its chat.

The branch was already in the graph (`checkout.branch`, from the git poll) and only ever reached the
page inside a sentence; it is a chip of its own now, on the checkout and on its agent. *open chat*
lands on the desk with that agent's pane open -- un-hidden if the operator had hidden it -- and, for
a console the fleet opened, also raises that console's own window, which is where its chat is.
"""
from __future__ import annotations
import json
import re

import pytest

from agentdata.fleet import fleetmap as M
from agentdata.fleet import serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_ink import _serve, _stop
from test_fleet_map import fleet_home, row, snap  # noqa: F401

READY = "() => !!window.FleetMap && FleetMap.graph !== null"


def _graph():
    git = {"git": {"value": {"branch": "feature/RDSD-1-tidy", "dirty": True}}}
    return M.graph(snap(row("luna", polls=git, ticket="RDSD-1"),
                        row("uat", console={"pid": 7, "host": "fake"},
                            polls={"git": {"value": {"branch": "main"}}})))


def test_the_graph_carries_each_checkouts_branch_for_its_agent_too():
    g = _graph()
    by = {c["repo"]: c for c in g["checkouts"]}
    assert by["luna"]["branch"] == "feature/RDSD-1-tidy" and by["luna"]["dirty"] is True
    assert by["uat"]["agent"]["kind"] == "console"


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


@pytest.mark.browser
def test_branch_chips_and_open_chat_land_on_the_agents_pane(fleet_home, tmp_path, browser):
    for name in ("luna", "uat"):
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    server, token, port = _serve()
    try:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/map?t={token}&w=side", wait_until="domcontentloaded")
        page.wait_for_function(READY, timeout=15000)
        page.evaluate("g => FleetMap.draw(g)", json.loads(json.dumps(_graph())))

        chips = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#maptree [data-node]')]
            .filter(li => /^[ca]:/.test(li.dataset.node))
            .map(li => { const b = li.querySelector(':scope > .branch');
                         return [li.dataset.node, b.hidden ? null : b.textContent]; }))""")
        assert chips["c:luna"] == "feature/RDSD-1-tidy · uncommitted"
        assert chips["a:luna"] == "feature/RDSD-1-tidy", "the agent says the branch it works on"
        assert chips["c:uat"] == "main"
        chats = page.eval_on_selector_all("#maptree [data-node^='a:'] > .mapchat:not([hidden])",
                                          "els => els.length")
        assert chats == 2

        # a console agent's chat is its own window: raised as well as opened on the desk
        focused = []
        page.route("**/api/focus*", lambda r: (focused.append(json.loads(r.request.post_data or "{}")),
                                               r.fulfill(status=200, content_type="application/json",
                                                         body='{"ok": true}')))
        page.click("#maptree [data-node='a:uat'] > .mapchat")
        page.wait_for_url(re.compile(r"#tile=uat$"), wait_until="commit", timeout=10000)
        assert focused == [{"repo": "uat"}]
        assert S.desk_state()["windows"]["side"]["open"] == "uat"

        page.goto(f"http://127.0.0.1:{port}/map?t={token}&w=side", wait_until="domcontentloaded")
        page.wait_for_function(READY, timeout=15000)
        page.evaluate("g => FleetMap.draw(g)", json.loads(json.dumps(_graph())))
        page.click("#maptree [data-node='a:luna'] > .mapchat")
        page.wait_for_url(re.compile(r"#tile=luna$"), wait_until="commit", timeout=10000)
        assert len(focused) == 1, "a headless agent has no window to raise"
        assert S.desk_state()["windows"]["side"]["open"] == "luna"
        assert not errors, errors
        page.close()
    finally:
        _stop(server)
