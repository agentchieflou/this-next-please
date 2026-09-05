"""The normalized event contract, and the state machine every later slice reads.

The raw shapes here are the ones `docs/fleet-spike.md` recorded from a real `copilot` run, not
invented ones -- a fake that invents output proves the code handles a shape nobody has seen.
"""
from __future__ import annotations
import json
import os
import time

import pytest

from agentdata.fleet import agentstate, events as E, registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project           # the same project builder the supervisor tests use

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-events.md")


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


# The event shapes as measured. Anything here that stops matching the CLI is a real regression.
RAW_TURN = [
    {"type": "assistant.turn_start", "timestamp": "2026-01-01T00:00:00Z", "data": {"turnId": "0"}},
    {"type": "assistant.message_delta", "ephemeral": True, "data": {"delta": "hel"}},
    {"type": "tool.execution_start", "timestamp": "2026-01-01T00:00:01Z",
     "data": {"toolCallId": "t1", "toolName": "powershell",
              "arguments": {"command": "git status --short"}}},
    {"type": "tool.execution_complete", "timestamp": "2026-01-01T00:00:02Z",
     "data": {"toolCallId": "t1", "success": True}},
    {"type": "assistant.message", "timestamp": "2026-01-01T00:00:03Z",
     "data": {"content": "the tree is clean", "model": "claude-haiku-4.5", "toolRequests": []}},
    {"type": "assistant.turn_end", "timestamp": "2026-01-01T00:00:04Z", "data": {"turnId": "0"}},
    {"type": "result", "timestamp": "2026-01-01T00:00:05Z", "sessionId": "sess-1", "exitCode": 0,
     "usage": {"premiumRequests": 0.33, "codeChanges": {"filesModified": []}}},
]

DENIED = {"type": "tool.execution_complete", "timestamp": "2026-01-01T00:00:02Z",
          "data": {"toolCallId": "t9", "success": False,
                   "error": {"code": "denied",
                             "message": "Permission denied and could not request permission from user"}}}


def _kinds(events):
    return [e["kind"] for e in events]


# ------------------------------------------------------------------------------- the mapping


def test_a_turn_maps_to_the_narrative_and_drops_the_noise():
    got = []
    for raw in RAW_TURN:
        got.extend(E.from_copilot(raw, "a"))
    assert _kinds(got) == ["turn_started", "tool_call", "tool_result", "assistant_text",
                           "turn_ended", "session_id", "cost", "exited"], _kinds(got)
    assert all(e["schema"] == E.SCHEMA for e in got)


def test_the_result_event_is_read_at_the_top_level():
    """`result` is the one event not shaped {type,id,parentId,timestamp,data} -- measured. Reading
    its fields under `data` would silently lose the session id, the cost and the exit code."""
    got = E.from_copilot(RAW_TURN[-1], "a")
    by_kind = {e["kind"]: e["data"] for e in got}
    assert by_kind["session_id"]["session"] == "sess-1"
    assert by_kind["cost"]["premium_requests"] == 0.33
    assert by_kind["exited"]["exit_code"] == 0


def test_a_denied_tool_yields_its_own_kind():
    """There is no permission-request event, so this is the only signal that the agent wanted
    something it may not have. #94 was written expecting a request event; there is none."""
    got = E.from_copilot(DENIED, "a")
    assert _kinds(got) == ["tool_result", "denied"]
    assert "Permission denied" in got[1]["data"]["message"]


def test_an_unknown_kind_passes_through_as_raw_and_never_raises():
    """A Copilot upgrade will add event kinds. A reader that raised would turn that into an outage."""
    got = E.from_copilot({"type": "session.something_new_in_1_1", "timestamp": "2026-01-01T00:00:00Z",
                          "data": {"whatever": 1}}, "a")
    assert _kinds(got) == ["raw"]
    assert got[0]["data"]["type"] == "session.something_new_in_1_1"


def test_one_clock_for_the_whole_stream(monkeypatch):
    """Copilot stamps UTC with a `Z`; stamping ours with local time put 09:31 next to 05:08 on the
    same second of the same run, which reads as an event four hours in the past."""
    assert E.stamp("2026-01-04T09:31:41Z") == "2026-01-04T09:31:41"
    assert E.stamp("2026-01-04T09:31:41+00:00") == "2026-01-04T09:31:41"
    mine, theirs = E.stamp(), E.stamp(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    assert mine[:13] == theirs[:13], f"{mine} and {theirs} are not the same clock"


def test_ephemeral_events_produce_nothing():
    assert E.from_copilot({"type": "assistant.reasoning_delta", "ephemeral": True, "data": {}}, "a") == []


# --------------------------------------------------------------------------------- redaction


@pytest.mark.parametrize("payload,needle", [
    ({"api_key": "abcd1234abcd1234"}, "abcd1234abcd1234"),
    ({"output": "export GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"}, "ghp_ABCDEFGH"),
    ({"nested": [{"client_secret": "s3cr3t-value-here"}]}, "s3cr3t-value-here"),
])
def test_no_credential_shaped_value_reaches_the_stream(payload, needle):
    """A tool result is arbitrary text from a command we did not write, so the key is not always a
    clue -- both the key rule and the value shapes are checked."""
    text = json.dumps(E.event("a", "tool_result", payload))
    assert needle not in text, text
    assert E.REDACTED in text


# ------------------------------------------------------------------- state.json and friction


def test_state_changes_become_events():
    before = {"phase": "idle", "open_questions": [], "artifacts": []}
    after = {"phase": "triaged", "active_ticket": "RDSD-1", "open_questions": ["which env?"],
             "artifacts": ["plan.md"], "pr_url": "https://example.invalid/pr/1"}
    got = E.from_state(before, after, "a")
    assert _kinds(got) == ["phase_changed", "question_opened", "artifact", "pr_open"]
    assert got[0]["data"] == {"from": "idle", "to": "triaged"}
    assert got[1]["data"]["question"] == "which env?"
    assert all(e["ticket"] == "RDSD-1" for e in got)


@pytest.mark.parametrize("encoding,newline", [
    ("utf-8", "\n"),            # what pwsh 7 and a sane editor write
    ("utf-8-sig", "\r\n"),      # a BOM, which Windows PowerShell 5.1 used to add
    ("utf-16", "\r\n"),         # what `>` produced under 5.1
])
def test_a_friction_file_yields_its_unblock_sentence_however_it_was_written(tmp_path, encoding, newline):
    """The skills are prose files edited by whatever is to hand. Reading them through `textio` is
    what makes the badly-encoded ones the same event as the clean ones."""
    directory = tmp_path / ".agent" / "friction"
    directory.mkdir(parents=True)
    path = directory / "20260101-jira-triage.md"
    body = ("# Friction\n\n## What happened\n\nThe acceptance criteria contradict each other.\n\n"
            "## What would unblock me\n\nA decision on whether RDSD-1 covers the UAT env.\n")
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(body)

    ev = E.friction_event(str(path), "a")
    assert ev["kind"] == "friction"
    assert ev["data"]["unblock"] == "A decision on whether RDSD-1 covers the UAT env."


# ------------------------------------------------------------------------ merging, idempotent


def _write_raw(name, raws):
    from agentdata.fleet.supervisor import events_path

    path = events_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for raw in raws:
            f.write(json.dumps(raw) + "\n")


def test_refresh_is_idempotent_and_ordered(fleet_home, tmp_path):
    repo = make_project(tmp_path / "repo-a", phase="idle")
    Registry().add(repo, name="a")
    _write_raw("a", RAW_TURN)

    first = E.refresh("a", repo, repo_state={"phase": "idle", "open_questions": [], "artifacts": []})
    again = E.refresh("a", repo, repo_state={"phase": "idle", "open_questions": [], "artifacts": []})

    assert first and not again, "replaying the same inputs produced the stream twice"
    stream = E.read("a")
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1)), "seq must be dense and ordered"
    assert "exited" in _kinds(stream)


def test_since_and_kind_filters_do_what_they_say(fleet_home, tmp_path):
    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    _write_raw("a", RAW_TURN)
    E.refresh("a", repo, repo_state={})

    everything = E.read("a")
    assert E.read("a", since=everything[2]["seq"]) == everything[3:]
    assert _kinds(E.read("a", kinds=("assistant_text",))) == ["assistant_text"]


# ------------------------------------------------------------------------- two writers at once


def test_concurrent_writers_never_hand_out_the_same_seq(fleet_home, tmp_path):
    """Two writers is the normal case, not an edge: `ad-state` emits from inside the agent while
    `ad-fleet serve` refreshes the same stream from the operator's machine. Unlocked, both read
    `seq: 5` and both write a `seq: 6`, and the dense, never-reused numbering this contract promises
    is quietly untrue."""
    import threading

    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    writers, each = 8, 12
    total = writers * each
    ready = threading.Barrier(writers)

    def writer(n):
        ready.wait()
        for i in range(each):
            E.append("a", [E.event("a", "assistant_text", {"text": f"{n}-{i}"})])

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    seqs = [e["seq"] for e in E.read("a")]
    assert len(seqs) == total, f"{len(seqs)} of {total} events survived"
    assert seqs == sorted(seqs) and len(set(seqs)) == total, "a seq was reused"
    assert seqs == list(range(1, total + 1)), "the numbering is not dense"


def test_a_refresh_racing_an_append_loses_nothing(fleet_home, tmp_path):
    """Exactly the CI failure this lock was written for: the SSE loop refreshing while the agent
    appends. Both write the cursor, and unlocked they clobbered each other's staging file."""
    import threading

    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    _write_raw("a", RAW_TURN)
    stop = threading.Event()
    errors = []

    def refresher():
        while not stop.is_set():
            try:
                E.refresh("a", repo, repo_state={"phase": "idle"})
            except E.Busy:
                pass                                              # the documented answer; retry
            except Exception as e:                                # noqa: BLE001 - that is the point
                errors.append(e)
            stop.wait(0.01)                                       # as the SSE loop paces itself

    t = threading.Thread(target=refresher, daemon=True)
    t.start()
    try:
        for i in range(20):
            E.append("a", [E.event("a", "assistant_text", {"text": f"line {i}"})])
    finally:
        stop.set()
        t.join(timeout=30)

    assert not errors, f"the refresher raised: {errors[:3]}"
    stream = E.read("a")
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    said = [e["data"]["text"] for e in stream if e["kind"] == "assistant_text"]
    assert sorted(said) == sorted([f"line {i}" for i in range(20)] + ["the tree is clean"])


def test_a_writer_that_cannot_get_the_lock_writes_nothing_at_all(fleet_home, tmp_path, monkeypatch):
    """The first version of this proceeded unlocked rather than lose an event, and CI produced a
    duplicate `seq` for it. That trade is backwards: a dropped append is recovered on the next
    `refresh`, which re-reads state.json and re-emits what changed, while a duplicate `seq` is
    permanent and makes every reader resuming from a cursor skip real events."""
    make_project(tmp_path / "repo-a")
    Registry().add(str(tmp_path / "repo-a"), name="a")
    path = os.path.join(registry.agent_dir("a"), E.LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()                                       # a live holder: fresh mtime
    monkeypatch.setattr(E, "LOCK_WAIT_S", 0.2)

    with pytest.raises(E.Busy) as e:
        E.append("a", [E.event("a", "assistant_text", {"text": "should not land"})])
    assert e.value.repo == "a"
    assert isinstance(e.value, OSError), "every reader already treats an OS error as 'not this time'"
    assert E.read("a") == [], "a refused write still wrote"


def test_a_busy_stream_never_fails_a_state_save(fleet_home, tmp_path, monkeypatch):
    """`ad-state` is the only writer of state.json. A held event lock must not cost a decision."""
    from agentdata import state as S

    repo = make_project(tmp_path / "repo-a", phase="idle")
    Registry().add(repo, name="a")
    path = os.path.join(registry.agent_dir("a"), E.LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    monkeypatch.setattr(E, "LOCK_WAIT_S", 0.2)
    monkeypatch.setenv(registry.AGENT_ENV, "a")

    S.save({"phase": "blocked"}, os.path.join(repo, ".agent", "state.json"))
    assert json.loads(open(os.path.join(repo, ".agent", "state.json"), encoding="utf-8").read())["phase"] == "blocked"


def test_a_lock_that_was_merely_released_is_never_mistaken_for_a_stale_one(fleet_home, tmp_path):
    """The exact hole CI found. The first version called a missing lock "stale" -- which is what a
    *released* lock looks like -- and then deleted whatever was at that path. Between the check and
    the delete another waiter could have taken the lock, so the delete removed a live holder's lock
    and two writers ran at once: one duplicate `seq` in thirty, on a loaded runner, never locally."""
    make_project(tmp_path / "repo-a")
    Registry().add(str(tmp_path / "repo-a"), name="a")
    path = os.path.join(registry.agent_dir("a"), E.LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    assert E._age_of(path) == 0.0, "a lock that does not exist must not read as infinitely old"
    E._steal_if_stale(path)                                       # nothing there: must not raise

    open(path, "w").close()                                       # a live holder, taken just now
    E._steal_if_stale(path)
    assert os.path.exists(path), "a fresh lock was stolen from its holder"


def test_a_lock_left_by_a_dead_writer_is_stolen(fleet_home, tmp_path):
    """A crash must not block a repository's stream forever -- the events are how anyone finds out
    it crashed."""
    make_project(tmp_path / "repo-a")
    Registry().add(str(tmp_path / "repo-a"), name="a")
    path = os.path.join(registry.agent_dir("a"), E.LOCK)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    old = time.time() - E.LOCK_STALE_S - 60
    os.utime(path, (old, old))

    E.append("a", [E.event("a", "assistant_text", {"text": "after the crash"})])
    assert [e["data"]["text"] for e in E.read("a")] == ["after the crash"]
    assert not os.path.exists(path), "the stolen lock was not released"


# ------------------------------------------------------------------------- the state machine


def _events(*specs):
    return [E.event("a", kind, data or {}) for kind, data in specs]


def test_a_clean_finished_turn_is_idle():
    got = agentstate.derive(_events(("turn_started", {}), ("assistant_text", {"text": "done."}),
                                    ("turn_ended", {}), ("exited", {"exit_code": 0})))
    assert got["state"] == "idle"
    assert not agentstate.needs_the_human(got["state"])


def test_a_denied_tool_makes_the_agent_need_the_human():
    got = agentstate.derive(_events(("turn_started", {}), ("denied", {"message": "no `git push`"}),
                                    ("turn_ended", {})))
    assert got["state"] == "needs_human"
    assert "git push" in got["why"]
    assert agentstate.needs_the_human(got["state"])


def test_a_friction_file_outranks_a_question():
    """Both mean "stopped", but the friction log says what would unblock it and a question does not."""
    got = agentstate.derive(_events(("question_opened", {"question": "which env?"}),
                                    ("friction", {"unblock": "a decision on the UAT env"}),
                                    ("turn_ended", {})))
    assert got["state"] == "blocked"
    assert got["why"] == "a decision on the UAT env"


def test_an_assistant_that_ends_on_a_question_needs_the_human():
    got = agentstate.derive(_events(("turn_started", {}),
                                    ("assistant_text", {"text": "Should I use the UAT env?"}),
                                    ("turn_ended", {})))
    assert got["state"] == "needs_human"


def test_a_non_zero_exit_is_an_error():
    got = agentstate.derive(_events(("turn_started", {}), ("turn_ended", {}),
                                    ("error", {"exit_code": 2})))
    assert got["state"] == "error"
    assert "2" in got["why"]


def test_a_live_process_is_running_whatever_the_history_says():
    got = agentstate.derive(_events(("denied", {"message": "x"}), ("turn_ended", {})), live=True)
    assert got["state"] == "running"


def test_a_terminal_phase_is_done():
    got = agentstate.derive(_events(("phase_changed", {"to": "pr_open"}), ("turn_ended", {})))
    assert got["state"] == "done"


def test_no_events_at_all_is_starting():
    assert agentstate.derive([])["state"] == "starting"


def test_cost_is_the_high_water_mark_not_a_sum_of_checkpoints():
    """`session.usage_checkpoint` reports the session total so far, so adding checkpoints up would
    multiply the bill. #101 budgets from this number."""
    got = agentstate.derive(_events(("cost", {"premium_requests": 0.33}),
                                    ("cost", {"premium_requests": 1.0}),
                                    ("turn_ended", {})))
    assert got["premium_requests"] == 1.0


# ----------------------------------------------------------------------- the ad-state emit


def test_ad_state_emits_to_the_fleet_only_when_it_is_in_one(fleet_home, tmp_path, monkeypatch):
    """Outside a fleet the behaviour must be byte-identical to before: the state file is the
    contract, the event is a courtesy."""
    from agentdata import state as S

    repo = make_project(tmp_path / "repo-a", phase="idle")
    Registry().add(repo, name="a")
    path = os.path.join(repo, ".agent", "state.json")

    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    S.save({"phase": "triaged", "active_ticket": "RDSD-1"}, path)
    assert E.read("a") == [], "an agent outside a fleet wrote events"

    monkeypatch.setenv(registry.AGENT_ENV, "a")
    S.save({"phase": "blocked", "active_ticket": "RDSD-1",
            "open_questions": ["which env?"]}, path)
    kinds = _kinds(E.read("a"))
    assert "phase_changed" in kinds and "question_opened" in kinds, kinds
    assert agentstate.derive(E.read("a"))["state"] == "blocked"


def test_the_supervisor_records_the_launch_itself(fleet_home, tmp_path, monkeypatch):
    """Without a `started` event the stream begins mid-narrative, and "never launched" looks
    exactly like "launched and said nothing"."""
    from agentdata.fleet import supervisor

    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: type("P", (), {"pid": 4242})())

    supervisor.start("a", key="RDSD-1")
    started = E.read("a", kinds=("started",))
    assert len(started) == 1
    assert started[0]["ticket"] == "RDSD-1"
    assert started[0]["data"]["pid"] == 4242
    assert agentstate.derive(E.read("a"))["ticket"] == "RDSD-1"


# ------------------------------------------------------------------------------ log rotation


def test_rotating_the_raw_log_rewinds_the_cursor(fleet_home, tmp_path, monkeypatch):
    """`_rotate` renames events.jsonl between turns. The cursor counts *lines consumed*, so without
    a rewind the next refresh silently skips the opening lines of the new log -- the turn boundary,
    the prompt, and quite possibly a denial."""
    from agentdata.fleet import supervisor

    repo = make_project(tmp_path / "repo-a")
    Registry().add(repo, name="a")
    _write_raw("a", RAW_TURN)
    E.refresh("a", repo)
    assert E.read_cursor("a")["raw_lines"] == len(RAW_TURN)

    monkeypatch.setattr(supervisor, "MAX_LOG_BYTES", 1)
    supervisor._rotate("a")
    assert E.read_cursor("a")["raw_lines"] == 0

    _write_raw("a", RAW_TURN)                       # the new log, from line one
    assert "turn_started" in _kinds(E.refresh("a", repo)), "the first lines of the new log were lost"


# --------------------------------------------------------------------------- the written contract


def test_every_kind_is_documented_with_a_sample_line():
    """A kind added in code and forgotten in the contract is how the next slice learns the shapes by
    hand instead of reading them, which is the whole thing this file exists to prevent."""
    text = open(CONTRACT, encoding="utf-8").read()
    samples = [json.loads(line) for line in text.splitlines()
               if line.startswith('{"schema"')]
    documented = {s["kind"] for s in samples}
    assert documented == set(E.KINDS), (
        f"undocumented: {sorted(set(E.KINDS) - documented)}; "
        f"documented but not emitted: {sorted(documented - set(E.KINDS))}")


def test_every_sample_line_in_the_contract_is_a_real_envelope():
    """A sample that could not be produced is worse than no sample: it is read as the shape."""
    text = open(CONTRACT, encoding="utf-8").read()
    for line in text.splitlines():
        if not line.startswith('{"schema"'):
            continue
        sample = json.loads(line)
        assert sorted(sample) == sorted(E.event("r", "raw")), line
        assert sample["schema"] == E.SCHEMA and isinstance(sample["data"], dict), line


def test_the_documented_states_are_the_ones_the_fold_can_return():
    text = open(CONTRACT, encoding="utf-8").read()
    for state in agentstate.STATES:
        assert f"`{state}`" in text, f"{state} is not in the contract's state table"


def test_the_real_command_blocks_an_agent_in_one_step(fleet_home, tmp_path, monkeypatch, capsys):
    """The whole path, through the argv a skill actually types. No polling anywhere: by the time
    `ad-state` has returned, the dashboard's answer has already changed."""
    from agentdata import cli_state

    repo = make_project(tmp_path / "repo-a", phase="optimizing", ticket="RDSD-1")
    Registry().add(repo, name="a")
    monkeypatch.setenv(registry.AGENT_ENV, "a")

    code = cli_state.main(["--file", os.path.join(repo, ".agent", "state.json"), "set",
                           "phase=blocked", "--question", "Which workspace is UAT?"])
    capsys.readouterr()
    assert code == 0

    got = agentstate.derive(E.read("a"))
    assert got["state"] == "blocked"
    assert got["ticket"] == "RDSD-1"
    assert _kinds(E.read("a")) == ["phase_changed", "question_opened"]


def test_a_broken_fleet_emit_never_fails_the_save(tmp_path, monkeypatch):
    """`ad-state` is the only writer of state.json. A dashboard that misses an event is a nuisance;
    a save that fails because of one is a lost decision."""
    from agentdata import state as S

    def explode(*_a, **_k):
        raise OSError("the fleet directory is on a share that just went away")

    monkeypatch.setenv(registry.AGENT_ENV, "a")
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setattr(E, "append", explode)
    path = str(tmp_path / "state.json")
    S.save({"phase": "triaged"}, path)
    assert json.loads(open(path, encoding="utf-8").read())["phase"] == "triaged"
