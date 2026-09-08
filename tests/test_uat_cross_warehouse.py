"""Three-way UAT: live Jira, two warehouse histories, and whether the two warehouses agree.

The business question is migration parity — *has the move from one platform to the other reproduced
the data* — and it is not the single-engine reconciliation run twice. Two separate runs would each
report "this warehouse disagrees with Jira" and neither would notice that the two warehouses
disagree with **each other**, which is the finding that names the migration rather than the load.
"""
from __future__ import annotations
import os

import pytest

from agentdata.model import AgentTable
from agentdata.uat import jira_vs_source as JV
from agentdata.uat import jira_vs_warehouses as JW
from agentdata.uat import reconcile as R

FACTS = {"jira_project": "RDSD", "jira_hist_table": "EDW.JIRA_HIST",
         "jira_hist_table_hive": "lake.jira_hist",
         "teradata_env": "prod", "hive_env": "lake"}


def _table(name, rows, columns=("key", "status")):
    return AgentTable(name=name, columns=list(columns), rows=[list(r) for r in rows])


# ------------------------------------------------------------------- the class that is new


def test_two_warehouses_that_disagree_are_their_own_finding():
    """Not "hist disagrees with Jira". Naming one platform would hide that the other differs too,
    and the answer to "did the migration work" is the one being asked for."""
    got = R.reconcile(expected=None, jira=_table("jira", [["RDSD-1", "Done"]]),
                      hist=_table("hist", [["RDSD-1", "Done"]]),
                      hist2=_table("hist2", [["RDSD-1", "In Review"]]), hist2_name="hive",
                      pbi=None, key="key", cols=["status"])

    assert got["counts"]["warehouse-drift"] == 1
    finding = [f for f in got["findings"] if f["class"] == "warehouse-drift"][0]
    assert finding["hist"] == "Done" and finding["hist2"] == "In Review"
    assert "hive" in finding["note"], "the second warehouse is named, not called hist2"
    assert "agrees with hist" in finding["note"], "which one Jira backs is the useful half"


def test_drift_is_reported_even_when_neither_warehouse_matches_jira():
    got = R.reconcile(expected=None, jira=_table("jira", [["RDSD-1", "Done"]]),
                      hist=_table("hist", [["RDSD-1", "To Do"]]),
                      hist2=_table("hist2", [["RDSD-1", "In Review"]]), hist2_name="hive",
                      pbi=None, key="key", cols=["status"])
    finding = [f for f in got["findings"] if f["class"] == "warehouse-drift"][0]
    assert "agrees with neither" in finding["note"]


def test_two_warehouses_that_agree_produce_no_drift_and_still_check_jira():
    """Agreeing with each other and both being wrong is a load defect, not a migration one."""
    got = R.reconcile(expected=None, jira=_table("jira", [["RDSD-1", "Done"]]),
                      hist=_table("hist", [["RDSD-1", "To Do"]]),
                      hist2=_table("hist2", [["RDSD-1", "To Do"]]), hist2_name="hive",
                      pbi=None, key="key", cols=["status"],
                      coverage=_table("cov", [["RDSD-1", "2026-01-01", "2026-01-31", 5]],
                                      columns=("key", "first_ts", "last_ts", "n_rows")),
                      window=("2026-01-01", "2026-01-31"))
    assert got["counts"]["warehouse-drift"] == 0
    assert got["counts"]["mapping-bug"] == 1, "both warehouses disagreeing with Jira is the load"


def test_the_new_class_is_registered_everywhere_a_class_has_to_be():
    """A class with no definition or no recommendation renders as a blank in the findings file."""
    assert "warehouse-drift" in R.CLASSES
    assert R.DEFINITION["warehouse-drift"] and R.RECOMMENDATION["warehouse-drift"]
    assert "migration" in R.RECOMMENDATION["warehouse-drift"]


# ------------------------------------------------------------- the existing callers are intact


def test_the_two_tier_caller_is_unchanged():
    got = R.reconcile(expected=None, jira=_table("jira", [["RDSD-1", "Done"]]),
                      hist=_table("hist", [["RDSD-1", "Done"]]), pbi=None,
                      key="key", cols=["status"])
    assert got["counts"]["warehouse-drift"] == 0
    assert got["tiers"] == ["jira", "hist"], "a tier nobody passed must not appear"


def test_the_four_tier_caller_is_unchanged():
    """`uat-report-visual` calls this with expected/jira/hist/pbi and must keep behaving exactly."""
    got = R.reconcile(expected=_table("e", [["RDSD-1", "5"]]), jira=_table("j", [["RDSD-1", "5"]]),
                      hist=_table("h", [["RDSD-1", "5"]]), pbi=_table("p", [["RDSD-1", "9"]]),
                      key="key", cols=["status"])
    assert got["tiers"] == ["expected", "jira", "hist", "pbi"]
    assert got["counts"]["report-bug"] == 1, "pbi disagreeing while hist matches jira is still a report bug"


def test_classify_can_still_be_called_the_old_way():
    """Its signature is positional and widely called; the new tier is defaulted."""
    cls, note, truth = R.classify("RDSD-1", "status", None, "Done", "Done", "Done", None, False, None, 0.0)
    assert cls == "ok"


# ------------------------------------------------------------------------------- the command


def _runners(first_rows, second_rows):
    return {"teradata": lambda sql, env, rows, timeout: _table("t", first_rows),
            "hive": lambda sql, env, rows, timeout: _table("h", second_rows)}


def _jira(rows):
    return type("C", (), {"jira_search": staticmethod(lambda jql, fields, n: _table("j", rows))})


def test_one_call_generates_both_queries_runs_three_sides_and_writes_one_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = JW.run(ticket="RDSD-101", sources=["teradata", "hive"], jql="project = RDSD",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 jira_client=_jira([["RDSD-1", "Done"], ["RDSD-2", "To Do"]]),
                 sql_runners=_runners([["RDSD-1", "Done"], ["RDSD-2", "To Do"]],
                                      [["RDSD-1", "In Review"], ["RDSD-2", "To Do"]]))

    assert got["counts"]["warehouse-drift"] == 1
    assert os.path.isfile(got["findings"])
    assert got["history_rows"] == {"teradata": 2, "hive": 2}


def test_the_two_queries_do_not_overwrite_each_other(tmp_path, monkeypatch):
    """Both files are the point: one per engine, and a shared name would leave one of them."""
    monkeypatch.chdir(tmp_path)
    got = JW.run(ticket="RDSD-101", sources=["teradata", "hive"], jql="x",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 plan_only=True)
    written = sorted(os.listdir(os.path.join(".agent", "sql")))
    assert "RDSD-101-teradata-uat.sql" in written and "RDSD-101-hive-uat.sql" in written

    teradata = open(os.path.join(".agent", "sql", "RDSD-101-teradata-uat.sql"), encoding="utf-8").read()
    hive = open(os.path.join(".agent", "sql", "RDSD-101-hive-uat.sql"), encoding="utf-8").read()
    assert "QUALIFY" in teradata and "QUALIFY" not in hive, "each engine got its own shape"
    assert "lake.jira_hist" in hive and "EDW.JIRA_HIST" in teradata, "each got its own table fact"


def test_the_findings_file_answers_the_migration_question_first(tmp_path, monkeypatch):
    """"Do the two platforms agree" is what was asked. Burying it among the per-warehouse classes
    would mean reading the whole file to find the answer."""
    monkeypatch.chdir(tmp_path)
    got = JW.run(ticket="RDSD-101", sources=["teradata", "hive"], jql="project = RDSD",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 jira_client=_jira([["RDSD-1", "Done"]]),
                 sql_runners=_runners([["RDSD-1", "Done"]], [["RDSD-1", "In Review"]]))

    body = open(got["findings"], encoding="utf-8").read()
    assert "## Do teradata and hive agree?" in body
    assert body.index("Do teradata and hive agree?") < body.index("Against live Jira")
    assert "**No —" in body and "migration finding" in body
    assert "`RDSD-1` status: teradata `Done`, hive `In Review`" in body


def test_agreement_is_stated_plainly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = JW.run(ticket="RDSD-101", sources=["teradata", "hive"], jql="x",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 jira_client=_jira([["RDSD-1", "Done"]]),
                 sql_runners=_runners([["RDSD-1", "Done"]], [["RDSD-1", "Done"]]))
    body = open(got["findings"], encoding="utf-8").read()
    assert "Yes — every compared value is identical" in body


def test_the_findings_file_stays_readable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = [[f"RDSD-{i}", "Done"] for i in range(60)]
    drifted = [[f"RDSD-{i}", "To Do"] for i in range(60)]
    got = JW.run(ticket="RDSD-101", sources=["teradata", "hive"], jql="x",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 jira_client=_jira(rows), sql_runners=_runners(rows, drifted))
    body = open(got["findings"], encoding="utf-8").read()
    assert len(body.splitlines()) <= 40, "a findings file nobody reads is not a finding"
    assert "60 value(s) differ" in body


# ---------------------------------------------------------------------------- what it refuses


@pytest.mark.parametrize("sources,why", [
    ("teradata", "exactly two"),
    ("teradata,hive,impala", "exactly two"),
    ("teradata,teradata", "same engine twice"),
])
def test_it_refuses_anything_but_two_different_engines(sources, why, capsys, tmp_path, monkeypatch):
    from agentdata import cli_uat

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli_uat.main(["jira-vs-warehouses", "--sources", sources, "--ticket", "T-1",
                      "--jql", "x", "--window", "2026-01-01,2026-01-31"])
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert why in out
    if "same" in why:
        assert "jira-vs-source" in out, "one engine has its own command; say so"


def test_an_unknown_engine_is_refused_before_anything_is_generated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(JV.UatError) as e:
        JW.run(ticket="T-1", sources=["teradata", "postgres"], jql="x",
               window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS)
    assert "postgres" in e.value.msg
    assert not os.path.isdir(os.path.join(".agent", "sql")), "it generated before it checked"


# -------------------------------------------------------------------------------- the skill


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_skill_and_router_cover_the_cross_warehouse_case():
    body = open(os.path.join(ROOT, "skills", "uat-jira-vs-warehouses", "SKILL.md"),
                encoding="utf-8").read()
    assert "ad-uat jira-vs-warehouses" in body
    assert "migration" in body.lower() or "parity" in body.lower()
    assert "friction-log" in body and "state-update" in body

    router = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    row = [ln for ln in router.splitlines() if "uat-jira-vs-warehouses" in ln]
    assert row, "the router cannot reach it"
    assert "both" in row[0].lower() or "two" in row[0].lower() or "parity" in row[0].lower()
