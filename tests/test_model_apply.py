"""Tests for semantic model authoring (live TOM apply, TMDL fallback, audit, and optimize)."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agentdata.cli_pbip import main
from agentdata.model import AgentTable
from agentdata.pbip import audit as ADT
from agentdata.pbip import normalize as N
from agentdata.pbip import tmdl as T
from agentdata.pbip import tom as TOM

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample.pbip"
DEFN_DIR = FIXTURE_DIR / "Sample.SemanticModel" / "definition"

SAMPLE_OPS = [
    {
        "op": "measure.set",
        "table": "Sales",
        "name": "Profit Margin",
        "expression": "DIVIDE([Margin], [Total Sales])",
        "formatString": "0.0%",
        "displayFolder": "KPIs",
        "description": "Calculates profit margin percentage",
    },
    {
        "op": "column.calc.set",
        "table": "Sales",
        "name": "Margin Amount",
        "expression": "Sales[Net Price] - Sales[Unit Cost]",
        "dataType": "decimal",
        "formatString": "$#,##0.00",
        "isHidden": False,
        "description": "Calculated row-level margin",
    },
    {
        "op": "relationship.set",
        "fromTable": "Sales",
        "fromColumn": "DateKey",
        "toTable": "Calendar",
        "toColumn": "Date",
        "cardinality": "manyToOne",
        "crossFilteringBehavior": "oneDirection",
        "isActive": True,
    },
    {
        "op": "hierarchy.set",
        "table": "Calendar",
        "name": "Fiscal Hierarchy",
        "levels": [
            {"name": "Year", "column": "Year"},
            {"name": "Month", "column": "Month"},
        ],
        "isHidden": False,
        "description": "Fiscal calendar drilldown",
    },
    {
        "op": "calcgroup.set",
        "table": "Time Intelligence",
        "name": "CalculationGroup",
        "precedence": 20,
        "items": [
            {
                "name": "YTD",
                "expression": "TOTALYTD(SELECTEDMEASURE(), 'Calendar'[Date])",
                "formatStringExpression": "SELECTEDMEASUREFORMATSTRING()",
                "ordinal": 0,
            }
        ],
    },
    {
        "op": "fieldparam.set",
        "table": "Metric Selector",
        "name": "Metric Param",
        "fields": ["'Sales'[Margin]", "'Sales'[Total Sales]"],
    },
    {
        "op": "role.set",
        "name": "Regional Manager",
        "modelPermission": "read",
        "tablePermissions": [
            {"table": "Sales", "filterExpression": "'Sales'[Quantity] > 0"}
        ],
    },
    {
        "op": "partition.set",
        "table": "Sales",
        "name": "Sales-Archive",
        "mode": "import",
        "source": {"type": "m", "query": "let Source = #\"Sales\" in Source"},
    },
    {
        "op": "perspective.set",
        "name": "Finance View",
        "tables": [{"name": "Sales", "columns": ["DateKey", "Margin"]}],
    },
    {
        "op": "object.describe",
        "table": "Sales",
        "objectType": "measure",
        "name": "Margin",
        "description": "Updated margin description",
    },
    {
        "op": "object.hide",
        "table": "Sales",
        "objectType": "column",
        "name": "DateKey",
        "isHidden": True,
    },
    {
        "op": "object.delete",
        "table": "Sales",
        "objectType": "column",
        "name": "Status",
    },
]


def test_live_te2_script_generation_and_execution(tmp_path):
    """Test op list execution through simulated Tabular Editor 2."""
    captured_scripts = []

    def fake_te2_run(args, timeout=60):
        # Inspect args: [te2_exe, server, database, -S, script_path]
        assert "-S" in args
        s_idx = args.index("-S")
        script_path = args[s_idx + 1]
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
            captured_scripts.append(content)

        # Find outPath from script
        assert "var outPath =" in content
        # Simulate TE2 writing results
        res = [
            {"op": 0, "status": "ok", "action": "measure.set", "object": "Sales[Profit Margin]"},
            {"op": 1, "status": "ok", "action": "column.calc.set", "object": "Sales[Margin Amount]"},
            {"op": 2, "status": "ok", "action": "relationship.set", "object": "Sales[DateKey] -> Calendar[Date]"},
            {"op": 3, "status": "ok", "action": "hierarchy.set", "object": "Calendar[Fiscal Hierarchy]"},
        ]
        # Extract outPath
        out_line = [ln for ln in content.splitlines() if "var outPath =" in ln][0]
        out_file = out_line.split('@"')[1].split('";')[0]
        with open(out_file, "w", encoding="utf-8") as out_f:
            json.dump(res, out_f)
        return 0, "", ""

    res = TOM.apply_live("localhost:50000", SAMPLE_OPS[:4], database="TestDB", run=fake_te2_run)
    assert len(captured_scripts) == 1
    # Verify C# script content
    assert "Microsoft.AnalysisServices.Tabular" in captured_scripts[0]
    assert "Model.SaveChanges()" in captured_scripts[0]
    assert len(res) == 4
    assert res[0]["status"] == "ok"
    assert res[0]["action"] == "measure.set"


def test_tmdl_writer_tier2_fallback(tmp_path):
    """Test op list applied directly to TMDL files in Tier 2 fallback."""
    target_pbip = tmp_path / "sample.pbip"
    shutil.copytree(FIXTURE_DIR, target_pbip)
    defn = target_pbip / "Sample.SemanticModel" / "definition"

    res = TOM.apply_tmdl(str(defn), SAMPLE_OPS)
    # Assert every op succeeded
    for r in res:
        assert r.get("status") == "ok", f"Op failed: {r}"

    # Verify measure was added
    sales_tmdl = (defn / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
    assert "measure 'Profit Margin' = ```" in sales_tmdl or "measure 'Profit Margin' = " in sales_tmdl
    assert "column 'Margin Amount' = Sales[Net Price] - Sales[Unit Cost]" in sales_tmdl
    assert "hierarchy 'Fiscal Hierarchy'" in (defn / "tables" / "Calendar.tmdl").read_text(encoding="utf-8")
    assert (defn / "tables" / "Metric Selector.tmdl").exists()
    assert (defn / "roles" / "Regional Manager.tmdl").exists()

    # Re-parse and lint updated definition to assert correctness
    model_after, _, _ = N.load_all(str(defn), legacy_ok=True)
    for p, f in model_after.files.items():
        check = T.parse_text(f.text, f.path, bom=f.bom)
        errs = [e for e in T.lint_file(check) if e.severity == "error"]
        assert errs == [], f"Lint errors in {p}: {errs}"


def test_no_lineagetag_in_writer_output(tmp_path):
    """CRITICAL Grep test: assert lineageTag never appears in newly authored objects."""
    target_pbip = tmp_path / "sample.pbip"
    shutil.copytree(FIXTURE_DIR, target_pbip)
    defn = target_pbip / "Sample.SemanticModel" / "definition"

    TOM.apply_tmdl(str(defn), SAMPLE_OPS)

    # Inspect created files
    metric_selector = (defn / "tables" / "Metric Selector.tmdl").read_text(encoding="utf-8")
    assert "lineageTag" not in metric_selector

    roles_tmdl = (defn / "roles" / "Regional Manager.tmdl").read_text(encoding="utf-8")
    assert "lineageTag" not in roles_tmdl

    sales_tmdl = (defn / "tables" / "Sales.tmdl").read_text(encoding="utf-8")
    # Verify new measure Profit Margin has no lineageTag
    lines = sales_tmdl.splitlines()
    pm_lines = []
    capture = False
    for ln in lines:
        if "measure 'Profit Margin'" in ln:
            capture = True
        elif capture and ("measure " in ln or "column " in ln):
            break
        if capture:
            pm_lines.append(ln)
    assert not any("lineageTag" in ln for ln in pm_lines)


def test_model_audit_rules():
    """Test model audit identifies 8+ canonical best-practice rules."""
    model, report, _ = N.load_all(str(DEFN_DIR), legacy_ok=True)
    findings = ADT.audit_model(model, report=report)
    assert len(findings) >= 8

    rule_ids = set(f.rule_id for f in findings)
    assert "columns-not-hidden-used-in-measures" in rule_ids
    assert "unused-columns" in rule_ids

    # Check that fixes are valid op snippets
    for f in findings:
        if f.fix:
            assert "op" in f.fix
            assert f.fix["op"] in TOM.VALID_OPS


def test_model_audit_copilot():
    """Test Copilot AI readiness scored checklist."""
    model, _, _ = N.load_all(str(DEFN_DIR), legacy_ok=True)
    copilot_res = ADT.audit_copilot(model)
    assert 0 <= copilot_res.score <= 100
    assert copilot_res.total_checks > 0
    assert copilot_res.passed_checks + copilot_res.failed_checks == copilot_res.total_checks

    summary = copilot_res.summary()
    assert "score" in summary
    assert "items" in summary
    categories = set(it["category"] for it in summary["items"])
    assert "table-description" in categories
    assert "measure-description" in categories
    assert "hidden-hygiene" in categories
    assert "column-description" in categories


def test_model_optimize_success(tmp_path):
    """Test model optimize captures evidence, optimizes, and verifies matching numbers."""
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")

    def fake_dax_run(args, timeout=30):
        out_csv = args[2]
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write("Result\n42.0\n")
        return 0, "", ""

    with patch("agentdata.pbip.tom.apply_live", return_value=[{"op": 0, "status": "ok"}]):
        res = TOM.model_optimize(
            measure="Margin",
            server="localhost:50000",
            dscmd_exe=str(dscmd),
            runner=fake_dax_run,
        )
        assert res["measure"] == "Margin"
        assert res["baseline_val"] == 42.0
        assert res["optimized_val"] == 42.0
        assert "speedup" in res


def test_model_optimize_refuses_differing_results(tmp_path):
    """Test model optimize detects regression when value changes and rolls back."""
    dscmd = tmp_path / "dscmd.exe"
    dscmd.write_text("stub")
    call_count = 0

    def fake_dax_run_differing(args, timeout=30):
        nonlocal call_count
        call_count += 1
        out_csv = args[2]
        val = "100.0" if call_count == 1 else "99.0"
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write(f"Result\n{val}\n")
        return 0, "", ""

    rollback_called = False

    def fake_apply(ops, **kwargs):
        nonlocal rollback_called
        if any("DIVIDE" in op.get("expression", "") or "VAR" in op.get("expression", "") for op in ops):
            return {"tier": "live", "results": [{"status": "ok"}]}
        rollback_called = True
        return {"tier": "live", "results": [{"status": "ok"}]}

    with patch("agentdata.pbip.tom.model_apply", side_effect=fake_apply):
        with pytest.raises(ValueError) as exc:
            TOM.model_optimize(
                measure="Margin",
                server="localhost:50000",
                dscmd_exe=str(dscmd),
                runner=fake_dax_run_differing,
            )
        assert "Regression detected" in str(exc.value)
        assert rollback_called is True


def test_cli_model_audit(capsys):
    """Test CLI model audit command."""
    with pytest.raises(SystemExit) as exc:
        main(["model", "audit", str(DEFN_DIR)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "source: ad-pbip model audit" in out
    assert "columns-not-hidden-used-in-measures" in out


def test_cli_model_audit_copilot(capsys):
    """Test CLI model audit --copilot command."""
    with pytest.raises(SystemExit) as exc:
        main(["model", "audit", str(DEFN_DIR), "--copilot"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "source: ad-pbip model audit --copilot" in out
    assert "score:" in out


def test_cli_model_apply_tmdl(tmp_path, capsys):
    """Test CLI model apply with ops file."""
    target_pbip = tmp_path / "sample.pbip"
    shutil.copytree(FIXTURE_DIR, target_pbip)
    defn = target_pbip / "Sample.SemanticModel" / "definition"

    ops = [
        {"op": "measure.set", "table": "Sales", "name": "CLI Measure", "expression": "100"}
    ]
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(json.dumps(ops), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        main(["model", "apply", "--model", str(defn), "--ops", str(ops_file)])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "source: ad-pbip model apply" in out
    assert "CLI Measure" in out


def test_cli_measure_set_alias(tmp_path, capsys):
    """Test CLI measure set behaves as thin alias over model apply."""
    target_pbip = tmp_path / "sample.pbip"
    shutil.copytree(FIXTURE_DIR, target_pbip)

    with pytest.raises(SystemExit) as exc:
        main(["measure", "set", str(target_pbip), "--table", "Sales", "--name", "Alias Measure",
              "--expr", "200", "--dry-run"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "source: ad-pbip measure set" in out
    assert "dry_run: true" in out

