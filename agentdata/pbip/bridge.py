"""Power BI Desktop Bridge wire adapter.

Speaks JSON-RPC 2.0 over named pipe \\\\.\\pipe\\pbi-desktop-bridge-<pid> with Content-Length framing.
Pure standard library: opens the Windows named pipe as binary unbuffered file.

Two dialects (0.18.0):

- documented: the contract Microsoft Learn documents for the Desktop Bridge ("What is the Power BI
  Desktop Bridge?"), shipped in Desktop 2.155 (June 2026) and verified against 2.157 (August 2026):
  `bridge.manifest` returns `{"methods": [{name, description, params, result}]}`, and the operations
  are versioned methods -- `application.state.get/v1`, `file.reload/v1`, `report.snapshot.capture/v1`.
- legacy: the pre-release bridge the 2.138 transcript recorded -- `manifest` returns
  `{"version", "operations": [...]}`, and the operations are bare words (`status`, `reload`,
  `screenshot`).

The client asks for `bridge.manifest` first and falls back to `manifest`; every caller works in the
logical operations of `DOCUMENTED`, never in method names, so a later `/v2` is one manifest away.
It degrades to native on a missing pipe, an undeclared operation, a malformed frame, or a timeout.
"""
from __future__ import annotations
import base64
import glob
import json
import os
import re
import struct
import sys
import time
from typing import Any

PIPE_PREFIX = r"\\.\pipe\pbi-desktop-bridge-"
CONTENT_LENGTH_RE = re.compile(rb"content-length:\s*(\d+)", re.IGNORECASE)

#: Each logical operation this package uses, and the documented method family that serves it. A
#: family is versioned (`file.reload/v1`); the highest version the manifest declares is the one called.
DOCUMENTED = {
    "manifest": "bridge.manifest",
    "state": "application.state.get",
    "reload": "file.reload",
    "screenshot": "report.snapshot.capture",
}
#: What the pre-release bridge answered to (tests/fixtures/bridge/2.138.1452.0): one word per operation.
LEGACY = {"manifest": "manifest", "state": "status", "reload": "reload", "screenshot": "screenshot"}
#: JSON-RPC 2.0's "method not found": an older or newer Desktop that does not serve a method.
METHOD_NOT_FOUND = -32601
#: The bridge runs one operation at a time and answers a second one with an error while the first
#: runs; the documentation gives no code for it, so it is recognised by its words.
BUSY_WORDS = ("busy", "in progress", "another operation", "already running", "currently running")
#: Seconds before the first retry of a busy answer; it doubles each time (tests set it to 0).
BUSY_BACKOFF = 0.5
#: The machine policy that turns the bridge on or off for every user (Microsoft Learn: "Manage
#: Desktop Bridge with a registry policy").
POLICY_HIVE = "HKLM"
POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Power BI Desktop"
POLICY_VALUE = "DesktopNamedPipeBridge"
#: Where a person turns it on when no policy decides: on by default.
ENABLE_HINT = ("open the report in Power BI Desktop (2.155 or later); the bridge is File > Options and settings > "
               "Options > Security > Desktop Bridge > 'Enable external tool access to Power BI Desktop through "
               "secure local APIs', on by default")
VERSION_RE = re.compile(r"/v(\d+)$")


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


class BridgeUnsupported(BridgeError):
    """The manifest does not declare the operation asked for."""
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


def _best(family: str, names: list[str]) -> str | None:
    """The highest-versioned method of a family (`file.reload/v2` over `/v1` over a bare name)."""
    best, best_v = None, -1
    for name in names:
        if name == family:
            v = 0
        elif name.startswith(family + "/"):
            m = VERSION_RE.search(name)
            if not m:
                continue
            v = int(m.group(1))
        else:
            continue
        if v > best_v:
            best, best_v = name, v
    return best


def normalize_manifest(raw: dict[str, Any] | None) -> dict[str, Any]:
    """One shape for both dialects, and idempotent: a normalised manifest comes back unchanged.

    `{"dialect", "version", "methods": {name: definition}, "names": {operation: method},
    "operations": [operation, ...]}` -- `operations` are the logical names of `DOCUMENTED`.
    """
    raw = raw or {}
    if raw.get("dialect") in ("documented", "legacy"):
        return raw
    if isinstance(raw.get("methods"), list):
        methods: dict[str, Any] = {}
        for m in raw["methods"]:
            if isinstance(m, dict) and m.get("name"):
                methods[str(m["name"])] = m
            elif isinstance(m, str):
                methods[m] = {"name": m}
        names = {}
        for op, family in DOCUMENTED.items():
            best = _best(family, list(methods))
            if best:
                names[op] = best
        names.setdefault("manifest", DOCUMENTED["manifest"])
        version = raw.get("version") or raw.get("productVersion") or raw.get("desktopVersion") or "unknown"
        return {"dialect": "documented", "version": str(version), "methods": methods, "names": names,
                "operations": sorted(names)}
    ops = [str(o) for o in (raw.get("operations") or [])]
    names = {op: word for op, word in LEGACY.items() if word in ops}
    return {"dialect": "legacy", "version": str(raw.get("version", "unknown")), "methods": {o: {"name": o} for o in ops},
            "names": names, "operations": sorted(names)}


def _busy(e: BridgeError) -> bool:
    text = str(e).lower()
    return any(w in text for w in BUSY_WORDS)


def _png_size(png: bytes) -> tuple[int | None, int | None]:
    """Width and height from a PNG's IHDR chunk, which the documented snapshot does not repeat."""
    if len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR":
        w, h = struct.unpack(">II", png[16:24])
        return int(w), int(h)
    return None, None


class BridgeClient:
    """JSON-RPC 2.0 client over an unbuffered binary stream."""

    def __init__(self, stream: Any, pid: int | None = None):
        self.stream = stream
        self.pid = pid
        self._next_id = 1
        self.man: dict[str, Any] | None = None

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

    def call_retry(self, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0,
                   attempts: int = 4) -> dict[str, Any]:
        """`call`, waiting out a bridge that is busy with another client's operation."""
        delay = BUSY_BACKOFF
        for i in range(attempts):
            try:
                return self.call(method, params=params, timeout=timeout)
            except BridgeError as e:
                if i == attempts - 1 or not _busy(e):
                    raise
                time.sleep(delay)
                delay *= 2
        raise BridgeError(f"{method}: still busy after {attempts} attempts")

    def manifest(self, timeout: float = 5.0) -> dict[str, Any]:
        """The manifest, normalised: `bridge.manifest` first, the pre-release `manifest` second."""
        raw: dict[str, Any] = {}
        try:
            raw = self.call(DOCUMENTED["manifest"], timeout=timeout)
        except BridgeError as e:
            if e.code not in (METHOD_NOT_FOUND, None) and not isinstance(e, BridgeMalformedError):
                raise
        if not isinstance(raw.get("methods"), list) and "operations" not in raw:
            raw = self.call(LEGACY["manifest"], timeout=timeout)
        self.man = normalize_manifest(raw)
        return self.man

    def bind(self, manifest: dict[str, Any] | None) -> "BridgeClient":
        """Adopt a manifest read elsewhere, so a call does not read it again."""
        if manifest and self.man is None:
            self.man = normalize_manifest(manifest)
        return self

    def method(self, op: str) -> str:
        """The method that serves a logical operation, or `BridgeUnsupported`."""
        if self.man is None:
            self.manifest()
        name = (self.man or {}).get("names", {}).get(op)
        if not name:
            raise BridgeUnsupported(f"operation '{op}' not declared in bridge manifest")
        return name

    @property
    def documented(self) -> bool:
        return bool(self.man and self.man.get("dialect") == "documented")

    def state(self, timeout: float = 10.0) -> dict[str, Any]:
        """The open file and whether it has unsaved changes.

        `unsaved` is True, False, or None when the bridge did not say: callers that would overwrite
        Desktop's state go ahead only on an explicit False.
        """
        raw = self.call_retry(self.method("state"), timeout=timeout)
        if self.documented:
            flag = raw.get("hasUnsavedChanges")
            return {"file": raw.get("currentFilePath") or "", "unsaved": flag if isinstance(flag, bool) else None,
                    "raw": raw}
        flag = raw.get("unsaved")
        return {"file": raw.get("file") or "", "unsaved": flag if isinstance(flag, bool) else None,
                "pages": raw.get("pages", []), "raw": raw}

    status = state  # the pre-release name, and what older callers say

    def reload(self, model: bool = True, timeout: float = 180.0) -> dict[str, Any]:
        """Reload the open PBIP from disk; `model=False` reloads the report without the model definition."""
        name = self.method("reload")
        params = {"reloadModelDefinition": bool(model)} if self.documented else {}
        raw = self.call_retry(name, params=params, timeout=timeout)
        ok = raw["success"] if "success" in raw else raw.get("ok", raw.get("reloaded", False))
        return {"ok": bool(ok), "reloaded": bool(ok), "model": bool(model) if self.documented else None,
                "elapsed_ms": raw.get("elapsed_ms", 0), "raw": raw}

    def screenshot(self, page: str | None = None, scale: float | None = None, timeout: float = 60.0) -> dict[str, Any]:
        """One page as a PNG: `{"png", "page", "displayName", "mime", "width", "height", "dpi", "path"}`."""
        name = self.method("screenshot")
        if self.documented:
            if not page:
                raise BridgeError("report.snapshot.capture needs a page id (the PBIR page name)")
            params: dict[str, Any] = {"pageId": page}
            if scale:
                params["scale"] = max(1.0, min(3.0, float(scale)))
        else:
            params = {"page": page} if page else {}
        raw = self.call_retry(name, params=params, timeout=timeout)
        png = None
        if raw.get("payload"):
            png = base64.b64decode(raw["payload"])
        elif raw.get("image_base64"):
            png = base64.b64decode(raw["image_base64"])
        w, h = raw.get("width"), raw.get("height")
        if png and (not w or not h):
            w, h = _png_size(png)
        return {"png": png, "path": raw.get("path"), "page": raw.get("pageId") or raw.get("page") or page,
                "displayName": raw.get("pageDisplayName") or raw.get("displayName"),
                "mime": raw.get("mimeType", "image/png"), "width": w, "height": h, "dpi": raw.get("dpi", 96),
                "raw": raw}

    def close(self) -> None:
        """Close underlying stream."""
        try:
            if hasattr(self.stream, "close"):
                self.stream.close()
        except Exception:
            pass


def policy(native: bool = True) -> str:
    """The machine policy: `enabled`, `disabled`, `unset`, or `unknown` (off Windows, or unreadable)."""
    if not native or sys.platform != "win32":
        return "unknown"
    try:
        import winreg  # win32 only
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, POLICY_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, POLICY_VALUE)
    except FileNotFoundError:
        return "unset"
    except OSError:
        return "unknown"
    return "disabled" if str(value).strip() == "0" else "enabled"


def no_pipe_reason(pid: int | None = None, native: bool = True) -> str:
    """Why there is no pipe, in words a person can act on."""
    if policy(native=native) == "disabled":
        return (f"Desktop Bridge disabled by machine policy ({POLICY_HIVE}\\{POLICY_KEY}\\{POLICY_VALUE} = 0); "
                "only IT can turn it back on")
    where = f"pipe for pid {pid} not found" if pid else "no bridge pipe active"
    return f"{where}: {ENABLE_HINT}"


def list_pipes() -> list[str]:
    """Every bridge pipe on this machine, one per open Desktop window."""
    if sys.platform != "win32":
        return []
    pipes = glob.glob(PIPE_PREFIX + "*")
    if not pipes:
        try:
            pipes = [r"\\.\pipe" + "\\" + n for n in os.listdir("\\\\.\\pipe\\") if n.startswith("pbi-desktop-bridge-")]
        except OSError:
            pipes = []
    return sorted(pipes)


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
    """Retrieve bridge client and its normalised manifest. Returns (client, manifest_dict, reason)."""
    c = client
    if c is None:
        if pid is None:
            # Discover first active pipe
            pipes = list_pipes()
            if not pipes:
                return None, {}, no_pipe_reason()
            m = re.search(r"bridge-(\d+)", pipes[0])
            if m:
                pid = int(m.group(1))
            else:
                return None, {}, "invalid bridge pipe name"

        c = open_pipe(pid)
        if not c:
            return None, {}, no_pipe_reason(pid)

    try:
        man = c.manifest(timeout=3.0)
        return c, man, "ok"
    except Exception as e:
        if client is None and c:
            c.close()
        return None, {}, f"manifest read error: {e}"


def is_operation_supported(op: str, pid: int | None = None, manifest: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Check if a logical operation is declared in bridge manifest."""
    if manifest is None:
        client, man, reason = get_bridge_manifest(pid=pid)
        if client:
            client.close()
        if not man:
            return False, reason
        manifest = man

    man = normalize_manifest(manifest)
    if op in man["operations"]:
        return True, f"declared as {man['names'][op]}"
    return False, f"operation '{op}' not declared in manifest"


# ---------------- Transcript recording and drift detection ----------------

def _version_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else -1 for p in re.split(r"[.\-]", name))


def find_baseline_transcript(fixture_dir: str | None = None) -> tuple[str | None, dict[str, Any]]:
    """Locate the newest recorded transcript fixture and parse its manifest (normalised)."""
    base_dir = fixture_dir or os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "bridge")
    base_dir = os.path.abspath(base_dir)
    if not os.path.isdir(base_dir):
        return None, {}

    versions = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    if not versions:
        return None, {}
    versions.sort(key=_version_key, reverse=True)
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
                result = frame.get("result") or {}
                if rec.get("direction") == "response" and ("operations" in result or "methods" in result):
                    manifest = normalize_manifest(result)
                    if manifest.get("version") in (None, "", "unknown"):
                        manifest["version"] = latest_ver
                    break
    except Exception:
        pass
    return t_path, manifest


def compare_manifests(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Compare current manifest against baseline manifest to detect added/removed methods."""
    curr = normalize_manifest(current) if current else {"methods": {}, "dialect": None}
    base = normalize_manifest(baseline) if baseline else {"methods": {}, "dialect": None}
    curr_ops = set(curr.get("methods", {}))
    base_ops = set(base.get("methods", {}))

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
        if base.get("dialect") and curr.get("dialect") and base["dialect"] != curr["dialect"]:
            parts.append(f"dialect: {base['dialect']} -> {curr['dialect']}")
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
            "dialect": "none",
            "operations": [],
            "names": {},
            "drift": "unknown",
            "drift_summary": "no bridge pipe active",
            "reason": reason,
            "policy": policy(),
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
        "dialect": man.get("dialect", "unknown"),
        "operations": man.get("operations", []),
        "names": man.get("names", {}),
        "methods": sorted(man.get("methods", {})),
        "drift": "detected" if diff["drift"] else "none",
        "drift_summary": diff["summary"],
        "added": diff["added"],
        "removed": diff["removed"],
        "policy": policy(),
    }


def record_transcript(pid: int, out_dir: str | None = None, client: BridgeClient | None = None,
                      version: str | None = None, page: str | None = None) -> str:
    """Record manifest + state (+ one page snapshot when `page` is given) to a .jsonl transcript file.

    Read-only: it never records a reload, which would change what Desktop shows.
    """
    import datetime
    c = client or open_pipe(pid)
    if not c:
        raise BridgeConnectionError(no_pipe_reason(pid))

    frames: list[dict[str, Any]] = []

    def record_call(method: str, params: dict[str, Any] | None = None):
        req_id = c._next_id
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        req_frame = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        frames.append({"direction": "request", "timestamp": now, "frame": req_frame})
        try:
            res = c.call(method, params=params)
        except BridgeError as e:
            frames.append({"direction": "response", "timestamp": now,
                           "frame": {"jsonrpc": "2.0", "id": req_id, "error": {"code": e.code, "message": str(e)}}})
            raise
        frames.append({"direction": "response", "timestamp": now, "frame": {"jsonrpc": "2.0", "id": req_id, "result": res}})
        return res

    try:
        raw = record_call(DOCUMENTED["manifest"])
    except BridgeError as e:
        if e.code not in (METHOD_NOT_FOUND, None):
            raise
        raw = {}
    if not isinstance(raw.get("methods"), list) and "operations" not in raw:
        raw = record_call(LEGACY["manifest"])
    man = c.man = normalize_manifest(raw)
    ver = version or (man.get("version") if man.get("version") not in (None, "", "unknown") else None) or "unknown"
    if "state" in man["names"]:
        record_call(man["names"]["state"])
    if page and "screenshot" in man["names"]:
        params = {"pageId": page} if man["dialect"] == "documented" else {"page": page}
        try:
            record_call(man["names"]["screenshot"], params)
        except BridgeError:
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
    """Bidirectional in-memory stream for testing that simulates a bridge pipe using a transcript.

    A request whose method the transcript never saw is answered with JSON-RPC's -32601 (method not
    found), as Desktop does, so the dialect fallback is exercised the way it runs.
    """

    def __init__(self, transcript_items: list[dict[str, Any]], strict: bool = True):
        self.responses_by_id: dict[tuple[int, str], dict[str, Any]] = {}
        self.responses_by_method: dict[str, dict[str, Any]] = {}
        self.requests: list[dict[str, Any]] = []
        self.strict = strict
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
    def from_jsonl(cls, jsonl_path: str, strict: bool = True) -> "ReplayStream":
        items = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return cls(items, strict=strict)

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
                    self.requests.append(req)
                    req_id = req.get("id")
                    method = req.get("method")
                    base_frame = self.responses_by_id.get((req_id, method)) or self.responses_by_method.get(method)
                    if base_frame:
                        resp_frame = dict(base_frame)
                        resp_frame["id"] = req_id
                    elif self.strict:
                        resp_frame = {"jsonrpc": "2.0", "id": req_id,
                                      "error": {"code": METHOD_NOT_FOUND, "message": f"Method not found: {method}"}}
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
