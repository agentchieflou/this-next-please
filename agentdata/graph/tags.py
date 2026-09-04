"""Tag definitions and classification rules for graph nodes."""
from __future__ import annotations
from typing import Any

# Standard I/O functions and module call patterns
IO_CALL_NAMES = {
    # File / OS
    "open",
    "read",
    "write",
    "load",
    "dump",
    "loads",
    "dumps",
    # Subprocess / Process
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.call",
    "os.system",
    "os.popen",
    "proc.run",
    # Socket / Network
    "socket.socket",
    "socket.create_connection",
    # HTTP
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "requests.request",
    "httpx.get",
    "httpx.post",
    "urllib.request.urlopen",
    # DB
    "sqlite3.connect",
    "connect",
    "cursor",
    "execute",
    "executemany",
    "pyodbc.connect",
    "teradatasql.connect",
}

IO_MODULE_PREFIXES = (
    "subprocess.",
    "socket.",
    "sqlite3.",
    "requests.",
    "httpx.",
    "urllib.",
    "pyodbc.",
    "teradatasql.",
)


def is_io_call(call_name: str) -> bool:
    """Checks if a called symbol represents an I/O operation."""
    if call_name in IO_CALL_NAMES:
        return True
    if any(call_name.startswith(pfx) for pfx in IO_MODULE_PREFIXES):
        return True
    # Strip object qualifiers: e.g. self.cursor.execute -> execute
    leaf = call_name.split(".")[-1]
    if leaf in ("open", "connect", "cursor", "execute", "executemany"):
        return True
    return False
