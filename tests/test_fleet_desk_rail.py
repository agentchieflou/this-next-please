"""Sitting: D — the rail (issue #183).

In the grid a ticket goes to an agent by being dragged onto its tile. In the board window there are
no tiles -- that is the point of the window -- so the row offered a button per candidate and a drag
went nowhere; and the dispatch card, which lived inside the tile, either fell back to a bare start
(no tile) or drew inside a tile the window was not showing (a hidden one). The window built for
handing tickets over was the one place the hand-over skipped its pre-flight.

The rail is one chip per registered checkout at the top of the board, each a drop target; a drop
calls exactly what a drop on the tile calls; the card is one element the page owns, drawn under the
rail when the tile is not on the glass. The board window went with `roles` (#232); what these tests
drive now is the board open beside the agent the operator is reading, with the two checkouts a
ticket can go to as rails with no room for the card (bands, off the glass, until #233) -- the same
situation, one window instead of three. Same rules as `tests/test_fleet_handoff_pickup.py`: the
drop is built in page context, and the assertions are on the rendered page and on the consequence
(the `started` events on the checkout), never on the source text.
"""
from __future__ import annotations
import datetime as _dt
import json
import os
import threading
import time

import pytest

from agentdata import config as C, proc
from agentdata.fleet import (approval, board as B, events as E, models as M, preflight as PF, registry,
                             serve as S, supervisor)
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
        "schema": 2, "selected": "", "version": 0, "at": "",
        "arrangement": {"order": [], "size": {}, "pinned": [], "hidden": []},
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
    cache are the seams, primed the way a second read inside the TTL would find them. A third,
    `sol`, is the agent the operator has open, so neither checkout the ticket can go to is on the
    glass."""
    Registry().add(make_project(tmp_path / "luna", project="RDSD"), name="luna")
    Registry().add(make_project(tmp_path / "mars", project="DATAENG"), name="mars")
    Registry().add(make_project(tmp_path / "sol", project="OPS"), name="sol")
    S.update_window("main", open="sol")
    B.write_cache({"jql": B.DEFAULT_JQL, "fetched_at": time.time(), "rows": [
        {"key": "RDSD-118", "summary": "UAT refresh is slow", "status": "To Do", "category": "new"}]})
    PF.write_cache({"issues": {"RDSD-118": {"description": "UAT refresh is slow.", "issuetype": "",
                                            "comments": 0, "attachments": 0, "error": "",
                                            "at": time.time()}}})


def _seed_models():
    """`<fleet_dir>/models.json` as a refresh under Copilot CLI 1.0.88 writes it (#360), so the card
    offers the CLI's own list and nothing is spawned for it (#368)."""
    shipped = M.shipped()
    os.makedirs(os.path.dirname(M.cache_file()), exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(M.cache_file(), "w", encoding="utf-8") as f:
        json.dump({"source": "help", "cli_version": "1.0.88", "fetched_at": now,
                   "models": shipped["models"], "efforts": shipped["efforts"], "why": ""}, f)


def _luna_model():
    return (C.get_leaf(C.load(), "fleet.models", "luna", {}) or {}).get("model", "")


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _board_window(p, port, token):
    """The board, open beside `sol`: the checkouts a ticket can go to are rails, with no room on the
    glass for the card (#233; they were bands in the column, off the glass altogether). The address
    is the roles layout's board window, as a bookmark from before #232 still has it."""
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=roles&view=board", wait_until="domcontentloaded")
    page.wait_for_selector('.tile[data-repo="sol"].is-solo', timeout=15000)
    page.evaluate("() => boardPanel(true)")
    page.wait_for_selector("#tickets li[data-key='RDSD-118']", timeout=15000)
    page.wait_for_selector("#agentrail .rail-chip[data-repo='luna']:not([hidden])", timeout=15000)
    page.wait_for_function("""() => ['luna', 'mars'].every(name =>
        document.querySelector('.tile[data-repo="' + name + '"]').dataset.tier === 'rail')""",
        timeout=15000)
    assert page.evaluate("() => ['luna', 'mars'].every(name => !onTheGlass(name))"), \
        "a checkout the ticket can go to has room for the card on the glass"
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
        fleet_home, tmp_path, spawns, monkeypatch):
    """Acceptance criterion. With the board open and the checkout off the glass, a ticket row
    dragged onto a rail chip opens the pre-flight card under the rail with its verdict; *Start*
    counts exactly one `started` event on that checkout.

    And the card says what it will run on (#368): "runs on" and its pills, one of which is the model
    luna's last turn ran on. A press writes `fleet.models.luna` -- this start and every later one --
    and the start that follows carries `--model`."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)
    _seed_models()
    E.append("luna", [E.event("luna", "assistant_text", {"text": "done", "model": "claude-opus-5"},
                              ticket="RDSD-1")])
    # Every issue read the pre-flight makes: the drop's one, and none for a press (decision 15).
    fetched: list[str] = []
    read_issue = PF.fetch_issue
    monkeypatch.setattr(PF, "fetch_issue", lambda key, **kw: (fetched.append(key), read_issue(key, **kw))[1])

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

            # #368: the model row, "runs on" and the pills: the inherit pill pressed, the last turn's
            # model beside it, and `more…`.
            assert "the CLI chooses · cli-auto" in card.locator(".dispatch-rows").inner_text()
            assert card.locator(".dispatch-note").get_attribute("role") == "status"
            assert card.locator(".dispatch-runs").inner_text().strip() == "runs on"
            page.wait_for_selector('#dispatch .dispatch-model button[data-model="claude-opus-5"]', timeout=5000)
            pills = page.evaluate("""() => [...document.querySelectorAll('#dispatch .dispatch-model button.pill')]
                .map(b => [b.dataset.model ?? 'more', b.getAttribute('aria-pressed')])""")
            assert pills == [["", "true"], ["claude-opus-5", "false"], ["more", None]], pills
            card.locator('.dispatch-model button[data-model="claude-opus-5"]').click()
            assert _eventually(lambda: _luna_model() == "claude-opus-5"), "the press wrote nothing"
            page.wait_for_function(
                "() => /model set for this and later turns/.test(document.querySelector('#dispatch .dispatch-note').textContent)",
                timeout=5000)
            page.wait_for_selector('#dispatch .dispatch-model button[data-model="claude-opus-5"][aria-pressed="true"]',
                                   timeout=5000)
            assert _started("luna") == 0, "a press is a setting, not a launch"
            # The card's own `model` row is current at once, and reading it read no issue.
            page.wait_for_function(
                """() => document.querySelector('#dispatch .dispatch-row[data-row="model"] .dr-value')
                         .textContent === 'opus-5 · fleet.models.luna'""", timeout=5000)
            assert fetched == ["RDSD-118"], fetched

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
    argv = spawns["launched"][0]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "claude-opus-5", argv


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
            assert lit == [["luna", True, False, "true"], ["mars", False, True, "false"],
                           ["sol", False, True, "false"]], lit

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
def test_a_refusal_on_an_open_tile_lands_on_the_tile_and_the_rail_note_stays_empty(
        fleet_home, tmp_path, spawns, monkeypatch):
    """The card is one element with two homes. On a tile that is on the glass -- the grid's every
    tile once, the open one now (#232) -- it draws in the tile that took the drop, exactly where
    #164's tests find it, and a refusal is written on that card -- never under a rail the operator
    is not looking at.

    In a pane's slot the card's keys are its own (#368). Here the ticket is written well and luna
    is set to a model Copilot CLI 1.0.88 no longer lists, so the model is the card's one thin row:
    its why is the note, the keyboard is on the pressed pill, and `h`, `a` and `j` pressed there
    hide nothing, approve nothing and walk nowhere. `more…` opens the model card and it stays open;
    a press there is what the session menu then says a new session starts on."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _fleet(tmp_path)
    S.update_window("main", open="luna")
    PF.write_cache({"issues": {"RDSD-118": {
        "description": ("The nightly refresh of the UAT semantic model takes over forty minutes and "
                        "the team cannot validate it before standup, so every morning starts late. "
                        "Make it finish inside fifteen minutes.\n"
                        "Acceptance criteria\n"
                        "- the refresh completes in under fifteen minutes\n"
                        "- no partition is dropped\n"),
        "issuetype": "", "comments": 0, "attachments": 0, "error": "", "at": time.time()}}})
    _seed_models()
    cfg = C.load()
    C.put_leaf(cfg, "fleet.models", "luna", {"model": "claude-opus-4.6"})
    C.save(cfg)
    # A write luna is waiting on: `a` from anywhere on the desk would approve it.
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    approval.require("jira-transition", "RDSD-118: To Do -> In Progress", {"key": "RDSD-118"},
                     ticket="RDSD-118", timeout=0)
    monkeypatch.delenv(registry.AGENT_ENV)
    assert [r["repo"] for r in approval.pending()] == ["luna"]

    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
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

            # #368: the model is the one thin row; its why is the note, and the keyboard is on the
            # pressed pill rather than in the brief.
            page.wait_for_function(
                "() => document.querySelector('#dispatch .verdict').textContent.trim() !== 'reading…'", timeout=5000)
            assert page.inner_text("#dispatch .verdict").strip().lower() == "thin"
            thin = page.evaluate("""() => [...document.querySelectorAll('#dispatch .dispatch-row.r-thin .dr-name')]
                .map(e => e.textContent)""")
            assert thin == ["model"], thin
            page.wait_for_function(
                """() => document.activeElement.matches('#dispatch .dispatch-model button[aria-pressed="true"]')""",
                timeout=5000)
            assert page.evaluate("document.activeElement.dataset.model") == "claude-opus-4.6"
            assert page.get_attribute("#dispatch .dispatch-note", "role") == "status"
            note = page.inner_text("#dispatch .dispatch-note")
            assert note == "not in copilot 1.0.88's list — the turn may fail at start", note

            # A desk key pressed on a dispatch pill is the card's: nothing hidden, nothing approved,
            # the keyboard where it was and the same pane open.
            for key in ("h", "a", "j"):
                page.keyboard.press(key)
            assert page.evaluate("document.activeElement.dataset.model") == "claude-opus-4.6"
            assert not page.evaluate("document.querySelector('.tile[data-repo=\"luna\"]').classList.contains('is-hidden')")
            assert page.is_visible(".tile[data-repo='luna'] .dispatch-slot #dispatch")
            assert S.desk_state()["arrangement"]["hidden"] == []
            assert [r["repo"] for r in approval.pending()] == ["luna"], "a key on a pill approved the write"
            assert page.evaluate("document.querySelector('.tile.is-solo[data-tier=\"full\"]').dataset.repo") == "luna"

            # `more…` opens the model card, and the click that opened it does not close it.
            page.click("#dispatch .mp-more")
            page.wait_for_selector("#modelcard:not([hidden])", timeout=5000)
            page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")
            assert page.is_visible("#modelcard") and page.inner_text("#mc-repo") == "luna"
            page.wait_for_selector('#modelcard button[data-model="claude-opus-5"]', timeout=5000)
            page.click('#modelcard button[data-model="claude-opus-5"]')
            assert _eventually(lambda: _luna_model() == "claude-opus-5"), "the model card's press wrote nothing"
            # The dispatch card under it says so at once: its `model` row is current and ready, and
            # with the model the card's one thin row, the card is ready and its button says Start.
            page.wait_for_function(
                """() => { const li = document.querySelector('#dispatch .dispatch-row[data-row="model"]');
                  return li.querySelector('.dr-value').textContent === 'opus-5 · fleet.models.luna'
                    && li.classList.contains('r-ready') && !li.querySelector('.dr-why'); }""", timeout=5000)
            assert page.inner_text("#dispatch .verdict").strip().lower() == "ready"
            assert page.inner_text("#dispatch .dispatch-go").strip() == "Start"

            # The session menu says what a new session and a console start on.
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="luna"] .sm-new .sm-model').textContent === 'opus-5'""",
                timeout=5000)
            page.keyboard.press("Escape")
            page.wait_for_selector("#modelcard[hidden]", state="attached", timeout=5000)
            page.click(".tile[data-repo='luna'] .spill")
            page.wait_for_selector(".tile[data-repo='luna'] .sm-new .sm-model", state="visible", timeout=5000)
            assert page.inner_text(".tile[data-repo='luna'] .sm-new .sm-model") == "opus-5"
            assert page.inner_text(".tile[data-repo='luna'] .sm-console .sm-model") == "opus-5"
            assert page.inner_text(".tile[data-repo='luna'] .sm-console .sm-console-label") == "open in a console"
            assert "fleet.models.luna" in page.get_attribute(".tile[data-repo='luna'] .sm-new .sm-model", "title")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert not spawns["launched"], "nothing here is a start"
