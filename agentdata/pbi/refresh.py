"""Semantic model refresh execution, history polling, failure parsing, and partition queries."""
from __future__ import annotations
import json
import os
import re
import sys
import time
from typing import Any, Callable

from .. import config as C
from .. import proc
from . import auth as AUTH
from .client import FabricClient
from .errors import FabricError

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
    # The az token rides in the connection string (`auth.xmla_source`): no cached sign-in needed.
    source = AUTH.xmla_source(AUTH.xmla_url(workspace), runner=r)

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
        cmd = [te2, source, model, "-S", csx, "-E", "-W"]
        rc, out, err, _ = r(cmd, timeout=120)
        if rc != 0:
            raise FabricError("refresh_submit_failed",
                              f"TE2 refresh submission failed (exit {rc}): {AUTH.redact((err or out).strip()[-200:])}",
                              hint="check XMLA read/write permission and the workspace name; `ad-pbi auth --probe` "
                                   "proves the sign-in on its own")
    finally:
        if env_backup is not None:
            os.environ["TE_REFRESH_SCOPE"] = env_backup
        else:
            os.environ.pop("TE_REFRESH_SCOPE", None)


def _row_key(row: dict | None) -> str:
    """A refresh history row's identity: the request id when the service gives one, else its id."""
    if not isinstance(row, dict):
        return ""
    return str(row.get("requestId") or row.get("id") or "")


def is_new_row(row: dict, baseline: dict | None) -> bool:
    """Is this history row a refresh that started after `baseline`, the top row before submission?

    The history's top row is whatever refresh ran last. Read without a baseline, a submission that
    never reached the service (a sign-in that failed while the wrapper still exited 0) left
    yesterday's `Completed` on top, and the poll reported it as this refresh's success (friction
    scan 1.2). A row counts as new when its identity differs from the baseline's, or -- when the
    service reuses ids -- when it started later.
    """
    if not baseline:
        return True
    if _row_key(row) and _row_key(row) != _row_key(baseline):
        return True
    start, before = str(row.get("startTime") or ""), str(baseline.get("startTime") or "")
    return bool(start and before and start > before)


def poll_refresh(
    workspace_id: str,
    model_id: str,
    client: FabricClient,
    wait_timeout: int = 1800,
    interval: float = 3.0,
    baseline: dict | None = None,
) -> dict[str, Any]:
    """Poll refresh history until the refresh submitted after `baseline` is Completed or Failed.

    A refresh that never shows up is `Indeterminate`, never `Completed`: the caller must not call
    it done.
    """
    t0 = time.time()
    last_status = "Unknown"
    observed = False

    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/semanticModels/{model_id}/refreshes"
    fallback_url = f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/datasets/{model_id}/refreshes?$top=1"

    while (time.time() - t0) < wait_timeout:
        elapsed = time.time() - t0
        rc, data, _, _ = client.rest_call("GET", url, check=False)
        if rc != 0:
            rc, data, _, _ = client.rest_call("GET", fallback_url, resource="https://analysis.windows.net/powerbi/api", check=False)

        refreshes = []
        if isinstance(data, dict):
            refreshes = [r for r in data.get("value", []) if isinstance(r, dict) and is_new_row(r, baseline)]

        if refreshes:
            observed = True
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
                    "request_id": _row_key(latest),
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

            if st in ("Cancelled", "Disabled"):
                raise FabricError("refresh_failed", f"refresh ended {st.lower()} on the service",
                                  hint="the service stopped it; read `ad-pbi refresh --history` before submitting again")

        time.sleep(interval)

    if not observed:
        raise FabricError(
            "refresh_not_observed",
            f"no refresh newer than the one before submission appeared within {wait_timeout}s",
            hint="status Indeterminate, not Completed: the submission may never have reached the service. "
                 "Run `ad-pbi refresh --history` and `ad-pbi auth --probe` before submitting again",
            detail={"status": "Indeterminate", "baseline": _row_key(baseline)})
    raise FabricError("refresh_timeout", f"timed out waiting for refresh after {wait_timeout}s (last status: {last_status})",
                      detail={"status": "Indeterminate", "last_status": last_status})


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
    xmla_url = AUTH.xmla_url(workspace)

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
    except AUTH.AuthError:
        raise                       # a sign-in problem is an answer, not an empty partition list
    except Exception:
        # Fallback empty list if DMV not queryable or running offline test
        return []
