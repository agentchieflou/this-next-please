"""Read-only access to a DPM run root: orchestrator.db (SQLite, opened immutable), selection manifests, text_analysis."""
from __future__ import annotations
import glob
import json
import os
import pathlib
import re
import sqlite3
from dataclasses import dataclass

from . import DpmError

HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WINDRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def q(ident: str) -> str:
    """Quote an identifier taken from the binding."""
    return '"' + str(ident).replace('"', '""') + '"'


def norm_version(v) -> str | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v == 0:
        return None
    s = str(v).strip()
    return s or None


class _Placeholders(dict):
    def __missing__(self, key):
        raise DpmError("binding_invalid", f"text_analysis.file uses unknown placeholder {{{key}}}", "allowed: {document_id} {sha256}")


@dataclass
class Selection:
    path: str                 # relative to the run root, '/' separators
    selection_id: str | None
    run_id: str | None
    version: str | None
    items: list
    raw: dict


class Run:
    """One DPM run root. Everything is read-only: the SQLite file is opened `mode=ro&immutable=1` (no lock, no journal,
    no -shm side file), manifests and analysis outputs are read once and cached."""

    def __init__(self, root: str, binding: dict):
        self.root = os.path.abspath(root)
        self.b = binding
        rr = binding["run_root"]
        self.db_path = os.path.join(self.root, rr["orchestrator_db"])
        self.analysis_dir = os.path.join(self.root, rr["text_analysis_dir"])
        self._conn: sqlite3.Connection | None = None
        self._tables: dict[str, list[str]] | None = None
        self._analysis: dict[str, dict | None] = {}
        self._selections: list[Selection] | None = None

    # ---------- locate ----------
    def markers(self) -> dict[str, bool]:
        rr = self.b["run_root"]
        return {rr["orchestrator_db"]: os.path.isfile(self.db_path), rr["text_analysis_dir"] + "/": os.path.isdir(self.analysis_dir)}

    def markers_ok(self) -> bool:
        return all(self.markers().values())

    @classmethod
    def locate(cls, binding: dict, run_root: str | None = None, runs_dir: str | None = None, run_id: str | None = None,
               latest: bool = False) -> "Run":
        db_name = binding["run_root"]["orchestrator_db"]
        if run_root:
            root = run_root
        elif runs_dir:
            if not os.path.isdir(runs_dir):
                raise DpmError("runs_dir_missing", f"runs dir not found: {runs_dir}", "check dpm_runs_dir in AGENTS.md or pass --runs-dir")
            cands = [os.path.join(runs_dir, d) for d in sorted(os.listdir(runs_dir)) if os.path.isdir(os.path.join(runs_dir, d))]
            cands = [c for c in cands if cls(c, binding).markers_ok()]
            if run_id:
                hit = [c for c in cands if os.path.basename(c) == run_id] or [c for c in cands if cls(c, binding).run_id() == run_id]
                if len(hit) != 1:
                    raise DpmError("run_not_found", f"{len(hit)} run roots under {runs_dir} match run id {run_id!r}",
                                   "ad-dpm locate --runs-dir <dir> --latest picks the newest; --run-root <dir> names an exact folder")
                root = hit[0]
            elif latest:
                if not cands:
                    raise DpmError("run_not_found", f"no run root under {runs_dir}", f"a run root holds {db_name} and {binding['run_root']['text_analysis_dir']}/")
                root = max(cands, key=lambda c: os.path.getmtime(os.path.join(c, db_name)))
            else:
                raise DpmError("usage", "pass --run-id <id> or --latest together with --runs-dir", "")
        else:
            raise DpmError("usage", "no run root given",
                           "pass --run-root <dir>, or --runs-dir <dir> with --run-id/--latest, or set dpm_run_root / dpm_runs_dir in AGENTS.md")
        run = cls(root, binding)
        missing = [k for k, ok in run.markers().items() if not ok]
        if not os.path.isdir(run.root) or missing:
            raise DpmError("not_a_run_root", f"{root} is not a DPM run root (missing: {', '.join(missing) or 'directory'})",
                           "a run root holds orchestrator.db and text_analysis/; ad-dpm inspect --run-root <dir> shows what is there; "
                           "if DPM renamed them, bind run_root.* in a dpm_binding file")
        return run

    # ---------- orchestrator.db ----------
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            uri = pathlib.Path(self.db_path).resolve().as_uri() + "?mode=ro&immutable=1"
            try:
                self._conn = sqlite3.connect(uri, uri=True)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
            except sqlite3.Error as e:
                raise DpmError("orchestrator_unreadable", f"cannot read {self.rel(self.db_path)} as SQLite: {e}",
                               "the producer output is damaged or not SQLite; report to DPM, never repair files in the run root")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def tables(self) -> dict[str, list[str]]:
        if self._tables is None:
            out: dict[str, list[str]] = {}
            names = [r[0] for r in self.conn().execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for n in names:
                out[n] = [r[1] for r in self.conn().execute(f"PRAGMA table_info({q(n)})")]
            self._tables = out
        return self._tables

    def has(self, table: str | None, column: str | None = None) -> bool:
        if not table or table not in self.tables():
            return False
        return column is None or column in self.tables()[table]

    def count(self, table: str) -> int:
        return int(self.conn().execute(f"SELECT COUNT(*) FROM {q(table)}").fetchone()[0])

    def user_version(self) -> int:
        return int(self.conn().execute("PRAGMA user_version").fetchone()[0])

    def _last(self, table: str, column: str):
        try:
            row = self.conn().execute(f"SELECT {q(column)} FROM {q(table)} WHERE {q(column)} IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
        except sqlite3.Error:
            row = self.conn().execute(f"SELECT {q(column)} FROM {q(table)} WHERE {q(column)} IS NOT NULL LIMIT 1").fetchone()
        return row[0] if row else None

    def wal_pending(self) -> bool:
        wal = self.db_path + "-wal"
        return os.path.isfile(wal) and os.path.getsize(wal) > 0

    def run_id(self) -> str:
        spec = self.b["run_root"].get("run_id") or {}
        t, c = spec.get("table"), spec.get("column")
        if t and c and self.has(t, c):
            v = self._last(t, c)
            if v is not None and str(v).strip():
                return str(v).strip()
        return os.path.basename(self.root.rstrip("/\\"))

    def versions(self) -> dict:
        spec = self.b["versions"]["orchestrator"]
        out: dict = {"orchestrator_user_version": None, "orchestrator_schema_version": None}
        if spec.get("pragma_user_version"):
            out["orchestrator_user_version"] = self.user_version() or None
        if spec.get("table") and self.has(spec["table"], spec.get("column")):
            out["orchestrator_schema_version"] = norm_version(self._last(spec["table"], spec["column"]))
        return out

    def check_versions(self) -> dict:
        """Refuse (DpmError unsupported_version) unless every observed orchestrator marker is in the supported list."""
        spec = self.b["versions"]["orchestrator"]
        supported = [str(s) for s in spec.get("supported", [])]
        v = self.versions()
        observed = {k: str(x) for k, x in v.items() if x is not None}
        if not observed and spec.get("required", True):
            raise DpmError("unsupported_version", "orchestrator.db carries no schema version marker (PRAGMA user_version is 0 and no "
                           f"{spec.get('table')}.{spec.get('column')} value)", f"agree a marker with the DPM owners; the binding accepts {supported}")
        bad = {k: x for k, x in observed.items() if x not in supported}
        if bad:
            raise DpmError("unsupported_version", f"orchestrator schema version {bad} is not supported ({supported})",
                           "hand off to Michael / the DPM owners with this message; the binding's supported list changes only with their sign-off")
        return v

    def _check_version(self, ver: str | None, spec: dict, what: str) -> None:
        supported = [str(s) for s in spec.get("supported", [])]
        if ver is None:
            if spec.get("required", True):
                raise DpmError("unsupported_version", f"{what} has no {spec['key']!r} key",
                               f"the producer must stamp {spec['key']} (accepted: {supported}); never add it to the run root yourself")
            return
        if ver not in supported:
            raise DpmError("unsupported_version", f"{what}: {spec['key']} {ver!r} is not supported ({supported})",
                           "hand off to Michael / the DPM owners with this message; the binding's supported list changes only with their sign-off")

    def canonical_documents(self) -> list[dict]:
        """Rows of the canonical manifest keyed by concept name (document_id, loan_id, sha256, ...), plus `_rowid`."""
        c = self.b["canonical"]
        t, cols, optional = c["table"], c["columns"], set(c.get("optional_columns", []))
        if not self.has(t):
            raise DpmError("binding_mismatch", f"orchestrator.db has no table {t!r} (the canonical document manifest)",
                           "ad-dpm inspect lists the tables; bind canonical.table in a dpm_binding file")
        present = set(self.tables()[t])
        missing = [k for k, col in cols.items() if col not in present and k not in optional]
        if missing:
            raise DpmError("binding_mismatch", f"table {t!r} lacks bound columns: " + ", ".join(f"{k}->{cols[k]}" for k in missing),
                           "ad-dpm inspect shows candidate columns; bind canonical.columns.<concept> in a dpm_binding file")
        sel = [k for k, col in cols.items() if col in present]
        body = ", ".join(f"{q(cols[k])} AS {q(k)}" for k in sel) + f" FROM {q(t)}"
        try:
            rows = self.conn().execute("SELECT rowid AS _rowid, " + body).fetchall()
        except sqlite3.Error:
            rows = self.conn().execute("SELECT NULL AS _rowid, " + body).fetchall()
        return [dict(r) for r in rows]

    def pages_by_document(self) -> dict[str, set[int]] | None:
        p = self.b.get("pages") or {}
        t, cols = p.get("table"), p.get("columns", {})
        if not (t and self.has(t, cols.get("document_id")) and self.has(t, cols.get("page_number"))):
            if p.get("required"):
                raise DpmError("binding_mismatch", f"pages table {t!r} with columns {cols} not found", "ad-dpm inspect; bind pages.* or set pages.required false")
            return None
        out: dict[str, set[int]] = {}
        for r in self.conn().execute(f"SELECT {q(cols['document_id'])}, {q(cols['page_number'])} FROM {q(t)}"):
            try:
                out.setdefault(str(r[0]), set()).add(int(r[1]))
            except (TypeError, ValueError):
                continue
        return out

    def allowed_channels(self) -> tuple[set[str] | None, str]:
        ch = self.b["channels"]
        if ch.get("allowed"):
            return {str(x) for x in ch["allowed"]}, "binding"
        t, c = ch.get("table"), ch.get("column")
        if t and c and self.has(t, c):
            return {str(r[0]) for r in self.conn().execute(f"SELECT DISTINCT {q(c)} FROM {q(t)} WHERE {q(c)} IS NOT NULL")}, f"table {t}"
        return None, "unconstrained"

    # ---------- files ----------
    def resolve(self, p: str) -> str:
        p = os.path.expanduser(str(p))
        if os.path.isabs(p) or _WINDRIVE.match(p):
            return os.path.normpath(p)
        return os.path.normpath(os.path.join(self.root, p))

    def rel(self, p: str) -> str:
        a = os.path.abspath(p)
        try:
            r = os.path.relpath(a, self.root)
        except ValueError:  # another drive on Windows
            return a.replace("\\", "/")
        return a.replace("\\", "/") if r.startswith("..") else r.replace("\\", "/")

    def _json(self, p: str, what: str):
        try:
            with open(p, encoding="utf-8-sig") as f:
                return json.load(f)
        except ValueError as e:
            raise DpmError("manifest_invalid", f"{self.rel(p)}: {what} is not valid JSON ({e})",
                           "the producer output is damaged; report to DPM, never repair files in the run root")
        except OSError as e:
            raise DpmError("manifest_invalid", f"{self.rel(p)}: cannot read {what} ({e})", "")

    def selection_paths(self) -> list[str]:
        found: set[str] = set()
        for pat in self.b["run_root"]["selection_manifests"]:
            for p in glob.glob(os.path.join(self.root, pat)):
                if os.path.isfile(p) and not p.startswith(self.analysis_dir + os.sep):
                    found.add(os.path.abspath(p))
        return sorted(found)

    def selections(self) -> list[Selection]:
        if self._selections is None:
            k, vs = self.b["selection"]["keys"], self.b["versions"]["selection_manifest"]
            out: list[Selection] = []
            for p in self.selection_paths():
                rel = self.rel(p)
                data = self._json(p, "selection manifest")
                if not isinstance(data, dict):
                    raise DpmError("manifest_invalid", f"{rel}: top level must be an object", "")
                ver = norm_version(data.get(vs["key"]))
                self._check_version(ver, vs, f"selection manifest {rel}")
                items = data.get(k["items"])
                items = [] if items is None else items
                if not isinstance(items, list):
                    raise DpmError("manifest_invalid", f"{rel}: {k['items']!r} must be a list", "")
                sid, rid = data.get(k["selection_id"]), data.get(k["run_id"])
                out.append(Selection(rel, None if sid is None else str(sid), None if rid is None else str(rid), ver, items, data))
            self._selections = out
        return self._selections

    def analysis_rel(self, document_id, sha256) -> str:
        name = self.b["text_analysis"]["file"].format_map(_Placeholders(document_id=document_id or "", sha256=sha256 or ""))
        return (self.b["run_root"]["text_analysis_dir"] + "/" + name).replace("\\", "/")

    def analysis(self, document_id, sha256) -> dict | None:
        """The text_analysis output for a document, or None when absent. Refuses unsupported versions."""
        rel = self.analysis_rel(document_id, sha256)
        if rel not in self._analysis:
            p = os.path.join(self.root, rel)
            if not os.path.isfile(p):
                self._analysis[rel] = None
            else:
                data = self._json(p, "text_analysis output")
                if not isinstance(data, dict):
                    raise DpmError("manifest_invalid", f"{rel}: top level must be an object", "")
                vs = self.b["versions"]["text_analysis"]
                self._check_version(norm_version(data.get(vs["key"])), vs, f"text_analysis {rel}")
                self._analysis[rel] = data
        return self._analysis[rel]

    def analysis_versions(self) -> list[str]:
        key = self.b["versions"]["text_analysis"]["key"]
        return sorted({v for v in (norm_version(d.get(key)) for d in self._analysis.values() if d) if v})
