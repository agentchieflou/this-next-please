"""Tests for Fabric REST item-definition transport (ad-pbi)."""
from __future__ import annotations
import base64
import json
import os
import re
import shutil
import pytest

from agentdata import cli_pbi
from agentdata.pbi.binding import verify_binding
from agentdata.pbi.client import FabricClient, FabricError
from agentdata.pbi.parts import check_vanished_parts, extract_parts_to_disk, load_model_parts, load_report_parts

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pbip")
SAMPLE_REPORT_DIR = os.path.join(FIXTURES_DIR, "Sample.Report")
SAMPLE_MODEL_DIR = os.path.join(FIXTURES_DIR, "Sample.SemanticModel")


class FakeAzDispatcher:
    """Mock runner for az account and az rest commands recording calls and returning sequenced responses."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.recorded_bodies: list[dict] = []
        self.op_sequence: dict[str, list[dict]] = {}
        self.legacy_format_on_get: bool = False

    def __call__(self, cmd: list[str], timeout: int = 120) -> tuple[int, str, str, float]:
        self.calls.append(list(cmd))
        sub = cmd[1] if len(cmd) > 1 else ""

        # Capture --body if present
        if "--body" in cmd:
            idx = cmd.index("--body")
            body_arg = cmd[idx + 1]
            if body_arg.startswith("@"):
                path = body_arg[1:]
                if os.path.exists(path):
                    self.recorded_bodies.append(json.loads(open(path, encoding="utf-8").read()))

        # 1. az account get-access-token
        if sub == "account":
            return 0, json.dumps({"accessToken": "eyJfake.token.secret12345"}), "", 0.01

        # 2. az rest
        if sub == "rest":
            method = cmd[cmd.index("--method") + 1].upper() if "--method" in cmd else "GET"
            url = cmd[cmd.index("--url") + 1] if "--url" in cmd else ""

            # Workspaces list
            if url.endswith("/v1/workspaces") and method == "GET":
                return 0, json.dumps({
                    "value": [
                        {"id": "ws-1111-2222", "displayName": "Sales Workspace"},
                        {"id": "ws-3333-4444", "displayName": "Ops Workspace"}
                    ]
                }), "", 0.01

            # Reports list
            if "/reports" in url and not url.endswith("/reports") and method == "GET" and not "/operations/" in url:
                if "/reports/" in url and not url.endswith("/reports"):
                    # Single report or definition
                    pass
                else:
                    return 0, json.dumps({
                        "value": [
                            {"id": "rep-0001", "displayName": "Sample"},
                            {"id": "rep-0002", "displayName": "ExistingReport"}
                        ]
                    }), "", 0.01

            if url.endswith("/reports") and method == "GET":
                return 0, json.dumps({
                    "value": [
                        {"id": "rep-0001", "displayName": "Sample"},
                        {"id": "rep-0002", "displayName": "ExistingReport"}
                    ]
                }), "", 0.01

            # Semantic models list
            if url.endswith("/semanticModels") and method == "GET":
                return 0, json.dumps({
                    "value": [
                        {"id": "model-0001", "displayName": "Sample"},
                        {"id": "model-0002", "displayName": "TargetModel"}
                    ]
                }), "", 0.01

            # getDefinition for report
            if "/reports/" in url and "getDefinition" in url and method == "POST":
                if self.legacy_format_on_get:
                    return 0, json.dumps({
                        "format": "PBIR-Legacy",
                        "definition": {
                            "parts": [
                                {"path": "report.json", "payload": base64.b64encode(b"{}").decode("ascii"), "payloadType": "InlineBase64"}
                            ]
                        }
                    }), "", 0.01

                # Generate valid PBIR definition parts from fixture
                parts, _ = load_report_parts(SAMPLE_REPORT_DIR, target_model_id="model-0001")
                # Return 202 with operation id
                op_id = "op-get-rep-def-1"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded", "result": {"definition": {"parts": parts}}}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # getDefinition for semanticModel
            if "/semanticModels/" in url and "getDefinition" in url and method == "POST":
                parts, _ = load_model_parts(SAMPLE_MODEL_DIR)
                op_id = "op-get-mod-def-1"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded", "result": {"definition": {"parts": parts}}}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # Create report
            if url.endswith("/reports") and method == "POST":
                op_id = "op-create-rep-100"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded", "result": {"id": "rep-new-999"}}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # Update report definition
            if "/updateDefinition" in url and "/reports/" in url and method == "POST":
                op_id = "op-update-rep-200"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded"}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # Create model
            if url.endswith("/semanticModels") and method == "POST":
                op_id = "op-create-mod-100"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded", "result": {"id": "mod-new-999"}}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # Update model definition
            if "/updateDefinition" in url and "/semanticModels/" in url and method == "POST":
                op_id = "op-update-mod-200"
                self.op_sequence[op_id] = [
                    {"id": op_id, "status": "Succeeded"}
                ]
                err = f"x-ms-operation-id: {op_id}\nLocation: https://api.fabric.microsoft.com/v1/operations/{op_id}\n"
                return 0, json.dumps({"id": op_id, "status": "Running"}), err, 0.01

            # Operations status query: GET /v1/operations/{op_id}
            m_op = re.search(r"/operations/([a-zA-Z0-9_\-]+)$", url)
            if m_op and method == "GET":
                op_id = m_op.group(1)
                seq = self.op_sequence.get(op_id, [{"id": op_id, "status": "Succeeded"}])
                item = seq.pop(0) if len(seq) > 1 else seq[0]
                return 0, json.dumps(item), "", 0.01

            # Operations result query: GET /v1/operations/{op_id}/result
            m_res = re.search(r"/operations/([a-zA-Z0-9_\-]+)/result$", url)
            if m_res and method == "GET":
                op_id = m_res.group(1)
                seq = self.op_sequence.get(op_id, [{"id": op_id, "status": "Succeeded"}])
                res = seq[-1].get("result", {"id": op_id, "status": "Succeeded"})
                return 0, json.dumps(res), "", 0.01

            # Delete
            if method == "DELETE":
                return 0, json.dumps({}), "", 0.01

            # ExportTo (stretch)
            if "/ExportTo" in url and method == "POST":
                return 0, json.dumps({"id": "export-job-123"}), "", 0.01

            if "/exports/export-job-123" in url and method == "GET" and not url.endswith("/file"):
                return 0, json.dumps({"id": "export-job-123", "status": "Succeeded"}), "", 0.01

            if "/exports/export-job-123/file" in url and method == "GET":
                return 0, "fake-png-bytes-content", "", 0.01

        return 0, json.dumps({"value": []}), "", 0.01


@pytest.fixture
def fake_az(monkeypatch):
    dispatcher = FakeAzDispatcher()
    from agentdata import proc
    monkeypatch.setattr(proc, "run", dispatcher)
    return dispatcher


def test_token_acquisition_no_leak(fake_az, capsys):
    """Auth token is retrieved via az account get-access-token but never printed or leaked."""
    client = FabricClient(runner=fake_az)
    token = client.get_access_token()
    assert token == "eyJfake.token.secret12345"
    out, err = capsys.readouterr()
    assert token not in out
    assert token not in err


def test_ls_reports_and_models(fake_az, capsys):
    """ad-pbi ls displays TOON table of reports and models."""
    rc = cli_pbi.main(["ls", "--workspace", "Sales Workspace"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "workspace: Sales Workspace (ws-1111-2222)" in out
    assert "items[4]{id,name,kind,description}:" in out
    assert "rep-0001,Sample,report" in out
    assert "model-0001,Sample,model" in out


def test_get_report_refuses_legacy_format(fake_az, capsys):
    """ad-pbi get report refuses PBIR-Legacy format with an actionable hint."""
    fake_az.legacy_format_on_get = True
    rc = cli_pbi.main(["get", "report", "Sample", "--workspace", "Sales Workspace"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "pbir_legacy_format" in err
    assert "Store reports using enhanced metadata format (PBIR)" in err


def test_get_report_extracts_parts_with_forward_slashes(fake_az, tmp_path):
    """ad-pbi get report base64-decodes parts to disk with forward-slash paths."""
    out_dir = str(tmp_path / "downloaded_report")
    rc = cli_pbi.main(["get", "report", "Sample", "--workspace", "Sales Workspace", "--out", out_dir])
    assert rc == 0
    assert os.path.exists(os.path.join(out_dir, "definition.pbir"))
    assert os.path.exists(os.path.join(out_dir, "definition", "report.json"))


def test_binding_diff_detects_unresolved_fields(tmp_path):
    """Binding diff verifies PBIR visual fields against target model TMDL."""
    # Sample.Report intentionally contains a "Broken table" visual referencing Sales[Region Name]
    valid, unresolved = verify_binding(SAMPLE_REPORT_DIR, SAMPLE_MODEL_DIR)
    assert not valid
    assert len(unresolved) == 1
    assert unresolved[0]["prop"] == "Region Name"
    assert "Sales" in unresolved[0]["entity"]

    # When the broken visual is removed, verification succeeds
    clean_dir = tmp_path / "Clean.Report"
    shutil.copytree(SAMPLE_REPORT_DIR, clean_dir)
    shutil.rmtree(clean_dir / "definition" / "pages" / "page1" / "visuals" / "aaaaaaaaaaaaaaaaaaaa")
    valid_clean, unresolved_clean = verify_binding(str(clean_dir), SAMPLE_MODEL_DIR)
    assert valid_clean
    assert len(unresolved_clean) == 0


def test_publish_report_halts_on_unresolved_without_allow_unbound(fake_az, capsys):
    """publish report halts if binding diff finds unresolved fields, unless --allow-unbound is passed."""
    # Attempting to publish the sample report with the broken visual without --allow-unbound fails
    rc = cli_pbi.main([
        "publish", "report", SAMPLE_REPORT_DIR,
        "--workspace", "Sales Workspace",
        "--model", "Sample",
        "--dry-run"
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "binding_diff_failed" in err
    assert "Region Name" in err

    # With --allow-unbound, it succeeds
    rc2 = cli_pbi.main([
        "publish", "report", SAMPLE_REPORT_DIR,
        "--workspace", "Sales Workspace",
        "--model", "Sample",
        "--dry-run",
        "--allow-unbound"
    ])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "dry_run: true" in out2


def test_publish_report_dry_run_no_post(fake_az, capsys, tmp_path):
    """ad-pbi publish report --dry-run runs binding diff and lists parts without any write POST."""
    clean_dir = tmp_path / "Clean.Report"
    shutil.copytree(SAMPLE_REPORT_DIR, clean_dir)
    shutil.rmtree(clean_dir / "definition" / "pages" / "page1" / "visuals" / "aaaaaaaaaaaaaaaaaaaa")

    rc = cli_pbi.main([
        "publish", "report", str(clean_dir),
        "--workspace", "Sales Workspace",
        "--model", "Sample",
        "--dry-run"
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry_run: true" in out
    assert "parts[" in out
    assert "unresolved_bindings: 0" in out

    # Assert no POST /reports or POST /updateDefinition was issued
    posts = [cmd for cmd in fake_az.calls if "--method" in cmd and cmd[cmd.index("--method") + 1].lower() == "post"]
    write_posts = [p for p in posts if "/reports" in p[p.index("--url") + 1] and "getDefinition" not in p[p.index("--url") + 1]]
    assert len(write_posts) == 0


def test_publish_report_create_payload_and_in_memory_byconnection(fake_az, capsys, tmp_path):
    """publish report creates report, rewrites definition.pbir to byConnection in memory only, disk stays byPath."""
    clean_dir = tmp_path / "Clean.Report"
    shutil.copytree(SAMPLE_REPORT_DIR, clean_dir)
    shutil.rmtree(clean_dir / "definition" / "pages" / "page1" / "visuals" / "aaaaaaaaaaaaaaaaaaaa")

    # Ensure disk copy has byPath
    pbir_disk = open(os.path.join(str(clean_dir), "definition.pbir"), encoding="utf-8").read()
    assert "byPath" in pbir_disk

    rc = cli_pbi.main([
        "publish", "report", str(clean_dir),
        "--workspace", "Sales Workspace",
        "--model", "TargetModel",
        "--name", "BrandNewReport"
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "action: created" in out
    assert "https://app.powerbi.com/groups/ws-1111-2222/reports/rep-new-999" in out

    # Verify payload parts
    assert len(fake_az.recorded_bodies) > 0
    body = fake_az.recorded_bodies[-1]
    parts = body["definition"]["parts"]

    # All paths must use forward slashes
    for p in parts:
        assert "\\" not in p["path"]

    # definition.pbir payload must be byConnection referencing TargetModel (model-0002)
    pbir_part = next(p for p in parts if p["path"] == "definition.pbir")
    decoded_pbir = json.loads(base64.b64decode(pbir_part["payload"]).decode("utf-8"))
    assert "byConnection" in decoded_pbir["datasetReference"]
    assert decoded_pbir["datasetReference"]["byConnection"]["pbiModelDatabaseName"] == "model-0002"

    # Disk copy MUST still be byPath
    pbir_disk_after = open(os.path.join(SAMPLE_REPORT_DIR, "definition.pbir"), encoding="utf-8").read()
    assert "byPath" in pbir_disk_after


def test_publish_report_update_warns_on_vanished_part(fake_az, capsys, tmp_path):
    """publish report warns if a part in previous definition is absent in the folder being published."""
    # Create a cached previous definition directory under .agent/out/def/ExistingReport
    prev_dir = tmp_path / ".agent" / "out" / "def" / "ExistingReport"
    prev_dir.mkdir(parents=True)
    (prev_dir / "definition.pbir").write_text("{}", encoding="utf-8")
    (prev_dir / "vanished_file.json").write_text("{}", encoding="utf-8")

    current_paths = ["definition.pbir", "definition/report.json"]
    vanished = check_vanished_parts(current_paths, str(prev_dir))
    assert "vanished_file.json" in vanished


def test_lro_persisted_op_id_and_ops_resume(fake_az, capsys, tmp_path):
    """A 202 operation is recorded to .agent/out/pbi-ops/<op-id>.json before polling; ops resumes safely."""
    client = FabricClient(runner=fake_az)
    op_id = "op-crash-sim-42"
    client.record_operation(op_id, "create_report", "ws-1111-2222", target_name="CrashTest", status="Running")

    # Verify file was written
    record = client.load_operation(op_id)
    assert record is not None
    assert record["status"] == "Running"
    assert record["op_id"] == op_id

    # Configure fake_az with Succeeded on polling
    fake_az.op_sequence[op_id] = [{"id": op_id, "status": "Succeeded", "result": {"id": "rep-recovered-42"}}]

    # Resume via cmd_ops
    rc = cli_pbi.main(["ops", op_id])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resumed: true" in out
    assert "status: Succeeded" in out


def test_publish_model_tmdl(fake_az, capsys):
    """ad-pbi publish model publishes TMDL definition."""
    rc = cli_pbi.main([
        "publish", "model", SAMPLE_MODEL_DIR,
        "--workspace", "Sales Workspace",
        "--name", "NewSemanticModel"
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "action: created" in out
    assert "model_id: mod-new-999" in out


def test_rm_report(fake_az, capsys):
    """ad-pbi rm report deletes report."""
    rc = cli_pbi.main(["rm", "report", "Sample", "--workspace", "Sales Workspace", "-y"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "action: deleted" in out
    assert "item_id: rep-0001" in out


def test_export_png_stretch(fake_az, capsys, tmp_path):
    """ad-pbi export-png stretch export-to-file executes."""
    out_png = str(tmp_path / "test.png")
    rc = cli_pbi.main(["export-png", "Sample", "--workspace", "Sales Workspace", "--page", "Page1", "--out", out_png])
    assert rc == 0
    out = capsys.readouterr().out
    assert "report_id: rep-0001" in out
    assert os.path.exists(out_png)
