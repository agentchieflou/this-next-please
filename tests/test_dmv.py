"""Tests for Analysis Services DMV diagnostics and live model observation."""
import json
import os
import tempfile
import pytest
from unittest.mock import patch
from agentdata.pbip import dmv as DMV
from agentdata.pbip import trace as TR
from agentdata.model import AgentTable
from agentdata.cli_pbip import main


def test_dmv_shortcuts_exist():
    assert "deps" in DMV.DMV_SHORTCUTS
    assert "segments" in DMV.DMV_SHORTCUTS
    assert "sessions" in DMV.DMV_SHORTCUTS
    assert "schema" in DMV.DMV_SHORTCUTS
    assert "DISCOVER_CALC_DEPENDENCY" in DMV.DMV_SHORTCUTS["deps"]


def test_run_dmv_te2_mocked(tmp_path):
    # Fake TE2 script executor that writes dmv.csv
    def fake_run(cmd, timeout):
        # Find csx script from cmd
        csx_file = cmd[cmd.index("-S") + 1]
        assert os.path.exists(csx_file)
        # Find out_csv destination from script content
        with open(csx_file, encoding="utf-8") as f:
            content = f.read()
        for line in content.splitlines():
            if 'var outFile = @"' in line:
                out_csv = line.split('@"')[1].rstrip('";')
                with open(out_csv, "w", encoding="utf-8") as out_f:
                    out_f.write('"TABLE_ID","COLUMN_ID","ROWS_COUNT","USED_SIZE"\n')
                    out_f.write('"Sales","Amount","1000","4096"\n')
                    out_f.write('"Customer","Name","50","1024"\n')
                break
        return 0, "OK", ""

    table = DMV.run_dmv_te2("localhost:50000", "SELECT * FROM SEGMENTS", "TabularEditor.exe", run=fake_run)
    assert table.name == "dmv"
    assert [c.lower() for c in table.columns] == ["table_id", "column_id", "rows_count", "used_size"]
    assert len(table.rows) == 2
    assert table.rows[0][0] == "Sales"
    assert table.rows[0][3] == 4096


def test_normalize_segments():
    raw_table = AgentTable("raw_segments", ["TABLE_ID", "COLUMN_ID", "ROWS_COUNT", "USED_SIZE"], [
        ["Customer", "Key", 100, 1000],
        ["Sales", "Amount", 5000, 3000],
    ])
    norm = DMV.normalize_segments(raw_table)
    assert norm.columns == ["table", "column", "rows", "bytes", "pct_of_model"]
    # Sorted by bytes descending
    assert norm.rows[0][0] == "Sales"
    assert norm.rows[0][3] == 3000
    assert norm.rows[0][4] == 75.0  # 3000 / 4000 = 75%
    assert norm.rows[1][0] == "Customer"
    assert norm.rows[1][4] == 25.0


def test_refs_live_reconciliation(tmp_path):
    # Mock run_dmv returning live dependencies
    live_table = AgentTable("deps", ["OBJECT_TYPE", "OBJECT_NAME", "REFERENCED_OBJECT_TYPE", "REFERENCED_OBJECT_NAME"], [
        ["MEASURE", "TotalSales", "COLUMN", "Sales[Amount]"],
        ["MEASURE", "LiveOnlyMeasure", "COLUMN", "Sales[Discount]"],
    ])

    # Mock TMDL model loading
    with patch("agentdata.pbip.dmv.run_dmv", return_value=live_table):
        with patch("agentdata.pbip.normalize.load_all") as mock_load:
            class MockMeasure:
                def __init__(self, name, deps):
                    self.name = name
                    self.dependencies = deps

            class MockTable:
                def __init__(self, measures):
                    self.measures = measures

            class MockModel:
                def __init__(self, tables):
                    self.tables = tables

            m1 = MockMeasure("TotalSales", ["Sales[Amount]"])
            m2 = MockMeasure("FileOnlyMeasure", ["Sales[Tax]"])
            mock_load.return_value = (MockModel([MockTable([m1, m2])]), None, None)

            reconciled = DMV.refs_live("dummy_pbip", "localhost:50000")
            assert reconciled.columns == ["object", "refers_to", "kind", "status"]

            status_map = {r[0]: r[3] for r in reconciled.rows}
            assert status_map["TotalSales"] == "synced"
            assert status_map["LiveOnlyMeasure"] == "live-only"
            assert status_map["FileOnlyMeasure"] == "file-only"


def test_page_cost():
    # Mock status, trace, navigate
    fake_inst = type("Instance", (), {"server": "localhost:51234", "database": "db", "file": None, "port": 51234})()
    with patch("agentdata.pbip.desktop.status", return_value=[fake_inst]):
        with patch("agentdata.pbip.screenshot.navigate_page") as mock_nav:
            with patch("agentdata.pbip.trace.start_trace") as mock_start:
                with patch("agentdata.pbip.trace.stop_trace"):
                    with patch("agentdata.pbip.trace.report_trace") as mock_rep:
                        mock_start.return_value = (None, "trace.jsonl", {})
                        mock_rep.return_value = AgentTable("trace_rep", ["hash", "visual", "count", "total_ms", "median_ms", "mode", "query"], [
                            ["h1", "Sales Chart", 2, 150, 75, "vertipaq", "EVALUATE ..."],
                            ["h2", "Sales Chart", 1, 50, 50, "formula", "EVALUATE ..."],
                            ["h3", "KPI Card", 1, 20, 20, "vertipaq", "EVALUATE ..."],
                        ])

                        cost_table = DMV.page_cost(1234, "SummaryPage", seconds=1)
                        assert cost_table.columns == ["visual", "query_count", "total_ms"]
                        assert len(cost_table.rows) == 2
                        assert cost_table.rows[0][0] == "Sales Chart"
                        assert cost_table.rows[0][1] == 3
                        assert cost_table.rows[0][2] == 200
                        assert cost_table.rows[1][0] == "KPI Card"
                        assert cost_table.rows[1][2] == 20
                        assert cost_table.raw["total_page_ms"] == 220


def test_cli_dmv(capsys):
    with patch("agentdata.pbip.dmv.run_dmv") as mock_dmv:
        mock_dmv.return_value = AgentTable("dmv_deps", ["obj", "ref"], [["M1", "C1"]])
        with pytest.raises(SystemExit) as exc:
            main(["dmv", "deps", "--server", "localhost:50000"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "M1" in captured.out


def test_cli_page_cost(capsys):
    with patch("agentdata.pbip.dmv.page_cost") as mock_pc:
        mock_pc.return_value = AgentTable("page_cost", ["visual", "query_count", "total_ms"], [["Chart1", 2, 80]])
        with pytest.raises(SystemExit) as exc:
            main(["page-cost", "--page", "Page1", "--pid", "9999", "--seconds", "2"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Chart1" in captured.out


def test_cli_refs_live(capsys):
    with patch("agentdata.pbip.dmv.refs_live") as mock_rl:
        mock_rl.return_value = AgentTable("refs_live", ["object", "refers_to", "kind", "status"], [["M1", "C1", "measure", "synced"]])
        with pytest.raises(SystemExit) as exc:
            main(["refs", "dummy.pbip", "--live", "--server", "localhost:50000"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "synced" in captured.out
