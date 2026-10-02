"""Tests for Power BI custom visual development loop (ad-pbiviz and PBIR integration)."""
import copy
import json
import os
import re
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

    # the layout `pbiviz package` builds: package.json names resources/<guid>.pbiviz.json, which carries the rest
    guid = res["guid"]
    with zipfile.ZipFile(pkg_path, "r") as z:
        assert sorted(z.namelist()) == ["package.json", f"resources/{guid}.pbiviz.json"]
        package_json = json.loads(z.read("package.json"))
        pbiviz_json = json.loads(z.read(f"resources/{guid}.pbiviz.json"))
    assert package_json["resources"] == [{"resourceId": "rId0", "sourceType": 5, "file": f"resources/{guid}.pbiviz.json"}]
    assert package_json["metadata"] == {"pbivizjson": {"resourceId": "rId0"}}
    assert package_json["version"] == package_json["visual"]["version"] == "1.0.1.0"
    assert pbiviz_json["visual"]["guid"] == guid
    assert [r["name"] for r in pbiviz_json["capabilities"]["dataRoles"]] == ["category", "measure"]
    assert pbiviz_json["content"]["iconBase64"].startswith("data:image/png;base64,")

    # Minor bump
    res2 = PV.package_visual("heatmap", bump="minor", base_dir=str(tmp_path))
    assert res2["version"] == "1.1.0.0"


# ---------------- Import, Catalog & Visual Query ----------------

def _desktop_entry(guid):
    """The `resourcePackages` entry Desktop saves for a visual imported from a file, as in every Desktop-saved PBIP
    report checked (report schemas 1.1.0 to 3.3.0): one item, the package's pbiviz.json, relative to `resources/`."""
    return {"name": guid, "type": "CustomVisual",
            "items": [{"name": f"{guid}.pbiviz.json", "path": f"{guid}.pbiviz.json", "type": "CustomVisualMetadata"}]}


def test_import_custom_visual(tmp_path, monkeypatch):
    """import_custom_visual saves the visual as Desktop saves "Import a visual from a file", and places it on the page.

    Desktop extracts the .pbiviz into CustomVisuals/<guid>/ and registers it as a `CustomVisual` resource package.
    It leaves `publicCustomVisuals` alone: the report schema defines that as the AppSource visuals."""
    monkeypatch.chdir(tmp_path)
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)

    PV.scaffold_visual("my-card", base_dir=str(tmp_path))
    PV.bind_roles("my-card", FIXTURE_PBIP, {"category": "'Dates'[MonthName]", "measure": "[Total Sales]"}, base_dir=str(tmp_path))
    PV.package_visual("my-card", base_dir=str(tmp_path))

    imp_res = PV.import_custom_visual("my-card", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    assert imp_res["ok"] is True
    guid = imp_res["guid"]

    # report.json: the resource package, and nothing in the AppSource list
    rj = json.loads((dest_rep / "definition" / "report.json").read_text(encoding="utf-8"))
    assert "publicCustomVisuals" not in rj
    assert rj["resourcePackages"] == [_desktop_entry(guid)]

    # the package's own files, under CustomVisuals/<guid>/ and nowhere else
    folder = dest_rep / "CustomVisuals" / guid
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == \
        ["package.json", f"resources/{guid}.pbiviz.json"]
    package_json = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    assert package_json["resources"][0]["file"] == f"resources/{guid}.pbiviz.json"
    assert not list(dest_rep.rglob("*.pbiviz"))

    # Check visual instance
    vis_file = dest_rep / "definition" / "pages" / "overview" / "visuals" / imp_res["visual_id"] / "visual.json"
    assert vis_file.exists()
    v_data = json.loads(vis_file.read_text(encoding="utf-8"))
    assert v_data["visual"]["visualType"] == guid
    assert "category" in v_data["visual"]["projections"]


# A report.json as Desktop saves one with no custom visual, declaring report schema 3.1.0. The Native fixture's
# report.json predates that schema and does not validate against it.
DESKTOP_REPORT_3_1 = {
    "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.1.0/schema.json",
    "themeCollection": {"baseTheme": {"name": "CY24SU10", "type": "SharedResources",
                                      "reportVersionAtImport": {"visual": "1.8.50", "report": "2.0.50", "page": "1.3.50"}}},
    "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                          "items": [{"name": "CY24SU10", "path": "BaseThemes/CY24SU10.json", "type": "BaseTheme"}]}],
    "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized"},
}


def test_imported_report_json_validates_against_report_schema_3_1_0(tmp_path, monkeypatch):
    """Desktop refuses to open a report whose report.json breaks its schema (Microsoft's PBIP docs list that among
    the blocking errors). The entry import used to write broke report schema 3.1.0 twice: a `ResourcePackage`
    takes no `path`, and requires `items`."""
    import pbir_schema as S  # jsonschema, from the dev extra
    monkeypatch.chdir(tmp_path)
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    rj_path = dest_rep / "definition" / "report.json"
    rj_path.write_text(json.dumps(DESKTOP_REPORT_3_1, indent=2), encoding="utf-8")
    assert S.errors(DESKTOP_REPORT_3_1) == []

    PV.scaffold_visual("schema-check", base_dir=str(tmp_path))
    guid = PV.import_custom_visual("schema-check", str(dest_rep), page="Overview", base_dir=str(tmp_path))["guid"]

    written = json.loads(rj_path.read_text(encoding="utf-8"))
    assert S.errors(written) == []
    assert written["resourcePackages"] == DESKTOP_REPORT_3_1["resourcePackages"] + [_desktop_entry(guid)]

    # the same schema refuses what import used to write
    old = {**DESKTOP_REPORT_3_1, "publicCustomVisuals": [guid], "resourcePackages": [
        *DESKTOP_REPORT_3_1["resourcePackages"],
        {"name": guid, "type": "CustomVisual", "path": f"StaticResources/RegisteredResources/{guid}.pbiviz"}]}
    problems = S.errors(old)
    assert len(problems) == 2 and all(p.startswith("$.resourcePackages[1]: ") for p in problems), problems
    assert any("'items'" in p for p in problems) and any("'path'" in p for p in problems), problems


def test_importing_again_replaces_the_entry_and_the_files(tmp_path, monkeypatch):
    """A second import (a newer build, or a report the old import wrote) leaves one entry, in Desktop's shape, and
    only the files of the package it installed."""
    monkeypatch.chdir(tmp_path)
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    PV.scaffold_visual("reimport", base_dir=str(tmp_path))
    guid = PV.import_custom_visual("reimport", str(dest_rep), page="Overview", base_dir=str(tmp_path))["guid"]

    rj_path = dest_rep / "definition" / "report.json"
    rj = json.loads(rj_path.read_text(encoding="utf-8"))
    rj["resourcePackages"] = [{"name": guid, "type": "CustomVisual",
                               "path": f"StaticResources/RegisteredResources/{guid}.pbiviz"}]
    rj_path.write_text(json.dumps(rj), encoding="utf-8")
    stale = dest_rep / "CustomVisuals" / guid / "resources" / "stale.pbiviz.json"
    stale.write_text("{}", encoding="utf-8")

    PV.import_custom_visual("reimport", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    assert json.loads(rj_path.read_text(encoding="utf-8"))["resourcePackages"] == [_desktop_entry(guid)]
    assert not stale.exists()


def test_import_refuses_a_package_that_names_no_pbiviz_json(tmp_path, monkeypatch):
    """An item whose file is missing hands Desktop a report it cannot load. So a package not laid out the way
    `pbiviz package` builds it, like the one `ad-pbiviz package` used to write, stops the import before any write."""
    monkeypatch.chdir(tmp_path)
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    PV.scaffold_visual("old-layout", base_dir=str(tmp_path))
    v_dir = tmp_path / "old-layout"
    (v_dir / "dist").mkdir()
    with zipfile.ZipFile(v_dir / "dist" / "old-layout.1.0.0.0.pbiviz", "w") as z:
        z.write(v_dir / "pbiviz.json", arcname="package.json")
        z.write(v_dir / "capabilities.json", arcname="resources/capabilities.json")
    before = (dest_rep / "definition" / "report.json").read_bytes()

    with pytest.raises(PV.PbivizError, match="pbiviz package") as ei:
        PV.import_custom_visual("old-layout", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    assert "ad-pbiviz package old-layout" in ei.value.hint

    (v_dir / "dist" / "old-layout.1.0.0.0.pbiviz").write_bytes(b"not a zip")
    with pytest.raises(PV.PbivizError, match="not a zip file"):
        PV.import_custom_visual("old-layout", str(dest_rep), page="Overview", base_dir=str(tmp_path))
    assert (dest_rep / "definition" / "report.json").read_bytes() == before
    assert not (dest_rep / "CustomVisuals").exists()


def test_capabilities_still_read_where_import_used_to_put_the_package(tmp_path):
    """`ad-pbip check` still reads the roles of a report the old import wrote: a .pbiviz of the old layout under
    StaticResources/RegisteredResources/."""
    PV.scaffold_visual("legacy", base_dir=str(tmp_path))
    v_dir = tmp_path / "legacy"
    guid = json.loads((v_dir / "pbiviz.json").read_text(encoding="utf-8"))["visual"]["guid"]
    reg = tmp_path / "Old.Report" / "StaticResources" / "RegisteredResources"
    reg.mkdir(parents=True)
    with zipfile.ZipFile(reg / f"{guid}.pbiviz", "w") as z:
        z.write(v_dir / "pbiviz.json", arcname="package.json")
        z.write(v_dir / "capabilities.json", arcname="resources/capabilities.json")
    caps = PV.read_visual_capabilities(guid, str(tmp_path / "Old.Report"))
    assert [r["name"] for r in caps["dataRoles"]] == ["category", "measure"]


def test_catalog_describe_finds_an_imported_visual_under_the_working_directory(tmp_path, monkeypatch):
    """`ad-pbip catalog describe <guid>` names no report folder: it finds CustomVisuals/<guid>/ below the cwd."""
    monkeypatch.chdir(tmp_path)
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    PV.scaffold_visual("cwd-funnel", base_dir=str(tmp_path))
    guid = PV.import_custom_visual("cwd-funnel", str(dest_rep), page="Overview", base_dir=str(tmp_path))["guid"]
    assert [r[0] for r in CAT.describe_visual(guid).rows] == ["category", "measure"]


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

    shutil.rmtree(dest_rep / "CustomVisuals" / guid)

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
#
# The enterprise blocks every custom visual that is not Microsoft-certified (the operator, release 0.18.0).
# So a non-certified visual is an error on every tenant, and no fact downgrades it: a .pbiviz built with
# the SDK while `pbi_sdk_visuals` is blocked, an AppSource visual whose GUID is not in pbi_certified_visuals,
# an organizational-store visual that is neither certified nor the operator's org pick. Before 0.18.0 a
# file visual on an `allowed` tenant was only a warning; that warning now needs `pbi_sdk_visuals: approved`.

APPROVED = {"pbi_sdk_visuals": "approved", "pbi_sdk_workspace": "Sales Workspace"}


def _imported(tmp_path, name="variance-bars"):
    """A report carrying one visual imported from a .pbiviz file with `ad-pbiviz import`."""
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    PV.scaffold_visual(name, base_dir=str(tmp_path))
    PV.package_visual(name, base_dir=str(tmp_path))
    res = PV.import_custom_visual(name, str(dest_rep), page="Overview", base_dir=str(tmp_path))
    return dest_rep, res["guid"]


def _registered_as(dest_rep, guid, channel, disabled=False):
    """Re-register the imported visual the way a report records the other channels, and return its visualType.

    `appsource`: listed in `publicCustomVisuals`. `org`: what Microsoft's authoring guide says registers a store
    visual, a `resourcePackages` entry of type `OrganizationalStoreCustomVisual` named `<GUID>_OrgStore`, and
    the same `<GUID>_OrgStore` as the visual's type. `org-root`: only the root `organizationCustomVisuals`
    array, which is schema-valid and registers nothing."""
    rj_path = dest_rep / "definition" / "report.json"
    rj = json.loads(rj_path.read_text(encoding="utf-8"))
    rj["resourcePackages"] = [rp for rp in rj.get("resourcePackages", []) if rp.get("name") != guid]
    rj["publicCustomVisuals"] = [g for g in rj.get("publicCustomVisuals", []) if g != guid]
    vtype = guid
    if channel == "appsource":
        rj["publicCustomVisuals"].append(guid)
    elif channel == "org":
        vtype = guid + "_OrgStore"
        rj["resourcePackages"].append({"name": vtype, "type": "OrganizationalStoreCustomVisual", "items": [
            {"name": f"resources/{vtype}.pbiviz.json", "path": "", "type": "CustomVisualMetadata"}]})
    else:
        rj["organizationCustomVisuals"] = [{"name": guid, "path": f"orgstore/{guid}", "disabled": disabled}]
    rj_path.write_text(json.dumps(rj), encoding="utf-8")
    shutil.rmtree(dest_rep / "CustomVisuals" / guid)
    for vj in dest_rep.rglob("visual.json"):
        data = json.loads(vj.read_text(encoding="utf-8"))
        if (data.get("visual") or {}).get("visualType") == guid:
            data["visual"]["visualType"] = vtype
            vj.write_text(json.dumps(data), encoding="utf-8")
    return vtype


def _cv(dest_rep, facts=None):
    rep = P.load_report(str(dest_rep))
    mod = N.load_model(FIXTURE_MODEL)
    return [f for f in CK.check_report(rep, mod, facts) if f.kind.startswith("custom-visual")]


def _kinds(rows):
    return [(f.severity, f.kind) for f in rows]


def test_check_a_correctly_imported_visual_is_registered_and_packaged(tmp_path):
    """Regression: check.py called json.load without importing json, the NameError was swallowed, and
    report.json was never read -- so every custom visual in every report was 'unregistered'. Registered and
    packaged, the one finding left is the enterprise floor: it is an SDK visual."""
    dest_rep, _guid = _imported(tmp_path)
    assert _kinds(_cv(dest_rep)) == [("error", "custom-visual-uncertified")]
    assert _kinds(_cv(dest_rep, {**APPROVED, "pbi_custom_visuals": "allowed"})) == \
        [("warning", "custom-visual-uncertified")]


def test_the_certification_floor_runs_without_facts(tmp_path):
    """Library callers that pass no facts get the floor (nothing is certified, SDK visuals are blocked), and
    no tenant rule: they never said what the tenant renders."""
    dest_rep, guid = _imported(tmp_path)
    rows = _cv(dest_rep, None)
    assert _kinds(rows) == [("error", "custom-visual-uncertified")]
    assert "workspace approval" in rows[0].message and "pbi-custom-visual" in rows[0].hint
    _registered_as(dest_rep, guid, "appsource")
    assert _kinds(_cv(dest_rep, None)) == [("error", "custom-visual-certification-unconfirmed")]


def test_an_uncertified_visual_is_an_error_on_an_allowed_tenant(tmp_path):
    """The behaviour change: `pbi_custom_visuals: allowed` no longer downgrades a non-certified visual."""
    dest_rep, guid = _imported(tmp_path)
    for facts in ({"pbi_custom_visuals": "allowed"}, {"pbi_custom_visuals": "allowed", "pbi_sdk_visuals": "blocked"}):
        rows = _cv(dest_rep, facts)
        assert _kinds(rows) == [("error", "custom-visual-uncertified")]
        assert "pbi_sdk_visuals: blocked" in rows[0].message
    _registered_as(dest_rep, guid, "appsource")
    assert _kinds(_cv(dest_rep, {"pbi_custom_visuals": "allowed"})) == \
        [("error", "custom-visual-certification-unconfirmed")]
    assert _cv(dest_rep, {"pbi_custom_visuals": "allowed", "pbi_certified_visuals": guid}) == []


def test_check_an_appsource_visual_needs_no_package(tmp_path):
    """Power BI fetches AppSource visuals itself; only a private visual travels inside the report."""
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "appsource")
    assert _cv(dest_rep, {"pbi_custom_visuals": "certified-only", "pbi_certified_visuals": guid}) == []


def test_an_organizational_store_package_registers_the_visual_and_needs_no_package(tmp_path):
    """Microsoft's guide: an `OrganizationalStoreCustomVisual` package named `<GUID>_OrgStore` registers it;
    the certified allow-list is matched on the GUID inside the suffix."""
    dest_rep, guid = _imported(tmp_path)
    vtype = _registered_as(dest_rep, guid, "org")
    assert vtype.endswith("_OrgStore")
    assert _cv(dest_rep, {"pbi_custom_visuals": "certified-only", "pbi_certified_visuals": guid}) == []
    rows = _cv(dest_rep, None)
    assert _kinds(rows) == [("error", "custom-visual-org-unapproved")]
    assert "pbi_org_visuals" in rows[0].hint


def test_an_org_visual_the_operator_picked_passes_only_where_the_tenant_is_org_only(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    vtype = _registered_as(dest_rep, guid, "org")
    for listed in (guid, vtype, f"otherVisual, {vtype.upper()}"):
        assert _cv(dest_rep, {"pbi_custom_visuals": "org-only", "pbi_org_visuals": listed}) == []
    for tenant in ("allowed", "certified-only", ""):
        rows = _cv(dest_rep, {"pbi_custom_visuals": tenant, "pbi_org_visuals": guid})
        assert _kinds(rows) == [("error", "custom-visual-org-unapproved")]
    assert _kinds(_cv(dest_rep, {"pbi_custom_visuals": "org-only"})) == [("error", "custom-visual-org-unapproved")]


def test_a_bare_root_organization_entry_does_not_register_the_visual(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org-root")
    rows = _cv(dest_rep, {"pbi_custom_visuals": "certified-only", "pbi_certified_visuals": guid})
    assert _kinds(rows) == [("warning", "custom-visual-org-root-entry")]
    assert "does not register" in rows[0].message and f"{guid}_OrgStore" in rows[0].hint


def test_a_bare_guid_next_to_its_orgstore_package_is_unregistered_and_says_why(tmp_path):
    """A `visualType` without the `_OrgStore` suffix draws the empty placeholder even with the package there."""
    dest_rep, guid = _imported(tmp_path)
    vtype = _registered_as(dest_rep, guid, "org")
    for vj in dest_rep.rglob("visual.json"):
        data = json.loads(vj.read_text(encoding="utf-8"))
        if (data.get("visual") or {}).get("visualType") == vtype:
            data["visual"]["visualType"] = guid
            vj.write_text(json.dumps(data), encoding="utf-8")
    rows = _cv(dest_rep, {"pbi_custom_visuals": "certified-only", "pbi_certified_visuals": guid})
    assert _kinds(rows) == [("error", "custom-visual-guid-unregistered")]
    assert vtype in rows[0].hint


def test_check_a_store_visual_the_admin_switched_off_is_an_error(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org-root", disabled=True)
    assert _kinds(_cv(dest_rep, {"pbi_certified_visuals": guid})) == \
        [("warning", "custom-visual-org-root-entry"), ("error", "custom-visual-store-disabled")]


def test_org_only_tenant_blocks_a_file_visual_and_an_appsource_visual(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    blocked = _cv(dest_rep, {**APPROVED, "pbi_custom_visuals": "org-only"})
    assert _kinds(blocked) == [("error", "custom-visual-tenant-blocked")]
    assert "a .pbiviz file" in blocked[0].message and "pbi-custom-visual" in blocked[0].hint

    _registered_as(dest_rep, guid, "appsource")
    blocked = _cv(dest_rep, {"pbi_custom_visuals": "org-only", "pbi_certified_visuals": guid})
    assert _kinds(blocked) == [("error", "custom-visual-tenant-blocked")]
    assert "AppSource" in blocked[0].message


def test_no_tenant_setting_reaches_a_certified_organizational_store_visual(tmp_path):
    """Microsoft: visuals on the Organizational visuals page aren't affected by either setting."""
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "org")
    for tenant in ("org-only", "certified-only", "allowed"):
        assert _cv(dest_rep, {"pbi_custom_visuals": tenant, "pbi_certified_visuals": guid}) == []


def test_certified_only_blocks_a_file_visual_and_an_unconfirmed_appsource_one(tmp_path):
    """A visual loaded from a file is never the certified one, even with SDK visuals approved; an AppSource
    visual passes only once somebody has checked its certified badge and recorded the GUID."""
    dest_rep, guid = _imported(tmp_path)
    facts = {"pbi_custom_visuals": "certified-only"}
    assert _kinds(_cv(dest_rep, facts)) == [("error", "custom-visual-uncertified")]
    assert _kinds(_cv(dest_rep, {**facts, **APPROVED})) == [("error", "custom-visual-tenant-blocked")]
    _registered_as(dest_rep, guid, "appsource")
    assert _kinds(_cv(dest_rep, facts)) == [("error", "custom-visual-certification-unconfirmed")]
    assert _cv(dest_rep, {**facts, "pbi_certified_visuals": f"otherVisual1, {guid}"}) == []


def test_an_approved_sdk_visual_is_held_to_its_workspace(tmp_path):
    """`pbi_sdk_visuals: approved` is the operator's word once workspace approval exists: the file visual is
    a warning on an `allowed` tenant, and it ships to the approved workspace only."""
    dest_rep, _guid = _imported(tmp_path)
    facts = {"pbi_custom_visuals": "allowed", "pbi_sdk_visuals": "approved"}
    assert _kinds(_cv(dest_rep, facts)) == [("warning", "custom-visual-uncertified"),
                                            ("warning", "custom-visual-sdk-workspace-unrecorded")]
    facts["pbi_sdk_workspace"] = "Sales Workspace"
    assert _kinds(_cv(dest_rep, facts)) == [("warning", "custom-visual-uncertified")]
    assert _kinds(_cv(dest_rep, {**facts, "pbi_workspace": "sales workspace"})) == \
        [("warning", "custom-visual-uncertified")]
    rows = _cv(dest_rep, {**facts, "pbi_workspace": "Ops Workspace"})
    assert _kinds(rows) == [("warning", "custom-visual-uncertified"), ("error", "custom-visual-sdk-workspace")]
    assert "Sales Workspace" in rows[1].message and "Ops Workspace" in rows[1].message
    rep = P.load_report(str(dest_rep))
    assert [f.kind for f in CK.custom_visual_delivery(rep, facts, ("ws-1", "Ops Workspace"))
            if f.severity == "error"] == ["custom-visual-sdk-workspace"]
    assert [f.kind for f in CK.custom_visual_delivery(rep, {**facts, "pbi_workspace": "Ops Workspace"}, ())
            if f.severity == "error"] == []


def test_an_unrecorded_tenant_fails_closed(tmp_path):
    """Nobody wrote down what the tenant renders, so even a certified AppSource visual does not pass."""
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "appsource")
    for facts in ({"pbi_certified_visuals": guid}, {"pbi_certified_visuals": guid, "pbi_custom_visuals": "unknown"}):
        rows = _cv(dest_rep, facts)
        assert _kinds(rows) == [("error", "custom-visual-tenant-unknown")]
        assert guid in rows[0].message and "pbi_custom_visuals" in rows[0].hint


def test_a_misspelt_tenant_fact_warns_and_still_fails_closed(tmp_path):
    dest_rep, guid = _imported(tmp_path)
    _registered_as(dest_rep, guid, "appsource")
    rows = _cv(dest_rep, {"pbi_custom_visuals": "blocked", "pbi_certified_visuals": guid})
    assert _kinds(rows) == [("warning", "custom-visual-tenant-fact-invalid"), ("error", "custom-visual-tenant-unknown")]


def test_a_misspelt_sdk_fact_is_read_as_blocked(tmp_path):
    dest_rep, _guid = _imported(tmp_path)
    rows = _cv(dest_rep, {"pbi_custom_visuals": "allowed", "pbi_sdk_visuals": "yes"})
    assert _kinds(rows) == [("warning", "custom-visual-sdk-fact-invalid"), ("error", "custom-visual-uncertified")]


def test_cli_check_reads_the_facts_from_agents_md(tmp_path, monkeypatch, capsys):
    """`ad-pbip check` runs from the project root, where AGENTS.md holds the facts."""
    import sys
    from agentdata import cli_pbip
    project = tmp_path / "project"
    shutil.copytree(FIXTURE_DIR, project / "reports")
    _imported_into = project / "reports" / "Native.Report"
    shutil.rmtree(_imported_into)
    dest_rep, _guid = _imported(tmp_path)
    shutil.copytree(dest_rep, _imported_into)
    monkeypatch.chdir(project)
    for facts, kind in (("- pbi_custom_visuals: allowed\n", "custom-visual-uncertified"),
                        ("- pbi_custom_visuals: org-only\n- pbi_sdk_visuals: approved\n",
                         "custom-visual-tenant-blocked")):
        (project / "AGENTS.md").write_text("## Project facts\n" + facts, encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["ad-pbip", "check", "reports"])
        with pytest.raises(SystemExit) as ei:
            cli_pbip.main()
        out = capsys.readouterr().out
        assert ei.value.code == 1 and kind in out


def test_the_authoring_catalog_holds_no_custom_or_script_visual():
    """`ad-pbip visual add` takes catalog types only, so it can never add a custom visual (or an R or Python
    one, which needs a runtime and packages: external packaging). Deneb has its own verb."""
    types = set(CAT.load_catalog()["visuals"])
    assert not types & {"rScript", "pythonVisual", "scriptVisual"}
    assert not any(t.endswith("_OrgStore") or "deneb" in t.lower() or re.search(r"[0-9A-F]{16}", t) for t in types)


def test_visual_add_refuses_a_custom_visual_type(tmp_path):
    from agentdata.pbip import author as AU
    from agentdata.pbip import deneb as DN
    dest_rep = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest_rep)
    for vtype in (DN.GUID, DN.GUID + "_OrgStore", "pythonVisual"):
        with pytest.raises(KeyError, match="not found in catalog"):
            AU.visual_add(str(dest_rep), "Overview", vtype)


# ---------------- CLI Tests ----------------

def _pbiviz(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli_pbiviz.main(argv)
    return exc.value.code, capsys.readouterr().out


def test_cli_pbiviz_commands(capsys, tmp_path, monkeypatch):
    """ad-pbiviz doctor, new, roles, package commands execute cleanly via CLI, once the operator has written
    `pbi_sdk_visuals: approved` (workspace approval for SDK visuals)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("- pbi_sdk_visuals: approved\n- pbi_sdk_workspace: Sales\n", encoding="utf-8")

    # 1. doctor: the gate first, then the toolchain
    code, out = _pbiviz(["doctor"], capsys)
    assert code in (0, 1)
    assert out.index("sdk_visuals,ok") < out.index("node,")

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


@pytest.mark.parametrize("facts", ["", "- pbi_sdk_visuals: blocked\n", "- pbi_sdk_visuals: yes please\n"])
def test_sdk_verbs_refuse_until_the_operator_approves_sdk_visuals(capsys, tmp_path, monkeypatch, facts):
    """The enterprise blocks non-certified visuals; SDK visuals wait on workspace approval, and their toolchain
    (Node.js, npm, powerbi-visuals-tools) is outside te2, dscmd and az. Absent or misspelt reads as blocked."""
    monkeypatch.chdir(tmp_path)
    if facts:
        (tmp_path / "AGENTS.md").write_text(facts, encoding="utf-8")
    PV.scaffold_visual("kept", base_dir="visuals")
    for argv in (["new", "cli-chart"], ["dev", "kept"], ["stop", "kept"], ["package", "kept"],
                 ["import", "kept", "--pbip", str(tmp_path), "--page", "Overview"]):
        code, out = _pbiviz(argv, capsys)
        assert code == 2, argv
        assert "code: sdk_visuals_blocked" in out and f"ad-pbiviz {argv[0]} refused" in out
        assert "workspace approval" in out and "pbi_sdk_visuals: approved" in out
        assert "te2, dscmd and az" in out and "npm install" not in out
    assert not (tmp_path / "visuals" / "cli-chart").exists()
    assert not (tmp_path / "visuals" / "kept" / "dist").exists()


def test_doctor_reports_the_gate_first_and_offers_no_toolchain_while_blocked(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def probed(*_a, **_k):
        raise AssertionError("the SDK toolchain was probed while SDK visuals are blocked")

    monkeypatch.setattr(PV, "doctor", probed)
    code, out = _pbiviz(["doctor"], capsys)
    assert code == 1 and "ok: false" in out and "code: sdk_visuals_blocked" in out
    assert out.index("sdk_visuals,blocked") < out.index("toolchain,not_offered")
    for install in ("npm install", "nodejs.org", "--install-cert"):
        assert install not in out


def test_the_verbs_that_need_no_sdk_still_work_while_blocked(capsys, tmp_path, monkeypatch):
    """`roles` and `bind` read a visual's capabilities.json; `candidate(s)` log a need. None needs Node."""
    monkeypatch.chdir(tmp_path)
    PV.scaffold_visual("kept", base_dir="visuals")
    code, out = _pbiviz(["roles", "kept"], capsys)
    assert code == 0 and "category,Grouping" in out
    code, out = _pbiviz(["bind", "kept", "--pbip", FIXTURE_PBIP, "--role", "category='Dates'[MonthName]",
                         "--role", "measure=[Total Sales]"], capsys)
    assert code == 0 and "bindings" in out
    code, out = _pbiviz(["candidates"], capsys)
    assert code == 0 and "count: 0" in out


def test_the_desktop_capability_row_does_not_offer_npm_while_blocked(tmp_path, monkeypatch):
    from agentdata.pbip import desktop as DT
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(DT.shutil, "which", lambda name: f"/opt/{name}")
    row = next(c for c in DT.capabilities(run=lambda *a, **k: (1, "", "")) if c["capability"] == "pbiviz")
    assert row["available"] is False and row["via"] == "blocked" and "not offered" in row["evidence"]
    (tmp_path / "AGENTS.md").write_text("- pbi_sdk_visuals: approved\n", encoding="utf-8")
    row = next(c for c in DT.capabilities(run=lambda *a, **k: (1, "", "")) if c["capability"] == "pbiviz")
    assert row["available"] is True and row["via"] == "npm" and row["evidence"] == "/opt/pbiviz"
