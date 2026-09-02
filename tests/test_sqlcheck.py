import os, re, sys
import pytest
from agentdata import policy
from agentdata.sqlcheck import DIALECTS, check, to_toon
from agentdata.sqlcheck import rules as R
from agentdata.sqlcheck.strip import strip

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = {"teradata": "skills/teradata-query/references/teradata-sql.md",
       "hive": "skills/hive-query/references/hive-impala-sql.md",
       "impala": "skills/hive-query/references/hive-impala-sql.md",
       "oracle": "skills/oracle-query/references/oracle-sql.md"}


def ids(sql, dialect, caps=None):
    return [f.rule for f in check(sql, dialect, caps)]


def sev(sql, dialect, caps=None):
    return {f.rule: f.severity for f in check(sql, dialect, caps)}


def test_strip_keeps_lines_and_units():
    s = strip("SELECT 'Done', 'a,b' -- LIMIT 5\n, '' /* x\ny */ FROM t")
    assert "LIMIT" not in s and "'Done'" in s and "'§'" in s and "''" in s and s.count("\n") == 2


def test_comments_and_literals_do_not_trigger():
    assert ids("SELECT a FROM t WHERE x LIKE '%LIMIT 10%' -- LIMIT 10\n/* QUALIFY */", "teradata") == []
    assert ids("SELECT a FROM t WHERE note = 'a || b'", "impala") == []


CANONICAL = {
    "teradata": "SELECT TOP 10 ISSUE_KEY, MOD(n, 2), CAST(SUM(pts) AS DECIMAL(18,4)) / COUNT(*) AS avg_pts\n"
                "FROM DB.T WHERE STATUS = 'Done' AND d >= DATE '2025-01-01' GROUP BY ISSUE_KEY, MOD(n, 2)",
    "hive": "SELECT issue_key, count(*) FROM db.t WHERE dt = '2025-01-31' AND a || b = 'x' GROUP BY issue_key LIMIT 100",
    "impala": "SELECT `key`, concat(a, 'x') FROM db.t WHERE dt = '2025-01-31' LIMIT 100 OFFSET 0",
    "oracle": "SELECT h.issue_key FROM jira_hist h WHERE h.changed_ts >= DATE '2025-01-01' ORDER BY h.changed_ts FETCH FIRST 10 ROWS ONLY",
}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_canonical_queries_have_no_errors(dialect):
    assert [f for f in check(CANONICAL[dialect], dialect, {"tmode": "ANSI", "major": 4}) if f.severity == "error"] == []


def test_teradata_rules():
    assert "td_limit" in ids("SELECT * FROM t LIMIT 10", "teradata")
    assert "td_fetch_first" in ids("SELECT * FROM t FETCH FIRST 10 ROWS ONLY", "teradata")
    assert "td_backtick" in ids("SELECT `a` FROM t", "teradata")
    assert "td_string_type" in ids("SELECT CAST(a AS STRING) FROM t", "teradata")
    assert "td_modulo" in ids("SELECT a % 2 FROM t", "teradata")
    assert "td_top_qualify" in ids("SELECT TOP 5 a FROM t QUALIFY ROW_NUMBER() OVER (ORDER BY a) = 1", "teradata")
    assert "td_top_qualify" not in ids("SELECT TOP 5 a FROM t", "teradata")
    assert "td_hint" in ids("SELECT /*+ FULL(t) */ a FROM t", "teradata")
    assert sev("SELECT 1 FROM DUAL", "teradata")["td_dual"] == "warning"
    assert "td_hive_date_funcs" in ids("SELECT date_add(d, 1) FROM t", "teradata")
    assert sev("SELECT SUM(x)/COUNT(*) FROM t", "teradata")["td_int_division"] == "warning"
    assert "current_date_parens" in ids("SELECT CURRENT_DATE() FROM t", "teradata")


def test_teradata_capability_gates():
    q = "SELECT TRUNC(d, 'MM'), TO_CHAR(d, 'YYYY-MM-DD'), LISTAGG(x, ',') WITHIN GROUP (ORDER BY x) FROM t"
    unknown = sev(q, "teradata", {})
    assert unknown["td_trunc_date"] == "warning" and unknown["td_to_char"] == "warning" and unknown["td_listagg"] == "warning"
    absent = sev(q, "teradata", {"trunc_date": False, "to_char": False, "listagg": False})
    assert absent["td_trunc_date"] == "error" and absent["td_listagg"] == "error"
    assert ids(q, "teradata", {"trunc_date": True, "to_char": True, "listagg": True}) == []
    assert "td_case_insensitive_eq" in ids("SELECT * FROM t WHERE s = 'Done'", "teradata", {"tmode": "TERA"})
    assert "td_case_insensitive_eq" not in ids("SELECT * FROM t WHERE s = 'Done'", "teradata", {"tmode": "ANSI"})


def test_oracle_rules():
    assert ids("SELECT 1", "oracle") == ["ora_fromless_select"]
    assert ids("SELECT 1 FROM DUAL", "oracle") == []
    assert "ora_limit" in ids("SELECT * FROM t LIMIT 5", "oracle")
    assert "ora_top" in ids("SELECT TOP 5 * FROM t", "oracle")
    assert "ora_table_alias_as" in ids("SELECT x.a FROM t AS x", "oracle")
    assert "ora_table_alias_as" not in ids("SELECT x.a AS b FROM t x", "oracle")
    assert sev("SELECT * FROM t WHERE ROWNUM <= 5 ORDER BY a", "oracle")["ora_rownum_orderby"] == "warning"
    assert sev("SELECT * FROM t WHERE a = ''", "oracle")["ora_empty_string_eq"] == "warning"
    assert "ora_empty_string_eq" not in ids("SELECT * FROM t WHERE a = 'x'", "oracle")
    assert sev("SELECT * FROM t GROUP BY 1", "oracle")["group_by_ordinal"] == "error"
    assert sev("SELECT * FROM t GROUP BY 1", "teradata")["group_by_ordinal"] == "warning"
    assert "ora_null_funcs" in ids("SELECT IFNULL(a, 0) FROM t", "oracle")
    assert sev("SELECT * FROM t WHERE created_date >= '2025-01-01'", "oracle")["ora_date_string_compare"] == "warning"
    assert "ora_backtick" in ids("SELECT `a` FROM t", "oracle")


def test_hive_and_impala_rules():
    q = "SELECT * FROM t QUALIFY row_number() OVER (ORDER BY a) = 1"
    assert sev(q, "hive", {"major": 3})["hive_qualify"] == "error"
    assert sev(q, "hive", {})["hive_qualify"] == "warning" and "capability unknown" in check(q, "hive", {})[0].message
    assert ids(q, "hive", {"major": 4}) == []
    assert sev(q, "impala")["imp_qualify"] == "error"
    assert "hive_top" in ids("SELECT TOP 5 * FROM t", "hive") and "hive_fetch_first" in ids("SELECT * FROM t FETCH FIRST 5 ROWS ONLY", "impala")
    assert "hive_sample" in ids("SELECT * FROM t SAMPLE 10", "hive")
    assert "hive_limit_nonliteral" in ids("SELECT * FROM t LIMIT n", "hive") and "hive_limit_nonliteral" not in ids("SELECT * FROM t LIMIT 10", "hive")
    assert sev('SELECT "a" FROM t', "hive")["hive_double_quotes"] == "warning"
    assert "hive_sysdate" in ids("SELECT SYSDATE FROM t", "impala")
    assert "hive_to_char" in ids("SELECT TO_CHAR(d, 'YYYY') FROM t", "hive")
    assert "hive_to_date_fmt" in ids("SELECT TO_DATE(s, 'yyyy-MM-dd') FROM t", "hive") and "hive_to_date_fmt" not in ids("SELECT to_date(ts) FROM t", "hive")
    assert "hive_trunc_unit" in ids("SELECT trunc(d, 'DD') FROM t", "hive") and "hive_trunc_unit" not in ids("SELECT trunc(d, 'MM') FROM t", "hive")
    assert sev("SELECT NVL(a, b, c) FROM t", "hive")["hive_nvl_nary"] == "warning" and sev("SELECT NVL(a, b, c) FROM t", "impala")["imp_nvl_nary"] == "error"
    assert "hive_nvl_nary" not in ids("SELECT NVL(a, b) FROM t", "hive")
    assert "hive_listagg" in ids("SELECT LISTAGG(a, ',') FROM t", "impala") and "hive_rownum" in ids("SELECT * FROM t WHERE ROWNUM < 5", "hive")
    assert "imp_concat_pipes" in ids("SELECT a || b FROM t", "impala") and "imp_concat_pipes" not in ids("SELECT a || b FROM t", "hive")
    assert "imp_lateral_view" in ids("SELECT x FROM t LATERAL VIEW explode(arr) e AS x", "impala")
    assert "imp_collect" in ids("SELECT collect_list(a) FROM t", "impala") and "imp_date_format" in ids("SELECT date_format(d, 'yyyy') FROM t", "impala")
    assert "imp_date_trunc_order" in ids("SELECT DATE_TRUNC(ts, 'MM') FROM t", "impala") and "imp_date_trunc_order" not in ids("SELECT DATE_TRUNC('MONTH', ts) FROM t", "impala")
    assert "imp_trunc_order" in ids("SELECT TRUNC('MONTH', ts) FROM t", "impala") and "imp_trunc_order" not in ids("SELECT TRUNC(ts, 'MM') FROM t", "impala")
    assert sev("SELECT concat(a, b) FROM t", "impala")["imp_concat_null"] == "warning"


def test_line_numbers_and_toon():
    fs = check("SELECT a\nFROM t\nWHERE x = 1\nLIMIT 10", "teradata")
    assert fs[0].line == 4
    out = to_toon(fs, "teradata", {"env": "prod"})
    assert "ok: false" in out and "errors: 1" in out and "findings[1]" in out and "hint:" in out
    assert "ok: true" in to_toon([], "hive")


def _slug(h):
    return re.sub(r"[^a-z0-9\- ]", "", h.lower()).strip().replace(" ", "-")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_rule_doc_anchors_exist(dialect):
    text = open(os.path.join(ROOT, REF[dialect]), encoding="utf-8").read()
    headings = {_slug(h) for h in re.findall(r"^##+\s+(.+)$", text, re.M)}
    missing = R.anchors_for(dialect) - headings
    assert not missing, f"{dialect}: anchors without heading {missing}"


def test_cli_hook_blocks_and_warns(monkeypatch, capsys, tmp_path):
    import types
    from agentdata import cli
    from agentdata.model import AgentTable
    calls = []
    fake = types.SimpleNamespace(query=lambda sql, env, mr, to: (calls.append(sql) or AgentTable("td", ["a"], [[1]], source="teradata:prod")))
    monkeypatch.setitem(sys.modules, "agentdata.connectors.teradata", fake)
    monkeypatch.setattr("agentdata.model.OUT_DIR", str(tmp_path))
    monkeypatch.delenv("AGENTDATA_SQLCHECK", raising=False)
    monkeypatch.setattr(sys, "argv", ["ad-td", "--env", "prod", "--sql", "SELECT * FROM t LIMIT 5"])
    with pytest.raises(SystemExit) as ei:
        cli.main_td()
    assert ei.value.code == 2 and calls == [] and "td_limit" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["ad-td", "--env", "prod", "--sql", "SELECT SUM(x)/COUNT(*) FROM t"])
    cli.main_td()
    out = capsys.readouterr().out
    assert calls and "warnings[1]" in out and "td_int_division" in out and "ok: true" in out
    monkeypatch.setenv("AGENTDATA_SQLCHECK", "off")
    monkeypatch.setattr(sys, "argv", ["ad-td", "--env", "prod", "--sql", "SELECT * FROM t LIMIT 5"])
    cli.main_td()
    assert len(calls) == 2


def test_render_extra_meta(tmp_path, monkeypatch):
    from agentdata.model import AgentTable
    monkeypatch.setattr("agentdata.model.OUT_DIR", str(tmp_path))
    out = policy.render(AgentTable("t", ["a"], [[1], [2]]), extra={"warnings": ["w1"]})
    assert "warnings[1]: w1" in out
