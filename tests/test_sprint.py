from datetime import datetime, timedelta, timezone
import pytest
from agentdata.uat import sprint as SP

SPRINT_F, PTS_F = "customfield_10020", ["customfield_10026", "customfield_10016"]
CAT = {"1": "new", "3": "indeterminate", "10001": "done", "to do": "new", "in progress": "indeterminate", "done": "done"}
T0 = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
S = SP.SprintInfo(41, "Sprint 41", "closed", T0, T0 + timedelta(days=14), T0 + timedelta(days=14, hours=2))


def ch(days, field, frm, to, cid=1, hours=0):
    t = T0 + timedelta(days=days, hours=hours)
    return SP.Change(t, cid, field, frm, frm, to, to)


def issue(key="K-1", sprints={41}, points=3.0, status="10001", changes=(), created_days=-30, subtask=False):
    return SP.IssueState(key, "1", subtask, T0 + timedelta(days=created_days), set(sprints), points, status, None, sorted(changes))


def run(*issues, **kw):
    return SP.replay(issues, S, CAT, SPRINT_F, PTS_F, **kw)


def test_value_at_never_changed_and_set_at_creation():
    i = issue(points=5.0, changes=[])
    assert SP.points_at(i, PTS_F, T0) == 5.0 and SP.sprints_at(i, SPRINT_F, T0) == {41}


def test_committed_and_completed_simple():
    i = issue(changes=[ch(-1, SPRINT_F, "", "41"), ch(5, "status", "3", "10001")])
    rows, s = run(i)
    r = rows[0]
    assert r["committed"] and r["completed"] and r["done_at_utc"] == "2026-08-09T09:00:00Z"
    assert s["committed_points"] == 3.0 and s["completed_points"] == 3.0 and s["completed_issues"] == 1


def test_added_mid_sprint():
    i = issue(changes=[ch(2, SPRINT_F, "", "41"), ch(5, "status", "3", "10001")])
    rows, s = run(i)
    assert not rows[0]["committed"] and rows[0]["added_after_start"] and rows[0]["completed"]
    assert s["committed_points"] == 0 and s["completed_points"] == 3.0 and s["added"] == 1


def test_punted_still_committed():
    i = issue(sprints=set(), status="3", changes=[ch(-1, SPRINT_F, "", "41"), ch(5, SPRINT_F, "41", "")])
    rows, s = run(i)
    assert rows[0]["committed"] and rows[0]["punted"] and not rows[0]["completed"] and s["punted"] == 1 and s["committed_points"] == 3.0


def test_re_estimated_credit_modes():
    i = issue(points=5.0, changes=[ch(-1, SPRINT_F, "", "41"), ch(3, PTS_F[0], "3", "5", cid=2), ch(6, "status", "3", "10001", cid=3)])
    rows, s_close = run(i)
    assert rows[0]["points_start"] == 3.0 and rows[0]["points_close"] == 5.0 and rows[0]["re_estimated"]
    assert s_close["committed_points"] == 3.0 and s_close["completed_points"] == 5.0
    _, s_commit = run(i, points_at_mode="commit")
    assert s_commit["completed_points"] == 3.0


def test_estimated_mid_sprint():
    i = issue(points=3.0, changes=[ch(-1, SPRINT_F, "", "41"), ch(2, PTS_F[0], None, "3"), ch(6, "status", "3", "10001")])
    rows, s = run(i)
    assert rows[0]["estimated_mid_sprint"] and s["committed_points"] == 0 and s["completed_points"] == 3.0


def test_reopened_not_completed():
    i = issue(status="3", changes=[ch(-1, SPRINT_F, "", "41"), ch(3, "status", "3", "10001", cid=2), ch(6, "status", "10001", "3", cid=3)])
    rows, s = run(i)
    assert rows[0]["reopened"] and not rows[0]["completed"] and rows[0]["cat_close"] == "indeterminate"


def test_completed_in_another_sprint():
    i = issue(sprints={40, 41}, changes=[ch(-10, SPRINT_F, "", "40"), ch(-5, "status", "3", "10001", cid=2), ch(-1, SPRINT_F, "40", "40, 41", cid=3)])
    rows, s = run(i)
    assert rows[0]["completed_in_another_sprint"] and not rows[0]["completed"] and rows[0]["carried_over"] and s["completed_points"] == 0


def test_event_exactly_at_start_counts_as_committed():
    i = issue(changes=[ch(0, SPRINT_F, "", "41"), ch(5, "status", "3", "10001")])
    rows, _ = run(i)
    assert rows[0]["in_at_start"] and rows[0]["committed"]


def test_mixed_offsets_epoch_and_dc_sprint_strings():
    rows = [{"key": "K-1", "changelog_id": 1, "created_utc": "2026-08-03T09:00:00Z", "field_id": SPRINT_F, "from_id": "", "from_str": "", "to_id": "41", "to_str": "Sprint 41"},
            {"key": "K-1", "changelog_id": 2, "created_utc": "2026-08-10T09:00:00Z", "field_id": "status", "from_id": "3", "from_str": "In Progress", "to_id": "10001", "to_str": "Done"},
            {"key": "OTHER", "changelog_id": 3, "created_utc": "2026-08-10T09:00:00Z", "field_id": "status", "from_id": "3", "to_id": "10001"}]
    issue_json = {"key": "K-1", "id": "1", "fields": {"created": "2026-07-01T00:00:00.000+10:00", "issuetype": {"subtask": False},
                                                       "status": {"id": "10001", "name": "Done"},
                                                       SPRINT_F: ["com.atlassian.greenhopper.service.sprint.Sprint@1a[id=41,rapidViewId=3]"],
                                                       PTS_F[0]: None, PTS_F[1]: "8"}}
    st = SP.build_issue_state(issue_json, rows, SPRINT_F, PTS_F)
    assert st.sprint_ids == {41} and st.points == 8.0 and len(st.changes) == 2
    out, s = SP.replay([st], S, CAT, SPRINT_F, PTS_F)
    assert out[0]["completed"] and s["completed_points"] == 8.0


def test_active_sprint_provisional_and_future_error():
    active = SP.SprintInfo(42, "S42", "active", T0, T0 + timedelta(days=14), None)
    i = issue(sprints={42}, status="3", changes=[ch(-1, SPRINT_F, "", "42")])
    rows, s = SP.replay([i], active, CAT, SPRINT_F, PTS_F, now=T0 + timedelta(days=3))
    assert s["provisional"] and s["close_utc"] == "2026-08-07T09:00:00Z" and rows[0]["committed"]
    with pytest.raises(ValueError):
        SP.replay([i], SP.SprintInfo(43, "S43", "future", None, None, None), CAT, SPRINT_F, PTS_F)


def test_subtasks_excluded_by_default():
    i = issue(subtask=True, changes=[ch(-1, SPRINT_F, "", "41"), ch(5, "status", "3", "10001")])
    rows, s = run(i)
    assert not rows[0]["committed"] and s["subtasks_excluded"] == 1 and s["committed_points"] == 0
    _, s2 = run(i, include_subtasks=True)
    assert s2["committed_points"] == 3.0 and s2["subtasks_excluded"] == 0


def test_untouched_issue_skipped_and_sprintreport_delta():
    other = issue(key="K-9", sprints={40}, changes=[])
    hit = issue(changes=[ch(-1, SPRINT_F, "", "41"), ch(5, "status", "3", "10001")])
    rows, s = run(other, hit)
    assert [r["key"] for r in rows] == ["K-1"]
    rep = {"contents": {"completedIssues": [{"key": "K-1"}, {"key": "K-2"}], "puntedIssues": [], "issueKeysAddedDuringSprint": {},
                        "completedIssuesEstimateSum": {"value": "5"}}}
    d = SP.sprintreport_delta(rep, rows, s)
    assert d["keys_only_in_report"] == ["K-2"] and d["completed_points_delta"] == -2.0


def test_parse_helpers():
    assert SP.parse_sprint_ids("12, 15") == {12, 15} and SP.parse_sprint_ids(None) == set() and SP.parse_sprint_ids([{"id": 3}]) == {3}
    assert SP.parse_points("3.0") == 3.0 and SP.parse_points("") is None and SP.parse_points("x") is None
