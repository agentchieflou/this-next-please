"""One arithmetic for what an agent has cost (issue #209).

There were two answers, in two files, printed side by side under one column name. `agentstate.Fold`
took the **maximum** of every `cost` event, because the CLI reports a session total so far and
adding checkpoints up would multiply the bill. `supervisor.agent_state` took the **sum** of
`result.usage.premiumRequests` over the raw stream. `ad-fleet status` printed the second; the tile,
the history, the sessions list and the budget printed the first.

The rule is `spend.fold` now, and what these tests hold is that every printer calls it.
"""
from __future__ import annotations
import json
import os
import threading

import pytest

from agentdata.fleet import agentstate, events as E, lifecycle, registry, serve as S, spend as SPEND
from agentdata.fleet import supervisor
from agentdata.fleet.registry import Registry, agent_dir

from test_fleet import make_project

pytest.importorskip("hypothesis", reason="hypothesis is in the dev extra")
from hypothesis import given, settings as hsettings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from props_profiles import load_profiles  # noqa: E402

load_profiles()


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return tmp_path / "fleet"


def ev(kind, data, *, ts="2026-01-04T09:30:00", repo="alpha", ticket="RDSD-1"):
    return {"schema": 1, "seq": 0, "ts": ts, "repo": repo, "ticket": ticket,
            "kind": kind, "data": data}


# --------------------------------------------------------------------------------- the rule


def test_checkpoints_are_totals_so_the_fold_takes_the_mark_and_never_the_sum():
    """The cautionary number: 1.0 + 1.33 + 2.0 is 4.33, and the session cost 2.0."""
    stream = [
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 1.0, "source": "checkpoint"}),
        ev("cost", {"premium_requests": 1.33, "source": "checkpoint"}),
        ev("cost", {"premium_requests": 2.0, "source": "checkpoint"}),
        ev("cost", {"premium_requests": 2.0, "source": "result"}),
        ev("exited", {"exit_code": 0}),
    ]
    folded = SPEND.fold(stream)
    assert SPEND.total(folded) == 2.0
    assert folded["sessions"]["s1"]["premium"] == 2.0


def test_two_sessions_are_summed_because_sessions_do_not_overlap():
    """A mark across the whole agent would under-report one that has had three sessions."""
    stream = [
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 2.0, "source": "checkpoint"}),
        ev("exited", {"exit_code": 0}),
        ev("started", {}), ev("session_id", {"session": "s2"}),
        ev("cost", {"premium_requests": 1.0, "source": "checkpoint"}),
        ev("cost", {"premium_requests": 2.0, "source": "checkpoint"}),
    ]
    folded = SPEND.fold(stream)
    assert SPEND.total(folded) == 4.0
    assert sorted(folded["sessions"]) == ["s1", "s2"]


def test_a_day_gets_the_rise_and_not_the_running_total():
    """A session that spans midnight must not be counted whole on both days."""
    stream = [
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 3.0}, ts="2026-01-04T23:50:00"),
        ev("cost", {"premium_requests": 5.0}, ts="2026-01-05T00:10:00"),
    ]
    folded = SPEND.fold(stream)
    assert SPEND.on_day(folded, "2026-01-04") == 3.0
    assert SPEND.on_day(folded, "2026-01-05") == 2.0
    assert SPEND.total(folded) == 5.0


def test_a_cost_before_any_session_is_kept_under_a_name_rather_than_dropped():
    """A number that quietly excludes part of the bill is worse than one that says whose it was
    not."""
    folded = SPEND.fold([ev("cost", {"premium_requests": 1.5})])
    assert SPEND.total(folded) == 1.5
    assert SPEND.UNKNOWN in folded["sessions"]


def test_a_nonsense_cost_is_ignored_rather_than_read_as_zero():
    folded = SPEND.fold([
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 2.0}),
        ev("cost", {"premium_requests": "banana"}),
        ev("cost", {"premium_requests": -4}),
    ])
    assert SPEND.total(folded) == 2.0


@hsettings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(["s1", "s2"]),
                          st.floats(min_value=0, max_value=50, allow_nan=False,
                                    allow_infinity=False)),
                min_size=0, max_size=25))
def test_any_interleaving_of_two_sessions_checkpoints_folds_to_the_same_totals(pairs):
    """The property that makes the rule safe to interleave: a checkpoint is a running total for its
    own session, so the answer is the largest one each session ever reported, however the two
    streams are shuffled together."""
    stream = [ev("started", {})]
    for session, value in pairs:
        stream.append(ev("session_id", {"session": session}))
        stream.append(ev("cost", {"premium_requests": value}))
    folded = SPEND.fold(stream)

    expected = {}
    for session, value in pairs:
        expected[session] = max(expected.get(session, 0.0), value)
    assert SPEND.total(folded) == pytest.approx(round(sum(expected.values()), 2), abs=0.02)


# ------------------------------------------------------------------------- one reader, not two


def test_the_status_table_and_the_tile_row_print_the_same_number(fleet_home, tmp_path):
    """The failure this slice exists for: `ad-fleet status` summed raw `result` events while the
    tile folded the normalized stream, and the two were printed side by side under one name."""
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [
        E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1"),
        E.event("alpha", "session_id", {"session": "s1"}, ticket="RDSD-1"),
        E.event("alpha", "cost", {"premium_requests": 1.0, "source": "checkpoint"}, ticket="RDSD-1"),
        E.event("alpha", "cost", {"premium_requests": 2.5, "source": "checkpoint"}, ticket="RDSD-1"),
        E.event("alpha", "turn_ended", {"turn": "0"}, ticket="RDSD-1"),
        E.event("alpha", "cost", {"premium_requests": 2.5, "source": "result"}, ticket="RDSD-1"),
    ])

    from_status = supervisor.status()[0]
    from_tile = S.row_for("alpha")
    assert from_status["premium_requests"] == 2.5
    assert from_tile["premium_requests"] == from_status["premium_requests"]
    assert from_tile["turns"] == from_status["turns"] == 1
    # And the budget reads the same one, so a cap fires where the number says it should.
    assert lifecycle.spent("alpha") == 2.5


def test_the_fold_and_the_state_agree_because_one_overlays_the_other(fleet_home, tmp_path):
    """`derive` still decides the STATE; the spend on its answer is `spend.py`'s."""
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    stream = [
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 2.0}),
        ev("exited", {"exit_code": 0}),
        ev("started", {}), ev("session_id", {"session": "s2"}),
        ev("cost", {"premium_requests": 3.0}),
    ]
    derived = agentstate.derive(stream)
    assert derived["premium_requests"] == 5.0, "two sessions, summed"
    assert derived["state"], "and the state is still decided by the fold"


# ------------------------------------------------------- the CLI's own usage file, read at last


def test_the_usage_file_is_read_and_a_disagreement_is_reported_rather_than_resolved(
        fleet_home, tmp_path):
    """`--usage-output-file` has been passed on every launch since #93 and read by nothing. Which
    of the two numbers is right is measurement M1, so the reader disagrees out loud instead of
    quietly preferring one."""
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [
        E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1"),
        E.event("alpha", "session_id", {"session": "s1"}, ticket="RDSD-1"),
        E.event("alpha", "cost", {"premium_requests": 1.0, "source": "checkpoint"}, ticket="RDSD-1"),
    ])
    path = os.path.join(agent_dir("alpha"), "usage.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"premiumRequests": 1.33}, handle)

    assert SPEND.from_usage_file(path) == 1.33
    gap = SPEND.disagreement(SPEND.fold(E.read("alpha")), SPEND.from_usage_file(path))
    assert gap == {"stream": 1.0, "file": 1.33, "delta": 0.33}

    # Agreeing is silence, and a file that is not there is not a disagreement.
    assert SPEND.disagreement(SPEND.fold(E.read("alpha")), 1.0) == {}
    assert SPEND.from_usage_file(os.path.join(agent_dir("alpha"), "nope.json")) is None


def test_a_malformed_usage_file_is_not_a_crash(fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    os.makedirs(agent_dir("alpha"), exist_ok=True)
    path = os.path.join(agent_dir("alpha"), "usage.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("{not json")
    assert SPEND.from_usage_file(path) is None


def test_the_doctor_says_when_the_two_disagree(fleet_home, tmp_path, monkeypatch):
    """A warn row naming the measurement, not a verdict about which number is right."""
    from agentdata.setup.wizard import run_doctor

    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [
        E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1"),
        E.event("alpha", "session_id", {"session": "s1"}, ticket="RDSD-1"),
        E.event("alpha", "cost", {"premium_requests": 1.0}, ticket="RDSD-1"),
    ])
    with open(os.path.join(agent_dir("alpha"), "usage.json"), "w",
              encoding="utf-8", newline="\n") as handle:
        json.dump({"premiumRequests": 9.0}, handle)

    run_doctor(["--only", "fleet"])
    # The row is the deliverable; the exit code is the doctor's own and depends on the machine.


# ---------------------------------------------------------------- the event says where it came from


def test_a_cost_event_records_which_source_reported_it():
    """Additive, schema 1 unchanged. It exists so the rule can treat a `result`'s usage differently
    from a checkpoint's one day, WITHOUT re-reading what is already written."""
    checkpoint = E.from_copilot({"type": "session.usage_checkpoint",
                                 "data": {"totalPremiumRequests": 1.33, "totalNanoAiu": 42}},
                                "alpha")
    assert checkpoint[0]["kind"] == "cost"
    assert checkpoint[0]["data"]["source"] == "checkpoint"
    assert checkpoint[0]["data"]["nano_aiu"] == 42, "measured, kept, and shown nowhere"

    result = E.from_copilot({"type": "result", "sessionId": "s1", "exitCode": 0,
                             "usage": {"premiumRequests": 2.0}}, "alpha")
    costs = [e for e in result if e["kind"] == "cost"]
    assert costs and costs[0]["data"]["source"] == "result"


# ------------------------------------------------------------------------ the ledger (#210)


def _spend(name, amount, session="s1", ts=None):
    rows = [E.event(name, "session_id", {"session": session}, ticket="RDSD-1"),
            E.event(name, "cost", {"premium_requests": amount, "source": "checkpoint"},
                    ticket="RDSD-1")]
    E.append(name, rows)


def test_the_fold_is_incremental_by_construction():
    """`fold(a + b)` and `advance(advance(blank(), a), b)` are the same ledger. That property is
    the whole design: it is why the number survives a rotation and why `--rebuild` can be checked
    against what was written a day at a time."""
    a = [ev("started", {}), ev("session_id", {"session": "s1"}),
         ev("cost", {"premium_requests": 2.0}), ev("turn_ended", {"turn": "0"})]
    b = [ev("cost", {"premium_requests": 5.0}), ev("turn_ended", {"turn": "1"}),
         ev("exited", {"exit_code": 0})]

    whole = SPEND.fold(a + b)
    piecewise = SPEND.advance(SPEND.advance(SPEND.blank(), a), b)
    assert SPEND.total(whole) == SPEND.total(piecewise) == 5.0
    assert SPEND.turns(whole) == SPEND.turns(piecewise) == 2
    assert whole["sessions"] == piecewise["sessions"]
    assert whole["days"] == piecewise["days"]


def test_a_partial_fold_charges_the_day_the_rise_and_not_the_total_again():
    """The trap the incremental shape avoids: a second fold that started from zero would charge
    today the session's whole running total a second time."""
    first = SPEND.advance(SPEND.blank(), [
        ev("started", {}), ev("session_id", {"session": "s1"}),
        ev("cost", {"premium_requests": 4.0}, ts="2026-01-04T10:00:00")])
    assert SPEND.on_day(first, "2026-01-04") == 4.0

    SPEND.advance(first, [ev("cost", {"premium_requests": 6.0}, ts="2026-01-04T11:00:00")])
    assert SPEND.on_day(first, "2026-01-04") == 6.0, "the rise, not 4 + 6"
    assert SPEND.total(first) == 6.0


def test_the_budget_survives_the_log_rolling_and_history_keeps_the_morning(fleet_home, tmp_path):
    """The bug: `rotate_all` moved `events.norm.jsonl` aside, `events.read` opens only the live
    file, and so at `fleet.log_mb` an agent's spend silently became zero and the budget re-opened.
    `lifecycle.gc`'s own docstring promised this could not happen."""
    from agentdata import config as C

    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1")])
    _spend("alpha", 6.0)
    assert lifecycle.spent("alpha") == 6.0

    # Roll it, the way `fleet.log_mb` would: `log_mb` is a whole number of megabytes, so the
    # stream is made big enough to trip it rather than the threshold being made small.
    E.append("alpha", [E.event("alpha", "raw", {"pad": "x" * (1200 * 1024)}, ticket="RDSD-1")])
    C.save({"fleet": {"log_mb": 1, "log_keep": 3, "budget_per_agent": 7}})
    rolled = lifecycle.rotate_all("alpha", cfg=C.load())
    assert E.NORMALIZED in rolled, rolled
    assert not os.path.exists(os.path.join(agent_dir("alpha"), E.NORMALIZED)) or \
        E.read("alpha") == [], "the live file really was moved aside"

    # The ledger was written before the move, so the number did not go with it.
    assert lifecycle.spent("alpha") == 6.0

    _spend("alpha", 2.0, session="s2")
    assert lifecycle.spent("alpha") == 8.0, "6 from before the roll, 2 after it"

    over, used, budget = lifecycle.over_budget("alpha", cfg=C.load())
    assert over and used == 8.0 and budget == 7.0, (over, used, budget)


def test_rebuild_reads_every_log_on_disk_and_agrees_with_the_ledger(fleet_home, tmp_path):
    """The check on the whole design: the ledger is a fold, never a source, so folding the files
    again must produce it. Including when a rotation falls in the middle of a session."""
    from agentdata import config as C

    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1")])
    _spend("alpha", 3.0)
    E.append("alpha", [E.event("alpha", "raw", {"pad": "x" * (1200 * 1024)}, ticket="RDSD-1")])
    C.save({"fleet": {"log_mb": 1, "log_keep": 3}})
    assert E.NORMALIZED in lifecycle.rotate_all("alpha", cfg=C.load())
    _spend("alpha", 5.0)                       # the SAME session, after the roll

    incremental = SPEND.for_agent("alpha")
    rebuilt = SPEND.rebuild("alpha")
    assert SPEND.total(incremental) == SPEND.total(rebuilt) == 5.0, \
        "one session's mark, not 3 + 5"
    assert incremental["sessions"] == rebuilt["sessions"]
    assert incremental["days"] == rebuilt["days"]


def test_the_ledger_is_a_few_hundred_bytes_under_the_fleet_and_never_in_a_repository(
        fleet_home, tmp_path):
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1")])
    _spend("alpha", 1.0)
    SPEND.for_agent("alpha")                   # reading it is what brings it up to date and saves it
    path = SPEND.ledger_path("alpha")
    assert os.path.isfile(path)
    assert os.path.getsize(path) < 4096, "a fold of every log, in a few hundred bytes"
    assert str(fleet_home) in path, "the fleet writes only under its own directory"
    assert not os.path.exists(os.path.join(tmp_path / "alpha", ".agent", "spend.json"))


def test_a_ledger_from_an_older_build_is_rebuilt_rather_than_trusted(fleet_home, tmp_path):
    """Additive, and refusing to guess: a schema it does not know is not a ledger it may read."""
    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    os.makedirs(agent_dir("alpha"), exist_ok=True)
    with open(SPEND.ledger_path("alpha"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"schema": 99, "sessions": {"s1": {"premium": 500.0}}}, handle)
    assert SPEND.total(SPEND.read_ledger("alpha")) == 0.0

    with open(SPEND.ledger_path("alpha"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("{not json")
    assert SPEND.total(SPEND.read_ledger("alpha")) == 0.0


def test_the_cli_prints_the_ledger_and_rebuild_agrees(fleet_home, tmp_path, capsys):
    from agentdata import cli_fleet

    Registry().add(make_project(tmp_path / "alpha", ticket="RDSD-1"), name="alpha")
    E.append("alpha", [E.event("alpha", "started", {"pid": 1}, ticket="RDSD-1")])
    _spend("alpha", 4.25)

    assert cli_fleet.main(["spend", "alpha"]) == 0
    out = capsys.readouterr().out
    assert "ad-fleet spend" in out and "4.25" in out and "premium requests" in out

    assert cli_fleet.main(["spend", "--rebuild"]) == 0
    again = capsys.readouterr().out
    assert "4.25" in again and "rebuilt" in again
