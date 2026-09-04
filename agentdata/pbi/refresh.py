"""Semantic model refresh execution, history polling, failure parsing, and partition queries."""
from __future__ import annotations
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Any, Callable

from .. import config as C
from .. import proc
from .client import FabricClient, FabricError

REFRESH_CSX_PATH = os.path.join(os.path.dirname(__file__), "scripts", "refresh.csx")


def parse_service_exception(exc_json_str: str | dict) -> dict[str, str]:
    """Parse serviceExceptionJson from Power BI refresh failure into structured fields."""
    data = exc_json_str if isinstance(exc_json_str, dict) else {}
    if isinstance(exc_json_str, str):
        try:
            data = json.loads(exc_json_str)
        except Exception:
            data = {"message": exc_json_str}

    error_code = data.get("errorCode", data.get("error", {}).get("code", "RefreshError"))
    message = data.get("errorDescription", data.get("message", data.get("error", {}).get("message", "Model refresh failed")))
    
    # Try to extract table and partition names
    table = ""
    partition = ""
    hint = message

    # Often in format: "... Table: Customers, Partition: Customers-2024 ... [DataSource.Error] ..."
    m_tbl = re.search(r"(?:Table|table)[:\s]+'?([a-zA-Z0-9_\s]+)'?", message)
    if m_tbl:
        table = m_tbl.group(1).strip()
    m_part = re.search(r"(?:Partition|partition)[:\s]+'?([a-zA-Z0-9_\-\s]+)'?", message)
    if m_part:
        partition = m_part.group(1).strip()

    # Extract source error for hint
    m_src = re.search(r"(\[DataSource\.Error\].*?)(?:Table:|$)", message)
    if m_src:
        hint = m_src.group(1).strip()
    elif "Detail:" in message:
        hint = message.split("Detail:", 1)[1].strip()

    return {
        "error_code": str(error_code),
        "table": table,
        "partition": partition,
        "message": message,
        "hint": hint,
    }


def submit_refresh(
    workspace: str,
    model: str,
    scope: str = "full",
    runner: Callable | None = None,
    te2_exe: str | None = None,
) -> None:
    """Submit refresh to live model via TE2 and refresh.csx."""
    r = runner or proc.run
    te2 = te2_exe or C.get(C.load(), "powerbi.tools.te2_exe") or proc.which("TabularEditor.exe") or "TabularEditor.exe"
    ws_quoted = urllib.parse.quote(workspace, safe="")
    xmla_url = f"powerbi://api.powerbi.com/v1.0/myorg/{ws_quoted}"

    csx = REFRESH_CSX_PATH
    if not os.path.exists(csx):
        # Fallback to skills path
        alt_csx = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                               "skills", "pbi-refresh-xmla", "scripts", "refresh.csx")
        if os.path.exists(alt_csx):
            csx = alt_csx

    env_backup = os.environ.get("TE_REFRESH_SCOPE")
    os.environ["TE_REFRESH_SCOPE"] = scope
    try:
        cmd = [te2, xmla_url, model, "-S", csx, "-E", "-W"]
        rc, out, err, _ = r(cmd, timeout=120)
        if rc != 0:
            raise FabricError("refresh_submit_failed", f"TE2 refresh submission failed (exit {rc}): {(err or out).strip()[-200:]}",
                              hint="check XMLA read/write permission, workspace name, or az login")
    finally:
        if env_backup is not None:
            os.environ["TE_REFRESH_SCOPE"] = env_backup
        else:
            os.environ.pop("TE_REFRESH_SCOPE", None)


def poll_refresh(
    workspace_id: str,
    model_id: str,
    client: FabricClient,
    wait_timeout: int = 1800,
    interval: float = 3.0,
) -> dict[str, Any]:
    """Poll refresh history until Completed or Failed."""
    t0 = time.time()
    last_status = "Unknown"

    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/semanticModels/{model_id}/refreshes"
    fallback_url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{model_id}/refreshes?$top=1"

    while (time.time() - t0) < wait_timeout:
        elapsed = time.time() - t0
        rc, data, _, _ = client.rest_call("GET", url, check=False)
        if rc != 0:
            rc, data, _, _ = client.rest_call("GET", fallback_url, resource="https://analysis.windows.net/powerbi/api", check=False)

        refreshes = []
        if isinstance(data, dict):
            refreshes = data.get("value", [])

        if refreshes:
            latest = refreshes[0]
            st = latest.get("status", "Unknown")
            last_status = st
            print(f"[refresh] status: {st}, elapsed: {elapsed:.1f}s", file=sys.stderr)

            if st in ("Completed", "Succeeded"):
                return {
                    "ok": True,
                    "status": "Completed",
                    "duration_s": round(elapsed, 1),
                    "refresh_type": latest.get("refreshType", "Full"),
                    "start_time": latest.get("startTime", ""),
                    "end_time": latest.get("endTime", ""),
                }
            if st == "Failed":
                exc_raw = latest.get("serviceExceptionJson") or latest.get("error", {})
                parsed = parse_service_exception(exc_raw)
                raise FabricError(
                    "refresh_failed",
                    f"refresh failed: {parsed['message']}",
                    hint=parsed["hint"],
                    detail=parsed,
                )

        time.sleep(interval)

    raise FabricError("refresh_timeout", f"timed out waiting for refresh after {wait_timeout}s (last status: {last_status})")


def get_refresh_history(
    workspace_id: str,
    model_id: str,
    client: FabricClient,
    top: int = 5,
) -> list[dict[str, Any]]:
    """Fetch recent refresh history rows."""
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/semanticModels/{model_id}/refreshes"
    fallback_url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{model_id}/refreshes?$top={top}"

    rc, data, _, _ = client.rest_call("GET", url, check=False)
    if rc != 0:
        rc, data, _, _ = client.rest_call("GET", fallback_url, resource="https://analysis.windows.net/powerbi/api", check=False)

    if isinstance(data, dict):
        return list(data.get("value", []))[:top]
    return []


def get_refresh_partitions(
    workspace: str,
    model: str,
    runner: Callable | None = None,
) -> list[dict[str, Any]]:
    """Query partition names, row counts, and last processed times over XMLA via DMV."""
    ws_quoted = urllib.parse.quote(workspace, safe="")
    xmla_url = f"powerbi://api.powerbi.com/v1.0/myorg/{ws_quoted}"

    from ..pbip import dmv as D
    query = "SELECT [TABLE_ID], [PARTITION_NAME], [ROWS_COUNT], [MODIFY_TIME] FROM $SYSTEM.DISCOVER_STORAGE_TABLE_PARTITIONS"
    try:
        table = D.run_dmv(xmla_url, query, database=model, run=runner)
        rows = []
        for r in table.rows:
            rows.append({
                "table": str(r[0]),
                "partition": str(r[1]),
                "rows_count": int(r[2]) if str(r[2]).isdigit() else 0,
                "last_processed": str(r[3]),
            })
        return rows
    except Exception:
        # Fallback empty list if DMV not queryable or running offline test
        return []
