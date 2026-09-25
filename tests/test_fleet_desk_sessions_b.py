"""Sessions Slice B (#172) test suite: the desk comes back.

Acceptance criteria:
* `reset()` stops erasing `desk.json` on a clean shutdown: `drop_handles()` vs `forget_desk()`.
* A window has a name: `?w=<name>` in URL and `windows[name]` in `desk.json`.
* `POST /api/window {w, ...}` as the one write.
* `GET /open?w=`, `ad-fleet open --window <w>` and `--all`.
* Two windows named `left` and `main` keep different focus-mode states across a restart on a new port
  (their widths since #234, which made the needs-only filter a preset of widths).
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


# ----------------------------------------------------------- shutdown and desk persistence


def test_serve_run_finally_preserves_desk_json(fleet_home, tmp_path):  # noqa: F811
    """A clean shutdown (`serve.run()` running to its `finally:`) must preserve `desk.json`.
    Previously `finally:` called `reset()`, which blanked `desk.json` on clean exit.
    """
    repo = make_project(tmp_path / "alpha")
    Registry().add(repo, name="alpha")

    # Set up desk state
    S.select(selected="alpha")
    S.arrange(order=["alpha"], pinned=["alpha"])
    S.update_window("main", focus=True, open="alpha", section="board")

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
    assert after["arrangement"]["order"] == ["alpha"]
    assert after["windows"]["main"]["open"] == "alpha"
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


URL = "http://127.0.0.1:8765/?t=tok"


def _write_desk(text: str) -> None:
    """`desk.json` as the server left it, in the isolated fleet directory."""
    os.makedirs(fleet_dir(), exist_ok=True)
    with open(os.path.join(fleet_dir(), S.DESK_FILE), "w", encoding="utf-8") as f:
        f.write(text)


def _open_all(monkeypatch, capsys) -> tuple[str, list[str]]:
    """`ad-fleet open --all --in browser` on a desk that is already up: what it printed, and every
    URL it handed the browser."""
    from agentdata import cli_fleet

    urls = []
    monkeypatch.setattr(O, "current_desk", lambda port=8765: ({"port": 8765, "url": URL}, "already up"))
    monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: urls.append(url) or True)
    assert cli_fleet.main(["open", "--all", "--in", "browser"]) == 0
    return capsys.readouterr().out, urls


def test_cli_open_all_opens_every_window_desk_json_remembers(fleet_home, monkeypatch, capsys):  # noqa: F811
    """#172 read `desk.json` through `.registry` and `.serve`, which do not exist beside
    `cli_fleet`, and `except Exception` took the ImportError for an empty desk: `--all` opened `main`
    alone whatever the desk remembered. Written by hand rather than through `S.update_window`:
    `ad-fleet open` runs in a process of its own, and has only the file."""
    _write_desk(json.dumps({"windows": {"main": {"open": "alpha"}, "left": {"open": "beta"}}}))

    out, urls = _open_all(monkeypatch, capsys)

    assert "windows[2]: main,left" in out, out
    assert "opened[2]: default browser,default browser" in out, out
    assert urls == [f"{URL}&w=main", f"{URL}&w=left"]


def test_cli_open_all_leaves_the_ide_views_to_their_ide(fleet_home, monkeypatch, capsys):  # noqa: F811
    """`pycharm` and `vscode` are the IDE views' own records (#230), and nothing outside an IDE can
    point its view at a URL. A browser tab under either name would share the view's record -- and,
    once `ad-fleet probe --open pycharm` marks it (#247), go to the probe in the tool window's place
    and record the browser's WebGL as PyCharm's. `--all` says what it left instead."""
    _write_desk(json.dumps({"windows": {"main": {}, "pycharm": {"probe": int(time.time())},
                                        "left": {}, "vscode": {}}}))

    out, urls = _open_all(monkeypatch, capsys)

    assert "windows[2]: main,left" in out, out
    assert "skipped[2]: pycharm,vscode" in out, out
    assert urls == [f"{URL}&w=main", f"{URL}&w=left"]


@pytest.mark.parametrize("text,skipped", [
    ("{not json", "skipped[0]:"),
    (json.dumps({"windows": {"pycharm": {}}}), "skipped[1]: pycharm"),
], ids=["unreadable", "only-an-ide-view"])
def test_cli_open_all_opens_main_when_there_is_nothing_else_to_open(  # noqa: F811
        fleet_home, monkeypatch, capsys, text, skipped):
    """`--all` always puts the dashboard in front of the operator. The `except` is narrowed to what
    reading a file raises, not removed: a `desk.json` that is not JSON is still `main`, not a
    traceback."""
    _write_desk(text)

    out, urls = _open_all(monkeypatch, capsys)

    assert "windows[1]: main" in out, out
    assert skipped in out, out
    assert urls == [f"{URL}&w=main"]


def test_cli_open_window_and_all(fleet_home, monkeypatch):  # noqa: F811
    from agentdata import cli_fleet

    S.update_window("main", focus=True)
    # `seen` is what a page writes first. `focus=False` alone is the default, which is never written,
    # so `left` would be a window the server knows and `desk.json` does not.
    S.update_window("left", focus=False, seen="2026-09-11T12:00:00")

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
    # What `--all` opened, and only that: `opened[-2:]` also took in the `--window left` above, which
    # is how `--all` opening `main` alone passed here from #172 on.
    all_wins = [w for _, w in opened[1:]]
    assert "main" in all_wins and "left" in all_wins


def test_cli_open_in_edge_is_a_window_of_its_own(fleet_home, monkeypatch):  # noqa: F811
    """#230, #232: every window without `?w=` shared `main`, so an Edge window on a fourth monitor
    followed every click made in the browser tab. `--in edge` names its own record unless
    `--window` names another; a plain browser tab is still `main`."""
    from agentdata import cli_fleet

    opened = []
    monkeypatch.setattr(O, "running", lambda: {"port": 8765, "url": "http://127.0.0.1:8765/?t=tok"})
    monkeypatch.setattr(O, "open_in", lambda where, record, launcher_dir="", window="":
                        opened.append((where, window)) or {"opened": f"window {window}"})
    parser = cli_fleet.build_parser()
    for argv, want in ((["open", "--in", "edge"], ("edge", "edge")),
                       (["open", "--in", "edge", "--window", "left"], ("edge", "left")),
                       (["open"], ("browser", ""))):
        assert cli_fleet.cmd_open(parser.parse_args(argv)) == 0
        assert opened[-1] == want, argv


# ------------------------------------------------------------- window record & POST /api/window


def test_update_window_api_and_desk_state(fleet_home):  # noqa: F811
    """The one write a window makes. `zoomed`, `layout`, `view` and `screen` still arrive from a page
    older than #232 and are not kept: a field one window writes and nothing reads is the snap-back
    waiting for a reader (#230)."""
    res = S.act("window", {
        "w": "right",
        "focus": True,
        "open": "omega",
        "zoomed": "omega",
        "layout": "grid",
        "view": "agents",
        "screen": 2,
        "section": "drawer",
        "held": ["repo-a", "repo-b"],
        "read": {"repo-a": 15},
        "seen": "2026-09-11T12:00:00",
    })
    win = res["windows"]["right"]
    assert win["focus"] is True
    assert win["open"] == "omega"
    for gone in ("zoomed", "layout", "view", "screen"):
        assert gone not in win, gone
    assert win["section"] == "drawer"
    assert win["held"] == ["repo-a", "repo-b"]
    assert win["read"] == {"repo-a": 15}
    assert win["seen"] == "2026-09-11T12:00:00"

    # Must be written to desk.json
    disk = json.loads(open(os.path.join(fleet_dir(), S.DESK_FILE), encoding="utf-8").read())
    assert disk["windows"]["right"]["open"] == "omega"
    assert set(disk["windows"]["right"]) <= set(S.WINDOW_FIELDS)


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
    # A *painted* tile, not the first one in the DOM. A bare `.tile` wait resolves to the first match
    # and then waits for that one to be visible -- which, when it is hidden, it never will be. (In
    # the column only the open agent was on the glass; every agent is a pane since #233, but a
    # hidden one still is not.)
    page.wait_for_selector(".tile:visible", timeout=15000)
    page.wait_for_timeout(500)
    return browser, page, errors


@pytest.mark.browser
def test_two_named_windows_keep_different_widths_across_restart(fleet_home, tmp_path):  # noqa: F811
    """Acceptance criterion: two windows named `left` and `main` keep different states across a
    server restart on a new port. The state was the needs-only filter, one per window; the filter is
    the *needs me* preset since #234, one write of the window's own widths -- so what each window
    keeps across the restart is its widths: `main` given every agent an even share, `left` never
    given any and drawing its open pane wide."""
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

    wide = "() => document.querySelectorAll('#grid .tile.is-solo').length"
    with sync_playwright() as p:
        # Window 'main': every agent an even share.
        b1, page_main, errs = _page(p, f"http://127.0.0.1:{p1}/?t={t1}&layout=grid&w=main")
        assert not errs, errs
        page_main.locator("#preset-all").click()
        page_main.wait_for_function(f"() => ({wide})() === 2", timeout=8000)
        # Painted before it is written (#219): the record, not the pixels, is waited on.
        deadline = time.monotonic() + 10
        while not (S.desk_state()["windows"].get("main") or {}).get("widths"):
            assert time.monotonic() < deadline, "the widths never reached the server"
            time.sleep(0.05)
        b1.close()

        # Window 'left': never given widths, so one pane is open and the other a rail.
        b2, page_left, errs = _page(p, f"http://127.0.0.1:{p1}/?t={t1}&layout=grid&w=left")
        assert not errs, errs
        page_left.wait_for_function(f"() => ({wide})() === 1", timeout=8000)
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
            # Reopen window 'main' on the new port: both agents still share the row.
            b1, page_main, errs = _page(p, f"http://127.0.0.1:{p2}/?t={t2}&layout=grid&w=main")
            assert not errs, errs
            page_main.wait_for_function(f"() => ({wide})() === 2", timeout=8000)
            b1.close()

            # Reopen window 'left' on the new port: still one open and one rail.
            b2, page_left, errs = _page(p, f"http://127.0.0.1:{p2}/?t={t2}&layout=grid&w=left")
            assert not errs, errs
            page_left.wait_for_function(f"() => ({wide})() === 1", timeout=8000)
            assert page_left.evaluate("() => myWidths") is None
            b2.close()
    finally:
        s2.stopping.set()
        s2.shutdown()
        s2.server_close()


@pytest.mark.browser
def test_window_reopens_with_same_open_agent_after_restart(fleet_home, tmp_path):  # noqa: F811
    """Acceptance criterion: a rendered-page test reads the same arrangement and selection,
    and the same open agent in the same named window across server restart. It was the grid's
    zoomed tile; the zoom went with the grid (#232), and `open` is what a window keeps."""
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
        # Open beta from its rail. Waited for rather than slept through: 300ms is the page's budget
        # on an idle machine, and under `-n auto` on a Windows runner four browsers share the cores
        # -- which is the load talking, not the page. The selectors are the assertions.
        page.locator('.tile[data-repo="beta"] .pane-rail').click()
        page.wait_for_selector('.tile[data-repo="beta"].is-solo', timeout=15000)
        page.wait_for_function("() => windowWrites === 0", timeout=15000)
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
            # Beta is the one open, from the window's own record and not the address.
            page.wait_for_selector('.tile[data-repo="beta"].is-solo', timeout=15000)
            assert "is-solo" not in page.locator('.tile[data-repo="alpha"]').get_attribute("class")
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
            b, page, errs = _page(p, f"http://127.0.0.1:{port}/?t={token}&layout=grid&w=main")
            assert not errs, errs

            # Strip is visible and has exactly 2 lines
            strip = page.locator("#away-strip")
            page.wait_for_selector("#away-strip:not([hidden])", timeout=5000)
            lines = page.locator("#away-lines li")
            assert lines.count() == 2, f"expected 2 away lines, got {lines.count()}"

            # Click dismiss. The strip leaves over `--motion-base` now (#216), so it is still
            # painted for a fifth of a second after the click -- which is the point of the
            # animation. Wait for the attribute the script sets rather than for a clock.
            page.locator("#dismiss-away").click()
            page.wait_for_selector("#away-strip[hidden]", state="attached", timeout=5000)
            page.wait_for_timeout(400)
            assert strip.is_hidden()
            b.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
