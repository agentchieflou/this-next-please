"""Sitting: D — the rail (issue #183).

In the grid a ticket goes to an agent by being dragged onto its tile. In the board window there are
no tiles -- that is the point of the window -- so the row offered a button per candidate and a drag
went nowhere; and the dispatch card, which lived inside the tile, either fell back to a bare start
(no tile) or drew inside a tile the window was not showing (a hidden one). The window built for
handing tickets over was the one place the hand-over skipped its pre-flight.

The rail is one chip per registered checkout at the top of the board, each a drop target; a drop
calls exactly what a drop on the tile calls; the card is one element the page owns, drawn under the
rail when the tile is not on the glass. Same rules as `tests/test_fleet_handoff_pickup.py`: the
drop is built in page context, and the assertions are on the rendered page and on the consequence
(the `started` events on the checkout), never on the source text.
"""
from __future__ import annotations
import threading
import time

import pytest

from agentdata import proc
from agentdata.fleet import board as B, events as E, preflight as PF, registry, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": [], "hidden": []},
                        "roles": {"order": [], "hidden": []},
                        "screens": {"order": [], "hidden": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


class _FakeChild:
    def __init__(self, pid):
        self.pid = pid


@pytest.fixture()
def spawns(monkeypatch):
    """A launcher that records what it was asked to run and never runs it (the switcher's)."""
    alive: set[int] = set()
    launched: list[list[str]] = []
    next_pid = [4300]

    def spawn(repo, name, argv, exe=None):
        launched.append(list(argv))
        next_pid[0] += 1
        alive.add(next_pid[0])
        return _FakeChild(next_pid[0])

    monkeypatch.setattr(supervisor, "_spawn", spawn)
    monkeypatch.setattr(supervisor, "pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(proc, "kill_tree", lambda pid: alive.discard(pid))
    return {"alive": alive, "launched": launched}


def _fleet(tmp_path):
    """Two checkouts of two projects, and a board with one RDSD ticket on it: `luna` is the one
    candidate for it, `mars` is not. Jira is never reached -- the board cache and the pre-flight
    cache are the seams, primed the way a second read inside the TTL would find them."""
    Registry().add(make_project(tmp_path / "luna", project="RDSD"), name="luna")
    Registry().add(make_project(tmp_path / "mars", project="DATAENG"), name="mars")
    B.write_cache({"jql": B.DEFAULT_JQL, "fetched_at": time.time(), "rows": [
        {"key": "RDSD-118", "summary": "UAT refresh is slow", "status": "To Do", "category": "new"}]})
    PF.write_cache({"issues": {"RDSD-118": {"description": "UAT refresh is slow.", "issuetype": "",
                                            "comments": 0, "attachments": 0, "error": "",
                                            "at": time.time()}}})


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _board_window(p, port, token):
    """The right-hand window of the roles layout: the board, and no tiles on the glass."""
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=roles&view=board", wait_until="domcontentloaded")
    page.wait_for_selector("#tickets li[data-key='RDSD-118']", timeout=15000)
    page.wait_for_selector("#agentrail .rail-chip[data-repo='luna']:not([hidden])", timeout=15000)
    assert page.evaluate("() => document.body.classList.contains('panels')"), "not the board window"
    assert page.evaluate("() => Array.from(document.querySelectorAll('.tile')).every(t => t.offsetParent === null)"), \
        "the board window has a tile on the glass"
    return browser, page, errors


def _drop(page, repo):
    """A ticket row dropped on a rail chip, built in page context: the only way to put a
    `DataTransfer` on a synthetic event the page's own handler will read."""
    page.evaluate("""(repo) => {
      const chip = document.querySelector('#agentrail .rail-chip[data-repo="' + repo + '"] .rail-open');
      const dt = new DataTransfer();
      dt.setData('application/x-agentdata-ticket', 'RDSD-118');
      dt.setData('text/plain', 'RDSD-118');
      chip.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
    }""", repo)


def _card_open(page):
    page.wait_for_selector("#railslot #dispatch:not([hidden])", timeout=5000)
    page.wait_for_function(
        "() => document.querySelector('#dispatch .verdict').textContent.trim() !== 'reading…'", timeout=5000)


def _started(name):
    return sum(1 for ev in E.read(name) if ev["kind"] == "started")


def _eventually(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# ------------------------------------------------------------------------------------ the drop


@pytest.mark.browser
def test_a_ticket_dropped_on_a_rail_chip_opens_the_card_under_the_rail_and_start_starts_it_once(
        fleet_home, tmp_path, spawns):
    """Acceptance criterion. In `?layout=roles&view=board`, a ticket row dragged onto a rail chip
    opens the pre-flight card under the rail with its verdict; *Start* counts exactly one `started`
    event on that checkout."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _board_window(p, port, token)
            _drop(page, "luna")
            _card_open(page)
            card = page.locator("#railslot #dispatch")
            assert card.is_visible(), "the card is under the rail, where the operator is looking"
            assert card.locator(".verdict").inner_text().strip().lower() == "thin"
            assert "RDSD-118 → luna" in card.locator(".dispatch-key").inner_text()
            assert "none found" in card.locator(".dispatch-rows").inner_text()
            assert _started("luna") == 0, "the card is the decision, not the launch"

            card.locator(".dispatch-go").click()
            assert _eventually(lambda: _started("luna") == 1), "Start started nothing"
            page.wait_for_selector("#dispatch[hidden]", state="attached", timeout=5000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert _started("luna") == 1, "exactly one started, on the checkout the chip named"
    assert _started("mars") == 0
    assert len(spawns["launched"]) == 1


@pytest.mark.browser
def test_a_drop_on_a_live_agents_chip_reads_the_refusal_and_starts_nothing(fleet_home, tmp_path, spawns):
    """Acceptance criterion. The same drop on a chip whose agent is live reads the `live_agent`
    refusal verbatim -- the supervisor's words, on the card -- and counts no `started`."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)
    supervisor.write_lock("luna", {"pid": 4242, "repo": "luna", "ticket": "RDSD-2", "session": "sess-2"})
    spawns["alive"].add(4242)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _board_window(p, port, token)
            _drop(page, "luna")
            _card_open(page)
            page.locator("#dispatch .dispatch-go").click()
            page.wait_for_function(
                "() => /already has a live agent/.test(document.querySelector('#dispatch .dispatch-note').textContent)",
                timeout=5000)
            note = page.locator("#dispatch .dispatch-note").inner_text()
            assert "luna already has a live agent (pid 4242" in note, note
            assert "ad-fleet stop luna" in note, "the supervisor's own hint, not a reworded one"
            assert page.locator("#railslot #dispatch").is_visible(), "a refusal leaves the card open"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert _started("luna") == 0
    assert not spawns["launched"]
    assert 4242 in spawns["alive"], "the live one was left alone"


@pytest.mark.browser
def test_a_drop_on_a_non_candidate_reads_cross_project_and_declining_the_override_starts_nothing(
        fleet_home, tmp_path, spawns):
    """Acceptance criterion. A drop on a chip the rail did not light reads the `cross_project`
    refusal and its one override; declining it starts nothing. And the rail said so before the
    drop: while the ticket is in flight `luna` is lit and `mars` is dimmed."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _board_window(p, port, token)

            page.evaluate("""() => {
              const li = document.querySelector('#tickets li[data-key="RDSD-118"]');
              const dt = new DataTransfer();
              li.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""")
            lit = page.evaluate("""() => Array.from(document.querySelectorAll('#agentrail .rail-chip:not([hidden])')).map(li =>
                [li.dataset.repo, li.classList.contains('is-candidate'), li.classList.contains('is-dim'),
                 li.querySelector('.rail-open').getAttribute('aria-selected')])""")
            assert lit == [["luna", True, False, "true"], ["mars", False, True, "false"]], lit

            asked: list[str] = []
            page.on("dialog", lambda d: (asked.append(d.message), d.dismiss()))
            _drop(page, "mars")
            _card_open(page)
            page.locator("#dispatch .dispatch-go").click()
            page.wait_for_function(
                "() => /DATAENG/.test(document.querySelector('#dispatch .dispatch-note').textContent)", timeout=5000)
            note = page.locator("#dispatch .dispatch-note").inner_text()
            assert "RDSD-118 is a RDSD ticket and mars declares jira_project DATAENG" in note, note
            assert len(asked) == 1 and "Start it anyway?" in asked[0], asked
            page.wait_for_timeout(300)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert _started("mars") == 0 and _started("luna") == 0
    assert not spawns["launched"], "declining the override started something"


# -------------------------------------------------------------------------------- the keyboard


@pytest.mark.browser
def test_the_whole_gesture_from_the_keyboard(fleet_home, tmp_path, spawns):
    """Acceptance criterion. From a focused ticket row, `1` hands the ticket to the first rail
    chip and opens the same card; `Esc` closes it and starts nothing; `Enter` hands it to the row's
    one candidate; `Ctrl+Enter` in the brief starts it, with the brief -- once."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser, page, errors = _board_window(p, port, token)
            row = page.locator("#tickets li[data-key='RDSD-118']")
            row.focus()
            page.keyboard.press("2")                       # the second chip is mars: any chip takes it
            _card_open(page)
            assert "RDSD-118 → mars" in page.locator("#dispatch .dispatch-key").inner_text()

            page.keyboard.press("Escape")
            page.wait_for_selector("#dispatch[hidden]", state="attached", timeout=5000)
            assert page.evaluate("() => !document.getElementById('board').hidden"), \
                "Esc closed the card, not the board"
            assert _started("mars") == 0

            row.focus()
            page.keyboard.press("Enter")                   # the row's one candidate is luna
            _card_open(page)
            assert "RDSD-118 → luna" in page.locator("#dispatch .dispatch-key").inner_text()
            page.locator("#dispatch .brief").fill("the window is Tuesday")
            page.keyboard.press("Control+Enter")
            assert _eventually(lambda: _started("luna") == 1), "Ctrl+Enter started nothing"
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

    assert _started("luna") == 1 and _started("mars") == 0
    assert len(spawns["launched"]) == 1
    brief = tmp_path / "luna" / ".agent" / "in" / "RDSD-118" / "brief.md"
    assert brief.is_file() and "the window is Tuesday" in brief.read_text(encoding="utf-8")


# ------------------------------------------------------------------------- the tile still takes it


@pytest.mark.browser
def test_a_refusal_in_the_grid_lands_on_the_tile_and_the_rail_note_stays_empty(fleet_home, tmp_path, spawns):
    """The card is one element with two homes. In the grid it draws in the tile that took the
    drop, exactly where #164's tests find it, and a refusal is written on that card -- never under a
    rail the operator is not looking at."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile[data-repo='luna']:visible", timeout=15000)
            page.evaluate("""() => {
              const tile = document.querySelector('.tile[data-repo="luna"]');
              const dt = new DataTransfer();
              dt.setData('application/x-agentdata-ticket', 'RDSD-118');
              dt.setData('text/plain', 'RDSD-118');
              tile.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""")
            page.wait_for_selector(".tile[data-repo='luna'] .dispatch-slot #dispatch:not([hidden])", timeout=5000)
            assert page.evaluate("() => document.getElementById('railnote').hidden")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
