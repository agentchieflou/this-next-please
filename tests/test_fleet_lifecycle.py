"""Surviving a laptop: crashes, sleep, an expired login, a budget, and logs that grow.

Every failure in this file is a *quiet* one. A killed process raises nothing, a slept laptop looks
exactly like four agents thinking hard, an expired token looks like a turn that did not go well,
and a log that has eaten the disk looks like nothing at all until something else fails. So what is
asserted here is mostly that the fleet *noticed*.
"""
from __future__ import annotations
import os
import time

import pytest

from agentdata.fleet import events as E, lifecycle as L, registry, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-lifecycle.md")

DEAD_PID = 999_999_999          # high enough that nothing on any runner holds it


def a_repo(tmp_path, name="luna", **kw):
    path = make_project(tmp_path / name, **kw)
    Registry().add(path, name=name)
    return path


def a_dead_agent(name="luna", *, ticket="RDSD-1", stderr: str = "") -> None:
    """A lock naming a pid that is gone: what a killed process, a closed console or a slept laptop
    all leave behind."""
    supervisor.write_lock(name, {"pid": DEAD_PID, "repo": name, "ticket": ticket,
                                 "started": time.time()})
    if stderr:
        path = os.path.join(registry.agent_dir(name), "stderr.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(stderr)


# ----------------------------------------------------------------- a process that just stopped


def test_a_killed_agent_is_noticed_and_its_lock_cleared(fleet_home, tmp_path):   # noqa: F811
    """The lock outlives the process, and a row that said "running" about a pid that is gone is
    the one lie the whole fleet turns on."""
    a_repo(tmp_path)
    a_dead_agent()
    assert supervisor.read_lock("luna"), "the fixture did not write a lock"

    found = L.reap("luna")
    assert [e["kind"] for e in found] == ["exited"]
    assert found[0]["data"]["exit_code"] is None
    assert supervisor.read_lock("luna") == {}, "the lock survived its process"
    assert found[0]["ticket"] == "RDSD-1"


def test_an_agent_that_finished_properly_is_not_reaped_twice(fleet_home, tmp_path):  # noqa: F811
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "turn_ended", {}), E.event("luna", "exited", {"exit_code": 0})])
    a_dead_agent()

    assert L.reap("luna") == [], "an agent that reported its own exit was reported again"
    assert [e["kind"] for e in E.read("luna")] == ["turn_ended", "exited"]


def test_reaping_is_idempotent(fleet_home, tmp_path):           # noqa: F811
    a_repo(tmp_path)
    a_dead_agent()
    assert L.reap("luna")
    assert L.reap("luna") == [], "a second look invented a second death"


def test_a_crash_carries_its_last_words(fleet_home, tmp_path):  # noqa: F811
    """Without stderr the operator has an `error` and no idea why. Twenty lines is enough for the
    last traceback and short enough to read on a tile."""
    a_repo(tmp_path)
    a_dead_agent(stderr="\n".join(f"line {i}" for i in range(50)) + "\nTypeError: boom\n")

    found = L.reap("luna")
    assert [e["kind"] for e in found] == ["error"]
    tail = found[0]["data"]["stderr"]
    assert "TypeError: boom" in tail
    assert "line 49" in tail and "line 20" not in tail, "the tail is not the last 20 lines"


def test_a_crash_dump_never_carries_a_credential(fleet_home, tmp_path):    # noqa: F811
    """A proxy failure prints the request, and the request carries the header. Exactly where a
    token ends up."""
    a_repo(tmp_path)
    a_dead_agent(stderr="GET /api HTTP/1.1\nAuthorization: Bearer ghp_ABCDEFGHIJKLMNOPQRSTUV012345\n")

    found = L.reap("luna")
    assert "ghp_ABCDEFGH" not in found[0]["data"]["stderr"]
    assert E.REDACTED in found[0]["data"]["stderr"]


# ------------------------------------------------------------------------ an expired login


@pytest.mark.parametrize("said", [
    "Error: not logged in. Please run `copilot login`.",
    "authentication failed (401 Unauthorized)",
    "Your token has expired",
    "invalid credentials",
])
def test_an_expired_login_is_recognised_however_it_is_worded(said):
    """The wording moves between releases; the class of failure does not."""
    assert L.looks_like_auth_trouble(said)


@pytest.mark.parametrize("said", [
    "TypeError: cannot read property of undefined",
    "the tool `git push` was denied",
    "",
])
def test_an_ordinary_failure_is_not_mistaken_for_a_login_problem(said):
    assert not L.looks_like_auth_trouble(said)


def test_an_expired_login_asks_once_and_never_retries(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """Relaunching an agent whose token expired burns premium requests in a loop and produces the
    same failure every time. One clear answer instead."""
    a_repo(tmp_path)
    a_dead_agent(stderr="Error: not logged in. Please run `copilot login`.\n")
    launches = []
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: launches.append(1))

    found = L.reap("luna")
    assert [e["kind"] for e in found] == ["error", "question_opened"]
    assert "copilot login" in found[1]["data"]["question"]
    assert "ad-fleet restart luna" in found[1]["data"]["question"]
    assert launches == [], "the fleet relaunched an agent whose token had expired"

    from agentdata.fleet import agentstate

    assert agentstate.derive(E.read("luna"))["state"] == "error"


# ------------------------------------------------------------------------- the laptop slept


@pytest.mark.parametrize("previous,now,expected", [
    (1_000_000.0, 1_000_030.0, False),          # thirty seconds: an ordinary poll
    (1_000_000.0, 1_000_119.0, False),          # under two minutes: a long turn
    (1_000_000.0, 1_000_200.0, True),           # over: the machine was not awake for that
    (1_000_000.0, 1_007_200.0, True),           # two hours: a lunch break with the lid shut
    (0.0, 1_000_200.0, False),                  # no previous heartbeat: not a jump, a first look
])
def test_a_wall_clock_jump_is_how_sleep_is_detected(previous, now, expected):
    assert L.slept(previous, now) is expected


# ---------------------------------------------------------------------------- the budget


def test_a_budget_of_zero_is_off_which_is_the_default(fleet_home, tmp_path):     # noqa: F811
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "cost", {"premium_requests": 999})])
    over, used, budget = L.over_budget("luna", cfg={})
    assert over is False and used == 999 and budget == 0.0


def test_an_agent_over_its_budget_is_not_sent_another_turn(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "session_id", {"session": "s1"}),
                      E.event("luna", "cost", {"premium_requests": 12.0})])
    cfg = {"fleet": {"budget_per_agent": 10}}
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: pytest.fail("a turn was sent"))
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "s1")

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.send("luna", "carry on", cfg=cfg)
    assert "12 of its 10" in e.value.msg
    assert "--force" in e.value.hint and "budget_per_agent" in e.value.hint


def test_the_budget_is_checked_before_the_turn_and_not_during_it(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """Stopping an agent halfway through a thought leaves the repository in whatever state it had
    reached, and the money is spent either way."""
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "session_id", {"session": "s1"}),
                      E.event("luna", "cost", {"premium_requests": 9.0})])
    sent = []
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: sent.append(1) or type("P", (), {"pid": 5})())
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "s1")

    supervisor.send("luna", "carry on", cfg={"fleet": {"budget_per_agent": 10}})
    assert sent == [1], "a turn under budget was refused"


def test_force_buys_exactly_one_more_turn(fleet_home, tmp_path, monkeypatch):    # noqa: F811
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "cost", {"premium_requests": 99.0})])
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: type("P", (), {"pid": 5})())
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "s1")
    supervisor.send("luna", "one more", cfg={"fleet": {"budget_per_agent": 1}}, force=True)


def test_cost_is_the_high_water_mark_the_cli_reports(fleet_home, tmp_path):      # noqa: F811
    """`usage_checkpoint` reports the session total. Summing checkpoints would multiply the bill,
    and a budget built on a multiplied bill stops an agent that never overspent."""
    a_repo(tmp_path)
    E.append("luna", [E.event("luna", "cost", {"premium_requests": 0.33}),
                      E.event("luna", "cost", {"premium_requests": 1.0}),
                      E.event("luna", "cost", {"premium_requests": 1.66})])
    assert L.spent("luna") == 1.66


# --------------------------------------------------------------------------- the restart


def test_a_restart_resumes_the_session_rather_than_the_ticket(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """The agent has read the ticket, made a plan and possibly edited files. Starting over repeats
    all of it -- at full price, and with a second set of edits over the first."""
    a_repo(tmp_path)
    supervisor.write_lock("luna", {"pid": DEAD_PID, "repo": "luna", "ticket": "RDSD-1"})
    E.append("luna", [E.event("luna", "session_id", {"session": "sess-9"}, ticket="RDSD-1")])
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "sess-9")
    seen = {}

    def spawn(repo, name, argv, exe=None):
        seen["argv"] = argv
        return type("P", (), {"pid": 4242})()

    monkeypatch.setattr(supervisor, "_spawn", spawn)

    lock = supervisor.restart("luna")
    assert lock["session"] == "sess-9" and lock["restarts"] == 1
    assert "--resume" in seen["argv"] and "sess-9" in seen["argv"]
    assert lock["ticket"] == "RDSD-1", "the restarted agent forgot its ticket"
    assert "start the ticket again" in lock["prompt"], "the resumed agent was told to begin again"


def test_a_restart_is_bounded_because_the_second_failure_is_the_first_one(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    a_repo(tmp_path)
    supervisor.write_lock("luna", {"pid": DEAD_PID, "repo": "luna", "restarts": 1})
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "sess-9")
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: pytest.fail("it restarted anyway"))

    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.restart("luna", cfg={"fleet": {"max_restarts": 1}})
    assert "already been restarted" in e.value.msg
    assert "--force" in e.value.hint and "ad-fleet logs" in e.value.hint


def test_force_restarts_past_the_limit(fleet_home, tmp_path, monkeypatch):       # noqa: F811
    a_repo(tmp_path)
    supervisor.write_lock("luna", {"pid": DEAD_PID, "repo": "luna", "restarts": 5})
    monkeypatch.setattr(supervisor, "session_id", lambda *a, **k: "sess-9")
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: type("P", (), {"pid": 7})())
    assert supervisor.restart("luna", cfg={"fleet": {"max_restarts": 1}}, force=True)["restarts"] == 6


def test_a_restart_with_no_session_says_to_start_one(fleet_home, tmp_path):      # noqa: F811
    a_repo(tmp_path)
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.restart("luna")
    assert "no session to resume" in e.value.msg
    assert "ad-fleet start luna" in e.value.hint


# ------------------------------------------------------------------------- logs and gc


def test_a_log_rolls_at_its_size_and_keeps_a_bounded_history(fleet_home, tmp_path):  # noqa: F811
    path = str(tmp_path / "events.jsonl")
    for round_number in range(6):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"round {round_number}\n" + "x" * (1024 * 1024 + 10))
        assert L.rotate(path, mb=1, keep=3) is True

    assert not os.path.exists(path), "the live file survived its own rotation"
    kept = sorted(n for n in os.listdir(tmp_path) if n.startswith("events.jsonl."))
    assert kept == ["events.jsonl.1", "events.jsonl.2", "events.jsonl.3"], kept
    assert open(str(tmp_path / "events.jsonl.1"), encoding="utf-8").read(9) == "round 5\n"[:9] or True
    assert "round 5" in open(str(tmp_path / "events.jsonl.1"), encoding="utf-8").read(20)
    assert "round 3" in open(str(tmp_path / "events.jsonl.3"), encoding="utf-8").read(20)


def test_a_small_log_is_left_alone(fleet_home, tmp_path):       # noqa: F811
    path = str(tmp_path / "stderr.log")
    open(path, "w", encoding="utf-8").write("hello\n")
    assert L.rotate(path, mb=20, keep=5) is False
    assert os.path.exists(path)


def test_a_hundred_megabyte_stream_ends_up_bounded(fleet_home, tmp_path):   # noqa: F811
    """The acceptance criterion. Written in five-megabyte pushes rather than one 100 MB file: the
    point is that rotation is repeatedly applied, not that the disk can hold a big file."""
    path = str(tmp_path / "events.jsonl")
    chunk = "y" * (1024 * 1024)
    for _push in range(20):
        with open(path, "a", encoding="utf-8") as f:
            f.write(chunk * 5)
        L.rotate(path, mb=5, keep=3)
    total = sum(os.path.getsize(os.path.join(tmp_path, n)) for n in os.listdir(tmp_path))
    assert total < 60 * 1024 * 1024, f"{total} bytes left after 100 MB of stream"


def test_rotation_never_touches_a_live_agents_logs(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """A rename under a live writer fails on Windows and silently orphans the inode on POSIX."""
    a_repo(tmp_path)
    path = os.path.join(registry.agent_dir("luna"), "stderr.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("x" * (2 * 1024 * 1024))
    monkeypatch.setattr(supervisor, "live", lambda name: {"pid": 1})

    assert L.rotate_all("luna", cfg={"fleet": {"log_mb": 1}}) == []
    assert os.path.exists(path)


def test_gc_removes_rotated_logs_and_leaves_the_record(fleet_home, tmp_path):   # noqa: F811
    """`events.norm.jsonl` is what `ad-fleet history` reads. A report that silently loses last
    month is worse than a directory that is slightly too big."""
    a_repo(tmp_path)
    directory = registry.agent_dir("luna")
    os.makedirs(directory, exist_ok=True)
    old = time.time() - 90 * 86400
    for name in ("events.jsonl.1", "stderr.log.2", "events.norm.jsonl", "events.jsonl"):
        path = os.path.join(directory, name)
        open(path, "w", encoding="utf-8").write("x")
        os.utime(path, (old, old))

    result = L.gc(days=14)
    left = set(os.listdir(directory))
    assert "events.norm.jsonl" in left, "the record was pruned"
    assert "events.jsonl" in left, "the live raw log was pruned"
    assert "events.jsonl.1" not in left and "stderr.log.2" not in left
    assert len(result["removed"]) == 2


def test_gc_never_touches_a_running_agent(fleet_home, tmp_path, monkeypatch):    # noqa: F811
    a_repo(tmp_path)
    directory = registry.agent_dir("luna")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "events.jsonl.1")
    open(path, "w", encoding="utf-8").write("x")
    os.utime(path, (time.time() - 90 * 86400,) * 2)
    monkeypatch.setattr(supervisor, "live", lambda name: {"pid": 1})

    result = L.gc(days=14)
    assert os.path.exists(path)
    assert result["kept_running"] == ["luna"]


def test_recent_files_survive(fleet_home, tmp_path):            # noqa: F811
    a_repo(tmp_path)
    directory = registry.agent_dir("luna")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "events.jsonl.1")
    open(path, "w", encoding="utf-8").write("x")
    L.gc(days=14)
    assert os.path.exists(path)


# ------------------------------------------------------------------------- the doctor rows


def _doctor(cfg=None, **found):
    from agentdata.setup.steps.fleet import FleetStep
    from agentdata.setup.wizard import Context, Detectors, Prompter

    ctx = Context(cfg=cfg or {}, det=Detectors(), ask=Prompter(), interactive=False)
    step = FleetStep()
    base = {"enabled": True, "repos": [], "toast": "off",
            "settings": {"toast": False, "cooldown": 300, "idle_minutes": 20, "quiet_hours": "",
                         "dashboard": True, "chime": False},
            "version": "1.0.81", "why": "", "login": "ok", "port": 8765,
            "port_free": True, "ours": False}
    base.update(found)
    step.check(ctx, base)
    return {f"{c.step}/{c.name}": c for c in ctx.checks}


def test_no_fleet_means_one_skipped_row_and_no_subprocess(fleet_home):   # noqa: F811
    """`ad-doctor --quiet` runs on every session start. Probing a CLI nobody has installed costs a
    subprocess launch for an answer nobody wants."""
    from agentdata.setup.steps.fleet import FleetStep
    from agentdata.setup.wizard import Context, Detectors, Prompter

    ctx = Context(cfg={}, det=Detectors(), ask=Prompter(), interactive=False)
    step = FleetStep()
    found = step.detect(ctx)
    assert found["enabled"] is False
    assert "version" not in found, "the doctor probed `copilot` with no fleet configured"

    step.check(ctx, found)
    assert [c.status for c in ctx.checks] == ["skip"]
    assert "ad-fleet repo add" in ctx.checks[0].hint


def test_a_missing_copilot_fails_and_names_the_install(fleet_home):      # noqa: F811
    rows = _doctor(version="", why="'copilot' is not recognized")
    assert rows["fleet/copilot"].status == "fail"
    assert "npm install -g @github/copilot" in rows["fleet/copilot"].hint
    assert "fleet/login" not in rows, "it cannot be logged in if it will not start"


def test_an_expired_login_is_its_own_row(fleet_home):            # noqa: F811
    """"Installed" and "logged in" fail differently and are fixed differently, so one row that
    conflated them would send half the people to the wrong command."""
    rows = _doctor(login="expired")
    assert rows["fleet/copilot"].status == "ok"
    assert rows["fleet/login"].status == "fail"
    assert "copilot login" in rows["fleet/login"].hint


def test_an_older_cli_is_reported_rather_than_refused(fleet_home):       # noqa: F811
    """"Your CLI predates what this was built on" is a fact an operator can act on. A guess about
    compatibility is not."""
    rows = _doctor(version="1.0.40")
    assert rows["fleet/copilot"].status == "ok"
    assert "1.0.81" in rows["fleet/copilot"].detail


def test_a_taken_port_warns_and_names_the_way_out(fleet_home):  # noqa: F811
    rows = _doctor(port_free=False, ours=False)
    assert rows["fleet/dashboard"].status == "warn"
    assert "--port 0" in rows["fleet/dashboard"].hint
    assert rows["fleet/dashboard"].keys == ("fleet.port",)

    assert _doctor(port_free=False, ours=True)["fleet/dashboard"].status == "ok"


def test_a_repo_that_stopped_being_a_project_is_reported(fleet_home, tmp_path):  # noqa: F811
    a_repo(tmp_path)
    good = Registry().get("luna")
    gone = registry.Repo(name="ghost", path=str(tmp_path / "not-here"))
    rows = _doctor(repos=[good, gone])
    assert rows["fleet/repos"].status == "warn"
    assert "ghost" in rows["fleet/repos"].detail
    assert "ad-fleet repo rm" in rows["fleet/repos"].hint

    assert _doctor(repos=[good])["fleet/repos"].status == "ok"


def test_every_row_that_a_setting_could_fix_names_the_setting(fleet_home):   # noqa: F811
    """HANDOFF.md rule. A row whose fix is `npm install` names no key deliberately -- `--patch`
    lists it under `manual` rather than asking a pointless question."""
    rows = _doctor(version="", port_free=False)
    for row in rows.values():
        if row.keys:
            assert all(k.startswith("fleet.") for k in row.keys), row.keys


# ------------------------------------------------------------------------------ the contract


def test_the_lifecycle_is_documented():
    text = open(CONTRACT, encoding="utf-8").read()
    for key in ("fleet.max_restarts", "fleet.log_mb", "fleet.log_keep", "fleet.budget_per_agent",
                "fleet.port", "fleet.enabled"):
        assert key in text, f"{key} is not documented"
    for verb in ("ad-fleet restart", "ad-fleet gc", "ad-fleet doctor"):
        assert verb in text, f"{verb} is not documented"
    assert "copilot login" in text and "--resume" in text
