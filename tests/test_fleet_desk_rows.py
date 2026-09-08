"""The four project kinds on #94's contract, and the desk rows the doctor grew for them.

Two halves of one slice. The kinds are what the fleet learns about the *project* -- a ticket that
moved, a refresh that finished, a PR somebody merged, a file carried in from Downloads -- and the
rows are what the doctor says when the machinery behind them is not ready.

The thing both halves are really about is restraint. A refresh finishing is the toast that removes
a tab from the centre monitor; the same refresh, re-observed after `ad-fleet serve` restarts, is
nothing at all. And a doctor row that asks a question no answer can fix is how `--patch` stops
being surgical, so every row here is asserted to name the settings behind it or to name none.
"""
from __future__ import annotations
import json
import os
import time

import pytest

from agentdata import config as C
from agentdata.fleet import agentstate, catalogue as CAT, events as E, links as L, notify as N
from agentdata.fleet import poll as P
from agentdata.fleet.registry import Registry
from agentdata.setup import wizard as W
from agentdata.setup.steps.fleet import CATALOGUE_STALE_S, POLLS_PER_HOUR_WARN, FleetStep

from test_fleet import make_project
from test_fleet_events import fleet_home                       # noqa: F401 - a fixture, used by name

TICKET = {"key": "RDSD-101", "status": "In Review", "assignee": "Luna",
          "updated": "2026-01-04T09:00:00"}
REFRESH = {"status": "Completed", "end": "2026-01-04T06:12:00", "type": "Scheduled",
           "workspace": "w", "dataset": "d"}
MERGED = {"url": "https://bitbucket.org/acme/luna/pull-requests/42", "state": "MERGED", "id": "42"}
ATTACHED = {"file": "C:/work/luna/.agent/in/RDSD-101/velocity.csv", "name": "velocity.csv",
            "dir": ".agent/in/RDSD-101", "source": "C:/Users/luna/Downloads/velocity.csv",
            "size": 2048, "project": "luna", "attached": True, "recorded": True, "why": ""}

NEW_KINDS = {"project.ticket_changed": TICKET, "project.refresh_finished": REFRESH,
             "project.pr_merged": MERGED, "inbox.attached": ATTACHED}


def a_repo(tmp_path, name="luna", **kw):
    path = make_project(tmp_path / name, **kw)
    return Registry().add(path, name=name)


# ------------------------------------------------------------------- the kinds on the contract


def test_every_new_kind_round_trips_through_append_and_read(fleet_home):        # noqa: F811
    """Additive only: a kind is written, numbered and read back with its payload intact."""
    stream = [E.event("luna", kind, data, ticket="RDSD-101") for kind, data in NEW_KINDS.items()]
    assert E.append("luna", stream) == len(NEW_KINDS)

    back = E.read("luna")
    assert [e["kind"] for e in back] == list(NEW_KINDS)
    assert [e["seq"] for e in back] == [1, 2, 3, 4], "seq must stay dense across the new kinds"
    assert back[0]["data"] == TICKET and back[-1]["data"] == ATTACHED
    assert all(k in E.KINDS for k in NEW_KINDS), "a kind that is written must be in the catalogue"

    # ...and reading a slice by kind, which is how a tile asks for just its own cells.
    assert [e["kind"] for e in E.read("luna", kinds=tuple(P.KINDS))] == list(P.KINDS)


def test_the_kinds_the_poller_and_the_inbox_emit_are_the_kinds_in_the_contract():
    """Two modules name these strings for their own callers. A third spelling is a silent drop."""
    from agentdata.fleet import inbox as IN

    assert set(P.KINDS) | {IN.ATTACHED} == set(NEW_KINDS) <= set(E.KINDS)


def test_a_credential_in_a_new_kind_is_redacted_like_every_other(fleet_home):   # noqa: F811
    """The rule is the stream's, not the writer's: `redact` runs over every payload."""
    E.append("luna", [E.event("luna", "inbox.attached",
                              dict(ATTACHED, token="ghp_0123456789abcdefghij"))])
    written = E.read("luna")[0]["data"]
    assert written["token"] == E.REDACTED and "ghp_" not in json.dumps(written)


# ----------------------------------------------------------------- and how they reach a person


def test_each_new_kind_produces_exactly_one_notice_on_the_notifier_s_own_shape():
    """`notify.suppress` and `notify.deliver` take this dict unchanged, so it has to *be* that
    dict. A near-miss here is a KeyError in the drawer three slices later."""
    shape = sorted(N.notification("luna", "done", "phase is pr_open", ticket="RDSD-101"))
    for kind, data in NEW_KINDS.items():
        item = E.notice(E.event("luna", kind, data, ticket="RDSD-101", seq=7))
        assert item is not None, kind
        assert sorted(item) == shape, kind
        assert item["severity"] in N.SEVERITIES and item["repo"] == "luna"
        assert item["title"].startswith("luna · RDSD-101 — ") and item["body"]
        assert item["seq"] == 7


def test_the_stream_yields_one_notice_per_change_and_nothing_before_the_cursor():
    stream = [dict(E.event("luna", kind, data), seq=i)
              for i, (kind, data) in enumerate(NEW_KINDS.items(), 1)]
    assert len(E.notices(stream)) == 4
    assert [i["state"] for i in E.notices(stream, since=2)] == ["project.pr_merged",
                                                               "inbox.attached"]
    assert E.notices(stream, since=99) == []


def test_the_same_refresh_seen_twice_is_one_toast_and_the_next_one_is_news():
    """The toast that removes the centre-monitor tab, and the double-notify that would train the
    operator to ignore it. Dedupe is #97's cooldown, keyed on what actually changed."""
    first = E.notice(E.event("luna", "project.refresh_finished", REFRESH))
    again = E.notice(E.event("luna", "project.refresh_finished", REFRESH))
    tomorrow = E.notice(E.event("luna", "project.refresh_finished",
                                dict(REFRESH, end="2026-01-05T06:11:00")))
    assert first["key"] == again["key"] != tomorrow["key"]

    state, now = {}, time.time()
    assert N.suppress([first], state, cooldown=300, now=now) == [first]
    assert N.suppress([again], state, cooldown=300, now=now + 60) == []
    assert N.suppress([tomorrow], state, cooldown=300, now=now + 60) == [tomorrow]


def test_a_refresh_that_failed_is_not_the_same_news_as_one_that_worked():
    """Same kind, different severity: `notify` chimes for anything that is not `info`, and an
    operator told "the refresh finished" who finds a failure in the morning stops reading."""
    ok = E.notice(E.event("luna", "project.refresh_finished", REFRESH))
    bad = E.notice(E.event("luna", "project.refresh_finished", dict(REFRESH, status="Failed")))
    assert ok["severity"] == "info" and bad["severity"] == "alert"
    assert "failed" in bad["title"] and "Failed" in bad["body"]


def test_attaching_the_same_file_twice_announces_nothing_the_second_time():
    """`inbox.attach` returns the event either way, because the click is in the history; an
    operator who clicked twice meant it once and does not need telling what they just did."""
    assert E.notice(E.event("luna", "inbox.attached", ATTACHED)) is not None
    assert E.notice(E.event("luna", "inbox.attached",
                            dict(ATTACHED, attached=False, recorded=False,
                                 why="already attached"))) is None


def test_quiet_hours_hold_the_new_toasts_back_and_still_record_the_badge(fleet_home):  # noqa: F811
    """Unchanged from #97, which is the point: the new kinds go through the existing rules."""
    item = E.notice(E.event("luna", "project.pr_merged", MERGED))
    night = time.strptime("2026-01-04T23:30:00", "%Y-%m-%dT%H:%M:%S")
    out = N.deliver([item], cfg={"fleet": {"notify": {"quiet_hours": "18:00-08:00"}}}, when=night)
    assert out[0]["quiet"] is True and out[0]["toasted"] is False
    assert [i["state"] for i in N.read_log()] == ["project.pr_merged"]


def test_a_project_event_never_repaints_the_agent_s_own_tile():
    """The one question the fleet exists to answer is whether the *agent* needs a human. A Power
    BI refresh is not the agent, so the fold ignores it -- and `notify.scan`, which folds the same
    stream, must not raise a second notification for what `notices` already carried."""
    working = [dict(E.event("luna", kind, {}), seq=i) for i, kind in
               enumerate(("started", "turn_started", "turn_ended", "exited"), 1)]
    quiet = agentstate.derive(working)
    noisy = working + [dict(E.event("luna", kind, data), seq=5 + i)
                       for i, (kind, data) in enumerate(NEW_KINDS.items())]

    assert agentstate.derive(noisy)["state"] == quiet["state"] == "idle"
    assert N.scan("luna", noisy) == N.scan("luna", working) == []


# ------------------------------------------------------------------------------- the doctor rows


def _rows(cfg=None, **found):
    """The rows `check` produces for one machine, by name. `found` is what `detect` gathered."""
    ctx = W.Context(cfg=cfg if cfg is not None else {}, det=W.Detectors(), ask=W.Prompter(),
                    interactive=False)
    base = {"enabled": True, "repos": [], "toast": "off", "settings": N.settings({}),
            "version": "1.0.81", "why": "", "login": "ok", "port": 8765, "port_free": True,
            "ours": False}
    base.update(found)
    FleetStep().check(ctx, base)
    return {c.name: c for c in ctx.checks}


def test_the_parent_folder_row_passes_when_the_checkouts_are_there(fleet_home, tmp_path):  # noqa: F811
    repos = [a_repo(tmp_path, "luna"), a_repo(tmp_path, "velocity")]
    row = _rows(repos=repos)["parent folder"]
    assert row.status == "ok" and "2 under" in row.detail and str(tmp_path.name) in row.detail


def test_a_disconnected_parent_folder_is_one_row_and_not_four(fleet_home, tmp_path):  # noqa: F811
    """The laptop case: `Z:` is not connected this morning. Four rows saying "no AGENTS.md any
    more" would send the operator to re-run `ad-setup --project` in four folders that are fine."""
    from agentdata.fleet import registry as R

    gone = [R.Repo(name="luna", path=str(tmp_path / "Z" / "luna")),
            R.Repo(name="velocity", path=str(tmp_path / "Z" / "velocity"))]
    row = _rows(repos=gone)["parent folder"]
    assert row.status == "warn" and "is not there" in row.detail and "2 of 2" in row.detail
    assert "nothing is removed for you" in row.hint and row.keys == ()


def test_one_moved_checkout_names_it_and_offers_the_scan(fleet_home, tmp_path):  # noqa: F811
    from agentdata.fleet import registry as R

    repos = [a_repo(tmp_path, "luna"), R.Repo(name="ghost", path=str(tmp_path / "ghost"))]
    row = _rows(repos=repos)["parent folder"]
    assert row.status == "warn" and "ghost" in row.detail
    assert "ad-fleet repo add --scan" in row.hint


def test_no_repositories_is_a_skip_that_names_the_quickstart(fleet_home):        # noqa: F811
    row = _rows()["parent folder"]
    assert row.status == "skip" and "ad-fleet quickstart" in row.hint


# ---- the catalogue


def test_a_catalogue_that_was_never_built_asks_for_the_index():
    row = _rows(catalogue={"exists": False, "path": "x/catalogue.sqlite"})["catalogue"]
    assert row.status == "warn" and row.detail == "not built yet"
    assert "ad-fleet index" in row.hint and row.keys == ()


@pytest.mark.parametrize("fts,said", [(True, "FTS5"), (False, "LIKE fallback")])
def test_the_row_states_which_search_is_answering(fts, said):
    """"Search found nothing" and "search is on the fallback" look identical from a result set."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    row = _rows(catalogue={"exists": True, "fts": fts, "docs": 40, "projects": 4,
                           "last_indexed": now})["catalogue"]
    assert row.status == "ok" and said in row.detail and "40 docs across 4 projects" in row.detail


def test_a_catalogue_older_than_a_day_is_reported_with_its_age():
    stale = time.strftime("%Y-%m-%dT%H:%M:%S",
                          time.localtime(time.time() - CATALOGUE_STALE_S - 3600))
    row = _rows(catalogue={"exists": True, "fts": True, "docs": 40, "projects": 4,
                           "last_indexed": stale})["catalogue"]
    assert row.status == "warn" and "25h ago" in row.detail and "ad-fleet index" in row.hint

    broken = _rows(catalogue={"exists": True, "path": "c.sqlite", "error": "file is not a database"})
    assert broken["catalogue"].status == "warn" and "--rebuild" in broken["catalogue"].hint


def test_the_catalogue_row_reads_what_a_search_would_read(fleet_home, tmp_path):  # noqa: F811
    """Through `Catalogue`, not a second sqlite reader that could disagree with it -- and without
    creating the database when there is none, which would turn "never indexed" into "empty"."""
    repo = a_repo(tmp_path, "luna")
    assert FleetStep()._catalogue() == {"exists": False,
                                        "path": os.path.join(str(fleet_home), "catalogue.sqlite")
                                        .replace("\\", "/")}
    assert not os.path.exists(os.path.join(str(fleet_home), "catalogue.sqlite")), \
        "the doctor built a catalogue as a side effect of reporting on it"

    cat = CAT.Catalogue.open()
    try:
        cat.index([repo])
    finally:
        cat.close()
    found = FleetStep()._catalogue()
    assert found["exists"] and found["docs"] > 0 and found["fts"] in (True, False)


# ---- the facts behind the tile links


def test_a_bare_project_is_named_with_the_agents_md_keys_it_is_missing(fleet_home, tmp_path):  # noqa: F811
    """The row has to name keys a human can actually type into a facts block, so they come from
    `links.MISSING_KEYS_HINT` rather than from a sentence written here."""
    repo = a_repo(tmp_path, "luna")
    ctx = W.Context(cfg={}, det=W.Detectors(), ask=W.Prompter(), interactive=False)
    facts = FleetStep()._facts(ctx, [repo])
    assert facts == [{"name": "luna", "keys": ["jira_board_id", "report_id", "ds_id", "ws_id",
                                               "bitbucket_repo"]}]

    row = _rows(repos=[repo], facts=facts)["facts"]
    assert row.status == "warn" and "luna needs jira_board_id" in row.detail
    assert "AGENTS.md" in row.hint and "ad-fleet show" in row.hint
    assert row.keys == (), "no answer to this wizard writes another project's AGENTS.md"
    for key in facts[0]["keys"]:
        assert key in L.MISSING_KEYS_HINT.values(), f"{key} is not a key anyone can add"


def test_a_project_that_supplies_its_facts_passes(fleet_home, tmp_path):        # noqa: F811
    repo = a_repo(tmp_path, "luna")
    row = _rows(repos=[repo], facts=[{"name": "luna", "keys": []}])["facts"]
    assert row.status == "ok" and "1 projects supply" in row.detail


# ---- the tray


def test_the_inbox_row_says_which_folder_and_that_nothing_is_opened():
    rows = _rows(inbox={"folders": [{"path": "C:/Users/luna/Downloads", "why": ""}]})
    assert rows["inbox"].status == "ok" and "no file is opened" in rows["inbox"].detail

    refused = _rows(inbox={"folders": [{"path": "D:/Downloads", "why": "Access is denied"}]})
    assert refused["inbox"].status == "warn" and "Access is denied" in refused["inbox"].detail

    none = _rows(inbox={"folders": []})
    assert none["inbox"].status == "warn" and "--folder" in none["inbox"].hint


def test_the_inbox_probe_lists_one_entry_and_opens_no_file(tmp_path, monkeypatch):
    """`os.scandir` is what `inbox.look` uses. A row that answered from `os.access` would pass on a
    Downloads redirected onto a disconnected OneDrive."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "statement.pdf").write_text("not read", encoding="utf-8")
    monkeypatch.setattr("agentdata.fleet.inbox.default_folders", lambda: [str(downloads)])

    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda *a, **k: (opened.append(a[0]), real_open(*a, **k))[1])
    found = FleetStep()._inbox()
    assert found["folders"] == [{"path": str(downloads), "why": ""}]
    assert not [p for p in opened if "Downloads" in str(p)], f"a file in Downloads was opened: {opened}"


# ---- what the polling costs


def test_the_token_budget_row_makes_the_tile_count_visible():
    """Four tiles on the defaults is 228 requests an hour; eight is over the line. That is the
    fact the row exists to put in front of somebody before their tenant does."""
    quiet = _rows(polls={"settings": P.settings({}), "repos": 4, "counts": {}})["token budget"]
    assert quiet.status == "ok" and "4 tile(s) ≈ 228 requests/hour" in quiet.detail
    assert "one Jira search covers every tile" in quiet.detail

    busy = _rows(polls={"settings": P.settings({}), "repos": 8, "counts": {}})["token budget"]
    assert busy.status == "warn" and f"over {POLLS_PER_HOUR_WARN}" in busy.hint
    assert busy.keys == ("fleet.poll.enabled", "fleet.poll.jira.interval")


def test_a_stand_down_is_reported_because_the_budget_itself_said_so():
    counts = {"day": "2026-01-04", "total": 120, "requests": {"jira": 60, "pr": 60},
              "stood_down": {"jira": 3}, "errors": {}}
    row = _rows(polls={"settings": P.settings({}), "repos": 2, "counts": counts})["token budget"]
    assert row.status == "warn" and "stood down 3 time(s)" in row.detail
    assert "today 120" in row.detail and "60 jira" in row.detail
    assert "fleet.poll.jira.interval" in row.hint


def test_polling_turned_off_is_a_setting_and_not_a_fault():
    off = P.settings({"fleet": {"poll": {"enabled": False}}})
    row = _rows(polls={"settings": off, "repos": 4, "counts": {}})["token budget"]
    assert row.status == "ok" and "polling is off" in row.detail
    assert row.keys == ("fleet.poll.enabled", "fleet.poll.jira.interval")


# ------------------------------------------------------------------- and what --patch does with them


def test_every_desk_row_either_names_its_settings_or_names_none(fleet_home, tmp_path):  # noqa: F811
    """HANDOFF.md's rule, on the new rows. A row whose fix is an edit to another repository's
    AGENTS.md, a re-index or a reconnected drive names no key *deliberately*: `--patch` lists it
    under `manual` with its hint instead of asking a question that cannot help."""
    from agentdata.fleet import registry as R

    a_repo(tmp_path, "luna")
    rows = _rows(repos=[R.Repo(name="ghost", path=str(tmp_path / "ghost"))],
                 catalogue={"exists": False, "path": "c"},
                 facts=[{"name": "luna", "keys": ["ws_id"]}], inbox={"folders": []},
                 polls={"settings": P.settings({}), "repos": 1, "counts": {}})
    for name in ("parent folder", "catalogue", "facts", "inbox"):
        assert rows[name].status == "warn", f"{name} is not in the state this asserts about"
        assert rows[name].keys == (), f"{name} asks a question no answer can fix"
        assert rows[name].hint, f"{name} lands under manual with no hint to follow"
    for key in rows["token budget"].keys:
        assert key.startswith("fleet.poll."), key


def test_patch_reaches_the_poll_prompts_and_leaves_the_manual_rows_to_the_human(
        fleet_home, tmp_path, capsys, monkeypatch):                             # noqa: F811
    """One warn row that a setting really does fix, re-asked; four that it does not, reported."""
    monkeypatch.setattr("agentdata.proc.run", lambda *a, **k: (127, "", "not found", 0.0))
    a_repo(tmp_path, "luna")
    C.save({"fleet": {"enabled": True, "poll": {"jira": {"interval": 5}}}})

    rc = W.run_setup(["--patch", "--include-warnings", "--non-interactive", "--offline",
                      "--only", "fleet", "--set", "fleet.poll.jira.interval=300"], W.Detectors())
    out, _err = capsys.readouterr()

    assert C.load()["fleet"]["poll"]["jira"]["interval"] == 300, out
    assert "fleet.poll.jira.interval" in out
    assert "fleet/facts" in out or "fleet/catalogue" in out, "the manual rows were not reported"
    assert rc in (0, 1), out          # `copilot` is not installed on a CI runner; that is a fail row
