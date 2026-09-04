"""Tests for deploy, refresh, and verify loop in Power BI (ad-pbi)."""
from __future__ import annotations
import glob
import json
import os
import pytest

from agentdata import cli_pbi
from agentdata.pbi.client import FabricError
from agentdata.pbi.deploy import deploy_model
from agentdata.pbi.refresh import parse_service_exception, poll_refresh
from agentdata.pbi.verify import verify_service_parity
from agentdata.setup.steps import powerbi
from agentdata.setup.wizard import Context, Detectors

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pbip")
SAMPLE_REPORT_DIR = os.path.join(FIXTURES_DIR, "Sample.Report")
SAMPLE_MODEL_DIR = os.path.join(FIXTURES_DIR, "Sample.SemanticModel")
SAMPLE_TMDL_DIR = os.path.join(SAMPLE_MODEL_DIR, "definition")


class FakeDeployRefreshRunner:
    """Mock runner for TE2, az, and git calls."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.git_dirty: bool = False
        self.te2_fail: bool = False
        self.refresh_status_sequence: list[dict] = []
        self.dmv_rows: list[list[str]] = [
            ["Customers", "Customers-2024", "1500", "2026-09-01T12:00:00Z"],
            ["Sales", "Sales-2024", "45000", "2026-09-01T12:05:00Z"],
        ]
        self.dax_measure_values: dict[str, Any] = {
            "Total Sales": 42000.0,
            "Ext Measure": 100.0,
        }
        self.desktop_measure_values: dict[str, Any] = {
            "Total Sales": 42000.0,
            "Ext Measure": 100.0,
        }

    def __call__(self, cmd: list[str], timeout: int = 120, **kwargs) -> tuple[int, str, str, float]:
        self.calls.append(list(cmd))
        tool = os.path.basename(str(cmd[0])).split(".")[0].lower()

        # Git status
        if tool == "git" and "status" in cmd:
            if self.git_dirty:
                return 0, " M Sample.SemanticModel/definition/tables/Sales.tmdl\n", "", 0.01
            return 0, "", "", 0.01

        # TabularEditor (TE2)
        if "tabulareditor" in tool or tool == "te2":
            if self.te2_fail:
                return 1, "", "Error: The credentials supplied for the AnalysisServices source are not valid.\n", 0.01

            # If dry-run with -X, create the output xmla file
            if "-X" in cmd:
                xmla_out = cmd[cmd.index("-X") + 1]
                os.makedirs(os.path.dirname(os.path.abspath(xmla_out)), exist_ok=True)
                with open(xmla_out, "w", encoding="utf-8") as f:
                    f.write("<Batch xmlns='http://schemas.microsoft.com/analysisservices/2003/engine'><Deploy/></Batch>")

            return 0, "Model successfully deployed / verified.\n", "", 0.01

        # DAX Studio (dscmd) or TE2 for DAX/DMV queries
        if "dscmd" in tool or tool == "csv":
            out_csv = cmd[2] if len(cmd) > 2 else None
            q_text = " ".join(str(x) for x in cmd)
            if "-f" in cmd:
                try:
                    qf = cmd[cmd.index("-f") + 1]
                    if os.path.isfile(qf):
                        q_text += " " + open(qf, encoding="utf-8").read()
                except Exception:
                    pass

            # If DMV query
            if "DISCOVER" in q_text:
                if out_csv and os.path.dirname(out_csv):
                    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
                    lines = ["TABLE_ID,PARTITION_NAME,ROWS_COUNT,MODIFY_TIME"]
                    for r in self.dmv_rows:
                        lines.append(",".join(r))
                    with open(out_csv, "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                return 0, "rows=2", "", 0.01

            # Measure evaluation query
            for m_name, val in self.dax_measure_values.items():
                if f"[{m_name}]" in q_text:
                    if out_csv and os.path.dirname(out_csv):
                        os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
                        with open(out_csv, "w", encoding="utf-8") as f:
                            f.write(f"Value\n{val}\n")
                    return 0, "rows=1", "", 0.01

            if out_csv and os.path.dirname(out_csv):
                os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
                with open(out_csv, "w", encoding="utf-8") as f:
                    f.write("Value\n42.0\n")
            return 0, "rows=1", "", 0.01

        # Azure CLI (az)
        if tool == "az":
            sub = cmd[1] if len(cmd) > 1 else ""
            if sub == "account":
                return 0, json.dumps({"accessToken": "fake.token"}), "", 0.01
            if sub == "rest":
                url = cmd[cmd.index("--url") + 1] if "--url" in cmd else ""
                method = cmd[cmd.index("--method") + 1].upper() if "--method" in cmd else "GET"

                if url.endswith("/v1/workspaces"):
                    return 0, json.dumps({"value": [{"id": "ws-100", "displayName": "Sales Workspace"}]}), "", 0.01
                if url.endswith("/semanticModels"):
                    return 0, json.dumps({"value": [{"id": "mod-100", "displayName": "Sample"}]}), "", 0.01
                if "/refreshes" in url:
                    if self.refresh_status_sequence:
                        item = self.refresh_status_sequence.pop(0) if len(self.refresh_status_sequence) > 1 else self.refresh_status_sequence[0]
                        return 0, json.dumps({"value": [item]}), "", 0.01
                    return 0, json.dumps({
                        "value": [{
                            "id": 99999,
                            "refreshType": "Full",
                            "startTime": "2026-09-01T12:00:00Z",
                            "endTime": "2026-09-01T12:05:00Z",
                            "status": "Completed"
                        }]
                    }), "", 0.01

        return 0, json.dumps({"value": []}), "", 0.01


@pytest.fixture
def fake_runner(monkeypatch, tmp_path):
    runner = FakeDeployRefreshRunner()
    from agentdata import proc, config as C
    monkeypatch.setattr(proc, "run", runner)

    # Clean deploy stamp file if present
    stamp_file = os.path.join(".agent", "out", "deploy_stamp.json")
    if os.path.exists(stamp_file):
        try:
            os.remove(stamp_file)
        except OSError:
            pass

    dummy_dscmd = tmp_path / "dscmd.exe"
    dummy_dscmd.write_text("dummy")
    dummy_te2 = tmp_path / "te2.exe"
    dummy_te2.write_text("dummy")

    cfg = {
        "powerbi": {
            "tools": {
                "dscmd_exe": str(dummy_dscmd),
                "te2_exe": str(dummy_te2),
            },
            "workspaces": [
                {
                    "name": "Sales Workspace",
                    "xmla": "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace",
                    "models": ["Sample"],
                }
            ],
        }
    }
    monkeypatch.setattr(C, "load", lambda: cfg)
    return runner


def test_deploy_refuses_dirty_tree(fake_runner, capsys):
    """ad-pbi deploy refuses to deploy when git working tree has uncommitted changes."""
    fake_runner.git_dirty = True
    rc = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "clean_tree_required" in err
    assert "git working tree has uncommitted changes" in err

    # With --allow-dirty it proceeds
    rc_dirty = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample", "--allow-dirty", "--dry-run"])
    assert rc_dirty == 0


def test_deploy_dry_run_generates_xmla(fake_runner, capsys):
    """ad-pbi deploy --dry-run invokes TE2 with -X and generates XMLA script without deploying."""
    rc = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status: preview" in out
    assert "log:" in out

    # Assert TE2 was called with -X and base flags
    te2_calls = [c for c in fake_runner.calls if any("tabulareditor" in str(x).lower() or "te2" in str(x).lower() for x in c)]
    assert len(te2_calls) > 0
    deploy_call = te2_calls[0]
    assert "-X" in deploy_call
    assert "-S" in deploy_call
    assert "-C" in deploy_call
    assert "-O" in deploy_call
    assert "-E" in deploy_call
    assert "-W" in deploy_call
    assert "-D" not in deploy_call


def test_deploy_live_and_already_deployed_stamp(fake_runner, capsys):
    """Live deploy executes TE2 -D and writes stamp; repeating immediately reports already_deployed."""
    rc = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status: deployed" in out

    # Second deploy with same files detects already_deployed
    rc2 = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "status: already_deployed" in out2

    # With --force it redeploys
    rc3 = cli_pbi.main(["deploy", SAMPLE_TMDL_DIR, "--workspace", "Sales Workspace", "--model", "Sample", "--force"])
    assert rc3 == 0
    out3 = capsys.readouterr().out
    assert "status: deployed" in out3


def test_parse_service_exception_fields():
    """parse_service_exception extracts error_code, table, partition, message, and hint."""
    raw_exc = {
        "errorCode": "DMTS_OAuthTokenRefreshFailedError",
        "errorDescription": "Table: Customers, Partition: Customers-2024. [DataSource.Error] An error occurred while evaluating the query: Access Denied.",
    }
    parsed = parse_service_exception(raw_exc)
    assert parsed["error_code"] == "DMTS_OAuthTokenRefreshFailedError"
    assert parsed["table"] == "Customers"
    assert parsed["partition"] == "Customers-2024"
    assert "[DataSource.Error]" in parsed["hint"]


def test_refresh_wait_completed(fake_runner, capsys):
    """ad-pbi refresh --wait polls until Completed and returns duration."""
    fake_runner.refresh_status_sequence = [
        {"id": 1, "status": "InProgress", "refreshType": "Full"},
        {"id": 1, "status": "Completed", "refreshType": "Full", "startTime": "2026-09-01T12:00:00Z", "endTime": "2026-09-01T12:02:00Z"},
    ]
    rc = cli_pbi.main(["refresh", "--workspace", "Sales Workspace", "--model", "Sample", "--wait", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status: Completed" in out
    assert "duration_s:" in out


def test_refresh_wait_failed_structured_error(fake_runner, capsys):
    """ad-pbi refresh --wait parses serviceExceptionJson on Failed."""
    fake_runner.refresh_status_sequence = [
        {
            "id": 2,
            "status": "Failed",
            "refreshType": "Full",
            "serviceExceptionJson": json.dumps({
                "errorCode": "MashupException",
                "errorDescription": "Table: Sales, Partition: Sales-2024. [DataSource.Error] Connection timed out.",
            }),
        }
    ]
    rc = cli_pbi.main(["refresh", "--workspace", "Sales Workspace", "--model", "Sample", "--wait", "10"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "refresh_failed" in err
    assert "MashupException" in err
    assert "Sales" in err


def test_refresh_history_table(fake_runner, capsys):
    """ad-pbi refresh --history outputs TOON table of recent refreshes."""
    rc = cli_pbi.main(["refresh", "--workspace", "Sales Workspace", "--model", "Sample", "--history", "--top", "3"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "refreshes[1]{id,type,startTime,endTime,status}:" in out
    assert "99999,Full" in out


def test_refresh_partitions_table(fake_runner, capsys):
    """ad-pbi refresh --partitions outputs partition row counts over XMLA."""
    rc = cli_pbi.main(["refresh", "--workspace", "Sales Workspace", "--model", "Sample", "--partitions"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "partitions[2]{table,partition,rows,last_processed}:" in out
    assert "Customers,Customers-2024,1500" in out
    assert "Sales,Sales-2024,45000" in out


def test_verify_service_and_desktop_parity(fake_runner, capsys, monkeypatch):
    """ad-pbi verify runs report measures on service and compares Desktop parity."""
    from agentdata.pbip import desktop as DT
    # Mock DT.discover returning a fake instance with port
    fake_inst = DT.Instance(
        pid=1234, port=54321, server="localhost:54321",
        workspace_dir=None, workspace_name=None, title="Sample - Power BI Desktop",
        file="Sample.pbip", matched="Sample.pbip", source="test",
    )
    monkeypatch.setattr(DT, "discover", lambda: [fake_inst])

    # When values match: service has 42000.0, desktop has 42000.0
    rc = cli_pbi.main(["verify", "--pbip", SAMPLE_REPORT_DIR, "--workspace", "Sales Workspace", "--model", "Sample", "--pid", "1234"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "parity: ok" in out
    assert "tested_desktop: true" in out

    # When values mismatch: change desktop measure value
    fake_runner.desktop_measure_values["Total Sales"] = 99999.0
    # Update fake runner to return 99999.0 when query is for localhost:54321
    def mock_run(cmd, timeout=120, **kw):
        if "54321" in " ".join(cmd):
            out_csv = cmd[2] if len(cmd) > 2 else None
            if out_csv and os.path.dirname(out_csv):
                os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
                with open(out_csv, "w", encoding="utf-8") as f:
                    f.write("Value\n99999.0\n")
            return 0, "rows=1", "", 0.01
        return fake_runner(cmd, timeout=timeout, **kw)

    from agentdata import proc
    monkeypatch.setattr(proc, "run", mock_run)

    rc_mismatch = cli_pbi.main(["verify", "--pbip", SAMPLE_REPORT_DIR, "--workspace", "Sales Workspace", "--model", "Sample", "--pid", "1234"])
    assert rc_mismatch == 1
    out_mismatch = capsys.readouterr().out
    assert "parity: mismatch" in out_mismatch
    assert "Total Sales" in out_mismatch


def test_skills_contain_no_raw_te2_flag_strings():
    """Assert skills contain no raw TE2 flag strings (-S -C -O -E -W -P -Y), only ad-pbi verbs."""
    skills_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "skills")
    skill_files = glob.glob(os.path.join(skills_root, "**", "SKILL.md"), recursive=True)
    forbidden_patterns = ["-S -C -O -E -W", "-P -Y", "-R -M"]
    for path in skill_files:
        content = open(path, encoding="utf-8").read()
        for pat in forbidden_patterns:
            assert pat not in content, f"{path} contains raw TE2 flag string '{pat}'"


def test_doctor_online_refresh_history_check(monkeypatch):
    """ad-doctor --online verifies powerbi/refresh_history probe."""
    from agentdata.setup.wizard import AnswerPrompter

    class FakeDet(Detectors):
        def __init__(self):
            super().__init__()
            self.az = "az"

        def run(self, cmd, timeout=120):
            return 0, json.dumps({"value": [{"id": "ws-100", "displayName": "Sales"}, {"id": "mod-100", "displayName": "Sample"}], "status": "Completed"}), ""

    ctx = Context(
        cfg={"powerbi": {"workspaces": [{"name": "Sales", "xmla": "powerbi://api.powerbi.com/v1.0/myorg/Sales", "models": ["Sample"]}]}},
        det=FakeDet(),
        ask=AnswerPrompter(),
        online=True,
        interactive=False,
    )
    step = powerbi.PowerBIStep()
    step.verify(ctx)

    rh_check = next((c for c in ctx.checks if c.name == "powerbi/refresh_history"), None)
    assert rh_check is not None
    assert rh_check.status == "ok"
    assert "endpoint readable" in rh_check.detail

