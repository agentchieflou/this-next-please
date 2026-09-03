"""Transitions belong to the issue TYPE.

The bug this file guards: `pncli jira <verb> <KEY> "In Review"` was written once, against a Story workflow, and
every Task hit a workflow that has no review state. Nothing here may hard-code a status name -- each test states
a workflow the way Jira returns it and asserts what the same intent resolves to on each type.
"""
import json

import pytest

from agentdata import cli_jira as CLI
from agentdata import config as C
from agentdata import jira_workflow as W
from agentdata.connectors import jira_api as J
from tests.test_jira_api import FakeOpener, creds


def T(tid, name, status, category, fields=None, looped=False):
    t = {"id": tid, "name": name, "to": {"id": f"1{tid}", "name": status, "statusCategory": {"key": category}}}
    if fields:
        t["fields"] = fields
    if looped:
        t["isLooped"] = True
    return t


RESOLUTION = {"resolution": {"required": True, "hasDefaultValue": False, "name": "Resolution"},
              "assignee": {"required": True, "hasDefaultValue": True, "name": "Assignee"}}
# The same project, the same status, two issue types. This is the whole point.
STORY = [T("31", "In Review", "In Review", "indeterminate"),
         T("41", "Done", "Done", "done", RESOLUTION),
         T("11", "Stop Progress", "To Do", "new")]
TASK = [T("21", "Done", "Done", "done"),
        T("11", "Stop Progress", "To Do", "new")]


def test_the_same_intent_resolves_per_type_and_is_refused_rather_than_guessed():
    story, task = W.normalize(STORY), W.normalize(TASK)
    hit, why = W.resolve(story, "review", "Story")
    assert (hit["id"], hit["to_status"], why) == ("31", "In Review", "intent review")
    with pytest.raises(W.WorkflowError) as e:
        W.resolve(task, "review", "Task")
    assert "no review transition on this Task" in str(e.value)
    assert "Stories and Tasks differ" in e.value.hint
    assert [r["to_status"] for r in e.value.available] == ["Done", "To Do"]      # what it CAN do is the answer
    for rows, t in ((story, "Story"), (task, "Task")):                           # done and todo work on both
        assert W.resolve(rows, "done", t)[0]["to_status"] == "Done"
        assert W.resolve(rows, "todo", t)[0]["to_status"] == "To Do"


def test_review_never_falls_back_to_the_only_other_in_progress_transition():
    """A Task in To Do offers exactly one indeterminate transition. Sending "review" there would look like it
    worked and quietly park the ticket in In Progress."""
    rows = W.normalize([T("21", "Start Progress", "In Progress", "indeterminate"), T("31", "Done", "Done", "done")])
    with pytest.raises(W.WorkflowError):
        W.resolve(rows, "review", "Task")
    assert W.resolve(rows, "in-progress", "Task")[1].startswith("intent in-progress")   # this one may


def test_a_workflow_that_spells_the_intent_differently_still_resolves():
    for name, status in [("Submit for Review", "Peer Review"), ("Ready for QA", "Ready for QA"), ("x", "In Test")]:
        rows = W.normalize([T("31", name, status, "indeterminate"), T("41", "Done", "Done", "done")])
        assert W.resolve(rows, "review", "Story")[0]["id"] == "31"
    rows = W.normalize([T("21", "Start Progress", "Doing", "indeterminate"), T("41", "Close Issue", "Closed", "done")])
    assert W.resolve(rows, "done", "Task")[0]["to_status"] == "Closed"
    assert W.resolve(rows, "in-progress", "Task")[0]["to_status"] == "Doing"


@pytest.mark.parametrize("want,expect", [("In Review", "31"), ("in review", "31"), ("Stop Progress", "11"),
                                         ("To Do", "11"), ("Rev", "31"), ("qa", "31"), ("nonsense", None)])
def test_exact_names_beat_intents_and_a_unique_substring_is_the_last_resort(want, expect):
    rows = W.normalize(STORY)
    if expect is None:
        with pytest.raises(W.WorkflowError):
            W.resolve(rows, want, "Story")
    else:
        assert W.resolve(rows, want, "Story")[0]["id"] == expect


def test_ambiguity_is_reported_with_the_candidates_never_broken_by_picking_one():
    rows = W.normalize([T("41", "Ship It", "Shipped", "done"), T("51", "Reject", "Rejected", "done"),
                        T("61", "Duplicate", "Duplicated", "done")])
    with pytest.raises(W.WorkflowError) as e:
        W.resolve(rows, "done", "Bug")
    assert "3 transitions into a done status" in str(e.value)
    for status in ("Shipped", "Rejected", "Duplicated"):
        assert status in e.value.hint
    assert W.resolve(rows, "Rejected", "Bug")[0]["id"] == "51"          # naming one is always allowed


def test_a_pin_wins_and_a_stale_pin_is_refused_not_ignored():
    rows = W.normalize(TASK)
    hit, why = W.resolve(rows, "review", "Task", pinned="Done")         # this org reviews Tasks by closing them
    assert hit["id"] == "21" and "pinned" in why
    with pytest.raises(W.WorkflowError) as e:
        W.resolve(rows, "review", "Task", pinned="In Review")
    assert "stale" in e.value.hint and "jira.workflow.task" in e.value.hint


def test_normalize_names_the_screen_fields_that_would_400_the_post():
    rows = W.normalize(STORY)
    assert rows[1]["requires"] == ["Resolution"]                        # Assignee has a default: not required of us
    assert rows[0]["requires"] == [] and rows[0]["to_id"] == "131"
    assert W.normalize([]) == [] and W.normalize(None) == []


@pytest.mark.parametrize("status,want,already", [
    ("In Review", "In Review", True), ("in review", "review", True), ("Done", "done", True),
    ("In Progress", "review", False), ("To Do", "in-progress", False), ("Done", "todo", False), ("", "done", False)])
def test_rerunning_a_skill_on_a_ticket_already_there_is_not_a_failure(status, want, already):
    assert W.already_there(status, want) is already


def test_type_key_and_field_values():
    assert W.type_key("Sub-task") == W.type_key("Sub task") == "sub-task"
    assert W.type_key("") == "unknown" and W.type_key("Story") == "story"
    assert W.field_value('{"name":"Done"}') == {"name": "Done"} and W.field_value("Done") == "Done"


# ---------- the HTTP client ----------

def _client(routes, flavor=J.CLOUD):
    op = FakeOpener(routes)
    return J.Jira(creds(), flavor, opener=op, sleep=lambda s: None), op


def test_transitions_asks_for_the_screens_and_transition_posts_the_id():
    j, op = _client([("GET /rest/api/3/issue/RDSD-1/transitions*", {"transitions": STORY}),
                     ("POST /rest/api/3/issue/RDSD-1/transitions", {})])
    assert [t["id"] for t in j.transitions("RDSD-1")] == ["31", "41", "11"]
    assert "expand=transitions.fields" in op.calls[0][0]                # without it, `requires` is always empty
    j.transition("RDSD-1", "41", {"resolution": {"name": "Done"}})
    assert json.loads(op.calls[1][2]) == {"transition": {"id": "41"}, "fields": {"resolution": {"name": "Done"}}}


def test_a_comment_is_adf_on_cloud_and_a_string_on_data_center():
    j, op = _client([("POST /rest/api/3/issue/A-1/transitions", {})])
    j.transition("A-1", "31", comment="Documented: https://x")
    body = json.loads(op.calls[0][2])["update"]["comment"][0]["add"]["body"]
    assert body["type"] == "doc" and body["content"][0]["content"][0]["text"] == "Documented: https://x"
    j, op = _client([("POST /rest/api/2/issue/A-1/transitions", {})], flavor=J.DC_BEARER)
    j.transition("A-1", "31", comment="Documented: https://x")
    assert json.loads(op.calls[0][2])["update"]["comment"][0]["add"]["body"] == "Documented: https://x"


# ---------- the command ----------

def _run(monkeypatch, capsys, argv, itype, status, transitions, after=None, cfg=None):
    cfg = cfg if cfg is not None else {}
    issue = {"fields": {"issuetype": {"name": itype}, "status": {"name": status, "statusCategory": {"key": "indeterminate"}}}}
    later = {"fields": {"issuetype": {"name": itype}, "status": {"name": after or status, "statusCategory": {"key": "done"}}}}
    seen = {"n": 0}

    def read(_key, _req):
        seen["n"] += 1
        return issue if seen["n"] == 1 else later

    op = FakeOpener([("GET /rest/api/3/issue/RDSD-1?*", read),
                     ("GET /rest/api/3/issue/RDSD-1/transitions*", {"transitions": transitions}),
                     ("POST /rest/api/3/issue/RDSD-1/transitions", {})])
    j = J.Jira(creds(), J.CLOUD, opener=op, sleep=lambda s: None)
    monkeypatch.setattr(CLI, "_client", lambda redetect=False: (cfg, j, {}))
    rc = CLI.main(argv)
    return rc, capsys.readouterr().out, op, cfg


def test_command_moves_a_story_and_tells_a_task_what_it_can_do_instead(monkeypatch, capsys):
    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], "Story", "In Progress",
                          STORY, after="In Review")
    assert rc == 0 and "ok: true" in out and "transition: 31 In Review" in out and "moved: true" in out
    assert sum(c[0].startswith("POST") for c in op.calls) == 1

    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], "Task", "In Progress", TASK)
    assert rc == 2 and "ok: false" in out and "issue_type: Task" in out
    assert "no review transition on this Task" in out and "Done" in out and "To Do" in out
    assert not any(c[0].startswith("POST") for c in op.calls)          # refused before touching the issue


def test_dry_run_resolves_without_moving_anything(monkeypatch, capsys):
    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review", "--dry-run"],
                          "Story", "In Progress", STORY)
    assert rc == 0 and "dry_run: true" in out and "to: In Review" in out
    assert not any(c[0].startswith("POST") for c in op.calls)


def test_a_transition_screen_is_reported_before_the_post_not_as_a_400(monkeypatch, capsys):
    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "done"], "Story", "In Progress", STORY)
    assert rc == 2 and "requiring Resolution" in out and "--resolution <name>" in out
    assert not any(c[0].startswith("POST") for c in op.calls)
    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "done", "--resolution", "Done"],
                          "Story", "In Progress", STORY, after="Done")
    post = [c for c in op.calls if c[0].startswith("POST")][-1]      # the read-back GET comes after it
    assert rc == 0 and json.loads(post[2])["fields"] == {"resolution": {"name": "Done"}}


def test_an_issue_already_there_is_a_no_op_and_the_pin_is_remembered(monkeypatch, capsys, tmp_path):
    rc, out, op, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], "Story", "In Review", STORY)
    assert rc == 0 and "already: true" in out and len(op.calls) == 1   # not even a transitions lookup

    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    cfg: dict = {}
    rc, out, _, cfg = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review", "--pin"],
                           "Story", "In Progress", STORY, after="In Review", cfg=cfg)
    assert rc == 0 and C.get(cfg, "jira.workflow.story.review") == "In Review"
    rc, out, _, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], "Story", "In Progress",
                         STORY, after="In Review", cfg=cfg)
    assert rc == 0 and "matched: pinned for Story" in out


def test_a_transition_that_did_not_move_the_issue_is_a_failure(monkeypatch, capsys):
    """Jira accepts a POST that a post-function undoes. Only the read-back proves the ticket moved."""
    rc, out, _, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], "Story", "In Progress",
                         STORY, after="In Progress")
    assert rc == 1 and "ok: false" in out and "still 'In Progress'" in out


def test_transitions_lists_what_this_issue_can_do(monkeypatch, capsys):
    rc, out, _, _ = _run(monkeypatch, capsys, ["transitions", "RDSD-1"], "Task", "In Progress", TASK)
    assert rc == 0 and "issue_type: Task" in out and "Done" in out and "To Do" in out
    assert "a Task and a Story in the same project differ" in out


def test_bad_field_syntax_is_named_not_crashed(monkeypatch, capsys):
    rc, out, _, _ = _run(monkeypatch, capsys, ["transition", "RDSD-1", "--to", "done", "--field", "resolution"],
                         "Story", "In Progress", STORY)
    assert rc == 2 and "NAME=VALUE" in out
