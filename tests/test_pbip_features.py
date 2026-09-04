"""Tests for native Power BI features: fixture, check rules, --features CLI, live checks, and decay check."""
import copy
import json
import os
import shutil
import tempfile
import pytest

from agentdata import cli_pbip
from agentdata.pbip import check as CK
from agentdata.pbip import features as F
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P
from agentdata.setup.wizard import Context, AnswerPrompter, Detectors
from agentdata.setup.steps import powerbi


FIXTURE_PBIP = os.path.join(os.path.dirname(__file__), "fixtures", "pbip", "native", "Native.pbip")
FIXTURE_DIR = os.path.dirname(FIXTURE_PBIP)
FIXTURE_REPORT = os.path.join(FIXTURE_DIR, "Native.Report")
FIXTURE_MODEL = os.path.join(FIXTURE_DIR, "Native.SemanticModel", "definition")


def test_native_fixture_complete_and_clean():
    """Native fixture contains all 20 features and passes validation with 0 findings."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)

    feats = F.detect_features(mod, rep)
    assert len(feats) == 20
    missing = [f.feature for f in feats if not f.present]
    assert not missing, f"Expected all 20 features to be present in native fixture, missing: {missing}"

    model_findings = CK.check_model(mod)
    assert len(model_findings) == 0, f"Expected 0 model findings, got: {[f.row() for f in model_findings]}"

    report_findings = CK.check_report(rep, mod)
    assert len(report_findings) == 0, f"Expected 0 report findings, got: {[f.row() for f in report_findings]}"


def test_check_features_cli(capsys):
    """ad-pbip check --features prints the 20-row features TOON table."""
    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["check", FIXTURE_PBIP, "--features"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "features[20]{feature,present,objects,status}:" in out
    assert "bookmarks,true" in out
    assert "drillthrough,true" in out
    assert "tooltip,true" in out
    assert "sync_slicers,true" in out
    assert "field_parameters,true" in out
    assert "calculation_groups,true" in out
    assert "visual_calculations,true" in out
    assert "conditional_formatting,true" in out
    assert "rls_ols,true" in out
    assert "incremental_refresh,true" in out
    assert "hierarchies,true" in out
    assert "sort_by,true" in out
    assert "format_strings,true" in out
    assert "page_navigation,true" in out
    assert "mobile_layout,true" in out
    assert "visual_interactions,true" in out
    assert "relationships,true" in out
    assert "report_level_measures,true" in out
    assert "themes,true" in out
    assert "agg_tables,true" in out
    assert "meta:" in out
    assert "ok: true" in out


# ---------------- Broken variant tests for all 20 feature rules ----------------

def test_rule_bookmark_page_missing():
    """Rule 1: bookmark activeSection targeting nonexistent page produces bookmark-page-missing."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    rep.bookmarks.append({
        "file": "b_broken.json",
        "name": "BrokenBookmark",
        "explorationState": {"activeSection": "nonexistent_page"},
        "visuals": [],
    })
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "bookmark-page-missing" in kinds


def test_rule_drillthrough_field_missing():
    """Rule 2: drillthrough target field not in model produces drillthrough-field-missing."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    rep.pages[1].raw["drillthrough"] = {
        "target": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": "Sales"}},
                "Property": "NonExistentColumn",
            }
        }
    }
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "drillthrough-field-missing" in kinds


def test_rule_tooltip_page_not_tooltip():
    """Rule 3: visual tooltip targeting nonexistent or non-tooltip page produces tooltip-page-not-tooltip."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    # Point visual to a page that is not a tooltip page (e.g. 'overview')
    v = rep.all_visuals().__next__()
    v.raw["visual"]["visualTooltip"] = {"type": "Page", "pageName": "overview"}
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "tooltip-page-not-tooltip" in kinds


def test_rule_sync_slicer_group_field_mismatch():
    """Rule 4: slicers in the same sync group binding to different columns produce sync-slicer-group-field-mismatch."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    # Create two visuals in same sync group with different fields
    v1 = rep.pages[0].visuals[0]
    v2 = copy.deepcopy(v1)
    v2.id = "aaaaaaaaaaaaaaaaaaaa"
    v2.fields = [P.FieldRef("column", "Dates", "MonthNumber")]
    rep.pages[0].visuals.append(v2)
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "sync-slicer-group-field-mismatch" in kinds


def test_rule_fieldparam_nameof_mismatch(tmp_path):
    """Rule 5: NAMEOF referencing missing column/table produces fieldparam-nameof-mismatch."""
    # Copy fixture model into tmp_path and modify FieldParam.tmdl
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    fp_file = dest / "tables" / "FieldParam.tmdl"
    text = fp_file.read_text(encoding="utf-8")
    text = text.replace("NAMEOF('Sales'[Margin])", "NAMEOF('Sales'[NonExistent])")
    fp_file.write_text(text, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "fieldparam-nameof-mismatch" in kinds


def test_rule_calcgroup_precedence_clash(tmp_path):
    """Rule 6: two calculation groups with identical precedence produce calcgroup-precedence-clash."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    ti_file = dest / "tables" / "TimeIntelligence.tmdl"
    ti2_file = dest / "tables" / "TimeIntelligence2.tmdl"
    text = ti_file.read_text(encoding="utf-8")
    text2 = text.replace("table TimeIntelligence", "table TimeIntelligence2")
    ti2_file.write_text(text2, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "calcgroup-precedence-clash" in kinds


def test_rule_visualcalc_missing_nativequeryref():
    """Rule 7: visual calculation without nativeQueryRef produces visualcalc-missing-nativequeryref."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    # Remove nativeQueryRef from projection
    v = rep.pages[0].visuals[1]
    projs = v.raw["visual"]["query"]["queryState"]["Values"]["projections"]
    for p in projs:
        if "visualCalculation" in p:
            del p["nativeQueryRef"]
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "visualcalc-missing-nativequeryref" in kinds


def test_rule_cf_rule_field_missing():
    """Rule 8: conditional formatting referencing missing field produces cf-rule-field-missing."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    v = rep.pages[0].visuals[1]
    cf = v.raw["visual"]["objects"]["values"][0]["properties"]["backColor"]["conditionalFormatting"]
    cf["field"]["Measure"]["Property"] = "MissingKPI"
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "cf-rule-field-missing" in kinds


def test_rule_rls_table_missing_and_filter_dax(tmp_path):
    """Rule 9: role referencing missing table or invalid DAX produces rls-table-missing / rls-filter-invalid-dax."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    role_file = dest / "roles" / "SalesManager.tmdl"
    role_file.write_text("role SalesManager\n\tmodelPermission: read\n\ttablePermission NonExistentTable = [Region] == \"North\"\n", encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "rls-table-missing" in kinds

    # Test invalid DAX (unmatched paren)
    role_file.write_text("role SalesManager\n\tmodelPermission: read\n\ttablePermission Customers = ([Region] == \"North\"\n", encoding="utf-8")
    mod2 = N.load_model(str(dest))
    findings2 = F.check_model_features(mod2)
    assert "rls-filter-invalid-dax" in [f.kind for f in findings2]


def test_rule_refresh_policy_parameters_missing(tmp_path):
    """Rule 10: refreshPolicy without RangeStart/RangeEnd produces refresh-policy-parameters-missing."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    # Remove RangeStart from expressions.tmdl
    exp_file = dest / "expressions.tmdl"
    exp_file.write_text("", encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "refresh-policy-parameters-missing" in kinds


def test_rule_hierarchy_level_column_missing(tmp_path):
    """Rule 11: hierarchy level referencing missing column produces level-column-missing."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    dates_file = dest / "tables" / "Dates.tmdl"
    text = dates_file.read_text(encoding="utf-8")
    text = text.replace("column: MonthName", "column: NonExistentMonth")
    dates_file.write_text(text, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = CK.check_model(mod)
    kinds = [f.kind for f in findings]
    assert "level-column-missing" in kinds


def test_rule_sortby_missing(tmp_path):
    """Rule 12: sortByColumn referencing missing column produces sort-by-missing."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    dates_file = dest / "tables" / "Dates.tmdl"
    text = dates_file.read_text(encoding="utf-8")
    text = text.replace("sortByColumn: MonthNumber", "sortByColumn: NonExistentSortCol")
    dates_file.write_text(text, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = CK.check_model(mod)
    kinds = [f.kind for f in findings]
    assert "sort-by-missing" in kinds


def test_rule_format_string_invalid(tmp_path):
    """Rule 13: empty formatString produces format-string-invalid."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    sales_file = dest / "tables" / "Sales.tmdl"
    text = sales_file.read_text(encoding="utf-8")
    text = text.replace("formatString: $ #,##0", "formatString:   ")
    sales_file.write_text(text, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "format-string-invalid" in kinds


def test_rule_nav_action_page_missing():
    """Rule 14: button action navigation targeting missing page produces nav-action-page-missing."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    v = rep.pages[0].visuals[2]
    v.raw["visual"]["objects"]["action"][0]["properties"]["destination"]["expr"]["Literal"]["Value"] = "'MissingPage'"
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "nav-action-page-missing" in kinds


def test_rule_mobile_visual_not_on_page():
    """Rule 15: mobileState referencing visual not on page produces mobile-visual-not-on-page."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    rep.pages[0].raw["mobileState"]["visualContainers"]["99999999999999999999"] = {"position": {}}
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "mobile-visual-not-on-page" in kinds


def test_rule_interaction_visual_missing(tmp_path):
    """Rule 16: visualInteractions targeting nonexistent visual produces interaction-visual-missing."""
    dest = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest)
    rj = dest / "definition" / "report.json"
    data = json.loads(rj.read_text(encoding="utf-8"))
    data["visualInteractions"].append({"source": "nonexistent_source", "target": "22222222222222222222", "type": "CrossFilter"})
    rj.write_text(json.dumps(data), encoding="utf-8")

    rep = P.load_report(str(dest))
    mod = N.load_model(FIXTURE_MODEL)
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "interaction-visual-missing" in kinds


def test_rule_userelationship_inactive_missing(tmp_path):
    """Rule 17: USERELATIONSHIP without corresponding inactive relationship produces userelationship-inactive-missing."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    # Remove inactive relationship from relationships.tmdl
    rel_file = dest / "relationships.tmdl"
    rel_file.write_text("relationship AutoDetected_Dates_Sales_Order\n\tfromColumn: Sales.OrderDateKey\n\ttoColumn: Dates.DateKey\n", encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "userelationship-inactive-missing" in kinds


def test_rule_report_measure_entity_missing():
    """Rule 18: reportExtension measure targeting nonexistent table produces extension-entity-missing."""
    rep = P.load_report(FIXTURE_REPORT)
    mod = N.load_model(FIXTURE_MODEL)
    rep.extension_measures.append({
        "name": "OrphanKPI",
        "entity": "NonExistentTable",
        "file": "reportExtension.json",
        "expression": "1 + 1",
    })
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "extension-entity-missing" in kinds


def test_rule_theme_resource_missing(tmp_path):
    """Rule 19: custom theme file missing on disk produces theme-resource-missing."""
    dest = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest)
    theme_file = dest / "StaticResources" / "SharedResources" / "BaseThemes" / "CY24SU02.json"
    if theme_file.exists():
        theme_file.unlink()

    rep = P.load_report(str(dest))
    mod = N.load_model(FIXTURE_MODEL)
    findings = F.check_report_features(mod, rep)
    kinds = [f.kind for f in findings]
    assert "theme-resource-missing" in kinds


def test_rule_agg_table_hidden(tmp_path):
    """Rule 20: aggregation table not hidden produces agg-table-hidden."""
    dest = tmp_path / "model"
    shutil.copytree(FIXTURE_MODEL, dest)
    agg_file = dest / "tables" / "SalesAgg.tmdl"
    text = agg_file.read_text(encoding="utf-8")
    text = text.replace("isHidden\n", "")
    agg_file.write_text(text, encoding="utf-8")

    mod = N.load_model(str(dest))
    findings = F.check_model_features(mod)
    kinds = [f.kind for f in findings]
    assert "agg-table-hidden" in kinds


# ---------------- Live check and decay tests ----------------

def test_live_feature_verification(tmp_path):
    """Live verification handles DAX queries and report-side checks."""
    dummy_dscmd = str(tmp_path / "dscmd.exe")
    with open(dummy_dscmd, "w", encoding="utf-8") as f:
        f.write("")

    def fake_run(args, timeout=30):
        out_csv = args[2] if len(args) > 2 else None
        if out_csv and os.path.dirname(out_csv):
            os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
            with open(out_csv, "w", encoding="utf-8") as f:
                f.write("Col1,Col2\nVal1,Val2\n")
        return 0, "rows=1", ""

    # Test DAX-backed feature
    res_dax = F.verify_feature_live("calculation_groups", "localhost:5000", "Model", runner=fake_run, dscmd_exe=dummy_dscmd)
    assert res_dax["verified"] is True
    assert res_dax["type"] == "dax"
    assert "YTD" in res_dax["query"]

    # Test report-side feature
    res_rep = F.verify_feature_live("drillthrough", "localhost:5000", "Model", runner=fake_run, dscmd_exe=dummy_dscmd)
    assert res_rep["verified"] is True
    assert res_rep["type"] == "report-side"


def test_doctor_feature_decay_check(monkeypatch):
    """ad-doctor --online verifies powerbi/feature_decay check against docs/power-bi-features.md."""
    class FakeDet(Detectors):
        def run(self, cmd, timeout=120):
            return 0, json.dumps({"value": []}), ""

    ctx = Context(
        cfg={"powerbi": {"feature_recheck_days": 30}},
        det=FakeDet(),
        ask=AnswerPrompter(),
        online=True,
        interactive=False,
    )
    step = powerbi.PowerBIStep()
    step.verify(ctx)

    decay_check = next((c for c in ctx.checks if c.name == "powerbi/feature_decay"), None)
    assert decay_check is not None
    assert decay_check.status == "ok"
    assert "verified within 30d" in decay_check.detail

    # Test when threshold is 0 days (forces decay warning)
    ctx_decay = Context(
        cfg={"powerbi": {"feature_recheck_days": -1}},
        det=FakeDet(),
        ask=AnswerPrompter(),
        online=True,
        interactive=False,
    )
    step.verify(ctx_decay)
    decay_warn = next((c for c in ctx_decay.checks if c.name == "powerbi/feature_decay"), None)
    assert decay_warn is not None
    assert decay_warn.status == "warn"
    assert "decayed verifications" in decay_warn.detail
