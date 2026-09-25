"""`ad-jira comment`: a progress note on a ticket without moving it (#501).

Today a comment only goes out inside a transition, and skills/confluence-publish step 9 named a pncli verb nobody
has pinned. These tests hold the command to the shape `ad-jira transition` already has: the dry-run reads the issue
and sends nothing, the real run waits on the approval gate inside a fleet, and the POST is never replayed.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from agentdata import cli_jira as CLI
from agentdata.fleet import approval, registry
from tests.fakes import jira as FJ

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(monkeypatch, capsys, argv, *, flavor="cloud", fake=None):
    fake = fake or FJ.FakeJira(issues=3, histories=1, flavor=flavor)
    j = fake.client()
    monkeypatch.setattr(CLI, "_client", lambda redetect=False, a=None: ({}, j, {}))
    rc = CLI.main(argv)
    return rc, capsys.readouterr().out, fake


def _posts(fake):
    return [r for r in fake.requests if r.method == "POST"]


@pytest.fixture()
def outside_fleet(monkeypatch):
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    monkeypatch.delenv(registry.FLEET_DIR_ENV, raising=False)


# --------------------------------------------------------------------------------- the dry-run


def test_a_dry_run_reads_the_issue_prints_what_would_be_posted_and_posts_nothing(monkeypatch, capsys, outside_fleet):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-2", "--body", "Documented: https://x\nsecond line",
                                               "--dry-run"])
    assert rc == 0, out
    assert _posts(fake) == [], "a dry-run wrote to Jira"
    for want in ("ok: true", "key: RDSD-2", "summary: Fake issue RDSD-2", "flavor: cloud", "chars: 33", "lines: 2",
                 "first_line: \"Documented: https://x\"", "dry_run: true"):
        assert want in out, (want, out)
    got = fake.last("/issue/RDSD-2")
    assert got.method == "GET" and set(got.params["fields"].split(",")) == {"summary", "status"}


def test_a_key_jira_does_not_know_fails_in_the_preview_with_no_issue(monkeypatch, capsys, outside_fleet):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-99", "--body", "hello", "--dry-run"])
    assert rc == 2, out
    assert "refused: no_issue" in out and "RDSD-99" in out and "hint:" in out
    assert _posts(fake) == []


# --------------------------------------------------------------------------------- the real run


def test_on_cloud_the_body_is_adf_and_the_url_carries_the_comment_id(monkeypatch, capsys, outside_fleet):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "Documented: https://x"])
    assert rc == 0, out
    posts = _posts(fake)
    assert len(posts) == 1 and posts[0].path == "/rest/api/3/issue/RDSD-1/comment"
    body = posts[0].body["body"]
    assert body["type"] == "doc" and body["content"][0]["content"][0]["text"] == "Documented: https://x"
    cid = fake.comments[-1]["id"]
    assert f"comment_id: \"{cid}\"" in out or f"comment_id: {cid}" in out
    assert f"https://fake.atlassian.net/browse/RDSD-1?focusedCommentId={cid}" in out


def test_on_data_center_the_body_is_the_plain_string(monkeypatch, capsys, outside_fleet):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "Documented: https://x"], flavor="dc")
    assert rc == 0, out
    posts = _posts(fake)
    assert len(posts) == 1 and posts[0].path == "/rest/api/2/issue/RDSD-1/comment"
    assert posts[0].body == {"body": "Documented: https://x"}
    assert f"focusedCommentId={fake.comments[-1]['id']}" in out


def test_a_multi_line_body_file_keeps_its_lines_on_both_flavors(monkeypatch, capsys, outside_fleet, tmp_path):
    f = tmp_path / "note.md"
    f.write_text("End of day\n\n3 commits: a, b, c\nPR none\n", encoding="utf-8")
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body-file", str(f)], flavor="dc")
    assert rc == 0, out
    assert _posts(fake)[0].body == {"body": "End of day\n\n3 commits: a, b, c\nPR none"}
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body-file", str(f)])
    doc = _posts(fake)[0].body["body"]
    texts = [n.get("text") for p in doc["content"] for n in p["content"] if n["type"] == "text"]
    assert texts == ["End of day", "3 commits: a, b, c", "PR none"]


def test_a_failed_post_is_not_sent_twice(monkeypatch, capsys, outside_fleet):
    """A comment POST that times out may well have landed; replaying it posts the note twice."""
    fake = FJ.FakeJira(issues=3, histories=1, faults=[("POST /rest/api/3/issue/RDSD-1/comment", 1, 503)])
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "hello"], fake=fake)
    assert rc == 1, out
    assert len(_posts(fake)) == 1 and fake.comments == []


# --------------------------------------------------------------------------------- refusals


@pytest.mark.parametrize("args, code", [
    (["--body", "   \n  "], "empty_body"),
    (["--body", "x" * 32768], "body_too_long"),
])
def test_an_empty_or_oversized_body_is_refused_before_jira_is_asked(monkeypatch, capsys, outside_fleet, args, code):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", *args, "--dry-run"])
    assert rc == 2, out
    assert f"refused: {code}" in out and "hint:" in out
    assert fake.requests == []


def test_a_body_at_jiras_limit_is_accepted(monkeypatch, capsys, outside_fleet):
    rc, out, _ = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "x" * 32767, "--dry-run"])
    assert rc == 0 and "chars: 32767" in out


def test_body_and_body_file_are_one_or_the_other(monkeypatch, capsys, outside_fleet):
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, capsys, ["comment", "RDSD-1"])
    assert e.value.code == 2


# --------------------------------------------------------------------------------- the gate


@pytest.fixture()
def as_agent(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    return "luna"


def _wait_for_request(timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        waiting = approval.pending()
        if waiting:
            return waiting[0]
        time.sleep(0.02)
    raise AssertionError("no approval request appeared")


def _gated(monkeypatch, capsys, state, reason=""):
    result: dict = {}
    fake = FJ.FakeJira(issues=3, histories=1)

    def agent():
        result["rc"], result["out"], _ = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "Progress: 3 commits"],
                                              fake=fake)

    real_require = approval.require                     # poll fast: the default two seconds is a person's pace
    monkeypatch.setattr(approval, "require", lambda *a, **kw: real_require(*a, **{"poll": 0.02, **kw}))
    t = threading.Thread(target=agent)
    t.start()
    req = _wait_for_request()
    approval.decide(req["id"], state, reason=reason, by="operator")
    t.join(timeout=15)
    return req, result, fake


def test_inside_a_fleet_the_run_asks_once_with_the_body_and_posts_on_approval(as_agent, monkeypatch, capsys):
    req, result, fake = _gated(monkeypatch, capsys, approval.APPROVED)
    assert req["kind"] == "jira-comment" and req["ticket"] == "RDSD-1"
    assert req["payload"] == {"key": "RDSD-1", "body": "Progress: 3 commits"}
    assert req["summary"] == "RDSD-1: comment (19 chars)"
    assert result["rc"] == 0, result["out"]
    assert len(_posts(fake)) == 1
    assert len(approval.history()) == 1


def test_inside_a_fleet_a_deny_posts_nothing(as_agent, monkeypatch, capsys):
    _, result, fake = _gated(monkeypatch, capsys, approval.DENIED, reason="not this ticket")
    assert result["rc"] == 2
    assert "refused: approval_denied" in result["out"] and "not this ticket" in result["out"]
    assert _posts(fake) == [], "a denied comment was posted to Jira anyway"


def test_a_dry_run_inside_a_fleet_asks_for_nothing(as_agent, monkeypatch, capsys):
    rc, out, fake = _run(monkeypatch, capsys, ["comment", "RDSD-1", "--body", "x", "--dry-run"])
    assert rc == 0 and approval.pending() == [] and _posts(fake) == []


# --------------------------------------------------------------------------------- the fake and the docs


def test_the_fake_answers_a_comment_post_in_jiras_shape():
    for flavor, body in (("cloud", {"type": "doc", "version": 1, "content": []}), ("dc", "plain")):
        fake = FJ.FakeJira(issues=2, histories=1, flavor=flavor)
        got = fake.request("POST", f"{fake.api}/issue/RDSD-1/comment", body={"body": body})
        assert {"self", "id", "author", "body", "updateAuthor", "created", "updated"} <= set(got)
        assert got["body"] == body and got["self"].endswith(f"/comment/{got['id']}")
        listed = fake.request("GET", f"{fake.api}/issue/RDSD-1/comment")
        assert listed["total"] == 1 and listed["comments"][0]["id"] == got["id"]


def test_confluence_publish_comments_through_ad_jira_comment_dry_run_first():
    text = open(os.path.join(ROOT, "skills", "confluence-publish", "SKILL.md"), encoding="utf-8").read()
    step = next(line for line in text.splitlines() if line.startswith("9. "))
    assert "ad-jira comment <KEY>" in step and "--dry-run" in step and "<comment verb>" not in step
    gated = open(os.path.join(ROOT, "docs", "fleet-approvals.md"), encoding="utf-8").read()
    assert "`ad-jira comment <KEY>" in gated
    refusals = open(os.path.join(ROOT, "docs", "refusals.md"), encoding="utf-8").read()
    for code in ("empty_body", "body_too_long", "no_issue"):
        assert f"`refused: {code}`" in refusals, code
