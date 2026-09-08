"""Model (TMDL) + report (PBIR) -> one normalized dict, plus the index the validator resolves against."""
from __future__ import annotations
import datetime as _dt
import glob
import os
import re
from dataclasses import dataclass, field
from typing import Any

from . import pbir as P
from . import tmdl as T
from .. import textio

_DAX_QUALIFIED = re.compile(r"'((?:[^']|'')+)'\[([^\]]+)\]|(?<![\w'\]])([A-Za-z_][\w]*)\[([^\]]+)\]")
_DAX_BARE = re.compile(r"(?<![\w'\]\)])\[([^\]]+)\]")
_M_SOURCES = [
    re.compile(r'Item\s*=\s*"([^"]+)"'), re.compile(r'Name\s*=\s*"([^"]+)"'),
    re.compile(r'(?:FROM|JOIN)\s+([A-Za-z_][\w$]*\.[A-Za-z_][\w$]*)', re.I),
]
_M_CONNECTORS = re.compile(r"\b(Teradata\.Database|Sql\.Database|Oracle\.Database|Odbc\.DataSource|Odbc\.Query|Impala\.Database|Hive\.Database|Value\.NativeQuery|Csv\.Document|Excel\.Workbook|SharePoint\.Files|Web\.Contents|Snowflake\.Databases|Databricks\.Catalogs)\b")


@dataclass
class Model:
    definition_dir: str
    files: dict[str, T.TmdlFile]
    name: str | None = None
    tables: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    expressions: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    perspectives: list[str] = field(default_factory=list)
    cultures: list[str] = field(default_factory=list)
    refs: dict[str, list[str]] = field(default_factory=dict)  # refType -> names from model.tmdl
    lint: list[T.Finding] = field(default_factory=list)
    compatibility: str | None = None


class ModelIndex:
    """Fast lookups for the validator: tables -> columns / measures / hierarchies; report-extension measures included."""

    def __init__(self, model: Model, report: P.Report | None = None):
        self.tables: dict[str, dict] = {}
        self.measure_table: dict[str, str] = {}
        self.level_column: dict[tuple, str] = {}
        for t in model.tables:
            for h in t["hierarchies"]:
                for lv in h["levels"]:
                    if lv["column"]:
                        self.level_column[(t["name"], h["name"], lv["name"])] = lv["column"]
            self.tables[t["name"]] = {"columns": {c["name"] for c in t["columns"]}, "measures": {m["name"] for m in t["measures"]},
                                      "hierarchies": {h["name"]: {lv["name"] for lv in h["levels"]} for h in t["hierarchies"]},
                                      "hidden_columns": {c["name"] for c in t["columns"] if c["hidden"]}}
            for m in t["measures"]:
                self.measure_table.setdefault(m["name"], t["name"])
        if report:
            for em in report.extension_measures:
                self.tables.setdefault(em["entity"], {"columns": set(), "measures": set(), "hierarchies": {}, "hidden_columns": set()})
                self.tables[em["entity"]]["measures"].add(em["name"])
                self.measure_table.setdefault(em["name"], em["entity"])

    def resolve(self, ref: P.FieldRef) -> tuple[bool, str]:
        if not ref.entity:
            return True, "non-model source"  # presentation objects / expression tables are out of scope
        t = self.tables.get(ref.entity)
        if t is None:
            return False, f"table '{ref.entity}' not in model"
        if ref.kind == "column":
            return (True, "ok") if ref.prop in t["columns"] else (False, f"column '{ref.entity}'[{ref.prop}] not in model")
        if ref.kind == "measure":
            if ref.prop in t["measures"]:
                return True, "ok"
            owner = self.measure_table.get(ref.prop)
            return (False, f"measure [{ref.prop}] lives in table '{owner}', not '{ref.entity}'") if owner else (False, f"measure '{ref.entity}'[{ref.prop}] not in model")
        if ref.kind == "hierarchy":
            return (True, "ok") if ref.prop in t["hierarchies"] else (False, f"hierarchy '{ref.entity}'[{ref.prop}] not in model")
        if ref.kind == "level":
            levels = t["hierarchies"].get(ref.hierarchy or "", set())
            if ref.hierarchy not in t["hierarchies"]:
                return False, f"hierarchy '{ref.entity}'[{ref.hierarchy}] not in model"
            return (True, "ok") if ref.prop in levels else (False, f"level {ref.prop} not in hierarchy '{ref.entity}'[{ref.hierarchy}]")
        return True, "unknown ref kind"


# ---------- model ----------
def find_model_dir(pbip_dir: str, report: P.Report | None = None) -> str:
    cands = []
    if report and report.dataset_path:
        cands.append(os.path.join(report.dataset_path, "definition"))
    base = pbip_dir if os.path.isdir(pbip_dir) else os.path.dirname(pbip_dir)
    cands += [os.path.join(d, "definition") for d in sorted(glob.glob(os.path.join(base, "*.SemanticModel")))]
    if os.path.exists(os.path.join(base, "model.tmdl")):
        cands.append(base)
    for c in cands:
        if os.path.exists(os.path.join(c, "model.tmdl")):
            return c
    raise FileNotFoundError(f"no TMDL definition folder (model.tmdl) found for {pbip_dir}")


def load_model(definition_dir: str) -> Model:
    files = T.read_model(definition_dir)
    m = Model(definition_dir, files)
    for path, tf in files.items():
        m.lint.extend(T.lint_file(tf))
        rel = textio.norm_path(os.path.relpath(path, definition_dir))
        for node in tf.nodes:
            if node.kind == "table":
                m.tables.append(_table(node, rel))
            elif node.kind == "relationship":
                ft, fc = T.split_ref(str(node.props.get("fromColumn", "")))
                tt, tc = T.split_ref(str(node.props.get("toColumn", "")))
                m.relationships.append({"name": node.name, "fromTable": ft, "fromColumn": fc, "toTable": tt, "toColumn": tc,
                                        "active": str(node.props.get("isActive", "true")).lower() != "false",
                                        "crossFilter": node.props.get("crossFilteringBehavior", "oneDirection"), "file": rel, "line": node.line_start})
            elif node.kind == "expression":
                m.expressions.append({"name": node.name, "kind": node.props.get("kind") or "m", "file": rel})
            elif node.kind == "role":
                m.roles.append(node.name)
            elif node.kind == "perspective":
                m.perspectives.append(node.name)
            elif node.kind in ("cultureInfo", "culture"):
                m.cultures.append(node.name)
            elif node.kind == "model":
                m.name = node.name
            elif node.kind == "database":
                m.compatibility = str(node.props.get("compatibilityLevel", "")) or None
            elif node.kind == "ref":
                m.refs.setdefault(node.props.get("refType", ""), []).append(node.name)
    m.tables.sort(key=lambda t: t["name"].lower())
    return m


def _table(node: T.Node, rel: str) -> dict:
    cols, measures, hiers, parts = [], [], [], []
    for c in node.children:
        if c.kind == "column":
            cols.append({"name": c.name, "dataType": c.props.get("dataType"), "kind": "calculated" if c.expr else "data",
                         "sourceColumn": c.props.get("sourceColumn"), "expression": c.expr, "hidden": c.props.get("isHidden") is True,
                         "formatString": c.props.get("formatString"), "summarizeBy": c.props.get("summarizeBy"),
                         "sortByColumn": T.unquote(str(c.props["sortByColumn"])) if c.props.get("sortByColumn") else None,
                         "lineageTag": c.props.get("lineageTag"), "line": c.line_start})
        elif c.kind == "measure":
            measures.append({"name": c.name, "expression": c.expr or "", "formatString": c.props.get("formatString"),
                             "displayFolder": c.props.get("displayFolder"), "hidden": c.props.get("isHidden") is True,
                             "lineageTag": c.props.get("lineageTag"), "description": " ".join(c.desc) if c.desc else None,
                             "deps": measure_deps(c.expr or ""), "line": c.line_start})
        elif c.kind == "hierarchy":
            hiers.append({"name": c.name, "levels": [{"name": lv.name, "column": T.unquote(str(lv.props.get("column", ""))) or None}
                                                     for lv in c.children if lv.kind == "level"], "line": c.line_start})
        elif c.kind == "partition":
            src = c.props.get("source")
            src_text = src if isinstance(src, str) else ""
            parts.append({"name": c.name, "kind": c.expr or "", "mode": c.props.get("mode"), "connector": _connector(src_text),
                          "sources": partition_sources(src_text), "line": c.line_start})
    return {"name": node.name, "hidden": node.props.get("isHidden") is True, "file": rel, "line": node.line_start,
            "description": " ".join(node.desc) if node.desc else None, "lineageTag": node.props.get("lineageTag"),
            "columns": cols, "measures": measures, "hierarchies": hiers, "partitions": parts}


def measure_deps(expr: str) -> dict:
    cols, meas = [], []
    for m in _DAX_QUALIFIED.finditer(expr):
        t = (m.group(1) or m.group(3) or "").replace("''", "'")
        c = m.group(2) or m.group(4)
        lab = f"'{t}'[{c}]"
        if lab not in cols:
            cols.append(lab)
    for m in _DAX_BARE.finditer(expr):
        lab = m.group(1)
        if lab not in meas:
            meas.append(lab)
    return {"columns": cols, "measures": meas}


def _connector(m_text: str) -> str | None:
    m = _M_CONNECTORS.search(m_text or "")
    return m.group(1) if m else None


def partition_sources(m_text: str) -> list[str]:
    out: list[str] = []
    for rx in _M_SOURCES:
        for m in rx.finditer(m_text or ""):
            v = m.group(1)
            if v and v not in out and not v.lower().startswith(("http", "select")):
                out.append(v)
    return out


# ---------- normalized dict ----------
def normalize(model: Model, report: P.Report | None, pbip_dir: str) -> dict:
    norm: dict[str, Any] = {"generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "pbip": {"dir": textio.norm_path(pbip_dir), "model_dir": textio.norm_path(model.definition_dir),
                                     "report_dir": textio.norm_path(report.root) if report else None}}
    norm["model"] = {"name": model.name, "compatibility": model.compatibility, "tables": model.tables,
                     "relationships": model.relationships, "expressions": model.expressions, "roles": model.roles,
                     "perspectives": model.perspectives, "cultures": model.cultures}
    usage: dict[str, list[dict]] = {}
    rep: dict[str, Any] | None = None
    if report:
        pages = []
        for p in report.pages:
            visuals = []
            for v in p.visuals:
                fields = [{"kind": r.kind, "entity": r.entity, "prop": r.prop, "hierarchy": r.hierarchy, "agg": r.agg,
                           "context": r.context, "label": r.label()} for r in v.fields]
                for r in v.fields:
                    if r.entity:
                        usage.setdefault(r.label() if not r.agg else f"'{r.entity}'[{r.prop}]", []).append(
                            {"page": p.name, "visual": v.id, "title": v.title, "type": v.type, "context": r.context})
                visuals.append({"id": v.id, "type": v.type, "title": v.title, "hidden": v.hidden, "file": v.file, "fields": fields,
                                "filters": [{"name": f["name"], "type": f["type"], "field": f["field"]} for f in v.filters]})
            pages.append({"id": p.id, "name": p.name, "ordinal": p.ordinal, "hidden": p.hidden, "file": p.file, "visuals": visuals,
                          "filters": [{"name": f["name"], "type": f["type"], "field": f["field"]} for f in p.filters]})
        rep = {"legacy": report.legacy, "version": report.version, "dataset_path": report.dataset_path,
               "dataset_connection": report.dataset_connection, "pages": pages,
               "filters": [{"name": f["name"], "type": f["type"], "field": f["field"]} for f in report.filters],
               "bookmarks": report.bookmarks, "extension_measures": report.extension_measures}
    norm["report"] = rep
    measure_usage: dict[str, list[str]] = {}
    for t in model.tables:
        for m in t["measures"]:
            for dep in m["deps"]["measures"]:
                measure_usage.setdefault(f"[{dep}]", []).append(f"'{t['name']}'[{m['name']}]")
            for dep in m["deps"]["columns"]:
                measure_usage.setdefault(dep, []).append(f"'{t['name']}'[{m['name']}]")
    sources = {t["name"]: sorted({s for p in t["partitions"] for s in p["sources"]}) for t in model.tables}
    norm["lineage"] = {"field_usage": dict(sorted(usage.items())), "measure_usage": dict(sorted(measure_usage.items())),
                       "sources": sources}
    return norm


def load_all(pbip_dir: str, legacy_ok: bool = True) -> tuple[Model, P.Report | None, dict]:
    report = None
    try:
        report = P.load_report(pbip_dir, allow_legacy=legacy_ok)
    except FileNotFoundError:
        report = None
    model = load_model(find_model_dir(pbip_dir, report))
    return model, report, normalize(model, report, pbip_dir)


def source_files(model: Model, report: P.Report | None) -> list[str]:
    files = list(model.files)
    if report:
        for root, _d, fs in os.walk(report.root):
            for f in fs:
                if f.endswith((".json", ".pbir")) and "localSettings" not in f:
                    files.append(os.path.join(root, f))
    return sorted(files)
