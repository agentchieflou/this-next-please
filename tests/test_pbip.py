import json, os, shutil, sys
import pytest
from agentdata.pbip import check as CK
from agentdata.pbip import edit as E
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P
from agentdata.pbip import project as PJ
from agentdata.pbip import tmdl as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "sample.pbip")
DEFN = os.path.join(FIX, "Sample.SemanticModel", "definition")


# ---------- TMDL ----------
def test_tmdl_parses_fixture_objects():
    tf = T.read_file(os.path.join(DEFN, "tables", "Sales.tmdl"))
    t = tf.find("table", "Sales")
    assert t.desc == ["Jira issue facts loaded from the Teradata history table"]
    m = t.child("measure", "Margin")
    assert m.fenced and m.expr.startswith("SUMX (") and m.props["formatString"] == "$ #,##0"
    ly = t.child("measure", "Sales Amount (LY)")
    assert not ly.fenced and "return" in ly.expr and ly.desc
    calc = t.child("column", "Story Points Rounded")
    assert calc.expr == "ROUND ( Sales[Quantity], 0 )" and "sourceColumn" not in calc.props
    part = t.child("partition", "Sales")
    assert part.expr == "m" and part.props["mode"] == "import" and 'Item="JIRA_ISSUE_HISTORY"' in part.props["source"]
    assert t.child("column", "DateKey").props["isHidden"] is True
    assert T.lint_file(tf) == []


def test_tmdl_crlf_bom_preserved_and_roundtrip(tmp_path):
    src = os.path.join(DEFN, "tables", "Calendar.tmdl")
    tf = T.read_file(src)
    assert tf.bom and tf.newline == "\r\n" and [f.rule for f in tf.findings] == ["bom"]
    h = tf.find("table", "Calendar").child("hierarchy", "Date Hierarchy")
    assert [(lv.name, lv.props["column"]) for lv in h.children if lv.kind == "level"] == [("Year", "Year"), ("Month", "Month")]
    tf.path = str(tmp_path / "Calendar.tmdl")
    T.write_file(tf)
    assert open(tf.path, "rb").read() == open(src, "rb").read()


def test_tmdl_lint_rules():
    bad = "table T\n\tmeasure Sales Amount = 1\n\tcolumn X\n\t\tsortByColumn: Week Day\n    isHidden\n\t\t\t\tdataType: int64\n// nope\n\tmeasure Y = ```\n\t\t\tSUM(1)\n"
    tf = T.parse_text(bad, "tables/T.tmdl")
    rules = {f.rule for f in T.lint_file(tf)}
    assert {"unquoted_name", "unquoted_ref", "mixed_indent", "indent_jump", "double_slash_comment", "unterminated_fence"} <= rules
    db = T.parse_text("\tcompatibilityLevel: 1604\n", "database.tmdl")
    assert "database_decl" in {f.rule for f in db.findings}
    assert "missing_trailing_newline" in {f.rule for f in T.parse_text("table T", "t.tmdl").findings}
    cont = T.parse_text("table T\n\tmeasure M =\n\t\tSUM(1)\n", "t.tmdl")
    assert "continuation_indent" in {f.rule for f in T.lint_file(cont)}


def test_tmdl_names_and_refs():
    assert T.quote_name("Order Date") == "'Order Date'" and T.quote_name("Sales") == "Sales" and T.quote_name("a.b") == "'a.b'"
    assert T.split_ref("Sales.'Order Date'") == ("Sales", "Order Date") and T.split_ref("'My Table'.Col") == ("My Table", "Col")
    assert T.split_ref("Col") == (None, "Col") and T.unquote("'Week Day (#)'") == "Week Day (#)"
    assert T.split_ref("'Sales'[Net Price]") == ("Sales", "Net Price") and T.split_ref("Sales[Quantity]") == ("Sales", "Quantity")


def test_measure_upsert_add_and_update(tmp_path):
    shutil.copytree(FIX, tmp_path / "p")
    model = N.load_model(str(tmp_path / "p" / "Sample.SemanticModel" / "definition"))
    res = E.measure_set(model, "Sales", "Margin %", "DIVIDE (\n    [Margin],\n    [Total Sales]\n)", format_string="0.0%", display_folder="KPIs", description="Margin over sales")
    assert res["action"] == "added" and res["file"] == "tables/Sales.tmdl"
    text = open(tmp_path / "p" / "Sample.SemanticModel" / "definition" / "tables" / "Sales.tmdl", encoding="utf-8").read()
    block = "\t/// Margin over sales\n\tmeasure 'Margin %' = ```\n\t\t\tDIVIDE (\n\t\t\t    [Margin],\n\t\t\t    [Total Sales]\n\t\t\t)\n\t\t\t```\n\t\tformatString: 0.0%\n\t\tdisplayFolder: KPIs\n"
    assert block in text and "lineageTag" not in block
    assert text.index("measure 'Margin %'") > text.index("measure 'Total Sales'") and text.index("measure 'Margin %'") < text.index("column DateKey")
    model2 = N.load_model(str(tmp_path / "p" / "Sample.SemanticModel" / "definition"))
    res2 = E.measure_set(model2, "Sales", "Total Sales", "SUM ( Sales[Net Price] )")
    text2 = open(tmp_path / "p" / "Sample.SemanticModel" / "definition" / "tables" / "Sales.tmdl", encoding="utf-8").read()
    assert res2["action"] == "updated"
    assert "\tmeasure 'Total Sales' = SUM ( Sales[Net Price] )\n\t\tformatString: $ #,##0\n\t\tdisplayFolder: KPIs\n\t\tlineageTag: 0d3ae0f6-0000-4000-8000-000000000012\n" in text2
    assert text2.count("measure 'Total Sales'") == 1
    with pytest.raises(LookupError):
        E.measure_set(model2, "Nope", "X", "1")
    with pytest.raises(ValueError):
        E.measure_set(model2, "Sales", "Bad", "SUM(1)\n```\nbroken")


# ---------- PBIR ----------
def test_pbir_refs_and_alias_resolution():
    rep = P.load_report(FIX)
    assert not rep.legacy and rep.version == "4.0" and rep.dataset_path.endswith("Sample.SemanticModel")
    assert [p.name for p in rep.pages] == ["Overview", "Detail"]
    v1 = next(v for v in rep.pages[0].visuals if v.id == "f1a2b3c4d5e6f7a8b9c0")
    assert v1.title == "Margin by Year" and v1.type == "barChart"
    labels = {(r.context, r.label()) for r in v1.fields}
    assert ("projection:Category", "'Calendar'[Year]") in labels and ("projection:Y", "'Sales'[Margin]") in labels and ("sort", "'Sales'[Margin]") in labels
    v3 = rep.pages[1].visuals[0]
    kinds = {(r.kind, r.label(), r.hierarchy, r.context) for r in v3.fields}
    assert ("level", "'Calendar'[Year]", "Date Hierarchy", "projection:Category") in kinds
    assert ("column", "Sum('Sales'[Quantity])", None, "projection:Y") in kinds
    assert ("measure", "'Sales'[Margin]", None, "format") in kinds
    pf = rep.pages[1].filters[0]
    assert pf["field"] == "'Sales'[Status]" and all(r.entity == "Sales" for r in pf["refs"])
    assert rep.filters[0]["name"] == "Filter000000000000000000000001" and rep.extension_measures[0]["name"] == "Ext Measure"
    assert rep.bookmarks[0]["visuals"] == ["f1a2b3c4d5e6f7a8b9c0", "zzzzzzzzzzzzzzzzzzzz"]


def test_pbir_type_1_sources_are_skipped():
    obj = {"filter": {"From": [{"Name": "p", "Entity": "ReportSection1", "Type": 1}], "Where": [{"Condition": {"Column": {"Expression": {"SourceRef": {"Source": "p"}}, "Property": "X"}}}]}}
    refs = list(P.walk_refs(obj))
    assert len(refs) == 1 and refs[0].entity is None


# ---------- normalize / check ----------
def test_check_reports_expected_findings():
    model, report, norm = N.load_all(FIX)
    findings = CK.check_model(model) + CK.check_report(report, model)
    kinds = {(f.kind, f.object) for f in findings if f.severity == "error"}
    assert ("field-unresolved", "aaaaaaaaaaaaaaaaaaaa (Broken table)") in kinds
    msgs = [f.message for f in findings if f.kind == "field-unresolved"]
    assert any("'Sales'[Region Name] not in model" in m for m in msgs)
    assert not any("Ext Measure" in m for m in msgs)
    assert not any("Total Sales" in m for m in msgs)
    assert any(f.kind == "bookmark-visual-missing" for f in findings)
    assert [f for f in findings if f.kind in ("relationship-column-missing", "relationship-table-missing", "sort-by-missing", "ref-table-missing", "dax-ref-unresolved")] == []
    assert norm["lineage"]["sources"]["Sales"] == ["JIRA_ISSUE_HISTORY"]
    assert "'Sales'[Quantity]" in norm["lineage"]["measure_usage"] and "'Sales'[Margin]" in norm["lineage"]["field_usage"]


def test_check_clean_after_fixing_visual(tmp_path):
    shutil.copytree(FIX, tmp_path / "p")
    vj = tmp_path / "p" / "Sample.Report" / "definition" / "pages" / "page1" / "visuals" / "aaaaaaaaaaaaaaaaaaaa" / "visual.json"
    d = json.loads(vj.read_text(encoding="utf-8"))
    d["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Column"]["Property"] = "Status"
    vj.write_text(json.dumps(d), encoding="utf-8")
    bj = tmp_path / "p" / "Sample.Report" / "definition" / "bookmarks" / "b1.json"
    bj.write_text(bj.read_text(encoding="utf-8").replace(', "zzzzzzzzzzzzzzzzzzzz": {}', ""), encoding="utf-8")
    model, report, _ = N.load_all(str(tmp_path / "p"))
    findings = CK.check_model(model) + CK.check_report(report, model)
    assert [f for f in findings if f.severity == "error"] == []


def test_model_checks_catch_dups_and_dangling(tmp_path):
    shutil.copytree(FIX, tmp_path / "p")
    defn = tmp_path / "p" / "Sample.SemanticModel" / "definition"
    sales = defn / "tables" / "Sales.tmdl"
    sales.write_text(sales.read_text(encoding="utf-8").replace("0d3ae0f6-0000-4000-8000-000000000015", "0d3ae0f6-0000-4000-8000-000000000012").replace("sortByColumn: 'Status Order'", "sortByColumn: 'Nope'"), encoding="utf-8")
    (defn / "relationships.tmdl").write_text((defn / "relationships.tmdl").read_text(encoding="utf-8").replace("toColumn: Calendar.Date\n\nrelationship", "toColumn: Calendar.Missing\n\nrelationship"), encoding="utf-8")
    (defn / "tables" / "Extra.tmdl").write_text("table Extra\n\tcolumn A\n\t\tdataType: string\n\n\tpartition Extra = m\n\t\tmode: import\n\t\tsource = 1\n", encoding="utf-8")
    model = N.load_model(str(defn))
    kinds = {f.kind for f in CK.check_model(model)}
    assert {"dup-lineage-tag", "sort-by-missing", "relationship-column-missing", "ref-table-missing"} <= kinds


def test_projection_writes_and_skips(tmp_path):
    model, report, norm = N.load_all(FIX)
    out = tmp_path / "proj"
    res = PJ.write_projection(norm, model, report, str(out))
    assert not res["skipped"] and {"MODEL.md", "REPORT.md", "LINEAGE.md", "measures.tsv", "visual_fields.tsv", "meta.json"} <= set(res["files"])
    md = (out / "MODEL.md").read_text(encoding="utf-8")
    assert "## Sales" in md and "| Margin |" in md and "JIRA_ISSUE_HISTORY" in md and "Sales[DateKey] → Calendar[Date]" in md
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "Margin by Year" in rep and "'Calendar'[Year]" in rep and "Report-level measures" in rep
    assert PJ.write_projection(norm, model, report, str(out))["skipped"] is True
    assert PJ.write_projection(norm, model, report, str(out), force=True)["skipped"] is False
    rows = (out / "visual_fields.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0] == "page\tvisual\tcontext\tkind\tentity\tprop\thierarchy\tagg" and len(rows) > 5


def test_te2_missing_is_a_warning():
    fs, info = CK.run_te2(DEFN, "/nonexistent/TabularEditor.exe")
    assert not info["ran"] and fs[0].severity == "warning" and "te2" in fs[0].kind


def test_cli_check_project_refs(monkeypatch, capsys, tmp_path):
    from agentdata import cli_pbip

    def run(argv):
        monkeypatch.setattr(sys, "argv", ["ad-pbip", *argv])
        with pytest.raises(SystemExit) as ei:
            cli_pbip.main()
        return ei.value.code, capsys.readouterr().out

    code, out = run(["check", FIX])
    assert code == 1 and "field-unresolved" in out and "ok: false" in out
    code, out = run(["project", FIX, "--out", str(tmp_path / "o")])
    assert code == 0 and "MODEL.md" in out and "tables: 2" in out
    code, out = run(["refs", FIX, "--visual", "Margin by Year"])
    assert code == 0 and "JIRA_ISSUE_HISTORY" in out and "'Sales'[Margin]" in out
    code, out = run(["refs", FIX, "--table", "Calendar", "--column", "Year"])
    assert code == 0 and "hierarchy" in out and "f1a2b3c4d5e6f7a8b9c0" in out
    code, out = run(["lint", DEFN])
    assert code == 0 and "bom" in out
