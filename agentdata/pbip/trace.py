"""Power BI live Analysis Services tracing via Tabular Editor 2 and named pipe IPC.

Captures QueryBegin, QueryEnd, DirectQueryEnd, VertiPaqSEQueryEnd trace events
over Analysis Services port, correlates them to PBIR visual projections, and reports
execution latency and engine modes.
"""
from __future__ import annotations
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Callable
from . import desktop as DT
from ..model import AgentTable
from .. import textio

Runner = Callable[[list[str], int], tuple[int, str, str]]
SCRIPT_CSX = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                          "skills", "pbi-observe", "scripts", "trace.csx")


class TraceListener:
    """Named pipe or socket listener for TE2 trace stream."""

    def __init__(self, address: str | tuple[str, int], family: str = "AF_PIPE"):
        self.address = address
        self.family = family
        self.listener: Listener | None = None
        self.events: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self.out_file: str | None = None

    def start(self, out_file: str | None = None) -> None:
        self.out_file = out_file
        if out_file:
            os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)

        try:
            self.listener = Listener(self.address, family=self.family)
        except Exception:
            # Fallback to AF_INET if AF_PIPE or address fails
            if self.family == "AF_PIPE":
                self.address = ("localhost", 0)
                self.family = "AF_INET"
                self.listener = Listener(self.address, family=self.family)

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self) -> None:
        if not self.listener:
            return
        while self._running:
            try:
                conn = self.listener.accept()
            except Exception:
                break
            try:
                # Read lines/messages from connection
                while self._running:
                    try:
                        msg = conn.recv()
                        if isinstance(msg, bytes):
                            line = msg.decode("utf-8")
                        else:
                            line = str(msg)
                        for part in line.splitlines():
                            if not part.strip():
                                continue
                            try:
                                data = json.loads(part)
                                self.events.append(data)
                                if self.out_file:
                                    with open(self.out_file, "a", encoding="utf-8") as f:
                                        f.write(part + "\n")
                            except Exception:
                                pass
                    except EOFError:
                        break
                    except Exception:
                        break
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def stop(self) -> None:
        self._running = False
        if self.listener:
            try:
                self.listener.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


def stop_trace(listener: TraceListener | None) -> None:
    """Stop active trace listener."""
    if listener:
        listener.stop()


def default_trace_pipe(pid: int | None = None) -> tuple[str | tuple[str, int], str]:
    """Return default pipe address and family for platform."""
    target_pid = pid or os.getpid()
    if sys.platform == "win32":
        return f"\\\\.\\pipe\\agentdata-trace-{target_pid}", "AF_PIPE"
    # Linux / macOS fallback
    return ("localhost", 0), "AF_INET"


def start_trace(server: str, pid: int | None = None, seconds: int = 60,
                out_path: str | None = None, te2_exe: str | None = None,
                database: str | None = None, run: Runner | None = None) -> tuple[TraceListener, str, dict]:
    """Start named-pipe listener and launch TE2 with trace.csx."""
    addr, family = default_trace_pipe(pid)
    listener = TraceListener(addr, family=family)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_file = out_path or os.path.join(".agent", "out", f"trace-{ts}.jsonl")
    out_file = textio.norm_path(out_file)

    listener.start(out_file=out_file)

    meta = {
        "server": server,
        "pid": pid,
        "pipe": str(addr),
        "family": family,
        "out_file": out_file,
        "seconds": seconds,
    }

    if te2_exe and os.path.exists(te2_exe):
        env = dict(os.environ)
        env["TE_TRACE_SECONDS"] = str(seconds)
        env["TE_TRACE_OUT"] = out_file
        env["TE_TRACE_PIPE"] = str(addr) if family == "AF_PIPE" else ""

        # Launch TE2 in background
        db_arg = database or ""
        cmd = [te2_exe, server, db_arg, "-S", SCRIPT_CSX]
        try:
            p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            meta["te2_pid"] = p.pid
        except Exception as e:
            meta["te2_error"] = str(e)

    return listener, out_file, meta


def report_trace(jsonl_path: str, report_dir: str | None = None) -> AgentTable:
    """Aggregate trace events by query text hash and correlate to PBIR visuals."""
    if not os.path.exists(jsonl_path):
        return AgentTable("trace_report", ["hash", "visual", "count", "total_ms", "median_ms", "mode", "query"], [])

    events = []
    with open(jsonl_path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass

    # Extract visuals from PBIR if report_dir available
    visual_map = {}
    if report_dir and os.path.exists(report_dir):
        try:
            from .screenshot import find_visual_in_pbir
            # Scan all pages
            p_dir = Path(report_dir)
            pages_dir = p_dir / "definition" / "pages"
            if not pages_dir.exists():
                for rep in p_dir.glob("*.Report/definition/pages"):
                    pages_dir = rep
                    break

            if pages_dir.exists():
                for vj in pages_dir.rglob("visual.json"):
                    try:
                        with open(vj, encoding="utf-8-sig") as vf:
                            vdata = json.load(vf)
                        vid = vdata.get("name") or vj.parent.name
                        vis = vdata.get("visual") or {}
                        title = None
                        try:
                            for t in (vis.get("visualContainerObjects") or {}).get("title") or []:
                                lit = (((t.get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal") or {}
                                if lit.get("Value"):
                                    title = str(lit["Value"]).strip("'")
                        except Exception:
                            pass
                        # Store queryRef identifiers
                        refs = set()
                        qs = (vis.get("query") or {}).get("queryState") or {}
                        for container in qs.values():
                            for proj in (container.get("projections") or []):
                                qref = proj.get("queryRef")
                                if qref:
                                    refs.add(qref.lower())
                        visual_map[title or vid] = refs
                    except Exception:
                        pass
        except Exception:
            pass

    # Group QueryEnd and related events
    grouped: dict[str, dict] = {}

    for ev in events:
        ev_name = ev.get("event")
        text = ev.get("text") or ""
        dur = ev.get("duration_ms") or 0

        if ev_name in ("QueryEnd", "DirectQueryEnd", "VertiPaqSEQueryEnd"):
            if not text:
                continue
            q_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            if q_hash not in grouped:
                # Correlate visual
                matched_vis = "unmatched"
                t_lower = text.lower()
                for vname, refs in visual_map.items():
                    if any(r in t_lower or (len(r.split(".")[-1]) > 3 and r.split(".")[-1] in t_lower) for r in refs if len(r) > 3):
                        matched_vis = vname
                        break
                    if vname.lower() in t_lower:
                        matched_vis = vname
                        break

                grouped[q_hash] = {
                    "hash": q_hash,
                    "visual": matched_vis,
                    "durations": [],
                    "modes": set(),
                    "query": text[:120].replace("\n", " ").strip(),
                }

            entry = grouped[q_hash]
            entry["durations"].append(dur)
            if ev_name == "DirectQueryEnd":
                entry["modes"].add("directquery")
            elif ev_name == "VertiPaqSEQueryEnd":
                entry["modes"].add("vertipaq")
            else:
                entry["modes"].add("formula")

    rows = []
    for g in grouped.values():
        durs = g["durations"]
        total_ms = sum(durs)
        med_ms = int(statistics.median(durs)) if durs else 0
        mode_str = "/".join(sorted(g["modes"]))
        rows.append([
            g["hash"],
            g["visual"],
            len(durs),
            total_ms,
            med_ms,
            mode_str,
            g["query"],
        ])

    rows.sort(key=lambda r: r[3], reverse=True)  # Sort by total_ms descending
    cols = ["hash", "visual", "count", "total_ms", "median_ms", "mode", "query"]
    return AgentTable("trace_report", cols, rows, source=f"trace {os.path.basename(jsonl_path)}")
