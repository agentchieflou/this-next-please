from __future__ import annotations
import csv, io, json, os, time, uuid
from dataclasses import dataclass, field
from .textio import read_text
from typing import Any
from . import textio

OUT_DIR = os.environ.get("AGENTDATA_OUT", os.path.join(".agent", "out"))


def _flatten(obj: Any, prefix: str = "", depth: int = 0, max_depth: int = 2) -> dict:
    """Dot-path flatten to max_depth. Lists of scalars -> ';'-joined string; lists of dicts -> count."""
    out: dict = {}
    if not isinstance(obj, dict):
        return {prefix or "value": obj}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict) and depth < max_depth:
            out.update(_flatten(v, key, depth + 1, max_depth))
        elif isinstance(v, list):
            if all(not isinstance(x, (dict, list)) for x in v):
                out[key] = ";".join("" if x is None else str(x) for x in v)
            else:
                out[key + "_count"] = len(v)
        elif isinstance(v, dict):
            out[key] = json.dumps(v, separators=(",", ":"))
        else:
            out[key] = v
    return out


@dataclass
class AgentTable:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    source: str = ""
    truncated: bool = False
    elapsed_s: float = 0.0
    run_id: str = field(default_factory=lambda: time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4])
    raw: Any = None  # original payload for --raw / nested fallback

    # ---------- construction ----------
    @classmethod
    def from_records(cls, records: list[dict], name="result", source="", fields: list[str] | None = None,
                     raw: Any = None) -> "AgentTable":
        flat = [_flatten(r) for r in records]
        if fields:
            cols = fields
        else:
            seen: dict[str, int] = {}
            for r in flat:
                for k in r:
                    seen[k] = seen.get(k, 0) + 1
            cols = list(seen)
        rows = [[r.get(c) for c in cols] for r in flat]
        return cls(name=name, columns=cols, rows=rows, source=source, raw=raw)

    @staticmethod
    def flatten_ok(records: list[dict], threshold: float = 0.8) -> bool:
        if not records:
            return True
        flat = [_flatten(r) for r in records]
        keysets = [set(f) for f in flat]
        union = set().union(*keysets)
        if not union:
            return True
        shared = sum(1 for k in union if sum(k in ks for ks in keysets) / len(keysets) >= threshold)
        return shared / len(union) >= threshold

    # ---------- properties ----------
    @property
    def n(self) -> int:
        return len(self.rows)

    @property
    def shape(self) -> str:
        if self.n == 1 and len(self.columns) == 1:
            return "scalar"
        if self.n == 1:
            return "record"
        return "table"

    def head(self, k: int) -> "AgentTable":
        return AgentTable(self.name, self.columns, self.rows[:k], self.source, self.truncated, self.elapsed_s, self.run_id)

    def stats(self) -> dict:
        out = {}
        for i, c in enumerate(self.columns):
            col = [r[i] for r in self.rows]
            nn = [v for v in col if v is not None and v != ""]
            s = {"nulls": len(col) - len(nn), "distinct": len(set(map(str, nn)))}
            nums = [v for v in nn if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums and len(nums) == len(nn):
                s["min"], s["max"] = min(nums), max(nums)
            elif nn and all(isinstance(v, str) and len(v) >= 10 and v[4] == "-" for v in nn[:20]):
                s["min"], s["max"] = min(nn), max(nn)  # ISO-ish dates sort lexically
            out[c] = s
        return out

    # ---------- persistence ----------
    def _path(self, ext: str) -> str:
        os.makedirs(OUT_DIR, exist_ok=True)
        return os.path.join(OUT_DIR, f"{self.run_id}_{self.name}.{ext}")

    def write_tsv(self) -> str:
        p = self._path("tsv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(self.columns)
            for r in self.rows:
                w.writerow(["" if v is None else v for v in r])
        return textio.norm_path(p)

    def write_json(self) -> str:
        p = self._path("json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.raw if self.raw is not None else self.to_records(), f, default=str)
        return textio.norm_path(p)

    @staticmethod
    def read_tsv(path: str, name="result") -> "AgentTable":
        r = csv.reader(io.StringIO(read_text(path), newline=""), delimiter="\t")
        # An empty file has no header row. `next(r)` raised StopIteration, which reached the caller
        # as a traceback rather than as a row saying the file is empty -- and a 0-byte TSV is a
        # perfectly ordinary thing to be handed by a query that matched nothing.
        cols = next(r, None)
        if cols is None:
            return AgentTable(name=name, columns=[], rows=[], source=path)
        rows = [[_coerce(v) for v in row] for row in r]
        return AgentTable(name=name, columns=cols, rows=rows, source=path)

    def to_records(self) -> list[dict]:
        return [dict(zip(self.columns, r)) for r in self.rows]


def _coerce(v: str):
    """Text from a TSV or a tool's stdout, as a number **only when that loses nothing**.

    The round-trip rule is the whole of it: if writing the number back would not reproduce the
    text, the text was not a number, it was an identifier that happens to be digits. This matters
    here more than in most places -- the values passing through are cost centres, account numbers,
    Jira keys and DAX results:

        "007"    was becoming 7        -- a zero-padded code, silently renumbered
        "1_000"  was becoming 1000     -- Python allows underscores in int literals; nothing else does
        "+5"     was becoming 5
        " 5"     was becoming 5        -- and the padding a fixed-width extract relied on was gone

    `"1.50"` now stays text for the same reason: it is a formatting the source chose, and a caller
    that wants a float from it can say so. Found by `tests/test_props_toon.py`, which has asserted
    this round trip since #75 while the code did not honour it.
    """
    if v == "":
        return None
    for t in (int, float):
        try:
            n = t(v)
        except ValueError:
            continue
        if str(n) == v:
            return n
    return v
