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
    functions: list[dict] = field(default_factory=list)  # DAX user-defined functions (functions.tmdl)
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


# ---------- DAX user-defined functions (UDFs): the signature parser, the call finder, the naming rules ----------
# Facts encoded here (Microsoft Learn, "DAX user-defined functions", GA in Desktop 2.155 / June 2026):
# - TMDL: `function <Name> = ( [<param> [: <type hints>] [= <default>], ...] ) => <body>`, `///` description lines
#   above it, all of a model's functions in `definition/functions.tmdl`. The TOM `Function.Expression` is the whole
#   `( params ) => body` text.
# - compatibilityLevel 1702 or higher.
# - type hints `[type] [subtype] [mode]`: types AnyVal Scalar Table AnyRef CalendarRef ColumnRef MeasureRef TableRef;
#   subtypes (Scalar only, implying it) Variant Int64 Decimal Double String DateTime Boolean Numeric; modes val expr.
#   Nothing given = `AnyVal val`; the *Ref types are always `expr` (`val` is not allowed).
# - `= <default>` makes a parameter optional (June 2026). Optional parameters may sit anywhere; the minimum number of
#   arguments is the position of the rightmost required one, and `F(1,,3)` leaves the second one empty.
# - names: letters, digits, `_`, dots for namespacing (not first/last, never two in a row), first character a letter
#   or `_`; parameter names letters, digits, `_`. Not a reserved word (measure, function, define). No recursion.
UDF_MIN_COMPATIBILITY = 1702
UDF_TYPES = {t.lower(): t for t in ("AnyVal", "Scalar", "Table", "AnyRef", "CalendarRef", "ColumnRef", "MeasureRef", "TableRef")}
UDF_SUBTYPES = {t.lower(): t for t in ("Variant", "Int64", "Decimal", "Double", "String", "DateTime", "Boolean", "Numeric")}
UDF_MODES = {"val", "expr"}
UDF_REF_TYPES = {"AnyRef", "CalendarRef", "ColumnRef", "MeasureRef", "TableRef"}
UDF_RESERVED = {"measure", "function", "define"}
_UDF_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*$")
_UDF_PARAM = re.compile(r"^[A-Za-z0-9_]+$")
_DAX_OPEN, _DAX_CLOSE = "([{", ")]}"


def blank_dax(text: str) -> str:
    """The text with string literals, quoted names and comments replaced by spaces (same length), so a scan for
    `(`, `,`, `=` or a function name never trips over one inside `"a, b"`, `'My (Table)'` or `// F(x)`."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n:
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:   # "" / '' escape
                        j += 2
                        continue
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
        elif text.startswith("//", i) or text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = " " * (j - i)
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out[i:j] = [c if c == "\n" else " " for c in text[i:j]]
            i = j
        else:
            i += 1
    return "".join(out)


def _dax_close(clean: str, start: int) -> int:
    """Index of the bracket closing the one at `start` (in blanked text), or -1."""
    depth = 0
    for i in range(start, len(clean)):
        if clean[i] in _DAX_OPEN:
            depth += 1
        elif clean[i] in _DAX_CLOSE:
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_dax(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` outside brackets, strings, quoted names and comments."""
    clean = blank_dax(text)
    parts, depth, last = [], 0, 0
    for i, ch in enumerate(clean):
        if ch in _DAX_OPEN:
            depth += 1
        elif ch in _DAX_CLOSE:
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[last:i])
            last = i + 1
    parts.append(text[last:])
    return parts


def parse_function_param(raw: str) -> dict:
    clean = blank_dax(raw)
    eq = clean.find("=")
    head, default = (raw, None) if eq < 0 else (raw[:eq], raw[eq + 1:].strip())
    name, _, hints = head.partition(":")
    words = hints.split()
    ptype = subtype = mode = None
    unknown = []
    for w in words:
        lw = w.lower()
        if lw in UDF_TYPES and ptype is None:
            ptype = UDF_TYPES[lw]
        elif lw in UDF_SUBTYPES and subtype is None:
            subtype = UDF_SUBTYPES[lw]
        elif lw in UDF_MODES and mode is None:
            mode = lw
        else:
            unknown.append(w)
    eff_type = ptype or ("Scalar" if subtype else "AnyVal")
    return {"name": name.strip(), "type": eff_type, "subtype": subtype, "mode": mode or ("expr" if eff_type in UDF_REF_TYPES else "val"),
            "declared_mode": mode, "default": default, "optional": default is not None, "unknown_hints": unknown,
            "text": " ".join(raw.split())}


def parse_function(expr: str) -> dict | None:
    """`( params ) => body` -> {params, body, min_args, max_args}; None when the text is not a function signature."""
    text = (expr or "").strip()
    clean = blank_dax(text)
    start = len(clean) - len(clean.lstrip())
    if start >= len(clean) or clean[start] != "(":
        return None
    close = _dax_close(clean, start)
    if close < 0 or not clean[close + 1:].lstrip().startswith("=>"):
        return None
    inner = text[start + 1:close]
    params = [] if not blank_dax(inner).strip() else [parse_function_param(p) for p in split_dax(inner)]
    body = text[close + 1:].lstrip()[2:].strip()
    required = [i for i, p in enumerate(params) if not p["optional"]]
    return {"params": params, "body": body, "min_args": (required[-1] + 1) if required else 0, "max_args": len(params)}


def parse_function_doc(lines: list[str]) -> tuple[str | None, dict[str, str], str | None]:
    """`///` lines -> (description, {param: doc}, returns). JSDoc `@param {T} [name] - text` / `@returns text` lines
    are what Desktop's DAX query view and TMDL view author for a function."""
    desc, params, returns = [], {}, None
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^@param\s+(?:\{[^}]*\}\s*)?\[?([A-Za-z0-9_]+)\]?\s*-?\s*(.*)$", s)
        if m:
            params[m.group(1)] = m.group(2).strip()
        elif s.startswith(("@returns", "@return")):
            returns = s.split(None, 1)[1].strip() if len(s.split(None, 1)) > 1 else ""
        elif s:
            desc.append(s)
    return (" ".join(desc) or None), params, returns


def function_name_problems(name: str) -> list[str]:
    out = []
    if not _UDF_NAME.match(name or ""):
        out.append("a function name is letters, digits and `_`, dots only between parts, first character a letter or `_`")
    if (name or "").lower() in UDF_RESERVED:
        out.append(f"`{name}` is a reserved word")
    return out


def function_param_problems(p: dict) -> list[str]:
    out = []
    if not _UDF_PARAM.match(p["name"]):
        out.append(f"parameter `{p['name']}`: a parameter name is letters, digits and `_` only")
    elif p["name"].lower() in UDF_RESERVED:
        out.append(f"parameter `{p['name']}` is a reserved word")
    if p["type"] in UDF_REF_TYPES and p["declared_mode"] == "val":
        out.append(f"parameter `{p['name']}`: {p['type']} is always passed as expr; `val` is not allowed")
    return out


def function_calls(expr: str, names: list[str]) -> list[tuple[str, int]]:
    """Every call of one of `names` in a DAX expression -> [(name as declared, argument count)]. DAX names are
    case-insensitive; `F()` has 0 arguments and `F(1,,3)` has 3 (the empty one takes the default)."""
    if not names or not expr:
        return []
    by_lower = {n.lower(): n for n in names}
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    rx = re.compile(r"(?<![\w.'\[\]])(" + alt + r")\s*\(", re.I)
    clean = blank_dax(expr)
    out = []
    for m in rx.finditer(clean):
        open_at = m.end() - 1
        close = _dax_close(clean, open_at)
        inner = expr[open_at + 1:close] if close > 0 else ""
        argc = 0 if not blank_dax(inner).strip() else len(split_dax(inner))
        out.append((by_lower[m.group(1).lower()], argc))
    return out


def functions_called(expr: str, names: list[str]) -> list[str]:
    seen: list[str] = []
    for n, _ in function_calls(expr, names):
        if n not in seen:
            seen.append(n)
    return seen


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
            elif node.kind == "function":
                m.functions.append(_function(node, rel))
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
    _link_functions(m)
    return m


def _function(node: T.Node, rel: str) -> dict:
    sig = parse_function(node.expr or "")
    desc, param_docs, returns = parse_function_doc(node.desc)
    params = [dict(p, doc=param_docs.get(p["name"])) for p in (sig or {}).get("params", [])]
    body = sig["body"] if sig else (node.expr or "")
    return {"name": node.name, "expression": node.expr or "", "signature_ok": sig is not None, "parameters": params,
            "body": body, "min_args": sig["min_args"] if sig else None, "max_args": sig["max_args"] if sig else None,
            "description": desc, "returns": returns, "lineageTag": node.props.get("lineageTag"),
            "deps": measure_deps(body), "file": rel, "line": node.line_start}


def _link_functions(m: Model) -> None:
    """UDF calls are only knowable once every file is read: `deps.functions` on measures and functions, `functions`
    on columns, each with the names as the model declares them."""
    names = [f["name"] for f in m.functions]
    for f in m.functions:
        f["deps"]["functions"] = functions_called(f["body"], names)
    for t in m.tables:
        for x in t["measures"]:
            x["deps"]["functions"] = functions_called(x["expression"], names)
        for c in t["columns"]:
            c["functions"] = functions_called(c["expression"] or "", names)


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
                     "relationships": model.relationships, "expressions": model.expressions, "functions": model.functions,
                     "roles": model.roles,
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
    function_usage: dict[str, list[str]] = {f["name"]: [] for f in model.functions}
    for t in model.tables:
        for m in t["measures"]:
            for fn in m["deps"].get("functions", []):
                function_usage[fn].append(f"'{t['name']}'[{m['name']}]")
        for c in t["columns"]:
            for fn in c.get("functions", []):
                function_usage[fn].append(f"'{t['name']}'[{c['name']}] (column)")
    for f in model.functions:  # a function body uses what it reads, the way a measure does
        for dep in [f"[{d}]" for d in f["deps"]["measures"]] + f["deps"]["columns"]:
            measure_usage.setdefault(dep, []).append(f"function {f['name']}")
        for fn in f["deps"]["functions"]:
            function_usage[fn].append(f"function {f['name']}")
    sources = {t["name"]: sorted({s for p in t["partitions"] for s in p["sources"]}) for t in model.tables}
    norm["lineage"] = {"field_usage": dict(sorted(usage.items())), "measure_usage": dict(sorted(measure_usage.items())),
                       "function_usage": function_usage, "sources": sources}
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
