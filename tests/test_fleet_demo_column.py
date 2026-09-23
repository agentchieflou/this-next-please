"""The column's definition-of-done demo (issue #208).

Five agents on one desk, in the state a real afternoon puts them in: one running, one waiting for a
click, one with a question, one idle, one removed from the registry. The demo renders that in the
`column` arrangement and measures the two things the operator asked for --

* every agent that is not open is a band, one above another, and
* the bands account for the column's height, so the page has no dead space in it --

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


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))
    monkeypatch.setattr(S, "_refreshed_at", {})


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
    # a question, which is what a band has room for and a dock chip never did
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
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector(".tile.is-solo", timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('#bands .band:not([hidden])').length >= 3",
                timeout=15000)

            out = page.evaluate("""() => {
              const list = document.getElementById('bands');
              const bands = [...list.querySelectorAll('.band:not([hidden])')];
              const gap = parseFloat(getComputedStyle(list).rowGap || '0') * (bands.length - 1);
              const tile = document.querySelector('.tile.is-solo').getBoundingClientRect();
              return {
                bands: bands.map(b => b.dataset.repo),
                red: [...list.querySelectorAll('.band.needs-human')].map(b => b.dataset.repo),
                asks: [...list.querySelectorAll('.band.needs-human .b-last')].map(b => b.textContent),
                says: [...bands].map(b => b.querySelector('.b-last').textContent),
                sum: bands.reduce((n, b) => n + b.getBoundingClientRect().height, 0) + gap,
                listH: list.getBoundingClientRect().height,
                tileBottom: tile.bottom, page: window.innerHeight,
                head: document.getElementById('column-count').textContent,
                foot: document.getElementById('column-hidden').textContent,
                dock: !!document.getElementById('dock'),
                tools: [...bands[0].querySelectorAll('[data-tool]')].map(b => b.dataset.tool),
              };
            }""")
            assert not errors, errors

            # Four registered agents are not open, one of them hidden: three bands.
            assert len(out["bands"]) == 3, out["bands"]
            assert "arl-usage" not in out["bands"] and "1 hidden" in out["foot"], out
            assert out["dock"] is False, "the dock went with the grid (#232)"

            # The loud two are red and their asks are readable without opening a tile.
            assert sorted(out["red"]) == ["luna", "velocity"], out["red"]
            assert any("sprint field is empty" in ask for ask in out["asks"]), out["asks"]
            assert "2 need you" in out["head"], out["head"]

            # The quiet one says what it did, which a dock chip never had room for.
            assert any("pushed feature/RDSD-771" in said for said in out["says"]), out["says"]

            # No dead space: the bands account for the column and the tile reaches the bottom.
            assert abs(out["sum"] - out["listH"]) < 1.5, out
            assert out["tileBottom"] > out["page"] * 0.75, out

            # And every band carries the same three controls the open tile has.
            assert out["tools"] == ["hide", "refresh", "model"], out["tools"]

            for skin in SKINS:
                S.act("theme", {"skin": skin})
                page.wait_for_timeout(350)
                page.screenshot(path=os.path.join(
                    shots, "column-" + skin.replace(":", "-") + ".png"))
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    for skin in SKINS:
        shot = os.path.join(shots, "column-" + skin.replace(":", "-") + ".png")
        assert os.path.getsize(shot) > 5000, f"{shot} is not a rendered page"
