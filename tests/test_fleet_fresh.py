"""Start fresh (#488): leave the session a checkout is on for a clean one, in one call.

The operator: *it still does not feel intuitive to exit out of a stale session (that may have come
from a native copilot CLI chat) with a fresh clean session.* It took three presses found through
refusals on the desk and two to five commands in a terminal. `ad-fleet fresh <repo>` and
`POST /api/fresh` are one call: a clean `--new` session on the same ticket and the configured model,
with the old session still listed and marked as left. It never ends the operator's own chat, never
starts beside one it can name, and asks for a deliberate second press when a chat may still be open.
"""
from __future__ import annotations
import http.client
import json
import os
import time

import pytest

from agentdata import cli_fleet
from agentdata.fleet import adopt as A, events as E, fingerprint as FP, fresh as FRESH
from agentdata.fleet import serve as S, sessions as SESS, supervisor
from agentdata.fleet.registry import Registry, fleet_dir

from test_fleet_desk_switcher import _serve, spawns  # noqa: F401 - fixtures
from test_fleet_renew import NOW, OLD, _repo, fleet_home, started, turn_ended  # noqa: F401 - fixtures

CHAT_PID = 26846


@pytest.fixture()
def copilot_home(tmp_path, monkeypatch):
    """Copilot's session files and store, in this test's own folder and never a real home."""
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "session-state"))
    monkeypatch.setenv("COPILOT_SESSION_STORE", str(tmp_path / "no-store.db"))
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    return tmp_path / "session-state"


def _session_file(root, sid: str, checkout: str, age_s: float = 0.0) -> str:
    """A Copilot session file for this checkout, written `age_s` ago, as a terminal chat writes one."""
    d = os.path.join(str(root), sid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "workspace.yaml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"id: {sid}\ncwd: '{checkout}'\n")
    path = os.path.join(d, "events.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "assistant.turn_start", "data": {"turnId": "0"}}) + "\n")
    when = time.time() - age_s
    os.utime(path, (when, when))
    return path


def _stale(tmp_path, name, *, phase="validating", ticket="RDSD-201", cost=0.0):
    """An idle fleet session on the skills of 0.13.1, mid-ticket."""
    events = [started(OLD), E.event(name, "session_id", {"session": f"s-{name}"}, ticket=ticket)]
    if cost:
        events.append(E.event(name, "cost", {"premium_requests": cost, "source": "checkpoint"}, ticket=ticket))
    return _repo(tmp_path, name, phase=phase, ticket=ticket, events=events + [turn_ended()])


def _adopted_by_file(tmp_path, home, name, *, ticket="RDSD-118"):
    """A terminal chat known only by its session file (the Windows shape: pid 0), adopted."""
    path = _repo(tmp_path, name, phase="querying", ticket=ticket,
                 events=[started(OLD), E.event(name, "session_id", {"session": f"s-{name}"}), turn_ended()])
    old = time.time() - 3600
    os.utime(os.path.join(path, ".agent", "state.json"), (old, old))
    _session_file(home, f"native-{name}", path)
    assert A.adopt(name)["how"] == "matched by session file"
    return path


def _prompt(argv: list[str]) -> str:
    return argv[argv.index("-p") + 1]


def _files() -> set[str]:
    out = set()
    for root, _dirs, names in os.walk(fleet_dir()):
        out.update(os.path.join(root, n) for n in names)
    return out


# ------------------------------------------------------------------------------------ the plan


def test_every_fresh_verdict(fleet_home, copilot_home, tmp_path, monkeypatch, spawns):  # noqa: F811
    _stale(tmp_path, "stale")
    _adopted_by_file(tmp_path, copilot_home, "chat")
    # Adopted with a pid this machine named: the chat is alive (the POSIX shape).
    _repo(tmp_path, "named", phase="querying", ticket="RDSD-7")
    lock = {"pid": CHAT_PID, "how": "matched by working directory", "repo": "named",
            "path": Registry().get("named").path, "session": "native-named", "external": True}
    supervisor.write_lock("named", lock)
    monkeypatch.setattr(A, "proc_alive", lambda pid: pid == CHAT_PID)
    # Adopted, then quiet: its session file fell silent and the reaper cleared the lock.
    _adopted_by_file(tmp_path, copilot_home, "quiet")
    quiet = time.time() - A.IDLE_S - 60
    for sid in ("native-quiet",):
        f = os.path.join(str(copilot_home), sid, "events.jsonl")
        os.utime(f, (quiet, quiet))
    supervisor.clear_lock("quiet")
    # A fleet turn in progress, and a console the fleet opened.
    _repo(tmp_path, "busy", events=[started(NOW)])
    supervisor.write_lock("busy", {"pid": 7001, "repo": "busy", "ticket": "RDSD-1"})
    _repo(tmp_path, "consoled", events=[started(NOW, console=True)])
    supervisor.write_lock("consoled", {"pid": 7002, "repo": "consoled", "kind": "console"})
    spawns["alive"].update({7001, 7002})
    _repo(tmp_path, "asking", events=[started(OLD), turn_ended()],
          questions=[{"id": "q1", "q": "which workspace?"}])
    _repo(tmp_path, "never", ticket="")
    _repo(tmp_path, "beside", ticket="RDSD-9")

    for repo in Registry().sorted():                     # the stream caught up, as a desk tick leaves it
        E.refresh(repo.name, repo.path, repo_state=repo.state())
        supervisor.session_id(repo.name)
    before_started = len([e for n in Registry().repos for e in E.read(n) if e["kind"] == "started"])
    before_files = _files()
    got = {name: FRESH.plan(name, cfg={}) for name in
           ("stale", "chat", "named", "quiet", "busy", "consoled", "asking", "never")}
    verdicts = {name: (row["verdict"], row["code"]) for name, row in got.items()}
    assert verdicts == {
        "stale": ("now", ""), "chat": ("second_press", "chat_open"),
        "named": ("refused", "foreign_session"), "quiet": ("now", ""),
        "busy": ("refused", "mid_turn"), "consoled": ("refused", "console_window"),
        "asking": ("refused", "needs_you"), "never": ("now", ""),
    }, verdicts
    assert got["stale"]["leaves"]["session"] == "s-stale" and got["stale"]["leaves"]["origin"] == "fleet"
    assert got["stale"]["leaves"]["stale"]["stale"] is True
    assert got["stale"]["starts"] == {"ticket": "RDSD-201", "model": "", "effort": "",
                                      "model_source": "cli-auto", "effort_source": "cli-auto"}
    assert got["chat"]["leaves"] == {**got["chat"]["leaves"], "session": "native-chat", "origin": "adopted"}
    assert "matched by session file" in got["chat"]["why"] and "--closed" in got["chat"]["hint"]
    assert f"pid {CHAT_PID}" in got["named"]["why"] and "close it there" in got["named"]["why"]
    assert got["quiet"]["leaves"]["origin"] == "adopted"
    assert got["busy"]["why"].startswith("a session changes between turns")
    assert "ad-fleet console consoled --new" in got["consoled"]["why"]
    assert got["asking"]["why"].startswith("answer it first")
    assert got["never"]["leaves"]["session"] == "" and got["never"]["starts"]["ticket"] == ""
    # A Copilot the listing places in the checkout is named, adopted or not.
    monkeypatch.setattr(A, "agent_processes",
                        lambda **_: [{"pid": CHAT_PID, "cwd": Registry().get("beside").path, "cmdline": "copilot"}])
    assert FRESH.plan("beside", cfg={})["code"] == "foreign_session"

    assert len([e for n in Registry().repos for e in E.read(n) if e["kind"] == "started"]) == before_started
    assert _files() == before_files, "a plan writes nothing"
    assert spawns["launched"] == [], "a plan launches nothing"


# ------------------------------------------------------------------------------------- the run


def test_fresh_is_new_never_resume_and_on_the_configured_model(fleet_home, copilot_home, tmp_path, spawns):  # noqa: F811
    _stale(tmp_path, "luna")
    out = FRESH.run("luna", cfg={})
    assert out["done"] == "started" and out["verdict"] == "now"
    assert len(spawns["launched"]) == 1
    argv = spawns["launched"][0]
    assert "--resume" not in argv
    assert "--model" not in argv and "--effort" not in argv, "cli-auto: the CLI chooses"
    said = _prompt(argv)
    assert said.startswith("Ticket RDSD-201.") and "This is a fresh session" in said
    assert "left session s-luna (a fleet session; started on 0.13.1" in said
    lock = supervisor.read_lock("luna")
    assert lock["session"] == "" and lock["ticket"] == "RDSD-201"
    began = [e for e in E.read("luna") if e["kind"] == "started"][-1]["data"]
    assert began["new"] is True and began["resumed"] is False
    assert began["leaves"] == {"session": "s-luna", "origin": "fleet"}

    # On a configured model, the launch carries exactly what `model_for` gives the pane.
    _stale(tmp_path, "sol")
    cfg = {"fleet": {"models": {"sol": {"model": "claude-opus-5", "effort": "high"}}}}
    FRESH.run("sol", cfg=cfg)
    argv = spawns["launched"][1]
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--effort") + 1] == "high"
    assert FRESH.plan("sol", cfg=cfg)["code"] == "mid_turn", "the fresh one is running now"


def test_a_second_press_releases_and_starts_but_never_over_a_named_pid(
        fleet_home, copilot_home, tmp_path, monkeypatch, spawns):  # noqa: F811
    _adopted_by_file(tmp_path, copilot_home, "luna")
    started_before = len([e for e in E.read("luna") if e["kind"] == "started"])
    with pytest.raises(FRESH.FreshRefused) as first:
        FRESH.run("luna", cfg={})
    assert first.value.code == "chat_open" and first.value.second_press
    assert supervisor.read_lock("luna").get("external"), "the first press changes nothing"
    assert spawns["launched"] == []
    assert len([e for e in E.read("luna") if e["kind"] == "started"]) == started_before

    out = FRESH.run("luna", closed=True, cfg={})
    assert out["done"] == "started" and out["released"] is True
    assert len(spawns["launched"]) == 1 and "--resume" not in spawns["launched"][0]
    assert "RDSD-118" in _prompt(spawns["launched"][0]) and "your own chat" in _prompt(spawns["launched"][0])
    assert not supervisor.read_lock("luna").get("external")

    # A chat named by pid: `closed` never overrides it, and nothing is released or launched.
    _repo(tmp_path, "vega", phase="querying", ticket="RDSD-7")
    supervisor.write_lock("vega", {"pid": CHAT_PID, "how": "matched by working directory", "repo": "vega",
                                   "path": Registry().get("vega").path, "session": "native-vega",
                                   "external": True})
    monkeypatch.setattr(A, "proc_alive", lambda pid: pid == CHAT_PID)
    with pytest.raises(FRESH.FreshRefused) as named:
        FRESH.run("vega", closed=True, cfg={})
    assert named.value.code == "foreign_session" and not named.value.second_press
    assert supervisor.read_lock("vega").get("external") and len(spawns["launched"]) == 1


def test_a_fresh_start_that_dies_never_resumes_the_session_it_left(fleet_home, copilot_home, tmp_path, spawns):  # noqa: F811
    _stale(tmp_path, "luna")
    FRESH.run("luna", cfg={})
    spawns["alive"].clear()                              # it died before its first `result`
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.send("luna", "carry on", cfg={})
    assert e.value.code == "no_session" and "no session to continue" in e.value.msg
    assert len(spawns["launched"]) == 1, "never `--resume s-luna`"


def test_a_keyless_fresh_start_has_no_empty_ticket_in_its_prompt(fleet_home, copilot_home, tmp_path, spawns):  # noqa: F811
    _stale(tmp_path, "done", phase="done", ticket="RDSD-5")
    _stale(tmp_path, "none", phase="idle", ticket="")
    for name in ("done", "none"):
        assert FRESH.plan(name, cfg={})["starts"]["ticket"] == ""
        FRESH.run(name, cfg={})
        assert supervisor.read_lock(name)["ticket"] == ""
    for argv in spawns["launched"]:
        said = _prompt(argv)
        assert "Ticket ." not in said and "Ticket" not in said.split("This is a fresh session")[0]
        assert said.startswith("Invoke skill session-bootstrap, then router.")
    # A configured template is the operator's own words, and is left as it is.
    from agentdata.fleet import launch as LAUNCH

    assert LAUNCH.prompt_for("", None, {"fleet": {"prompt_template": "Go {key}."}}) == "Go ."
    assert LAUNCH.prompt_for("RDSD-1", None, {}) == "Ticket RDSD-1. Invoke skill session-bootstrap, then router."


def test_the_left_session_stays_listed_and_marked(fleet_home, copilot_home, tmp_path, capsys, spawns):  # noqa: F811
    path = _stale(tmp_path, "luna", cost=3.5)
    copilot_file = _session_file(copilot_home, "native-luna", path, age_s=4000)
    copilot_bytes = open(copilot_file, "rb").read()
    before = {r["id"]: r for r in SESS.rebuild_sessions("luna", repo_path=path)}
    lines_before = len(E.read("luna"))
    FRESH.run("luna", cfg={})
    E.append("luna", [E.event("luna", "session_id", {"session": "s-fresh"}, ticket="RDSD-201")])

    after = {r["id"]: r for r in SESS.rebuild_sessions("luna", repo_path=path)}
    assert set(before) <= set(after), "nothing is removed"
    left = after["s-luna"]
    for k in ("source", "runs", "cost", "sources"):
        assert left[k] == before["s-luna"][k], k
    assert left["cost"] == 3.5 and left["left"]
    assert after["s-fresh"]["after"] == "s-luna" and "left" not in after["s-fresh"]
    assert len(E.read("luna")) > lines_before
    assert open(copilot_file, "rb").read() == copilot_bytes
    # The same bytes from the same stream.
    assert SESS.fold_stream(E.read("luna")) == SESS.fold_stream(E.read("luna"))

    assert cli_fleet.main(["sessions", "luna"]) == 0
    out = capsys.readouterr().out
    assert "left" in out and "s-luna" in out and left["left"][:16] in out


def test_the_row_says_when_to_offer_it_without_a_listing(fleet_home, copilot_home, tmp_path, monkeypatch):  # noqa: F811
    _stale(tmp_path, "stale")
    _adopted_by_file(tmp_path, copilot_home, "chat")
    _adopted_by_file(tmp_path, copilot_home, "quiet")
    quiet = time.time() - A.IDLE_S - 60
    os.utime(os.path.join(str(copilot_home), "native-quiet", "events.jsonl"), (quiet, quiet))
    supervisor.clear_lock("quiet")
    _repo(tmp_path, "current", events=[started(NOW), turn_ended()])

    asked = []
    real = A.agent_processes
    monkeypatch.setattr(A, "agent_processes", lambda **kw: asked.append(kw) or real(**kw))
    rows = {r["repo"]: r["fresh"] for r in S.fleet_snapshot()["repos"]}
    assert all(kw.get("wait") is False and kw.get("max_age", 1) != 0 for kw in asked), asked
    assert (rows["stale"]["offer"], rows["stale"]["because"], rows["stale"]["verdict"]) == (True, "old skills", "now")
    assert rows["stale"]["starts"] == {**rows["stale"]["starts"], "ticket": "RDSD-201",
                                       "model_label": "", "model_source": "cli-auto"}
    assert (rows["chat"]["offer"], rows["chat"]["because"], rows["chat"]["verdict"]) == \
        (True, "your own chat", "second_press")
    assert (rows["quiet"]["offer"], rows["quiet"]["because"]) == (True, "began outside the fleet")
    assert rows["current"]["offer"] is False and rows["current"]["because"] == ""


def test_the_cli_previews_refuses_and_takes_the_second_press(fleet_home, copilot_home, tmp_path, capsys, spawns):  # noqa: F811
    _stale(tmp_path, "sol")
    assert cli_fleet.main(["fresh", "sol", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "verdict: now" in out and "s-sol" in out and "ad-fleet sessions sol" in out and "RDSD-201" in out
    assert spawns["launched"] == []

    _adopted_by_file(tmp_path, copilot_home, "luna")
    assert cli_fleet.main(["fresh", "luna"]) == 2
    out = capsys.readouterr().out
    assert "code: chat_open" in out and "--closed" in out and "error:" in out and "hint:" in out
    assert spawns["launched"] == []
    assert cli_fleet.main(["fresh", "luna", "--closed"]) == 0
    assert "done: started" in capsys.readouterr().out and len(spawns["launched"]) == 1
    with pytest.raises(SystemExit):
        cli_fleet.main(["fresh", "--help"])
    assert "--closed" in capsys.readouterr().out


def test_the_api_answers_what_the_cli_answers(fleet_home, copilot_home, tmp_path, capsys, spawns):  # noqa: F811
    _adopted_by_file(tmp_path, copilot_home, "luna")
    _stale(tmp_path, "sol")
    assert cli_fleet.main(["fresh", "luna"]) == 2
    said = capsys.readouterr().out
    server, token, port = _serve()
    try:
        def post(body):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("POST", f"/api/fresh?t={token}", body=json.dumps(body),
                         headers={"Content-Type": "application/json"})
            r = conn.getresponse()
            return r.status, json.loads(r.read())

        status, refused = post({"repo": "luna"})
        assert status == 409 and refused["code"] == "chat_open" and refused["second_press"] is True
        assert refused["error"] in said.replace("\n", " ") or refused["error"][:60] in said
        assert refused["hint"] and "--closed" in refused["hint"]
        status, preview = post({"repo": "sol", "dry_run": True})
        assert status == 200 and preview["verdict"] == "now" and spawns["launched"] == []
        status, done = post({"repo": "luna", "closed": True})
        assert status == 200 and done["done"] == "started" and done["row"]["repo"] == "luna"
        assert len(spawns["launched"]) == 1
        status, again = post({"repo": "luna"})
        assert status == 409 and again["code"] == "mid_turn" and "second_press" not in again
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()

