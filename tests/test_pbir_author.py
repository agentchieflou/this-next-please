"""Tests for PBIR authoring parity: catalog, mechanical edits, anti-pattern lint, and schema validation."""
import json
import os
import shutil
import tempfile
import pytest
from agentdata.pbip import catalog as CAT
from agentdata.pbip import expr as EX
from agentdata.pbip import author as AU
from agentdata.pbip import check as CK
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P
from agentdata.cli_pbip import main

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pbip")


def test_schema_version_and_files():
    """Assert vendored schema VERSION agrees with files and catalog."""
    res = CAT.schema_update()
    assert res["ok"] is True
    assert res["version"] == "2.0.0"
    assert res["pbir_format_version"] == "2.0.0"
    assert res["visual_types_count"] >= 15
    assert "columnChart" in res["visual_types"]
    assert "cardVisual" in res["visual_types"]
    assert "tableEx" in res["visual_types"]


def test_catalog_list_and_describe():
    t_list = CAT.list_visuals()
    assert t_list.name == "visual_catalog"
    assert len(t_list.rows) >= 15
    # Check columnChart
    col_row = next(r for r in t_list.rows if r[0] == "columnChart")
    assert col_row[3] == "no"  # not legacy
    assert "Category" in col_row[2]

    # Check legacy card
    card_row = next(r for r in t_list.rows if r[0] == "card")
    assert card_row[3] == "yes"  # legacy
    assert card_row[4] == "cardVisual"  # replacement

    t_desc = CAT.describe_visual("columnChart")
    roles = {r[0]: (r[1], r[2], r[3]) for r in t_desc.rows}
    assert roles["Category"] == (0, 1, "Grouping")
    assert roles["Y"][0] == 1  # min 1
    assert roles["Y"][2] == "Measure"


def test_catalog_formatting():
    t_fmt = CAT.formatting_catalog(object_name="title")
    props = {r[1]: r[2] for r in t_fmt.rows}
    assert "text" in props
    assert "fontColor" in props

    t_search = CAT.formatting_catalog(search="shadow")
    assert len(t_search.rows) >= 1
    assert t_search.rows[0][0] == "dropShadow"


def test_expr_encoding_and_decoding():
    # Column
    e1 = EX.encode_expr("'Sales'[Amount]")
    assert e1 == {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Amount"}}
    assert EX.decode_expr(e1) == "'Sales'[Amount]"

    # Measure
    e2 = EX.encode_expr("[Total Margin]", is_measure=True)
    assert "Measure" in e2
    assert e2["Measure"]["Property"] == "Total Margin"

    # Aggregation
    e3 = EX.encode_expr("Sum('Sales'[Amount])")
    assert "Aggregation" in e3
    assert e3["Aggregation"]["Function"] == 0
    assert EX.decode_expr(e3) == "Sum('Sales'[Amount])"


def test_theme_shading():
    # Darken
    darker = EX.shade_color("#1F77B4", -20)
    assert darker.startswith("#") and darker != "#1F77B4"
    # Lighten
    lighter = EX.shade_color("#1F77B4", 20)
    assert lighter.startswith("#") and lighter != "#1F77B4"
    with pytest.raises(ValueError):
        EX.shade_color("not-a-color", 10)


def test_mechanical_page_edits(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # Page add
    res_add = AU.page_add(str(target), "KPI Dashboard", after="page1", width=1920, height=1080)
    assert res_add["ok"] is True
    pid = res_add["page_id"]

    pages_meta = json.loads((target / "Sample.Report" / "definition" / "pages" / "pages.json").read_text("utf-8"))
    assert pid in pages_meta["pageOrder"]
    assert pages_meta["pageOrder"][1] == pid  # after page1

    # Page move
    res_move = AU.page_move(str(target), pid, after=None)  # move to first
    assert res_move["ok"] is True
    pages_meta = json.loads((target / "Sample.Report" / "definition" / "pages" / "pages.json").read_text("utf-8"))
    assert pages_meta["pageOrder"][0] == pid

    # Page remove
    res_rm = AU.page_remove(str(target), pid)
    assert res_rm["ok"] is True
    pages_meta = json.loads((target / "Sample.Report" / "definition" / "pages" / "pages.json").read_text("utf-8"))
    assert pid not in pages_meta["pageOrder"]


def test_mechanical_visual_add_and_set(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # Visual add: columnChart
    res_v = AU.visual_add(str(target), "page1", "columnChart", title="Sales by Year",
                          fields=["'Calendar'[Year]", "'Sales'[Margin]"], position=(50, 50, 600, 400))
    assert res_v["ok"] is True
    vid = res_v["visual_id"]
    assert len(vid) == 20

    # Verify visual.json exists and contains queryState
    vj_file = target / "Sample.Report" / "definition" / "pages" / "page1" / "visuals" / vid / "visual.json"
    assert vj_file.exists()
    vdata = json.loads(vj_file.read_text("utf-8"))
    assert vdata["position"]["width"] == 600
    assert "Category" in vdata["visual"]["query"]["queryState"]
    assert "Y" in vdata["visual"]["query"]["queryState"]

    # Visual set formatting property
    res_set = AU.visual_set(str(target), vid, "title.text", "Updated Title")
    assert res_set["ok"] is True
    vdata_updated = json.loads(vj_file.read_text("utf-8"))
    t_val = vdata_updated["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"]
    assert "Updated Title" in t_val

    # Visual set position property
    res_pos = AU.visual_set(str(target), vid, "position.x", 100)
    assert res_pos["ok"] is True
    assert json.loads(vj_file.read_text("utf-8"))["position"]["x"] == 100

    # Visual remove
    res_rm = AU.visual_remove(str(target), vid)
    assert res_rm["ok"] is True
    assert not vj_file.exists()


def test_visual_add_validation_checks(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # 1. Reject legacy visual type
    with pytest.raises(ValueError) as exc:
        AU.visual_add(str(target), "page1", "card", fields=["'Sales'[Margin]"])
    assert "deprecated" in str(exc.value)

    # 2. Reject off-canvas positioning (e.g. x + width > 1280)
    with pytest.raises(ValueError) as exc:
        AU.visual_add(str(target), "page1", "cardVisual", fields=["'Sales'[Margin]"], position=(1000, 20, 500, 300))
    assert "off-canvas" in str(exc.value)

    # 3. Reject missing required roles (cardVisual requires at least 1 Data metric)
    with pytest.raises(ValueError) as exc:
        AU.visual_add(str(target), "page1", "cardVisual", fields=[])
    assert "requires at least 1 field" in str(exc.value)


def test_filter_set_canonical_source_ref(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # Set page filter
    res_flt = AU.filter_set(str(target), "page", "'Sales'[Status]", values=["Open", "Closed"], page="page1")
    assert res_flt["ok"] is True

    pj = target / "Sample.Report" / "definition" / "pages" / "page1" / "page.json"
    pdata = json.loads(pj.read_text("utf-8"))
    filters = pdata["filterConfig"]["filters"]
    new_filter = filters[-1]
    assert new_filter["type"] == "Categorical"

    # CRITICAL: ensure SourceRef has Source alias, NOT Entity
    where = new_filter["filter"]["Where"][0]
    expr_col = where["Condition"]["In"]["Expressions"][0]["Column"]
    assert "Source" in expr_col["Expression"]["SourceRef"]
    assert "Entity" not in expr_col["Expression"]["SourceRef"]


def test_bookmark_add_and_theme_set(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # Bookmark add
    res_bm = AU.bookmark_add(str(target), "Default View", "page1", visuals=["f1a2b3c4d5e6f7a8b9c0"])
    assert res_bm["ok"] is True
    bm_file = target / "Sample.Report" / "definition" / "bookmarks" / f"{res_bm['name']}.json"
    assert bm_file.exists()

    # Theme set
    custom_theme = tmp_path / "brand.json"
    custom_theme.write_text(json.dumps({"name": "BrandTheme", "dataColors": ["#112233"]}), encoding="utf-8")
    res_theme = AU.theme_set(str(target), str(custom_theme))
    assert res_theme["ok"] is True
    assert (target / "Sample.Report" / "StaticResources" / "RegisteredResources" / "brand.json").exists()


def test_anti_pattern_lint_catches_issues(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # 1. Induce filter-entity-vs-source
    pj = target / "Sample.Report" / "definition" / "pages" / "page1" / "page.json"
    pdata = json.loads(pj.read_text("utf-8"))
    bad_filter = {
        "name": "Filter000000000000000000000099",
        "type": "Categorical",
        "field": {"Column": {"Property": "Year"}},
        "filter": {
            "Version": 2,
            "From": [{"Name": "c", "Entity": "Calendar", "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Entity": "Calendar"}}, "Property": "Year"}}]}}}]
        }
    }
    pdata.setdefault("filterConfig", {}).setdefault("filters", []).append(bad_filter)
    pj.write_text(json.dumps(pdata), encoding="utf-8")

    # 2. Induce legacy-visual-type
    vj = target / "Sample.Report" / "definition" / "pages" / "page1" / "visuals" / "f1a2b3c4d5e6f7a8b9c0" / "visual.json"
    vdata = json.loads(vj.read_text("utf-8"))
    vdata["visual"]["visualType"] = "card"
    vj.write_text(json.dumps(vdata), encoding="utf-8")

    # 3. Induce position-off-canvas
    vdata["position"]["x"] = 1200
    vdata["position"]["width"] = 300  # 1200 + 300 = 1500 > 1280
    vj.write_text(json.dumps(vdata), encoding="utf-8")

    # 4. Induce duplicate-visual-id (copy visual into page2)
    vj2_dir = target / "Sample.Report" / "definition" / "pages" / "page2" / "visuals" / "f1a2b3c4d5e6f7a8b9c0"
    vj2_dir.mkdir(parents=True, exist_ok=True)
    (vj2_dir / "visual.json").write_text(json.dumps(vdata), encoding="utf-8")

    # 5. Induce page-not-in-pages-json
    orphan_dir = target / "Sample.Report" / "definition" / "pages" / "orphan_page"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "page.json").write_text(json.dumps({"name": "orphan_page", "displayName": "Orphan"}), encoding="utf-8")

    model, report, _ = N.load_all(str(target))
    findings = CK.check_report(report, model)
    kinds = {f.kind for f in findings}

    assert "filter-entity-vs-source" in kinds
    assert "legacy-visual-type" in kinds
    assert "position-off-canvas" in kinds
    assert "duplicate-visual-id" in kinds
    assert "page-not-in-pages-json" in kinds


def test_cli_authoring_commands(tmp_path, capsys):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    # CLI catalog list
    with pytest.raises(SystemExit) as exc:
        main(["catalog", "list"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "columnChart" in out

    # CLI page add
    with pytest.raises(SystemExit) as exc:
        main(["page", "add", str(target), "--name", "Summary"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "page_add" in out

    # CLI preview pages
    with pytest.raises(SystemExit) as exc:
        main(["preview", "pages", str(target)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Summary" in out
