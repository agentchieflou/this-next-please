"""Fabric REST API client for Power BI reports and semantic models."""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
from typing import Any, Callable

from .. import config as C
from .. import proc
from ..version import version_string

FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
POWERBI_RESOURCE = "https://analysis.windows.net/powerbi/api"
POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class FabricError(Exception):
    """An error from the Fabric REST API or client operation."""

    def __init__(self, code: str, msg: str, hint: str = "", detail: dict | None = None):
        super().__init__(msg)
        self.code, self.msg, self.hint, self.detail = code, msg, hint, detail or {}

    def to_dict(self) -> dict:
        d = {"ok": False, "code": self.code, "error": self.msg}
        if self.hint:
            d["hint"] = self.hint
        if self.detail:
            d["detail"] = self.detail
        return d


class FabricClient:
    """Client for Fabric item-definition transport (reports and semantic models)."""

    def __init__(self, az_exe: str | None = None, tenant: str | None = None,
                 runner: Callable[..., tuple[int, str, str, float]] | None = None):
        self.az = az_exe or "az"
        self.tenant = tenant
        self.runner = runner or proc.run
        from ..update import version as get_version
        self.version = get_version()

    def get_access_token(self, tenant: str | None = None) -> str:
        """Fetch bearer token via `az account get-access-token`. Token is never logged or stored."""
        t = tenant or self.tenant or C.get(C.load(), "powerbi.tenant_id")
        cmd = [self.az, "account", "get-access-token", "--resource", FABRIC_RESOURCE, "-o", "json"]
        if t:
            cmd.extend(["--tenant", str(t)])
        res = self.runner(cmd, timeout=30)
        rc, out, err = res[0], res[1], res[2]
        if rc != 0:
            err_msg = (err or out).strip()
            raise FabricError("auth_failed", f"failed to get Fabric access token via az: {err_msg}",
                              "run `az login --allow-no-subscriptions` or check tenant ID")
        try:
            data = json.loads(out or "{}")
            token = data.get("accessToken")
            if not token:
                raise ValueError("missing accessToken in response")
            return str(token)
        except Exception as e:
            raise FabricError("auth_failed", f"malformed token response from az: {e}",
                              "run `az login --allow-no-subscriptions`") from None

    def rest_call(self, method: str, url: str, body: dict | None = None,
                  headers: list[str] | None = None, resource: str = FABRIC_RESOURCE,
                  check: bool = True, timeout: int = 120) -> tuple[int, Any, dict[str, str], str]:
        """Execute a REST call via `az rest`. Returns (rc, parsed_json, response_headers, stdout)."""
        cmd = [self.az, "rest", "--method", method.lower(), "--url", url, "--resource", resource, "-o", "json", "--verbose"]
        ua_header = f"User-Agent=agentdata/{self.version}"
        cmd.extend(["--headers", ua_header])
        if headers:
            for h in headers:
                cmd.extend(["--headers", h])

        tmp_body: str | None = None
        if body is not None:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
                json.dump(body, f)
                tmp_body = f.name
            cmd.extend(["--body", f"@{tmp_body}"])

        try:
            res = self.runner(cmd, timeout=timeout)
            rc, out, err = res[0], res[1], res[2]
        finally:
            if tmp_body and os.path.exists(tmp_body):
                try:
                    os.unlink(tmp_body)
                except OSError:
                    pass

        # Parse response headers from verbose stderr
        resp_headers: dict[str, str] = {}
        for line in (err or "").splitlines():
            line = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                kl = k.strip().lower()
                if kl in ("x-ms-operation-id", "location", "retry-after", "operation-location", "content-type"):
                    resp_headers[kl] = v.strip()

        parsed: Any = None
        if out and out.strip():
            try:
                parsed = json.loads(out)
            except ValueError:
                parsed = None

        # Check if operation ID was returned in JSON body
        if isinstance(parsed, dict):
            if "id" in parsed and "x-ms-operation-id" not in resp_headers:
                # If body is an operation response
                if parsed.get("status") in ("Running", "NotStarted", "Succeeded", "Failed"):
                    resp_headers["x-ms-operation-id"] = str(parsed["id"])
            elif "operationId" in parsed and "x-ms-operation-id" not in resp_headers:
                resp_headers["x-ms-operation-id"] = str(parsed["operationId"])

        if check and rc != 0:
            msg = (err or out or "unknown error").strip()
            # Strip any potential token from error message
            msg = re.sub(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]", msg)
            raise FabricError("rest_failed", f"Fabric REST call failed: {msg}", detail={"method": method, "url": url})

        return rc, parsed, resp_headers, out

    # ---------- Workspaces & Resolution ----------

    def list_workspaces(self) -> list[dict]:
        """List all accessible workspaces."""
        _, data, _, _ = self.rest_call("GET", f"{FABRIC_API_BASE}/workspaces")
        if isinstance(data, dict):
            return list(data.get("value", []))
        return []

    def resolve_workspace(self, name_or_id: str) -> tuple[str, str]:
        """Resolve workspace name or GUID to (workspace_id, display_name)."""
        if GUID_RE.match(name_or_id):
            return name_or_id, name_or_id
        workspaces = self.list_workspaces()
        for ws in workspaces:
            if ws.get("displayName", "").strip().lower() == name_or_id.strip().lower():
                return str(ws["id"]), str(ws["displayName"])
            if ws.get("id", "").strip().lower() == name_or_id.strip().lower():
                return str(ws["id"]), str(ws.get("displayName", ws["id"]))
        raise FabricError("workspace_not_found", f"workspace '{name_or_id}' not found",
                          "run `ad-pbi ls --workspace ...` or check workspace permissions")

    def list_items(self, workspace_id: str, kind: str | None = None) -> list[dict]:
        """List reports, semantic models, or both in a workspace."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        out: list[dict] = []
        if kind in (None, "report", "reports"):
            rc, data, _, _ = self.rest_call("GET", f"{FABRIC_API_BASE}/workspaces/{ws_id}/reports", check=False)
            if rc == 0 and isinstance(data, dict):
                for item in data.get("value", []):
                    item["kind"] = "report"
                    out.append(item)
        if kind in (None, "model", "models", "semanticmodel", "semanticmodels"):
            rc, data, _, _ = self.rest_call("GET", f"{FABRIC_API_BASE}/workspaces/{ws_id}/semanticModels", check=False)
            if rc == 0 and isinstance(data, dict):
                for item in data.get("value", []):
                    item["kind"] = "model"
                    out.append(item)
        return out

    def resolve_item(self, workspace_id: str, name_or_id: str, kind: str) -> tuple[str, str]:
        """Resolve report or model name/GUID to (item_id, display_name)."""
        if GUID_RE.match(name_or_id):
            return name_or_id, name_or_id
        items = self.list_items(workspace_id, kind=kind)
        for it in items:
            if it.get("displayName", "").strip().lower() == name_or_id.strip().lower():
                return str(it["id"]), str(it["displayName"])
            if it.get("id", "").strip().lower() == name_or_id.strip().lower():
                return str(it["id"]), str(it.get("displayName", it["id"]))
        raise FabricError("item_not_found", f"{kind} '{name_or_id}' not found in workspace",
                          f"run `ad-pbi ls --workspace {workspace_id} --kind {kind}` to see available items")

    # ---------- Operations persistence & polling ----------

    def _op_file(self, op_id: str) -> str:
        ops_dir = os.path.join(".agent", "out", "pbi-ops")
        os.makedirs(ops_dir, exist_ok=True)
        return os.path.join(ops_dir, f"{op_id}.json")

    def record_operation(self, op_id: str, op_type: str, workspace_id: str,
                         target_id: str = "", target_name: str = "", status: str = "Running",
                         detail: dict | None = None) -> None:
        """Record an operation to disk BEFORE polling so a crash never re-POSTs."""
        path = self._op_file(op_id)
        record = {
            "op_id": op_id,
            "type": op_type,
            "workspace_id": workspace_id,
            "target_id": target_id,
            "target_name": target_name,
            "status": status,
            "started_at": time.time(),
            "updated_at": time.time(),
            "detail": detail or {},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

    def update_operation(self, op_id: str, status: str, result: dict | None = None, error: str = "") -> None:
        """Update an existing operation record."""
        path = self._op_file(op_id)
        record = {}
        if os.path.exists(path):
            try:
                record = json.loads(open(path, encoding="utf-8").read())
            except Exception:
                record = {}
        record.update({
            "op_id": op_id,
            "status": status,
            "updated_at": time.time(),
        })
        if result:
            record["result"] = result
        if error:
            record["error"] = error
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

    def load_operation(self, op_id: str) -> dict | None:
        """Load an operation record from disk."""
        path = self._op_file(op_id)
        if os.path.exists(path):
            try:
                return json.loads(open(path, encoding="utf-8").read())
            except Exception:
                return None
        return None

    def poll_operation(self, op_id: str, max_attempts: int = 60, interval: float = 1.0) -> dict:
        """Poll GET /v1/operations/{op_id} until Succeeded or Failed."""
        url = f"{FABRIC_API_BASE}/operations/{op_id}"
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            rc, data, headers, _ = self.rest_call("GET", url, check=False)
            if rc == 0 and isinstance(data, dict):
                st = data.get("status", "")
                if st == "Succeeded":
                    # Fetch result if available
                    res_url = f"{FABRIC_API_BASE}/operations/{op_id}/result"
                    r_rc, r_data, _, _ = self.rest_call("GET", res_url, check=False)
                    res = r_data if (r_rc == 0 and isinstance(r_data, dict)) else data
                    self.update_operation(op_id, "Succeeded", result=res)
                    return res
                if st == "Failed":
                    err_detail = data.get("error", {})
                    self.update_operation(op_id, "Failed", error=str(err_detail))
                    raise FabricError("operation_failed", f"Fabric operation {op_id} failed: {err_detail}",
                                      "check item definitions and model bindings", detail=data)
            wait = float(headers.get("retry-after", interval))
            time.sleep(wait)
        raise FabricError("operation_timeout", f"timed out waiting for operation {op_id}",
                          f"run `ad-pbi ops {op_id}` to check or resume")

    # ---------- Item Definitions (Get) ----------

    def get_report_definition(self, workspace_id: str, report_id: str) -> dict:
        """Fetch PBIR report definition via POST getDefinition?format=PBIR."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        rep_id, _ = self.resolve_item(ws_id, report_id, kind="report")
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/reports/{rep_id}/getDefinition?format=PBIR"
        _, data, headers, _ = self.rest_call("POST", url)

        # Check for PBIR-Legacy format refusal
        if isinstance(data, dict):
            fmt = data.get("format", "")
            if fmt == "PBIR-Legacy":
                raise FabricError("pbir_legacy_format", "report definition is in PBIR-Legacy format",
                                  "convert report to PBIR in Power BI Desktop (File -> Options -> Preview features -> Store reports using enhanced metadata format (PBIR))")

        op_id = headers.get("x-ms-operation-id")
        if not op_id and isinstance(data, dict) and data.get("status") in ("Running", "NotStarted"):
            op_id = data.get("id")

        if op_id:
            self.record_operation(op_id, "get_report_definition", ws_id, target_id=rep_id)
            result = self.poll_operation(op_id)
            data = result

        # Check definition payload for legacy refusal
        definition = data.get("definition", data) if isinstance(data, dict) else {}
        parts = definition.get("parts", [])
        for part in parts:
            if part.get("path") == "report.json" and not any(p.get("path", "").startswith("definition/") for p in parts):
                raise FabricError("pbir_legacy_format", "report definition is in PBIR-Legacy format",
                                  "convert report to PBIR in Power BI Desktop (File -> Options -> Preview features -> Store reports using enhanced metadata format (PBIR))")

        return definition

    def get_model_definition(self, workspace_id: str, model_id: str) -> dict:
        """Fetch TMDL semantic model definition via POST getDefinition?format=TMDL."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        m_id, _ = self.resolve_item(ws_id, model_id, kind="model")
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/semanticModels/{m_id}/getDefinition?format=TMDL"
        _, data, headers, _ = self.rest_call("POST", url)

        op_id = headers.get("x-ms-operation-id")
        if not op_id and isinstance(data, dict) and data.get("status") in ("Running", "NotStarted"):
            op_id = data.get("id")

        if op_id:
            self.record_operation(op_id, "get_model_definition", ws_id, target_id=m_id)
            result = self.poll_operation(op_id)
            data = result

        definition = data.get("definition", data) if isinstance(data, dict) else {}
        return definition

    # ---------- Publishing (Create & Update) ----------

    def create_report(self, workspace_id: str, name: str, definition_parts: list[dict]) -> tuple[str, str]:
        """Create a new report in workspace. Returns (report_id, operation_id)."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/reports"
        body = {
            "displayName": name,
            "definition": {
                "parts": definition_parts
            }
        }
        _, data, headers, _ = self.rest_call("POST", url, body=body)
        op_id = headers.get("x-ms-operation-id") or (data.get("id") if isinstance(data, dict) else "") or f"op-{int(time.time()*1000)}"
        self.record_operation(op_id, "create_report", ws_id, target_name=name)

        result = self.poll_operation(op_id)
        report_id = ""
        if isinstance(result, dict):
            report_id = result.get("id", "")
        if not report_id:
            # Look up newly created report by name
            rep_id, _ = self.resolve_item(ws_id, name, kind="report")
            report_id = rep_id
        return report_id, op_id

    def update_report_definition(self, workspace_id: str, report_id: str, definition_parts: list[dict]) -> str:
        """Update definition of an existing report. Returns operation_id."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        rep_id, rep_name = self.resolve_item(ws_id, report_id, kind="report")
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/reports/{rep_id}/updateDefinition"
        body = {
            "definition": {
                "parts": definition_parts
            }
        }
        _, data, headers, _ = self.rest_call("POST", url, body=body)
        op_id = headers.get("x-ms-operation-id") or (data.get("id") if isinstance(data, dict) else "") or f"op-{int(time.time()*1000)}"
        self.record_operation(op_id, "update_report_definition", ws_id, target_id=rep_id, target_name=rep_name)

        self.poll_operation(op_id)
        return op_id

    def create_model(self, workspace_id: str, name: str, definition_parts: list[dict]) -> tuple[str, str]:
        """Create a new TMDL semantic model in workspace. Returns (model_id, operation_id)."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/semanticModels"
        body = {
            "displayName": name,
            "definition": {
                "parts": definition_parts
            }
        }
        _, data, headers, _ = self.rest_call("POST", url, body=body)
        op_id = headers.get("x-ms-operation-id") or (data.get("id") if isinstance(data, dict) else "") or f"op-{int(time.time()*1000)}"
        self.record_operation(op_id, "create_model", ws_id, target_name=name)

        result = self.poll_operation(op_id)
        model_id = ""
        if isinstance(result, dict):
            model_id = result.get("id", "")
        if not model_id:
            m_id, _ = self.resolve_item(ws_id, name, kind="model")
            model_id = m_id
        return model_id, op_id

    def update_model_definition(self, workspace_id: str, model_id: str, definition_parts: list[dict]) -> str:
        """Update definition of an existing TMDL semantic model. Returns operation_id."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        m_id, m_name = self.resolve_item(ws_id, model_id, kind="model")
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/semanticModels/{m_id}/updateDefinition"
        body = {
            "definition": {
                "parts": definition_parts
            }
        }
        _, data, headers, _ = self.rest_call("POST", url, body=body)
        op_id = headers.get("x-ms-operation-id") or (data.get("id") if isinstance(data, dict) else "") or f"op-{int(time.time()*1000)}"
        self.record_operation(op_id, "update_model_definition", ws_id, target_id=m_id, target_name=m_name)

        self.poll_operation(op_id)
        return op_id

    # ---------- Delete ----------

    def delete_item(self, workspace_id: str, item_id: str, kind: str) -> None:
        """Delete a report or semantic model."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        it_id, _ = self.resolve_item(ws_id, item_id, kind=kind)
        endpoint = "reports" if kind.lower() in ("report", "reports") else "semanticModels"
        url = f"{FABRIC_API_BASE}/workspaces/{ws_id}/{endpoint}/{it_id}"
        self.rest_call("DELETE", url)

    # ---------- Stretch: Export PNG ----------

    def export_report_png(self, workspace_id: str, report_id: str, page_name: str, out_path: str) -> str:
        """Export a report page as PNG using Power BI REST API."""
        ws_id, _ = self.resolve_workspace(workspace_id)
        rep_id, _ = self.resolve_item(ws_id, report_id, kind="report")
        url = f"{POWERBI_API_BASE}/groups/{ws_id}/reports/{rep_id}/ExportTo"
        body = {
            "format": "PNG",
            "powerBIReportConfiguration": {
                "pages": [{"pageName": page_name}]
            }
        }
        _, data, _, _ = self.rest_call("POST", url, body=body, resource=POWERBI_RESOURCE)
        export_id = data.get("id") if isinstance(data, dict) else ""
        if not export_id:
            raise FabricError("export_failed", "no export ID returned from ExportTo API", detail=data)

        # Poll export status
        poll_url = f"{POWERBI_API_BASE}/groups/{ws_id}/reports/{rep_id}/exports/{export_id}"
        for _ in range(60):
            time.sleep(2.0)
            _, status_data, _, _ = self.rest_call("GET", poll_url, resource=POWERBI_RESOURCE)
            if isinstance(status_data, dict):
                st = status_data.get("status")
                if st == "Succeeded":
                    break
                if st == "Failed":
                    raise FabricError("export_failed", f"export {export_id} failed", detail=status_data)

        # Download file
        file_url = f"{POWERBI_API_BASE}/groups/{ws_id}/reports/{rep_id}/exports/{export_id}/file"
        _, _, _, raw_out = self.rest_call("GET", file_url, resource=POWERBI_RESOURCE)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as f:
            if isinstance(raw_out, str):
                f.write(raw_out.encode("utf-8", errors="replace"))
            else:
                f.write(bytes(raw_out))
        return out_path
