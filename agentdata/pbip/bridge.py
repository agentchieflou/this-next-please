"""Power BI Desktop Bridge wire adapter.

Speaks JSON-RPC 2.0 over named pipe \\\\.\\pipe\\pbi-desktop-bridge-<pid> with Content-Length framing.
Pure standard library: opens the Windows named pipe as binary unbuffered file.
Learns operations from manifest and recorded transcripts; gracefully degrades to native
on missing pipe, undeclared operations, malformed frames, or timeouts.
"""
from __future__ import annotations
import glob
import io
import json
import os
import re
import socket
import sys
import time
from typing import Any, Callable

PIPE_PREFIX = r"\\.\pipe\pbi-desktop-bridge-"
CONTENT_LENGTH_RE = re.compile(rb"content-length:\s*(\d+)", re.IGNORECASE)


class BridgeError(RuntimeError):
    """Base error for Bridge wire operations."""
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class BridgeConnectionError(BridgeError):
    """Pipe connection not available or closed."""
    pass


class BridgeTimeoutError(BridgeError):
    """Operation timed out waiting for pipe response."""
    pass


class BridgeMalformedError(BridgeError):
    """Malformed framing or invalid JSON-RPC payload."""
    pass


def frame_message(payload: dict | str) -> bytes:
    """Encode JSON-RPC message into Content-Length framed byte sequence."""
    if isinstance(payload, dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    else:
        body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def read_frame(stream: Any, timeout: float = 5.0) -> dict[str, Any]:
    """Read a Content-Length framed JSON-RPC message from an unbuffered binary stream."""
    t0 = time.perf_counter()
    header_buf = bytearray()
    content_len: int | None = None

    # Read until header terminator \r\n\r\n
    while True:
        if time.perf_counter() - t0 > timeout:
            raise BridgeTimeoutError(f"timed out waiting for headers ({timeout}s)")
        b = stream.read(1)
        if not b:
            raise BridgeConnectionError("connection closed while reading header")
        header_buf.extend(b)
        if b"\r\n\r\n" in header_buf:
            break

    # Parse Content-Length
    m = CONTENT_LENGTH_RE.search(header_buf)
    if not m:
        raise BridgeMalformedError(f"missing Content-Length header in: {bytes(header_buf)!r}")
    try:
        content_len = int(m.group(1).decode("ascii"))
    except ValueError as e:
        raise BridgeMalformedError(f"invalid Content-Length: {e}")

    # Read body bytes
    body_buf = bytearray()
    while len(body_buf) < content_len:
        if time.perf_counter() - t0 > timeout:
            raise BridgeTimeoutError(f"timed out reading body ({len(body_buf)}/{content_len} bytes)")
        chunk = stream.read(content_len - len(body_buf))
        if not chunk:
            raise BridgeConnectionError("connection closed while reading body")
        body_buf.extend(chunk)

    try:
        data = json.loads(body_buf.decode("utf-8"))
    except Exception as e:
        raise BridgeMalformedError(f"invalid JSON payload: {e}")

    return data


class BridgeClient:
    """JSON-RPC 2.0 client over an unbuffered binary stream."""

    def __init__(self, stream: Any, pid: int | None = None):
        self.stream = stream
        self.pid = pid
        self._next_id = 1

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        raw = frame_message(req)
        try:
            self.stream.write(raw)
            if hasattr(self.stream, "flush"):
                self.stream.flush()
        except Exception as e:
            raise BridgeConnectionError(f"failed to write frame: {e}")

        resp = read_frame(self.stream, timeout=timeout)
        if resp.get("id") != req_id:
            raise BridgeMalformedError(f"id mismatch: expected {req_id}, got {resp.get('id')}")
        if "error" in resp:
            err = resp["error"]
            raise BridgeError(err.get("message", "Bridge error"), code=err.get("code"))
        return resp.get("result", {})

    def manifest(self, timeout: float = 5.0) -> dict[str, Any]:
        """Read advertised capabilities from Bridge."""
        return self.call("manifest", timeout=timeout)

    def status(self, timeout: float = 5.0) -> dict[str, Any]:
        """Read session status (file, unsaved, pages)."""
        return self.call("status", timeout=timeout)

    def reload(self, timeout: float = 10.0) -> dict[str, Any]:
        """Trigger in-place report reload keeping AS instance alive."""
        return self.call("reload", timeout=timeout)

    def screenshot(self, page: str | None = None, timeout: float = 15.0) -> dict[str, Any]:
        """Capture screenshot via Desktop rendering engine."""
        params = {"page": page} if page else {}
        return self.call("screenshot", params=params, timeout=timeout)

    def close(self) -> None:
        """Close underlying stream."""
        try:
            if hasattr(self.stream, "close"):
                self.stream.close()
        except Exception:
            pass


def open_pipe(pid: int, timeout: float = 5.0, stream: Any = None) -> BridgeClient | None:
    """Open connection to named pipe \\\\.\\pipe\\pbi-desktop-bridge-<pid>.
    
    Returns BridgeClient or None if pipe is unavailable or fails.
    """
    if stream is not None:
        return BridgeClient(stream, pid=pid)

    if sys.platform != "win32":
        return None

    pipe_path = f"{PIPE_PREFIX}{pid}"
    if not os.path.exists(pipe_path):
        return None

    try:
        # Open pipe in unbuffered binary read/write mode
        f = open(pipe_path, "r+b", buffering=0)
        return BridgeClient(f, pid=pid)
    except (FileNotFoundError, PermissionError, OSError):
        return None


def get_bridge_manifest(pid: int | None = None, client: BridgeClient | None = None) -> tuple[BridgeClient | None, dict[str, Any], str]:
    """Retrieve bridge client and manifest. Returns (client, manifest_dict, reason)."""
    c = client
    if c is None:
        if pid is None:
            # Discover first active pipe
            pipes = glob.glob(r"\\.\pipe\pbi-desktop-bridge-*")
            if not pipes:
                return None, {}, "no bridge pipe active"
            m = re.search(r"bridge-(\d+)", pipes[0])
            if m:
                pid = int(m.group(1))
            else:
                return None, {}, "invalid bridge pipe name"

        c = open_pipe(pid)
        if not c:
            return None, {}, f"pipe for pid {pid} not found"

    try:
        man = c.manifest(timeout=3.0)
        return c, man, "ok"
    except Exception as e:
        if client is None and c:
            c.close()
        return None, {}, f"manifest read error: {e}"


def is_operation_supported(op: str, pid: int | None = None, manifest: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Check if operation is declared in bridge manifest."""
    if manifest is None:
        client, man, reason = get_bridge_manifest(pid=pid)
        if client:
            client.close()
        if not man:
            return False, reason
        manifest = man

    ops = manifest.get("operations", [])
    if op in ops:
        return True, "declared"
    return False, f"operation '{op}' not declared in manifest"


# ---------------- Transcript recording and drift detection ----------------

def find_baseline_transcript(fixture_dir: str | None = None) -> tuple[str | None, dict[str, Any]]:
    """Locate the newest recorded transcript fixture and parse its manifest."""
    base_dir = fixture_dir or os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "bridge")
    base_dir = os.path.abspath(base_dir)
    if not os.path.isdir(base_dir):
        return None, {}

    versions = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if not versions:
        return None, {}
    versions.sort(reverse=True)
    latest_ver = versions[0]
    jsonl_files = glob.glob(os.path.join(base_dir, latest_ver, "*.jsonl"))
    if not jsonl_files:
        return None, {}

    t_path = sorted(jsonl_files)[0]
    manifest: dict[str, Any] = {}
    try:
        with open(t_path, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                frame = rec.get("frame") or {}
                # Look for response to manifest
                if rec.get("direction") == "response" and "operations" in frame.get("result", {}):
                    manifest = frame["result"]
                    break
    except Exception:
        pass
    return t_path, manifest


def compare_manifests(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Compare current manifest against baseline manifest to detect added/removed operations."""
    curr_ops = set(current.get("operations", []))
    base_ops = set(baseline.get("operations", []))

    added = sorted(list(curr_ops - base_ops))
    removed = sorted(list(base_ops - curr_ops))

    if not base_ops and not curr_ops:
        summary = "none"
        has_drift = False
    elif not base_ops:
        summary = f"baseline empty; current has {len(curr_ops)} ops"
        has_drift = False
    elif not added and not removed:
        summary = "none"
        has_drift = False
    else:
        parts = []
        if added:
            parts.append(f"added: {', '.join(added)}")
        if removed:
            parts.append(f"removed: {', '.join(removed)}")
        summary = "; ".join(parts)
        has_drift = True

    return {
        "drift": has_drift,
        "summary": summary,
        "added": added,
        "removed": removed,
    }


def probe_bridge(pid: int | None = None, client: BridgeClient | None = None, fixture_dir: str | None = None) -> dict[str, Any]:
    """Probe active bridge for status, RTT, and manifest drift."""
    t0 = time.perf_counter()
    c, man, reason = get_bridge_manifest(pid=pid, client=client)
    rtt_ms = int((time.perf_counter() - t0) * 1000)

    if not c or not man:
        return {
            "pipe_present": False,
            "pid": pid,
            "rtt_ms": 0,
            "version": "none",
            "operations": [],
            "drift": "unknown",
            "drift_summary": "no bridge pipe active",
            "reason": reason,
        }

    _, baseline = find_baseline_transcript(fixture_dir=fixture_dir)
    diff = compare_manifests(man, baseline)

    if client is None:
        c.close()

    return {
        "pipe_present": True,
        "pid": pid or c.pid,
        "rtt_ms": rtt_ms,
        "version": man.get("version", "unknown"),
        "operations": man.get("operations", []),
        "drift": "detected" if diff["drift"] else "none",
        "drift_summary": diff["summary"],
        "added": diff["added"],
        "removed": diff["removed"],
    }


def record_transcript(pid: int, out_dir: str | None = None, client: BridgeClient | None = None) -> str:
    """Record manifest + status + screenshot interactions to a .jsonl transcript file."""
    import datetime
    c = client or open_pipe(pid)
    if not c:
        raise BridgeConnectionError(f"unable to connect to pipe for pid {pid}")

    frames: list[dict[str, Any]] = []

    def record_call(method: str, params: dict[str, Any] | None = None):
        req_id = c._next_id
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        req_frame = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        frames.append({"direction": "request", "timestamp": now, "frame": req_frame})
        res = c.call(method, params=params)
        res_frame = {"jsonrpc": "2.0", "id": req_id, "result": res}
        frames.append({"direction": "response", "timestamp": now, "frame": res_frame})
        return res

    man = record_call("manifest")
    ver = man.get("version", "unknown")
    record_call("status")
    if "screenshot" in man.get("operations", []):
        try:
            record_call("screenshot")
        except Exception:
            pass

    if client is None:
        c.close()

    dest_dir = out_dir or os.path.join("tests", "fixtures", "bridge", ver)
    os.makedirs(dest_dir, exist_ok=True)
    out_file = os.path.join(dest_dir, "transcript.jsonl")
    with open(out_file, "w", encoding="utf-8") as f:
        for item in frames:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return out_file


# ---------------- Replay / Mock transport for tests ----------------

class ReplayStream:
    """Bidirectional in-memory stream for testing that simulates a bridge pipe using a transcript."""

    def __init__(self, transcript_items: list[dict[str, Any]]):
        self.responses_by_id: dict[tuple[int, str], dict[str, Any]] = {}
        self.responses_by_method: dict[str, dict[str, Any]] = {}
        curr_req = None
        for item in transcript_items:
            direction = item.get("direction")
            frame = item.get("frame", {})
            if direction == "request":
                curr_req = frame
            elif direction == "response" and curr_req:
                self.responses_by_id[(curr_req.get("id"), curr_req.get("method"))] = frame
                self.responses_by_method[curr_req.get("method")] = frame
                curr_req = None

        self._read_buf = bytearray()
        self._write_buf = bytearray()
        self.closed = False

    @classmethod
    def from_jsonl(cls, jsonl_path: str) -> "ReplayStream":
        items = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return cls(items)

    def write(self, data: bytes) -> int:
        self._write_buf.extend(data)
        # Check if full frame written
        if b"\r\n\r\n" in self._write_buf:
            m = CONTENT_LENGTH_RE.search(self._write_buf)
            if m:
                clen = int(m.group(1).decode("ascii"))
                hdr_end = self._write_buf.index(b"\r\n\r\n") + 4
                if len(self._write_buf) >= hdr_end + clen:
                    body = self._write_buf[hdr_end:hdr_end + clen]
                    self._write_buf = self._write_buf[hdr_end + clen:]
                    req = json.loads(body.decode("utf-8"))
                    req_id = req.get("id")
                    method = req.get("method")
                    base_frame = self.responses_by_id.get((req_id, method)) or self.responses_by_method.get(method)
                    if base_frame:
                        resp_frame = dict(base_frame)
                        resp_frame["id"] = req_id
                    else:
                        resp_frame = {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True, "method": method}}
                    raw_resp = frame_message(resp_frame)
                    self._read_buf.extend(raw_resp)
        return len(data)

    def read(self, n: int = -1) -> bytes:
        if n == -1 or n >= len(self._read_buf):
            res = bytes(self._read_buf)
            self._read_buf.clear()
            return res
        res = bytes(self._read_buf[:n])
        self._read_buf = self._read_buf[n:]
        return res

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
