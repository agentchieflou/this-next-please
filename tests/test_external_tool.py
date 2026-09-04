import json
import os
import shutil
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from agentdata.pbip import external_tool as EXT
from agentdata.cli_pbip import build_parser, main
from agentdata.setup.wizard import Context, Detectors, AnswerPrompter
from agentdata.setup.steps.powerbi import PowerBIStep


def test_render_tool_json():
    data = EXT.render_tool_json(python_exe="C:/custom/python.exe")
    assert data["version"] == "1.0.0"
    assert data["name"] == "agentdata"
    assert data["path"] == "C:/custom/python.exe"
    assert '-m agentdata pbip handoff --server "%server%" --database "%database%"' in data["arguments"]
    assert data["iconData"].startswith("data:image/png;base64,")


def test_render_tool_json_with_project():
    data = EXT.render_tool_json(python_exe="C:/custom/python.exe", project_dir="C:/Repo/MyReport")
    assert '--project "C:/Repo/MyReport"' in data["arguments"]


def test_register_tool_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ok, dest, hint = EXT.register_tool(target_dir=tmp_dir, python_exe="C:/Python312/python.exe")
        assert ok is True
        assert dest == os.path.join(tmp_dir, "agentdata.pbitool.json")
        assert hint is None
        assert os.path.exists(dest)

        with open(dest, encoding="utf-8") as f:
            content = json.load(f)
        assert content["name"] == "agentdata"
        assert content["path"] == "C:/Python312/python.exe"


def test_register_tool_permission_error():
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch("shutil.copy2", side_effect=PermissionError("Access denied")):
        ok, dest, hint = EXT.register_tool(target_dir=tmp_dir)
        assert ok is False
        assert dest == os.path.join(tmp_dir, "agentdata.pbitool.json")
        assert hint is not None
        assert "Copy-Item" in hint
        assert "PowerShell" in hint


def test_is_external_tools_enabled_runner():
    mock_run_disabled = MagicMock(return_value=(0, "0\n", ""))
    enabled, msg = EXT.is_external_tools_enabled(run=mock_run_disabled)
    assert enabled is False
    assert "disabled" in msg

    mock_run_enabled = MagicMock(return_value=(0, "1\n", ""))
    enabled, msg = EXT.is_external_tools_enabled(run=mock_run_enabled)
    assert enabled is True


def test_handoff_and_read_fresh():
    with tempfile.TemporaryDirectory() as tmp_dir:
        res = EXT.handoff(server="localhost:54321", database="test-guid-1234", project_dir=tmp_dir)
        assert res["ok"] is True
        assert res["server"] == "localhost:54321"
        assert res["database"] == "test-guid-1234"

        desktop_json = os.path.join(tmp_dir, ".agent", "desktop.json")
        assert os.path.exists(desktop_json)

        with patch("agentdata.pbip.external_tool.is_pid_alive", return_value=True):
            handoff_data = EXT.read_handoff(project_dir=tmp_dir)
            assert handoff_data is not None
            assert handoff_data["server"] == "localhost:54321"
            assert handoff_data["database"] == "test-guid-1234"


def test_read_handoff_stale():
    with tempfile.TemporaryDirectory() as tmp_dir:
        agent_dir = os.path.join(tmp_dir, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
        with open(os.path.join(agent_dir, "desktop.json"), "w", encoding="utf-8") as f:
            json.dump({
                "server": "localhost:54321",
                "database": "guid",
                "handed_off_at": stale_time,
            }, f)

        # Default max_age is 8h -> 9h is stale
        assert EXT.read_handoff(project_dir=tmp_dir, max_age_seconds=8 * 3600) is None
        # With larger max_age (10h) -> not stale
        assert EXT.read_handoff(project_dir=tmp_dir, max_age_seconds=10 * 3600) is not None


def test_read_handoff_dead_pid():
    with tempfile.TemporaryDirectory() as tmp_dir:
        agent_dir = os.path.join(tmp_dir, ".agent")
        os.makedirs(agent_dir, exist_ok=True)
        now_time = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(agent_dir, "desktop.json"), "w", encoding="utf-8") as f:
            json.dump({
                "server": "localhost:54321",
                "database": "guid",
                "pid": 999999,
                "handed_off_at": now_time,
            }, f)

        with patch("agentdata.pbip.external_tool.is_pid_alive", return_value=False):
            assert EXT.read_handoff(project_dir=tmp_dir) is None


def test_cli_handoff_and_register_parser():
    parser = build_parser()
    args = parser.parse_args(["handoff", "--server", "localhost:54321", "--database", "test-db"])
    assert args.cmd == "handoff"
    assert args.server == "localhost:54321"
    assert args.database == "test-db"

    args_reg = parser.parse_args(["register-tool", "--python", "C:/python.exe", "--project", "C:/proj"])
    assert args_reg.cmd == "register-tool"
    assert args_reg.python == "C:/python.exe"
    assert args_reg.project == "C:/proj"


def test_doctor_powerbi_external_tool_check():
    ctx = Context(cfg={}, det=Detectors(), ask=AnswerPrompter())
    step = PowerBIStep()
    found = {
        "tools": {"pbi_desktop_exe": None, "te2_exe": None, "dscmd_exe": None, "az_exe": None},
        "az": None,
        "workspaces": [],
    }

    with patch("agentdata.pbip.external_tool.is_external_tools_enabled", return_value=(True, "enabled")), \
         patch("agentdata.pbip.external_tool.external_tools_dir", return_value="/nonexistent/ext_tools"):
        step.check(ctx, found)
        ext_rows = [r for r in ctx.checks if r.name == "powerbi/external_tool"]
        assert len(ext_rows) == 1
        assert ext_rows[0].status == "warn"
        assert "not registered" in ext_rows[0].detail
