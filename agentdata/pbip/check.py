"""Model <-> report validator. Findings carry an exact location and a fix. Exit 1 on any error.
TE2 (`TabularEditor.exe <definition> -B out.bim`) is the authoritative TMDL/DAX check when available: it parses
TMDL and builds the TOM graph, so it catches invalid properties, unresolved columns and DAX syntax errors."""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass

from . import pbir as P
from . import tmdl as T
from .normalize import Model, ModelIndex


@dataclass
class Finding:
    severity: str   # error | warning | info
    kind: str
    where: str
    object: str
    message: str
    hint: str = ""

    def row(self) -> list:
        return [self.severity, self.kind, self.where, self.object, self.message, self.hint]


def check_model(model: Model) -> list[Finding]:
    out: list[Finding] = []
    rel = lambda p: os.path.relpath(p, model.definition_dir).replace("\\", "/")  # noqa: E731
    for f in model.lint:
        out.append(Finding("error" if f.severity == "error" else "warning", "tmdl-" + f.rule, f"{rel(f.file)}:{f.line}", "", f.message, f.fix))
    idx = ModelIndex(model)
    tags: dict[str, str] = {}
    table_names = {t["name"] for t in model.tables}
    for t in model.tables:
        for obj, label in ([(t, f"table {t['name']}")] + [(c, f"'{t['name']}'[{c['name']}]") for c in t["columns"]] + [(m, f"'{t['name']}'[{m['name']}]") for m in t["measures"]]):
            tag = obj.get("lineageTag")
            if tag:
                if tag in tags:
                    out.append(Finding("error", "dup-lineage-tag", f"{t['file']}:{obj.get('line', '')}", label, f"lineageTag {tag} already used by {tags[tag]}", "delete the lineageTag line on the copied object; Desktop assigns a new one on save"))
                tags[tag] = label
        cols = {c["name"] for c in t["columns"]}
        for c in t["columns"]:
            if c["sortByColumn"] and c["sortByColumn"] not in cols:
                out.append(Finding("error", "sort-by-missing", f"{t['file']}:{c['line']}", f"'{t['name']}'[{c['name']}]", f"sortByColumn '{c['sortByColumn']}' is not a column of {t['name']}", "point sortByColumn at an existing column (quote names with spaces)"))
        for h in t["hierarchies"]:
            for lv in h["levels"]:
                if lv["column"] and lv["column"] not in cols:
                    out.append(Finding("error", "level-column-missing", f"{t['file']}:{h['line']}", f"'{t['name']}'[{h['name']}]", f"level {lv['name']} references missing column {lv['column']}", "use a column of the same table"))
        for m in t["measures"]:
            for dep in m["deps"]["columns"]:
                dt, dc = T.split_ref(dep)
                if dt in table_names and dc not in idx.tables[dt]["columns"] and dc not in idx.tables[dt]["measures"]:
                    out.append(Finding("warning", "dax-ref-unresolved", f"{t['file']}:{m['line']}", f"'{t['name']}'[{m['name']}]", f"DAX references {dep}, which is not a column or measure of {dt}", "check spelling/quotes; run --te2 for the authoritative DAX check"))
            for dep in m["deps"]["measures"]:
                if dep not in idx.measure_table and dep not in cols and not any(dep in x["columns"] for x in idx.tables.values()):
                    out.append(Finding("warning", "dax-measure-unresolved", f"{t['file']}:{m['line']}", f"'{t['name']}'[{m['name']}]", f"DAX references [{dep}], which is not a measure (or same-table column) in the model", "check spelling; run --te2 for the authoritative DAX check"))
    for r in model.relationships:
        for side, tn, cn in (("from", r["fromTable"], r["fromColumn"]), ("to", r["toTable"], r["toColumn"])):
            if tn not in table_names:
                out.append(Finding("error", "relationship-table-missing", f"{r['file']}:{r['line']}", f"relationship {r['name']}", f"{side}Column table '{tn}' not in model", "fix the table name or delete the relationship"))
            elif cn not in idx.tables[tn]["columns"]:
                out.append(Finding("error", "relationship-column-missing", f"{r['file']}:{r['line']}", f"relationship {r['name']}", f"{side}Column {tn}.{cn} not in model", "fix the column name (quote names with spaces)"))
    ref_tables = set(model.refs.get("table", []))
    for t in model.tables:
        if ref_tables and t["name"] not in ref_tables:
            out.append(Finding("error", "ref-table-missing", "model.tmdl", f"table {t['name']}", f"tables/{t['name']}.tmdl exists but model.tmdl has no `ref table {T.quote_name(t['name'])}`", f"add `ref table {T.quote_name(t['name'])}` to model.tmdl"))
    for rt in ref_tables - table_names:
        out.append(Finding("error", "ref-table-dangling", "model.tmdl", f"ref table {rt}", "model.tmdl references a table with no tables/*.tmdl file", "remove the ref or add the table file"))
    return out


def check_report(report: P.Report, model: Model) -> list[Finding]:
    out: list[Finding] = []
    idx = ModelIndex(model, report)
    for f in report.findings:
        out.append(Finding(f["severity"], "report-structure", f["where"], "", f["message"], ""))
    if report.dataset_path and not os.path.exists(os.path.join(report.dataset_path, "definition", "model.tmdl")):
        out.append(Finding("error", "pbir-dataset-path", "definition.pbir", "", f"byPath '{report.dataset_path}' has no definition/model.tmdl", "fix datasetReference.byPath.path (relative, forward slashes)"))
    seen_pages: dict[str, str] = {}
    filter_names: dict[str, str] = {}
    for p in report.pages:
        if p.id in seen_pages:
            out.append(Finding("error", "page-name-dup", p.file, p.id, "page name used twice", "page names must be unique in the report"))
        seen_pages[p.id] = p.name
        seen_visuals: set[str] = set()
        for flt in p.filters:
            _filter_checks(out, flt, idx, filter_names, f"page {p.name}")
        for v in p.visuals:
            if not report.legacy:
                if not P.HEX20.match(v.id or ""):
                    out.append(Finding("warning", "visual-name-format", v.file, v.id, "visual name should be 20 lowercase hex chars", "keep Desktop-generated names; never invent one"))
                if v.id in seen_visuals:
                    out.append(Finding("error", "visual-name-dup", v.file, v.id, "visual name used twice on the page", "names must be unique per page"))
                if not v.schema:
                    out.append(Finding("warning", "schema-missing", v.file, v.id, "visual.json has no $schema", "copy the $schema URL from a sibling visual; never bump the version by hand"))
            seen_visuals.add(v.id)
            for r in v.fields:
                ok, why = idx.resolve(r)
                label = f"{v.id}{' (' + v.title + ')' if v.title else ''}"
                if not ok:
                    out.append(Finding("error", "field-unresolved", f"{v.file} {r.path}", label, f"{r.context}: {why}", "rename in the report (visual.json) or restore the object in TMDL; `ad-pbip refs` lists every use"))
                elif r.entity and r.kind == "column" and r.prop in idx.tables[r.entity]["hidden_columns"]:
                    out.append(Finding("info", "hidden-column-used", f"{v.file} {r.path}", label, f"{r.context}: hidden column '{r.entity}'[{r.prop}] is used directly", "fine for keys/sorts; otherwise unhide or use a measure"))
            for flt in v.filters:
                _filter_checks(out, flt, idx, filter_names, f"visual {v.id}")
    for flt in report.filters:
        _filter_checks(out, flt, idx, filter_names, "report")
    visual_ids = {v.id for v in report.all_visuals()}
    for b in report.bookmarks:
        for vid in b["visuals"]:
            if vid not in visual_ids:
                out.append(Finding("warning", "bookmark-visual-missing", b["file"], b.get("displayName") or b.get("name") or "", f"bookmark targets visual {vid} which no longer exists", "recreate the bookmark in Desktop or delete it"))
    for em in report.extension_measures:
        if em["entity"] not in idx.tables or em["entity"] not in {t["name"] for t in model.tables}:
            out.append(Finding("error", "extension-entity-missing", em["file"], f"[{em['name']}]", f"report-level measure targets table '{em['entity']}' which is not in the model", "fix the entity or move the measure into TMDL"))
    return out


def _filter_checks(out: list[Finding], flt: dict, idx: ModelIndex, names: dict[str, str], scope: str) -> None:
    name = flt.get("name")
    if name:
        if name in names:
            out.append(Finding("error", "filter-name-dup", flt["file"], name, f"filter name also used in {names[name]}", "filter names must be unique across the whole report"))
        names[name] = scope
        if not P.FILTER_NAME.match(name):
            out.append(Finding("warning", "filter-name-format", flt["file"], name, "filter name should be Filter + 24 lowercase hex chars", "keep Desktop-generated names"))
    for r in flt.get("refs") or []:
        ok, why = idx.resolve(r)
        if not ok:
            out.append(Finding("error", "filter-field-unresolved", f"{flt['file']} {r.path}", name or scope, f"{scope}: {why}", "fix the field in filterConfig or restore the object in TMDL"))


# ---------- Tabular Editor 2 ----------
def run_te2(definition_dir: str, te2_exe: str, bpa: bool = False, timeout: int = 300) -> tuple[list[Finding], dict]:
    """TabularEditor.exe <definition> -B <tmp>/model.bim [-A]: exit 1 iff TE2 reported an error."""
    if not te2_exe or not os.path.exists(te2_exe):
        return [Finding("warning", "te2-missing", "", "", "TabularEditor.exe not found", "set te2_exe (ad-setup --only powerbi) or pass --te2-exe")], {"ran": False}
    if not os.path.exists(os.path.join(definition_dir, "model.tmdl")):
        return [Finding("error", "te2-input", definition_dir, "", "folder has no model.tmdl (pass the SemanticModel/definition folder)", "")], {"ran": False}
    with tempfile.TemporaryDirectory() as td:
        args = [te2_exe, definition_dir, "-B", os.path.join(td, "model.bim")] + (["-A"] if bpa else [])
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return [Finding("error", "te2-run", "", "", f"{type(e).__name__}: {e}", "check te2_exe; TE2 needs .NET Framework 4.7.2+")], {"ran": False}
    text = (p.stdout or "") + "\n" + (p.stderr or "")
    out: list[Finding] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r"\berror\b", s, re.I):
            out.append(Finding("error", "te2", "TE2", "", s[:300], "fix the TMDL/DAX at the location TE2 names"))
        elif re.search(r"\bwarning\b", s, re.I) or (bpa and re.match(r"^\[", s)):
            out.append(Finding("warning", "te2-bpa" if bpa else "te2", "TE2", "", s[:300], ""))
    if p.returncode != 0 and not any(f.severity == "error" for f in out):
        out.append(Finding("error", "te2", "TE2", "", f"exit code {p.returncode}: {text.strip()[-300:]}", "read the TE2 output above"))
    return out, {"ran": True, "exit_code": p.returncode, "bpa": bpa}
