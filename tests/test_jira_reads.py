"""`ad-jira search`, `ad-jira get`, `ad-jira comments`: the three reads that were pncli-only, over REST.

They print the columns pncli taught this repo (`connectors/jira_columns.py`, `docs/pncli-parts.md`), so a
skill written against `ad-pncli jira search` keeps its column names; they are reads, so they never touch the
approval gate; and `jira_reads.backend()` is the switch every in-process caller uses: REST when credentials
exist, pncli only when they do not.
"""
from __future__ import annotations

import pytest

from agentdata import cli_jira as CLI
from agentdata.connectors import jira_api as J
from agentdata.connectors import jira_columns as COLS
from agentdata.connectors import jira_reads as R
from agentdata.connectors import pncli
from agentdata.fleet import approval
from tests.fakes import jira as FJ


@pytest.fixture()
def wire(monkeypatch):
    """Point `ad-jira` at a fake instance; the approval gate must never be consulted by a read."""
    def _wire(fake: FJ.FakeJira):
        def detect(creds, cfg=None, redetect=False, **kw):
            return fake.client(**kw), {"displayName": "Luna Fake"}

        monkeypatch.setattr(J, "load_credentials",
                            lambda cfg=None: J.Creds(fake.base_url, FJ.FAKE_EMAIL, FJ.FAKE_TOKEN, "test"))
        monkeypatch.setattr(J, "detect_flavor", detect)
        monkeypatch.setattr(approval, "require", lambda *a, **k: pytest.fail("a read reached the approval gate"))
        return fake
    return _wire


def run(argv, capsys) -> tuple[int, str]:
    rc = CLI.main(argv)
    return rc, capsys.readouterr().out


def test_search_prints_pnclis_columns_for_a_jql(wire, capsys):
    fake = wire(FJ.FakeJira(issues=4))
    rc, out = run(["search", "--jql", "key in (RDSD-1, RDSD-3)"], capsys)
    assert rc == 0, out
    assert "jira[2]{key,status,assignee,priority,updated,summary}" in out
    assert "RDSD-1,Done," in out or "RDSD-1," in out
    assert "Fake issue RDSD-3" in out
    assert fake.count("/search") >= 1 and fake.count("POST") == 0


def test_search_narrows_columns_and_marks_a_wider_result_truncated(wire, capsys):
    wire(FJ.FakeJira(issues=5))
    rc, out = run(["search", "--jql", "project = RDSD", "--fields", "key,status,summary", "--max-results", "2"], capsys)
    assert rc == 0, out
    assert "jira[2]{key,status,summary}" in out and "truncated: true" in out, out
    rc, out = run(["search", "--jql", "project = RDSD", "--fields", "key,status,summary"], capsys)
    assert "jira[5]{key,status,summary}" in out and "truncated: false" in out


def test_get_is_one_row_with_counts_and_plain_text(wire, capsys):
    fake = wire(FJ.FakeJira(issues=2))
    fake.client().add_comment("RDSD-2", "a human already answered")
    rc, out = run(["get", "RDSD-2"], capsys)
    assert rc == 0, out
    assert f"cols: {len(R.ISSUE_COLUMNS)}" in out and "summary: Fake issue RDSD-2" in out and "issuetype: Story" in out
    assert "comments: 0" in out and "attachment: 0" in out and "description:" in out      # one row renders as key: value
    rc, out = run(["get", "RDSD-2", "--fields", "key,status,summary"], capsys)
    assert "cols: 3" in out and "status:" in out and "issuetype" not in out


def test_comments_are_oldest_first_as_plain_text(wire, capsys):
    fake = wire(FJ.FakeJira(issues=2))
    c = fake.client()
    c.add_comment("RDSD-1", "first")
    c.add_comment("RDSD-1", "second <with> & markup")
    rc, out = run(["comments", "RDSD-1"], capsys)
    assert rc == 0, out
    assert "comments[2]{id,author,created,updated,body}" in out
    assert out.index("first") < out.index("second <with> & markup")
    rc, out = run(["comments", "RDSD-2"], capsys)
    assert rc == 0 and "comments[0]" in out


def test_the_columns_are_pnclis(wire):
    """One source for the names: a rename in one backend is a rename in the other."""
    assert pncli.JIRA_RENAME is COLS.JIRA_RENAME and pncli.ISSUE_RENAME is COLS.ISSUE_RENAME
    assert R.ISSUE_COLUMNS[:6] == COLS.rename(COLS.JIRA_DEFAULT_FIELDS, COLS.JIRA_RENAME)
    assert COLS.field_ids(["key", "status", "fields.assignee.displayName", "customfield_1"]) == \
        ["status", "assignee", "customfield_1"]
    fake = wire(FJ.FakeJira(issues=3))
    t = R.jira_search("project = RDSD", ["key", "status"], j=fake.client())
    assert t.columns == ["key", "status"] and len(t.rows) == 3 and t.source.startswith("ad-jira search")
    assert R.text({"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}]}) == "hi"
    assert R.text("plain") == "plain" and R.text(None) == ""


def test_backend_is_rest_when_credentials_exist_and_pncli_otherwise(monkeypatch):
    monkeypatch.setattr(J, "has_credentials", lambda cfg=None: True)
    assert R.backend() is R
    monkeypatch.setattr(J, "has_credentials", lambda cfg=None: False)
    assert R.backend() is pncli
    for name in ("jira_search", "get_issue", "get_comments"):
        assert callable(getattr(R, name)) and callable(getattr(pncli, name))


def test_the_in_process_callers_take_the_rest_path_by_default(monkeypatch, tmp_path):
    """`uat.jira_vs_source.live_side`, `fleet.preflight.fetch_issue` and the UAT plan all point at REST now."""
    from agentdata.fleet import preflight as PF
    from agentdata.uat import jira_vs_source as JV
    from agentdata.model import AgentTable
    seen: list[str] = []
    monkeypatch.setattr(J, "has_credentials", lambda cfg=None: True)
    monkeypatch.setattr(R, "jira_search", lambda jql, fields=None, max_results=500, j=None, cfg=None:
                        seen.append(f"search {jql}") or AgentTable("jira", ["key", *fields[1:]], [], ""))
    monkeypatch.setattr(R, "get_issue", lambda key, fields=None, j=None, cfg=None:
                        seen.append(f"get {key}") or AgentTable("issue", ["key", "description", "comments", "attachment"],
                                                                 [[key, "d", 0, 0]], ""))
    t = JV.live_side("project = RDSD", ["status"])
    assert t.columns == ["key", "status"] and seen == ["search project = RDSD"]
    monkeypatch.setattr(PF, "_cached_issue", lambda *a, **k: None)
    monkeypatch.setattr(PF, "_remember", lambda *a, **k: None)
    got = PF.fetch_issue("RDSD-9", cfg={}, now=1.0)
    assert got["description"] == "d" and seen[-1] == "get RDSD-9"
