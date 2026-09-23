"""`ad-pbiviz candidate`: the only way to say a chart "can't" be done, and it costs a reason per route.

A custom visual the tenant blocked reached production once, and an assistant had just said a native
chart could not carry a label it could. So the routing never builds a non-certified visual; a need that
survives every native route and every certified visual is logged as a candidate for AppSource instead.
"""
from __future__ import annotations

import os
import re

import pytest
import yaml

from agentdata import cli_pbiviz
from agentdata.pbiviz import candidate as CV

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE = os.path.join(ROOT, "skills", "pbi-custom-visual", "references", "delivery-routes.md")

REASONS = {
    "N1": "a label field shows one value per bar, and the requirement draws a second axis inside each bar",
    "N2": "a format string changes text only; the requirement needs a shape drawn beside the bar",
    "N3": "an SVG in a table cannot share the chart's axis, and the requirement needs one continuous axis",
    "N4": "reference lines and bands are per axis, not per category, and the marker is per category",
    "N5": "small multiples split categories into panels; the requirement keeps them on one axis",
    "N6": "the paginated visual does not cross-filter, and the page depends on it filtering the others",
    "N7": "the tenant disables script visuals, and a static image cannot cross-filter the page",
    "C1": "Deneb draws it, but the tenant is org-only and the organizational store does not carry Deneb",
    "C2": "no other certified visual on AppSource draws a per-category second axis",
}


def _run(argv, capsys):
    with pytest.raises(SystemExit) as ei:
        cli_pbiviz.main(argv)
    return ei.value.code, capsys.readouterr().out


def _tried(reasons):
    return [arg for rid, why in reasons.items() for arg in ("--tried", f"{rid}={why}")]


def test_a_candidate_without_a_reason_for_every_route_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    partial = {k: v for k, v in REASONS.items() if k not in ("N3", "C1")}
    code, out = _run(["candidate", "variance label at each bar end", *_tried(partial)], capsys)
    assert code == 1 and "candidate_unproven" in out and "N3, C1" in out
    assert not os.path.exists(CV.DEFAULT_ROOT)


@pytest.mark.parametrize("thin", ["n/a", "can't", "Not possible.", "doesn't work", "too hard"])
def test_a_reason_that_names_nothing_is_refused(tmp_path, monkeypatch, capsys, thin):
    monkeypatch.chdir(tmp_path)
    code, out = _run(["candidate", "variance label at each bar end", *_tried({**REASONS, "N1": thin})], capsys)
    assert code == 1 and "candidate_reason_too_thin" in out and "N1" in out
    assert not os.path.exists(CV.DEFAULT_ROOT)


def test_an_unknown_route_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code, out = _run(["candidate", "x", *_tried({**REASONS, "N9": "a route that does not exist anywhere"})], capsys)
    assert code == 1 and "candidate_unknown_route" in out


def test_a_proven_candidate_is_logged_with_the_tenant_and_listed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").write_text("- pbi_custom_visuals: org-only\n", encoding="utf-8")
    code, out = _run(["candidate", "second axis inside each bar", *_tried(REASONS),
                      "--ticket", "RDSD-7", "--where", "Sales.Report / Overview / Average vs Recent"], capsys)
    assert code == 0 and "status: logged" in out
    path = re.search(r"path: (\S+)", out).group(1)
    text = open(path, encoding="utf-8").read()
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["requirement"] == "second axis inside each bar" and meta["status"] == "logged"
    assert meta["tenant"] == "org-only" and meta["ticket"] == "RDSD-7"
    for rid, why in REASONS.items():
        assert f"| {rid} |" in text and why in text
    assert "never a visual in a report" in text

    code, out = _run(["candidates"], capsys)
    assert code == 0 and "count: 1" in out and "second axis inside each bar" in out


def test_two_candidates_the_same_day_do_not_overwrite_each_other(tmp_path):
    a = CV.record("same need", REASONS, root=str(tmp_path), today="2026-09-23")
    b = CV.record("same need", REASONS, root=str(tmp_path), today="2026-09-23")
    assert a["path"] != b["path"] and len(CV.listing(str(tmp_path))) == 2


def test_every_route_has_a_section_in_the_reference_and_nothing_else_does():
    """The command asks for a reason per route; the reference is where each route is explained. An id
    that exists in one and not the other sends the agent to a section that is not there."""
    headings = re.findall(r"(?m)^### ([NC]\d)\b", open(REFERENCE, encoding="utf-8").read())
    assert headings == list(CV.ROUTE_IDS)
