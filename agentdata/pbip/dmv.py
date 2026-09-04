"""Analysis Services Dynamic Management View (DMV) queries and live model diagnostics.

Executes DMVs over localhost:<port> via dscmd or Tabular Editor 2, providing
dependency graphs (DISCOVER_CALC_DEPENDENCY), storage statistics (DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS),
and live model comparison with TMDL/PBIR files.
"""
from __future__ import annotations
import csv
import os
import tempfile
import time
from typing import Callable
from . import dax as D
from . import desktop as DT
from . import screenshot as SC
from . import trace as TR
from .. import config as C
from ..model import AgentTable

Runner = Callable[[list[str], int], tuple[int, str, str]]

DMV_SHORTCUTS = {
    "deps": "SELECT [OBJECT_TYPE], [OBJECT_NAME], [REFERENCED_OBJECT_TYPE], [REFERENCED_OBJECT_NAME] FROM $SYSTEM.DISCOVER_CALC_DEPENDENCY",
    "segments": "SELECT [TABLE_ID], [COLUMN_ID], [ROWS_COUNT], [USED_SIZE] FROM $SYSTEM.DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS",
    "sessions": "SELECT [SESSION_ID], [SESSION_USER_NAME], [SESSION_CURRENT_DATABASE], [SESSION_START_TIME] FROM $SYSTEM.DISCOVER_SESSIONS",
    "schema": "SELECT [CATALOG_NAME], [DESCRIPTION] FROM $SYSTEM.DBSCHEMA_CATALOGS",
}


def run_dmv(server: str, query_or_shortcut: str, dscmd_exe: str | None = None,
            database: str | None = None, te2_exe: str | None = None,
            run: Runner | None = None) -> AgentTable:
    """Run an Analysis Services DMV query via dscmd or TE2 fallback."""
    shortcut = query_or_shortcut.strip().lower()
    sql = DMV_SHORTCUTS.get(shortcut, query_or_shortcut)
    name = f"dmv_{shortcut}" if shortcut in DMV_SHORTCUTS else "dmv"

    cfg = C.load()
    dscmd = dscmd_exe or C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe")

    # Try dscmd first
    if dscmd and os.path.exists(dscmd):
        try:
            return D.run_dax(sql, server, dscmd, database=database, run=run, name=name)
        except Exception:
            pass

    # TE2 fallback via C# ExecuteReader
    te2 = te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe")
    if te2 and os.path.exists(te2):
        return run_dmv_te2(server, sql, te2, database=database, run=run, name=name)

    raise RuntimeError(f"Neither dscmd nor Tabular Editor 2 available to run DMV on {server}")


def run_dmv_te2(server: str, sql: str, te2_exe: str, database: str | None = None,
                run: Runner | None = None, name: str = "dmv") -> AgentTable:
    """Execute DMV query using Tabular Editor 2 script."""
    run = run or DT.default_run
    with tempfile.TemporaryDirectory() as td:
        out_csv = os.path.join(td, "dmv.csv").replace("\\", "/")
        csx = os.path.join(td, "dmv.csx")
        escaped_sql = sql.replace('"', '""')
        script = f'''
using System;
using System.IO;
using System.Data;

var sql = @"{escaped_sql}";
var outFile = @"{out_csv}";

try {{
    using (var reader = Model.Database.ExecuteReader(sql))
    {{
        using (var writer = new StreamWriter(outFile, false, System.Text.Encoding.UTF8))
        {{
            int cols = reader.FieldCount;
            for (int i = 0; i < cols; i++)
            {{
                if (i > 0) writer.Write(",");
                writer.Write("\"" + reader.GetName(i).Replace("\"", "\"\"") + "\"");
            }}
            writer.WriteLine();

            while (reader.Read())
            {{
                for (int i = 0; i < cols; i++)
                {{
                    if (i > 0) writer.Write(",");
                    var val = reader.IsDBNull(i) ? "" : reader.GetValue(i).ToString();
                    writer.Write("\"" + val.Replace("\"", "\"\"") + "\"");
                }}
                writer.WriteLine();
            }}
        }}
    }}
}}
catch (Exception ex) {{
    File.WriteAllText(outFile + ".err", ex.ToString());
}}
'''
        with open(csx, "w", encoding="utf-8") as f:
            f.write(script)

        db_arg = database or ""
        cmd = [te2_exe, server, db_arg, "-S", csx]
        rc, out, err = run(cmd, 60)

        if not os.path.exists(out_csv):
            err_file = out_csv + ".err"
            detail = ""
            if os.path.exists(err_file):
                with open(err_file, encoding="utf-8") as ef:
                    detail = ef.read()
            raise RuntimeError(f"TE2 DMV query failed: {detail or err or out}")

        with open(out_csv, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))

    cols = [D.clean_header(h) for h in (rows[0] if rows else [])]
    return AgentTable(name, cols, [[D._coerce(v) for v in r] for r in rows[1:]], source=f"te2 dmv {server}")


def normalize_segments(table: AgentTable) -> AgentTable:
    """Format DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS into [table, column, rows, bytes, pct_of_model]."""
    total_bytes = 0
    raw_rows = []
    # Find column indices
    col_idx = {c.upper(): i for i, c in enumerate(table.columns)}
    t_idx = col_idx.get("TABLE_ID") or 0
    c_idx = col_idx.get("COLUMN_ID") or 1
    r_idx = col_idx.get("ROWS_COUNT") or 2
    s_idx = col_idx.get("USED_SIZE") or 3

    for r in table.rows:
        t_name = str(r[t_idx]) if t_idx < len(r) else ""
        c_name = str(r[c_idx]) if c_idx < len(r) else ""
        rows_cnt = int(r[r_idx]) if r_idx < len(r) and str(r[r_idx]).isdigit() else 0
        used_sz = int(r[s_idx]) if s_idx < len(r) and str(r[s_idx]).isdigit() else 0
        total_bytes += used_sz
        raw_rows.append([t_name, c_name, rows_cnt, used_sz])

    formatted = []
    for t_name, c_name, rows_cnt, used_sz in raw_rows:
        pct = round((used_sz / total_bytes * 100.0), 2) if total_bytes > 0 else 0.0
        formatted.append([t_name, c_name, rows_cnt, used_sz, pct])

    formatted.sort(key=lambda x: x[3], reverse=True)
    return AgentTable("segments", ["table", "column", "rows", "bytes", "pct_of_model"], formatted, source=table.source)


def refs_live(pbip_dir: str, server: str, database: str | None = None,
              dscmd: str | None = None, te2_exe: str | None = None,
              run: Runner | None = None) -> AgentTable:
    """Compare DISCOVER_CALC_DEPENDENCY live graph with PBIP TMDL/PBIR files."""
    dmv_table = run_dmv(server, "deps", dscmd_exe=dscmd, database=database, te2_exe=te2_exe, run=run)

    live_deps = set()
    for r in dmv_table.rows:
        if len(r) >= 4:
            obj = str(r[1])
            ref = str(r[3])
            kind = str(r[0]).lower()
            live_deps.add((obj, ref, kind))

    # Read file graph
    from .normalize import load_all
    model, report, _ = load_all(pbip_dir, legacy_ok=True)
    file_deps = set()
    if model:
        for t in model.tables:
            for m in t.measures:
                for dep in getattr(m, "dependencies", []):
                    file_deps.add((m.name, dep, "measure"))

    # Reconcile live vs file
    all_pairs = sorted(live_deps | file_deps)
    rows = []
    for obj, ref, kind in all_pairs:
        in_live = (obj, ref, kind) in live_deps
        in_file = (obj, ref, kind) in file_deps
        if in_live and in_file:
            status = "synced"
        elif in_live:
            status = "live-only"
        else:
            status = "file-only"
        rows.append([obj, ref, kind, status])

    cols = ["object", "refers_to", "kind", "status"]
    return AgentTable("refs_live", cols, rows, source=f"refs --live @ {server}")


def page_cost(pid: int, page: str, pbip_dir: str | None = None,
              seconds: int = 15, te2_exe: str | None = None,
              run: Runner | None = None) -> AgentTable:
    """Measure total and per-visual query costs for a page."""
    run = run or DT.default_run
    # Resolve instance and server
    insts = DT.status(pid=pid, run=run)
    inst = insts[0] if insts else None
    server = inst.server if inst else f"localhost:{inst.port}" if inst and inst.port else "localhost:0"

    # Start trace
    listener, out_file, meta = TR.start_trace(server, pid=pid, seconds=seconds, te2_exe=te2_exe, database=inst.database if hasattr(inst, "database") else None, run=run)

    try:
        # Navigate to page to trigger queries
        SC.navigate_page(pid, page, run=run)
        time.sleep(min(seconds, 3))
    finally:
        TR.stop_trace(listener)

    # Report trace
    rep = TR.report_trace(out_file, report_dir=pbip_dir or (inst.file if inst else None))
    # Aggregate per-visual
    vis_costs: dict[str, list[int]] = {}
    for r in rep.rows:
        vname = str(r[1])
        cnt = int(r[2])
        tot_ms = int(r[3])
        if vname not in vis_costs:
            vis_costs[vname] = [0, 0]
        vis_costs[vname][0] += cnt
        vis_costs[vname][1] += tot_ms

    page_rows = []
    total_page_ms = 0
    for vname, (cnt, ms) in sorted(vis_costs.items(), key=lambda x: x[1][1], reverse=True):
        page_rows.append([vname, cnt, ms])
        total_page_ms += ms

    cols = ["visual", "query_count", "total_ms"]
    table = AgentTable("page_cost", cols, page_rows, source=f"page-cost {page} (pid {pid})")
    table.raw = {"page": page, "total_page_ms": total_page_ms, "visuals": len(page_rows)}
    return table
