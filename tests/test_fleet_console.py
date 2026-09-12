"""Console: A — the file (issue #188).

Copilot writes every session -- interactive or `-p` -- to `~/.copilot/session-state/<id>/events.jsonl`
as it runs, in the catalogue `events.from_copilot` folds. The fleet's own agents get their events
because the supervisor redirects stdout into a file it owns; a session in a console has no such pipe,
so its file is the only stream there is. It is read from a byte offset on the desk's own tick, and
never written.
"""
from __future__ import annotations
import inspect
import json
import os
import subprocess
import sys
import threading
import time

import pytest

from agentdata.fleet import events as E, launch, lifecycle, registry, serve as S, sessions as SESS, supervisor

import fakes
from agentdata.fleet.registry import Registry

from test_fleet import make_project

FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "copilot" / "session-state"))
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


def _line(kind: str, **data) -> str:
    return json.dumps({"type": kind, "id": "e", "parentId": None,
                       "timestamp": "2026-09-12T10:00:00Z", "data": data}) + "\n"


def _console(tmp_path, name="luna", session="sess-console"):
    """A checkout with a console lock naming a session, and that session's file."""
    path = make_project(tmp_path / name, ticket="RDSD-7")
    Registry().add(path, name=name)
    supervisor.write_lock(name, {"pid": os.getpid(), "kind": "console", "session": session,
                                 "repo": name, "path": path, "ticket": "RDSD-7",
                                 "started": time.time(), "restarts": 0, "launch": []})
    E.append(name, [E.event(name, "started", {"pid": os.getpid(), "console": True, "session": session},
                            ticket="RDSD-7")])
    file = SESS.session_state_path(session)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    return path, file


# ------------------------------------------------------------------------------------ the path


def test_the_session_file_is_under_copilots_own_directory_and_the_id_is_one_segment(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "state"))
    assert SESS.session_state_path("abc-123") == os.path.join(str(tmp_path / "state"), "abc-123", "events.jsonl")
    assert SESS.session_state_path("") == "" and SESS.session_state_path("..") == ""
    assert SESS.session_state_path("../../etc/passwd") == os.path.join(str(tmp_path / "state"), "passwd", "events.jsonl")
    monkeypatch.delenv("COPILOT_SESSION_STATE")
    assert SESS.session_state_dir() == os.path.expanduser("~/.copilot/session-state")


def test_nothing_in_the_session_state_functions_can_write():
    """Acceptance criterion. Read-only by construction: the source of the two functions carries no
    call that could create, write or remove anything."""
    for fn in (SESS.session_state_dir, SESS.session_state_path):
        src = inspect.getsource(fn)
        for bad in ("open(", "makedirs", "write", "remove", "rename", "unlink", "rmtree", "mkdir"):
            assert bad not in src, f"{fn.__name__} carries {bad!r}"


# ------------------------------------------------------------------------------------ the fold


def test_a_line_appended_to_the_session_file_is_an_agent_frame_on_the_next_tick(fleet_home, tmp_path):
    """Acceptance criterion. The console's file is folded by the same function on the same tick
    as the fleet's own logs, so a line Copilot writes is an SSE `agent` frame inside
    `FOLD_EVERY_S + TICK_S`, the bar the desk already keeps."""
    assert S.FOLD_EVERY_S + S.TICK_S < 1.0
    _path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.turn_start", turnId="0"))
        f.write(_line("assistant.message", content="Reading the ticket.", model="m", toolRequests=[]))

    out: list[str] = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert '"kind": "assistant_text"' in frames and "Reading the ticket." in frames
    assert '"kind": "turn_started"' in frames

    # One more line, one more fold, one more frame -- and only the new one.
    with open(file, "a", encoding="utf-8") as f:
        f.write(_line("tool.execution_start", toolName="shell", toolCallId="t1", arguments={"command": "git status"}))
    cursors = {"luna": max(ev["seq"] for ev in E.read("luna"))}
    S._desk["last_fold"] = 0.0
    out.clear()
    S.stream_events(cursors, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert '"kind": "tool_call"' in frames and "git status" in frames
    assert "Reading the ticket." not in frames


def test_the_file_is_read_from_its_offset_and_a_half_written_line_waits(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion. The second fold reads only the bytes appended since the first -- a
    console session's file grows for hours -- and a partial last line is neither folded nor lost."""
    _path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        for i in range(2000):
            f.write(_line("assistant.message", content=f"line {i} " + "x" * 200, model="m", toolRequests=[]))
    big = os.path.getsize(file)
    reads: list[tuple[str, int, int]] = []
    real = E._read_from

    def counted(path, offset):
        lines, new_offset, n = real(path, offset)
        reads.append((path, offset, new_offset - offset))
        return lines, new_offset, n

    monkeypatch.setattr(E, "_read_from", counted)
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, 0, big)]
    assert sum(1 for ev in E.read("luna") if ev["kind"] == "assistant_text") == 2000

    reads.clear()
    half = _line("assistant.message", content="the last one", model="m", toolRequests=[])
    with open(file, "a", encoding="utf-8") as f:
        f.write(half[:40])                                     # the writer is mid-line
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, 0)], "a partial line is not consumed"
    assert sum(1 for ev in E.read("luna") if ev["kind"] == "assistant_text") == 2000

    reads.clear()
    with open(file, "a", encoding="utf-8") as f:
        f.write(half[40:])
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, len(half.encode("utf-8")))]
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts.count("the last one") == 1 and len(texts) == 2001


def test_a_cursor_written_as_a_line_count_is_read_once_as_an_offset(fleet_home, tmp_path):
    """Every cursor before #188 counted lines. Upgrading skips nothing and repeats nothing."""
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    raw = supervisor.events_path("luna")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    with open(raw, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="one", model="m", toolRequests=[]))
        f.write(_line("assistant.message", content="two", model="m", toolRequests=[]))
    E.write_cursor("luna", {"raw_lines": 1})                  # the old shape: one line consumed
    E.refresh("luna", path, repo_state={})
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts == ["two"], texts
    cursor = E.read_cursor("luna")
    assert cursor["raw_lines"] == 2 and cursor["raw_offset"] == os.path.getsize(raw)
    E.reset_raw_cursor("luna")
    assert E.read_cursor("luna")["raw_offset"] == 0 and E.read_cursor("luna")["raw_lines"] == 0


def test_a_new_session_is_a_new_file_and_the_offset_belongs_to_the_path(fleet_home, tmp_path):
    path, file = _console(tmp_path, session="sess-one")
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="first session", model="m", toolRequests=[]))
    E.refresh("luna", path, repo_state={})
    supervisor.write_lock("luna", {**supervisor.read_lock("luna"), "session": "sess-two"})
    second = SESS.session_state_path("sess-two")
    os.makedirs(os.path.dirname(second), exist_ok=True)
    with open(second, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="second session", model="m", toolRequests=[]))
    E.refresh("luna", path, repo_state={})
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts == ["first session", "second session"]
    assert E.read_cursor("luna")["console_file"] == second


def test_without_a_console_lock_no_session_file_is_read(fleet_home, tmp_path):
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    assert E.console_path("luna") == ""
    supervisor.write_lock("luna", {"pid": 1, "repo": "luna", "session": "sess-fleet", "launch": []})
    assert E.console_path("luna") == "", "a fleet lock's session is on the fleet's own pipe"
    supervisor.write_lock("luna", {"pid": 0, "repo": "luna", "external": True, "session": "s",
                                   "session_file": str(tmp_path / "somewhere" / "events.jsonl")})
    assert E.console_path("luna") == str(tmp_path / "somewhere" / "events.jsonl")


# --------------------------------------------------------------------------------- never written


def test_copilots_directory_is_never_written_by_a_fold(fleet_home, tmp_path):
    """Acceptance criterion. Every fold path runs against Copilot's directory and nothing under it
    changes: not a file, not a timestamp, not a listing."""
    path, file = _console(tmp_path)
    with open(file, "w", encoding="utf-8") as f:
        f.write(_line("assistant.message", content="hello", model="m", toolRequests=[]))
    root = SESS.session_state_dir()

    def snapshot():
        out = {}
        for d, _dirs, files in os.walk(root):
            for name in files:
                p = os.path.join(d, name)
                out[p] = (os.path.getsize(p), os.path.getmtime(p))
            out[d] = ("dir", os.path.getmtime(d))
        return out

    before = snapshot()
    for _ in range(3):
        E.refresh("luna", path, repo_state={"active_ticket": "RDSD-7", "phase": "triaged"})
        S.stream_events({}, threading.Event(), lambda s: None, once=True)
        S._desk["last_fold"] = 0.0
    assert snapshot() == before


# ------------------------------------------------------------------------------------- the fake


def test_the_fake_copilot_writes_its_session_file_in_the_order_it_prints(tmp_path, monkeypatch):
    """Acceptance criterion. The fake's session file and its stdout carry the same events in the
    same order, so CI has a file that grows the way Copilot's does."""
    state = tmp_path / "state"
    env = dict(os.environ, COPILOT_SESSION_STATE=str(state), AGENTDATA_FAKE_CASE="triage-ok")
    done = subprocess.run([sys.executable, os.path.join(FAKES, "runner.py"), "copilot", "-p", "hello",
                           "--resume", "sess-file"], capture_output=True, text=True, env=env,
                          cwd=str(tmp_path), timeout=120)
    assert done.returncode == 0, done.stderr
    printed = [ln for ln in done.stdout.splitlines() if ln.startswith("{")]
    file = state / "sess-file" / "events.jsonl"
    assert file.is_file()
    written = [ln for ln in file.read_text(encoding="utf-8").splitlines() if ln.startswith("{")]
    assert written == printed and len(written) >= 2
    assert json.loads(written[-1])["type"] == "result"


# ---------------------------------------------------------------------- the console's argv (#189)


def _patterns(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_the_consoles_argv_is_the_turns_without_the_three_headless_flags():
    """Acceptance criterion (#189). No `-p`, no `--no-ask-user`, no `--output-format`; the
    enumerated allow-list; `--session-id <id>`; `-C <repo>`."""
    argv = launch.console_command("copilot", "C:/repo", log_dir="C:/logs", session="6f1c-console")
    assert argv[0] == "copilot"
    for gone in ("-p", "--no-ask-user", "--output-format", "--usage-output-file"):
        assert gone not in argv, gone
    assert _patterns(argv, "--session-id") == ["6f1c-console"] and "--resume" not in argv
    assert _patterns(argv, "-C") == ["C:/repo"] and _patterns(argv, "--add-dir") == ["C:/repo"]
    assert _patterns(argv, "--log-dir") == ["C:/logs"] and "--disable-builtin-mcps" in argv
    headless = launch.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs")
    assert _patterns(argv, "--allow-tool") == _patterns(headless, "--allow-tool"), "the same enumerated list"
    assert _patterns(argv, "--deny-tool") == _patterns(headless, "--deny-tool")
    assert "shell(ad-fleet)" in _patterns(argv, "--deny-tool")


def test_a_resumed_console_continues_the_session_it_names_and_a_blanket_permission_is_refused():
    argv = launch.console_command("copilot", "C:/repo", log_dir="C:/logs", session="sess-1", resume=True)
    assert _patterns(argv, "--resume") == ["sess-1"] and "--session-id" not in argv
    with pytest.raises(launch.LaunchError) as e:
        launch.console_command("copilot", "C:/repo", log_dir="C:/logs", session="")
    assert "session id" in e.value.msg
    with pytest.raises(launch.LaunchError) as e:
        launch.console_command("copilot", "C:/repo", log_dir="C:/logs", session="s",
                               cfg={"fleet": {"allow_tools": ["--allow-all"]}})
    assert "blanket" in e.value.hint


# -------------------------------------------------------------- the console the fleet opens (#189)


def _eventually(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


CONSOLE_CFG = {"fleet": {"console": {"host": "fake"}, "notify": {"toast": False}}}


def test_the_console_the_fleet_opens_takes_the_lock_and_the_tile_reads_it_live(fleet_home, tmp_path, monkeypatch):
    """Acceptance criteria (#189). With a fake host, `ad-fleet console luna RDSD-7` takes the lock
    with `kind: console` and a pid, appends `started` with `console: true`, and the tile reads the
    fake's session file live. While it is live, start/send refuse with `live_agent` and stop refuses
    with *close that window* and kills nothing. The window closing ends the run."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "console-session")
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")

    lock = supervisor.console("luna", key="RDSD-7", cfg=CONSOLE_CFG)
    assert lock["kind"] == "console" and lock["pid"] and lock["session"]
    assert "-C" in lock["launch"] and "-p" not in lock["launch"]
    started = [e for e in E.read("luna") if e["kind"] == "started"]
    assert len(started) == 1 and started[0]["data"]["console"] is True
    assert started[0]["data"]["session"] == lock["session"]

    # Live, and read from Copilot's own file for the session, not from a pipe.
    assert supervisor.live("luna")["kind"] == "console"
    file = SESS.session_state_path(lock["session"])
    assert _eventually(lambda: os.path.isfile(file) and "Hello from the console" in open(file, encoding="utf-8").read())
    E.refresh("luna", path, repo_state=Registry().get("luna").state())
    texts = [e["data"]["text"] for e in E.read("luna") if e["kind"] == "assistant_text"]
    assert texts == ["Hello from the console."], texts
    assert os.path.getsize(supervisor.events_path("luna")) == 0 if os.path.isfile(supervisor.events_path("luna")) else True

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.start("luna", key="RDSD-7", cfg=CONSOLE_CFG)
    assert e.value.code == "live_agent"
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.send("luna", "hello", cfg=CONSOLE_CFG)
    assert e.value.code == "external_session" and "type in that window" in e.value.hint
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.stop("luna")
    assert e.value.code == "console_window" and "close that window" in e.value.hint
    assert supervisor.pid_alive(lock["pid"]), "stop killed the console"

    # The window closes (the fake's turn ends): the reaper says so, and the lock goes with it.
    assert _eventually(lambda: not supervisor.pid_alive(lock["pid"]), timeout=30)
    fresh = lifecycle.reap("luna")
    assert [e["kind"] for e in fresh] == ["exited"] and fresh[0]["data"]["why"] == "the console closed"
    assert not supervisor.read_lock("luna")


def test_a_console_is_refused_beside_a_live_agent_and_a_machine_with_no_terminal(fleet_home, tmp_path, monkeypatch):
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    supervisor.write_lock("luna", {"pid": os.getpid(), "repo": "luna", "ticket": "RDSD-2", "launch": []})
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.console("luna", key="RDSD-7", cfg=CONSOLE_CFG)
    assert e.value.code == "live_agent"


@pytest.mark.skipif(os.name == "nt", reason="Windows always has cmd.exe")
def test_a_machine_with_no_terminal_refuses_to_open_a_console(fleet_home, tmp_path, monkeypatch):
    import shutil

    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.console("luna", key="RDSD-7", cfg={"fleet": {"console": {"host": "terminal"}}})
    assert e.value.code == "no_console_host"
    assert not supervisor.read_lock("luna"), "no window, no lock"


@pytest.mark.browser
def test_the_console_button_on_the_strip_opens_one_and_the_tile_shows_it(fleet_home, tmp_path, monkeypatch):
    """The page is a view: the strip's *console* button posts the verb, and the tile then draws the
    session the fake writes to Copilot's file."""
    from test_fleet_desk_browser import launch_chromium

    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "console-session")
    (tmp_path / "cfg.json").write_text(json.dumps({"fleet": {"console": {"host": "fake"}, "notify": {"toast": False}}}),
                                       encoding="utf-8")
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="luna"] .console-tab', timeout=15000)
            page.locator('.tile[data-repo="luna"] .console-tab').click()
            assert _eventually(lambda: any(e["kind"] == "started" and e["data"].get("console")
                                           for e in E.read("luna")))
            lock = supervisor.read_lock("luna")
            assert lock.get("kind") == "console" and lock.get("ticket") == "RDSD-7"
            page.wait_for_function(
                """() => /Hello from the console/.test(document.querySelector('.tile[data-repo="luna"]').textContent)""",
                timeout=15000)
            # A second press while it is live is the supervisor's refusal, on the tile.
            page.locator('.tile[data-repo="luna"] .console-tab').click()
            page.wait_for_function(
                """() => /already has a live agent/.test(document.querySelector('.tile[data-repo="luna"] .err').textContent)""",
                timeout=5000)
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert _eventually(lambda: not supervisor.pid_alive(int(supervisor.read_lock("luna").get("pid") or 0)), timeout=30)


# ------------------------------------------------------------- one session, either surface (#191)


def test_the_session_index_says_a_console_held_the_session(fleet_home, tmp_path):
    """A `started` with `console: true` folds to `source: console`; the fleet's own to `fleet`; an
    adopted one to `adopted` -- the surface that held the session when the run began."""
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    E.append("luna", [
        E.event("luna", "started", {"pid": 1, "console": True, "session": "sess-c", "new": True}, ticket="RDSD-7"),
        E.event("luna", "exited", {"exit_code": None, "why": "the console closed"}, ticket="RDSD-7"),
        E.event("luna", "started", {"pid": 2, "session": "sess-c", "resumed": True}, ticket="RDSD-7"),
        E.event("luna", "started", {"pid": 0, "external": True, "adopted": True, "session": "sess-x"}, ticket="RDSD-7"),
    ])
    rows = {r["id"]: r for r in SESS.rebuild_sessions("luna", path)}
    assert rows["sess-c"]["runs"] == 2 and rows["sess-c"]["source"] == "console", rows["sess-c"]
    assert rows["sess-x"]["source"] == "adopted"
