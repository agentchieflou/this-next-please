"""`/api/models`, the `models` stream frame, and a refresh that never blocks the page (#361).

A page asks for the model list and is answered from the cache, else from the shipped list marked
stale: no request starts the Copilot CLI, which costs 2.5 s on a dev box and more on the laptop. The
CLI is asked on a thread of its own -- once when `ad-fleet serve` or `quickstart` starts, and on
`POST /api/models {refresh: true}` -- and a list that changed reaches every open page as one
`models` frame.

No sleeps. A slow CLI is a copy of the fake copilot whose `help config` answers after 2 s, and every
wait is on a condition with a deadline. Every test that starts a refresh ends with
`models.wait_refresh(10)`, before its fixtures undo the environment the thread was started in.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import threading
import time
import urllib.request

import pytest

from agentdata import cli_fleet, proc, textio
from agentdata.fleet import events as E, models as M, registry, serve as S
from agentdata.fleet.registry import Registry
from tests import fakes

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


@pytest.fixture()
def counted(fleet_home, monkeypatch, tmp_path):
    """The fake copilot on PATH, and the argv of every `proc.run` recorded: a spawn is counted,
    never hidden by a missing CLI."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"])
    calls: list[list[str]] = []
    real = proc.run

    def run(argv, **kw):
        calls.append(list(argv[1:]))
        return real(argv, **kw)

    monkeypatch.setattr(proc, "run", run)
    return calls


@pytest.fixture()
def slow_cli(counted, monkeypatch, tmp_path):
    """`counted`, with a copy of the fake copilot whose `help config` answers after 2 s. The copy's
    transcript is edited, never the shared one."""
    root = tmp_path / "fake"
    shutil.copytree(os.path.join(fakes.HERE, "copilot"), root / "copilot")
    path = root / "copilot" / "transcripts" / "help-config.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["delay"] = 2
    path.write_text(json.dumps(entry), encoding="utf-8")
    monkeypatch.setenv("AGENTDATA_FAKE_DIR", str(root))
    return counted


@pytest.fixture()
def served(fleet_home):
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", token
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _get(base: str, token: str) -> dict:
    with urllib.request.urlopen(f"{base}/api/models?t={token}", timeout=10) as r:
        return json.loads(r.read())


def _post(base: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(f"{base}/api/models?t={token}", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _no_refresh_running() -> None:
    """A refresh another test left running would be joined here instead of started."""
    assert M.wait_refresh(10), "a refresh started before this test is still running"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _cache(ids, *, efforts=("low", "medium", "high"), fetched_at: str = "") -> str:
    """`<fleet dir>/models.json` as a refresh writes it, with an mtime later than the one it had: a
    filesystem's clock may be too coarse to tell two writes in a row apart."""
    path = M.cache_file()
    before = os.stat(path).st_mtime_ns if os.path.exists(path) else 0
    textio.write_json(path, {"source": "help", "cli_version": "1.0.88", "fetched_at": fetched_at or _now(),
                             "models": list(ids), "efforts": list(efforts), "why": ""})
    later = max(os.stat(path).st_mtime_ns, before + 1_000_000_000)
    os.utime(path, ns=(later, later))
    return path


# ------------------------------------------------------------------------ GET /api/models


def test_the_list_is_read_from_a_fresh_cache_and_starts_nothing(served, counted, tmp_path):
    base, token = served
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [E.event("alpha", "assistant_text", {"text": "hi", "model": "o3-mini"},
                               ticket="RDSD-1")])
    _cache(["gpt-5.5", "claude-opus-5"], efforts=["low", "high"])

    got = _get(base, token)
    assert got["ok"] is True and got["refreshing"] is False
    assert got["meta"]["source"] == "help" and got["meta"]["stale"] is False
    assert [m["id"] for m in got["models"]] == ["", "auto", "gpt-5.5", "claude-opus-5", "o3-mini"]
    seen = got["models"][-1]
    assert seen["via"] == ["seen"] and seen["offered"] is False, "what the last turn ran on is listed"
    assert got["efforts"] == ["low", "high"]
    assert [g["key"] for g in got["groups"]] == [k for k, _t, _p in M.GROUPS]
    assert counted == [], "a page request started the CLI"


def test_with_no_cache_the_shipped_list_is_answered_stale_and_nothing_starts(served, counted):
    base, token = served
    got = _get(base, token)
    assert got["meta"]["source"] == "shipped" and got["meta"]["stale"] is True
    assert [m["id"] for m in got["models"] if "shipped" in m["via"]] == M.shipped()["models"]
    assert got["efforts"] == M.shipped()["efforts"]
    assert counted == []
    assert not os.path.exists(M.cache_file()), "answering wrote a cache"


def test_a_server_that_is_built_and_asked_starts_no_cli(fleet_home, counted):
    """About 250 browser tests call `S.build(0)`: building a server starts no refresh, and neither
    does the first question it is asked."""
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        got = _get(f"http://127.0.0.1:{server.server_address[1]}", token)
        assert got["ok"] is True and got["refreshing"] is False
        assert not M.refreshing()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert counted == []


# ------------------------------------------------------------------------ POST /api/models


def test_a_refresh_is_answered_at_once_and_a_second_ask_joins_it(served, slow_cli):
    base, token = served
    _no_refresh_running()
    first = _post(base, token, {"refresh": True})
    assert first == {"ok": True, "action": "models", "refreshing": True, "started": True}
    # Answered while the fake's `help config` is still asleep: nothing has been written yet.
    assert M.refreshing(), "the answer waited for the CLI"
    assert not os.path.exists(M.cache_file())
    assert _get(base, token)["refreshing"] is True, "a page can tell a refresh is running"

    second = _post(base, token, {"refresh": True})
    assert second["refreshing"] is True and second["started"] is False, "a second ask started another"
    assert M.wait_refresh(0) is False, "the deadline passed with the refresh still running"
    assert M.wait_refresh(10)

    assert slow_cli.count(["help", "config"]) == 1, slow_cli
    with open(M.cache_file(), encoding="utf-8") as f:
        assert len(json.load(f)["models"]) == 26
    assert _post(base, token, {}) == {"ok": True, "action": "models", "refreshing": False, "started": False}


def test_models_is_an_action_and_model_is_no_longer_a_row_action():
    assert "models" not in S.ROW_ACTIONS, "the list is not a repository's row"
    assert "model" not in S.ROW_ACTIONS, "`act()` has no `model` branch: the entry led nowhere"


# ------------------------------------------------------------------------ the refresh thread


def test_a_refresh_writes_where_the_fleet_was_when_it_started(slow_cli, monkeypatch, tmp_path):
    """The next test's fleet directory, or the real home, must never receive a late write."""
    _no_refresh_running()
    here = M.cache_file()
    assert M.start_refresh() is True
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "elsewhere"))
    assert M.wait_refresh(10)
    with open(here, encoding="utf-8") as f:
        assert len(json.load(f)["models"]) == 26
    assert not os.path.exists(tmp_path / "elsewhere" / "models.json")


def test_a_refresh_stopped_while_the_cli_answers_writes_nothing(slow_cli):
    _no_refresh_running()
    stop = threading.Event()
    assert M.start_refresh(stop, force=True) is True
    stop.set()
    assert M.wait_refresh(10)
    assert not os.path.exists(M.cache_file())


def test_a_refresh_for_a_stopping_server_starts_nothing(counted):
    _no_refresh_running()
    stop = threading.Event()
    stop.set()
    M.start_refresh(stop, force=True)
    assert M.wait_refresh(10)
    assert counted == []
    assert not os.path.exists(M.cache_file())


def test_a_start_up_refresh_keeps_a_fresh_cache_and_a_forced_one_asks_again(counted):
    _no_refresh_running()
    M.refresh({})
    counted.clear()
    assert M.start_refresh() is True
    assert M.wait_refresh(10)
    assert counted == [["--version"]], "a fresh cache from this CLI build is kept"
    counted.clear()
    assert M.start_refresh(force=True) is True
    assert M.wait_refresh(10)
    assert counted == [["--version"], ["help", "config"], ["--help"]]


# ------------------------------------------------------------------------ the start-up refresh


def test_serve_and_quickstart_each_start_one_refresh_with_their_servers_stopping(fleet_home, tmp_path,
                                                                                 monkeypatch, capsys):
    built, asked = [], []
    monkeypatch.setattr(S, "run", built.append)
    monkeypatch.setattr(M, "start_refresh", lambda stop=None, **kw: asked.append((stop, kw)) or True)
    empty = tmp_path / "checkouts"
    empty.mkdir()
    try:
        assert cli_fleet.main(["serve", "--port", "0"]) == 0
        assert len(built) == 1 and len(asked) == 1
        assert cli_fleet.main(["quickstart", str(empty), "--yes", "--port", "0",
                               "--folder-watch", str(empty)]) == 0
    finally:
        for server in built:
            server.server_close()
    assert len(built) == 2 and len(asked) == 2, capsys.readouterr().out
    for server, (stop, kw) in zip(built, asked):
        assert stop is server.stopping, "the refresh does not stop with its server"
        assert kw == {}, "a start-up refresh is not forced: a fresh cache is kept"


# ------------------------------------------------------------------------ the stream


class Frames:
    """A stream's `write`: the `models` payloads, an Event on the first, and a count of `tick`s."""

    def __init__(self):
        self.models: list[dict] = []
        self.heard = threading.Event()
        self.ticks = 0
        self.ticked = threading.Condition()

    def __call__(self, chunk: str) -> None:
        if chunk.startswith("event: models\n"):
            self.models.append(json.loads(chunk.split("data: ", 1)[1]))
            self.heard.set()
        elif chunk.startswith("event: tick\n"):
            with self.ticked:
                self.ticks += 1
                self.ticked.notify_all()

    def ticks_past(self, n: int) -> bool:
        """True once `n` more `tick` frames than now have been written; False after 10 s."""
        with self.ticked:
            target = self.ticks + n
            return self.ticked.wait_for(lambda: self.ticks >= target, 10)


def test_one_stream_sends_one_models_frame_per_changed_list(fleet_home):
    _cache(["gpt-5.5", "claude-opus-5"])
    frames, stop = Frames(), threading.Event()
    t = threading.Thread(target=S.stream_events, args=({}, stop, frames),
                         kwargs={"tick": 0.05, "heartbeat": 0, "polls": False}, daemon=True)
    t.start()
    try:
        assert frames.ticks_past(1), "the stream never finished a pass"
        assert frames.models == [], "a new stream sent the list it found: the page fetches that itself"

        fetched = "2026-09-25T01:00:00Z"
        _cache(["gpt-5.5", "claude-opus-5", "gpt-6-astra"], fetched_at=fetched)
        assert frames.heard.wait(10), "a refresh that changed the ids sent no `models` frame"
        assert frames.models[0]["fetched_at"] == fetched
        assert re.fullmatch(r"[0-9a-f]{40}", frames.models[0]["version"]), frames.models[0]

        _cache(["gpt-5.5", "claude-opus-5", "gpt-6-astra"], fetched_at="2026-09-25T02:00:00Z")
        assert frames.ticks_past(5), "the stream stopped ticking"
        assert len(frames.models) == 1, f"a refresh that changed nothing sent a frame: {frames.models}"
    finally:
        stop.set()
        t.join(5)
    assert not t.is_alive()


# ------------------------------------------------------------------------ /settings


def test_the_settings_efforts_are_the_catalogues(counted):
    M.refresh({})                          # the fake CLI is 1.0.88: seven efforts
    counted.clear()
    efforts = S.settings_snapshot()["model"]["efforts"]
    assert efforts == M.catalogue({}, spawn=False)["efforts"]
    assert len(efforts) == 7 and efforts[-1] == "max"
    assert counted == [], "the settings page started the CLI"
