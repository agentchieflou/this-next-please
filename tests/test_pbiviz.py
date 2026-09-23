"""Tests for Power BI custom visual development loop (ad-pbiviz and PBIR integration)."""
import copy
import json
import os
import shutil
import zipfile
import pytest

from agentdata import cli_pbiviz
from agentdata.pbip import catalog as CAT
from agentdata.pbip import check as CK
from agentdata.pbip import dax as D
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P
from agentdata.pbiviz import core as PV

FIXTURE_PBIP = os.path.join(os.path.dirname(__file__), "fixtures", "pbip", "native", "Native.pbip")
FIXTURE_DIR = os.path.dirname(FIXTURE_PBIP)
FIXTURE_REPORT = os.path.join(FIXTURE_DIR, "Native.Report")
FIXTURE_MODEL = os.path.join(FIXTURE_DIR, "Native.SemanticModel", "definition")


# ---------------- Doctor & Scaffolding ----------------

def test_pbiviz_doctor():
    """doctor checks node, pbiviz, and certificate."""
    checks = PV.doctor()
    assert len(checks) == 3
    names = [c["check"] for c in checks]
    assert "node" in names
    assert "pbiviz" in names
    assert "certificate" in names


def test_scaffold_visual(tmp_path):
    """scaffold_visual creates standard pbiviz file tree with valid JSON."""
    res = PV.scaffold_visual("donut-chart", base_dir=str(tmp_path))
    assert res["name"] == "donut-chart"
    assert os.path.exists(os.path.join(res["path"], "pbiviz.json"))
    assert os.path.exists(os.path.join(res["path"], "capabilities.json"))
    assert os.path.exists(os.path.join(res["path"], "package.json"))
    assert os.path.exists(os.path.join(res["path"], "src", "visual.ts"))

    with open(os.path.join(res["path"], "pbiviz.json"), "r", encoding="utf-8") as f:
        conf = json.load(f)
    assert conf["visual"]["name"] == "donut-chart"
    assert conf["visual"]["guid"].startswith("donut-chart_")


def test_get_roles(tmp_path):
    """get_roles reads declared dataRoles from capabilities.json."""
    PV.scaffold_visual("kpi-tile", base_dir=str(tmp_path))
    roles = PV.get_roles("kpi-tile", base_dir=str(tmp_path))
    assert len(roles) == 2
    r_map = {r["name"]: r for r in roles}
    assert r_map["category"]["kind"] == "Grouping"
    assert r_map["measure"]["kind"] == "Measure"


# ---------------- Binding & Kind Validation ----------------

def test_bind_roles_success(tmp_path):
    """bind_roles validates field kinds against model and writes binding file."""
    PV.scaffold_visual("bar-chart", base_dir=str(tmp_path))
    res = PV.bind_roles(
        "bar-chart",
        FIXTURE_PBIP,
        {"category": "'Dates'[MonthName]", "measure": "[Total Sales]"},
        base_dir=str(tmp_path),
    )
    assert res["visual"] == "bar-chart"
    assert os.path.exists(res["binding_file"])
    with open(res["binding_file"], "r", encoding="utf-8") as f:
        bdata = json.load(f)
    assert bdata["bindings"]["category"] == "'Dates'[MonthName]"
    assert bdata["bindings"]["measure"] == "[Total Sales]"


def test_bind_roles_refuses_grouping_with_measure(tmp_path):
    """bind_roles refuses when Grouping role receives a measure."""
    PV.scaffold_visual("bar-chart", base_dir=str(tmp_path))
    with pytest.raises(PV.PbivizError, match="requires a column, but received measure"):
        PV.bind_roles(
            "bar-chart",
            FIXTURE_PBIP,
            {"category": "[Total Sales]", "measure": "[Margin]"},
            base_dir=str(tmp_path),
        )


def test_bind_roles_refuses_measure_with_bare_column(tmp_path):
    """bind_roles refuses when Measure role receives an unaggregated column."""
    PV.scaffold_visual("bar-chart", base_dir=str(tmp_path))
    with pytest.raises(PV.PbivizError, match="requires a measure or aggregation, but received bare column"):
        PV.bind_roles(
            "bar-chart",
            FIXTURE_PBIP,
            {"category": "'Dates'[MonthName]", "measure": "'Sales'[Margin]"},
            base_dir=str(tmp_path),
        )


def test_bind_roles_aggregated_column_for_measure(tmp_path):
    """bind_roles accepts Sum('Table'[Column]) for a Measure role."""
    PV.scaffold_visual("bar-chart", base_dir=str(tmp_path))
    res = PV.bind_roles(
        "bar-chart",
        FIXTURE_PBIP,
        {"category": "'Dates'[MonthName]", "measure": "Sum('Sales'[Quantity])"},
        base_dir=str(tmp_path),
    )
    assert res["bindings"]["measure"]["agg"] == "Sum"


# ---------------- Dev Server Lifecycle ----------------

def test_dev_server_lifecycle(tmp_path):
    """start_dev_server records pid info and stop_dev_server cleans it up."""
    PV.scaffold_visual("gauge", base_dir=str(tmp_path))
    res = PV.start_dev_server("gauge", base_dir=str(tmp_path), port=9999)
    assert res["ok"] is True
    assert res["port"] == 9999
    assert os.path.exists(res["pid_file"])

    stop_res = PV.stop_dev_server("gauge")
    assert stop_res["ok"] is True
    assert not os.path.exists(res["pid_file"])


# ---------------- Packaging & Version Bump ----------------

def test_package_visual_and_bump(tmp_path):
    """package_visual updates version and creates .pbiviz zip bundle."""
    PV.scaffold_visual("heatmap", base_dir=str(tmp_path))
    res = PV.package_visual("heatmap", bump="patch", base_dir=str(tmp_path))
    assert res["ok"] is True
    assert res["version"] == "1.0.1.0"
    pkg_path = res["package_path"]
    assert os.path.exists(pkg_path)

    # Inspect zip contents
    with zipfile.ZipFile(pkg_path, "r") as z:
        assert "package.json" in z.namelist()
        assert "resources/capabilities.json" in z.namelist()

    # Minor bump
    res2 = PV.package_visual("heatmap", bump="minor", base_dir=str(tmp_path))
    assert res2["version"] == "1.1.0.0"


# ---------------- Import, Catalog & Visual Query ----------------

def test_import_custom_visual(tmp_path):
    """import_custom_visual registers package in report.json and instantiates visual on page."""
    # Copy fixture report to tmp_path
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("my-card", base_dir=str(tmp_path))
    PV.bind_roles("my-card", FIXTURE_PBIP, {"category": "'Dates'[MonthName]", "measure": "[Total Sales]"}, base_dir=str(tmp_path))
    PV.package_visual("my-card", base_dir=str(tmp_path))

    imp_res = PV.import_custom_visual("my-card", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    assert imp_res["ok"] is True
    guid = imp_res["guid"]

    # Check report.json registration
    rj = json.loads((dest_rep / "definition" / "report.json").read_text(encoding="utf-8"))
    assert guid in rj.get("publicCustomVisuals", [])
    assert any(rp.get("name") == guid for rp in rj.get("resourcePackages", []))

    # Check package on disk
    pkg_file = dest_rep / "StaticResources" / "RegisteredResources" / f"{guid}.pbiviz"
    assert pkg_file.exists()

    # Check visual instance
    vis_file = dest_rep / "definition" / "pages" / "overview" / "visuals" / imp_res["visual_id"] / "visual.json"
    assert vis_file.exists()
    v_data = json.loads(vis_file.read_text(encoding="utf-8"))
    assert v_data["visual"]["visualType"] == guid
    assert "category" in v_data["visual"]["projections"]


def test_catalog_describe_custom_visual(tmp_path):
    """catalog describe resolves custom visual capabilities from registered package."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("funnel", base_dir=str(tmp_path))
    PV.package_visual("funnel", base_dir=str(tmp_path))
    imp_res = PV.import_custom_visual("funnel", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    guid = imp_res["guid"]

    table = CAT.describe_visual(guid, report_dir=str(dest_rep))
    assert table.name == f"visual_{guid}"
    roles = [r[0] for r in table.rows]
    assert "category" in roles
    assert "measure" in roles


def test_visual_query_custom_visual(tmp_path):
    """visual_query generates SUMMARIZECOLUMNS for custom visual instances."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("bubble", base_dir=str(tmp_path))
    PV.bind_roles("bubble", FIXTURE_PBIP, {"category": "'Dates'[MonthName]", "measure": "[Total Sales]"}, base_dir=str(tmp_path))
    imp_res = PV.import_custom_visual("bubble", str(dest_rep), page="Overview", base_dir=str(tmp_path))

    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    idx = N.ModelIndex(mod, rep)

    c_vis = next(v for v in rep.all_visuals() if v.id == imp_res["visual_id"])
    dax, notes = D.visual_query(c_vis, idx)
    assert "SUMMARIZECOLUMNS" in dax
    assert "'Dates'[MonthName]" in dax
    assert "[Total Sales]" in dax


# ---------------- Check Rules ----------------

def test_check_custom_visual_package_missing(tmp_path):
    """custom-visual-package-missing triggers when report.json says the report ships a .pbiviz and it is gone.

    Only the file is deleted: a `resourcePackages` entry of type `CustomVisual` is the report's own claim
    that it carries the package. (The old rule fired only once the entry was gone as well, so a package
    that was never committed passed.)"""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("sparkline", base_dir=str(tmp_path))
    imp_res = PV.import_custom_visual("sparkline", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    guid = imp_res["guid"]

    pkg_file = dest_rep / "StaticResources" / "RegisteredResources" / f"{guid}.pbiviz"
    pkg_file.unlink()

    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "custom-visual-package-missing" in kinds
    assert "custom-visual-guid-unregistered" not in kinds


def test_check_custom_visual_guid_unregistered(tmp_path):
    """custom-visual-guid-unregistered triggers when visualType not in publicCustomVisuals."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    # Point visual to unregistered custom GUID
    v_file = dest_rep / "definition" / "pages" / "overview" / "visuals" / "11111111111111111111" / "visual.json"
    data = json.loads(v_file.read_text(encoding="utf-8"))
    data["visual"]["visualType"] = "custom_unregistered_guid_123"
    v_file.write_text(json.dumps(data), encoding="utf-8")

    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "custom-visual-guid-unregistered" in kinds


def test_check_custom_visual_role_unfilled(tmp_path):
    """custom-visual-role-unfilled triggers when required role is not projected."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("sankey", base_dir=str(tmp_path))
    # Mark category required
    cap_file = tmp_path / "sankey" / "capabilities.json"
    caps = json.loads(cap_file.read_text(encoding="utf-8"))
    caps["dataRoles"][0]["required"] = True
    cap_file.write_text(json.dumps(caps), encoding="utf-8")

    PV.package_visual("sankey", base_dir=str(tmp_path))
    imp_res = PV.import_custom_visual("sankey", str(dest_rep), page="Overview", base_dir=str(tmp_path))

    # Remove projections from visual
    v_file = dest_rep / "definition" / "pages" / "overview" / "visuals" / imp_res["visual_id"] / "visual.json"
    v_data = json.loads(v_file.read_text(encoding="utf-8"))
    v_data["visual"]["projections"] = {}
    v_file.write_text(json.dumps(v_data), encoding="utf-8")

    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "custom-visual-role-unfilled" in kinds


def test_check_custom_visual_role_kind_mismatch(tmp_path):
    """custom-visual-role-kind-mismatch triggers when role kind doesn't match field kind."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("treemap", base_dir=str(tmp_path))
    PV.package_visual("treemap", base_dir=str(tmp_path))
    imp_res = PV.import_custom_visual("treemap", str(dest_rep), page="Overview", base_dir=str(tmp_path))

    # Project measure into category (Grouping) role
    v_file = dest_rep / "definition" / "pages" / "overview" / "visuals" / imp_res["visual_id"] / "visual.json"
    v_data = json.loads(v_file.read_text(encoding="utf-8"))
    v_data["visual"]["queryState"] = {
        "category": {
            "projections": [{"queryRef": "Total Sales", "measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Total Sales"}}]
        }
    }
    v_file.write_text(json.dumps(v_data), encoding="utf-8")

    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    findings = CK.check_report(rep, mod)
    kinds = [f.kind for f in findings]
    assert "custom-visual-role-kind-mismatch" in kinds


# ---------------- Where a visual comes from, and whether the tenant renders it ----------------

def _imported(tmp_path, name="variance-bars"):
    """A report carrying one visual imported from a .pbiviz file with `ad-pbiviz import`."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    PV.scaffold_visual(name, base_dir=str(tmp_path))
    PV.package_visual(name, base_dir=str(tmp_path))
    res = PV.import_custom_visual(name, str(dest_rep), page="Overview", base_dir=str(tmp_path))
    return dest_rep, res["guid"]


def _registered_as(dest_rep, guid, channel, disabled=False):
    """Re-register the imported visual the way the PBIR report schema records the other two channels."""
    rj_path = dest_rep / "definition" / "report.json"
    rj = json.loads(rj_path.read_text(encoding="utf-8"))
    rj["resourcePackages"] = [rp for rp in rj.get("resourcePackages", []) if rp.get("name") != guid]
    rj["publicCustomVisuals"] = [g for g in rj.get("publicCustomVisuals", []) if g != guid]
    if channel == "appsource":
        rj["publicCustomVisuals"].append(guid)
    else:
        rj["organizationCustomVisuals"] = [{"name": guid, "path": f"orgstore/{guid}", "disabled": disabled}]
    rj_path.write_text(json.dumps(rj), encoding="utf-8")
    (dest_rep / "StaticResources" / "RegisteredResources" / f"{guid}.pbiviz").unlink()


def _cv(dest_rep, facts=None):
    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    return [f for f in CK.check_report(rep, mod, facts) if f.kind.startswith("custom-visual")]


def test_check_a_correctly_imported_visual_is_clean(tmp_path):
    """Regression: check.py called json.load without importing json, the NameError was swallowed, and
    report.json was never read -- so every custom visual in every report was 'unregistered'."""
    dest_rep, _guid = _imported(tmp_path)
    assert _cv(dest_rep) == []


def test_check_an_appsource_visual_needs_no_package(tmp_path):
    """Power BI fetches AppSource visuals itself; only a private visual travels inside the report."""
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "appsource")
    assert _cv(dest_rep) == []


def test_check_an_organizational_store_visual_is_registered_and_needs_no_package(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org")
    assert _cv(dest_rep) == []


def test_check_a_store_visual_the_admin_switched_off_is_an_error(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org", disabled=True)
    assert [f.kind for f in _cv(dest_rep)] == ["custom-visual-store-disabled"]


def test_tenant_rules_run_only_when_facts_are_given(tmp_path):
    """Library callers that pass no facts see exactly the findings they saw before."""
    dest_rep, _guid = _imported(tmp_path)
    assert [f.kind for f in _cv(dest_rep, None)] == []


def test_org_only_tenant_blocks_a_file_visual_and_an_appsource_visual(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    blocked = _cv(dest_rep, {"pbi_custom_visuals": "org-only"})
    assert [(f.severity, f.kind) for f in blocked] == [("error", "custom-visual-tenant-blocked")]
    assert "a .pbiviz file" in blocked[0].message and "pbi-custom-visual" in blocked[0].hint

    _registered_as(dest_rep, guid, "appsource")
    blocked = _cv(dest_rep, {"pbi_custom_visuals": "org-only"})
    assert [(f.severity, f.kind) for f in blocked] == [("error", "custom-visual-tenant-blocked")]
    assert "AppSource" in blocked[0].message


def test_no_tenant_setting_reaches_an_organizational_store_visual(tmp_path):
    """Microsoft: visuals on the Organizational visuals page aren't affected by either setting."""
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org")
    for tenant in ("org-only", "certified-only"):
        assert _cv(dest_rep, {"pbi_custom_visuals": tenant}) == []


def test_certified_only_blocks_a_file_visual_and_an_unconfirmed_appsource_one(tmp_path):
    """A visual loaded from a file is never the certified one; an AppSource visual passes only once
    somebody has checked its certified badge and recorded the GUID."""
    dest_rep, guid = _imported(tmp_path)
    facts = {"pbi_custom_visuals": "certified-only"}
    assert [(f.severity, f.kind) for f in _cv(dest_rep, facts)] == [("error", "custom-visual-tenant-blocked")]
    _registered_as(dest_rep, guid, "appsource")
    assert [(f.severity, f.kind) for f in _cv(dest_rep, facts)] == \
        [("error", "custom-visual-certification-unconfirmed")]
    assert _cv(dest_rep, {**facts, "pbi_certified_visuals": f"otherVisual1, {guid}"}) == []


def test_allowed_tenant_warns_on_a_file_visual_and_passes_appsource(tmp_path):
    """Files render where the tenant allows them, so it is a warning, not a refusal: the visual still
    stops the day the tenant turns certified-only."""
    dest_rep, guid = _imported(tmp_path)
    rows = _cv(dest_rep, {"pbi_custom_visuals": "allowed"})
    assert [(f.severity, f.kind) for f in rows] == [("warning", "custom-visual-uncertified")]
    _registered_as(dest_rep, guid, "appsource")
    assert _cv(dest_rep, {"pbi_custom_visuals": "allowed"}) == []


def test_an_unrecorded_tenant_fails_closed(tmp_path):
    """Nobody wrote down what the tenant renders, so nothing from a file or AppSource passes."""
    dest_rep, guid = _imported(tmp_path)
    for facts in ({}, {"pbi_custom_visuals": "unknown"}):
        rows = _cv(dest_rep, facts)
        assert [(f.severity, f.kind) for f in rows] == [("error", "custom-visual-tenant-unknown")]
        assert guid in rows[0].message and "pbi_custom_visuals" in rows[0].hint


def test_a_misspelt_tenant_fact_warns_and_still_fails_closed(tmp_path):
    dest_rep, _guid = _imported(tmp_path)
    rows = _cv(dest_rep, {"pbi_custom_visuals": "blocked"})
    assert [(f.severity, f.kind) for f in rows] == [("warning", "custom-visual-tenant-fact-invalid"),
                                                   ("error", "custom-visual-tenant-unknown")]


def test_cli_check_reads_the_tenant_fact_from_agents_md(tmp_path, monkeypatch, capsys):
    """`ad-pbip check` runs from the project root, where AGENTS.md holds the fact."""
    import sys
    from agentdata import cli_pbip
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_DIR, project / "reports")
    _imported_into = project / "reports" / "Native.Report"
    shutil.rmtree(_imported_into)
    dest_rep, _guid = _imported(tmp_path)
    shutil.copytree(dest_rep, _imported_into)
    (project / "AGENTS.md").write_text("## Project facts\n- pbi_custom_visuals: org-only\n", encoding="utf-8")
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["ad-pbip", "check", "reports"])
    with pytest.raises(SystemExit) as ei:
        cli_pbip.main()
    out = capsys.readouterr().out
    assert ei.value.code == 1 and "custom-visual-tenant-blocked" in out


# ---------------- CLI Tests ----------------

def test_cli_pbiviz_commands(capsys, tmp_path, monkeypatch):
    """ad-pbiviz doctor, new, roles, package commands execute cleanly via CLI."""
    monkeypatch.chdir(tmp_path)

    # 1. doctor
    with pytest.raises(SystemExit) as exc:
        cli_pbiviz.main(["doctor"])
    assert exc.value.code in (0, 1)

    # 2. new
    with pytest.raises(SystemExit) as exc:
        cli_pbiviz.main(["new", "cli-chart"])
    assert exc.value.code == 0
    assert (tmp_path / "visuals" / "cli-chart" / "pbiviz.json").exists()

    # 3. roles
    with pytest.raises(SystemExit) as exc:
        cli_pbiviz.main(["roles", "cli-chart"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "category,Grouping" in out
    assert "measure,Measure" in out

    # 4. package
    with pytest.raises(SystemExit) as exc:
        cli_pbiviz.main(["package", "cli-chart", "--bump", "patch"])
    assert exc.value.code == 0
