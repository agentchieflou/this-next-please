"""Deterministic format policy. See docs/data-format-policy.md. Agents never choose; this does."""
from __future__ import annotations
import json
from .model import AgentTable
from . import toon

INLINE_ROWS, INLINE_TOKENS = 50, 1500
MEDIUM_ROWS, MEDIUM_SAMPLE = 500, 20
LARGE_SAMPLE = 10
RAW_TOKENS = 300


def est_tokens(s: str) -> int:
    return int(len(s) / 3.5) + 1


def _meta(t: AgentTable, rule: int, path: str | None, extra: dict | None = None) -> dict:
    m = {"ok": True, "rule": rule, "source": t.source, "rows": t.n, "cols": len(t.columns),
         "truncated": t.truncated, "elapsed_s": round(t.elapsed_s, 2)}
    if path:
        m["path"] = path
    if extra:
        m.update(extra)
    return m


def render(t: AgentTable, raw: bool = False, extra: dict | None = None) -> str:
    """Return the exact text to print to the agent's context. `extra` is merged into meta (e.g. warnings)."""
    # rules 1-2: raw JSON for debugging
    if raw:
        payload = t.raw if t.raw is not None else t.to_records()
        js = json.dumps(payload, default=str, separators=(",", ":"))
        if est_tokens(js) <= RAW_TOKENS:
            return js
        path = t.write_json()
        keys = list(payload.keys()) if isinstance(payload, dict) else ["<list>"]
        return json.dumps({"ok": True, "rule": 2, "path": path, "top_keys": keys,
                           "len": len(payload) if hasattr(payload, "__len__") else None})

    # rule 3: scalar / small record
    if t.shape in ("scalar", "record") and len(t.columns) <= 20:
        body = toon.encode(dict(zip(t.columns, t.rows[0])))
        return "\n".join([toon.encode(_meta(t, 3, None, extra), key="meta"), body])

    # rule 4: small table inline
    full = toon.table(t.name, t.columns, t.rows)
    if t.n <= INLINE_ROWS and est_tokens(full) <= INLINE_TOKENS:
        path = t.write_tsv()
        return "\n".join([toon.encode(_meta(t, 4, path, extra), key="meta"), full])

    path = t.write_tsv()
    stats = toon.encode(t.stats(), key="stats")
    # rule 5: medium — header + first 20 + stats
    if t.n <= MEDIUM_ROWS:
        head = toon.table(t.name, t.columns, t.rows[:MEDIUM_SAMPLE])
        return "\n".join([toon.encode(_meta(t, 5, path, {"shown": min(MEDIUM_SAMPLE, t.n), **(extra or {})}), key="meta"), head, stats])
    # rule 6: large — schema + 10 sample + stats; instruct to script
    head = toon.table(t.name, t.columns, t.rows[:LARGE_SAMPLE])
    meta = _meta(t, 6, path, {"shown": LARGE_SAMPLE, "action": "script over path; do not read file", **(extra or {})})
    return "\n".join([toon.encode(meta, key="meta"), head, stats])


def render_nested(records: list, name: str, source: str, raw_payload) -> str:
    """Rules 7-8 for JSON payloads that are not obviously tabular."""
    if AgentTable.flatten_ok(records):
        return render(AgentTable.from_records(records, name=name, source=source, raw=raw_payload))
    t = AgentTable(name=name, columns=[], rows=[], source=source, raw=raw_payload)
    path = t.write_json()
    sample = records[0] if records else {}
    summary = {"meta": {"ok": True, "rule": 8, "source": source, "records": len(records), "path": path},
               "top_keys": list(sample.keys()) if isinstance(sample, dict) else [],
               "sample": sample}
    return toon.encode(summary)


def error(msg: str, hint: str = "", source: str = "") -> str:
    return toon.encode({"meta": {"ok": False, "source": source, "error": msg, "hint": hint}})
