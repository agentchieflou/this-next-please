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
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.turn_start", turnId="0"))
        f.write(_line("assistant.message", content="Reading the ticket.", model="m", toolRequests=[]))

    out: list[str] = []
    S.stream_events({}, threading.Event(), out.append, once=True)
    frames = "".join(out)
    assert '"kind": "assistant_text"' in frames and "Reading the ticket." in frames
    assert '"kind": "turn_started"' in frames

    # One more line, one more fold, one more frame -- and only the new one.
    with open(file, "a", encoding="utf-8", newline="\n") as f:
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
    with open(file, "w", encoding="utf-8", newline="\n") as f:
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
    with open(file, "a", encoding="utf-8", newline="\n") as f:
        f.write(half[:40])                                     # the writer is mid-line
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, 0)], "a partial line is not consumed"
    assert sum(1 for ev in E.read("luna") if ev["kind"] == "assistant_text") == 2000

    reads.clear()
    with open(file, "a", encoding="utf-8", newline="\n") as f:
        f.write(half[40:])
    E.refresh("luna", _path, repo_state={})
    assert [r for r in reads if r[0] == file] == [(file, big, os.path.getsize(file) - big)]
    texts = [ev["data"]["text"] for ev in E.read("luna") if ev["kind"] == "assistant_text"]
    assert texts.count("the last one") == 1 and len(texts) == 2001


def test_a_cursor_written_as_a_line_count_is_read_once_as_an_offset(fleet_home, tmp_path):
    """Every cursor before #188 counted lines. Upgrading skips nothing and repeats nothing."""
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    raw = supervisor.events_path("luna")
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    with open(raw, "w", encoding="utf-8", newline="\n") as f:
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
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.message", content="first session", model="m", toolRequests=[]))
    E.refresh("luna", path, repo_state={})
    supervisor.write_lock("luna", {**supervisor.read_lock("luna"), "session": "sess-two"})
    second = SESS.session_state_path("sess-two")
    os.makedirs(os.path.dirname(second), exist_ok=True)
    with open(second, "w", encoding="utf-8", newline="\n") as f:
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
    with open(file, "w", encoding="utf-8", newline="\n") as f:
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
    env = dict(os.environ, COPILOT_SESSION_STATE=str(state), AGENTDATA_FAKE_CASE="triage-ok",
               PYTHONUTF8="1")                         # what child_env gives a real launch
    done = subprocess.run([sys.executable, os.path.join(FAKES, "runner.py"), "copilot", "-p", "hello",
                           "--resume", "sess-file"], capture_output=True, text=True, env=env,
                          cwd=str(tmp_path), timeout=120, encoding="utf-8", errors="replace")
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
            # Once a console holds the tile, the same button is *show console* and raises that
            # window rather than opening a second one (#190). On a machine with no Win32 console
            # API the helper says so -- and either way nothing starts a second session.
            page.wait_for_function(
                """() => /show console/.test(document.querySelector('.tile[data-repo="luna"] .console-tab').textContent)""",
                timeout=15000)
            page.locator('.tile[data-repo="luna"] .console-tab').click()
            page.wait_for_function(
                """() => /console/.test(document.querySelector('.tile[data-repo="luna"] .err').textContent)"""
                if os.name != "nt" else
                """() => true""",
                timeout=5000)
            assert sum(1 for e in E.read("luna")
                       if e["kind"] == "started" and e["data"].get("console")) == 1
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


# ---------------------------------------------------------- adopt, made exact: the session files (#192)


def test_the_sessions_of_a_checkout_are_found_by_workspace_yaml_or_the_stores_cwd(fleet_home, tmp_path, monkeypatch):
    """Both schema shapes (S1): a `workspace.yaml` naming the working directory, and a store row
    with a `cwd` column. Newest log first; a session elsewhere is never offered."""
    import sqlite3

    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    other = make_project(tmp_path / "mars", ticket="RDSD-9")
    root = SESS.session_state_dir()

    def session(sid, cwd, when, yaml=True):
        d = os.path.join(root, sid)
        os.makedirs(d, exist_ok=True)
        if yaml:
            with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"id: {sid}\ncwd: '{cwd}'\nsummary: x\n")
        with open(os.path.join(d, "events.jsonl"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_line("assistant.message", content=sid, model="m", toolRequests=[]))
        os.utime(os.path.join(d, "events.jsonl"), (when, when))

    session("old-here", path, 1_700_000_000)
    session("new-here", path, 1_700_000_500)
    session("elsewhere", other, 1_700_000_900)
    session("by-store", path, 1_700_000_700, yaml=False)      # only the store knows its cwd

    store = tmp_path / "store.db"
    con = sqlite3.connect(store)
    con.execute("CREATE TABLE sessions (id TEXT, cwd TEXT, repository TEXT, summary TEXT, created_at TEXT, updated_at TEXT)")
    con.execute("INSERT INTO sessions VALUES ('by-store', ?, 'luna', 'via the store', '2026-09-12', '2026-09-12')", (path,))
    con.execute("INSERT INTO sessions VALUES ('elsewhere', ?, 'mars', 'no', '2026-09-12', '2026-09-12')", (other,))
    con.commit()
    con.close()
    monkeypatch.setenv("COPILOT_SESSION_STORE", str(store))

    rows = SESS.session_files(path)
    assert [(r["id"], r["how"]) for r in rows] == [("by-store", "store"), ("new-here", "workspace"), ("old-here", "workspace")], rows
    assert all(r["file"] == SESS.session_state_path(r["id"]) for r in rows)
    assert rows[0]["log_age_s"] > 0
    assert SESS.session_files(str(tmp_path / "nowhere")) == []


def test_a_console_the_operator_opened_is_offered_by_its_session_file_and_adopting_it_tails_the_file(fleet_home, tmp_path):
    """Acceptance criteria (#192). A session file for the checkout written now makes the checkout
    adoptable as *matched by session file* even when nothing wrote `.agent/state.json`; adopting it
    makes the tile draw the session's transcript from the file; `still_there` is false once the
    file has been quiet for `idle_s`; a checkout merely saved to is still *inferred*."""
    from agentdata.fleet import adopt as A

    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")
    old = time.time() - 3600
    os.utime(os.path.join(path, ".agent", "state.json"), (old, old))       # nothing wrote state for an hour
    d = os.path.join(SESS.session_state_dir(), "sess-own")
    os.makedirs(d)
    with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"cwd: {path}\n")
    file = os.path.join(d, "events.jsonl")
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.message", content="thinking out loud, in a window", model="m", toolRequests=[]))

    offers = {c["repo"]: c for c in A.candidates(Registry(), processes=[])}
    assert offers["luna"]["how"] == "matched by session file"
    assert offers["luna"]["session"] == "sess-own" and offers["luna"]["session_file"] == file

    got = A.adopt("luna")
    assert got["how"] == "matched by session file" and got["session"] == "sess-own"
    lock = supervisor.read_lock("luna")
    assert lock["external"] and lock["session_file"] == file and lock["idle_s"] == A.IDLE_S
    assert supervisor.live("luna"), "the file was written seconds ago"
    E.refresh("luna", path, repo_state=Registry().get("luna").state())
    texts = [e["data"]["text"] for e in E.read("luna") if e["kind"] == "assistant_text"]
    assert texts == ["thinking out loud, in a window"]

    quiet = time.time() - A.IDLE_S - 5
    os.utime(file, (quiet, quiet))
    assert not A.still_there(lock) and not supervisor.live("luna")

    # A checkout merely saved to: the state file touched, no session file -- inferred, as before.
    mars = make_project(tmp_path / "mars", ticket="RDSD-9")
    Registry().add(mars, name="mars")
    offers = {c["repo"]: c for c in A.candidates(Registry(), processes=[])}
    assert offers["mars"]["how"] == "inferred from recent activity" and offers["mars"]["session_file"] == ""


# ======================================================================= C #190: the reply

SAY_HELPER = os.path.join(FAKES, "say_helper.py")


def _say_cfg(tmp_path, *, session_file="", fail=""):
    """A config whose console helper is the fake, and the environment it reads."""
    (tmp_path / "cfg.json").write_text(
        json.dumps({"fleet": {"console": {"host": "fake", "helper": [sys.executable, SAY_HELPER]},
                              "notify": {"toast": False}}}), encoding="utf-8")
    log = str(tmp_path / "helper.jsonl")
    env = {"AGENTDATA_FAKE_SAY_LOG": log, "AGENTDATA_FAKE_SAY_FILE": session_file,
           "AGENTDATA_FAKE_SAY_FAIL": fail}
    return log, env


def _helper_calls(log) -> list[list[str]]:
    if not os.path.isfile(log):
        return []
    return [json.loads(line)["argv"] for line in open(log, encoding="utf-8") if line.strip()]


def test_say_types_the_line_into_the_console_and_the_tile_shows_what_was_typed(
        fleet_home, tmp_path, monkeypatch):
    """Acceptance (#190). `say` against a `kind: console` lock spawns the helper with that window's
    pid and the operator's line; the tile carries the line as the fleet's own act, and the session's
    answer arrives from Copilot's file rather than from a second channel."""
    path, file = _console(tmp_path, session="sess-say")
    log, env = _say_cfg(tmp_path, session_file=file)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    out = supervisor.say("luna", "  use the staging connection string  ")
    assert out["ok"] and out["echoed"] == "use the staging connection string"
    assert _helper_calls(log) == [["say-into", str(os.getpid()), "use the staging connection string"]]

    said = [e for e in E.read("luna") if e["kind"] == "said"]
    assert len(said) == 1 and said[0]["data"]["text"] == "use the staging connection string"
    assert said[0]["data"]["session"] == "sess-say"

    # And what the console did with it comes back the one way it ever does: the session's own file.
    E.refresh("luna", path, repo_state=Registry().get("luna").state())
    texts = [e["data"]["text"] for e in E.read("luna") if e["kind"] == "assistant_text"]
    assert texts == ["Heard: use the staging connection string"]


def test_say_is_refused_where_there_is_no_console_to_type_into(fleet_home, tmp_path, monkeypatch):
    """A fleet session is `send`'s to continue and an empty checkout has nothing at all; both say so
    in the CLI's words, with the code the page and the docs use."""
    log, env = _say_cfg(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    path = make_project(tmp_path / "luna", ticket="RDSD-7")
    Registry().add(path, name="luna")

    with pytest.raises(supervisor.SupervisorError) as no_agent:
        supervisor.say("luna", "anything")
    assert no_agent.value.code == "no_agent"

    supervisor.write_lock("luna", {"pid": os.getpid(), "repo": "luna", "path": path,
                                   "session": "s1", "started": time.time(), "launch": []})
    with pytest.raises(supervisor.SupervisorError) as not_console:
        supervisor.say("luna", "anything")
    assert not_console.value.code == "not_a_console"
    assert "ad-fleet send luna" in not_console.value.hint

    # An adopted console: the session file was the evidence, and no process was ever named for it.
    supervisor.write_lock("luna", {"pid": 0, "kind": "console", "external": True, "repo": "luna",
                                   "path": path, "session": "s1", "session_file": "",
                                   "started": time.time(), "launch": []})
    with pytest.raises(supervisor.SupervisorError) as adopted:
        supervisor.say("luna", "anything")
    assert adopted.value.code == "external_session"
    assert not _helper_calls(log), "nothing was typed at anything"


def test_a_helper_failure_reaches_the_tile_in_the_helpers_own_words(fleet_home, tmp_path, monkeypatch):
    """Acceptance (#190). The helper is the one that knows the Win32 number, so its sentence is the
    one the operator reads -- not a generic "something went wrong" invented one layer up."""
    path, file = _console(tmp_path, session="sess-fail")
    log, env = _say_cfg(tmp_path, session_file=file, fail="console_unreachable")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(supervisor.SupervisorError) as refused:
        supervisor.say("luna", "hello")
    assert refused.value.code == "console_unreachable"
    assert "win32 6" in refused.value.msg and "type in that window" in refused.value.hint
    assert not [e for e in E.read("luna") if e["kind"] == "said"], \
        "a line that was not typed is not a line the tile may claim was"


def test_the_page_posts_say_for_a_console_and_send_for_a_fleet_session(fleet_home, tmp_path):
    """The page is a view: which verb the reply box posts is decided by the lock the server reports,
    and both verbs are the same functions the CLI calls."""
    script = open(os.path.join(os.path.dirname(FAKES), "..", "agentdata", "fleet", "static",
                               "app.js"), encoding="utf-8").read()
    assert 'action(el, el.dataset.console ? "say" : "send"' in script
    assert 'el.dataset.console = row.console ? String(row.console.pid || 0) : ""' in script
    assert 'if (el.dataset.console) return action(el, "focus", { repo: row.repo });' in script


def test_the_snapshot_says_which_tile_a_console_is_holding(fleet_home, tmp_path, monkeypatch):
    path, file = _console(tmp_path, session="sess-row")
    row = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}["luna"]
    assert row["console"]["session"] == "sess-row" and row["console"]["pid"] == os.getpid()
    assert not row["external"], "a console the fleet opened is the fleet's own, not an adopted one"

    supervisor.clear_lock("luna")
    row = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}["luna"]
    assert row["console"] is None


def test_a_console_sitting_on_one_tool_call_says_where_to_look(fleet_home, tmp_path, monkeypatch):
    """The CLI writes no permission *request* event (docs/fleet-spike.md), so a `y/n` in the console
    looks like a slow tool. Time is the only thing that separates them, and the sentence says it is
    a guess rather than promising the fleet knows."""
    path, file = _console(tmp_path, session="sess-wait")
    with open(file, "w", encoding="utf-8", newline="\n") as f:
        f.write(_line("assistant.turn_start", turnId="0"))
        f.write(json.dumps({"type": "tool.execution_start", "id": "e", "parentId": None,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                       time.gmtime(time.time() - 90)),
                            "data": {"toolCallId": "t1", "toolName": "shell",
                                     "arguments": {"command": "rm -rf build"}}}) + "\n")
    E.refresh("luna", path, repo_state=Registry().get("luna").state())

    row = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}["luna"]
    assert row["state"] == "running", "a session with a window open is live, whatever it is waiting on"
    assert row["why"].startswith("waiting for you, in the console?")

    # The result lands: nothing is waiting on the operator any more.
    with open(file, "a", encoding="utf-8", newline="\n") as f:
        f.write(_line("tool.execution_complete", toolCallId="t1", success=True))
    E.refresh("luna", path, repo_state=Registry().get("luna").state())
    row = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}["luna"]
    assert "waiting for you" not in row["why"]


def test_the_console_helpers_never_reach_for_a_native_dependency_or_an_interrupt():
    """Ground rule 6, and the one the operator's fingers care about: `ctypes` for three console
    calls, and `GenerateConsoleCtrlEvent` nowhere at all -- interrupting a session a person is
    watching is theirs."""
    from agentdata.fleet import console as FC

    import ast

    source = inspect.getsource(FC)
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "os", "ctypes"}, f"a new dependency: {imported}"
    assert "ctypes" in imported, "the Win32 console API is reached the way color.py reaches it"
    assert "GenerateConsoleCtrlEvent" not in source.split('"""', 2)[-1], \
        "interrupting a session a person is watching is theirs"

    # Every attribute the package reaches for, by name: prose that *says* the call is banned is not
    # the same as code that makes it, and only one of the two is a Ctrl-C in somebody's session.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder, _, files in os.walk(os.path.join(root, "agentdata")):
        for name in sorted(f for f in files if f.endswith(".py")):
            tree = ast.parse(open(os.path.join(folder, name), encoding="utf-8").read())
            reached = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            reached |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            assert "GenerateConsoleCtrlEvent" not in reached, f"{name} interrupts a console"


def test_one_line_is_one_line_whatever_was_pasted_into_the_box():
    """A reply with newlines in it would be several commands to a console, and the second would run
    against whatever the first left behind."""
    from agentdata.fleet import console as FC

    assert FC.one_line("  first\nsecond\r\nthird  ") == "first second third"
    with pytest.raises(FC.ConsoleError) as empty:
        FC.one_line("   \n  ")
    assert empty.value.code == "empty_message"


@pytest.mark.skipif(os.name == "nt", reason="the Win32 console API is there to be used")
def test_on_posix_the_helper_says_the_console_is_a_windows_thing():
    from agentdata.fleet import console as FC

    for call in (lambda: FC.say_into(1, "hello"), lambda: FC.focus_console(1)):
        with pytest.raises(FC.ConsoleError) as refused:
            call()
        assert refused.value.code == "unsupported_host"


def test_the_cli_says_and_shows_and_the_two_helpers_take_a_pid(fleet_home, tmp_path, monkeypatch, capsys):
    """One vocabulary: `ad-fleet say` calls the same `serve.act` the tile posts to, prints TOON, and
    exits 2 on a refusal. The helpers take a pid because they are what the verbs spawn."""
    from agentdata import cli_fleet

    path, file = _console(tmp_path, session="sess-cli")
    log, env = _say_cfg(tmp_path, session_file=file)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    assert cli_fleet.main(["say", "luna", "check the staging table"]) == 0
    said = capsys.readouterr().out
    assert "ok: true" in said and "check the staging table" in said
    assert _helper_calls(log)[-1][0] == "say-into"

    assert cli_fleet.main(["show-console", "luna"]) == 0
    assert "focused: true" in capsys.readouterr().out
    assert _helper_calls(log)[-1] == ["focus-console", str(os.getpid())]

    supervisor.clear_lock("luna")
    assert cli_fleet.main(["say", "luna", "anyone there"]) == 2
    refused = capsys.readouterr().out
    assert "ok: false" in refused and "no_agent" in refused

    # The helpers are what a console attaches from, so they are given a pid and not a repository.
    parser = cli_fleet.build_parser()
    assert parser.parse_args(["say-into", "4242", "hello"]).pid == 4242
    assert parser.parse_args(["focus-console", "4242"]).pid == 4242
