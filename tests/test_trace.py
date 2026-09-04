"""Tests for Analysis Services trace capture and visual correlation."""
import json
import os
import tempfile
import time
from multiprocessing.connection import Client
import pytest
from agentdata.pbip import trace as TR
from agentdata.cli_pbip import main


def test_default_trace_pipe():
    addr, family = TR.default_trace_pipe(pid=1234)
    assert family in ("AF_PIPE", "AF_INET")
    if family == "AF_PIPE":
        assert "1234" in addr
    else:
        assert addr[0] == "localhost"


def test_trace_listener_streaming():
    # Use AF_INET on localhost for cross-platform test reliability
    listener = TR.TraceListener(("localhost", 0), family="AF_INET")
    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "trace.jsonl").replace("\\", "/")
        listener.start(out_file=out_file)
        addr = listener.listener.address

        # Connect client and send events
        client = Client(addr, family="AF_INET")
        ev1 = {"event": "QueryEnd", "duration_ms": 42, "text": "EVALUATE Customer"}
        ev2 = {"event": "VertiPaqSEQueryEnd", "duration_ms": 12, "text": "SELECT Customer[Id]"}
        client.send(json.dumps(ev1) + "\n" + json.dumps(ev2))
        client.close()

        # Give listener loop a moment to flush
        time.sleep(0.3)
        TR.stop_trace(listener)

        assert len(listener.events) == 2
        assert listener.events[0]["event"] == "QueryEnd"
        assert listener.events[1]["duration_ms"] == 12

        assert os.path.exists(out_file)
        with open(out_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) == 2


def test_report_trace_aggregation():
    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "events.jsonl")
        events = [
            {"event": "QueryEnd", "duration_ms": 100, "text": "EVALUATE Sales"},
            {"event": "VertiPaqSEQueryEnd", "duration_ms": 50, "text": "EVALUATE Sales"},
            {"event": "QueryEnd", "duration_ms": 200, "text": "EVALUATE Sales"},
            {"event": "DirectQueryEnd", "duration_ms": 400, "text": "SELECT * FROM remote_orders"},
        ]
        with open(out_file, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        rep = TR.report_trace(out_file)
        assert len(rep.rows) == 2
        # Highest total_ms should be first (EVALUATE Sales total = 100+50+200 = 350, DirectQuery = 400)
        top_row = rep.rows[0]
        assert "remote_orders" in top_row[6]
        assert top_row[3] == 400
        assert top_row[5] == "directquery"

        sales_row = rep.rows[1]
        assert "Sales" in sales_row[6]
        assert sales_row[2] == 3  # count
        assert sales_row[3] == 350  # total_ms
        assert sales_row[4] == 100  # median_ms
        assert "formula" in sales_row[5] and "vertipaq" in sales_row[5]


def test_report_trace_visual_correlation():
    with tempfile.TemporaryDirectory() as td:
        # Build mock PBIR report directory
        pages_dir = os.path.join(td, "definition", "pages", "page1", "visuals", "vis1")
        os.makedirs(pages_dir, exist_ok=True)
        vdata = {
            "name": "vis1",
            "visual": {
                "visualType": "barChart",
                "visualContainerObjects": {
                    "title": [{"properties": {"text": {"expr": {"Literal": {"Value": "'Sales by Region'"}}}}}]
                },
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {"queryRef": "Sales.TotalRevenue"}
                            ]
                        }
                    }
                }
            }
        }
        with open(os.path.join(pages_dir, "visual.json"), "w", encoding="utf-8") as vf:
            json.dump(vdata, vf)

        # Trace events referencing Sales.TotalRevenue
        out_file = os.path.join(td, "trace.jsonl")
        events = [
            {"event": "QueryEnd", "duration_ms": 75, "text": "EVALUATE SUMMARIZECOLUMNS(Region, 'Sales'[TotalRevenue])"},
        ]
        with open(out_file, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

        rep = TR.report_trace(out_file, report_dir=td)
        assert len(rep.rows) == 1
        # Correlated visual should be "Sales by Region"
        assert rep.rows[0][1] == "Sales by Region"


def test_cli_trace_report(capsys):
    with tempfile.TemporaryDirectory() as td:
        out_file = os.path.join(td, "cli_trace.jsonl")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"event": "QueryEnd", "duration_ms": 30, "text": "EVALUATE Top10"}) + "\n")

        with pytest.raises(SystemExit) as exc:
            main(["trace", "report", out_file])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Top10" in captured.out
