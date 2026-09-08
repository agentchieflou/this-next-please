"""Jira intake: the board, ticket-to-repo matching, the start guard rails, and the history strip.

No Jira here. The client is injected, because a test that needed a token would run on one laptop
and skip everywhere else — and what needs proving is the matching, the caching and the refusals,
none of which is about the network.
"""
from __future__ import annotations
import json
import os
import time

import pytest

from agentdata.fleet import board as B, events as E, launch, registry, supervisor
from agentdata.fleet.registry import Registry, RegistryError

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-intake.md")


def issue(key, summary="a thing", status="In Progress", category="indeterminate", kind="Story"):
    return {"key": key, "fields": {"summary": summary,
                                   "status": {"name": status, "statusCategory": {"key": category}},
                                   "issuetype": {"name": kind},
                                   "priority": {"name": "Medium"},
                                   "updated": "2026-01-04T09:31:41.000+0000"}}


class FakeJira:
    """Counts its searches, because "does the cache actually hold" is the point of one test."""

    def __init__(self, issues, fail=None):
        self.issues = issues
        self.fail = fail
        self.searches = []

    def search(self, jql, fields, max_results=5000):
        self.searches.append((jql, tuple(fields)))
        if self.fail:
            raise self.fail
        return self.issues


def a_repo(tmp_path, name, project="RDSD"):
    path = make_project(tmp_path / name, project=project)
    Registry().add(path, name=name)
    return path


# --------------------------------------------------------------------------------- the shape


def test_jiras_nesting_is_flattened_to_what_a_row_needs():
    rows = B.normalize([issue("RDSD-101", "Unused measures", "In Review", "indeterminate")])
    assert rows == [{"key": "RDSD-101", "summary": "Unused measures", "status": "In Review",
                     "category": "indeterminate", "type": "Story", "priority": "Medium",
                     "updated": "2026-01-04T09:31:41", "project": "RDSD"}]


@pytest.mark.parametrize("key,project", [
    ("RDSD-101", "RDSD"), ("DATA_ENG-7", "DATA_ENG"), ("rdsd-2", "RDSD"),
    ("not a key", ""), ("", ""), ("RDSD", ""), ("123-4", ""),
])
def test_the_project_is_read_from_the_key(key, project):
    assert B.project_of(key) == project


# ---------------------------------------------------------------------------------- the cache


def test_the_board_is_cached_so_four_tiles_do_not_hammer_jira(fleet_home):   # noqa: F811
    """A shared Jira instance rate-limits the whole team, not just the fleet. The board is a view
    of a queue, not a live feed."""
    jira = FakeJira([issue("RDSD-101")])
    cfg = {"fleet": {"board_ttl": 120}}
    now = 1_000_000.0

    first = B.board(cfg=cfg, client=jira, now=now)
    assert first["cached"] is False and len(jira.searches) == 1

    for offset in (1, 30, 119):
        again = B.board(cfg=cfg, client=jira, now=now + offset)
        assert again["cached"] is True and again["rows"] == first["rows"]
    assert len(jira.searches) == 1, "the cache did not hold"

    B.board(cfg=cfg, client=jira, now=now + 121)
    assert len(jira.searches) == 2, "the cache never expired"


def test_ten_minutes_of_four_tiles_and_an_open_panel_is_six_searches(fleet_home):  # noqa: F811
    """The acceptance criterion, counted. Five callers asking every five seconds for ten minutes is
    600 calls; with a 120-second TTL it must be six."""
    jira = FakeJira([issue("RDSD-101")])
    cfg = {"fleet": {"board_ttl": 120}}
    start = 2_000_000.0
    for tick in range(0, 600, 5):
        for _caller in range(5):
            B.board(cfg=cfg, client=jira, now=start + tick)
    assert len(jira.searches) <= 6, f"{len(jira.searches)} searches in ten minutes"
    assert len(jira.searches) == 5, "one per TTL window, and one to start"


def test_changing_the_jql_never_serves_the_old_answer(fleet_home):    # noqa: F811
    jira = FakeJira([issue("RDSD-101")])
    B.board(cfg={"fleet": {"jql": "one"}}, client=jira, now=1.0)
    B.board(cfg={"fleet": {"jql": "another"}}, client=jira, now=2.0)
    assert [s[0] for s in jira.searches] == ["one", "another"]


def test_refresh_asks_now(fleet_home):                          # noqa: F811
    jira = FakeJira([issue("RDSD-101")])
    B.board(cfg={}, client=jira, now=1.0)
    B.board(cfg={}, client=jira, now=2.0, force=True)
    assert len(jira.searches) == 2


def test_a_bad_jql_comes_back_as_jiras_own_words(fleet_home):   # noqa: F811
    """The hint has to be Jira's error text: "the query failed" tells an operator nothing about
    which clause they mistyped."""
    jira = FakeJira([], fail=RuntimeError("Field 'assignedto' does not exist or you do not have permission"))
    with pytest.raises(B.BoardError) as e:
        B.board(cfg={}, client=jira)
    assert "assignedto" in e.value.hint


# ------------------------------------------------------------------------ ticket -> repository


def test_one_repo_declaring_the_project_is_the_suggestion(fleet_home, tmp_path):  # noqa: F811
    a_repo(tmp_path, "luna", project="RDSD")
    got = B.suggest("RDSD-101")
    assert got["repo"] == "luna" and got["candidates"] == ["luna"]
    assert "RDSD" in got["why"]


def test_two_repos_declaring_the_same_project_ask_rather_than_guess(fleet_home, tmp_path):  # noqa: F811
    """Guessing would eventually start the wrong checkout, and twenty minutes of an agent editing
    the wrong repository is expensive and quiet."""
    a_repo(tmp_path, "luna", project="RDSD")
    a_repo(tmp_path, "luna-uat", project="RDSD")
    got = B.suggest("RDSD-101")
    assert got["repo"] == "" and sorted(got["candidates"]) == ["luna", "luna-uat"]
    assert got["hint"] == "pick one"


def test_no_repo_for_a_project_names_the_one_line_fix(fleet_home, tmp_path):    # noqa: F811
    a_repo(tmp_path, "luna", project="RDSD")
    got = B.suggest("DATAENG-9")
    assert got["repo"] == "" and got["candidates"] == []
    assert "ad-fleet repo add" in got["hint"] and "DATAENG" in got["hint"]


def test_something_that_is_not_a_key_says_so(fleet_home):       # noqa: F811
    got = B.suggest("please fix the report")
    assert got["repo"] == "" and "not a Jira key" in got["why"]


# ------------------------------------------------------------------------- the start guard rails


def _repo(tmp_path, name="luna", project="RDSD", **kw):
    path = make_project(tmp_path / name, project=project, **kw)
    Registry().add(path, name=name)
    return Registry().get(name)


def test_a_ticket_from_another_project_is_refused_by_name(fleet_home, tmp_path):  # noqa: F811
    repo = _repo(tmp_path, project="RDSD")
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.check_ticket(repo, "DATAENG-9")
    assert "DATAENG" in e.value.msg and "RDSD" in e.value.msg
    assert "--cross-project" in e.value.hint

    supervisor.check_ticket(repo, "DATAENG-9", cross_project=True)   # the override, and only it


def test_a_finished_ticket_is_refused_because_an_agent_would_invent_work(fleet_home, tmp_path):  # noqa: F811
    repo = _repo(tmp_path)
    rows = B.normalize([issue("RDSD-101", "Done already", "Done", "done")])
    with pytest.raises(supervisor.SupervisorError) as e:
        supervisor.check_ticket(repo, "RDSD-101", board_rows=rows)
    assert "already Done" in e.value.msg
    assert supervisor.check_ticket(repo, "RDSD-101", board_rows=rows, force=True) == "Done already"


def test_a_ticket_the_board_has_never_seen_is_allowed(fleet_home, tmp_path):     # noqa: F811
    """Being unable to reach Jira must not stop an operator starting an agent. The board feeds a
    courtesy check, not a gate."""
    repo = _repo(tmp_path)
    assert supervisor.check_ticket(repo, "RDSD-999", board_rows=[]) == ""


def test_the_summary_reaches_the_prompt_and_the_started_event(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    _repo(tmp_path)
    rows = B.normalize([issue("RDSD-101", "Six measures are unused")])
    monkeypatch.setattr(supervisor, "_spawn", lambda *a, **k: type("P", (), {"pid": 77})())

    lock = supervisor.start("luna", key="RDSD-101", board_rows=rows)
    assert lock["summary"] == "Six measures are unused"
    assert "RDSD-101: Six measures are unused" in lock["prompt"]

    started = E.read("luna", kinds=("started",))[0]
    assert started["data"]["summary"] == "Six measures are unused"
    assert started["ticket"] == "RDSD-101"


def test_the_prompt_carries_the_key_and_one_line_and_nothing_else():
    """`jira-triage` does the reading through `ad-pncli`, as its SKILL.md says. A fleet that pasted
    acceptance criteria into the prompt would hand the agent a second, staler copy of the ticket."""
    text = launch.prompt_for("RDSD-101", None, {}, summary="Six measures are unused")
    assert text == "Ticket RDSD-101: Six measures are unused. Invoke skill session-bootstrap, then router."
    assert launch.prompt_for("RDSD-101", None, {}) == \
        "Ticket RDSD-101. Invoke skill session-bootstrap, then router."
    assert launch.prompt_for("RDSD-101", "just do it", {}, summary="x") == "just do it"


def test_a_template_written_before_summary_existed_still_starts_the_agent():
    """Losing the summary is a smaller harm than refusing to launch over a config file someone
    wrote three months ago."""
    old = {"fleet": {"prompt_template": "Work {key} now."}}
    assert launch.prompt_for("RDSD-1", None, old, summary="a thing") == "Work RDSD-1 now."
    typo = {"fleet": {"prompt_template": "Work {ticket} on {key}."}}
    assert launch.prompt_for("RDSD-1", None, typo, summary="a thing") == "Work  on RDSD-1."


def test_a_summary_is_trimmed_before_it_reaches_a_command_line():
    long = "x" * 500
    text = launch.prompt_for("RDSD-1", None, {}, summary=f"line one\nline  two {long}")
    assert "\n" not in text and len(text) < 300


# ------------------------------------------------------------------------------- the history


def test_history_is_read_from_the_events_and_nothing_else(fleet_home, tmp_path):  # noqa: F811
    """It agrees with the tiles by construction rather than by a second bookkeeping file somebody
    has to remember to write."""
    a_repo(tmp_path, "luna")
    E.append("luna", [
        E.event("luna", "started", {"summary": "First job"}, ticket="RDSD-1"),
        E.event("luna", "turn_started", {}, ticket="RDSD-1"),
        E.event("luna", "turn_ended", {}, ticket="RDSD-1"),
        E.event("luna", "cost", {"premium_requests": 1.33}, ticket="RDSD-1"),
        E.event("luna", "phase_changed", {"to": "pr_open"}, ticket="RDSD-1"),
        E.event("luna", "exited", {"exit_code": 0}, ticket="RDSD-1"),
        E.event("luna", "started", {"summary": "Second job"}, ticket="RDSD-2"),
        E.event("luna", "turn_started", {}, ticket="RDSD-2"),
        E.event("luna", "denied", {"message": "no push"}, ticket="RDSD-2"),
        E.event("luna", "turn_ended", {}, ticket="RDSD-2"),
    ])
    runs = B.history(since=10 * 365 * 86400)
    assert [r["ticket"] for r in runs] == ["RDSD-1", "RDSD-2"]
    assert [r["summary"] for r in runs] == ["First job", "Second job"]
    assert runs[0]["state"] == "done" and runs[0]["premium_requests"] == 1.33
    assert runs[1]["state"] == "needs_human", "a run that never exited is still a run"
    assert runs[1]["premium_requests"] == 0, "the second run inherited the first one's cost"


def test_a_resume_is_not_a_new_dispatch(fleet_home, tmp_path):  # noqa: F811
    """`ad-fleet send` emits `started` too. Counting it as a dispatch would double every ticket in
    the report the moment anyone talked to an agent."""
    a_repo(tmp_path, "luna")
    E.append("luna", [E.event("luna", "started", {"summary": "One job"}, ticket="RDSD-1"),
                      E.event("luna", "turn_ended", {}, ticket="RDSD-1"),
                      E.event("luna", "started", {"resumed": True}, ticket="RDSD-1"),
                      E.event("luna", "turn_ended", {}, ticket="RDSD-1")])
    assert len(B.history(since=10 * 365 * 86400)) == 1


def test_history_honours_its_window(fleet_home, tmp_path):      # noqa: F811
    a_repo(tmp_path, "luna")
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400))
    E.append("luna", [E.event("luna", "started", {}, ticket="OLD-1", ts=old),
                      E.event("luna", "exited", {"exit_code": 0}, ticket="OLD-1", ts=old),
                      E.event("luna", "started", {}, ticket="NEW-1"),
                      E.event("luna", "exited", {"exit_code": 0}, ticket="NEW-1")])
    assert [r["ticket"] for r in B.history(since=B.since_seconds("7d"))] == ["NEW-1"]
    assert len(B.history(since=B.since_seconds("60d"))) == 2


@pytest.mark.parametrize("spec,seconds", [
    ("7d", 7 * 86400), ("12h", 12 * 3600), ("90m", 5400), ("1D", 86400),
    ("", 7 * 86400), ("rubbish", 7 * 86400), ("7", 7 * 86400),
])
def test_the_window_spec_falls_back_rather_than_erroring(spec, seconds):
    """This is a report. Refusing to print it over a mistyped flag helps nobody."""
    assert B.since_seconds(spec) == seconds


# ------------------------------------------------------------------------------ the commands


def test_board_prints_the_suggestion_for_every_ticket(fleet_home, tmp_path, capsys, monkeypatch):  # noqa: F811
    from agentdata import cli_fleet

    a_repo(tmp_path, "luna", project="RDSD")
    B.write_cache({"jql": B.DEFAULT_JQL, "fetched_at": time.time(),
                   "rows": B.normalize([issue("RDSD-101", "Unused measures"),
                                        issue("DATAENG-9", "Somebody else's")])})
    assert cli_fleet.main(["board"]) == 0
    out = capsys.readouterr().out
    assert "RDSD-101" in out and "luna" in out
    assert "ad-fleet repo add" in out, "the unmatched ticket must name the fix"

    assert cli_fleet.main(["board", "--project", "RDSD"]) == 0
    assert "DATAENG-9" not in capsys.readouterr().out


def test_history_prints_what_was_dispatched(fleet_home, tmp_path, capsys):     # noqa: F811
    from agentdata import cli_fleet

    a_repo(tmp_path, "luna")
    E.append("luna", [E.event("luna", "started", {"summary": "A job"}, ticket="RDSD-1"),
                      E.event("luna", "exited", {"exit_code": 0}, ticket="RDSD-1")])
    assert cli_fleet.main(["history"]) == 0
    out = capsys.readouterr().out
    assert "RDSD-1" in out and "A job" in out and "runs: 1" in out


def test_starting_a_cross_project_ticket_is_refused_at_the_command_line(fleet_home, tmp_path, capsys):  # noqa: F811
    from agentdata import cli_fleet

    a_repo(tmp_path, "luna", project="RDSD")
    assert cli_fleet.main(["start", "luna", "DATAENG-9"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "--cross-project" in out


# --------------------------------------------------------------------------- the page and doc


STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


def test_a_tile_is_a_drop_target():
    """`preventDefault` on dragover is what makes an element a drop target at all. Without it the
    browser refuses the drop silently, which looks exactly like a broken feature."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert 'addEventListener("dragover"' in js and "preventDefault" in js
    assert 'addEventListener("drop"' in js and 'dataTransfer.getData("text/plain")' in js
    assert 'addEventListener("dragstart"' in js


def test_the_panel_shows_all_three_answers_the_server_can_give():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "s.candidates" in js, "the ambiguous case must offer a pick, not vanish"
    assert "s.hint || s.why" in js, "the unmatched case must show why"


def test_the_contract_documents_the_keys_the_guards_and_the_gestures():
    text = open(CONTRACT, encoding="utf-8").read()
    for key in ("fleet.jql", "fleet.jql_fields", "fleet.board_ttl"):
        assert key in text, f"{key} is not documented"
    for flag in ("--cross-project", "--force", "--refresh"):
        assert flag in text, f"{flag} is not documented"
    assert "ad-fleet board" in text and "ad-fleet history" in text
    assert "jira_project" in text
