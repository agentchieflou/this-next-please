"""`ad-pbip visual set` writes formatting where, and as, Power BI Desktop saves it.

The expectations are Desktop's own output: visual.json files Desktop saved, vendored verbatim under
fixtures/pbip/desktop-saved/ (its README says where each came from). Chart formatting (data labels, legend, axes)
sits in `visual.objects`; container formatting (title, background, border, ...) in `visual.visualContainerObjects`,
whose published schema admits fifteen keys and nothing else.
"""
import copy
import json
import shutil
from pathlib import Path

import pytest

from agentdata.cli_pbip import main
from agentdata.pbip import author as AU
from agentdata.pbip import catalog as CAT
from agentdata.pbip import check as CK
from agentdata.pbip import expr as EX
from agentdata.pbip import normalize as N

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample.pbip"
DESKTOP_SAVED = sorted((FIXTURES / "pbip" / "desktop-saved").glob("*.visual.json"))
BAR = "f1a2b3c4d5e6f7a8b9c0"  # the sample report's barChart
CONTAINERS = ("objects", "visualContainerObjects")

# Where Desktop saves each catalog object, read off the Desktop-saved files. A new catalog object is pinned here.
DESKTOP_LOCATION = {
    "labels": "objects",
    "legend": "objects",
    "categoryAxis": "objects",
    "valueAxis": "objects",
    "title": "visualContainerObjects",
    "subTitle": "visualContainerObjects",
    "background": "visualContainerObjects",
    "border": "visualContainerObjects",
    "dropShadow": "visualContainerObjects",
    "padding": "visualContainerObjects",
    "visualHeader": "visualContainerObjects",
}
# VisualContainerFormattingObjects in Microsoft's visualContainer schema, 1.0.0 onwards: additionalProperties false.
SCHEMA_CONTAINER_KEYS = {
    "title", "subTitle", "divider", "spacing", "background", "padding", "lockAspect", "general", "border",
    "dropShadow", "visualLink", "visualTooltip", "stylePreset", "visualHeader", "visualHeaderTooltip",
}
# The one Desktop literal `visual set` does not reproduce: BCApps' titles store fontSize as the string '12'.
# Every other saved fontSize, and Microsoft's own examples, write a D-suffixed number, which is what it writes.
LEGACY = {("bcapps-manufacturing-4b62e0a39c39c8623304.visual.json", "title.fontSize"): "12D"}


@pytest.fixture
def report(tmp_path):
    target = tmp_path / "report"
    shutil.copytree(SAMPLE, target)
    return target


@pytest.fixture
def live_report(report):
    """The sample report without its semantic model, as a live-connected report is on disk."""
    shutil.rmtree(report / "Sample.SemanticModel")
    return report


def _visual_file(report, visual_id=BAR):
    return report / "Sample.Report" / "definition" / "pages" / "page1" / "visuals" / visual_id / "visual.json"


def _load(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def _install(report, desktop_file):
    """Put a Desktop-saved visual on the sample report's first page; return its id and file."""
    visual_id = _load(desktop_file)["name"]
    dest = _visual_file(report, visual_id)
    dest.parent.mkdir(parents=True)
    shutil.copyfile(desktop_file, dest)
    return visual_id, dest


def _lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def _typed(value, ptype):
    """What one types after `=` for `visual set` to write this Desktop value; None when it cannot."""
    if ptype == "field":
        return EX.decode_expr(value["expr"])
    if "solid" in value:
        value = value["solid"]["color"]
    lit = ((value.get("expr") or {}).get("Literal") or {}).get("Value")
    if lit is None:
        return None  # a theme colour, or a measure where the catalog wants a literal
    if lit.startswith("'"):
        return lit[1:-1].replace("''", "'")
    return lit[:-1] if lit.endswith("D") else lit


def _series_of(selector, ptype):
    """(True, series) when `visual set` writes this selector for this kind of property, else (False, None)."""
    selector = selector or {}
    if ptype == "field":
        rest = {k: v for k, v in selector.items() if k != "metadata"}
        return rest == {"data": AU.ALL_INSTANCES, "highlightMatching": 1}, selector.get("metadata")
    if not selector:
        return True, None
    return set(selector) == {"metadata"}, selector.get("metadata")


def _desktop_settings():
    """Every value a Desktop-saved fixture sets on a catalog property, under a selector `visual set` writes."""
    formatting = CAT.load_catalog()["formatting"]
    for f in DESKTOP_SAVED:
        vis = _load(f)["visual"]
        for obj, odef in formatting.items():
            for index, entry in enumerate((vis.get(odef["location"]) or {}).get(obj) or []):
                for prop, value in (entry.get("properties") or {}).items():
                    pdef = odef["properties"].get(prop)
                    if pdef is None or _typed(value, pdef["type"]) is None:
                        continue
                    ours, series = _series_of(entry.get("selector"), pdef["type"])
                    if ours and (series is None or odef.get("series")):
                        tag = f"{f.stem.rsplit('-', 1)[0]}:{obj}.{prop}" + (f"@{series}" if series else "")
                        yield pytest.param(f, obj, prop, index, series, id=tag)


def test_the_catalog_puts_every_object_where_desktop_saves_it():
    formatting = CAT.load_catalog()["formatting"]
    assert {obj: d["location"] for obj, d in formatting.items()} == DESKTOP_LOCATION
    container = {obj for obj, loc in DESKTOP_LOCATION.items() if loc == "visualContainerObjects"}
    assert container <= SCHEMA_CONTAINER_KEYS
    assert not (set(DESKTOP_LOCATION) - container) & SCHEMA_CONTAINER_KEYS


def test_desktop_saved_each_object_where_it_is_pinned():
    seen: dict[str, set[str]] = {}
    for f in DESKTOP_SAVED:
        vis = _load(f)["visual"]
        for container in CONTAINERS:
            for obj in vis.get(container) or {}:
                seen.setdefault(obj, set()).add(container)
    assert {obj: seen.get(obj) for obj in DESKTOP_LOCATION} == {obj: {loc} for obj, loc in DESKTOP_LOCATION.items()}
    assert "dataLabels" not in seen


@pytest.mark.parametrize("obj", sorted(DESKTOP_LOCATION))
def test_visual_set_writes_each_object_where_desktop_saves_it(report, obj):
    odef = CAT.load_catalog()["formatting"][obj]
    sample = {"bool": "true", "number": "10", "color": "#118DFF", "string": "Sales", "field": "[Margin]"}
    here = DESKTOP_LOCATION[obj]
    for prop, pdef in odef["properties"].items():
        typed = pdef["enum"][0] if pdef["type"] == "enum" else sample[pdef["type"]]
        res = AU.visual_set(str(report), BAR, f"{obj}.{prop}", typed)
        assert res["location"] == f"visual.{here}.{obj}"

    vis = _load(_visual_file(report))["visual"]
    fields = {p for p, d in odef["properties"].items() if d["type"] == "field"}
    by_selector = {json.dumps(e.get("selector")): set(e["properties"]) for e in vis[here][obj]}
    assert by_selector.pop(json.dumps(None)) == set(odef["properties"]) - fields
    assert by_selector == ({json.dumps({"data": AU.ALL_INSTANCES, "highlightMatching": 1}): fields} if fields else {})
    other = next(c for c in CONTAINERS if c != here)
    assert obj not in (vis.get(other) or {})


def test_data_labels_are_labels_in_visual_objects(report):
    """The regression: the catalog said `dataLabels`, and it was written into visualContainerObjects.

    Desktop's data-label object is `labels`, in visual.objects, and the container schema admits no `dataLabels`.
    """
    vj = _visual_file(report)
    before = vj.read_bytes()
    with pytest.raises(KeyError, match="Did you mean 'labels'"):
        AU.visual_set(str(report), BAR, "dataLabels.show", "true")
    assert vj.read_bytes() == before

    AU.visual_set(str(report), BAR, "labels.show", "true")
    AU.visual_set(str(report), BAR, "labels.labelPosition", "outsideend")
    vis = _load(vj)["visual"]
    assert vis["objects"]["labels"] == [{"properties": {
        "show": _lit("true"),
        "labelPosition": _lit("'OutsideEnd'"),
    }}]
    assert set(vis["visualContainerObjects"]) == {"title"}


def test_cli_refuses_data_labels_and_writes_labels(report, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["visual", "set", str(report), "--visual", BAR, "--property", "dataLabels.show=true"])
    assert exc.value.code == 2
    assert "Did you mean 'labels'" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exc:
        main(["visual", "set", str(report), "--visual", BAR, "--property", "labels.show=true"])
    assert exc.value.code == 0
    assert "visual.objects.labels" in capsys.readouterr().out
    assert _load(_visual_file(report))["visual"]["objects"]["labels"][0]["properties"]["show"] == _lit("true")


@pytest.mark.parametrize("old, new", [
    ("labels.position", "labelPosition"),
    ("categoryAxis.showTitle", "showAxisTitle"),
    ("valueAxis.showTitle", "showAxisTitle"),
])
def test_other_old_names_are_refused_with_desktops_name(report, old, new):
    with pytest.raises(KeyError, match=f"Did you mean '{new}'"):
        AU.visual_set(str(report), BAR, old, "true")


@pytest.mark.parametrize("desktop_file, obj, prop, index, series", list(_desktop_settings()))
def test_visual_set_writes_what_desktop_saved(live_report, desktop_file, obj, prop, index, series):
    """Take one setting out of a Desktop-saved visual and put it back: the file comes back as Desktop saved it.

    The report has no local model, like a live-connected one, so a field the fixture names is taken as written.
    """
    saved = _load(desktop_file)
    visual_id, vj = _install(live_report, desktop_file)
    edited = copy.deepcopy(saved)
    ptype = CAT.load_catalog()["formatting"][obj]["properties"][prop]["type"]
    typed = _typed(edited["visual"][DESKTOP_LOCATION[obj]][obj][index]["properties"].pop(prop), ptype)
    vj.write_text(json.dumps(edited), encoding="utf-8")

    AU.visual_set(str(live_report), visual_id, f"{obj}.{prop}", typed, series=series)

    expected = copy.deepcopy(saved)
    legacy = LEGACY.get((desktop_file.name, f"{obj}.{prop}"))
    if legacy:
        expected["visual"][DESKTOP_LOCATION[obj]][obj][index]["properties"][prop] = _lit(legacy)
    assert _load(vj) == expected


def test_every_desktop_saved_fixture_is_exercised():
    """The round trip reads every fixture but the one whose labels hold no literal (the selector case below)."""
    settings = [p.values for p in _desktop_settings()]
    selector_case = "bcapps-projects-56a753c4cc81a8e906d3.visual.json"
    assert {f.name for f, *_ in settings} == {f.name for f in DESKTOP_SAVED} - {selector_case}
    assert {obj for _, obj, *_ in settings} == set(DESKTOP_LOCATION)
    assert {(f.name, f"{obj}.{prop}") for f, obj, prop, *_ in settings} >= set(LEGACY)
    # Desktop's own per-series settings: a literal, and the label field the N1 route needs.
    per_series = {(f"{obj}.{prop}", series) for _, obj, prop, _, series in settings if series}
    assert ("labels.enableDetailDataLabel", "Production Orders.Actual Capacity Cost") in per_series
    assert ("labels.dynamicLabelValue", "Production Orders.Actual Material Cost") in per_series


def test_a_visual_wide_setting_skips_desktops_per_series_entry(report):
    """Desktop saved this chart's labels with the per-series entry first; `show` goes in the other entry."""
    desktop_file = next(f for f in DESKTOP_SAVED if f.name.startswith("bcapps-projects-"))
    saved = _load(desktop_file)["visual"]["objects"]["labels"]
    assert saved[0].get("selector") and not saved[1].get("selector")
    visual_id, vj = _install(report, desktop_file)

    AU.visual_set(str(report), visual_id, "labels.show", "false")

    assert _load(vj)["visual"]["objects"]["labels"] == [saved[0], {"properties": {"show": _lit("false")}}]


def test_a_static_entry_goes_first_when_every_entry_has_a_selector(report):
    vj = _visual_file(report)
    data = _load(vj)
    per_series = {
        "properties": {"color": {"solid": {"color": _lit("'#212121'")}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]},
    }
    data["visual"]["objects"] = {"labels": [per_series]}
    vj.write_text(json.dumps(data), encoding="utf-8")

    AU.visual_set(str(report), BAR, "labels.show", "true")

    assert _load(vj)["visual"]["objects"]["labels"] == [{"properties": {"show": _lit("true")}}, per_series]


@pytest.mark.parametrize("prop, typed, written", [
    ("title.fontSize", "10.5", _lit("10.5D")),
    ("title.show", "False", _lit("false")),
    ("title.alignment", "Center", _lit("'center'")),
    ("title.text", "Margin's trend", _lit("'Margin''s trend'")),
    ("title.fontColor", "#157A67", {"solid": {"color": _lit("'#157A67'")}}),
    ("legend.position", "topright", _lit("'TopRight'")),
    ("valueAxis.start", "0", _lit("0D")),
])
def test_values_are_written_in_desktops_literal_syntax(report, prop, typed, written):
    AU.visual_set(str(report), BAR, prop, typed)
    obj, name = prop.split(".")
    assert _load(_visual_file(report))["visual"][DESKTOP_LOCATION[obj]][obj][0]["properties"][name] == written


@pytest.mark.parametrize("prop, typed", [
    ("title.alignment", "justify"),
    ("title.show", "maybe"),
    ("title.fontSize", "large"),
    ("title.fontSize", "nan"),
    ("title.fontColor", "red"),
])
def test_a_value_outside_the_catalog_changes_nothing(report, prop, typed):
    vj = _visual_file(report)
    before = vj.read_bytes()
    with pytest.raises(ValueError):
        AU.visual_set(str(report), BAR, prop, typed)
    assert vj.read_bytes() == before


def test_visual_add_doubles_a_quote_in_the_title(report):
    res = AU.visual_add(str(report), "page1", "columnChart", title="Margin's trend",
                        fields=["'Calendar'[Year]", "'Sales'[Margin]"], position=(50, 50, 600, 400))
    title = _load(res["path"])["visual"]["visualContainerObjects"]["title"][0]["properties"]
    assert title["text"] == _lit("'Margin''s trend'")


# ---------- label fields and per-series settings (the native bar-end label route, N1) ----------

def _measure(entity, name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def _two_series(report):
    """Give the sample barChart a second value, as the Average/Recent chart has two."""
    vj = _visual_file(report)
    data = _load(vj)
    data["visual"]["query"]["queryState"]["Y"]["projections"].append(
        {"field": _measure("Sales", "Total Sales"), "queryRef": "Sales.Total Sales", "nativeQueryRef": "Total Sales"})
    vj.write_text(json.dumps(data), encoding="utf-8")
    return vj


def test_n1_a_label_field_on_one_series_as_desktop_saves_it(report):
    """Labels on; off for one series; on the other, outside end with another measure as its value."""
    vj = _two_series(report)
    AU.visual_set(str(report), BAR, "labels.show", "true")
    AU.visual_set(str(report), BAR, "labels.show", "false", series="Margin")
    AU.visual_set(str(report), BAR, "labels.labelPosition", "OutsideEnd", series="Total Sales")
    res = AU.visual_set(str(report), BAR, "labels.dynamicLabelValue", "[Sales Amount (LY)]", series="Sales.Total Sales")

    assert res["series"] == "Sales.Total Sales" and res["field_checked"] == "against the model"
    assert res["value"] == "'Sales'[Sales Amount (LY)]"
    assert _load(vj)["visual"]["objects"]["labels"] == [
        {"properties": {"show": _lit("true")}},
        {"properties": {"show": _lit("false")}, "selector": {"metadata": "Sales.Margin"}},
        {"properties": {"labelPosition": _lit("'OutsideEnd'")}, "selector": {"metadata": "Sales.Total Sales"}},
        {"properties": {"dynamicLabelValue": {"expr": _measure("Sales", "Sales Amount (LY)")}},
         "selector": {"data": AU.ALL_INSTANCES, "metadata": "Sales.Total Sales", "highlightMatching": 1}},
    ]


def test_a_detail_line_and_a_second_setting_share_their_entry(report):
    vj = _two_series(report)
    AU.visual_set(str(report), BAR, "labels.enableDetailDataLabel", "true", series="Total Sales")
    AU.visual_set(str(report), BAR, "labels.detailContentType", "custom", series="Total Sales")
    AU.visual_set(str(report), BAR, "labels.dynamicLabelDetail", "Min('Sales'[Status])", series="Total Sales")
    labels = _load(vj)["visual"]["objects"]["labels"]
    assert labels == [
        {"properties": {"enableDetailDataLabel": _lit("true"), "detailContentType": _lit("'Custom'")},
         "selector": {"metadata": "Sales.Total Sales"}},
        {"properties": {"dynamicLabelDetail": {"expr": {"Aggregation": {
            "Expression": {"Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Status"}},
            "Function": 3}}}},
         "selector": {"data": AU.ALL_INSTANCES, "metadata": "Sales.Total Sales", "highlightMatching": 1}},
    ]


@pytest.mark.parametrize("field, says", [
    ("'Sales'[Status]", "is a column; a label shows a measure or an aggregation, e.g. Min('Sales'[Status])"),
    ("[No Such Measure]", "no measure [No Such Measure] in the model"),
    ("'Calendar'[Margin]", "it lives in 'Sales'"),
    ("Min('Sales'[Nope])", "aggregates no column of the model"),
])
def test_a_label_field_the_model_does_not_have_changes_nothing(report, field, says):
    vj = _visual_file(report)
    before = vj.read_bytes()
    with pytest.raises(ValueError) as exc:
        AU.visual_set(str(report), BAR, "labels.dynamicLabelValue", field)
    assert says in str(exc.value)
    assert vj.read_bytes() == before


def test_without_a_local_model_a_label_field_must_name_its_table(live_report):
    with pytest.raises(ValueError, match="name its table"):
        AU.visual_set(str(live_report), BAR, "labels.dynamicLabelValue", "[Margin]")
    res = AU.visual_set(str(live_report), BAR, "labels.dynamicLabelValue", "'Sales'[Margin]")
    assert res["field_checked"].startswith("no local model")
    entry = _load(_visual_file(live_report))["visual"]["objects"]["labels"][0]
    assert entry["properties"]["dynamicLabelValue"] == {"expr": _measure("Sales", "Margin")}


@pytest.mark.parametrize("prop, series, says", [
    ("title.show", "Margin", "applies to the whole visual; --series is for labels"),
    ("legend.show", "Margin", "applies to the whole visual"),
    ("labels.show", "Profit", "series 'Profit' is not a field of this visual; the visual's fields are: "
                              "Calendar.Year, Sales.Margin"),
])
def test_series_is_refused_where_desktop_has_no_per_series_setting(report, prop, series, says):
    vj = _visual_file(report)
    before = vj.read_bytes()
    with pytest.raises(ValueError) as exc:
        AU.visual_set(str(report), BAR, prop, "true", series=series)
    assert says in str(exc.value)
    assert vj.read_bytes() == before


def test_cli_sets_a_label_field_on_a_series(report, capsys):
    _two_series(report)
    with pytest.raises(SystemExit) as exc:
        main(["visual", "set", str(report), "--visual", BAR, "--series", "Total Sales",
              "--property", "labels.dynamicLabelValue=[Margin]"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "series: Sales.Total Sales" in out and "field_checked: against the model" in out


def test_check_resolves_a_label_field_once_the_model_is_there(live_report, tmp_path):
    """Written blind on a live-connected report, the field is still validated when a model is at hand."""
    AU.visual_set(str(live_report), BAR, "labels.dynamicLabelValue", "'Sales'[Nope]")
    shutil.copytree(SAMPLE / "Sample.SemanticModel", live_report / "Sample.SemanticModel")
    model, rep, _ = N.load_all(str(live_report))
    unresolved = [f for f in CK.check_report(rep, model) if f.kind == "field-unresolved"]
    assert any("labels[0].properties.dynamicLabelValue" in str(f.__dict__) for f in unresolved)
