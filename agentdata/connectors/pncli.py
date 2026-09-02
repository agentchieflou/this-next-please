"""Run a pncli command, extract its result list, normalize. pncli always emits JSON; we never show it raw by default."""
from __future__ import annotations
import json, subprocess, time
from ..model import AgentTable

JIRA_DEFAULT_FIELDS = ["key", "fields.status.name", "fields.assignee.displayName", "fields.priority.name",
                       "fields.updated", "fields.summary"]
JIRA_RENAME = {"fields.status.name": "status", "fields.assignee.displayName": "assignee",
               "fields.priority.name": "priority", "fields.updated": "updated", "fields.summary": "summary"}
LIST_KEYS = ("issues", "results", "values", "items", "data")


def run(args: list[str], timeout: int = 120) -> tuple[dict | list, float]:
    t0 = time.time()
    p = subprocess.run(["pncli", *args], capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip() or p.stderr.strip()
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"pncli returned non-JSON: {out[:200]}")
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise RuntimeError(payload.get("error") or payload.get("message") or "pncli error")
    return payload, time.time() - t0


def extract_records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                inner = extract_records(payload[k])
                if inner:
                    return inner
        for k in LIST_KEYS:
            if isinstance(payload.get(k), list):
                return payload[k]
        return [payload]
    return []


def jira_search(jql: str, fields: list[str] | None = None, max_results: int = 500) -> AgentTable:
    payload, el = run(["jira", "search", "--jql", jql, "--max-results", str(max_results)])
    recs = extract_records(payload)
    want = fields or JIRA_DEFAULT_FIELDS
    # allow short names
    short = {v: k for k, v in JIRA_RENAME.items()}
    want = [short.get(f, f) for f in want]
    t = AgentTable.from_records(recs, name="jira", source=f"pncli jira search --jql {jql!r}", fields=want, raw=payload)
    t.columns = [JIRA_RENAME.get(c, c.replace("fields.", "")) for c in t.columns]
    t.elapsed_s = el
    t.truncated = len(recs) >= max_results
    return t
