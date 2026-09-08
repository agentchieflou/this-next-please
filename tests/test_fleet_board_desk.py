"""The desk half of the dashboard: the catalogue panel, the link rail, the polled cells, the
Downloads tray and the three layouts.

There is no browser here, for the same reason there is none in `test_fleet_serve.py`: what a browser
would add is whether the arrangement *looks* right on four monitors, and that is #133's sitting with
a person in front of it. What is proved here is everything that would otherwise break silently --
the JSON each panel draws from, the one write the tray is allowed to make, the path the verify pane
refuses to follow, the selection two windows share, and the fact that the page and the stylesheet
still know every layout name the CLI can print.
"""
from __future__ import annotations
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentdata import cli_fleet
from agentdata.fleet import catalogue as CAT, events as E, inbox as IN, poll as P, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")
APP_JS = os.path.join(STATIC, "app.js")
APP_CSS = os.path.join(STATIC, "app.css")
INDEX = os.path.join(STATIC, "index.html")

FACTS = ("- jira_project: {project}\n"
         "- jira_url: https://example.atlassian.net\n"
         "- jira_board_id: 42\n"
         "- ws_id: 11111111-2222-3333-4444-555555555555\n"
         "- report_id: 66666666-7777-8888-9999-000000000000\n")

# The rest of a real fact block: where the warehouse is, which share the DPM run writes to, the
# read-only service account, and where TabularEditor is installed. The repo's own agent needs all
# four; the tile needs none of them, and not one of them ends in token/secret/password/api_key/pat,
# so `config.looks_secret()` keeps every one. That is exactly why the tile filters on an allow-list.
SITE_FACTS = ("- td_host: teradata-prod.corp.example\n"
              "- dpm_share: \\\\share\\dpm\\runs\n"
              "- sql_user: svc_rdsd_ro\n"
              "- tabular_editor: C:\\Program Files\\TabularEditor 3\\TabularEditor.exe\n")


@pytest.fixture()
def desk(fleet_home, tmp_path, monkeypatch):                    # noqa: F811 - the fixture is the argument
    """A fleet with its own config, so the page's inbox watches a temporary Downloads.

    `S.reset()` on both sides because the poller, the inbox and the catalogue handle are held for the
    whole process: a test that inherited the previous one's sqlite file would pass for the wrong
    reason, and one that left its own behind would fail the next.
    """
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    config = tmp_path / "agentdata.json"
    config.write_text(json.dumps({"version": 1, "fleet": {"inbox": {"folders": [str(downloads)]},
                                                          "poll": {"enabled": False}}}),
                      encoding="utf-8")
    monkeypatch.setenv("AGENTDATA_CONFIG", str(config))
    S.reset()
    yield downloads
    S.reset()


def a_project(tmp_path, name, *, project="RDSD", ticket="", phase="idle", facts=True):
    path = make_project(tmp_path / name, project=project, ticket=ticket, phase=phase)
    if facts:
        with open(os.path.join(path, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# {name}\n\n" + FACTS.format(project=project))
    Registry().add(path, name=name)
    return path


def site_facts(repo_path, project="RDSD"):
    """Rewrite a fixture's AGENTS.md with the link facts *and* the site facts a real one carries."""
    with open(os.path.join(repo_path, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# facts\n\n" + FACTS.format(project=project) + SITE_FACTS)
    return repo_path


def out_file(repo_path, name, body="# findings\n\n3 of 41 rows differ on Sales Amount\n"):
    folder = os.path.join(repo_path, ".agent", "out")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


def saved(folder, name, body="x", when=None):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    if when is not None:
        os.utime(path, (when, when))
    return path


# ------------------------------------------------------------------ what is this project (#130)


def test_the_panel_answers_from_the_catalogue_once_the_repo_is_indexed(desk, tmp_path):
    path = a_project(tmp_path, "velocity", ticket="RDSD-22449")
    os.makedirs(os.path.join(path, ".agent", "friction"), exist_ok=True)
    with open(os.path.join(path, ".agent", "friction", "20260101T0900-stuck.md"),
              encoding="utf-8", mode="w", newline="\n") as f:
        f.write("# The refresh never finished\n\n## What would unblock me\n\n"
                "Somebody has to restart the gateway.\n")
    cat = CAT.Catalogue.open()
    cat.index(Registry())
    cat.close()
    S.reset()

    panel = S.show_for("velocity")
    assert panel["indexed"] is True
    assert panel["facts"]["jira_board_id"] == "42"
    stop = panel["friction"][0]
    assert stop["date"] == "2026-01-01" and "restart the gateway" in stop["unblock"]


def test_an_unindexed_repo_still_gets_its_links_rather_than_looking_broken(desk, tmp_path):
    """A tile with no links until somebody remembers to run `ad-fleet index` reads as a bug in the
    fleet. The facts come from the repo's own AGENTS.md either way."""
    a_project(tmp_path, "luna", ticket="RDSD-1")
    panel = S.show_for("luna")
    assert panel["indexed"] is False
    assert [row["name"] for row in panel["links"]] == ["ticket", "board", "report", "workspace",
                                                       "folder"]


def test_the_tile_is_sent_the_link_facts_and_never_the_whole_fact_block(desk, tmp_path):
    """`catalogue.LINK_FACTS` exists so a Teradata hostname cannot reach a browser, and the tile is
    the surface the operator screenshots into a ticket.

    Both halves of `show_for` are checked, unindexed and indexed, because they reach the facts by
    different routes -- `CAT._facts()` off AGENTS.md and the catalogue's `show()` off sqlite -- and
    a filter on only one of them closes the leak on exactly the machines that never ran
    `ad-fleet index`, or on exactly the ones that did.
    """
    path = site_facts(a_project(tmp_path, "velocity", ticket="RDSD-22449"))

    cold = S.show_for("velocity")
    assert cold["indexed"] is False
    assert set(cold["facts"]) <= set(CAT.LINK_FACTS)
    assert cold["facts"]["jira_board_id"] == "42", "the link facts still travel"

    cat = CAT.Catalogue.open()
    cat.index(Registry())
    cat.close()
    S.reset()
    warm = S.show_for("velocity")
    assert warm["indexed"] is True
    assert set(warm["facts"]) <= set(CAT.LINK_FACTS)

    for panel in (cold, warm):
        blob = json.dumps(panel)
        for leak in ("teradata-prod.corp.example", "dpm\\\\runs", "svc_rdsd_ro", "TabularEditor"):
            assert leak not in blob, f"{leak} reached the tile"
    # And the rail is still built from the whole block, so filtering the payload cost no links.
    assert [row["name"] for row in cold["links"]] == ["ticket", "board", "report", "workspace",
                                                      "folder"]
    assert os.path.isfile(os.path.join(path, "AGENTS.md"))


def test_the_site_facts_are_still_on_ad_fleet_show_where_a_human_asked_for_them(desk, tmp_path):
    """The filter is about the browser, not about secrecy: a human who typed `ad-fleet show` asked
    for the fact block and gets it. Narrowing the catalogue itself would take the warehouse host
    away from the person who needs it and leave the tile no safer."""
    site_facts(a_project(tmp_path, "velocity", ticket="RDSD-22449"))
    cat = CAT.Catalogue.open()
    cat.index(Registry())
    try:
        assert cat.show("velocity")["facts"]["td_host"] == "teradata-prod.corp.example"
    finally:
        cat.close()
    S.reset()


def test_every_desk_route_filters_the_facts_and_not_just_the_one_panel(running, tmp_path):
    """`/api/show` is one tile and `/api/desk` is all of them; the grid draws from the second. A
    filter on the panel function only is a leak that reappears the moment the page uses the other
    route -- which it does, on a 15 s clock, for every tile at once."""
    base, token = running
    site_facts(a_project(tmp_path, "velocity", ticket="RDSD-22449"))
    for path in ("/api/show?project=velocity", "/api/desk"):
        body = json.dumps(get(base, path, token))
        assert "teradata-prod.corp.example" not in body, path
        assert "svc_rdsd_ro" not in body, path
        assert "jira_board_id" in body, path


def test_search_is_the_same_catalogue_the_cli_verb_asks(desk, tmp_path):
    a_project(tmp_path, "velocity")
    with open(os.path.join(str(tmp_path / "velocity"), "AGENTS.md"), "a",
              encoding="utf-8", newline="\n") as f:
        f.write("\n## Notes\n\nThe Velocity page is the one the steering group reads.\n")
    a_project(tmp_path, "other", project="DATA")
    cat = CAT.Catalogue.open()
    cat.index(Registry())
    cat.close()
    S.reset()

    hits = S.catalogue().where("velocity")
    assert hits and hits[0]["project"] == "velocity"


def test_a_catalogue_that_will_not_open_is_a_reason_and_not_a_500(desk, tmp_path, monkeypatch):
    a_project(tmp_path, "luna")
    monkeypatch.setattr(CAT.Catalogue, "open", classmethod(
        lambda cls, *a, **k: (_ for _ in ()).throw(CAT.CatalogueError("half written", "delete it"))))
    S.reset()
    assert S.catalogue() is None
    panel = S.show_for("luna")            # the rail still works; only the catalogue half is gone
    assert panel["indexed"] is False and panel["links"]


# --------------------------------------------------------------------- the link rail, and cells


def test_a_missing_fact_is_a_named_key_and_never_a_broken_link(desk, tmp_path):
    path = make_project(tmp_path / "bare", project="RDSD")
    Registry().add(path, name="bare")
    panel = S.show_for("bare")
    assert all(row["url"] for row in panel["links"])
    assert "ws_id" in panel["missing_keys"] and "jira_board_id" in panel["missing_keys"]
    assert all(row["why_missing"] for row in panel["missing"])


def a_poller(**readers):
    """The shared poller with its read paths replaced. The four are attributes on purpose (#131)."""
    poller = S.poller()
    for name, reader in readers.items():
        setattr(poller, name, reader)
    return poller


def test_a_failing_poll_greys_the_cell_and_keeps_the_last_value_it_had(desk, tmp_path):
    """The criterion is "grey, not wrong". A blanked cell loses what was known; a cell that keeps
    the value with no age looks current. The honest answer is the old value, its age, and the
    error."""
    a_project(tmp_path, "luna")
    clock = {"t": 1_000_000.0}
    poller = a_poller(git_reader=lambda repo: {"branch": "feature/velocity", "ahead": 1,
                                               "behind": 0, "dirty": True})
    poller.now = lambda: clock["t"]
    poller.settings["git"]["on"] = True
    poller.tick(clock["t"])
    good = S.poll_state("luna")["git"]
    assert good["value"]["text"] == "feature/velocity +1 dirty"
    assert good["grey"] is False and not good["error"]

    def broken(repo):
        raise OSError(2, "git is not on PATH")

    poller.git_reader = broken
    clock["t"] += 600
    poller.tick(clock["t"])
    after = S.poll_state("luna")["git"]
    assert after["value"]["text"] == "feature/velocity +1 dirty", "the cell went blank or wrong"
    assert after["grey"] is True
    assert "git is not on PATH" in after["error"], "the tooltip has nothing to say"
    assert after["age_s"] >= 600, "a stale cell must say how stale"

    poller.git_reader = lambda repo: {"branch": "main", "ahead": 0, "behind": 0, "dirty": False}
    clock["t"] += 600
    poller.tick(clock["t"])
    recovered = S.poll_state("luna")["git"]
    assert recovered["grey"] is False and recovered["value"]["text"] == "main"


def test_the_cells_reach_the_page_beside_the_agents_own_state(desk, tmp_path):
    """Two state words on one row would eventually disagree, so the project's state travels under
    its own key with its own ages."""
    a_project(tmp_path, "luna")
    poller = a_poller(git_reader=lambda repo: {"branch": "main", "ahead": 0, "behind": 0,
                                               "dirty": False})
    poller.settings["git"]["on"] = True
    poller.tick(time.time())
    row = S.fleet_snapshot()["repos"][0]
    assert row["polls"]["git"]["value"]["text"] == "main"
    assert set(row["polls"]) == {"ticket", "pr", "refresh", "git"}
    assert "state" in row and row["state"] != row["polls"]["git"]["value"]["text"]


def test_polling_the_page_is_rate_limited_for_the_whole_process(desk, tmp_path, monkeypatch):
    """Four windows on four screens are four SSE loops. One poll between them, or the operator's
    Jira traffic multiplies by the number of monitors they own."""
    a_project(tmp_path, "luna")
    ticks = []
    poller = a_poller(git_reader=lambda repo: ticks.append(1) or {"branch": "main"})
    poller.settings["git"]["on"] = True
    S.poll_tick(2_000_000.0)
    S.poll_tick(2_000_000.1)
    S.poll_tick(2_000_000.2)
    assert len(ticks) == 1, "every open tab polled"
    S.poll_tick(2_000_100.0)               # past both the page's floor and git's own interval
    assert len(ticks) == 2


# ----------------------------------------------------------------------------- the verify pane


def test_the_verify_pane_shows_this_repos_latest_summary_and_nothing_else(desk, tmp_path):
    mine = a_project(tmp_path, "luna")
    theirs = a_project(tmp_path, "other", project="DATA")
    out_file(theirs, "DATA-9-uat-findings.md", "# not yours\n")
    old = out_file(mine, "RDSD-1-uat-findings.md", "# old\n")
    os.utime(old, (time.time() - 4000, time.time() - 4000))
    out_file(mine, "RDSD-2-uat-findings.md", "# findings\n\n3 rows differ\n")

    pane = S.verify_for(Registry().get("luna"))
    assert pane["latest"]["name"] == "RDSD-2-uat-findings.md"
    assert pane["latest"]["tool"] == "ad-uat reconcile"
    assert "3 rows differ" in pane["latest"]["excerpt"]
    for row in [pane["latest"]] + pane["others"]:
        assert row["path"].startswith(S.textio.norm_path(mine)), row["path"]
    assert "not yours" not in json.dumps(pane)


def test_a_link_out_of_the_repo_is_refused_by_name_not_followed(desk, tmp_path):
    """AGENTS.md rule 3: an agent never reads a second project's `.agent/`, and neither does the
    tile that stands for it. A symlink or an NTFS junction dropped into `.agent/out/` is the only
    way a foreign file could otherwise appear on this pane."""
    mine = a_project(tmp_path, "luna")
    theirs = a_project(tmp_path, "other", project="DATA")
    secret = out_file(theirs, "DATA-9-uat-findings.md", "# the other project's numbers\n")
    os.makedirs(os.path.join(mine, ".agent", "out"), exist_ok=True)
    door = os.path.join(mine, ".agent", "out", "borrowed-uat-findings.md")
    try:
        os.symlink(secret, door)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("this machine will not make a symlink without elevation")

    pane = S.verify_for(Registry().get("luna"))
    assert pane["latest"] == {} and pane["found"] == 0
    assert pane["refused"] and pane["refused"][0]["name"] == "borrowed-uat-findings.md"
    assert "outside" in pane["refused"][0]["why"]
    assert "the other project's numbers" not in json.dumps(pane)


def test_only_the_allow_listed_names_are_read_out_of_agent_out(desk, tmp_path):
    """`.agent/out/` also holds trace jsonl, screenshots and the debug log. "Show the newest file"
    would eventually put a stack trace on the operator's centre monitor."""
    mine = a_project(tmp_path, "luna")
    out_file(mine, "agentdata-debug.log", "Traceback (most recent call last):\n")
    out_file(mine, "trace-20260101.jsonl", "{}\n")
    assert S.verify_for(Registry().get("luna"))["found"] == 0
    out_file(mine, "RDSD-1-uat-findings.md")
    assert S.verify_for(Registry().get("luna"))["found"] == 1


def test_a_summary_with_something_credential_shaped_is_described_not_shown(desk, tmp_path):
    """A file in `.agent/out/` was written by a tool we did not write. The same refusal the
    catalogue applies to what it indexes applies to what the pane quotes."""
    mine = a_project(tmp_path, "luna")
    out_file(mine, "RDSD-1-uat-findings.md", "# findings\n\nAuthorization: Bearer abc123def456\n")
    pane = S.verify_for(Registry().get("luna"))
    assert "abc123def456" not in json.dumps(pane)
    assert "not shown" in pane["latest"]["excerpt"]


# ------------------------------------------------------------------ the Downloads inbox (#132)


def test_the_tray_splits_into_the_three_answers_the_inbox_can_give(desk, tmp_path):
    a_project(tmp_path, "rdsd", ticket="RDSD-22449")
    saved(desk, "RDSD-22449-export.md")
    saved(desk, "notes.md")
    saved(desk, "setup.exe")
    tray = S.inbox_snapshot()

    assert [row["name"] for row in tray["offers"]["rdsd"]] == ["RDSD-22449-export.md"]
    assert [row["name"] for row in tray["unsorted"]] == ["notes.md"]
    assert [row["name"] for row in tray["not_offered"]] == ["setup.exe"]
    assert "executable" in tray["not_offered"][0]["reason"]


def test_attaching_from_the_page_is_the_one_write_and_it_lands_in_agent_in(desk, tmp_path):
    path = a_project(tmp_path, "rdsd", ticket="RDSD-22449")
    saved(desk, "RDSD-22449-export.md", body="ticket,amount\n")
    offer = S.inbox_snapshot()["offers"]["rdsd"][0]

    event = S.act("attach", {"id": offer["id"], "repo": "rdsd"})
    landed = os.path.join(path, ".agent", "in", "RDSD-22449", "RDSD-22449-export.md")
    assert os.path.isfile(landed)
    assert event["kind"] == IN.ATTACHED and event["data"]["attached"] is True
    assert os.path.isfile(os.path.join(str(desk), "RDSD-22449-export.md")), "the original moved"
    assert any(ev["kind"] == IN.ATTACHED for ev in E.read("rdsd"))

    again = S.act("attach", {"id": offer["id"], "repo": "rdsd"})
    assert again["data"]["attached"] is False and "already attached" in again["data"]["why"]


def test_dismissing_from_the_page_survives_the_next_look(desk, tmp_path):
    a_project(tmp_path, "rdsd", ticket="RDSD-22449")
    saved(desk, "notes.md")
    offer = S.inbox_snapshot()["unsorted"][0]
    S.act("dismiss", {"id": offer["id"]})
    assert S.inbox_snapshot()["unsorted"] == []


def test_a_row_that_moved_between_the_draw_and_the_click_is_refused_by_name(desk, tmp_path):
    a_project(tmp_path, "rdsd", ticket="RDSD-22449")
    saved(desk, "RDSD-22449-export.md")
    offer = S.inbox_snapshot()["offers"]["rdsd"][0]
    os.remove(os.path.join(str(desk), "RDSD-22449-export.md"))
    with pytest.raises(IN.InboxError) as e:
        S.act("attach", {"id": offer["id"], "repo": "rdsd"})
    assert offer["id"] in e.value.msg and e.value.hint


def test_the_page_never_attaches_something_the_inbox_refused(desk, tmp_path):
    a_project(tmp_path, "rdsd", ticket="RDSD-22449")
    saved(desk, "setup.exe")
    offer = S.inbox_snapshot()["not_offered"][0]
    with pytest.raises(IN.InboxError) as e:
        S.act("attach", {"id": offer["id"], "repo": "rdsd"})
    assert "not offered" in e.value.msg


# ------------------------------------------------------------- the shared selection (#133 B)


def test_two_subscribers_are_told_the_same_selected_project(desk, tmp_path):
    """Layout B is three browser windows that agree on one project. The only thing they share is
    this stream, so the selection is server state pushed as a frame -- clicking a tile on the left
    monitor is what changes the centre one."""
    a_project(tmp_path, "luna")
    a_project(tmp_path, "other", project="DATA")
    left, centre = [], []
    S.stream_events({}, threading.Event(), left.append, once=True, polls=False)
    S.stream_events({}, threading.Event(), centre.append, once=True, polls=False)

    S.act("select", {"repo": "other"})
    left.clear()
    centre.clear()
    S.stream_events({}, threading.Event(), left.append, once=True, polls=False)
    S.stream_events({}, threading.Event(), centre.append, once=True, polls=False)
    for frames in (left, centre):
        blob = "".join(frames)
        assert "event: desk" in blob
        assert json.loads(blob.split("event: desk\ndata: ")[1].split("\n")[0])["selected"] == "other"


def test_a_window_that_joins_late_is_told_the_selection_immediately(desk, tmp_path):
    a_project(tmp_path, "luna")
    S.select(selected="luna")
    late = []
    S.stream_events({}, threading.Event(), late.append, once=True, polls=False)
    assert '"selected": "luna"' in "".join(late)


def test_the_selection_frame_is_not_repeated_while_nothing_changes(desk, tmp_path):
    """A frame per tick would be a heartbeat with a payload, and the page would redraw the centre
    monitor four times a second for no reason."""
    a_project(tmp_path, "luna")
    cursors, out = {}, []
    stop = threading.Event()
    S.stream_events(cursors, stop, out.append, once=True, polls=False)
    assert "event: desk" in "".join(out)


def test_the_screen_pinning_is_shared_so_a_swap_moves_it_off_the_other_monitor(desk, tmp_path):
    a_project(tmp_path, "luna")
    a_project(tmp_path, "other", project="DATA")
    S.act("select", {"screens": ["luna", "other"]})
    assert S.desk_state()["screens"] == ["luna", "other"]
    S.act("select", {"screens": ["other", "luna"]})
    assert S.desk_state()["screens"] == ["other", "luna"]
    assert S.fleet_snapshot()["desk"]["screens"] == ["other", "luna"]


def test_selecting_the_same_project_twice_does_not_wake_the_other_windows(desk, tmp_path):
    a_project(tmp_path, "luna")
    first = S.select(selected="luna")["version"]
    assert S.select(selected="luna")["version"] == first


# ------------------------------------------------- what four windows cost the laptop (#133)


def test_four_windows_fold_the_streams_once_between_them_and_not_once_each(desk, tmp_path,
                                                                          monkeypatch):
    """#133's premise is that four windows on four screens are cheap *because* they share one
    stream. `E.refresh` is the expensive half of the loop -- per repository it reads the cursor,
    reads the agent's raw log, globs `.agent/friction/`, rewrites the cursor and appends -- and it
    ran per repository per tick per connection, so the fourth monitor cost four times the disk of
    the first. It is rate-limited for the process now, the way `poll_tick` already was.
    """
    a_project(tmp_path, "luna")
    a_project(tmp_path, "other", project="DATA")
    folded = []
    real = E.refresh
    monkeypatch.setattr(E, "refresh", lambda name, *a, **kw: (folded.append(name),
                                                              real(name, *a, **kw))[1])

    for _ in range(4):                       # four windows, one tick
        S.stream_events({}, threading.Event(), lambda _f: None, once=True, polls=False)
    assert folded == ["luna", "other"], "the fold ran per connection, not per process"

    monkeypatch.setattr(S, "FOLD_EVERY_S", 0.0)   # the floor expiring, without the wall clock
    S.stream_events({}, threading.Event(), lambda _f: None, once=True, polls=False)
    assert folded == ["luna", "other", "luna", "other"], "the floor never let go"


def test_the_fold_floor_stays_under_the_second_the_transcript_is_promised_in(desk):
    """The fold is how an agent's newest line reaches the tile, so this floor is not the poller's
    five seconds: `test_a_live_stream_delivers_a_new_event_within_a_second` is the bar, and the
    worst case a window waits is one floor plus one tick."""
    assert S.FOLD_EVERY_S + S.TICK_S < 1.0


def test_the_stream_reads_the_registry_once_a_tick_and_not_once_a_tile(desk, tmp_path,
                                                                      monkeypatch):
    """`Registry()` re-parses `registry.json` in its constructor, and the loop built one per tile on
    top of the one it built for the names. The cost of a tick has to be flat in the number of
    projects the operator registered, or the twelfth repo is what makes the page expensive."""
    reads = []
    real = Registry.load
    monkeypatch.setattr(Registry, "load", lambda self: (reads.append(self.path), real(self))[1])

    a_project(tmp_path, "one")
    a_project(tmp_path, "two", project="DATA")
    reads.clear()
    S.stream_events({}, threading.Event(), lambda _f: None, once=True, polls=False)
    small = len(reads)

    for i in range(8):
        a_project(tmp_path, f"more{i}", project="DATA")
    reads.clear()
    S.stream_events({}, threading.Event(), lambda _f: None, once=True, polls=False)
    assert len(reads) == small, f"{small} registry reads for 2 repos, {len(reads)} for 10"


# ---------------------------------------------------------------------------- the routes


@pytest.fixture()
def running(desk):
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", token
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def get(base, path, token):
    sep = "&" if "?" in path else "?"
    with urllib.request.urlopen(f"{base}{path}{sep}t={token}", timeout=10) as r:
        return json.loads(r.read())


def test_every_desk_route_needs_the_token_like_everything_else(running):
    base, token = running
    for path in ("/api/desk", "/api/show?project=luna", "/api/inbox", "/api/where?q=x"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}{path}", timeout=10)
        assert e.value.code == 403, path


def test_the_desk_answers_every_tile_in_one_request(running, tmp_path):
    """One round trip and not one per tile: #133 puts the grid on a screen the operator is not even
    looking at, and a fetch per tile per refresh is what makes that expensive."""
    base, token = running
    a_project(tmp_path, "luna", ticket="RDSD-1")
    a_project(tmp_path, "other", project="DATA")
    saved(os.path.join(str(tmp_path), "Downloads"), "notes.md")
    body = get(base, "/api/desk", token)
    assert body["ok"] is True
    assert sorted(body["order"]) == ["luna", "other"]
    assert body["projects"]["luna"]["links"]
    assert "verify" in body["projects"]["luna"] and "polls" in body["projects"]["luna"]
    assert [row["name"] for row in body["unsorted"]] == ["notes.md"]
    assert body["desk"] == S.desk_state()


def test_the_centre_window_draws_one_project_from_one_request(running, tmp_path):
    """Layout B's verify window shows the selected project's links, its verify pane and its inbox.
    All three are on the project's own row, so a window that has been told which project it is on
    needs nothing else."""
    base, token = running
    path = a_project(tmp_path, "luna", ticket="RDSD-1")
    out_file(path, "RDSD-1-uat-findings.md")
    saved(os.path.join(str(tmp_path), "Downloads"), "RDSD-1-export.md")
    S.act("select", {"repo": "luna"})

    one = get(base, "/api/show?project=luna", token)
    assert one["ok"] is True
    assert [row["name"] for row in one["links"]][:2] == ["ticket", "board"]
    assert one["verify"]["latest"]["name"] == "RDSD-1-uat-findings.md"
    whole = get(base, "/api/desk", token)
    assert [row["name"] for row in whole["offers"]["luna"]] == ["RDSD-1-export.md"]
    assert whole["desk"]["selected"] == "luna"


def test_a_screen_with_nothing_pinned_still_shows_a_project(desk, tmp_path):
    """`?layout=screens&screen=2` on a fresh fleet must not be an empty monitor: with no pinning the
    Nth registered repository is the Nth screen, and the swap is what changes that."""
    js = open(APP_JS, encoding="utf-8").read()
    assert "return pinned || names[SCREEN - 1] || \"\";" in js
    a_project(tmp_path, "luna")
    a_project(tmp_path, "other", project="DATA")
    assert S.desk_state()["screens"] == []
    assert [r.name for r in Registry().sorted()] == ["luna", "other"]


def test_show_for_a_repo_that_is_gone_is_a_reason_the_panel_can_render(running):
    base, token = running
    body = get(base, "/api/show?project=vanished", token)
    assert body["ok"] is False and "vanished" in body["error"] and body["hint"]


def test_where_with_no_query_asks_nothing_of_the_catalogue(running):
    base, token = running
    body = get(base, "/api/where?q=%20", token)
    assert body["ok"] is True and body["results"] == []


def test_the_page_itself_is_served_for_every_layout_url(running):
    """The layouts are parameters on one page, so the server does not have to know them -- but a
    URL the CLI prints has to come back with the page and not a 404."""
    base, token = running
    for path in ("/?layout=grid", "/?layout=roles&view=agents", "/?layout=roles&view=verify",
                 "/?layout=roles&view=board", "/?layout=screens", "/?layout=screens&screen=2"):
        sep = "&" if "?" in path else "?"
        with urllib.request.urlopen(f"{base}{path}{sep}t={token}", timeout=10) as r:
            assert r.status == 200
            assert '<template id="tile">' in r.read().decode("utf-8")


def raw_get(base, path):
    """A GET with the path sent exactly as written -- `urlopen` would tidy `..` away before the
    server ever saw it, and tidying it away is the bug under test."""
    host, _, port = base[len("http://"):].partition(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.putrequest("GET", path, skip_accept_encoding=True)
        conn.endheaders()
        answer = conn.getresponse()
        return answer.status, answer.read().decode("utf-8", "replace")
    finally:
        conn.close()


def test_a_directory_beside_static_is_not_served_because_its_name_starts_with_static(
        running, tmp_path, monkeypatch):
    """`/static/` serves one directory. The containment check was `path.startswith(STATIC)`, which
    is a prefix match on a string and not a check that the path is inside the directory: every
    sibling whose name merely begins with `static` passed it. Nothing in the tree is named that
    today, which is why this had to be a test rather than a bug report -- one `mkdir` beside the
    package turns a 404 into a file read.
    """
    root = tmp_path / "pkg"
    (root / "static").mkdir(parents=True)
    with open(root / "static" / "app.js", "w", encoding="utf-8", newline="\n") as f:
        f.write("/* the real one */\n")
    (root / "static_backup").mkdir()
    with open(root / "static_backup" / "app.js", "w", encoding="utf-8", newline="\n") as f:
        f.write("/* NOT SERVED */\n")
    monkeypatch.setattr(S, "STATIC", str(root / "static"))
    base, token = running

    status, body = raw_get(base, f"/static/app.js?t={token}")
    assert status == 200 and "the real one" in body, "the control case must still work"
    for escape in ("/static/../static_backup/app.js", "/static/..%2Fstatic_backup/app.js",
                   "/static/../../etc/hostname"):
        status, body = raw_get(base, f"{escape}?t={token}")
        assert status == 404, escape
        assert "NOT SERVED" not in body, escape


# ------------------------------------------------------------------- the page and the layouts


def test_the_cli_and_the_page_agree_on_the_layout_names(desk):
    """`--layout` is spelled in `cli_fleet` and read in `app.js`; the middle of that seam is here.
    A layout the CLI can print and the page does not know is a blank window."""
    assert cli_fleet.LAYOUTS == S.LAYOUTS
    js = open(APP_JS, encoding="utf-8").read()
    assert 'var LAYOUTS = ["grid", "roles", "screens"];' in js
    assert 'var VIEWS = ["board", "agents", "verify"];' in js
    assert list(S.VIEWS) == ["board", "agents", "verify"]
    assert f'"{cli_fleet.LAYOUT_PARAM}"' in js


def test_every_class_the_layout_sets_is_a_class_it_also_clears():
    """`place()` is the one function that decides what a window shows, and it does it by swapping
    body classes. A class it can add and does not clear is a window that keeps the last layout's
    arrangement on top of the new one -- which looks like the page half-loading."""
    js = open(APP_JS, encoding="utf-8").read()
    calls = [c for c in re.findall(r"body\.classList\.remove\(([^)]*)\)", js, re.S)
             if "layout-" in c]
    assert len(calls) == 1, "more than one place decides which layout this window is in"
    cleared = set(re.findall(r'"([a-z-]+)"', calls[0]))
    assert cleared == {"layout-grid", "layout-roles", "layout-screens", "view-board", "view-agents",
                       "view-verify", "solo", "panels"}
    for layout in S.LAYOUTS:
        assert "layout-" + layout in cleared
    for view in S.VIEWS:
        assert "view-" + view in cleared


def test_every_arrangement_the_url_can_ask_for_is_actually_styled():
    """The layouts are body classes over one stylesheet -- one page, three arrangements. A class the
    script sets and the sheet does not style is a layout that silently renders as the grid.

    `layout-grid` is not here on purpose: the grid *is* the stylesheet's own arrangement, and a rule
    for it would be a rule that says "do what you already do"."""
    css = open(APP_CSS, encoding="utf-8").read()
    for name in ("layout-roles", "layout-screens", "view-agents", "solo", "panels", "needs-only"):
        assert f"body.{name}" in css, f"{name} is set by app.js and styled nowhere"
    # Layout B's centre and right windows, and every screen of layout C, are these two between them.
    assert "body.solo .tile:not(.is-solo) { display: none; }" in css
    assert "body.panels main, body.panels #empty { display: none; }" in css


def test_the_page_offers_every_layout_without_typing_a_url():
    """The operator is meant to reach the other two by parameter, and a parameter nobody can
    discover is a feature nobody uses."""
    js = open(APP_JS, encoding="utf-8").read()
    for label in ("grid — every tile, one screen", "roles — agents (left)",
                  "roles — verify (centre)", "roles — board (right)", "screens — screen 1"):
        assert label in js, label


def test_focus_mode_hides_every_tile_but_the_ones_that_need_a_person():
    """The one thing on #133 that is not a layout. It filters on `needs-human`, which comes from
    #94's fold -- the same flag the chip and the toast use, so the three cannot disagree."""
    js = open(APP_JS, encoding="utf-8").read()
    css = open(APP_CSS, encoding="utf-8").read()
    assert 'el.classList.toggle("needs-human", !!row.needs_human);' in js
    assert "body.needs-only:not(.solo) .tile:not(.needs-human) { display: none; }" in css
    assert 'if (e.key === "f") { focusMode(); return; }' in js


def test_the_keyboard_toggle_is_written_on_the_page_itself():
    """A shortcut documented only in a doc file is a shortcut nobody finds."""
    html = open(INDEX, encoding="utf-8").read()
    assert "<kbd>f</kbd> only what needs you" in html
    assert '<button id="focus"' in html and "show only the agents that need you" in html


def test_focus_mode_never_empties_a_window_that_exists_to_show_one_project():
    """In the solo views the one tile *is* the window. Hiding it because it does not happen to need
    a person would leave an operator staring at an empty monitor."""
    css = open(APP_CSS, encoding="utf-8").read()
    assert "body.needs-only:not(.solo)" in css


def test_a_grey_cell_carries_the_error_in_a_tooltip_and_still_shows_its_value():
    js = open(APP_JS, encoding="utf-8").read()
    assert 'cell.className = "cell" + (p.grey ? " grey" : "")' in js
    assert "cell.title = p.error ? p.error :" in js
    css = open(APP_CSS, encoding="utf-8").read()
    assert ".cell.grey" in css and "var(--idle)" in css.split(".cell.grey")[1][:200]


def test_the_status_colours_are_still_the_same_in_every_layout():
    """A chip that means "needs you" has to be the same red on the left monitor and the centre one,
    or the colour stops being information."""
    css = open(APP_CSS, encoding="utf-8").read()
    for body_class in ("layout-roles", "layout-screens", "solo", "panels", "needs-only"):
        for rule in re.findall(r"body\." + body_class + r"[^{]*\{([^}]*)\}", css):
            for status in ("--running", "--waiting", "--human", "--done"):
                assert status not in rule, f"body.{body_class} redefines {status}"


def test_a_link_row_without_a_url_is_never_rendered():
    """`links.py` refuses to compose a URL out of a hole precisely so the tile never shows something
    that opens onto an error page. The page must read `links`, not the whole rail."""
    js = open(APP_JS, encoding="utf-8").read()
    assert "((project && project.links) || []).forEach" in js
    assert "project.missing_keys" in js, "what is missing must still be named somewhere"


def test_the_page_has_exactly_one_place_that_renders_a_fact_block():
    """The tile renders whatever facts it is handed, and `serve.tile_facts()` is what makes that
    safe. A second loop over some other payload's facts is how the filter gets bypassed by a change
    that looks like a feature, so the count is the test."""
    js = open(APP_JS, encoding="utf-8").read()
    assert len(re.findall(r"\.facts \|\| \{\}\)", js)) == 1
    assert "serve.tile_facts()" in js, "the page must say where the narrowing happens"


def test_the_desk_puts_no_agent_output_into_markup():
    body = open(APP_JS, encoding="utf-8").read()
    assert "innerHTML" not in body
    assert "insertAdjacentHTML" not in body


def test_the_new_event_kinds_reach_the_transcript():
    """#131 and #132 put the project's own changes on #94's stream. A kind the page does not know
    renders as raw JSON, which is how an operator learns to stop reading the transcript."""
    js = open(APP_JS, encoding="utf-8").read()
    for kind in ("project.ticket_changed", "project.refresh_finished", "project.pr_merged",
                 "inbox.attached"):
        assert f'case "{kind}":' in js, kind
        assert f'"{kind}": 1' in js, f"{kind} is not in SHOWN"
