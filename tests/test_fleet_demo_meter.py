"""The meter's definition-of-done demo (issue #214).

Five agents with money actually spent on them: one over its budget, one at four fifths of it, one
comfortable, one that has never run, and one whose ledger survived a log rotation. The demo renders
that and checks the three things the operator asked to be able to see at a glance --

* what this agent has cost, on its tile;
* what it has cost against what, with the amber and the red carrying sentences and not just colour;
* what the whole fleet has cost today, in the footer --

and that `ad-fleet spend` prints the same numbers the page does, because a page and a CLI that
disagree about money are worse than either one alone.
"""
from __future__ import annotations
import os
import threading

import pytest

from agentdata import config as C
from agentdata.fleet import events as E, lifecycle, registry, serve as S, spend as SPEND
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium

SKINS = ["none", "glass:smoke"]


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def _agent(tmp_path, name, *, spend=0.0, model="", turns=1, session="s1"):
    Registry().add(make_project(tmp_path / name, ticket="RDSD-1"), name=name)
    rows = [E.event(name, "started", {"pid": 1}, ticket="RDSD-1"),
            E.event(name, "session_id", {"session": session}, ticket="RDSD-1")]
    if model:
        rows.append(E.event(name, "assistant_text",
                            {"text": "working on it", "model": model}, ticket="RDSD-1"))
    if spend:
        rows.append(E.event(name, "cost", {"premium_requests": spend, "source": "checkpoint"},
                            ticket="RDSD-1"))
    for n in range(turns):
        rows.append(E.event(name, "turn_ended", {"turn": str(n)}, ticket="RDSD-1"))
    E.append(name, rows)


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _desk_of_five(tmp_path):
    C.save({"fleet": {"budget_per_agent": 10}})
    _agent(tmp_path, "rdsd-pbi-reporting", spend=12.5, model="claude-opus-5", turns=9)
    _agent(tmp_path, "luna", spend=8.4, model="claude-haiku-4.5", turns=6)
    _agent(tmp_path, "velocity", spend=2.0, model="claude-haiku-4.5", turns=2)
    _agent(tmp_path, "backlog-health")                       # never spent anything
    # And one whose log rolled underneath it: the number has to survive that.
    _agent(tmp_path, "arl-usage", spend=6.0, turns=3)
    E.append("arl-usage", [E.event("arl-usage", "raw", {"pad": "x" * (1200 * 1024)},
                                   ticket="RDSD-1")])
    C.save({"fleet": {"budget_per_agent": 10, "log_mb": 1, "log_keep": 3}})
    assert E.NORMALIZED in lifecycle.rotate_all("arl-usage", cfg=C.load())
    S.arrange(order=["rdsd-pbi-reporting", "luna", "velocity", "backlog-health",
                              "arl-usage"])


def test_with_no_budget_and_nothing_spent_there_is_no_cell_to_draw(fleet_home, tmp_path):
    """A meter reading zero out of nothing is a control that says nothing, which is the kind of
    chrome the column was cleared of."""
    C.save({"fleet": {}})
    _agent(tmp_path, "quiet")
    row = S.row_for("quiet")
    assert row["spend"]["total"] == 0.0 and row["spend"]["budget"] == 0.0
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "agentdata", "fleet", "static", "app.js"), encoding="utf-8").read()
    # The cell is only in the list of cells to draw when there is something to meter.
    assert "if (spend && (spend.total || spend.budget)) want.push" in js


def test_the_ledger_and_the_cli_and_the_page_all_say_the_same_number(fleet_home, tmp_path):
    """Three printers, one arithmetic. A page and a CLI that disagree about money are worse than
    either one alone."""
    from agentdata import cli_fleet

    _desk_of_five(tmp_path)

    # The rolled one kept its spend: that is the bug #210 exists for.
    assert lifecycle.spent("arl-usage") == 6.0
    assert SPEND.total(SPEND.rebuild("arl-usage")) == 6.0

    snap = S.fleet_snapshot()
    by_repo = {r["repo"]: r["spend"]["total"] for r in snap["repos"]}
    assert by_repo == {"rdsd-pbi-reporting": 12.5, "luna": 8.4, "velocity": 2.0,
                       "backlog-health": 0.0, "arl-usage": 6.0}
    assert snap["spend"]["all_time"] == 28.9

    fleet = SPEND.for_fleet(sorted(by_repo), today=S._today())
    assert fleet["all_time"] == 28.9
    assert cli_fleet.main(["spend"]) == 0


@pytest.mark.browser
def test_the_meter_is_on_every_tile_and_the_footer_sums_the_day(fleet_home, tmp_path):
    """The demo. Amber at four fifths, red at the line, both with a sentence -- and the fleet's own
    total beside the agent count, from the same ledgers.

    The cell is drawn on a pane wide enough for its cells (#233: a rail and a compact pane skip
    them), so the four being read are open side by side -- three pinned beside the open one -- and
    the fifth is a rail, whose label carries the same number the band's chip did."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of_five(tmp_path)
    S.arrange(pinned=["rdsd-pbi-reporting", "luna", "velocity"])
    S.update_window("main", open="backlog-health")
    shots = os.environ.get("AGENTDATA_SHOTS") or str(tmp_path / "shots")
    os.makedirs(shots, exist_ok=True)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1800, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile.is-solo[data-tier="full"]', timeout=15000)
            page.wait_for_function(
                "() => document.querySelectorAll('.tile[data-tier=\"full\"] .cell.spend').length"
                " === 4", timeout=15000)

            out = page.evaluate("""() => {
              const cell = t => {
                const c = document.querySelector(`.tile[data-repo="${t}"] .cell.spend`);
                return c ? { text: c.innerText.replace(/\\s+/g, ' '),
                             over: c.classList.contains('over'),
                             warn: c.classList.contains('warn'),
                             why: c.title } : null;
              };
              return {
                over: cell('rdsd-pbi-reporting'),
                near: cell('luna'),
                fine: cell('velocity'),
                none: cell('backlog-health'),
                footer: document.getElementById('counts').textContent,
                rails: [...document.querySelectorAll('#grid .tile[data-tier="rail"] .pane-rail')]
                  .map(f => f.getAttribute('aria-label')),
              };
            }""")
            assert not errors, errors

            assert out["over"]["over"] is True and "12.5 premium" in out["over"]["text"]
            assert "of 10" in out["over"]["text"]
            assert "budget" in out["over"]["why"], "red carries its sentence, not just its colour"

            assert out["near"]["warn"] is True and "8.4 premium" in out["near"]["text"]
            assert "mean" in out["near"]["why"].lower(), "a mean, and said to be one"

            assert out["fine"]["over"] is False and out["fine"]["warn"] is False
            # An agent that has spent nothing still shows its headroom when a budget exists: "0 of
            # 10" is the answer to "how much room have I got", and it is the reassurance the whole
            # epic is for. The cell is absent only when there is no budget AND nothing spent.
            assert out["none"] is not None and "0 premium" in out["none"]["text"]
            assert "of 10" in out["none"]["text"]
            assert out["none"]["over"] is False and out["none"]["warn"] is False

            assert "premium today" in out["footer"] and "28.9 all time" in out["footer"]
            # The rail says what the band's chip said: what this agent has cost.
            assert len(out["rails"]) == 1 and "6 premium" in out["rails"][0], out["rails"]

            for skin in SKINS:
                S.act("theme", {"skin": skin})
                page.wait_for_timeout(350)
                page.screenshot(path=os.path.join(
                    shots, "meter-" + skin.replace(":", "-") + ".png"))
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_an_over_budget_agent_is_reachable_from_the_page_on_a_second_press(fleet_home, tmp_path):
    """The whole of #213: it was enforced in `send`, the desk called `send` with no `force`, and so
    the only door was a terminal."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of_five(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=column",
                      wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="rdsd-pbi-reporting"]', timeout=15000)

            tile = page.locator('.tile[data-repo="rdsd-pbi-reporting"]')
            tile.locator(".say").fill("carry on")
            tile.locator(".send").click()
            page.wait_for_function(
                """() => /Send anyway/.test(document.querySelector(
                     '.tile[data-repo="rdsd-pbi-reporting"] .send').textContent)""",
                timeout=8000)
            said = tile.locator(".err").inner_text()
            assert "premium-request budget" in said, said
            assert "--force" in said or "raise" in said, "the supervisor's own hint"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
