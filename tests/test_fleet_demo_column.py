"""The column's definition-of-done demo (issue #208), carried over to the row (issue #233).

Five agents on one desk, in the state a real afternoon puts them in: one running, one waiting for a
click, one with a question, one idle, one the operator hid. The column rendered every agent that was
not open as a band; the operator's correction was *each agent is a column -- skinnier agents*
(docs/plan-panes.md §Decisions 3), so the demo renders the row and measures what the operator asked
for, then and now --

* every agent that is not open is a rail beside the open pane, in the row's order, and
* the panes account for the row's width and height, so the page has no dead space in it --

then writes a screenshot per skin variant so the sitting has something to look at without a laptop.
`AGENTDATA_SHOTS=<dir>` says where; without it they go to pytest's own tmp dir and are thrown away,
because a suite that writes into the repository is a suite nobody can run twice.
"""
from __future__ import annotations
import os
import threading

import pytest

from agentdata.fleet import events as E, registry, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

SKINS = ["none", "glass:smoke", "farmstead:daytime", "voxel:overworld"]


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _desk_of_five(tmp_path):
    """The five states a real afternoon actually produces, and nothing invented beyond them."""
    names = ["rdsd-pbi-reporting", "luna", "velocity", "backlog-health", "arl-usage"]
    for name in names:
        Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
        E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-1")])

    # running: a turn is open
    E.append("rdsd-pbi-reporting", [E.event("rdsd-pbi-reporting", "turn_started", {"turn": "1"},
                                            ticket="RDSD-23000")])
    # waiting for a click
    E.append("luna", [E.event("luna", "turn_ended", {"turn": "0"}, ticket="RDSD-118"),
                      E.event("luna", "needs_approval",
                              {"id": "a1", "kind": "jira-transition",
                               "summary": "move RDSD-118 to In Review"}, ticket="RDSD-118")])
    # a question, which a band had room for, a dock chip never did, and a rail says in its label
    E.append("velocity", [
        E.event("velocity", "turn_ended", {"turn": "0"}, ticket="RDSD-902"),
        E.event("velocity", "question_opened",
                {"id": "q1", "blocking": True,
                 "question": "the sprint field is empty on 14 of these issues — treat them as "
                             "backlog, or stop and ask the board owner?"},
                ticket="RDSD-902")])
    # idle, with something to say for itself
    E.append("backlog-health", [
        E.event("backlog-health", "assistant_text",
                {"text": "rebuilt the semantic model and pushed feature/RDSD-771-backlog-health",
                 "model": "claude-haiku-4.5"}, ticket="RDSD-771"),
        E.event("backlog-health", "turn_ended", {"turn": "0"}, ticket="RDSD-771")])
    # and one the operator hid
    E.append("arl-usage", [E.event("arl-usage", "turn_ended", {"turn": "0"}, ticket="RDSD-55")])

    S.arrange(order=names, hidden=["arl-usage"])
    return names


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


@pytest.mark.browser
def test_five_agents_one_open_and_no_dead_space(fleet_home, tmp_path):
    """The demo. Everything asserted here is what the operator asked to be able to see at a glance:
    where everyone is, what the loud one wants, and that the page is full."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of_five(tmp_path)
    shots = os.environ.get("AGENTDATA_SHOTS") or str(tmp_path / "shots")
    os.makedirs(shots, exist_ok=True)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile.is-solo[data-tier="full"]', timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll("
                "'#grid .tile[data-tier=\"rail\"]:not(.is-hidden)').length >= 3",
                timeout=15000)

            out = page.evaluate("""() => {
              const row = document.getElementById('grid');
              const style = getComputedStyle(row);
              const panes = [...row.querySelectorAll('.tile:not(.is-hidden)')];
              const rails = panes.filter(t => t.dataset.tier === 'rail');
              const face = t => t.querySelector('.pane-rail');
              const inner = row.clientWidth - parseFloat(style.paddingLeft) -
                            parseFloat(style.paddingRight);
              const tall = row.clientHeight - parseFloat(style.paddingTop) -
                           parseFloat(style.paddingBottom);
              const open = document.querySelector('.tile.is-solo');
              return {
                rails: rails.map(t => t.dataset.repo),
                red: rails.filter(t => face(t).classList.contains('needs-human'))
                          .map(t => t.dataset.repo),
                glyphs: rails.filter(t => face(t).classList.contains('needs-human'))
                             .map(t => face(t).querySelector('.pr-glyph').textContent),
                says: rails.map(t => face(t).getAttribute('aria-label')),
                sum: panes.reduce((n, t) => n + t.getBoundingClientRect().width, 0) +
                     parseFloat(style.columnGap || '0') * (panes.length - 1),
                inner: inner,
                short: panes.filter(t => Math.abs(t.getBoundingClientRect().height - tall) > 1.5)
                            .map(t => t.dataset.repo),
                counts: document.getElementById('counts').textContent,
                hidden: document.getElementById('hiddencount').textContent,
                dock: !!document.getElementById('dock'),
                column: !!document.getElementById('column'),
                tools: [...open.querySelectorAll('.head [data-tool]')].map(b => b.dataset.tool),
              };
            }""")
            assert not errors, errors

            # Four registered agents are not open, one of them hidden: three rails.
            assert len(out["rails"]) == 3, out["rails"]
            assert "arl-usage" not in out["rails"] and out["hidden"] == "1 hidden", out
            assert out["dock"] is False, "the dock went with the grid (#232)"
            assert out["column"] is False, "the column went with #233"

            # The loud two are red, with a glyph as well as the colour, and their asks are in their
            # labels -- readable without opening a pane, by a screen reader or a pointer.
            assert sorted(out["red"]) == ["luna", "velocity"], out["red"]
            assert out["glyphs"] == ["!", "!"], out["glyphs"]
            assert any("sprint field is empty" in said for said in out["says"]), out["says"]
            assert "2 need you" in out["counts"], out["counts"]

            # The quiet one says what it did, which a dock chip never had room for.
            assert any("pushed feature/RDSD-771" in said for said in out["says"]), out["says"]

            # No dead space: the panes account for the row's width, and every one its height.
            assert abs(out["sum"] - out["inner"]) < 1.5, out
            assert out["short"] == [], out

            # And the open pane carries the three controls every pane with a head carries.
            assert out["tools"] == ["hide", "refresh", "model"], out["tools"]

            for skin in SKINS:
                S.act("theme", {"skin": skin})
                page.wait_for_timeout(350)
                page.screenshot(path=os.path.join(
                    shots, "row-" + skin.replace(":", "-") + ".png"))
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    for skin in SKINS:
        shot = os.path.join(shots, "row-" + skin.replace(":", "-") + ".png")
        assert os.path.getsize(shot) > 5000, f"{shot} is not a rendered page"
