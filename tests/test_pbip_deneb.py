"""`ad-pbip visual deneb`: a custom chart in the Microsoft-certified visual, never a custom visual.

The shape asserted here is the one in Deneb's own PBIR guide (deneb-viz.github.io/pbir-guide): the
AppSource GUID, the fields in the `dataset` role, the specification as a single-quoted text literal in
`objects.vega[0].properties.jsonSpec`.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

from agentdata import cli_pbip
from agentdata.pbip import check as CK
from agentdata.pbip import deneb as DN
from agentdata.pbip import pbir as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_REPORT = os.path.join(ROOT, "tests", "fixtures", "pbip", "native", "Native.Report")
SPEC = os.path.join(ROOT, "skills", "pbi-custom-visual", "references", "deneb-average-recent.vl.json")
FIELDS = ["'Dates'[MonthName]", "[Total Sales]", "[Margin]"]


@pytest.fixture
def report(tmp_path):
    dest = tmp_path / "Native.Report"
    shutil.copytree(FIXTURE_REPORT, dest)
    return dest


def _visual(report, visual_id):
    path, data = next((p, json.loads(p.read_text(encoding="utf-8")))
                      for p in report.rglob("visual.json") if p.parent.name == visual_id)
    return path, data


def _literal(prop):
    return prop["expr"]["Literal"]["Value"]


def test_add_writes_the_visual_denebs_guide_describes(report):
    res = DN.add(str(report), "Overview", SPEC, FIELDS, title="Average vs Recent")
    _path, vis = _visual(report, res["visual_id"])
    v = vis["visual"]
    assert v["visualType"] == DN.GUID == "deneb7E15AEF80B9E4D4F8E12924291ECE89A"
    projections = v["query"]["queryState"]["dataset"]["projections"]
    assert [p["nativeQueryRef"] for p in projections] == ["MonthName", "Total Sales", "Margin"]
    assert "Column" in projections[0]["field"] and "Measure" in projections[1]["field"]
    props = v["objects"]["vega"][0]["properties"]
    spec_literal = _literal(props["jsonSpec"])
    assert spec_literal.startswith("'") and spec_literal.endswith("'")
    assert json.loads(spec_literal[1:-1]) == json.load(open(SPEC, encoding="utf-8"))
    assert _literal(props["jsonConfig"]) == "'{}'" and _literal(props["provider"]) == "'vegaLite'"
    assert "enableSelection" not in props and v["drillFilterOtherVisuals"] is True
    rj = json.loads((report / "definition" / "report.json").read_text(encoding="utf-8"))
    assert DN.GUID in rj["publicCustomVisuals"] and res["registered"] == "added"


def test_the_gate_treats_it_as_the_certified_appsource_visual_it_is(report):
    DN.add(str(report), "Overview", SPEC, FIELDS)
    rep = P.load_report(str(report))
    kinds = lambda facts: [f.kind for f in CK.custom_visual_delivery(rep, facts)]  # noqa: E731
    assert kinds({"pbi_custom_visuals": "allowed"}) == []
    assert kinds({"pbi_custom_visuals": "certified-only"}) == ["custom-visual-certification-unconfirmed"]
    assert kinds({"pbi_custom_visuals": "certified-only", "pbi_certified_visuals": DN.GUID}) == []
    assert kinds({"pbi_custom_visuals": "org-only"}) == ["custom-visual-tenant-blocked"]


def test_interactivity_flags_are_the_booleans_deneb_reads(report):
    res = DN.add(str(report), "Overview", SPEC, FIELDS, cross_filter=True, cross_highlight=True)
    props = _visual(report, res["visual_id"])[1]["visual"]["objects"]["vega"][0]["properties"]
    assert _literal(props["enableSelection"]) == "true" and _literal(props["selectionMode"]) == "'simple'"
    assert _literal(props["enableHighlight"]) == "true"


def test_update_replaces_the_specification_and_keeps_what_deneb_manages(report, tmp_path):
    res = DN.add(str(report), "Overview", SPEC, FIELDS)
    path, vis = _visual(report, res["visual_id"])
    vis["visual"]["objects"]["stateManagement"] = [{"properties": {"viewportHeight": {"expr": {"Literal": {"Value": "270D"}}}}}]
    path.write_text(json.dumps(vis), encoding="utf-8")
    simple = tmp_path / "simple.json"
    simple.write_text(json.dumps({"data": {"name": "dataset"}, "mark": "bar"}), encoding="utf-8")
    DN.update(str(report), res["visual_id"], str(simple))
    v = _visual(report, res["visual_id"])[1]["visual"]
    assert json.loads(_literal(v["objects"]["vega"][0]["properties"]["jsonSpec"])[1:-1]) == {
        "data": {"name": "dataset"}, "mark": "bar"}
    assert "stateManagement" in v["objects"]


@pytest.mark.parametrize("text,needle", [
    ('{"data": {"name": "dataset"}, "mark": {"type": "text"}, "encoding": {"text": {"value": "Recent\'s"}}}', "apostrophe"),
    ('{"data": {"values": []}, "mark": "bar"}', "dataset"),
    ('{"data": {"name": "dataset"}, // a comment\n "mark": "bar"}', "not JSON"),
])
def test_a_specification_deneb_cannot_take_as_written_is_refused(report, tmp_path, text, needle):
    spec = tmp_path / "spec.json"
    spec.write_text(text, encoding="utf-8")
    with pytest.raises(DN.DenebError, match=needle):
        DN.add(str(report), "Overview", str(spec), FIELDS)


def test_the_uncertified_editions_and_other_visuals_are_refused(report):
    res = DN.add(str(report), "Overview", SPEC, FIELDS)
    path, vis = _visual(report, res["visual_id"])
    vis["visual"]["visualType"] = "STANDALONE" + DN.GUID
    path.write_text(json.dumps(vis), encoding="utf-8")
    with pytest.raises(DN.DenebError, match="not the certified visual"):
        DN.update(str(report), res["visual_id"], SPEC)
    vis["visual"]["visualType"] = "clusteredBarChart"
    path.write_text(json.dumps(vis), encoding="utf-8")
    with pytest.raises(DN.DenebError, match="not Deneb"):
        DN.update(str(report), res["visual_id"], SPEC)


def test_an_org_only_tenant_gets_no_appsource_deneb(report):
    with pytest.raises(DN.DenebError, match="organizational-store visuals only") as e:
        DN.add(str(report), "Overview", SPEC, FIELDS, facts={"pbi_custom_visuals": "org-only"})
    assert "My organization" in e.value.hint


def test_cli_adds_one_and_prints_the_refusal_hint(report, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(tmp_path)

    def run(argv):
        monkeypatch.setattr(sys, "argv", ["ad-pbip", *argv])
        with pytest.raises(SystemExit) as ei:
            cli_pbip.main()
        return ei.value.code, capsys.readouterr().out

    code, out = run(["visual", "deneb", str(report), "--page", "Overview", "--spec", SPEC,
                     "--fields", *FIELDS, "--cross-filter"])
    assert code == 0 and "deneb_add" in out and DN.GUID in out
    bad = tmp_path / "bad.json"
    bad.write_text('{"data": {"name": "dataset"}, "mark": {"type": "text", "text": "it\'s"}}', encoding="utf-8")
    code, out = run(["visual", "deneb", str(report), "--page", "Overview", "--spec", str(bad), "--fields", *FIELDS])
    assert code == 2 and "apostrophe" in out and "Vega expression" in out
