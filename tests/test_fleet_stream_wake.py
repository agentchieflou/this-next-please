"""A config write the server makes reaches every open stream at once, ahead of the pass's other work
(#348), and /settings hears the theme without every agent's history.

`stream_events` looked at config.json's mtime once per pass and then slept a whole tick, so a skin
chosen in one window reached the others a tick later, and a woken pass would still have run the
polls, the fold and every agent's read before the theme. `act()` read-modify-wrote config.json with
no lock beside the poller's Jira flavour write on the stream thread, so two writers could lose one.

No sleeps: every wait is a `threading.Event` with a deadline.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from types import SimpleNamespace

import pytest

from agentdata import config as C
from agentdata.fleet import events as E
from agentdata.fleet import poll as P
from agentdata.fleet import serve as S

from test_fleet_ink import (_desk_of, _serve, _stop, fleet_home,  # noqa: F401
                            _own_desk_globals)


class Frames:
    """A stream's `write`: every chunk, the `theme` payloads, and an Event per theme frame heard."""

    def __init__(self, on_theme=None):
        self.chunks: list[str] = []
        self.themes: list[dict] = []
        self.heard = [threading.Event() for _ in range(6)]
        self.on_theme = on_theme

    def __call__(self, chunk: str) -> None:
        self.chunks.append(chunk)
        if chunk.startswith("event: theme\n"):
            self.themes.append(json.loads(chunk.split("data: ", 1)[1]))
            if self.on_theme:
                self.on_theme(len(self.themes))
            self.heard[min(len(self.themes), len(self.heard)) - 1].set()

    def kinds(self, kind: str) -> int:
        return sum(1 for c in self.chunks if f"event: {kind}\n" in c)


def _stream(write, stop, **kw):
    t = threading.Thread(target=S.stream_events, args=({}, stop, write), kwargs=kw, daemon=True)
    t.start()
    return t


def _config(fleet_home, **cfg):
    (fleet_home.parent / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")


def _end(stop, t):
    stop.set()
    t.join(5)
    assert not t.is_alive()


def test_a_config_write_through_the_server_wakes_an_open_stream(fleet_home, tmp_path):
    _config(fleet_home, theme={"skin": "none"})
    frames, stop = Frames(), threading.Event()
    t = _stream(frames, stop, tick=30, polls=False)
    try:
        assert frames.heard[0].wait(10), "no first theme frame"
        t0 = time.monotonic()
        S.act("theme", {"skin": "voxel:nether"})
        assert frames.heard[1].wait(2), "the write waited for the tick"
        print(f"\n  frame after the write: {1000 * (time.monotonic() - t0):.1f} ms")
        assert frames.themes[1]["skin"] == "voxel:nether"
    finally:
        _end(stop, t)


def test_a_config_write_reaches_the_stream_before_the_passs_other_work(fleet_home, tmp_path, monkeypatch):
    _desk_of(tmp_path, ("alpha",))
    _config(fleet_home, theme={"skin": "none"})
    calls, blocked, release = [], threading.Event(), threading.Event()

    def poll_tick(now=None):
        calls.append(now)
        if len(calls) >= 2:
            blocked.set()
            release.wait(10)
        return []

    monkeypatch.setattr(S, "poll_tick", poll_tick)
    frames, stop = Frames(), threading.Event()
    t = _stream(frames, stop, tick=30, polls=True)
    try:
        assert frames.heard[0].wait(10), "no first theme frame"
        S.act("theme", {"skin": "glass:smoke"})
        assert frames.heard[1].wait(2), "the frame waited for the pass's other work"
        assert not release.is_set() and len(calls) <= 2, calls
    finally:
        release.set()
        _end(stop, t)


def test_a_write_between_two_passes_is_not_lost(fleet_home, tmp_path):
    _config(fleet_home, theme={"skin": "none"})

    def write_now(n):
        if n == 1:
            S.act("theme", {"skin": "glass:noir"})

    frames, stop = Frames(on_theme=write_now), threading.Event()
    t = _stream(frames, stop, tick=30, polls=False)
    try:
        assert frames.heard[0].wait(10), "no first theme frame"
        assert frames.heard[1].wait(2), "a write made while the frame was written was lost"
        assert frames.themes[1]["skin"] == "glass:noir"
    finally:
        _end(stop, t)


def test_a_terminal_write_still_arrives_on_the_tick(fleet_home, tmp_path):
    _config(fleet_home, theme={"skin": "none"})
    frames, stop = Frames(), threading.Event()
    t = _stream(frames, stop, tick=0.05, polls=False)
    try:
        assert frames.heard[0].wait(10), "no first theme frame"
        cfg = C.load()
        cfg["theme"] = {"default": "reds", "skin": "voxel:nether"}
        C.save(cfg)                                   # as `ad-theme set` does: no `act`, no wake
        assert frames.heard[1].wait(2), "a write made outside the server never arrived"
        assert frames.themes[1]["skin"] == "voxel:nether"
    finally:
        _end(stop, t)


def test_a_waiting_stream_stops_with_the_server(fleet_home, tmp_path):
    _config(fleet_home, theme={"skin": "none"})
    frames, stop = Frames(), threading.Event()
    t = _stream(frames, stop, tick=30, polls=False)
    assert frames.heard[0].wait(10), "no first theme frame"
    t0 = time.monotonic()
    stop.set()
    t.join(0.5)
    print(f"\n  stopped in {1000 * (time.monotonic() - t0):.1f} ms")
    assert not t.is_alive(), "a stream waiting a tick did not see the server stop"


def test_two_windows_writing_at_once_lose_nothing(fleet_home, tmp_path, monkeypatch):
    """The first round is made to interleave, deterministically: the theme write has loaded the
    config and waits (a deadline, not a sleep) for the settings write to be saved. With the lock the
    settings write cannot start, the deadline passes, and nothing is lost; without it the theme write
    saves what it loaded, and the settings value with it is gone. Then 50 rounds each, free-running."""
    _config(fleet_home, theme={"skin": "none"}, fleet={"approval_timeout": 59})
    real_load, real_save = C.load, C.save
    saved: list[int] = []
    loaded, other_saved = threading.Event(), threading.Event()
    threads: dict[str, threading.Thread] = {}

    def load(*a, **kw):
        cfg = real_load(*a, **kw)
        if threading.current_thread() is threads.get("theme") and not loaded.is_set():
            loaded.set()
            other_saved.wait(1.0)
        return cfg

    def save(cfg, *a, **kw):
        out = real_save(cfg, *a, **kw)
        saved.append(int(C.get(cfg, "fleet.approval_timeout") or 0))
        if threading.current_thread() is threads.get("settings"):
            other_saved.set()
        return out

    monkeypatch.setattr(C, "load", load)
    monkeypatch.setattr(C, "save", save)
    skins = ["glass:smoke", "glass:noir", "voxel:nether", "farmstead:daytime"]
    errors: list[BaseException] = []

    def theme_writer():
        try:
            for i in range(50):
                S.act("theme", {"skin": skins[i % len(skins)]})
        except BaseException as e:            # noqa: BLE001 - reported below
            errors.append(e)

    def settings_writer():
        try:
            assert loaded.wait(5), "the theme write never loaded"
            for i in range(50):
                S.act("settings", {"set": [{"key": "fleet.approval_timeout", "value": 60 + i}]})
        except BaseException as e:            # noqa: BLE001
            errors.append(e)

    threads["theme"] = threading.Thread(target=theme_writer, daemon=True)
    threads["settings"] = threading.Thread(target=settings_writer, daemon=True)
    for th in threads.values():
        th.start()
    for th in threads.values():
        th.join(30)
    assert not errors, errors
    final = real_load()
    assert final["fleet"]["approval_timeout"] == 109, final
    assert final["theme"]["skin"] == skins[49 % len(skins)], final
    went_back = [(i, a, b) for i, (a, b) in enumerate(zip(saved, saved[1:])) if b < a]
    assert not went_back, f"a save put an older approval_timeout back: {went_back[:3]}"


def test_the_jira_flavour_write_holds_the_config_lock(fleet_home, tmp_path, monkeypatch):
    """The detection is a Jira request and runs outside the lock; the flavour is then written under
    it, on a fresh read -- so a palette chosen while the request was out is not written back over."""
    from agentdata.connectors import jira_api as J

    _config(fleet_home, theme={"skin": "none"})
    seen = {}

    def detect_flavor(creds, cfg, budget=None):
        seen["during_request"] = C.LOCK.locked()
        S.act("theme", {"skin": "voxel:nether"})           # a window's write while the request is out
        return SimpleNamespace(creds=creds, flavor=SimpleNamespace(kind="server", auth="bearer",
                                                                   api="2")), {}

    real_save = C.save

    def save(cfg, *a, **kw):
        if "jira" in cfg:
            seen["at_save"] = C.LOCK.locked()
        return real_save(cfg, *a, **kw)

    monkeypatch.setattr(J, "load_credentials", lambda cfg: SimpleNamespace(base_url="https://jira.invalid"))
    monkeypatch.setattr(J, "detect_flavor", detect_flavor)
    monkeypatch.setattr(J, "Jira", lambda *a, **kw: None)
    monkeypatch.setattr(C, "save", save)
    P.default_jira_client(budget=None)
    got = C.load()
    assert seen == {"during_request": False, "at_save": True}, seen
    assert got["theme"]["skin"] == "voxel:nether", "the flavour write put the old palette back"
    assert got["jira"]["flavor"] == "server", got

    # ...and racing `act("theme")` from another thread, 50 times, loses nothing either.
    monkeypatch.setattr(J, "detect_flavor", lambda creds, cfg, budget=None: (SimpleNamespace(
        creds=creds, flavor=SimpleNamespace(kind="server", auth="bearer", api="2")), {}))
    cfg = C.load()
    cfg.pop("jira", None)
    real_save(cfg)
    errors: list[BaseException] = []

    def flavours():
        try:
            for _ in range(50):
                with C.LOCK:                  # forget the flavour, so the next call detects it
                    c = C.load()
                    c.pop("jira", None)
                    real_save(c)
                P.default_jira_client(budget=None)
        except BaseException as e:            # noqa: BLE001
            errors.append(e)

    skins = ["glass:smoke", "glass:noir"]
    th = threading.Thread(target=flavours, daemon=True)
    th.start()
    for i in range(50):
        S.act("theme", {"skin": skins[i % 2]})
    th.join(30)
    assert not errors, errors
    assert C.load()["theme"]["skin"] == skins[49 % 2]


def _history(names=("alpha", "beta"), n=50):
    for name in names:
        E.append(name, [E.event(name, "note", {"text": f"line {i}"}) for i in range(n)])


def test_a_theme_only_stream_sends_no_agent_frames(fleet_home, tmp_path):
    _desk_of(tmp_path, ("alpha", "beta"))
    _history()
    _config(fleet_home, theme={"skin": "voxel:nether"})
    everything, theme_only = Frames(), Frames()
    S.stream_events({}, threading.Event(), everything, once=True, polls=False)
    S.stream_events({}, threading.Event(), theme_only, once=True, polls=False, agents=False)
    assert everything.kinds("agent") >= 100, everything.kinds("agent")
    assert theme_only.kinds("agent") == 0 and theme_only.themes[0]["skin"] == "voxel:nether"

    # And over HTTP: `?frames=theme` is that stream. Agent frames come before the theme in a pass,
    # so reading up to the theme frame is reading everything the first pass sent.
    server, token, port = _serve()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/events?t={token}&frames=theme",
                                    timeout=10) as r:
            head = ""
            while "event: theme\n" not in head:
                line = r.readline().decode("utf-8")
                assert line, head
                head += line
    finally:
        _stop(server)
    assert "event: agent" not in head, head[:400]


@pytest.mark.browser
def test_the_settings_page_hears_no_agent_frames(fleet_home, tmp_path):
    from test_fleet_desk_browser import launch_chromium

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _desk_of(tmp_path, ("alpha", "beta"))
    _history()
    _config(fleet_home, theme={"skin": "none"})
    count = """(() => {
      window.__agent = 0; window.__theme = 0;
      const ES = window.EventSource;
      window.EventSource = function (u, o) { const s = new ES(u, o);
        s.addEventListener('agent', () => window.__agent++);
        s.addEventListener('theme', () => window.__theme++); return s; };
      window.EventSource.prototype = ES.prototype;
    })();"""
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page()
            page.add_init_script(count)
            page.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
            page.wait_for_function("() => window.__theme >= 1", timeout=15000)
            agents = page.evaluate("() => window.__agent")
            browser.close()
    finally:
        _stop(server)
    assert agents == 0, f"/settings downloaded {agents} agent frames to hear one theme frame"


@pytest.mark.browser
def test_another_window_follows_a_skin_chosen_in_settings(fleet_home, tmp_path):
    from agentdata.fleet import probe as PR
    from test_fleet_desk_browser import launch_chromium
    from test_fleet_ink import _facts
    from test_fleet_theme_switch import SETTLED

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    PR.record(_facts(shell="browser"))
    _desk_of(tmp_path, ("alpha", "beta"))
    _config(fleet_home, theme={"skin": "voxel:nether"})
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            desk, settings = context.new_page(), context.new_page()
            errors = []
            for page in (desk, settings):
                page.on("pageerror", lambda e: errors.append(str(e)))
            desk.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            desk.wait_for_function(SETTLED + " && document.body.dataset.skin === 'voxel'", timeout=15000)
            settings.goto(f"http://127.0.0.1:{port}/settings?t={token}", wait_until="domcontentloaded")
            settings.wait_for_function("() => document.getElementById('skin').value === 'voxel:nether'",
                                       timeout=15000)
            t0 = time.monotonic()
            settings.select_option("#skin", "farmstead:daytime")
            desk.wait_for_function("() => document.body.dataset.skin === 'farmstead'", timeout=15000)
            ms = 1000 * (time.monotonic() - t0)
            print(f"\n  the desk followed a skin chosen in /settings after {ms:.0f} ms")
            assert not errors, errors
            browser.close()
    finally:
        _stop(server)
    assert re.match(r"farmstead", S.theme_state()["skin"])
