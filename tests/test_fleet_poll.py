"""What the poll costs, what it announces, and what it does when the answer will not come.

Five properties carry the slice, and each of them is a way a real desk gets hurt:

* four tiles must cost **one** Jira search per interval, not four -- asserted on the fake's request
  log, because "we only make one call" is a claim that decays the first time someone adds a tile;
* the poll must **stand down** when it has spent its own day's allowance, and say so in those words.
  It caps its own spend and nothing else: `ad-jira changelog` is a separate process with a separate
  `RequestBudget`, so no counter in `poll.py` can hold requests back for it, and the tests below say
  "the poll's own allowance" wherever they used to say "the shared budget";
* the poll must **survive the afternoon**. `RequestBudget.max_seconds` is 900 and `Jira.__init__`
  starts that clock on the first client and never restarts it, so one budget for the life of
  `ad-fleet serve` made every search after the first quarter of an hour raise "request budget
  exhausted (seconds)" and greyed every ticket cell with a message naming the wrong cause
  (#122 defect 3). Two tests step the client's own clock past that ceiling on purpose;
* a failed poll must **grey** its cell -- last value, its age, and the error -- and a later success
  must clear it, because a cell that silently keeps saying `Done` is a lie the operator acts on;
* a change must be announced **once**, including across a restart of `ad-fleet serve`.

The Jira half runs against `tests/fakes/jira.FakeJira` through the real `jira_api` client, so the
request-count assertions are about the client the laptop runs and not about a mock of it.
"""
from __future__ import annotations
import dataclasses
import json
import os

import pytest

from agentdata import textio
from agentdata.connectors.jira_http import JiraBudgetError, RequestBudget
from agentdata.fleet import events as E, poll as P, registry
from agentdata.fleet.registry import Registry

from fakes import jira as FJ

T0 = 1_770_000_000.0            # a plausible wall clock; `last_at == 0` means "never polled"
WS = "11111111-2222-3333-4444-555555555555"
DS = "66666666-7777-8888-9999-000000000000"


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


def project(root, name: str, ticket: str = "", **facts) -> str:
    """A folder shaped like something `ad-setup --project` produced, with facts the tile reads."""
    path = os.path.join(str(root), name)
    os.makedirs(os.path.join(path, ".agent"), exist_ok=True)
    lines = ["# Project", "", "- jira_project: RDSD"]
    lines += [f"- {k}: {v}" for k, v in sorted(facts.items())]
    textio.write_text(os.path.join(path, "AGENTS.md"), "\n".join(lines) + "\n")
    textio.write_json(os.path.join(path, ".agent", "state.json"),
                      {"project": "RDSD", "phase": "querying", "active_ticket": ticket or None})
    return path


def fleet_of(tmp_path, n: int = 4, **facts) -> Registry:
    reg = Registry()
    for i in range(1, n + 1):
        reg.add(project(tmp_path, f"repo-{i}", ticket=f"RDSD-{i}", **facts), name=f"repo-{i}")
    return reg


@dataclasses.dataclass(frozen=True)
class Moving(FJ.Corpus):
    """A corpus whose tickets can be moved between ticks, which the generated one cannot.

    `Corpus` is frozen so that a page is a pure function of `(seed, i, h)`; `moved` keeps that
    property while letting a test say "RDSD-2 is Done now" between two polls.
    """

    moved: tuple = ()

    def status(self, i: int) -> dict:
        return dict(FJ.STATUSES[2] if self.key(i) in self.moved else FJ.STATUSES[1])


def wire(poller: P.Poller, fake: FJ.FakeJira) -> P.Poller:
    """The Jira seam, with the tick's budget handed through so no substitute polls unbounded."""
    poller.jira_client = lambda budget: fake.client(budget=budget)
    return poller


def wire_at(poller: P.Poller, fake: FJ.FakeJira, clock: list) -> P.Poller:
    """The same seam, with the *client's* clock in the test's hands.

    `Jira` reads `time.monotonic` by default and charges the budget's seconds against it, which is a
    different frame from the poller's wall clock. A test about the seconds ceiling has to move the
    frame the ceiling is measured in, so `clock[0]` is what the client sees.
    """
    poller.jira_client = lambda budget: fake.client(budget=budget, clock=lambda: clock[0])
    return poller


def only_jira(poller: P.Poller) -> P.Poller:
    """Silence the three sources a Jira test is not about, without turning them off in config."""
    poller.pr_reader = lambda *a, **k: (_ for _ in ()).throw(AssertionError("pr polled"))
    poller.refresh_reader = lambda *a, **k: (_ for _ in ()).throw(AssertionError("powerbi polled"))
    poller.git_reader = lambda *a, **k: {"branch": "main", "ahead": 0, "behind": 0, "dirty": False}
    return poller


# ---------------------------------------------------------------------------- the Jira budget


def test_four_tiles_cost_one_jira_search_per_interval(fleet_home, tmp_path):
    """The whole reason this is not four `ad-jira get` calls: one shared token, four tiles."""
    reg = fleet_of(tmp_path, 4)
    fake = FJ.FakeJira(issues=6, flavor="cloud")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))

    poller.tick(T0)
    searches = fake.matching("/search/jql")
    assert len(searches) == 1, [str(r) for r in fake.requests]

    jql = searches[0].params["jql"]
    for i in range(1, 5):
        assert f"RDSD-{i}" in jql
    assert jql.count("RDSD-") == 4

    poller.tick(T0 + 10)                        # inside the interval: nothing is due
    assert fake.count("/search/jql") == 1

    poller.tick(T0 + P.DEFAULT_INTERVALS["jira"])
    assert fake.count("/search/jql") == 2
    assert poller.counts()["requests"]["jira"] == 2


def test_the_poll_stands_down_when_its_own_allowance_is_nearly_spent(fleet_home, tmp_path):
    """The poll holds back the last `BUDGET_FLOOR` of what it may spend in a day and says so.

    This is the poll's *own* ceiling, and the docstrings here used to claim more than that: they said
    the budget was shared with a running `ad-jira changelog` so the poll could never starve it. It
    is not and it cannot be -- that command is another process with another `RequestBudget` object
    (#122 defect 5). What is true is what this asserts: the poll stops before it has spent
    everything, in a sentence with the numbers in it, and it resumes when there is room again.
    """
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=6, flavor="cloud")
    budget = RequestBudget(max_requests=60)
    budget.start(T0)
    budget.requests = 20                        # 40 left, under BUDGET_FLOOR
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0, budget=budget), fake))

    assert poller.tick(T0) == []
    assert fake.requests == [], [str(r) for r in fake.requests]
    cell = poller.state_for("repo-1")["ticket"]
    assert cell.grey and cell.error.startswith("standing down:")
    assert "40 of 60" in cell.error                # the numbers, not "the budget is short"
    assert "own allowance" in cell.error           # its own ceiling; it cannot see another process
    assert poller.counts()["stood_down"]["jira"] == 2
    assert poller.counts()["requests"]["jira"] == 0

    budget.requests = 0                          # room again; the poll resumes
    poller.tick(T0 + P.DEFAULT_INTERVALS["jira"])
    assert fake.count("/search/jql") == 1
    assert poller.state_for("repo-1")["ticket"].error == ""


def test_a_dashboard_left_open_all_afternoon_is_still_polling(fleet_home, tmp_path):
    """#122 defect 3, in the shape the reviewer reproduced it: `ad-fleet serve` at 09:00, a stale
    ticket status from 09:15 onwards, and a fleet doctor blaming the poll interval.

    One `RequestBudget` for the life of the process is one `max_seconds` for the life of the
    process. `Jira.__init__` starts that clock on the first client it is handed and deliberately
    does not restart it, so the second tick past 900 s raised `JiraBudgetError("seconds")`, every
    tile greyed with "standing down: request budget exhausted (seconds)", `stood_down` climbed on
    every tick after it, and only restarting the server brought the ticket cells back.

    The clock moved here is the *client's* -- the frame the seconds ceiling is measured in.
    """
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=6, flavor="cloud")
    clock = [1_000.0]
    poller = only_jira(wire_at(P.Poller(reg, cfg={}, now=lambda: T0), fake, clock))

    poller.tick(T0)
    assert fake.count("/search/jql") == 1

    clock[0] += 4 * RequestBudget.max_seconds       # the afternoon; four times over the old ceiling
    poller.tick(T0 + 3_600)
    assert fake.count("/search/jql") == 2, "the poll died with a ceiling meant to bound one command"

    cell = poller.state_for("repo-1")["ticket"]
    assert not cell.grey and cell.error == "" and cell.value["status"]
    assert poller.counts()["stood_down"]["jira"] == 0

    clock[0] += 4 * RequestBudget.max_seconds       # and it is not one extra tick, it is every tick
    poller.tick(T0 + 7_200)
    assert fake.count("/search/jql") == 3
    assert poller.counts()["requests"]["jira"] == 3


def test_a_tick_that_outruns_its_own_ceiling_is_not_the_operators_budget(fleet_home, tmp_path):
    """Three ways a budget runs out mid-search, and only one of them is a stand-down.

    The cell text is what the operator acts on and `ad-doctor` reads the counter beside it: a
    `stood_down` tick makes the `fleet / token budget` row warn "the shared request budget nearly
    spent" and advise raising `fleet.poll.jira.interval`. Filing a slow Jira or a failing Jira under
    that sends the operator to change a setting that cannot help -- so seconds and retries grey the
    cell as the errors they are, and only a spent allowance stands down.
    """
    reg = fleet_of(tmp_path, 2)

    def raising(limit: str, requests_made: int = 1, elapsed: float = 300.0):
        def client(budget):
            class Stub:
                def search(self, *a, **k):
                    raise JiraBudgetError(limit, requests_made, elapsed, "/rest/api/3/search/jql")
            return Stub()
        return client

    poller = only_jira(P.Poller(reg, cfg={}, now=lambda: T0))

    poller.jira_client = raising("seconds", requests_made=1, elapsed=241.0)
    poller.tick(T0)
    cell = poller.state_for("repo-1")["ticket"]
    assert cell.grey and not cell.error.startswith("standing down")
    assert f"{int(P.TICK_SECONDS)}s" in cell.error and "Jira is slow" in cell.error
    assert poller.counts()["errors"]["jira"] == 2
    assert poller.counts()["stood_down"]["jira"] == 0

    poller.jira_client = raising("retries", requests_made=6, elapsed=90.0)
    poller.tick(T0 + 60)
    cell = poller.state_for("repo-1")["ticket"]
    assert not cell.error.startswith("standing down") and "status page" in cell.error
    assert poller.counts()["stood_down"]["jira"] == 0
    assert poller.counts()["errors"]["jira"] == 4

    spent = RequestBudget(max_requests=100)
    spent.start(T0)
    # Its own counter file: the poller above persisted this day's errors, and a second `Poller` on
    # the same fleet dir would load them and make the numbers below about the wrong tick.
    poller = only_jira(P.Poller(reg, cfg={}, now=lambda: T0, budget=spent,
                                state_path=str(tmp_path / "second-poll.json")))
    poller.jira_client = raising("requests", requests_made=100, elapsed=30.0)
    poller.tick(T0)
    cell = poller.state_for("repo-1")["ticket"]
    assert cell.error.startswith("standing down:") and "0 of 100" in cell.error
    assert poller.counts()["stood_down"]["jira"] == 2
    assert poller.counts()["errors"]["jira"] == 0


def test_the_allowance_is_a_days_allowance_not_a_process_lifetime_one(fleet_home, tmp_path):
    """`max_requests` bounds one command too, and the poll is not one command.

    At a search a minute a dashboard reaches `RequestBudget`'s 2,000 in a day and a half, and before
    this rolled over the poll stood down from then on -- for ever, since nothing but a restart of
    `ad-fleet serve` ever reset the count. The counters the operator reads in `ad-fleet status
    --polls` are per day; the allowance they measure is now the same day.
    """
    reg = fleet_of(tmp_path, 1)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    budget = RequestBudget(max_requests=60)
    budget.start(T0)
    budget.requests = 58                            # today is spent
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0, budget=budget), fake))

    assert poller.tick(T0) == []
    assert fake.requests == []
    assert poller.counts()["stood_down"]["jira"] == 1

    tomorrow = T0 + 86_400
    poller.now = lambda: tomorrow
    poller.tick(tomorrow)
    assert fake.count("/search/jql") == 1
    assert poller.state_for("repo-1")["ticket"].error == ""
    counts = poller.counts()
    assert counts["requests"]["jira"] == 1 and counts["stood_down"]["jira"] == 0


def test_the_tick_budget_is_the_tick_s_own_and_the_allowance_is_charged_what_it_spent(
        fleet_home, tmp_path):
    """The seam's contract, so the next person to touch it keeps both halves.

    A budget per tick is what stops a run's ceilings from bounding the process; charging the day's
    allowance what the tick spent is what stops "a budget per tick" from meaning no budget at all.
    """
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    handed = []
    poller = only_jira(P.Poller(reg, cfg={}, now=lambda: T0))
    poller.jira_client = lambda budget: handed.append(budget) or fake.client(budget=budget)

    poller.tick(T0)
    poller.tick(T0 + 60)

    assert len(handed) == 2
    assert handed[0] is not handed[1] and all(b is not poller.budget for b in handed)
    assert [b.max_seconds for b in handed] == [P.TICK_SECONDS, P.TICK_SECONDS]
    assert handed[0].max_requests == RequestBudget.max_requests      # the whole day is still there
    assert handed[1].max_requests == RequestBudget.max_requests - 1  # minus what tick one spent
    assert poller.budget.requests == 2
    assert poller.counts()["requests"]["jira"] == 2


# ------------------------------------------------------------------------ grey, and recovery


def test_a_failing_poll_greys_the_cell_and_a_later_one_clears_it(fleet_home, tmp_path):
    """Value plus age, the error in the cell, never a wrong value."""
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=6, flavor="cloud")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))

    poller.tick(T0)
    good = poller.state_for("repo-1")["ticket"]
    assert good.value["status"] and not good.grey

    fake.faults = [FJ.Fault.of(("search", "every", 500))]
    poller.tick(T0 + 60)
    grey = poller.state_for("repo-1")["ticket"]
    assert grey.grey and "500" in grey.error
    assert grey.value == good.value              # the last good answer, not a blank and not a guess
    assert grey.last_ok == T0                    # ...and its age keeps growing
    poller.now = lambda: T0 + 120
    assert poller.state_for("repo-1")["ticket"].age_s == pytest.approx(120.0)
    assert poller.counts()["errors"]["jira"] == 2

    fake.faults = []
    poller.now = lambda: T0 + 121
    poller.tick(T0 + 121)
    clear = poller.state_for("repo-1")["ticket"]
    assert not clear.grey and clear.error == "" and clear.age_s == pytest.approx(0.0)


def test_a_ticket_jira_does_not_return_greys_rather_than_blanking(fleet_home, tmp_path):
    """A key that was renamed, deleted, or moved to a project this token cannot see. The tile must
    say so; silently dropping the cell reads as "no ticket", which is a different thing."""
    reg = Registry()
    reg.add(project(tmp_path, "repo-x", ticket="NOPE-9"), name="repo-x")
    fake = FJ.FakeJira(issues=3, flavor="cloud")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))

    poller.tick(T0)
    cell = poller.state_for("repo-x")["ticket"]
    assert cell.grey and "NOPE-9" in cell.error


# ------------------------------------------------------------------------------- the events


def test_a_ticket_that_moves_is_announced_once(fleet_home, tmp_path):
    """One event per real change, on #94's contract, and none for the same change polled again."""
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    fake.corpus = Moving(issues=4, project="RDSD")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))

    assert poller.tick(T0) == []                 # the first sighting is the baseline, not news

    fake.corpus = Moving(issues=4, project="RDSD", moved=("RDSD-2",))
    produced = poller.tick(T0 + 60)
    assert [e["kind"] for e in produced] == [P.TICKET_CHANGED]
    assert produced[0]["repo"] == "repo-2"
    assert produced[0]["ticket"] == "RDSD-2"
    assert produced[0]["data"]["status"] == "Done"
    assert produced[0]["schema"] == E.SCHEMA

    assert poller.tick(T0 + 120) == []           # the same change again is not a second change
    assert [e["kind"] for e in E.read("repo-2")] == [P.TICKET_CHANGED]


def test_a_restarted_dashboard_does_not_re_announce(fleet_home, tmp_path):
    """`ad-fleet serve` restarts. Re-baselining would lose a change; re-announcing would toast one
    the operator already dismissed. What was announced is on disk, so neither happens."""
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    fake.corpus = Moving(issues=4, project="RDSD")
    wire(only_jira(P.Poller(reg, cfg={}, now=lambda: T0)), fake).tick(T0)

    fake.corpus = Moving(issues=4, project="RDSD", moved=("RDSD-2",))
    again = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0 + 60), fake))
    assert [e["kind"] for e in again.tick(T0 + 60)] == [P.TICKET_CHANGED]

    third = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0 + 120), fake))
    assert third.tick(T0 + 120) == []


def test_a_held_event_stream_is_retried_rather_than_lost(fleet_home, tmp_path, monkeypatch):
    """`ad-state` holds the repo's write lock from inside the agent while the supervisor polls from
    outside. Remembering the fingerprint before the append succeeded would turn that ordinary
    contention into a change nobody is ever told about."""
    reg = fleet_of(tmp_path, 1)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    fake.corpus = Moving(issues=4, project="RDSD")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))
    poller.tick(T0)

    fake.corpus = Moving(issues=4, project="RDSD", moved=("RDSD-1",))
    monkeypatch.setattr(E, "append", lambda *a, **k: (_ for _ in ()).throw(E.Busy("repo-1")))
    assert poller.tick(T0 + 60) == []

    monkeypatch.undo()
    assert [e["kind"] for e in poller.tick(T0 + 120)] == [P.TICKET_CHANGED]


def test_a_merged_pr_is_announced_once_and_an_open_one_is_not(fleet_home, tmp_path):
    reg = Registry()
    path = project(tmp_path, "repo-p", ticket="RDSD-1")
    textio.write_json(os.path.join(path, ".agent", "state.json"),
                      {"project": "RDSD", "phase": "pr_open", "active_ticket": "RDSD-1",
                       "pr_url": "https://bitbucket.org/acme/rdsd/pull-requests/42"})
    reg.add(path, name="repo-p")

    answers = [{"state": "OPEN", "id": 42}, {"state": "OPEN", "id": 42}, {"state": "MERGED", "id": 42}]
    poller = P.Poller(reg, cfg={"fleet": {"poll": {"jira": False, "powerbi": False, "git": False}}},
                      now=lambda: T0)
    poller.pr_reader = lambda *a, **k: answers.pop(0)

    assert poller.tick(T0) == []
    assert poller.state_for("repo-p")["pr"].value["text"] == "OPEN"
    assert poller.tick(T0 + 120) == []           # still open: a cell update, not an event

    produced = poller.tick(T0 + 240)
    assert [e["kind"] for e in produced] == [P.PR_MERGED]
    assert produced[0]["data"]["url"].endswith("/pull-requests/42")
    assert poller.state_for("repo-p")["pr"].value["state"] == "MERGED"


def test_a_finished_refresh_is_announced_and_a_running_one_is_not(fleet_home, tmp_path):
    """"The refresh you were waiting on finished" is the toast that removes the centre-monitor tab.
    "The refresh you were waiting on is still going" is the toast that gets notifications muted."""
    reg = Registry()
    reg.add(project(tmp_path, "repo-r", ticket="RDSD-1", ws_id=WS, ds_id=DS), name="repo-r")
    answers = [{"status": "InProgress", "startTime": "2026-09-08T02:00:00Z"},
               {"status": "InProgress", "startTime": "2026-09-08T02:00:00Z"},
               {"status": "Completed", "startTime": "2026-09-08T02:00:00Z",
                "endTime": "2026-09-08T02:31:07Z", "refreshType": "Full"}]
    poller = P.Poller(reg, cfg={"fleet": {"poll": {"jira": False, "pr": False, "git": False}}},
                      now=lambda: T0)
    poller.refresh_reader = lambda *a, **k: answers.pop(0)

    assert poller.tick(T0) == []
    assert poller.tick(T0 + 300) == []
    produced = poller.tick(T0 + 600)
    assert [e["kind"] for e in produced] == [P.REFRESH_FINISHED]
    assert produced[0]["data"]["status"] == "Completed"
    assert produced[0]["data"]["workspace"] == WS
    assert poller.state_for("repo-r")["refresh"].value["text"] == "Completed"


def test_a_repo_with_no_dataset_and_no_pr_has_empty_cells_not_grey_ones(fleet_home, tmp_path):
    """A repository with no Power BI model is not a repository whose Power BI is broken."""
    reg = fleet_of(tmp_path, 1)
    poller = P.Poller(reg, cfg={"fleet": {"poll": {"jira": False, "git": False}}}, now=lambda: T0)
    poller.pr_reader = lambda *a, **k: (_ for _ in ()).throw(AssertionError("polled with no PR"))
    poller.refresh_reader = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no dataset"))

    poller.tick(T0)
    for cell in ("pr", "refresh"):
        assert not poller.state_for("repo-1")[cell].grey
        assert poller.state_for("repo-1")[cell].value == {"text": ""}


def test_git_fills_its_cell_and_announces_nothing(fleet_home, tmp_path):
    """#94's contract has no kind for a dirty tree, and a toast per saved file is the notification
    an operator turns off first."""
    reg = fleet_of(tmp_path, 1)
    poller = P.Poller(reg, cfg={"fleet": {"poll": {"jira": False, "pr": False, "powerbi": False}}},
                      now=lambda: T0)
    poller.git_reader = lambda repo: {"branch": "feature/velocity-gate", "ahead": 2, "behind": 1,
                                      "dirty": True}
    assert poller.tick(T0) == []
    assert poller.state_for("repo-1")["git"].value["text"] == "feature/velocity-gate +2 -1 dirty"

    poller.git_reader = lambda repo: {"branch": "feature/velocity-gate", "ahead": 0, "behind": 0,
                                      "dirty": False}
    assert poller.tick(T0 + 30) == []
    assert poller.state_for("repo-1")["git"].value["text"] == "feature/velocity-gate"


# ------------------------------------------------------------------------------ configuration


def test_every_source_can_be_turned_off_on_its_own(fleet_home, tmp_path):
    """`fleet.poll.<source>: false` is the shortest spelling, and it is the one an operator reaches
    for when one system is down and its cell is nothing but noise."""
    reg = fleet_of(tmp_path, 1, ws_id=WS, ds_id=DS)
    for source in P.SOURCES:
        cfg = {"fleet": {"poll": {source: False}}}
        assert P.settings(cfg)[source]["on"] is False
        assert all(P.settings(cfg)[other]["on"] for other in P.SOURCES if other != source)

        poller = P.Poller(reg, cfg=cfg, now=lambda: T0)
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"{source} polled"))  # noqa: E731
        setattr(poller, {"jira": "jira_client", "pr": "pr_reader", "powerbi": "refresh_reader",
                         "git": "git_reader"}[source], boom)
        for other, attr in (("pr", "pr_reader"), ("powerbi", "refresh_reader"),
                            ("git", "git_reader")):
            if other != source:
                setattr(poller, attr, lambda *a, **k: {})
        if source != "jira":
            poller.jira_client = lambda budget: FJ.FakeJira(issues=4).client(budget=budget)
        poller.tick(T0)


def test_the_whole_poll_can_be_turned_off(fleet_home, tmp_path):
    cfg = {"fleet": {"poll": {"enabled": False}}}
    assert all(not P.settings(cfg)[s]["on"] for s in P.SOURCES)

    reg = fleet_of(tmp_path, 2)
    poller = P.Poller(reg, cfg=cfg, now=lambda: T0)
    poller.jira_client = lambda budget: (_ for _ in ()).throw(AssertionError("polled"))
    poller.pr_reader = poller.refresh_reader = poller.git_reader = poller.jira_client
    assert poller.tick(T0) == []


def test_intervals_default_and_can_be_overridden(fleet_home, tmp_path):
    assert P.DEFAULT_INTERVALS == {"jira": 60, "pr": 120, "powerbi": 300, "git": 30}
    assert all(P.settings({})[s]["interval"] == P.DEFAULT_INTERVALS[s] for s in P.SOURCES)

    cfg = {"fleet": {"poll": {"jira": {"interval": 600}, "git": {"interval": "nonsense"}}}}
    assert P.settings(cfg)["jira"]["interval"] == 600
    assert P.settings(cfg)["jira"]["on"] is True
    assert P.settings(cfg)["git"]["interval"] == P.DEFAULT_INTERVALS["git"]


# ------------------------------------------------------------------------- honesty about cost


def test_counts_are_per_source_and_survive_a_restart(fleet_home, tmp_path):
    """`ad-fleet status --polls` prints what the day cost. A dashboard restarted at lunchtime
    reporting zero would understate the morning by a few hundred requests."""
    reg = fleet_of(tmp_path, 2)
    fake = FJ.FakeJira(issues=4, flavor="cloud")
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))
    poller.tick(T0)
    poller.tick(T0 + 60)

    counts = poller.counts()
    assert counts["requests"]["jira"] == 2
    assert set(counts["requests"]) == set(P.SOURCES)
    assert counts["day"] and counts["total"] == 2

    restarted = P.Poller(reg, cfg={}, now=lambda: T0 + 120)
    assert restarted.counts()["requests"]["jira"] == 2


def test_the_poll_never_writes_to_a_repository(fleet_home, tmp_path):
    """`ad-state` stays the only writer of `.agent/state.json`. The fleet asks; it never writes."""
    reg = fleet_of(tmp_path, 2)
    files = {r.name: r.state_file for r in reg.sorted()}
    before = {n: (open(p, "rb").read(), os.stat(p).st_mtime_ns) for n, p in files.items()}

    fake = FJ.FakeJira(issues=4, flavor="cloud")
    fake.corpus = Moving(issues=4, project="RDSD", moved=("RDSD-1", "RDSD-2"))
    poller = only_jira(wire(P.Poller(reg, cfg={}, now=lambda: T0), fake))
    poller.tick(T0)
    poller.tick(T0 + 60)

    assert {n: (open(p, "rb").read(), os.stat(p).st_mtime_ns) for n, p in files.items()} == before
    written = json.loads(textio.read_text(poller.state_path))
    assert written["version"] == P.STATE_VERSION
    # Both spellings through `norm_path`: the poller stores its path canonicalised and `tmp_path`
    # hands out backslashes on Windows, so a raw `startswith` compared two spellings of one path.
    assert textio.norm_path(str(poller.state_path)).startswith(textio.norm_path(str(fleet_home)))


def test_state_for_names_the_four_cells(fleet_home, tmp_path):
    reg = fleet_of(tmp_path, 1)
    poller = P.Poller(reg, cfg={"fleet": {"poll": {"enabled": False}}}, now=lambda: T0)
    cells = poller.state_for("repo-1")
    assert sorted(cells) == ["git", "pr", "refresh", "ticket"]
    assert [cells[c].source for c in ("ticket", "pr", "refresh", "git")] == list(P.SOURCES)
    assert all(c.age_s == 0.0 and not c.grey for c in cells.values())


# ------------------------------------------------------------------------- the default readers


def test_read_git_parses_porcelain_v2_rather_than_the_localised_prose(monkeypatch, tmp_path):
    """A laptop set to French reports "Votre branche est en avance de 2 commits" where a parser of
    the prose wanted "ahead"."""
    from agentdata import proc

    out = ("# branch.oid 1a2b3c\n"
           "# branch.head feature/velocity-gate\n"
           "# branch.upstream origin/feature/velocity-gate\n"
           "# branch.ab +2 -1\n"
           "1 .M N... 100644 100644 100644 aaa bbb agentdata/fleet/poll.py\n"
           "? notes.txt\n")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["cwd"] = argv, kw.get("cwd")
        return 0, out, "", 0.01

    monkeypatch.setattr(proc, "run", fake_run)
    got = P.read_git(type("R", (), {"path": str(tmp_path)})())
    assert got == {"branch": "feature/velocity-gate", "ahead": 2, "behind": 1, "dirty": True}
    assert "--no-optional-locks" in seen["argv"] and "--porcelain=v2" in seen["argv"]
    assert seen["cwd"] == str(tmp_path)


def test_read_git_reports_the_failure_rather_than_a_clean_tree(monkeypatch, tmp_path):
    from agentdata import proc

    monkeypatch.setattr(proc, "run", lambda argv, **kw: (128, "", "fatal: not a git repository", 0.0))
    with pytest.raises(OSError) as e:
        P.read_git(type("R", (), {"path": str(tmp_path)})())
    assert "not a git repository" in str(e.value)


def test_read_pr_refuses_a_url_it_cannot_read_an_id_from():
    """A guessed PR id is a poll that reports somebody else's pull request as this project's."""
    with pytest.raises(ValueError) as e:
        P.read_pr(None, {"pr_url": "https://bitbucket.org/acme/rdsd"})
    assert "pull-requests" in str(e.value)


def test_the_pr_read_is_a_read_verb():
    """A poll that could reach a write verb is a poll that could merge a pull request on a timer."""
    from agentdata.connectors import pncli

    assert pncli.is_write(["bitbucket", "get-pr", "--id", "42"]) is False
