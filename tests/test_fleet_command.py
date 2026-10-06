"""The Command Center (docs/plan-command-center.md; the operator, 2026-10-06): every open ticket assigned to
the operator that has acceptance criteria and a real description, seated at a free agent of its project,
and all of them started with one press -- then each gates wherever it gates.

Held here: the gate (boundaries and forty words, or never slated), the criteria wherever Jira keeps them
(a pinned field, a section of the description, Given/When/Then), Cloud's and Data Center's text, the
slate's one query and its cache, the seating (one ticket to one free checkout, the rest waiting, in
priority order), and the start (back to back, every refusal its own row's), through the CLI and the route.
"""
from __future__ import annotations
import json
import threading
import urllib.request

import pytest

from agentdata.fleet import adopt, command as CMD, serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_switcher import spawns  # noqa: F401 - fixture
from test_fleet_ink import fleet_home  # noqa: F401 - fixture

STORY = ("The monthly revenue report sums invoices twice when a credit note references the same invoice line. "
         "Finance found the March totals overstated by about two percent. The fix belongs in the invoice batcher, "
         "which should net credit notes against their lines before summing, and the report should show the netted "
         "figure with a footnote.")
CRITERIA = ("Acceptance Criteria\n"
            "- A credit note that references an invoice line reduces that line's amount before the monthly sum.\n"
            "- The March report total matches the finance spreadsheet within one cent.\n"
            "- The report footnote names the number of credit notes netted.")
READY = STORY + "\n\n" + CRITERIA


def ticket(key, description=READY, *, summary="Net credit notes in the revenue report", category="new",
           status="To Do", kind="Story", priority="Medium", criteria_field=None):
    fields = {"summary": summary, "status": {"name": status, "statusCategory": {"key": category}},
              "issuetype": {"name": kind}, "priority": {"name": priority},
              "updated": "2026-10-06T09:00:00.000+0000", "description": description}
    if criteria_field is not None:
        fields["customfield_10042"] = criteria_field
    return {"key": key, "fields": fields}


class FakeJira:
    def __init__(self, issues, fields=None):
        self.issues = issues
        self.listed = fields if fields is not None else [{"id": "customfield_10042", "name": "Acceptance Criteria"}]
        self.searches = []

    def fields(self):
        return self.listed

    def search(self, jql, fields, max_results=5000):
        self.searches.append((jql, tuple(fields)))
        return self.issues


@pytest.fixture(autouse=True)
def nobody_else_working(monkeypatch):
    """No process listing in a test: a checkout is free unless the test says otherwise."""
    monkeypatch.setattr(adopt, "outside", lambda *a, **k: {})


def checkout(tmp_path, name, project="RDSD", *, active="", phase="idle"):
    path = make_project(tmp_path / name, project=project, phase=phase, ticket=active)
    Registry().add(path, name=name)
    return path


# ------------------------------------------------------------------------------- the gate


def words(n):
    return " ".join(f"word{i}" for i in range(n))


@pytest.mark.parametrize("description,ok,why", [
    (READY, True, ""),
    (STORY + "\nAC: 1) totals match the spreadsheet 2) the footnote counts the credit notes", True, ""),
    (STORY + "\n\n## Definition of Done\nThe report is netted and the footnote is shown.", True, ""),
    (STORY + "\nGiven a credit note on an invoice line\nWhen the month is summed\nThen the line is netted", True, ""),
    (STORY + "\n- check the batcher\n- check the report", False, "no acceptance criteria"),
    ("## Background\n\n## Steps\n\n## Notes\n\n" + CRITERIA, False, "a template's headings"),
    ("TBD - as discussed, details to follow.\n" + CRITERIA, False, "words of description once"),
    ("Net credit notes in the revenue report\n" + CRITERIA, False, "the summary over again"),
    ("", False, "no description"),
    (words(39) + "\n" + CRITERIA, False, "39 words of description"),
    (words(40) + "\n" + CRITERIA, True, ""),
])
def test_the_gate_lets_through_only_tickets_with_boundaries_and_a_real_description(description, ok, why):
    """The operator: "only ... tickets that have Acceptance Criteria / Done state's so that an agent can have
    boundaries ... never ... short/generic descriptions or no descriptions at all", and forty words."""
    got = CMD.ready({"summary": "Net credit notes in the revenue report", "description": description})
    assert got["ready"] is ok, got
    if why:
        assert any(why in r for r in got["reasons"]), got["reasons"]
    else:
        assert got["reasons"] == [] and got["criteria"], got


def test_two_stray_bullets_are_not_criteria_but_an_inline_list_is():
    assert CMD.criteria("Some prose.\n- one thing\n- another thing")["items"] == []
    assert CMD.criteria("AC: 1) totals match 2) the footnote counts")["items"] == ["totals match", "the footnote counts"]


def test_criteria_come_from_the_pinned_field_before_the_description():
    """The operator chose both: the criteria field when the instance has one, the description otherwise."""
    got = CMD.ready({"summary": "s", "description": STORY, "criteria": "- totals match\n- the footnote shows"})
    assert got["ready"] and got["source"] == "field" and got["criteria"] == ["totals match", "the footnote shows"], got
    got = CMD.ready({"summary": "s", "description": READY, "criteria": ""})
    assert got["source"] == "section" and len(got["criteria"]) == 3, got


def test_clouds_document_format_and_data_centers_wiki_markup_read_as_plain_lines():
    adf = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Net the credit notes."}]},
        {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Acceptance Criteria"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "totals match"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "the footnote shows"}]},
                                              {"type": "bulletList", "content": [{"type": "listItem", "content": [
                                                  {"type": "paragraph", "content": [{"type": "text", "text": "with a count"}]}]}]}]}]},
        {"type": "taskList", "content": [{"type": "taskItem", "attrs": {"state": "TODO"},
                                          "content": [{"type": "text", "text": "a test proves it"}]}]}]}
    assert CMD.plain_text(adf).split("\n") == ["Net the credit notes.", "# Acceptance Criteria", "- totals match",
                                               "- the footnote shows", "  - with a count", "- [ ] a test proves it"]
    assert CMD.criteria(CMD.plain_text(adf))["items"][:2] == ["totals match", "the footnote shows"]
    wiki = "Net the credit notes.\nh3. Acceptance Criteria\n* totals match\n** with a count\n# the footnote shows"
    assert CMD.plain_text(wiki).split("\n") == ["Net the credit notes.", "# Acceptance Criteria", "- totals match",
                                                "  - with a count", "- the footnote shows"]


# ------------------------------------------------------------------------------- the slate


def test_the_slate_asks_once_for_descriptions_and_the_criteria_field_and_keeps_it(fleet_home):
    """The board's query, with the description and the instance's Acceptance Criteria field (found by its
    name when none is pinned), cached for the board's time; pinning a field is a new query."""
    jira = FakeJira([ticket("RDSD-1", STORY, criteria_field="- totals match")])
    got = CMD.slate(client=jira, now=1000.0)
    assert len(jira.searches) == 1 and "description" in jira.searches[0][1] and "customfield_10042" in jira.searches[0][1]
    assert got["rows"][0]["description"] == STORY and got["rows"][0]["criteria"] == "- totals match"
    again = CMD.slate(client=jira, now=1010.0)
    assert again["cached"] and len(jira.searches) == 1
    cfg = {"fleet": {"command": {"criteria_field": "customfield_77"}}}
    CMD.slate(cfg=cfg, client=jira, now=1020.0)
    assert len(jira.searches) == 2 and "customfield_77" in jira.searches[1][1], jira.searches


# ------------------------------------------------------------------------------- the seating


def test_ready_tickets_are_seated_one_to_a_free_checkout_and_the_rest_wait(fleet_home, tmp_path):
    """One ticket to each free checkout of its project, highest priority first; the others wait for a
    desk. A ticket a checkout already holds, one in progress, an epic, one not ready and one whose project
    has no checkout each say why they are not slated."""
    checkout(tmp_path, "rdsd-a")
    checkout(tmp_path, "rdsd-b")
    checkout(tmp_path, "rdsd-busy", active="RDSD-9", phase="building")
    jira = FakeJira([
        ticket("RDSD-1", priority="Low"), ticket("RDSD-2", priority="High"), ticket("RDSD-3", priority="Medium"),
        ticket("RDSD-4", "too short\n" + CRITERIA), ticket("RDSD-5", category="indeterminate", status="In Progress"),
        ticket("RDSD-6", kind="Epic"), ticket("RDSD-9"), ticket("DATA-1"),
    ])
    p = CMD.plan(client=jira)
    rows = {r["key"]: r for r in p["rows"]}
    assert [r["key"] for r in p["rows"] if r["verdict"] == "ready"] == ["RDSD-2", "RDSD-3"], p["rows"]
    assert {rows["RDSD-2"]["repo"], rows["RDSD-3"]["repo"]} == {"rdsd-a", "rdsd-b"}
    assert rows["RDSD-1"]["verdict"] == "waiting" and "waiting for a desk" in rows["RDSD-1"]["reasons"][0]
    assert rows["RDSD-4"]["verdict"] == "not_ready" and not rows["RDSD-4"]["ticked"]
    assert rows["RDSD-5"]["verdict"] == "in_progress" and rows["RDSD-6"]["verdict"] == "not_work"
    assert rows["RDSD-9"]["verdict"] == "held" and rows["RDSD-9"]["repo"] == "rdsd-busy"
    assert rows["DATA-1"]["verdict"] == "no_checkout"
    assert p["ticked"] == p["premium_turns"] == 2 and len(p["plan_id"]) == 12


# ------------------------------------------------------------------------------- the start


def test_one_press_starts_every_ticked_ticket_and_a_refusal_is_its_own_rows(fleet_home, tmp_path, spawns):
    """The ticked pairs start back to back. A plan that moved is refused whole; a ticket the gate refuses,
    or a seat that is not its, is refused alone, and the others start regardless."""
    checkout(tmp_path, "rdsd-a")
    checkout(tmp_path, "rdsd-b")
    jira = FakeJira([ticket("RDSD-1", priority="High"), ticket("RDSD-2"), ticket("RDSD-4", "too short\n" + CRITERIA)])
    p = CMD.plan(client=jira, now=1000.0)
    with pytest.raises(CMD.CommandRefused) as e:
        CMD.run("000000000000", [{"key": "RDSD-1", "repo": "rdsd-a"}], client=jira, now=1001.0)
    assert e.value.code == "plan_changed"
    seated = {r["key"]: r["repo"] for r in p["rows"] if r["ticked"]}
    out = CMD.run(p["plan_id"], [{"key": "RDSD-1", "repo": seated["RDSD-1"]},
                                 {"key": "RDSD-4", "repo": "rdsd-b"},
                                 {"key": "RDSD-2", "repo": seated["RDSD-1"]}], client=jira, now=1002.0)
    done = {r["key"]: r for r in out["rows"]}
    assert done["RDSD-1"]["done"] == "started" and out["started"] == 1, out
    assert done["RDSD-4"]["code"] == "not_ready" and done["RDSD-2"]["code"] == "seat_taken", out
    assert [argv for argv in spawns["launched"] if any("RDSD-1" in a for a in argv)], spawns["launched"]
    assert supervisor.read_lock(seated["RDSD-1"])["ticket"] == "RDSD-1"


def test_the_route_and_the_cli_preview_and_start_the_same_plan(fleet_home, tmp_path, spawns, monkeypatch, capsys):
    from agentdata import cli_fleet

    checkout(tmp_path, "rdsd-a")
    jira = FakeJira([ticket("RDSD-1")])
    monkeypatch.setattr(CMD, "_client", lambda: jira)
    assert cli_fleet.main(["command", "--dry-run"]) == 0
    shown = capsys.readouterr().out
    assert "RDSD-1" in shown and "ready" in shown and "--confirm" in shown, shown
    assert cli_fleet.main(["command"]) == 2, "a press without a preview's id starts nothing"
    capsys.readouterr()

    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port = server.server_address[1]

    def post(body):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/command?t={token}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as answer:
                return json.loads(answer.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    try:
        preview = post({"dry_run": True})
        assert preview["ok"] and preview["rows"][0]["verdict"] == "ready", preview
        refused = post({"plan_id": "", "start": []})
        assert not refused["ok"] and refused["code"] == "preview_first", refused
        started = post({"plan_id": preview["plan_id"], "start": [{"key": "RDSD-1", "repo": "rdsd-a"}]})
        assert started["ok"] and started["started"] == 1, started
        assert started["rows"][0]["row"]["repo"] == "rdsd-a", started["rows"][0]
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.fixture()
def browser(desk_browser):
    return desk_browser


@pytest.mark.browser
def test_the_day_menus_command_center_previews_ticks_only_ready_tickets_and_starts_them(fleet_home, tmp_path,
                                                                                         browser, spawns, monkeypatch):
    """The desk's way in: *day* → *command center…* holds the day strip with a row a ticket. Only a ready
    one has a tick; a thin one says why; *start 1* starts its agent, and its row says so."""
    checkout(tmp_path, "rdsd-a")
    jira = FakeJira([ticket("RDSD-1", priority="High"), ticket("RDSD-2", "too short\n" + CRITERIA)])
    monkeypatch.setattr(CMD, "_client", lambda: jira)
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port = server.server_address[1]
    try:
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
        page.wait_for_function("() => document.querySelectorAll('#grid .tile').length > 0", timeout=15000)
        page.click("#daybtn")
        page.click("#daycommand")
        page.wait_for_function("() => document.querySelectorAll('#day-strip .command-row:not(.day-pattern)').length === 2",
                               timeout=15000)
        rows = page.evaluate("""() => [...document.querySelectorAll('#day-strip .command-row:not(.day-pattern)')].map(li => ({
            key: li.dataset.rowkey, verdict: li.querySelector('.day-verdict').textContent,
            ticked: li.querySelector('.day-tick').checked, disabled: li.querySelector('.day-tick').disabled,
            why: li.querySelector('.day-why').textContent }))""")
        by = {r["key"]: r for r in rows}
        assert by["RDSD-1"]["verdict"] == "ready" and by["RDSD-1"]["ticked"], rows
        assert by["RDSD-2"]["disabled"] and "words of description" in by["RDSD-2"]["why"], rows
        assert page.text_content("#daygo") == "start 1 — about 1 premium turn"
        with page.expect_request(lambda r: r.url.split("?")[0].endswith("/api/command") and "plan_id" in (r.post_data or "")) as sent:
            page.click("#daygo")
        assert sent.value.post_data_json["start"] == [{"key": "RDSD-1", "repo": "rdsd-a"}], sent.value.post_data_json
        page.wait_for_function("""() => document.querySelector('#day-strip .command-row[data-rowkey="RDSD-1"] .day-verdict')
                                   .textContent === 'started'""", timeout=15000)
        assert supervisor.read_lock("rdsd-a")["ticket"] == "RDSD-1"
        page.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
