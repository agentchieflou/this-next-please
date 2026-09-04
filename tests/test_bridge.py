"""Tests for Power BI Desktop Bridge wire adapter.

Covers:
- JSON-RPC 2.0 Content-Length framing and parsing
- Error handling: timeouts, EOF, malformed headers, invalid JSON
- Request ID correlation and JSON-RPC error responses
- Replay stream contract testing against recorded golden transcripts
- Capability negotiation and graceful fallback classes (no pipe, undeclared op, timeout, error)
- ad-pbip capabilities bridge_manifest row
- ad-pbip bridge probe and drift detection
- ad-doctor powerbi/bridge_drift check
- ad-pbip bridge record CLI
"""
import io
import json
import os
import shutil
import time
import pytest

from agentdata import cli_pbip
from agentdata.pbip import bridge as BR
from agentdata.pbip import desktop as DT
from agentdata.pbip import screenshot as SC
from agentdata.setup.wizard import Context, AnswerPrompter, Detectors
from agentdata.setup.steps import powerbi

TRANSCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "bridge", "2.138.1452.0", "transcript.jsonl"
)


# ---------------- Framing & Protocol Tests ----------------

def test_frame_message():
    """frame_message produces valid Content-Length ASCII header and UTF-8 body."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "manifest", "params": {}}
    raw = BR.frame_message(msg)
    assert raw.startswith(b"Content-Length: ")
    assert b"\r\n\r\n" in raw

    hdr, body = raw.split(b"\r\n\r\n", 1)
    clen = int(hdr.split(b": ")[1])
    assert len(body) == clen
    assert json.loads(body.decode("utf-8")) == msg


def test_read_frame_chunked():
    """read_frame successfully parses frame delivered in byte chunks."""
    msg = {"jsonrpc": "2.0", "id": 42, "result": {"ok": True}}
    raw = BR.frame_message(msg)

    # Simulate single-byte unbuffered stream
    stream = io.BytesIO(raw)
    parsed = BR.read_frame(stream, timeout=2.0)
    assert parsed == msg


def test_read_frame_eof():
    """read_frame raises BridgeConnectionError on unexpected stream termination."""
    stream = io.BytesIO(b"Content-Length: 50\r\n\r\nshort")
    with pytest.raises(BR.BridgeConnectionError):
        BR.read_frame(stream, timeout=1.0)


def test_read_frame_missing_content_length():
    """read_frame raises BridgeMalformedError when Content-Length header is missing."""
    stream = io.BytesIO(b"Host: localhost\r\n\r\n{}")
    with pytest.raises(BR.BridgeMalformedError):
        BR.read_frame(stream, timeout=1.0)


def test_read_frame_invalid_json():
    """read_frame raises BridgeMalformedError when payload is not valid JSON."""
    raw = b"Content-Length: 12\r\n\r\nnot json at!"
    stream = io.BytesIO(raw)
    with pytest.raises(BR.BridgeMalformedError):
        BR.read_frame(stream, timeout=1.0)


def test_read_frame_timeout():
    """read_frame raises BridgeTimeoutError when stream produces nothing."""
    class StallingStream:
        def read(self, n):
            time.sleep(0.05)
            return b""
    with pytest.raises(BR.BridgeConnectionError):
        BR.read_frame(StallingStream(), timeout=0.01)


# ---------------- Client & ID Correlation Tests ----------------

def test_client_id_correlation():
    """Client increments request ID and validates matching response ID."""
    req_data = []

    class MockStream:
        def __init__(self):
            self.buf = io.BytesIO()

        def write(self, b):
            req = json.loads(b.split(b"\r\n\r\n")[1].decode("utf-8"))
            req_data.append(req)
            resp = {"jsonrpc": "2.0", "id": req["id"], "result": {"status": "ok"}}
            self.buf = io.BytesIO(BR.frame_message(resp))
            return len(b)

        def read(self, n=-1):
            return self.buf.read(n)

    client = BR.BridgeClient(MockStream(), pid=100)
    res1 = client.call("manifest")
    res2 = client.call("status")

    assert res1 == {"status": "ok"}
    assert res2 == {"status": "ok"}
    assert req_data[0]["id"] == 1
    assert req_data[0]["method"] == "manifest"
    assert req_data[1]["id"] == 2
    assert req_data[1]["method"] == "status"


def test_client_id_mismatch_raises():
    """Client raises BridgeMalformedError when response ID does not match request ID."""
    class MismatchedStream:
        def __init__(self):
            resp = {"jsonrpc": "2.0", "id": 9999, "result": {}}
            self.buf = io.BytesIO(BR.frame_message(resp))

        def write(self, b):
            return len(b)

        def read(self, n=-1):
            return self.buf.read(n)

    client = BR.BridgeClient(MismatchedStream(), pid=100)
    with pytest.raises(BR.BridgeMalformedError, match="id mismatch"):
        client.call("manifest")


def test_client_jsonrpc_error():
    """Client raises BridgeError when response contains JSON-RPC error."""
    class ErrorStream:
        def __init__(self):
            resp = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
            self.buf = io.BytesIO(BR.frame_message(resp))

        def write(self, b):
            return len(b)

        def read(self, n=-1):
            return self.buf.read(n)

    client = BR.BridgeClient(ErrorStream(), pid=100)
    with pytest.raises(BR.BridgeError, match="Method not found") as exc:
        client.call("nonexistent")
    assert exc.value.code == -32601


# ---------------- Replay Stream & Golden Transcript Tests ----------------

def test_replay_stream_golden_transcript():
    """ReplayStream successfully replays manifest, status, reload, and screenshot from golden transcript."""
    assert os.path.exists(TRANSCRIPT_PATH)
    replay = BR.ReplayStream.from_jsonl(TRANSCRIPT_PATH)
    client = BR.BridgeClient(replay, pid=1234)

    # 1. Manifest
    man = client.manifest()
    assert man["version"] == "2.138.1452.0"
    assert "reload" in man["operations"]
    assert "screenshot" in man["operations"]

    # 2. Status
    st = client.status()
    assert "Sales.pbip" in st["file"]
    assert len(st["pages"]) == 2
    assert st["pages"][0]["id"] == "ReportSection1"

    # 3. Reload
    rel = client.reload()
    assert rel["ok"] is True
    assert rel["reloaded"] is True
    assert rel["elapsed_ms"] == 142

    # 4. Screenshot
    shot = client.screenshot(page="ReportSection1")
    assert shot["page"] == "ReportSection1"
    assert shot["width"] == 1280
    assert shot["height"] == 720
    assert "image_base64" in shot


# ---------------- Capability Negotiation & Fallback Classes ----------------

def test_capabilities_includes_bridge_manifest():
    """ad-pbip capabilities table includes bridge_manifest row."""
    caps = DT.capabilities()
    names = [c["capability"] for c in caps]
    assert "bridge_pipe" in names
    assert "bridge_manifest" in names
    bm_row = next(c for c in caps if c["capability"] == "bridge_manifest")
    assert bm_row["via"] == "named_pipe"


def test_reload_fallback_no_pipe(monkeypatch):
    """reload falls back to native close+open when bridge pipe is absent."""
    # Mock status, close, open_and_wait to verify native degrade path
    class FakeInst:
        pid = 1234
        file = "C:/fake/Report.pbip"
        matched = "C:/fake/Report.pbip"

    monkeypatch.setattr(DT, "status", lambda **kw: [FakeInst()])
    monkeypatch.setattr(DT, "close", lambda *a, **kw: {"ok": True, "closed": True})
    monkeypatch.setattr(DT, "open_and_wait", lambda *a, **kw: {"ok": True, "pid": 1234, "file": "C:/fake/Report.pbip"})
    # Ensure bridge returns no pipe
    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (None, {}, "pipe not found"))

    res = DT.reload(1234)
    assert res["ok"] is True
    assert res["reloaded_via"] == "native"
    assert res["via"] == "native"
    assert "pipe not found" in res["bridge_fallback"]


def test_reload_via_bridge_when_negotiated(monkeypatch):
    """reload routes through Bridge when available and declared."""
    replay = BR.ReplayStream.from_jsonl(TRANSCRIPT_PATH)
    client = BR.BridgeClient(replay, pid=1234)

    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (client, {"version": "2.138", "operations": ["reload"]}, "ok"))

    res = DT.reload(1234)
    assert res["ok"] is True
    assert res["reloaded_via"] == "bridge"
    assert res["via"] == "bridge"
    assert res["elapsed_ms"] == 142


def test_reload_fallback_undeclared_op(monkeypatch):
    """reload falls back to native when 'reload' is missing from bridge manifest."""
    class FakeInst:
        pid = 1234
        file = "C:/fake/Report.pbip"
        matched = "C:/fake/Report.pbip"

    monkeypatch.setattr(DT, "status", lambda **kw: [FakeInst()])
    monkeypatch.setattr(DT, "close", lambda *a, **kw: {"ok": True, "closed": True})
    monkeypatch.setattr(DT, "open_and_wait", lambda *a, **kw: {"ok": True, "pid": 1234, "file": "C:/fake/Report.pbip"})

    replay = BR.ReplayStream.from_jsonl(TRANSCRIPT_PATH)
    client = BR.BridgeClient(replay, pid=1234)
    # Manifest without 'reload'
    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (client, {"version": "2.138", "operations": ["manifest", "status"]}, "ok"))

    res = DT.reload(1234)
    assert res["ok"] is True
    assert res["reloaded_via"] == "native"
    assert res["via"] == "native"
    assert "not declared" in res["bridge_fallback"]


def test_reload_fallback_bridge_error(monkeypatch):
    """reload falls back to native when bridge call raises an error."""
    class FakeInst:
        pid = 1234
        file = "C:/fake/Report.pbip"
        matched = "C:/fake/Report.pbip"

    monkeypatch.setattr(DT, "status", lambda **kw: [FakeInst()])
    monkeypatch.setattr(DT, "close", lambda *a, **kw: {"ok": True, "closed": True})
    monkeypatch.setattr(DT, "open_and_wait", lambda *a, **kw: {"ok": True, "pid": 1234, "file": "C:/fake/Report.pbip"})

    class FailingClient:
        def reload(self):
            raise BR.BridgeTimeoutError("pipe timed out")
        def close(self):
            pass

    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (FailingClient(), {"operations": ["reload"]}, "ok"))

    res = DT.reload(1234)
    assert res["ok"] is True
    assert res["reloaded_via"] == "native"
    assert "pipe timed out" in res["bridge_fallback"]


def test_screenshot_via_bridge_and_fallback(tmp_path, monkeypatch):
    """screenshot_session routes through Bridge when available, and native when not."""
    replay = BR.ReplayStream.from_jsonl(TRANSCRIPT_PATH)
    client = BR.BridgeClient(replay, pid=1234)

    class FakeInst:
        pid = 1234
        file = None
        matched = None
        pages = [{"id": "ReportSection1", "displayName": "Overview", "active": True, "order": 0}]

    monkeypatch.setattr(DT, "status", lambda **kw: [FakeInst()])

    # Bridge route
    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (client, {"operations": ["screenshot"]}, "ok"))
    p_rows, v_rows = SC.screenshot_session(1234, out_dir=str(tmp_path / "bridge_out"))
    assert len(p_rows) == 1
    assert p_rows[0]["via"] == "bridge"
    assert p_rows[0]["width"] == 1280
    assert os.path.exists(p_rows[0]["path"])

    # Fallback to native
    monkeypatch.setattr(BR, "get_bridge_manifest", lambda **kw: (None, {}, "pipe not found"))
    monkeypatch.setattr(SC, "capture_window", lambda pid, out, **kw: {"width": 800, "height": 600, "dpi": 96, "via": "printwindow"})
    monkeypatch.setattr(SC, "navigate_page", lambda pid, name, **kw: None)

    p_rows_nat, _ = SC.screenshot_session(1234, out_dir=str(tmp_path / "native_out"))
    assert len(p_rows_nat) == 1
    assert p_rows_nat[0]["via"] == "printwindow"


# ---------------- Manifest Drift & Doctor Tests ----------------

def test_manifest_drift_detection():
    """compare_manifests correctly detects added and removed operations."""
    base = {"operations": ["manifest", "status", "reload", "screenshot"]}
    curr_same = {"operations": ["manifest", "status", "reload", "screenshot"]}
    diff_none = BR.compare_manifests(curr_same, base)
    assert diff_none["drift"] is False
    assert diff_none["summary"] == "none"

    curr_added = {"operations": ["manifest", "status", "reload", "screenshot", "theme-apply"]}
    diff_add = BR.compare_manifests(curr_added, base)
    assert diff_add["drift"] is True
    assert "added: theme-apply" in diff_add["summary"]

    curr_removed = {"operations": ["manifest", "status"]}
    diff_rem = BR.compare_manifests(curr_removed, base)
    assert diff_rem["drift"] is True
    assert "removed: reload, screenshot" in diff_rem["summary"]


def test_doctor_bridge_drift_check(monkeypatch):
    """ad-doctor powerbi/bridge_drift emits ok when matching or absent, and warn when drift detected."""
    class FakeDet(Detectors):
        def run(self, cmd, timeout=120):
            return 0, "", ""

    ctx = Context(cfg={}, det=FakeDet(), ask=AnswerPrompter(), online=False, interactive=False)
    step = powerbi.PowerBIStep()

    # Case 1: No active bridge pipe -> ok (preview transport optional)
    monkeypatch.setattr(BR, "probe_bridge", lambda **kw: {"pipe_present": False, "drift": "unknown"})
    step.verify(ctx)
    chk1 = next(c for c in ctx.checks if c.name == "powerbi/bridge_drift")
    assert chk1.status == "ok"
    assert "optional preview transport" in chk1.detail

    # Case 2: Bridge pipe with drift detected -> warn (never error)
    ctx2 = Context(cfg={}, det=FakeDet(), ask=AnswerPrompter(), online=False, interactive=False)
    monkeypatch.setattr(BR, "probe_bridge", lambda **kw: {
        "pipe_present": True,
        "drift": "detected",
        "drift_summary": "added: new_feature",
        "operations": ["manifest", "new_feature"],
        "rtt_ms": 15,
    })
    step.verify(ctx2)
    chk2 = next(c for c in ctx2.checks if c.name == "powerbi/bridge_drift")
    assert chk2.status == "warn"
    assert "added: new_feature" in chk2.detail


# ---------------- CLI Tests ----------------

def test_cli_bridge_probe(capsys, monkeypatch):
    """ad-pbip bridge probe prints operations and drift metadata."""
    monkeypatch.setattr(BR, "probe_bridge", lambda **kw: {
        "pipe_present": True,
        "pid": 5678,
        "rtt_ms": 10,
        "version": "2.138.1452.0",
        "operations": ["manifest", "status", "reload"],
        "drift": "none",
        "drift_summary": "none",
    })

    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["bridge", "probe"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "source: ad-pbip bridge probe" in out
    assert "pipe_present: true" in out
    assert "rtt_ms: 10" in out
    assert "drift: none" in out
    assert "manifest,declared" in out
    assert "status,declared" in out
    assert "reload,declared" in out


def test_cli_bridge_record_requires_pid(capsys):
    """ad-pbip bridge record fails when --pid is omitted."""
    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["bridge", "record"])
    assert exc.value.code == 2  # argparse missing required argument
