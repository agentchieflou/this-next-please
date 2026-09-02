from __future__ import annotations
import csv, json, os, time, uuid
from dataclasses import dataclass, field
from typing import Any

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
        return p.replace("\\", "/")

    def write_json(self) -> str:
        p = self._path("json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.raw if self.raw is not None else self.to_records(), f, default=str)
        return p.replace("\\", "/")

    @staticmethod
    def read_tsv(path: str, name="result") -> "AgentTable":
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.reader(f, delimiter="\t")
            cols = next(r)
            rows = [[_coerce(v) for v in row] for row in r]
        return AgentTable(name=name, columns=cols, rows=rows, source=path)

    def to_records(self) -> list[dict]:
        return [dict(zip(self.columns, r)) for r in self.rows]


def _coerce(v: str):
    if v == "":
        return None
    for t in (int, float):
        try:
            return t(v)
        except ValueError:
            pass
    return v
