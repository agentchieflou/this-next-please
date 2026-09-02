import os, tempfile
from agentdata.model import AgentTable
from agentdata import toon, policy


def test_table_encoding():
    t = toon.table("jira", ["key", "status"], [["RDSD-1", "Open"], ["RDSD-2", "In Progress"]])
    assert t.splitlines()[0] == "jira[2]{key,status}:"
    assert t.splitlines()[2] == "  RDSD-2,In Progress"


def test_quote_when_needed():
    assert toon._v("a,b") == '"a,b"' and toon._v("plain") == "plain" and toon._v(None) == ""


def test_policy_rules(tmp_path, monkeypatch):
    monkeypatch.setattr("agentdata.model.OUT_DIR", str(tmp_path))
    small = AgentTable("t", ["a", "b"], [[1, "x"]] * 5, source="test")
    assert "rule: 4" in policy.render(small)
    med = AgentTable("t", ["a", "b"], [[i, "x"] for i in range(200)], source="test")
    out = policy.render(med)
    assert "rule: 5" in out and "stats:" in out and out.count("\n  ") < 60
    big = AgentTable("t", ["a"], [[i] for i in range(1000)], source="test")
    assert "rule: 6" in policy.render(big)


def test_flatten_records():
    recs = [{"key": "A-1", "fields": {"status": {"name": "Open"}, "labels": ["x", "y"]}}]
    t = AgentTable.from_records(recs)
    assert "fields.status.name" in t.columns and t.rows[0][t.columns.index("fields.labels")] == "x;y"
