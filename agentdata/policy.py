"""Deterministic format policy. See docs/data-format-policy.md. Agents never choose; this does."""
from __future__ import annotations
import json
import re
from .model import AgentTable
from . import color
from . import metrics
from . import toon
from . import ui

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


def _pretty() -> bool:
    """Query results are TOON even on a terminal: `auto` cannot tell Luna's shell from a person's. Asking for it
    (`AGENTDATA_UI=rich`, or `--pretty`) is the only way a table is drawn instead."""
    return ui.on() and ui.mode() == "rich"


def pretty() -> bool:
    return _pretty()


def _rule_of(text: str, raw: bool) -> int:
    """The rule the rendered text says fired. Read back out rather than threaded through every
    branch, so a new rule cannot be added and silently go unmeasured.

    Rule 1 is the exception and the reason `raw` is a parameter: it returns the payload itself, so
    there is no `rule` in it to read. Everything else names its own rule.
    """
    m = re.search(r'"?rule"?:\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return 1 if raw else 0


def render(t: AgentTable, raw: bool = False, extra: dict | None = None) -> str:
    """Return the exact text to print to the agent's context. `extra` is merged into meta (e.g. warnings)."""
    out = _render(t, raw=raw, extra=extra)
    # Off unless the config says otherwise, and it can never raise. Measured on the finished text
    # because that is what actually reaches the context -- an estimate taken before the sample was
    # cut would be a number about a string nobody ever sees.
    metrics.record(source=t.source, rule=_rule_of(out, raw), shape=t.shape, rows=t.n,
                   cols=len(t.columns), est_tokens=est_tokens(out))
    return out


def _render(t: AgentTable, raw: bool = False, extra: dict | None = None) -> str:
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
        meta = _meta(t, 3, None, extra)
        if _pretty():
            return ui.record_view(dict(zip(t.columns, t.rows[0])), meta)
        return "\n".join([toon.encode(meta, key="meta"), toon.encode(dict(zip(t.columns, t.rows[0])))])

    # rule 4: small table inline
    full = toon.table(t.name, t.columns, t.rows)
    if t.n <= INLINE_ROWS and est_tokens(full) <= INLINE_TOKENS:
        path = t.write_tsv()
        meta = _meta(t, 4, path, extra)
        if _pretty():
            return ui.data_view(t, t.rows, meta)
        return "\n".join([toon.encode(meta, key="meta"), full])

    path = t.write_tsv()
    stats = toon.encode(t.stats(), key="stats")
    # rule 5: medium — header + first 20 + stats
    if t.n <= MEDIUM_ROWS:
        meta = _meta(t, 5, path, {"shown": min(MEDIUM_SAMPLE, t.n), **(extra or {})})
        if _pretty():
            return ui.data_view(t, t.rows[:MEDIUM_SAMPLE], meta, t.stats())
        head = toon.table(t.name, t.columns, t.rows[:MEDIUM_SAMPLE])
        return "\n".join([toon.encode(meta, key="meta"), head, stats])
    # rule 6: large — schema + 10 sample + stats; instruct to script
    meta = _meta(t, 6, path, {"shown": LARGE_SAMPLE, "action": "script over path; do not read file", **(extra or {})})
    if _pretty():
        return ui.data_view(t, t.rows[:LARGE_SAMPLE], meta, t.stats())
    head = toon.table(t.name, t.columns, t.rows[:LARGE_SAMPLE])
    return "\n".join([toon.encode(meta, key="meta"), head, stats])


def render_stream(name: str, source: str, columns: list[str], path: str, n_rows: int,
                  sample: list[list], extra: dict | None = None) -> str:
    """Rule 6 for a result that was streamed to disk and never held in memory.

    A long changelog pull writes its rows through `jira_stream.TsvWriter` as the pages arrive, so by the time
    there is anything to render the rows are gone -- all that is left is the file, the count, and the first ten
    rows the writer kept. This renders that, and it must be indistinguishable from what `render()` emits for a
    materialised table of the same data: same meta keys in the same order, same sample table, same instruction
    to script over the path. A reader that could tell the two apart would be reading the *mechanism* rather than
    the data, and would start treating a large streamed result as somehow less trustworthy than a large one that
    happened to fit in RAM.

    The one honest difference is `stats`. `AgentTable.stats()` walks every value in every column, which is
    exactly the pass over the whole result that streaming exists to avoid, and re-reading the file to compute it
    would be worse. So it is not computed and not silently dropped either: meta says `omitted (streamed)`, and
    this function never opens `path`.
    """
    t = AgentTable(name=name, columns=list(columns), rows=[list(r) for r in sample], source=source)
    meta = _meta(t, 6, path, {"shown": len(t.rows), "action": "script over path; do not read file",
                              "stats": "omitted (streamed)", **(extra or {})})
    meta["rows"] = n_rows            # the file's count, not the sample's; `rows` keeps its position in meta
    if _pretty():
        out = ui.data_view(t, t.rows, meta)
    else:
        out = "\n".join([toon.encode(meta, key="meta"), toon.table(t.name, t.columns, t.rows)])
    metrics.record(source=source, rule=6, shape="table", rows=n_rows, cols=len(t.columns),
                   est_tokens=est_tokens(out))
    return out


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
    out = toon.encode(summary)
    metrics.record(source=source, rule=8, shape="nested", rows=len(records), cols=0,
                   est_tokens=est_tokens(out))
    return out


def error(msg: str, hint: str = "", source: str = "") -> str:
    """The line a human reads when something failed. Colour is off whenever stdout is not a terminal."""
    return toon.encode({"meta": {"ok": color.status("false") if color.enabled() else False, "source": source,
                                 "error": color.paint(msg, "red"), "hint": color.paint(hint, "dim")}})
