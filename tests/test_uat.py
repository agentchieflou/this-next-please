import os, sys
import pytest
from agentdata.model import AgentTable
from agentdata.uat import expect as X
from agentdata.uat import plan as PL
from agentdata.uat import reconcile as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sample.pbip")


def test_expect_csv_and_grain(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("Issue Key,Sprint,Committed Points,Completed Points\nRDSD-1,Sprint 41,\"1,234.5\",3\nRDSD-2,Sprint 41,5,\n", encoding="utf-8-sig")
    t = X.load_expected(str(p))
    assert t.columns == ["issue_key", "sprint", "committed_points", "completed_points"] and t.n == 2
    g = X.infer_grain(t)
    assert g["key"] == "issue_key" and g["metrics"] == ["committed_points", "completed_points"] and g["dims"] == ["sprint"]
    X.coerce_metrics(t, g["metrics"])
    assert t.rows[0][2] == 1234.5 and t.rows[1][3] is None


def test_expect_tsv_md_and_key_detection(tmp_path):
    p = tmp_path / "e.tsv"
    p.write_text("ticket\tpts\nABC-12\t3\nABC-13\t5\n", encoding="utf-8")
    t = X.load_expected(str(p))
    assert t.columns == ["ticket", "pts"] and X.infer_grain(t)["key"] == "ticket"
    m = tmp_path / "doc.md"
    m.write_text("Intro\n\n| Ref | Points |\n|---|---:|\n| XY-1 | 8 |\n| XY-2 | 13 |\n\nText\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    t2 = X.load_expected(str(m))
    assert t2.columns == ["ref", "points"] and t2.rows == [["XY-1", 8], ["XY-2", 13]] and X.infer_grain(t2)["key"] == "ref"
    t3 = X.load_expected(str(m), table_index=1)
    assert t3.columns == ["a", "b"]
    with pytest.raises(X.ExpectError):
        X.load_expected(str(tmp_path / "x.pdf"))


def _t(cols, rows, name):
    return AgentTable(name, cols, rows)


def test_reconcile_classes():
    exp = _t(["key", "pts"], [["K-1", 3], ["K-2", 5], ["K-3", 8], ["K-4", 2], ["K-5", 1], ["K-6", 9], ["K-7", 4]], "expected")
    jira = _t(["key", "pts"], [["K-1", 3], ["K-2", 5], ["K-3", 8], ["K-4", 2], ["K-5", 1], ["K-6", 7]], "jira")
    hist = _t(["key", "pts"], [["K-1", 3], ["K-2", 4], ["K-3", None], ["K-4", 1], ["K-5", 1], ["K-6", 7]], "hist")
    pbi = _t(["key", "pts"], [["K-1", 3], ["K-2", 4], ["K-3", 0], ["K-4", 1], ["K-5", 2], ["K-6", 7]], "pbi")
    cov = _t(["key", "first_ts", "last_ts", "n_rows", "points_null"],
             [["K-1", "2026-08-01", "2026-08-20", 5, 0], ["K-2", "2026-08-01", "2026-08-10", 4, 0], ["K-3", "2026-08-01", "2026-08-20", 2, 2],
              ["K-4", "2026-08-01", "2026-08-20", 6, 0], ["K-5", "2026-08-01", "2026-08-20", 6, 0], ["K-6", "2026-08-01", "2026-08-20", 6, 0]], "cov")
    res = R.reconcile(expected=exp, jira=jira, hist=hist, pbi=pbi, key="key", cols=["pts"], window=("2026-08-04", "2026-08-18"), coverage=cov)
    by_key = {f["key"]: f["class"] for f in res["findings"]}
    assert by_key["K-2"] == "lag" and by_key["K-3"] == "history-gap" and by_key["K-4"] == "mapping-bug"
    assert by_key["K-5"] == "report-bug" and by_key["K-6"] == "expectation-wrong" and by_key["K-7"] == "missing"
    assert "K-1" not in by_key and res["counts"]["ok"] == 1 and res["keys_total"] == 7
    md = R.findings_md(res, "RDSD-99")
    assert md.count("\n") <= 40 and "cannot reproduce live Jira" in md and "## Recommendation" in md and "- K-3 pts" in md and "- K-7" in md


def test_reconcile_without_coverage_and_tolerance():
    jira = _t(["key", "v"], [["A", 10.0]], "jira")
    hist = _t(["key", "v"], [["A", 10.004]], "hist")
    res = R.reconcile(expected=None, jira=jira, hist=hist, pbi=None, key="key", cols=["v"])
    assert res["findings"][0]["class"] == "unexplained"
    res2 = R.reconcile(expected=None, jira=jira, hist=hist, pbi=None, key="key", cols=["v"], tol=0.01)
    assert res2["counts"]["ok"] == 1 and res2["findings"] == []
    with pytest.raises(ValueError):
        R.reconcile(expected=None, jira=jira, hist=None, pbi=None, key="key", cols=["v"])
    with pytest.raises(ValueError):
        R.reconcile(expected=None, jira=jira, hist=hist, pbi=None, key="nope", cols=["v"])


def test_plan_on_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    facts = {"jira_hist_table": "RDSD_DB.JIRA_ISSUE_HISTORY", "jira_project": "RDSD", "jira_board_id": "7"}
    res = PL.build(FIX, "Margin by Year", "RDSD-5", window=("2026-08-04", "2026-08-18"), facts=facts, expected="in/e.csv")
    assert res["group_by"] == ["'Calendar'[Year]"] and res["measures"][0]["name"] == "Margin" and "'Sales'[Quantity]" in res["measures"][0]["deps"]
    assert res["sources"] == ["JIRA_ISSUE_HISTORY"] and res["key_guess"] == "year" and res["metrics"] == ["margin"]
    tiers = [s["tier"] for s in res["steps"]]
    assert tiers == ["expected", "3 pbi", "2 hist", "1 jira", "reconcile"]
    sql = open(res["sql"][0], encoding="utf-8").read()
    assert "RDSD_DB.JIRA_ISSUE_HISTORY" in sql and "QUALIFY ROW_NUMBER()" in sql and "2026-08-18" in sql
    assert "--hist-coverage" in res["steps"][-1]["cmd"] and "--key year" in res["steps"][-1]["cmd"]
    with pytest.raises(LookupError):
        PL.build(FIX, "nope", "T", facts=facts)


def test_cli_reconcile_writes_findings(tmp_path, monkeypatch, capsys):
    from agentdata import cli_uat
    monkeypatch.setattr("agentdata.model.OUT_DIR", str(tmp_path))
    monkeypatch.setattr("agentdata.cli_uat.OUT_DIR", str(tmp_path))
    (tmp_path / "e.tsv").write_text("key\tpts\nK-1\t3\nK-2\t9\n", encoding="utf-8")
    (tmp_path / "j.tsv").write_text("key\tpts\nK-1\t3\nK-2\t5\n", encoding="utf-8")
    (tmp_path / "h.tsv").write_text("key\tpts\nK-1\t3\nK-2\t5\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-uat", "reconcile", "--expected", str(tmp_path / "e.tsv"), "--jira", str(tmp_path / "j.tsv"),
                                      "--hist", str(tmp_path / "h.tsv"), "--key", "key", "--cols", "pts", "--ticket", "RDSD-1"])
    with pytest.raises(SystemExit) as ei:
        cli_uat.main()
    out = capsys.readouterr().out
    assert ei.value.code == 0 and "expectation-wrong: 1" in out and "RDSD-1-uat-findings.md" in out
    assert (tmp_path / "RDSD-1-uat-findings.md").exists()
    (tmp_path / "e.csv").write_text("Key,Pts\nK-1,3\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ad-uat", "expect", str(tmp_path / "e.csv")])
    with pytest.raises(SystemExit) as ei:
        cli_uat.main()
    out = capsys.readouterr().out
    assert ei.value.code == 0 and "grain:" in out and "key: key" in out
