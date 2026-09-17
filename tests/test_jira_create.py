"""`ad-jira create`: the ticket the agent writes itself, shaped by the project's facts, gated like every write.

Nothing here hard-codes a custom field id. The project knows *Primary Domain*; Jira knows
`customfield_10123` and that it is a select list; the command asks `GET /field` and joins the two,
so a test states the field list the way Jira returns it and asserts what a name resolves to.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import cli_jira as CLI
from agentdata import jira_create as JC
from agentdata.connectors import jira_api as J
from agentdata.fleet import approval
from tests.test_jira_api import FakeOpener, creds


def F(fid, name, type_, items=None, custom=True):
    sch = {"type": type_}
    if items:
        sch["items"] = items
    if custom:
        sch["custom"] = f"com.atlassian.jira.plugin.system.customfieldtypes:{type_}"
    return {"id": fid, "name": name, "custom": custom, "schema": sch}


FIELDS = [F("summary", "Summary", "string", custom=False), F("description", "Description", "string", custom=False),
          F("components", "Components", "array", "component", custom=False), F("labels", "Labels", "array", "string", custom=False),
          F("customfield_10123", "Primary Domain", "option"), F("customfield_10200", "Team", "string"),
          F("customfield_10016", "Story Points", "number"), F("customfield_10300", "Reviewers", "array", "user"),
          F("customfield_10400", "Domains", "array", "option"), F("priority", "Priority", "priority", custom=False)]
ME = {"accountId": "acct-1", "displayName": "Luna Fake"}


# ---------------------------------------------------------------------------------------- facts


def test_facts_give_the_project_its_ticket_shape():
    d = JC.defaults({"jira_project": "RDSD", "jira_issue_type": "Story", "jira_components": "Data Platform, Reporting",
                     "jira_labels": "agent", "jira_fields": "Primary Domain=Data; Team=BI Platform",
                     "jira_parent": "RDSD-100", "jira_assignee": "me"})
    assert d == {"project": "RDSD", "issue_type": "Story", "components": ["Data Platform", "Reporting"],
                 "labels": ["agent"], "fields": {"Primary Domain": "Data", "Team": "BI Platform"},
                 "parent": "RDSD-100", "assignee": "me"}
    assert JC.defaults({}) == {"project": None, "issue_type": "Task", "components": [], "labels": [], "fields": {},
                               "parent": None, "assignee": None}


def test_a_pair_without_an_equals_sign_is_refused_by_name():
    with pytest.raises(JC.CreateError) as e:
        JC.parse_pairs(["Primary Domain"])
    assert "NAME=VALUE" in str(e.value) and "Primary Domain" in str(e.value)
    assert JC.parse_pairs(["Primary Domain=Data", " Team = BI ", ""]) == {"Primary Domain": "Data", "Team": "BI"}
    assert JC.parse_pairs('Primary Domain=Data; Note=a=b') == {"Primary Domain": "Data", "Note": "a=b"}


# --------------------------------------------------------------------------------------- shapes


@pytest.mark.parametrize("name,raw,want", [
    ("Primary Domain", "Data", {"value": "Data"}),
    ("Domains", "Data, Risk", [{"value": "Data"}, {"value": "Risk"}]),
    ("Team", "BI Platform", "BI Platform"),
    ("Story Points", "3", 3),
    ("Story Points", "2.5", 2.5),
    ("Reviewers", "acct-7", [{"accountId": "acct-7"}]),
    ("Priority", "High", {"name": "High"}),
    ("Labels", "a, b", ["a", "b"]),
    ("Primary Domain", '{"id": "10001"}', {"id": "10001"}),        # JSON is trusted as given
])
def test_a_named_field_is_sent_in_the_shape_its_schema_wants(name, raw, want):
    body, resolved = JC.payload(FIELDS, project="RDSD", issue_type="Task", summary="x", fields={name: raw})
    fid = next(f["id"] for f in FIELDS if f["name"] == name)
    assert body["fields"][fid] == want
    assert resolved[0]["field"] == name and resolved[0]["id"] == fid and json.loads(resolved[0]["value"]) == want


def test_the_body_carries_components_labels_parent_and_me_and_the_description_matches_the_api():
    body, _ = JC.payload(FIELDS, project="RDSD", issue_type="Story", summary="  Fix the thing  ", description="why",
                         components=["Data Platform"], labels=["agent"], parent="RDSD-100", assignee="me", me=ME)
    f = body["fields"]
    assert f["project"] == {"key": "RDSD"} and f["issuetype"] == {"name": "Story"} and f["summary"] == "Fix the thing"
    assert f["components"] == [{"name": "Data Platform"}] and f["labels"] == ["agent"] and f["parent"] == {"key": "RDSD-100"}
    assert f["assignee"] == {"accountId": "acct-1"}
    assert f["description"]["type"] == "doc" and f["description"]["content"][0]["content"][0]["text"] == "why"
    body, _ = JC.payload(FIELDS, project="RDSD", issue_type=None, summary="x", description="why", assignee="me",
                         me={"name": "luna"}, cloud=False, api3=False)
    assert body["fields"]["description"] == "why" and body["fields"]["assignee"] == {"name": "luna"}
    assert body["fields"]["issuetype"] == {"name": "Task"}


def test_refusals_happen_before_anything_is_sent():
    with pytest.raises(JC.CreateError) as e:
        JC.payload(FIELDS, project=None, issue_type="Task", summary="x")
    assert "jira_project" in e.value.hint
    with pytest.raises(JC.CreateError) as e:
        JC.payload(FIELDS, project="RDSD", issue_type="Task", summary="  ")
    assert "summary" in str(e.value)
    with pytest.raises(JC.CreateError) as e:
        JC.payload(FIELDS, project="RDSD", issue_type="Task", summary="x", fields={"Primary Domin": "Data"})
    assert "Primary Domin" in str(e.value) and e.value.available == ["Primary Domain"]
    with pytest.raises(JC.CreateError) as e:
        JC.payload(FIELDS, project="RDSD", issue_type="Task", summary="x", fields={"Story Points": "three"})
    assert "number" in str(e.value)
    with pytest.raises(JC.CreateError) as e:
        JC.payload(FIELDS, project="RDSD", issue_type="Task", summary="x", assignee="me", me={})
    assert "whoami" in e.value.hint


# --------------------------------------------------------------------------------------- command


def _run(monkeypatch, capsys, argv, *, flavor=J.CLOUD, created="RDSD-999", cfg=None):
    routes = [("GET /rest/api/3/field", FIELDS), ("GET /rest/api/2/field", FIELDS),
              ("POST /rest/api/3/issue", {"id": "1", "key": created, "self": "x"}),
              ("POST /rest/api/2/issue", {"id": "1", "key": created, "self": "x"})]
    op = FakeOpener(routes)
    j = J.Jira(creds(), flavor, opener=op, sleep=lambda s: None)
    monkeypatch.setattr(CLI, "_client", lambda redetect=False: (cfg if cfg is not None else {}, j, ME))
    rc = CLI.main(argv)
    return rc, capsys.readouterr().out, op


def _posts(op):
    return [json.loads(c[2]) for c in op.calls if c[0].startswith("POST")]


def test_dry_run_resolves_every_field_and_posts_nothing(monkeypatch, capsys):
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "Fix the margin measure",
                                             "--field", "Primary Domain=Data", "--component", "Reporting", "--dry-run"])
    assert rc == 0 and "dry_run: true" in out and "project: RDSD" in out and "issue_type: Task" in out
    assert "Primary Domain,customfield_10123,option," in out and '""value"": ""Data""' in out
    assert "components: Reporting" in out and not _posts(op)


def test_create_posts_once_and_prints_the_key_and_the_link(monkeypatch, capsys):
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "Fix the margin measure",
                                             "--description", "It is off by the tax", "--label", "agent"])
    assert rc == 0 and "key: RDSD-999" in out and "acme.atlassian.net/browse/RDSD-999" in out
    posts = _posts(op)
    assert len(posts) == 1
    f = posts[0]["fields"]
    assert f["summary"] == "Fix the margin measure" and f["labels"] == ["agent"] and f["description"]["type"] == "doc"
    assert "assignee" not in f and "parent" not in f


def test_the_projects_facts_are_the_defaults_and_flags_override_them(monkeypatch, capsys, tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "# Project\n- jira_project: RDSD\n- jira_issue_type: Story\n- jira_components: Data Platform, Reporting\n"
        "- jira_fields: Primary Domain=Data; Team=BI Platform\n- jira_parent: RDSD-100\n- jira_assignee: me\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rc, out, op = _run(monkeypatch, capsys, ["create", "--summary", "From the facts", "--field", "Story Points=3"])
    assert rc == 0, out
    f = _posts(op)[0]["fields"]
    assert f["project"] == {"key": "RDSD"} and f["issuetype"] == {"name": "Story"}
    assert f["components"] == [{"name": "Data Platform"}, {"name": "Reporting"}]
    assert f["customfield_10123"] == {"value": "Data"} and f["customfield_10200"] == "BI Platform"
    assert f["customfield_10016"] == 3 and f["parent"] == {"key": "RDSD-100"} and f["assignee"] == {"accountId": "acct-1"}
    assert 'fields: "Primary Domain,Team,Story Points"' in out

    rc, out, op = _run(monkeypatch, capsys, ["create", "--summary", "Overridden", "--type", "Bug", "--component", "Ops",
                                             "--parent", "none", "--assignee", "none", "--field", "Primary Domain=Risk"])
    f = _posts(op)[0]["fields"]
    assert f["issuetype"] == {"name": "Bug"} and f["components"] == [{"name": "Ops"}]
    assert "parent" not in f and "assignee" not in f and f["customfield_10123"] == {"value": "Risk"}


def test_an_unknown_field_is_refused_with_the_nearest_names_and_no_post(monkeypatch, capsys):
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "x", "--field", "Primary Domin=Data"])
    assert rc == 2 and "ok: false" in out and "Primary Domin" in out and "Primary Domain" in out and not _posts(op)
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "x", "--field", "nonsense"])
    assert rc == 2 and "NAME=VALUE" in out and not _posts(op)
    rc, out, op = _run(monkeypatch, capsys, ["create", "--summary", "x"])
    assert rc == 2 and "jira_project" in out and not _posts(op)


def test_data_center_gets_a_plain_description_and_a_username(monkeypatch, capsys):
    monkeypatch.setattr(CLI, "_client", lambda redetect=False: None)   # replaced inside _run
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "x", "--description", "why",
                                             "--assignee", "luna"], flavor=J.DC_BEARER)
    assert rc == 0
    f = _posts(op)[0]["fields"]
    assert f["description"] == "why" and f["assignee"] == {"name": "luna"}
    assert op.calls[0][0] == "GET /rest/api/2/field"


def test_the_gate_holds_the_post_and_a_denial_never_creates(monkeypatch, capsys):
    seen = {}

    def deny(kind, summary, payload=None, **kw):
        seen.update({"kind": kind, "summary": summary, "payload": payload})
        return approval.Decision(approval.DENIED, id="luna-jira-create-1", reason="not this sprint")

    monkeypatch.setattr(approval, "require", deny)
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "Fix the margin measure"])
    assert rc == 2 and "refused: approval_denied" in out and "not this sprint" in out and not _posts(op)
    assert seen["kind"] == "jira-create" and seen["summary"] == "RDSD: Fix the margin measure"
    assert seen["payload"]["fields"]["summary"] == "Fix the margin measure"      # the operator approves the exact body


def test_jira_answering_without_a_key_is_a_failure_that_says_not_to_create_again(monkeypatch, capsys):
    rc, out, op = _run(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "x"], created="")
    assert rc == 1 and "without a key" in out and "before creating again" in out and len(_posts(op)) == 1
