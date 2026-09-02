"""PBIR (enhanced report format) loader + field-reference extraction.

Verified against Microsoft's report-definition JSON schemas: every field reference is a QueryExpressionContainer with
exactly one expression key (Column, Measure, Aggregation, Hierarchy, HierarchyLevel, PropertyVariationSource, ...).
SourceRef comes in two forms: standalone {"SourceRef": {"Entity": "Table"}} in field/projection positions, and the
alias form {"SourceRef": {"Source": "s"}} inside filter.Where / prototypeQuery, where `s` names an entry of the
sibling `From[]` list ({Name, Entity, Type}; only Type 0 is a model table). Conditional-formatting values are untyped
in the schema, so the walk is recursive over every JSON file; fixed anchors only classify (role, filter, sort, format).
Legacy single-file report.json is loaded best-effort behind allow_legacy.
"""
from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

REF_KEYS = ("Column", "Measure", "Aggregation", "Hierarchy", "HierarchyLevel", "PropertyVariationSource", "Min", "Max", "Percentile")
AGG = {0: "Sum", 1: "Avg", 2: "DistinctCount", 3: "Min", 4: "Max", 5: "Count", 6: "Median", 7: "StdDev", 8: "Var"}
HEX20 = re.compile(r"^[0-9a-f]{20}$")
FILTER_NAME = re.compile(r"^Filter[0-9a-f]{24}$")


@dataclass
class FieldRef:
    kind: str            # column | measure | hierarchy | level
    entity: str | None
    prop: str | None      # column/measure name, hierarchy name, or level name
    hierarchy: str | None = None
    agg: str | None = None
    context: str = "other"  # projection:<Role> | filter | sort | format | other
    file: str = ""
    path: str = ""

    def label(self) -> str:
        base = f"'{self.entity}'[{self.prop}]" if self.entity else f"[{self.prop}]"
        return f"{self.agg}({base})" if self.agg else base


@dataclass
class Visual:
    page_id: str
    page_name: str
    id: str
    type: str | None
    title: str | None
    hidden: bool
    file: str
    fields: list[FieldRef] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    schema: str | None = None


@dataclass
class Page:
    id: str
    name: str
    ordinal: int
    file: str
    hidden: bool = False
    visuals: list[Visual] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)


@dataclass
class Report:
    root: str                 # the *.Report folder
    legacy: bool
    pages: list[Page] = field(default_factory=list)
    filters: list[dict] = field(default_factory=list)
    bookmarks: list[dict] = field(default_factory=list)
    extension_measures: list[dict] = field(default_factory=list)   # {entity, name, expression}
    dataset_path: str | None = None
    dataset_connection: str | None = None
    version: str | None = None
    findings: list[dict] = field(default_factory=list)

    def all_visuals(self) -> Iterator[Visual]:
        for p in self.pages:
            yield from p.visuals

    def all_refs(self) -> Iterator[tuple[Visual | None, FieldRef]]:
        for v in self.all_visuals():
            for r in v.fields:
                yield v, r


# ---------- io ----------
def _load(path: str) -> Any:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace("\\", "/")


# ---------- reference walk ----------
def walk_refs(obj: Any, file: str = "", path: str = "$", aliases: dict | None = None, context: str = "other") -> Iterator[FieldRef]:
    """Yield every model reference under obj. `aliases` maps From[].Name -> (Entity, Type) for the enclosing query."""
    aliases = dict(aliases or {})
    if isinstance(obj, dict):
        if isinstance(obj.get("From"), list):
            for src in obj["From"]:
                if isinstance(src, dict) and src.get("Name"):
                    aliases[src["Name"]] = (src.get("Entity"), src.get("Type", 0))
        keys = [k for k in REF_KEYS if k in obj]
        if len(keys) == 1 and isinstance(obj[keys[0]], dict):
            ref = _decode(keys[0], obj[keys[0]], aliases)
            if ref is not None:
                ref.file, ref.path, ref.context = file, path, context
                yield ref
                return  # do not descend into a decoded reference
        for k, v in obj.items():
            ctx = context
            if k == "queryState" and isinstance(v, dict):
                for role, state in v.items():
                    yield from walk_refs(state, file, f"{path}.queryState.{role}", aliases, f"projection:{role}")
                continue
            if k in ("filterConfig", "filters") and context == "other":
                ctx = "filter"
            elif k == "sortDefinition":
                ctx = "sort"
            elif k in ("objects", "visualContainerObjects") and context in ("other",):
                ctx = "format"
            yield from walk_refs(v, file, f"{path}.{k}", aliases, ctx)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_refs(v, file, f"{path}[{i}]", aliases, context)


def _source_entity(expr: Any, aliases: dict) -> str | None:
    """Resolve the SourceRef at the bottom of an expression to a table name (None for non-model sources)."""
    cur = expr
    for _ in range(6):
        if not isinstance(cur, dict):
            return None
        if "SourceRef" in cur:
            sr = cur["SourceRef"] or {}
            if sr.get("Entity"):
                return sr["Entity"]
            if sr.get("Source") in aliases:
                ent, typ = aliases[sr["Source"]]
                return ent if typ in (0, None) else None
            return None
        if "Expression" in cur:
            cur = cur["Expression"]
        elif "Hierarchy" in cur and isinstance(cur["Hierarchy"], dict):
            cur = cur["Hierarchy"]
        else:
            return None
    return None


def _decode(kind: str, body: dict, aliases: dict) -> FieldRef | None:
    if kind == "Column":
        return FieldRef("column", _source_entity(body.get("Expression"), aliases), body.get("Property"))
    if kind == "Measure":
        return FieldRef("measure", _source_entity(body.get("Expression"), aliases), body.get("Property"))
    if kind == "Hierarchy":
        return FieldRef("hierarchy", _source_entity(body.get("Expression"), aliases), body.get("Hierarchy"))
    if kind == "HierarchyLevel":
        h = body.get("Expression") or {}
        hier = (h.get("Hierarchy") or {}) if isinstance(h, dict) else {}
        ent = _source_entity(hier.get("Expression") if hier else h, aliases)
        return FieldRef("level", ent, body.get("Level"), hierarchy=hier.get("Hierarchy") if hier else None)
    if kind == "PropertyVariationSource":
        return FieldRef("column", _source_entity(body.get("Expression"), aliases), body.get("Property"))
    if kind in ("Aggregation", "Min", "Max", "Percentile"):
        inner = body.get("Expression") or {}
        sub = [k for k in REF_KEYS if k in inner]
        if len(sub) == 1:
            ref = _decode(sub[0], inner[sub[0]], aliases)
            if ref is not None:
                ref.agg = AGG.get(body.get("Function"), kind if kind != "Aggregation" else f"Fn{body.get('Function')}")
            return ref
        return None
    return None


# ---------- loading ----------
def find_report_dir(pbip_dir: str) -> str:
    """Accept a folder holding *.pbip, a *.pbip file, or a *.Report folder."""
    p = pbip_dir
    if os.path.isfile(p) and p.lower().endswith(".pbip"):
        base = os.path.dirname(p)
        rel = (_load(p).get("artifacts") or [{}])[0].get("report", {}).get("path")
        return os.path.normpath(os.path.join(base, rel)) if rel else base
    if os.path.isdir(p) and p.rstrip("/\\").lower().endswith(".report"):
        return p
    pbips = sorted(glob.glob(os.path.join(p, "*.pbip")))
    if pbips:
        return find_report_dir(pbips[0])
    reps = sorted(glob.glob(os.path.join(p, "*.Report")))
    if reps:
        return reps[0]
    raise FileNotFoundError(f"no *.pbip or *.Report under {pbip_dir}")


def load_report(pbip_dir: str, allow_legacy: bool = True) -> Report:
    root = find_report_dir(pbip_dir)
    rep = Report(root=root, legacy=False)
    pbir = os.path.join(root, "definition.pbir")
    if os.path.exists(pbir):
        d = _load(pbir)
        rep.version = d.get("version")
        dsr = d.get("datasetReference") or {}
        if (dsr.get("byPath") or {}).get("path"):
            rep.dataset_path = os.path.normpath(os.path.join(root, dsr["byPath"]["path"]))
        if (dsr.get("byConnection") or {}).get("connectionString"):
            rep.dataset_connection = dsr["byConnection"]["connectionString"]
    else:
        rep.findings.append({"severity": "warning", "where": _rel(root, pbir), "message": "definition.pbir missing"})
    defn = os.path.join(root, "definition")
    if os.path.isdir(defn):
        _load_pbir(rep, defn)
    elif os.path.exists(os.path.join(root, "report.json")):
        if not allow_legacy:
            raise ValueError("legacy report.json layout; pass --legacy-ok to load it best-effort")
        rep.legacy = True
        _load_legacy(rep, os.path.join(root, "report.json"))
    else:
        raise FileNotFoundError(f"no definition/ folder or report.json in {root}")
    return rep


def _load_pbir(rep: Report, defn: str) -> None:
    root = rep.root
    rj = os.path.join(defn, "report.json")
    if os.path.exists(rj):
        d = _load(rj)
        rep.filters = _filters(d.get("filterConfig"), _rel(root, rj), "report")
    ext = os.path.join(defn, "reportExtension.json")
    if os.path.exists(ext):
        for ent in (_load(ext).get("entities") or []):
            for m in ent.get("measures") or []:
                rep.extension_measures.append({"entity": ent.get("name"), "name": m.get("name"), "expression": m.get("expression"), "file": _rel(root, ext)})
    order: list[str] = []
    pages_json = os.path.join(defn, "pages", "pages.json")
    if os.path.exists(pages_json):
        order = list(_load(pages_json).get("pageOrder") or [])
    page_dirs = sorted(d for d in glob.glob(os.path.join(defn, "pages", "*")) if os.path.isdir(d))
    ordinal = {pid: i for i, pid in enumerate(order)}
    for pd in page_dirs:
        pid = os.path.basename(pd)
        pj = os.path.join(pd, "page.json")
        d = _load(pj) if os.path.exists(pj) else {}
        page = Page(pid, d.get("displayName") or pid, ordinal.get(pid, 999), _rel(root, pj),
                    hidden=str(d.get("visibility", "")).lower() == "hiddeninviewmode",
                    filters=_filters(d.get("filterConfig"), _rel(root, pj), "page"))
        for vd in sorted(glob.glob(os.path.join(pd, "visuals", "*"))):
            vj = os.path.join(vd, "visual.json")
            if not os.path.exists(vj):
                continue
            v = _load(vj)
            vis = v.get("visual") or {}
            visual = Visual(pid, page.name, v.get("name") or os.path.basename(vd), vis.get("visualType"), _title(vis),
                            bool(v.get("isHidden", False)), _rel(root, vj), schema=v.get("$schema"))
            visual.fields = list(walk_refs(v, visual.file))
            visual.filters = _filters(v.get("filterConfig"), visual.file, "visual")
            page.visuals.append(visual)
        rep.pages.append(page)
    rep.pages.sort(key=lambda p: (p.ordinal, p.id))
    for pid in order:
        if not any(p.id == pid for p in rep.pages):
            rep.findings.append({"severity": "error", "where": _rel(root, pages_json), "message": f"pageOrder names missing page folder {pid}"})
    for bj in sorted(glob.glob(os.path.join(defn, "bookmarks", "*.json"))):
        if os.path.basename(bj) == "bookmarks.json":
            continue
        b = _load(bj)
        targets = list(((b.get("explorationState") or {}).get("sections") or {}).keys())
        visuals = []
        for sec in ((b.get("explorationState") or {}).get("sections") or {}).values():
            visuals += list((sec.get("visualContainers") or {}).keys())
        rep.bookmarks.append({"name": b.get("name"), "displayName": b.get("displayName"), "pages": targets, "visuals": visuals, "file": _rel(root, bj)})


def _title(vis: dict) -> str | None:
    try:
        for t in (vis.get("visualContainerObjects") or {}).get("title") or []:
            lit = (((t.get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal") or {}
            if lit.get("Value"):
                return str(lit["Value"]).strip("'")
    except AttributeError:
        pass
    return None


def _filters(cfg: Any, file: str, scope: str) -> list[dict]:
    out = []
    for f in ((cfg or {}).get("filters") or []):
        refs = list(walk_refs(f.get("field") or f.get("expression") or {}, file, "$.field", None, "filter"))
        if not refs and f.get("filter"):
            refs = list(walk_refs(f["filter"], file, "$.filter", None, "filter"))
        out.append({"name": f.get("name"), "type": f.get("type"), "scope": scope, "file": file,
                    "field": refs[0].label() if refs else None, "refs": refs})
    return out


def _load_legacy(rep: Report, report_json: str) -> None:
    """Single-file report.json: sections[].visualContainers[] with stringified config/filters/query."""
    d = _load(report_json)
    root = rep.root
    rel = _rel(root, report_json)
    rep.filters = _filters({"filters": _js(d.get("filters"))}, rel, "report")
    for i, sec in enumerate(d.get("sections") or []):
        page = Page(sec.get("name") or f"section{i}", sec.get("displayName") or f"Page {i + 1}", sec.get("ordinal", i), rel,
                    filters=_filters({"filters": _js(sec.get("filters"))}, rel, "page"))
        for vc in sec.get("visualContainers") or []:
            cfg = _js(vc.get("config")) or {}
            sv = cfg.get("singleVisual") or {}
            visual = Visual(page.id, page.name, cfg.get("name") or "", sv.get("visualType"), None, False, rel)
            visual.fields = list(walk_refs({"prototypeQuery": sv.get("prototypeQuery"), "objects": sv.get("objects"),
                                            "vcObjects": sv.get("vcObjects")}, rel, "$.config.singleVisual"))
            visual.filters = _filters({"filters": _js(vc.get("filters"))}, rel, "visual")
            page.visuals.append(visual)
        rep.pages.append(page)


def _js(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v
