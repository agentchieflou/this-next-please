"""Verify deployed semantic model measures over XMLA and compare parity with Desktop."""
from __future__ import annotations
import os
import urllib.parse
from typing import Any, Callable

from .. import config as C
from ..pbip import dax as DAX
from ..pbip import dmv as DMV
from ..pbip import pbir as P
from .client import FabricClient, FabricError
from .refresh import get_refresh_partitions


def get_report_measures(report_dir: str) -> list[str]:
    """Find all unique measures referenced in a PBIR report's visuals."""
    rep = P.load_report(report_dir)
    measures = set()
    for v in rep.all_visuals():
        for f in v.fields:
            if f.kind == "measure":
                measures.add(f.prop)
    return sorted(measures)


def query_measures_dax(server: str, database: str, measures: list[str], runner: Callable | None = None) -> dict[str, Any]:
    """Query a list of measures against an SSAS/XMLA server. Returns {measure_name: value}."""
    cfg = C.load()
    dscmd = C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe") or "dscmd.exe"
    results: dict[str, Any] = {}
    for m in measures:
        # Build scalar evaluate query
        q = f'EVALUATE ROW("Value", [{m}])'
        try:
            tbl = DAX.run_dax(q, server, dscmd, database=database, run=runner)
            if tbl.rows:
                results[m] = tbl.rows[0][0]
            else:
                results[m] = None
        except Exception as e:
            results[m] = f"ERROR: {e}"
    return results


def verify_service_parity(
    pbip_dir: str,
    workspace: str,
    model: str,
    pid: int | None = None,
    runner: Callable | None = None,
) -> dict[str, Any]:
    """Execute report measures on service via XMLA and optionally against Desktop, comparing parity."""
    # 1. Locate report directory
    report_dir = pbip_dir
    if os.path.isfile(pbip_dir) and pbip_dir.endswith(".pbip"):
        import glob
        cands = glob.glob(os.path.join(os.path.dirname(pbip_dir), "*.Report"))
        if cands:
            report_dir = cands[0]
    elif os.path.isdir(pbip_dir) and not pbip_dir.endswith(".Report"):
        import glob
        cands = glob.glob(os.path.join(pbip_dir, "*.Report"))
        if cands:
            report_dir = cands[0]

    measures = get_report_measures(report_dir)
    if not measures:
        return {
            "ok": True,
            "parity": "ok",
            "measures_count": 0,
            "message": "no measures found in report visuals",
            "results": {},
        }

    # 2. Service XMLA query
    ws_quoted = urllib.parse.quote(workspace, safe="")
    xmla_url = f"powerbi://api.powerbi.com/v1.0/myorg/{ws_quoted}"
    service_vals = query_measures_dax(xmla_url, model, measures, runner=runner)

    # 3. Desktop query if pid or running desktop instance
    desktop_vals: dict[str, Any] | None = None
    target_pid = pid
    if not target_pid:
        from ..pbip import desktop as DT
        insts = DT.discover()
        if insts:
            target_pid = insts[0].pid

    if target_pid:
        from ..pbip import desktop as DT
        insts = DT.discover()
        inst = next((i for i in insts if i.pid == target_pid), None)
        if inst and inst.port:
            local_server = f"localhost:{inst.port}"
            desktop_vals = query_measures_dax(local_server, model, measures, runner=runner)

    # 4. Compare results
    mismatches = []
    comparison_rows = []
    parity = "ok"

    for m in measures:
        s_val = service_vals.get(m)
        d_val = desktop_vals.get(m) if desktop_vals else None

        if desktop_vals:
            # Check matching
            match = (s_val == d_val) and not (str(s_val).startswith("ERROR:") or str(d_val).startswith("ERROR:"))
            if not match:
                parity = "mismatch"
                mismatches.append({"measure": m, "service": s_val, "desktop": d_val})
            comparison_rows.append([m, s_val, d_val, "ok" if match else "mismatch"])
        else:
            if str(s_val).startswith("ERROR:"):
                parity = "error"
            comparison_rows.append([m, s_val, "-", "error" if str(s_val).startswith("ERROR:") else "service_only"])

    hint = ""
    if parity == "mismatch":
        hint = ("Common causes for Desktop vs Service mismatch: "
                "(1) service refresh is older than Desktop data; "
                "(2) Row-Level Security (RLS) active on service; "
                "(3) query parameters differ between environments.")

    return {
        "ok": (parity == "ok"),
        "parity": parity,
        "measures_count": len(measures),
        "tested_desktop": bool(desktop_vals is not None),
        "service_values": service_vals,
        "desktop_values": desktop_vals,
        "mismatches": mismatches,
        "comparison_rows": comparison_rows,
        "hint": hint,
    }
