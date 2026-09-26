"""Sitting: F — the demo (issue #185).

The epic's acceptance sentence, end to end, on CI against the fake `copilot`: the board in
`glass:smoke` hands a ticket to a checkout with seven branches, the card says *ready*, the agent
looks before it branches and continues on the ticket's own, the tile's git cell reads the count,
the inspector's pane names the unmerged three -- and the scrollbar the operator scrolls the board
with computes to the skin's thumb, not the operating system's grey.

A real `copilot` process (the fake from `tests/fakes/`, launched by the real supervisor with the
real allow-list), a real repository built with real git, and a real browser on the real page.

It was the roles layout's board window until #232 retired it. The same situation now is the board
open beside the agent the operator is reading (`sol`), with the checkout the ticket goes to a
48px rail in the row (a band off the glass until #233) -- which is what sends the card under the
agent rail.
"""
from __future__ import annotations
import os
import threading
import time

import pytest

from agentdata.fleet import board as B, events as E, preflight as PF, registry, serve as S, spend as SPEND, supervisor
from agentdata.fleet.registry import Registry

import fakes
from test_fleet import make_project
from test_fleet_board_desk import PHOTO, friction
from test_fleet_branches import seven_branches
from test_fleet_desk_browser import launch_chromium
from test_fleet_handoff_pickup import RICH

pytestmark = [pytest.mark.slow, pytest.mark.browser]

TICKET = "RDSD-7"
SETTLE_S = 90

# #504: the photo's shape -- nine AGENTS.md facts (every one a link fact, so every one reaches the
# panel and the rail), three friction files of 2026-09-03 and a spend ledger.
NINE_FACTS = (("jira_project", "RDSD"), ("jira_url", "https://jira.example.test"), ("jira_board_id", "42"),
              ("bitbucket_url", "https://bitbucket.example.test"), ("bitbucket_repo", "rdsd/luna"),
              ("confluence_base", "https://confluence.example.test"), ("confluence_space", "RDSD"),
              ("report_id", "0f1e2d3c"), ("ws_id", "9a8b7c6d"))


@pytest.fixture()
def desk(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "branches-caution")
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    path = make_project(tmp_path / "luna", project="RDSD", phase="triaged")
    seven_branches(path, ticket=TICKET)
    with open(os.path.join(path, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# Project\n\n" + "".join(f"- {k}: {v}\n" for k, v in NINE_FACTS))
    for name, unblock in PHOTO:
        friction(path, name, unblock, ticket=TICKET)
    Registry().add(path, name="luna")
    SPEND.write_ledger("luna", {"sessions": {"s-0903": {"premium": 41.5, "turns": 12, "first": "2026-09-03T12:00:00",
                                                        "last": "2026-09-03T13:04:00", "model": "", "ticket": TICKET,
                                                        "ended": "2026-09-03T13:05:00"}},
                                "days": {"2026-09-03": 41.5}, "session": "s-0903", "turn_closed": True})
    Registry().add(make_project(tmp_path / "sol", project="OPS"), name="sol")
    S.update_window("main", open="sol")
    B.write_cache({"jql": B.DEFAULT_JQL, "fetched_at": time.time(), "rows": [
        {"key": TICKET, "summary": "UAT refresh is slow", "status": "To Do", "category": "new"}]})
    PF.write_cache({"issues": {TICKET: {"description": RICH, "issuetype": "Story", "comments": 0,
                                        "attachments": 0, "error": "", "at": time.time()}}})
    return path


def _settle(name: str, seconds: float = SETTLE_S) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not supervisor.live(name):
            return
        time.sleep(0.2)
    raise AssertionError(f"{name} was still running after {seconds}s")


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _eventually(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def test_a_ticket_handed_over_from_the_board_window_to_a_checkout_with_seven_branches(desk):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            errors: list[str] = []

            # 1. The board, in glass, beside the agent the operator is reading. The address is the
            #    board window's, as an old bookmark has it; it opens the desk, and the board is a
            #    key away.
            board = browser.new_page(viewport={"width": 1280, "height": 900})
            board.on("pageerror", lambda e: errors.append(str(e)))
            board.goto(f"http://127.0.0.1:{port}/?t={token}&layout=roles&view=board", wait_until="domcontentloaded")
            board.wait_for_selector('.tile[data-repo="sol"].is-solo', timeout=15000)
            board.evaluate("() => boardPanel(true)")
            board.wait_for_selector(f"#tickets li[data-key='{TICKET}']", timeout=15000)
            board.wait_for_selector("#agentrail .rail-chip[data-repo='luna']:not([hidden])", timeout=15000)
            board.evaluate("(name) => post('theme', { skin: name })", "glass:smoke")
            board.wait_for_function("() => document.body.getAttribute('data-skin-variant') === 'smoke'", timeout=5000)
            # The skin has arrived when its stylesheet's tokens are on <body>. Since #257 glass paints
            # nothing in CSS -- the sidebar is the page's own opaque panel, not frost -- so what is
            # read is the skin's own input, and the sidebar stays readable as the plain look.
            board.wait_for_function("""() => getComputedStyle(document.body)
                .getPropertyValue('--glass-fill').trim() !== ''""", timeout=5000)
            assert board.evaluate("() => getComputedStyle(document.getElementById('side')).backdropFilter") == "none"

            # The scrollbar the board scrolls with is the skin's thumb, read off the computed style.
            bar = board.evaluate("""() => {
                const probe = document.createElement('i');
                probe.style.color = 'var(--scroll-thumb)';
                document.body.appendChild(probe);
                const thumb = getComputedStyle(probe).color;
                probe.remove();
                const s = getComputedStyle(document.getElementById('side'));
                return { thumb, bar: s.scrollbarColor, width: s.scrollbarWidth };
            }""")
            assert bar["thumb"] == "rgba(255, 255, 255, 0.22)", bar
            assert bar["bar"].startswith(bar["thumb"]) and bar["width"] == "thin", bar

            # 2. The drag: the rail lights the one candidate, the drop opens the card under the rail.
            board.evaluate(f"""() => {{
              const li = document.querySelector('#tickets li[data-key="{TICKET}"]');
              li.dispatchEvent(new DragEvent('dragstart', {{dataTransfer: new DataTransfer(), bubbles: true, cancelable: true}}));
            }}""")
            assert board.evaluate("() => document.querySelector('#agentrail .rail-chip[data-repo=\"luna\"]').classList.contains('is-candidate')")
            board.evaluate(f"""() => {{
              const chip = document.querySelector('#agentrail .rail-chip[data-repo="luna"] .rail-open');
              const dt = new DataTransfer();
              dt.setData('application/x-agentdata-ticket', '{TICKET}');
              dt.setData('text/plain', '{TICKET}');
              chip.dispatchEvent(new DragEvent('drop', {{dataTransfer: dt, bubbles: true, cancelable: true}}));
            }}""")
            board.wait_for_selector("#railslot #dispatch:not([hidden])", timeout=5000)
            board.wait_for_function(
                "() => document.querySelector('#dispatch .verdict').textContent.trim() !== 'reading…'", timeout=5000)
            assert board.locator("#dispatch .verdict").inner_text().strip().lower() == "ready"
            assert f"{TICKET} → luna" in board.locator("#dispatch .dispatch-key").inner_text()
            assert sum(1 for e in E.read("luna") if e["kind"] == "started") == 0

            # 3. Start. One agent, which looks before it branches.
            board.locator("#dispatch .dispatch-go").click()
            board.wait_for_selector("#dispatch[hidden]", state="attached", timeout=10000)
            assert _eventually(lambda: sum(1 for e in E.read("luna") if e["kind"] == "started") == 1)
            _settle("luna")
            E.refresh("luna", desk, repo_state=Registry().get("luna").state())
            events = E.read("luna")
            calls = [((e.get("data") or {}).get("arguments") or {}).get("command", "")
                     for e in events if e["kind"] == "tool_call"]
            assert [c for c in calls if c.startswith("git for-each-ref refs/heads")]
            assert not [c for c in calls if c.startswith("git checkout -b")], calls
            assert not [e for e in events if e["kind"] == "denied"], "the look must be permitted"
            said = " ".join((e.get("data") or {}).get("text", "") for e in events if e["kind"] == "assistant_text")
            assert "branches=7 (3 unmerged)" in said and "Continuing on feature/RDSD-7-part-2" in said
            assert Registry().get("luna").state()["branch"] == "feature/RDSD-7-part-2"

            # 4. A second window, opened on luna the way a toast opens it: the tile's cell reads the
            #    count, and the pane names the three.
            grid = browser.new_page(viewport={"width": 1280, "height": 900})
            grid.on("pageerror", lambda e: errors.append(str(e)))
            grid.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid#tile=luna",
                      wait_until="domcontentloaded")
            grid.wait_for_selector('.tile[data-repo="luna"].is-solo', timeout=15000)
            grid.wait_for_function(
                """() => /7 branches · 3 never reached main/.test(
                     (document.querySelector('.tile[data-repo="luna"] .cell[data-cell="git"]') || {}).textContent || '')""",
                timeout=40000)
            cell = grid.locator('.tile[data-repo="luna"] .cell[data-cell="git"]')
            assert cell.evaluate("el => el.classList.contains('warn')")
            cell.click()
            grid.wait_for_function(
                "() => document.querySelectorAll('#inspector:not([hidden]) .branches .branchrow').length === 7", timeout=10000)
            rows = grid.eval_on_selector_all("#inspector .branches .branchrow", """els => els.map(e => ({
                name: e.querySelector('.bname').textContent, unmerged: e.classList.contains('unmerged') }))""")
            assert [r["name"] for r in rows if r["unmerged"]] == \
                ["feature/RDSD-7-part-2", "fix/RDSD-9", "feature/RDSD-7-part-1"], rows
            assert grid.locator("#inspector .branches-carry").inner_text() == \
                "two branches carry RDSD-7 (feature/RDSD-7-part-2, feature/RDSD-7-part-1); only one can merge"

            # 5. The project panel fits one screen (#504): the rail, no open friction, one spend line,
            #    the branches with their seven rows in sight, and a closed *more* holding the facts.
            grid.wait_for_selector("#inspectordetails > details.more", state="attached", timeout=10000)
            shape = grid.evaluate("""() => {
                const el = document.getElementById('inspector');
                const body = document.getElementById('inspectordetails');
                const kids = Array.from(body.children);
                const at = (sel) => kids.findIndex(k => k.matches(sel));
                const more = body.querySelector(':scope > details.more');
                const spend = body.querySelector(':scope > .spendline');
                const rows = Array.from(body.querySelectorAll('.branches .branchrow'));
                const cs = spend ? getComputedStyle(spend) : null;
                const line = cs ? (parseFloat(cs.lineHeight) || 1.5 * parseFloat(cs.fontSize)) : 0;
                return { scroll: el.scrollHeight, client: el.clientHeight,
                         rail: at('.rail'), friction: at('.frictionrow'), spend: at('.spendline'),
                         branches: at('.branches'), more: at('details.more'), last: kids.length - 1,
                         spendCount: body.querySelectorAll('.spendline').length,
                         spendOneLine: !!spend && spend.getBoundingClientRect().height < 2 * line,
                         spendTitle: spend ? spend.title : '',
                         moreOpen: !!more && more.open, factsInMore: !!(more && more.querySelector('.facts')),
                         facts: document.querySelectorAll('#inspector .facts').length,
                         factKeys: more ? Array.from(more.querySelectorAll('.facts .k')).map(k => k.textContent) : [],
                         summary: more ? more.querySelector(':scope > summary').textContent : '',
                         rowsVisible: rows.filter(r => r.checkVisibility() && r.getBoundingClientRect().bottom <= el.getBoundingClientRect().bottom).length,
                         rowHeights: rows.map(r => Math.round(r.getBoundingClientRect().height)) };
            }""")
            assert shape["scroll"] <= shape["client"] + 1, shape
            assert shape["rail"] == 0 and shape["friction"] == -1, shape
            assert 0 < shape["spend"] < shape["branches"] < shape["more"] == shape["last"], shape
            assert shape["spendCount"] == 1 and shape["spendOneLine"] and "turn" in shape["spendTitle"], shape
            assert not shape["moreOpen"] and shape["factsInMore"] and shape["facts"] == 1, shape
            assert not {"project", "path", "branch"} & set(shape["factKeys"]) and "jira" in shape["factKeys"], shape
            assert shape["summary"].startswith("more") and "facts" in shape["summary"] and \
                "3 earlier friction" in shape["summary"], shape
            assert shape["rowsVisible"] == 7, shape

            # An open *more* stays open across a desk tick, and a tick with nothing changed writes nothing.
            grid.evaluate("() => { document.querySelector('#inspectordetails > details.more').open = true; }")
            ticked = grid.evaluate("""async () => {
                const body = document.getElementById('inspectordetails');
                const seen = [];
                const watch = new MutationObserver((records) => { for (const r of records) seen.push(r.type + ':' + (r.target.className || r.target.nodeName)); });
                watch.observe(body, { subtree: true, childList: true, attributes: true, characterData: true });
                await loadDesk();
                await new Promise(requestAnimationFrame);
                watch.disconnect();
                return { n: seen.length, seen: seen.slice(0, 8),
                         open: document.querySelector('#inspectordetails > details.more').open };
            }""")
            assert ticked["n"] == 0 and ticked["open"], ticked
            # A rebuild (a re-read of the branches) keeps both folds as the operator left them.
            grid.evaluate("() => loadBranches('luna', true)")
            grid.wait_for_function("""() => document.querySelectorAll('#inspector .branches .branchrow').length === 7
                && document.querySelector('#inspectordetails > details.more').open
                && document.querySelector('#inspector details.branches-list').open""", timeout=10000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    # The fleet wrote nothing in the checkout: the branch it is on is the one the agent chose.
    assert Registry().get("luna").state()["active_ticket"] == TICKET
