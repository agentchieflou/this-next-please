"""One-prompt Jira-vs-warehouse UAT: the SQL nobody has to write, and the nine steps in one call.

The thing worth testing hardest is the generated SQL, because it is the part that used to be
hand-authored on every ticket and the part where the three engines genuinely disagree. So every
query this module can emit is run through the *real* `ad-sql-check`, for the engine it was built
for — a generator whose output its own project would refuse is worse than no generator, since it
moves the failure to the warehouse where the message belongs to somebody else.
"""
from __future__ import annotations
import os

import pytest

from agentdata.model import AgentTable
from agentdata.sqlcheck import check as sql_check
from agentdata.uat import jira_sql as Q
from agentdata.uat import jira_vs_source as JV

FACTS = {"jira_project": "RDSD", "jira_hist_table": "EDW.JIRA_ISSUE_HIST",
         "teradata_env": "prod", "hive_env": "lake", "impala_env": "lake", "oracle_env": "ora"}


# --------------------------------------------------------------------------- the generated SQL


@pytest.mark.parametrize("dialect", Q.DIALECTS)
def test_every_dialect_gets_sql_its_own_linter_accepts(dialect):
    """The whole point of generating it. `ad-sql-check` is the same linter the query commands run,
    and it knows things about these engines that a person writing SQL at speed does not."""
    for sql in (Q.history_sql(dialect=dialect, hist_table="EDW.H", project="RDSD",
                              end="2026-01-31", ticket="RDSD-1"),
                Q.coverage_sql(dialect=dialect, hist_table="EDW.H", project="RDSD",
                               end="2026-01-31", ticket="RDSD-1")):
        errors = [f"{f.rule}: {f.message}" for f in sql_check(sql, dialect, {}) if f.severity == "error"]
        assert not errors, f"{dialect}: {errors}"


@pytest.mark.parametrize("dialect,expected", [
    ("teradata", True), ("oracle", True),      # both have QUALIFY
    ("hive", False),                           # only from 4.0, so never -- the subquery is always right
    ("impala", False),                         # no QUALIFY at all
])
def test_the_shape_changes_with_the_engine_not_just_the_quoting(dialect, expected):
    """A generator that emitted one SQL and let the linter complain would have moved the
    hand-authoring rather than removed it."""
    sql = Q.history_sql(dialect=dialect, hist_table="EDW.H", project="RDSD", end="2026-01-31",
                        ticket="RDSD-1")
    assert ("QUALIFY" in sql) is expected, sql
    if not expected:
        assert "ROW_NUMBER() OVER" in sql and "rn = 1" in sql, "no windowed fallback"


@pytest.mark.parametrize("dialect,quote", [
    ("hive", "`"), ("impala", "`"), ("teradata", '"'), ("oracle", '"'),
])
def test_the_key_alias_is_quoted_the_way_the_engine_quotes_identifiers(dialect, quote):
    """Double quotes are *string literals* in Hive and Impala, so `AS "key"` there names the column
    after a constant. `ad-sql-check`'s `hive_double_quotes` rule caught this in the generator's own
    first output, which is why the generated SQL is linted on the way out rather than trusted."""
    sql = Q.history_sql(dialect=dialect, hist_table="EDW.H", project="RDSD", end="2026-01-31",
                        ticket="RDSD-1")
    assert f"AS {quote}key{quote}" in sql, sql


def test_oracle_gets_its_own_timestamp_literal():
    """Oracle has no `TIMESTAMP '...'` in the spelling the others share. Getting it wrong is a
    runtime error on the warehouse, which is the worst place to find out."""
    sql = Q.history_sql(dialect="oracle", hist_table="EDW.H", project="RDSD", end="2026-01-31",
                        ticket="RDSD-1")
    assert "TO_TIMESTAMP('2026-01-31 23:59:59'" in sql
    assert "TIMESTAMP '2026-01-31" not in sql


def test_the_grain_is_one_row_per_key_at_the_window_end():
    """The live side has one row per key. Any other grain makes `ad-diff --key key` compare
    something to nothing."""
    sql = Q.history_sql(dialect="teradata", hist_table="EDW.H", project="RDSD", end="2026-01-31",
                        ticket="RDSD-1")
    assert "PARTITION BY h.ISSUE_KEY" in sql and "ORDER BY h.CHANGED_TS DESC" in sql
    assert "<= TIMESTAMP '2026-01-31 23:59:59'" in sql


def test_the_columns_compared_are_the_ones_asked_for():
    sql = Q.history_sql(dialect="teradata", hist_table="EDW.H", project="RDSD", end="2026-01-31",
                        ticket="RDSD-1", columns=["status", "priority", "assignee"])
    for column in ("status", "priority", "assignee"):
        assert f"h.{column} AS {column}" in sql


def test_the_table_and_column_names_are_configurable_because_no_two_warehouses_agree():
    sql = Q.history_sql(dialect="teradata", hist_table="LAKE.JIRA_SNAP", project="RDSD",
                        end="2026-01-31", ticket="RDSD-1", key_column="JIRA_KEY",
                        ts_column="LOAD_TS", project_column="PROJ")
    assert "FROM   LAKE.JIRA_SNAP h" in sql
    assert "h.PROJ = 'RDSD'" in sql and "h.LOAD_TS <=" in sql


# ------------------------------------------------------------------- it will not build bad SQL


@pytest.mark.parametrize("bad", ["EDW.H; DROP TABLE X", "EDW.H WHERE 1=1", "", "h'x", "EDW..H"])
def test_a_table_name_that_is_not_an_identifier_is_refused_not_quoted(bad):
    """Everything here is a project fact. A value that is not an identifier means the fact is
    wrong, and quoting it would build a query that fails later with a worse message."""
    with pytest.raises(Q.SqlError) as e:
        Q.history_sql(dialect="teradata", hist_table=bad, project="RDSD", end="2026-01-31",
                      ticket="RDSD-1")
    assert "identifier" in e.value.msg
    assert "AGENTS.md" in e.value.hint


@pytest.mark.parametrize("bad", ["RD'SD", "RDSD; DELETE", "RDSD--x"])
def test_a_literal_that_could_end_its_own_quote_is_refused(bad):
    """Not an escaping function on purpose: an escaper here would be the one place in this
    repository that builds SQL out of arbitrary text."""
    with pytest.raises(Q.SqlError):
        Q.history_sql(dialect="teradata", hist_table="EDW.H", project=bad, end="2026-01-31",
                      ticket="RDSD-1")


def test_an_unknown_engine_names_the_ones_that_exist():
    with pytest.raises(Q.SqlError) as e:
        Q.history_sql(dialect="postgres", hist_table="EDW.H", project="RDSD", end="2026-01-31",
                      ticket="RDSD-1")
    assert "teradata" in e.value.hint and "impala" in e.value.hint


def test_no_generated_query_can_write():
    """`ad-sql-check`'s read-only guardrail, on the generator's own output, for every engine."""
    for dialect in Q.DIALECTS:
        sql = Q.history_sql(dialect=dialect, hist_table="EDW.H", project="RDSD", end="2026-01-31",
                            ticket="RDSD-1")
        assert sql.strip().upper().startswith("--") or sql.strip().upper().startswith("SELECT")
        for forbidden in ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "TRUNCATE"):
            assert forbidden not in sql.upper(), f"{dialect} emitted {forbidden}"


# ------------------------------------------------------------------------- facts and overrides


def test_a_per_source_fact_wins_over_the_generic_one():
    """The same history lands in two warehouses under different names more often than not."""
    facts = {**FACTS, "jira_hist_table_hive": "lake.jira_hist"}
    assert JV.facts_for("hive", facts)["hist_table"] == "lake.jira_hist"
    assert JV.facts_for("teradata", facts)["hist_table"] == "EDW.JIRA_ISSUE_HIST"


def test_a_missing_history_table_says_which_fact_to_add(tmp_path):
    with pytest.raises(JV.UatError) as e:
        JV.write_sql(ticket="RDSD-1", source="hive", end="2026-01-31", fields=["status"],
                     facts={"jira_project": "RDSD"}, sql_dir=str(tmp_path))
    assert "jira_hist_table_hive" in e.value.hint


def test_both_files_are_written_where_the_convention_says(tmp_path):
    written = JV.write_sql(ticket="RDSD-101", source="teradata", end="2026-01-31",
                           fields=["status"], facts=FACTS, sql_dir=str(tmp_path))
    assert written["sql"].endswith("RDSD-101-uat.sql")
    assert written["coverage_sql"].endswith("RDSD-101-uat-cov.sql")
    assert os.path.isfile(written["sql"]) and os.path.isfile(written["coverage_sql"])


# ------------------------------------------------------------------------------ the comparison


def _table(name, columns, rows, truncated=False):
    t = AgentTable(name=name, columns=list(columns), rows=[list(r) for r in rows])
    t.truncated = truncated
    return t


LIVE = _table("live", ["key", "status", "assignee"],
              [["RDSD-1", "Done", "ana"], ["RDSD-2", "In Review", "ben"], ["RDSD-3", "To Do", ""]])


def test_the_three_classes_are_the_ones_the_skill_has_always_defined():
    hist = _table("hist", ["key", "status", "assignee"],
                  [["RDSD-1", "Done", "ana"],          # agrees
                   ["RDSD-2", "In Progress", "ben"],   # changed: lag or mapping
                   ["RDSD-9", "Done", "cat"]])         # only in the warehouse
    got = JV.compare(LIVE, hist, cols=["status", "assignee"])

    assert got["only_live"] == ["RDSD-3"], "missing from the warehouse"
    assert got["only_history"] == ["RDSD-9"], "stale in the warehouse"
    assert [(c["key"], c["col"]) for c in got["changed"]] == [("RDSD-2", "status")]
    assert got["matched"] == 2


def test_blank_and_null_are_the_same_absence():
    """Two sides spell "nobody is assigned" differently, and a diff that called that a change would
    fill the findings file with noise."""
    hist = _table("hist", ["key", "status", "assignee"], [["RDSD-3", "To Do", None]])
    got = JV.compare(_table("live", ["key", "status", "assignee"], [["RDSD-3", "To Do", ""]]), hist,
                     cols=["status", "assignee"])
    assert got["changed"] == []


def test_only_the_columns_present_on_both_sides_are_compared():
    hist = _table("hist", ["key", "status"], [["RDSD-1", "Done"]])
    got = JV.compare(LIVE, hist, cols=["status", "assignee"])
    assert got["compared"] == ["status"]


def test_a_missing_key_column_says_what_the_columns_actually_are():
    with pytest.raises(JV.UatError) as e:
        JV.compare(_table("live", ["issue"], [["RDSD-1"]]), LIVE)
    assert "issue" in e.value.hint


def test_a_lower_casing_warehouse_gets_a_hint_rather_than_a_shrug():
    with pytest.raises(JV.UatError) as e:
        JV.compare(LIVE, _table("hist", ["KEY", "status"], [["RDSD-1", "Done"]]))
    assert "lower-case" in e.value.hint


# ------------------------------------------------------------------------------- truncation


def test_a_truncated_side_invalidates_the_counts_and_says_so():
    """The one check that makes every other number meaningless: past the cut, every key looks
    "missing from the warehouse" and the finding reads as a data problem."""
    warning = JV.truncation_warning(_table("live", ["key"], [["a"]], truncated=True),
                                    _table("hist", ["key"], [["a"]]))
    assert "truncated" in warning and "run it again" in warning


def test_sides_that_differ_wildly_in_size_are_flagged_before_they_are_interpreted():
    live = _table("live", ["key"], [[f"K-{i}"] for i in range(100)])
    hist = _table("hist", ["key"], [[f"K-{i}"] for i in range(50)])
    assert "differ in size" in JV.truncation_warning(live, hist)
    assert JV.truncation_warning(live, _table("hist", ["key"], [[f"K-{i}"] for i in range(99)])) == ""


# --------------------------------------------------------------------------- the findings file


def _findings(result, warning=""):
    return JV.findings_md(ticket="RDSD-101", source="teradata", jql="project = RDSD",
                          window=("2026-01-01", "2026-01-31"), result=result,
                          sql_path=".agent/sql/RDSD-101-uat.sql", warning=warning)


def test_the_findings_file_keeps_the_contract_the_skill_has_always_had():
    """Counts, classification, three examples, a recommendation, under 25 lines. Short because it
    is read rather than skimmed."""
    result = JV.compare(LIVE, _table("hist", ["key", "status", "assignee"],
                                     [["RDSD-1", "Done", "ana"], ["RDSD-2", "In Progress", "ben"],
                                      ["RDSD-9", "Done", "cat"]]), cols=["status", "assignee"])
    body = _findings(result)

    assert len(body.splitlines()) <= JV.FINDINGS_MAX_LINES
    assert "RDSD-101" in body and "2026-01-01" in body and "2026-01-31" in body
    assert "missing from the warehouse" in body and "stale in the warehouse" in body
    assert "## Examples" in body and "## Recommendation" in body
    assert ".agent/sql/RDSD-101-uat.sql" in body, "the query has to be citable"


def test_agreement_is_reported_as_agreement_and_not_as_an_empty_table():
    result = JV.compare(LIVE, LIVE, cols=["status", "assignee"])
    body = _findings(result)
    assert "agree on every key" in body
    assert "## Examples" not in body, "there is nothing to exemplify"


def test_a_truncation_warning_outranks_any_conclusion():
    result = JV.compare(LIVE, LIVE, cols=["status"])
    body = _findings(result, warning="the live side was truncated")
    assert "**the live side was truncated**" in body
    assert "before drawing a conclusion" in body


def test_the_recommendation_names_what_to_check_for_each_class():
    result = JV.compare(LIVE, _table("hist", ["key", "status", "assignee"],
                                     [["RDSD-9", "Done", "cat"]]), cols=["status"])
    body = _findings(result)
    assert "watermark" in body, "missing keys point at the load"
    assert "JQL is narrower" in body, "extra keys point at the scope"


# -------------------------------------------------------------------------------- the one call


def test_the_whole_thing_runs_without_a_warehouse_or_a_jira(tmp_path, monkeypatch):
    """Both sides injected, so what is exercised is the composition: generate, lint, run, diff,
    classify, write."""
    monkeypatch.chdir(tmp_path)

    def jira(jql, fields, max_results):
        assert "project = RDSD" in jql
        return _table("live", ["key", "status"], [["RDSD-1", "Done"], ["RDSD-2", "To Do"]])

    def warehouse(sql, env, max_rows, timeout):
        assert env == "prod" and "QUALIFY" in sql
        return _table("hist", ["key", "status"], [["RDSD-1", "In Review"]])

    got = JV.run(ticket="RDSD-101", source="teradata", jql="project = RDSD",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 jira_client=type("C", (), {"jira_search": staticmethod(jira)}),
                 sql_runner=warehouse)

    assert got["only_live"] == 1 and got["changed"] == 1 and got["only_history"] == 0
    assert os.path.isfile(got["findings"])
    assert "RDSD-2" in open(got["findings"], encoding="utf-8").read()


def test_plan_only_writes_the_sql_and_touches_nothing_else(tmp_path, monkeypatch):
    """For checking the column names against a warehouse nobody here has seen, before spending a
    query on it."""
    monkeypatch.chdir(tmp_path)

    def refuse(*a, **k):
        raise AssertionError("plan-only ran a query")

    got = JV.run(ticket="RDSD-101", source="impala", jql="project = RDSD",
                 window=("2026-01-01", "2026-01-31"), fields=["status"], facts=FACTS,
                 plan_only=True, jira_client=refuse, sql_runner=refuse)
    assert os.path.isfile(got["sql"]), "plan-only did not write the SQL"
    assert "review the column names" in got["next"]
    assert "findings" not in got, "plan-only wrote a findings file"


def test_a_missing_environment_is_named_before_anything_is_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(JV.UatError) as e:
        JV.run(ticket="RDSD-1", source="hive", jql="x", window=("2026-01-01", "2026-01-31"),
               fields=["status"], facts={"jira_project": "RDSD", "jira_hist_table": "EDW.H"})
    assert "hive_env" in e.value.hint


# ------------------------------------------------------------------------------ the skill side


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_skill_covers_every_engine_the_command_does():
    body = open(os.path.join(ROOT, "skills", "uat-jira-vs-source", "SKILL.md"),
                encoding="utf-8").read()
    for engine in ("Teradata", "Hive", "Impala"):
        assert engine in body, f"{engine} is not mentioned"
    assert "ad-uat jira-vs-source" in body
    assert "friction-log" in body and "state-update" in body, "the stops must survive the rewrite"
    assert "Never edit Jira" in body


def test_the_router_sends_both_phrasings_to_it():
    body = open(os.path.join(ROOT, "skills", "router", "SKILL.md"), encoding="utf-8").read()
    row = [ln for ln in body.splitlines() if "uat-jira-vs-source" in ln]
    assert row, "the router has no row for it"
    assert "Teradata" in row[0] and ("Hadoop" in row[0] or "Hive" in row[0])
