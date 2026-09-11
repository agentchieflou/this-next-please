"""Sessions Slice B (#172) test suite: the desk comes back.

Acceptance criteria:
* `reset()` stops erasing `desk.json` on a clean shutdown: `drop_handles()` vs `forget_desk()`.
* A window has a name: `?w=<name>` in URL and `windows[name]` in `desk.json`.
* `POST /api/window {w, ...}` as the one write.
* `GET /open?w=`, `ad-fleet open --window <w>` and `--all`.
* Two windows named `left` and `main` keep different focus-mode states across a restart on a new port.
* A tab open across a server restart draws the new run's tiles without a hand-typed URL.
* *Since you were away*: one line per tile that changed since, dismissable.
* Transcript pane scroll position preserved across events when scrolled up, and across reload.
"""
from __future__ import annotations
import json
import os
import threading
import time
import urllib.error
import urllib.request
import pytest

from agentdata.fleet import events as E
from agentdata.fleet import opener as O
from agentdata.fleet import serve as S
from agentdata.fleet.registry import Registry, fleet_dir

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium
from test_fleet_desk_regressions import _drain_and_age
from test_fleet_events import fleet_home  # noqa: F401


@pytest.fixture(autouse=True)
def _own_desk_globals(monkeypatch):
    """Every test here gets the desk module's globals to itself, and gives them back.

    `_selection` and `_desk_loaded` are process-wide, which is right in production -- one
    `ad-fleet serve` has one fleet directory for its life, and `_fresh()` drops the handles if that
    ever changes. In a suite it is not: each test gets a fresh temporary fleet directory, and
    `_ensure_desk_loaded` returns early on the flag the *previous* test set, so the second test in
    the file inherits the first one's selection and window records instead of reading its own
    `desk.json`. Every test in this file passed alone and two of them failed when the file ran
    whole, which is exactly what that looks like from the outside.
    """
    monkeypatch.setattr(S, "_desk_loaded", False)
    monkeypatch.setattr(S, "_selection", {
        "selected": "", "screens": [], "version": 0, "at": "",
        "arrangement": {"grid": {"order": [], "size": {}, "pinned": []},
                        "roles": {"order": []}, "screens": {"order": []}},
        "windows": {},
    })
    monkeypatch.setattr(S, "_desk", dict(S._desk, dir="", poller=None, inbox=None,
                                         catalogue=None, last_tick=0.0, last_fold=0.0))


# ----------------------------------------------------------- shutdown and desk persistence


def test_serve_run_finally_preserves_desk_json(fleet_home, tmp_path):  # noqa: F811
    """A clean shutdown (`serve.run()` running to its `finally:`) must preserve `desk.json`.
    Previously `finally:` called `reset()`, which blanked `desk.json` on clean exit.
    """
    repo = make_project(tmp_path / "alpha")
    Registry().add(repo, name="alpha")

    # Set up desk state
    S.select(selected="alpha")
    S.arrange("grid", order=["alpha"], pinned=["alpha"])
    S.update_window("main", focus=True, zoomed="alpha", section="board")

    desk_file = os.path.join(fleet_dir(), S.DESK_FILE)
    assert os.path.isfile(desk_file)
    before = json.loads(open(desk_file, encoding="utf-8").read())
    assert before["selected"] == "alpha"
    assert before["windows"]["main"]["focus"] is True

    # Build server and invoke run(), raising KeyboardInterrupt
    server, token = S.build(0)

    class MockInterruptServer:
        def __init__(self, real):
            self.real = real
            self.stopping = real.stopping

        def serve_forever(self, poll_interval=0.2):
            raise KeyboardInterrupt()

        def shutdown(self):
            pass

        def server_close(self):
            self.real.server_close()

    S.run(MockInterruptServer(server))

    # desk.json must still exist and retain the saved state
    assert os.path.isfile(desk_file), "desk.json was deleted or not preserved on shutdown"
    after = json.loads(open(desk_file, encoding="utf-8").read())
    assert after["selected"] == "alpha"
    assert after["arrangement"]["grid"]["order"] == ["alpha"]
    assert after["windows"]["main"]["zoomed"] == "alpha"
    assert after["windows"]["main"]["focus"] is True


def test_drop_handles_vs_forget_desk(fleet_home, tmp_path):  # noqa: F811
    """`drop_handles()` drops runtime handles without erasing desk.json;
    `forget_desk()` blanks desk.json (used only when fleet dir changes).
    """
    S.select(selected="beta")
    S.update_window("left", focus=False, section="unsorted")

    desk_file = os.path.join(fleet_dir(), S.DESK_FILE)
    data = json.loads(open(desk_file, encoding="utf-8").read())
    assert data["selected"] == "beta"

    # drop_handles preserves desk.json
    S.drop_handles()
    data_after_drop = json.loads(open(desk_file, encoding="utf-8").read())
    assert data_after_drop["selected"] == "beta"
    assert data_after_drop["windows"]["left"]["section"] == "unsorted"

    # forget_desk blanks desk.json
    S.forget_desk()
    data_after_forget = json.loads(open(desk_file, encoding="utf-8").read())
    assert data_after_forget["selected"] == ""
    assert data_after_forget["windows"] == {}


# ----------------------------------------------------------------- /open and CLI open


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def test_open_preserves_query_parameters_and_attaches_token(fleet_home):  # noqa: F811
    """`GET /open?w=left&layout=roles&view=agents&screen=1` forwards all params to `/?t=...`."""
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            opener.open(f"http://127.0.0.1:{port}/open?w=left&layout=roles&view=agents&screen=1")
        assert e.value.code == 302
        location = e.value.headers["Location"]
        assert f"t={token}" in location
        assert "w=left" in location
        assert "layout=roles" in location
        assert "view=agents" in location
        assert "screen=1" in location
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def test_cli_open_window_and_all(fleet_home, monkeypatch):  # noqa: F811
    from agentdata import cli_fleet

    S.update_window("main", focus=True)
    S.update_window("left", focus=False)

    opened = []
    monkeypatch.setattr(O, "running", lambda: {"port": 8765, "url": "http://127.0.0.1:8765/?t=tok"})
    monkeypatch.setattr(O, "open_in", lambda where, record, launcher_dir="", window="":
                        opened.append((where, window)) or {"opened": f"window {window}"})

    # Test ad-fleet open --window left
    parser = cli_fleet.build_parser()
    args = parser.parse_args(["open", "--window", "left"])
    res = cli_fleet.cmd_open(args)
    assert res == 0
    assert opened[-1] == ("browser", "left")

    # Test ad-fleet open --all
    args_all = parser.parse_args(["open", "--all"])
    res_all = cli_fleet.cmd_open(args_all)
    assert res_all == 0
    all_wins = [w for _, w in opened[-2:]]
    assert "main" in all_wins and "left" in all_wins


# ------------------------------------------------------------- window record & POST /api/window


def test_update_window_api_and_desk_state(fleet_home):  # noqa: F811
    res = S.act("window", {
        "w": "right",
        "focus": True,
        "zoomed": "omega",
        "section": "drawer",
        "held": ["repo-a", "repo-b"],
        "read": {"repo-a": 15},
        "seen": "2026-09-11T12:00:00",
    })
    win = res["windows"]["right"]
    assert win["focus"] is True
    assert win["zoomed"] == "omega"
    assert win["section"] == "drawer"
    assert win["held"] == ["repo-a", "repo-b"]
    assert win["read"] == {"repo-a": 15}
    assert win["seen"] == "2026-09-11T12:00:00"

    # Must be written to desk.json
    disk = json.loads(open(os.path.join(fleet_dir(), S.DESK_FILE), encoding="utf-8").read())
    assert disk["windows"]["right"]["zoomed"] == "omega"


def test_sessions_b_offline_contract():
    """Offline DOM/assets contract: verify away strip, window record, and HIG scroll rules."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static = os.path.join(root, "agentdata", "fleet", "static")

    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    assert 'id="away-strip"' in html
    assert 'id="away-lines"' in html
    assert 'id="dismiss-away"' in html

    css = open(os.path.join(static, "app.css"), encoding="utf-8").read()
    assert ".away-strip" in css
    assert ".away-line" in css
    assert ".dismiss-away" in css

    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    # W_NAME and ?w=
    assert 'PARAMS.get("w") || "main"' in js
    # saveWindow and rehome
    assert "saveWindow" in js
    assert "rehome" in js
    assert "/open?w=" in js
    # checkAway and applyWindow
    assert "checkAway" in js
    assert "applyWindow" in js
    # focus mode no longer in localStorage
    assert 'localStorage.getItem("fleet.needsonly")' not in js
    assert 'localStorage.setItem("fleet.needsonly"' not in js
    # transcript scroll HIG
    assert "wasAtBottom" in js
    assert "sessionStorage.setItem" in js


# ------------------------------------------------------------------------- browser tests


def _page(p, url):
    browser = launch_chromium(p)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url, wait_until="domcontentloaded")
    # A *painted* tile, not the first one in the DOM. A window that restores a zoom hides every
    # other tile (`app.css` `body.focused .tile:not(.is-focused)`), and a bare `.tile` wait resolves
    # to the first match and then waits for that one to be visible -- which, in exactly the state
    # this file exists to test, it never will be.
    page.wait_for_selector(".tile:visible", timeout=15000)
    page.wait_for_timeout(500)
    return browser, page, errors


@pytest.mark.browser
def test_two_named_windows_keep_different_focus_states_across_restart(fleet_home, tmp_path):  # noqa: F811
    """Acceptance criterion: Two windows named `left` and `main` keep different focus-mode states
    across a server restart on a new port."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    asks = make_project(tmp_path / "asks", phase="blocked", ticket="RDSD-1")
    quiet = make_project(tmp_path / "quiet", phase="done")
    Registry().add(asks, name="asks")
    Registry().add(quiet, name="quiet")
    E.append("asks", [E.event("asks", "started", {"prompt": "Ticket RDSD-1"}, ticket="RDSD-1")])
    E.append("quiet", [E.event("quiet", "started", {"prompt": "Ticket RDSD-9"})])

    # Run Server 1
    s1, t1 = S.build(0)
    th1 = threading.Thread(target=s1.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th1.start()
    p1 = s1.server_address[1]

    with sync_playwright() as p:
        # Window 'main': turn focus mode ON
        b1, page_main, errs = _page(p, f"http://127.0.0.1:{p1}/?t={t1}&w=main")
        assert not errs, errs
        btn_focus = page_main.locator("#focus")
        btn_focus.click()
        page_main.wait_for_timeout(300)
        assert btn_focus.get_attribute("aria-pressed") == "true"
        b1.close()

        # Window 'left': verify focus mode is OFF
        b2, page_left, errs = _page(p, f"http://127.0.0.1:{p1}/?t={t1}&w=left")
        assert not errs, errs
        btn_focus_left = page_left.locator("#focus")
        assert btn_focus_left.get_attribute("aria-pressed") == "false"
        b2.close()

    # Shut down server 1 cleanly (Ctrl-C / shutdown)
    s1.stopping.set()
    s1.shutdown()
    s1.server_close()
    S.forget()
    S.drop_handles()

    # Start Server 2 on a NEW port with a NEW token
    s2, t2 = S.build(0)
    th2 = threading.Thread(target=s2.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th2.start()
    p2 = s2.server_address[1]
    assert p2 != p1

    try:
        with sync_playwright() as p:
            # Reopen window 'main' on new port: focus mode is still ON
            b1, page_main, errs = _page(p, f"http://127.0.0.1:{p2}/?t={t2}&w=main")
            assert not errs, errs
            assert page_main.locator("#focus").get_attribute("aria-pressed") == "true"
            b1.close()

            # Reopen window 'left' on new port: focus mode is still OFF
            b2, page_left, errs = _page(p, f"http://127.0.0.1:{p2}/?t={t2}&w=left")
            assert not errs, errs
            assert page_left.locator("#focus").get_attribute("aria-pressed") == "false"
            b2.close()
    finally:
        s2.stopping.set()
        s2.shutdown()
        s2.server_close()


@pytest.mark.browser
def test_window_reopens_with_same_zoomed_tile_after_restart(fleet_home, tmp_path):  # noqa: F811
    """Acceptance criterion: a rendered-page test reads the same arrangement and selection,
    and the same zoomed tile in the same named window across server restart."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    alpha = make_project(tmp_path / "alpha", phase="done")
    beta = make_project(tmp_path / "beta", phase="blocked", ticket="RDSD-2")
    Registry().add(alpha, name="alpha")
    Registry().add(beta, name="beta")
    E.append("alpha", [E.event("alpha", "started", {})])
    E.append("beta", [E.event("beta", "started", {}, ticket="RDSD-2")])

    s1, t1 = S.build(0)
    th1 = threading.Thread(target=s1.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th1.start()
    p1 = s1.server_address[1]

    with sync_playwright() as p:
        b, page, errs = _page(p, f"http://127.0.0.1:{p1}/?t={t1}&w=main")
        assert not errs, errs
        # Zoom tile beta
        page.locator('.tile[data-repo="beta"] .repo').click()
        page.wait_for_timeout(300)
        assert "focused" in page.locator("body").get_attribute("class")
        assert "is-focused" in page.locator('.tile[data-repo="beta"]').get_attribute("class")
        b.close()

    s1.stopping.set()
    s1.shutdown()
    s1.server_close()
    S.forget()
    S.drop_handles()

    # Start server 2 on new port
    s2, t2 = S.build(0)
    th2 = threading.Thread(target=s2.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    th2.start()
    p2 = s2.server_address[1]

    try:
        with sync_playwright() as p:
            b, page, errs = _page(p, f"http://127.0.0.1:{p2}/?t={t2}&w=main")
            assert not errs, errs
            # Tile beta is zoomed
            assert "focused" in page.locator("body").get_attribute("class")
            assert "is-focused" in page.locator('.tile[data-repo="beta"]').get_attribute("class")
            b.close()
    finally:
        s2.stopping.set()
        s2.shutdown()
        s2.server_close()


@pytest.mark.browser
def test_since_you_were_away_strip(fleet_home, tmp_path):  # noqa: F811
    """Acceptance criterion: A window reopened after two tiles changed state shows two
    `since you were away` lines and no more; four agents working normally show none."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from agentdata.fleet import notify as N

    luna = make_project(tmp_path / "luna", phase="working")
    mars = make_project(tmp_path / "mars", phase="working")
    sol = make_project(tmp_path / "sol", phase="working")
    terra = make_project(tmp_path / "terra", phase="working")
    for r in (luna, mars, sol, terra):
        Registry().add(r, name=os.path.basename(r))
        E.append(os.path.basename(r), [E.event(os.path.basename(r), "started", {})])

    # Timestamp when operator was looking
    past_ts = "2026-09-11T10:00:00"
    now_ts = "2026-09-11T11:00:00"
    S.update_window("main", seen=past_ts)

    # Append notifications: 2 tiles changed state (luna: needs_human, mars: done)
    N._append_log([
        N.notification("luna", "needs_human", "asked a question", at=now_ts),
        N.notification("mars", "done", "finished work", at=now_ts),
    ])

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]

    try:
        with sync_playwright() as p:
            b, page, errs = _page(p, f"http://127.0.0.1:{port}/?t={token}&w=main")
            assert not errs, errs

            # Strip is visible and has exactly 2 lines
            strip = page.locator("#away-strip")
            page.wait_for_selector("#away-strip:not([hidden])", timeout=5000)
            lines = page.locator("#away-lines li")
            assert lines.count() == 2, f"expected 2 away lines, got {lines.count()}"

            # Click dismiss
            page.locator("#dismiss-away").click()
            page.wait_for_timeout(200)
            assert strip.is_hidden()
            b.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
