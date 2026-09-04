"""Tests for report planning and design brief validation, human approval gate, and layout contracts."""
import io
import json
import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from agentdata.pbip import brief as BR
from agentdata.pbip import author as AU
from agentdata.pbip import normalize as N
from agentdata.cli_pbip import main

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pbip")

VALID_SPEC = """---
ticket: REPORT-101
pbip: tests/fixtures/sample.pbip
audience: Executive Leadership
pages:
  - id: page1
    displayName: Overview
---

# Report Specification: Sales Overview

## Design Brief:
```yaml
design_brief:
  theme:
    base: CY24SU06
    primary: "#1F77B4"
  pages:
    - name: page1
      title: "Executive Summary"
      canvas:
        width: 1280
        height: 720
      layout_contract:
        grid:
          columns: 12
          rows: 8
        regions:
          kpi: { x: 20, y: 20, width: 1240, height: 120 }
          main: { x: 20, y: 160, width: 800, height: 520 }
          side: { x: 840, y: 160, width: 420, height: 520 }
        placements:
          - visual_id: kpi_margin
            type: cardVisual
            title: "Total Margin"
            fields: ["'Sales'[Margin]", "'Sales'[Quantity]"]
            position: { x: 20, y: 20, width: 400, height: 120 }
          - visual_id: trend_year
            type: columnChart
            title: "Margin by Year"
            fields: ["'Calendar'[Year]", "'Sales'[Margin]"]
            position: { x: 20, y: 160, width: 800, height: 520 }
          - visual_id: status_tbl
            type: tableEx
            title: "Sales Status"
            fields: ["'Sales'[Status]", "'Sales'[Margin]"]
            position: { x: 840, y: 160, width: 420, height: 520 }
      space_audit:
        kpi: 10.0
        main: 45.0
        side: 25.0
        whitespace: 20.0
```
"""


def test_check_valid_brief(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(VALID_SPEC.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    errors = [f for f in findings if f.severity == "error"]
    assert errors == []


def test_check_brief_catches_overlaps(tmp_path):
    # Make kpi and trend overlap vertically (trend starts at y=100 instead of 160, kpi ends at 20+120=140)
    bad_spec = VALID_SPEC.replace("x: 20, y: 160, width: 800, height: 520", "x: 20, y: 100, width: 800, height: 520")
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    overlap_kinds = [f.kind for f in findings if f.kind == "overlap"]
    assert len(overlap_kinds) >= 1


def test_check_brief_catches_off_canvas(tmp_path):
    # Width 1500 > canvas width 1280
    bad_spec = VALID_SPEC.replace("x: 20, y: 160, width: 800, height: 520", "x: 20, y: 160, width: 1500, height: 520")
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    off_canvas = [f.kind for f in findings if f.kind == "position-off-canvas"]
    assert len(off_canvas) >= 1


def test_check_brief_catches_dominant_card(tmp_path):
    # Card takes up 700x600 = 420000 / (1280*720 = 921600) = 45% of canvas (> 30%)
    bad_spec = VALID_SPEC.replace("x: 20, y: 20, width: 400, height: 120", "x: 20, y: 20, width: 700, height: 600")
    # Single field cardVisual
    bad_spec = bad_spec.replace("fields: [\"'Sales'[Margin]\", \"'Sales'[Quantity]\"]", "fields: [\"'Sales'[Margin]\"]")
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    dom_cards = [f.kind for f in findings if f.kind == "brief-dominant-bare-card"]
    assert len(dom_cards) >= 1


def test_check_brief_catches_invalid_visual_type(tmp_path):
    bad_spec = VALID_SPEC.replace("type: columnChart", "type: completelyFakeChart")
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    invalid_types = [f.kind for f in findings if f.kind == "brief-visual-type-invalid"]
    assert len(invalid_types) >= 1


def test_check_brief_catches_unresolved_field(tmp_path):
    bad_spec = VALID_SPEC.replace("'Sales'[Margin]", "'Sales'[NonExistentMargin]")
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    unresolved = [f.kind for f in findings if f.kind == "field-unresolved"]
    assert len(unresolved) >= 1


def test_check_brief_catches_space_audit_sum(tmp_path):
    bad_spec = VALID_SPEC.replace("whitespace: 20.0", "whitespace: 50.0")  # total = 10+45+25+50 = 130%
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(bad_spec.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    findings = BR.check_brief(spec_file)
    audit_errs = [f.kind for f in findings if f.kind == "brief-space-audit-sum"]
    assert len(audit_errs) >= 1


def test_brief_approval_gate_refuses_without_tty(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(VALID_SPEC.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    # Regular io.StringIO returns isatty() == False
    fake_in = io.StringIO("yes\n")
    fake_out = io.StringIO()

    with pytest.raises(RuntimeError) as exc:
        BR.approve_brief(spec_file, stdin=fake_in, stdout=fake_out)
    assert "terminal" in str(exc.value)


def test_brief_approval_gate_interactive_and_status(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(VALID_SPEC.replace("tests/fixtures/sample.pbip", FIX.replace("\\", "/")), encoding="utf-8")

    # Initially missing
    assert BR.brief_status(spec_file) == "missing"

    # Mock interactive terminal streams
    mock_in = MagicMock()
    mock_in.isatty.return_value = True
    mock_in.readline.return_value = "yes\n"

    mock_out = MagicMock()
    mock_out.isatty.return_value = True

    res = BR.approve_brief(spec_file, stdin=mock_in, stdout=mock_out)
    assert res["ok"] is True
    assert res["approved"] is True

    # After approval, status is current
    assert BR.brief_status(spec_file) == "current"

    # Modify spec file -> status becomes stale
    spec_file.write_text(spec_file.read_text(encoding="utf-8") + "\n# Extra edit\n", encoding="utf-8")
    assert BR.brief_status(spec_file) == "stale"


def test_author_verbs_enforce_brief_gate(tmp_path, capsys):
    target = tmp_path / "report"
    shutil.copytree(FIX, target)

    spec_file = tmp_path / "spec.md"
    spec_file.write_text(VALID_SPEC.replace("tests/fixtures/sample.pbip", str(target).replace("\\", "/")), encoding="utf-8")

    # 1. Visual add fails if brief is missing approval
    with pytest.raises(SystemExit) as exc:
        main(["visual", "add", str(target), "--page", "page1", "--type", "columnChart",
              "--brief", str(spec_file), "--position", "20,160,800,520"])
    assert exc.value.code == 2
    err_out = capsys.readouterr().err or capsys.readouterr().out

    # Approve brief
    mock_in = MagicMock()
    mock_in.isatty.return_value = True
    mock_in.readline.return_value = "yes\n"
    mock_out = MagicMock()
    mock_out.isatty.return_value = True
    BR.approve_brief(spec_file, stdin=mock_in, stdout=mock_out)

    # 2. Visual add fails if placement coordinates do not match layout_contract
    with pytest.raises(SystemExit) as exc:
        main(["visual", "add", str(target), "--page", "page1", "--type", "columnChart",
              "--brief", str(spec_file), "--position", "10,10,300,300"])  # not in brief
    assert exc.value.code == 2

    # 3. Visual add succeeds when placement matches approved contract
    with pytest.raises(SystemExit) as exc:
        main(["visual", "add", str(target), "--page", "page1", "--type", "columnChart",
              "--title", "Margin by Year", "--fields", "'Calendar'[Year]", "'Sales'[Margin]",
              "--brief", str(spec_file), "--position", "20,160,800,520"])
    assert exc.value.code == 0


def test_design_skill_contains_rule_sentence():
    skill_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills", "pbi-report-design", "SKILL.md")
    with open(skill_path, encoding="utf-8") as f:
        content = f.read()
    assert "never runs an `ad-pbip` write verb" in content
