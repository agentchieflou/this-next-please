"""PBIR authoring on the schema set Power BI Desktop 2.157 (August 2026) writes.

What we write copies the `$schema` its kind already has in the project, and takes Desktop 2.157's version only for a
kind the project has none of (agentdata/pbip/pbir.py DESKTOP_SCHEMAS). Either way the file validates against the schema
it names, vendored byte for byte under agentdata/pbip/schema/fabric/. The fixture tests/fixtures/pbip/desktop-2157/ is a
project at those versions; the older fixtures stay, and keep their versions.
"""
import glob
import json
import os
import re
import shutil
from pathlib import Path

import pytest

import pbir_schema as S  # jsonschema, from the dev extra
from agentdata.cli_pbip import main
from agentdata.pbip import author as AU
from agentdata.pbip import catalog as CAT
from agentdata.pbip import check as CK
from agentdata.pbip import normalize as N
from agentdata.pbip import pbir as P

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
D2157 = FIXTURES / "pbip" / "desktop-2157"
REPORT = "Desktop2157.Report"
PAGE = "3f5e7a9b1c2d4e6f8a0b"
SAMPLE = FIXTURES / "sample.pbip"
NATIVE = FIXTURES / "pbip" / "native"
SAVED_2_4_0 = FIXTURES / "pbip" / "desktop-saved" / "bcapps-sales-99a8cdce74b55c10789f.visual.json"


def _load(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def _version(path):
    return P.schema_version(_load(path)["$schema"])


@pytest.fixture
def d2157(tmp_path):
    target = tmp_path / "d2157"
    shutil.copytree(D2157, target)
    return target


@pytest.fixture
def empty(tmp_path):
    """A report with nothing in it yet: no page, visual or bookmark, so nothing to copy a version from."""
    rep = tmp_path / "Empty.Report"
    (rep / "definition").mkdir(parents=True)
    (rep / "definition.pbir").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byConnection": {"connectionString": "semanticmodelid=0"}}}), "utf-8")
    (rep / "definition" / "report.json").write_text(json.dumps(
        {"$schema": P.schema_url("report"), "themeCollection": {}}), "utf-8")
    return rep


def test_the_defaults_are_what_desktop_2157_writes_and_every_one_is_vendored():
    assert P.DESKTOP_RELEASE == "2.157"
    assert P.DESKTOP_SCHEMAS == {
        "report": "3.3.0", "page": "2.1.0", "pagesMetadata": "1.1.0", "visualContainer": "2.12.0",
        "visualContainerMobileState": "2.7.0", "bookmark": "2.1.0", "bookmarksMetadata": "1.0.0",
        "versionMetadata": "1.0.0", "reportExtension": "1.0.0",
    }
    authored = ("report", "page", "pagesMetadata", "visualContainer", "bookmark", "bookmarksMetadata",
                "versionMetadata", "reportExtension")
    assert [k for k in authored if not S.vendored(S.DESKTOP_2157[k])] == []
    source = (ROOT / "agentdata" / "pbip" / "schema" / "fabric" / "SOURCE").read_text("utf-8")
    assert re.search(r"^commit: [0-9a-f]{40}", source, re.M)


def test_every_file_of_the_2157_fixture_is_at_desktop_2157s_version_and_validates():
    files = sorted(glob.glob(str(D2157 / REPORT / "definition" / "**" / "*.json"), recursive=True))
    assert len(files) == 9
    for f in files:
        url = _load(f)["$schema"]
        kind = P.SCHEMA_URL.search(url)["kind"]
        assert P.schema_version(url) == P.DESKTOP_SCHEMAS[kind], f
        assert S.file_errors(f) == [], f
    assert S.file_errors(D2157 / REPORT / "definition.pbir") == []


def test_a_page_visuals_and_a_bookmark_authored_into_an_empty_report_validate_against_2157(empty):
    page = AU.page_add(str(empty), "Overview")
    assert page["schema"] == "page 2.1.0, 2.157 default"
    assert page["pages_schema"] == "pagesMetadata 1.1.0, 2.157 default"
    first = AU.visual_add(str(empty), "Overview", "clusteredColumnChart", title="Sales by region",
                          fields=["'Sales'[Region]", "'Sales'[Total Sales]"])
    assert first["schema"] == "visualContainer 2.12.0, 2.157 default"
    added = [first]
    for vtype, fields, pos in (("listSlicer", ["'Sales'[Region]"], (540, 20, 200, 300)),
                               ("advancedSlicerVisual", ["'Sales'[Region]", "'Sales'[Total Sales]"], (760, 20, 300, 100)),
                               ("textSlicer", ["'Sales'[Region]"], (760, 140, 300, 80)),
                               ("kpi", ["'Sales'[Total Sales]", "'Dates'[Date]", "'Sales'[Target]"], (20, 340, 300, 200)),
                               ("azureMap", ["'Geo'[City]", "'Sales'[Total Sales]"], (340, 340, 500, 300))):
        res = AU.visual_add(str(empty), "Overview", vtype, fields=fields, position=pos)
        # from whichever visual already here sorts first: every one says 2.12.0
        assert res["schema"].startswith(f"visualContainer 2.12.0, copied from definition/pages/{page['page_id']}/"), res
        added.append(res)
    bm = AU.bookmark_add(str(empty), "Default view", "Overview", visuals=[first["visual_id"]])
    assert bm["schema"] == "bookmark 2.1.0, 2.157 default"
    assert bm["bookmarks_schema"] == "bookmarksMetadata 1.0.0, 2.157 default"

    written = [page["path"], *(r["path"] for r in added), bm["path"],
               empty / "definition" / "pages" / "pages.json", empty / "definition" / "bookmarks" / "bookmarks.json"]
    for f in written:
        assert S.file_errors(f) == [], f
    kpi = _load(added[4]["path"])["visual"]["query"]["queryState"]
    assert list(kpi) == ["Indicator", "TrendLine", "Goal"]
    assert list(_load(added[5]["path"])["visual"]["query"]["queryState"]) == ["Category", "Size"]


def test_a_new_visual_copies_the_2_4_0_its_report_already_has(d2157):
    visuals = d2157 / REPORT / "definition" / "pages" / PAGE / "visuals"
    shutil.rmtree(visuals)
    saved = _load(SAVED_2_4_0)
    (visuals / saved["name"]).mkdir(parents=True)
    shutil.copyfile(SAVED_2_4_0, visuals / saved["name"] / "visual.json")

    res = AU.visual_add(str(d2157), "Overview", "listSlicer", fields=["'Sales'[Region]"], position=(24, 600, 240, 300))
    assert _version(res["path"]) == "2.4.0"
    assert res["schema"] == (f"visualContainer 2.4.0, copied from definition/pages/{PAGE}/visuals/{saved['name']}"
                             "/visual.json")
    # the page and bookmark kinds keep the fixture's own 2.157 versions
    assert AU.page_add(str(d2157), "Detail")["schema"] == f"page 2.1.0, copied from definition/pages/{PAGE}/page.json"


def test_an_older_project_keeps_its_versions_and_takes_the_highest_when_they_mix(tmp_path):
    target = tmp_path / "sample"
    shutil.copytree(SAMPLE, target)
    assert _version(AU.page_add(str(target), "Next")["path"]) == "1.0.0"
    assert _version(AU.visual_add(str(target), "page1", "cardVisual", fields=["'Sales'[Margin]"],
                                  position=(700, 400, 200, 100))["path"]) == "1.0.0"
    # a visual Desktop saved at 2.4.0 beside the 1.0.0 ones: the newer is the one a Desktop that reads both wrote
    saved = _load(SAVED_2_4_0)
    dest = target / "Sample.Report" / "definition" / "pages" / "page2" / "visuals" / saved["name"]
    dest.mkdir(parents=True)
    shutil.copyfile(SAVED_2_4_0, dest / "visual.json")
    assert _version(AU.visual_add(str(target), "page1", "cardVisual", fields=["'Sales'[Margin]"],
                                  position=(700, 520, 200, 100))["path"]) == "2.4.0"


def test_report_extensions_json_is_read_and_so_is_the_singular(d2157):
    report = P.load_report(str(d2157))
    assert [(m["entity"], m["name"], m["file"]) for m in report.extension_measures] == [
        ("Sales", "Sales Uplift", "definition/reportExtensions.json")]
    assert [m["file"] for m in P.load_report(str(NATIVE)).extension_measures] == ["definition/reportExtension.json"]

    ext = d2157 / REPORT / "definition" / "reportExtensions.json"
    data = _load(ext)
    data["entities"][0]["name"] = "Gone"
    ext.write_text(json.dumps(data), "utf-8")
    model, report, _ = N.load_all(str(d2157))
    kinds = {(f.kind, f.where) for f in CK.check_report(report, model)}
    assert ("extension-entity-missing", "definition/reportExtensions.json") in kinds


def test_bookmark_add_writes_the_file_desktop_reads_and_lists_it_in_the_index(d2157):
    bookmarks = d2157 / REPORT / "definition" / "bookmarks"
    res = AU.bookmark_add(str(d2157), "Card only", "Overview", visuals=["6b8d0f2a4c6e8a0b2d4f"])
    assert Path(res["path"]) == bookmarks / f"{res['name']}.bookmark.json"
    assert res["schema"] == "bookmark 2.1.0, copied from definition/bookmarks/7c9e1a3b5d7f9b1d3f5a.bookmark.json"
    assert "bookmarks_schema" not in res
    assert _load(bookmarks / "bookmarks.json")["items"] == [{"name": "7c9e1a3b5d7f9b1d3f5a"}, {"name": res["name"]}]
    assert {b["name"] for b in P.load_report(str(d2157)).bookmarks} == {"7c9e1a3b5d7f9b1d3f5a", res["name"]}

    # a report with bookmark files and no index: the new index keeps the ones already there
    (bookmarks / "bookmarks.json").unlink()
    again = AU.bookmark_add(str(d2157), "Slicer only", "Overview", visuals=["5a7c9e1f3b5d7f9a1c3e"])
    assert [i["name"] for i in _load(bookmarks / "bookmarks.json")["items"]] == sorted(
        ["7c9e1a3b5d7f9b1d3f5a", res["name"]]) + [again["name"]]
    assert S.file_errors(bookmarks / "bookmarks.json") == []


def test_the_catalog_has_the_2157_visuals_and_marks_the_ones_to_avoid():
    rows = {r[0]: r for r in CAT.list_visuals().rows}
    for vtype in ("listSlicer", "advancedSlicerVisual", "textSlicer", "kpi", "azureMap", "shapeMap", "image", "shape",
                  "actionButton", "textbox"):
        assert rows[vtype][3] == "no", vtype
    for vtype, repl in (("map", "azureMap"), ("filledMap", "azureMap"), ("multiRowCard", "cardVisual"),
                        ("qnaVisual", "-")):
        assert (rows[vtype][3], rows[vtype][4]) == ("yes", repl), vtype
    assert "Copilot" in rows["qnaVisual"][1]
    roles = {r[0]: (r[1], r[2], r[3]) for r in CAT.describe_visual("advancedSlicerVisual").rows}
    assert roles == {"Values": (1, 1, "Grouping"), "Label": (0, 1, "Measure"), "Tooltips": (0, 10, "Measure")}
    assert [r[0] for r in CAT.describe_visual("azureMap").rows][:5] == ["Category", "Size", "Series", "Y", "X"]
    assert "add_in_desktop" in CAT.describe_visual("textbox").raw


@pytest.mark.parametrize("vtype, says", [("filledMap", "'azureMap'"), ("qnaVisual", "Copilot"),
                                         ("textbox", "paragraphs"), ("shapeMap", "query role")])
def test_visual_add_refuses_what_it_cannot_make_work(d2157, vtype, says):
    with pytest.raises(ValueError) as exc:
        AU.visual_add(str(d2157), "Overview", vtype, fields=["'Sales'[Region]"], position=(24, 600, 200, 200))
    assert says in str(exc.value)


def test_check_knows_the_2157_visuals_and_warns_on_the_deprecated_ones(d2157):
    model, report, _ = N.load_all(str(d2157))
    findings = CK.check_report(report, model)
    assert [f.row() for f in findings if f.severity == "error"] == []
    assert not any(f.kind.startswith("custom-visual") for f in findings)

    vj = d2157 / REPORT / "definition" / "pages" / PAGE / "visuals" / "5a7c9e1f3b5d7f9a1c3e" / "visual.json"
    for vtype, hint in (("filledMap", "replace with modern 'azureMap'"), ("qnaVisual", "Copilot")):
        data = _load(vj)
        data["visual"]["visualType"] = vtype
        vj.write_text(json.dumps(data), "utf-8")
        model, report, _ = N.load_all(str(d2157))
        legacy = [f for f in CK.check_report(report, model) if f.kind == "legacy-visual-type"]
        assert len(legacy) == 1 and hint in legacy[0].hint, (vtype, legacy)


def test_visual_add_says_which_schema_it_wrote_and_why(d2157, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["visual", "add", str(d2157), "--page", "Overview", "--type", "textSlicer",
              "--fields", "'Sales'[Region]", "--position", "24,600,240,80"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "visualContainer 2.12.0, copied from definition/pages/" in out


def test_the_wheel_ships_the_catalog_and_the_vendored_schemas():
    body = (ROOT / "pyproject.toml").read_text("utf-8")
    globs = re.search(r"^agentdata = \[(.*)\]$", body, re.M)[1]
    patterns = [g.strip().strip('"') for g in globs.split(",")]
    assert "pbip/schema/*" in patterns and "pbip/schema/fabric/**/*" in patterns
    pkg = ROOT / "agentdata"
    reached = {Path(p).relative_to(pkg).as_posix() for pat in patterns
               for p in glob.glob(str(pkg / pat), recursive=True) if os.path.isfile(p)}
    assert "pbip/schema/visuals.json" in reached
    for url in (S.DESKTOP_2157["visualContainer"], S.REPORT_3_1):
        assert "pbip/schema/" + url.removeprefix(S.BASE) in reached, url
