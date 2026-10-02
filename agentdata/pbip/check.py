"""Model <-> report validator. Findings carry an exact location and a fix. Exit 1 on any error.
TE2 (`TabularEditor.exe <definition> -B out.bim`) is the authoritative TMDL/DAX check when available: it parses
TMDL and builds the TOM graph, so it catches invalid properties, unresolved columns and DAX syntax errors."""
from __future__ import annotations
import glob
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass

from . import pbir as P
from . import tmdl as T
from .normalize import Model, ModelIndex
from .. import textio


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
    rel = lambda p: textio.norm_path(os.path.relpath(p, model.definition_dir))  # noqa: E731
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
    from .features import check_model_features
    out.extend(check_model_features(model))
    return out


def check_report(report: P.Report, model: Model, facts: dict | None = None) -> list[Finding]:
    """`facts` are the project's AGENTS.md facts. The custom-visual certification floor runs either way
    (no facts: nothing is certified, SDK visuals are blocked); the tenant rules run only when given."""
    out: list[Finding] = []
    idx = ModelIndex(model, report)
    for f in report.findings:
        out.append(Finding(f["severity"], "report-structure", f["where"], "", f["message"], ""))
    if report.dataset_path and not os.path.exists(os.path.join(report.dataset_path, "definition", "model.tmdl")):
        out.append(Finding("error", "pbir-dataset-path", "definition.pbir", "", f"byPath '{report.dataset_path}' has no definition/model.tmdl", "fix datasetReference.byPath.path (relative, forward slashes)"))
    seen_pages: dict[str, str] = {}
    filter_names: dict[str, str] = {}
    all_visual_ids: dict[str, str] = {}
    legacy_types = {"card": "cardVisual", "table": "tableEx", "matrix": "pivotTable", "map": "azureMap"}

    # Anti-pattern: page-not-in-pages-json
    if report.root:
        pages_json_path = os.path.join(report.root, "definition", "pages", "pages.json")
        if os.path.exists(pages_json_path):
            try:
                order = list(P._load(pages_json_path).get("pageOrder") or [])
                disk_pids = {p.id for p in report.pages}
                for p in report.pages:
                    if p.id not in order:
                        out.append(Finding("error", "page-not-in-pages-json", p.file, p.id,
                                           f"page folder '{p.id}' exists on disk but is not listed in pages.json pageOrder",
                                           "add page id to pages.json pageOrder"))
                for pid in order:
                    if pid not in disk_pids:
                        out.append(Finding("error", "page-not-in-pages-json", pages_json_path, pid,
                                           f"pages.json pageOrder lists '{pid}' but folder does not exist",
                                           "remove page id from pages.json or create page folder"))
            except Exception:
                pass

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
                # Anti-pattern: duplicate-visual-id across entire report
                if v.id in all_visual_ids:
                    out.append(Finding("error", "duplicate-visual-id", v.file, v.id,
                                       f"visual id '{v.id}' used more than once in report (also in {all_visual_ids[v.id]})",
                                       "visual names must be unique across the report; generate fresh 20-hex id"))
                all_visual_ids[v.id] = v.file

                if not v.schema:
                    out.append(Finding("warning", "schema-missing", v.file, v.id, "visual.json has no $schema", "copy the $schema URL from a sibling visual; never bump the version by hand"))

                # Anti-pattern: legacy-visual-type
                if v.type and v.type in legacy_types:
                    out.append(Finding("warning", "legacy-visual-type", v.file, v.id,
                                       f"visual uses deprecated legacy type '{v.type}'",
                                       f"replace with modern '{legacy_types[v.type]}'"))

                # Anti-pattern: visualcalc-missing-nativequeryref
                raw_qs = ((v.raw.get("visual") or {}).get("query") or {}).get("queryState") or {}
                for role, container in raw_qs.items():
                    for proj in (container.get("projections") or []):
                        if "visualCalculation" in proj and "nativeQueryRef" not in proj:
                            out.append(Finding("warning", "visualcalc-missing-nativequeryref", v.file, v.id,
                                               f"visual calculation '{proj.get('queryRef')}' missing nativeQueryRef",
                                               "add nativeQueryRef to visual calculation projection"))

                # Anti-pattern: position-off-canvas
                pos = v.position or {}
                vx, vy, vw, vh = pos.get("x"), pos.get("y"), pos.get("width"), pos.get("height")
                if vx is not None and vy is not None and vw is not None and vh is not None:
                    pw, ph = p.width or 1280, p.height or 720
                    if vx < 0 or vy < 0 or (vx + vw > pw) or (vy + vh > ph):
                        out.append(Finding("warning", "position-off-canvas", v.file, v.id,
                                           f"visual bounds (x={vx}, y={vy}, w={vw}, h={vh}) extend outside canvas ({pw}x{ph})",
                                           "adjust position to fit within page canvas"))

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

        # Anti-pattern: overlap
        page_vis = [vis for vis in p.visuals if not vis.hidden and vis.position]
        for i in range(len(page_vis)):
            for j in range(i + 1, len(page_vis)):
                v1, v2 = page_vis[i], page_vis[j]
                p1, p2 = v1.position, v2.position
                x1, y1, w1, h1 = p1.get("x", 0), p1.get("y", 0), p1.get("width", 0), p1.get("height", 0)
                x2, y2, w2, h2 = p2.get("x", 0), p2.get("y", 0), p2.get("width", 0), p2.get("height", 0)
                ox = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
                oy = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
                if ox > 0 and oy > 0:
                    out.append(Finding("warning", "overlap", v1.file, f"{v1.id} & {v2.id}",
                                       f"visual '{v1.id}' overlaps with '{v2.id}' ({ox}x{oy}px)",
                                       "adjust visual layout coordinates to eliminate overlap"))

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
    from .features import check_report_features
    out.extend(check_report_features(model, report))
    _check_custom_visuals(out, report, model, idx, facts)
    return out


# Where a custom visual comes from decides who sees it. The PBIR report schema
# (microsoft/json-schemas, fabric/item/report/definition/report/3.1.0) and Microsoft's authoring guide
# (skills-for-fabric, powerbi-report-cli `custom-visuals.md`) give three channels:
# `publicCustomVisuals` names AppSource visuals; a `resourcePackages` entry of type
# `OrganizationalStoreCustomVisual`, named `<GUID>_OrgStore` like the visual's `visualType`, registers
# an organizational-store visual (the root `organizationCustomVisuals` array is schema-valid but does
# not register the plugin, so a visual listed only there renders as an empty placeholder); and a
# `resourcePackages` entry of type `CustomVisual` a private visual imported from a .pbiviz file. Only
# a private visual travels inside the report (Desktop and `ad-pbiviz import` write it under
# `CustomVisuals/<guid>/`; `ad-pbiviz import` once copied the .pbiviz under
# `StaticResources/RegisteredResources/`, which still counts): Power BI fetches AppSource and store
# visuals itself, so asking them for a package is a false error.
ORG, FILE, APPSOURCE = "organizational store", "file", "AppSource"
ORG_SUFFIX = "_OrgStore"

# The enterprise floor, which no fact downgrades: a custom visual that is not Microsoft-certified is
# an error everywhere. Certified means its GUID is in `pbi_certified_visuals`, the project's list of
# AppSource GUIDs whose certified badge somebody checked (the project stub presets Deneb's); nothing
# listed, nothing certified. A private .pbiviz is uncertified by definition (an SDK visual, gated by
# `pbi_sdk_visuals`, agentdata/pbiviz/gate.py). Deneb's Standalone, Alpha and Beta editions share
# the certified GUID's suffix and are never the certified visual, listed or not.
#
# On top of it, `pbi_custom_visuals` (AGENTS.md): what the tenant renders for the report's viewers,
# i.e. the Fabric tenant settings "Allow visuals created using the Power BI SDK" and "Add and use
# certified visuals only". Neither setting applies to organizational-store visuals. The gate fails
# closed: a tenant nobody recorded is treated as one that renders nothing but native and store
# visuals, because a report that ships a visual its viewers cannot see is the failure this exists to stop.
TENANT = ("allowed", "certified-only", "org-only")
UNCERTIFIED_EDITIONS = ("STANDALONE", "ALPHA", "BETA")   # deneb.UNCERTIFIED_EDITIONS, without the import
ROUTES = ("take a route this tenant renders: skill `pbi-custom-visual` (native first, then a Microsoft-certified "
          "visual; a non-certified visual is never the route)")


def _custom_visual_registry(report: P.Report) -> tuple[set[str], dict[str, bool], set[str], set[str]]:
    """(AppSource names, store names → disabled, private package names, store names listed only in the root
    `organizationCustomVisuals` array) from definition/report.json."""
    rj_path = os.path.join(report.root, "definition", "report.json") if report.root else ""
    rj = P._load(rj_path) if rj_path and os.path.exists(rj_path) else {}
    public = {i if isinstance(i, str) else i.get("name") for i in rj.get("publicCustomVisuals") or []
              if isinstance(i, str) or isinstance(i, dict)}
    root_listed = {i["name"]: bool(i.get("disabled")) for i in rj.get("organizationCustomVisuals") or []
                   if isinstance(i, dict) and i.get("name")}
    store = dict(root_listed)
    packaged: set[str] = set()
    private: set[str] = set()
    for rp in rj.get("resourcePackages") or []:
        if not isinstance(rp, dict) or not rp.get("name"):
            continue
        if rp.get("type") == "CustomVisual":
            private.add(rp["name"])
        elif rp.get("type") == "OrganizationalStoreCustomVisual":
            store.setdefault(rp["name"], False)
            packaged.add(rp["name"])
    bare = {n for n in root_listed if n not in packaged and n + ORG_SUFFIX not in packaged}
    return public - {None}, store, private, bare


def _guid(vtype: str) -> str:
    """The visual's GUID: an organizational-store `visualType` carries it with the `_OrgStore` suffix."""
    return vtype[: -len(ORG_SUFFIX)] if vtype.endswith(ORG_SUFFIX) else vtype


def _listed(value: object) -> set[str]:
    return {g.strip().lower() for g in str(value or "").split(",") if g.strip()}


def _uncertified_edition(vtype: str) -> bool:
    """Deneb's Standalone, Alpha and Beta editions: not on AppSource, so never the certified visual."""
    guid = _guid(vtype)
    return "deneb" in guid.lower() and any(guid.upper().startswith(e) for e in UNCERTIFIED_EDITIONS)


def _is_certified(vtype: str, certified: set[str]) -> bool:
    return not _uncertified_edition(vtype) and (_guid(vtype).lower() in certified or vtype.lower() in certified)


def _private_package_on_disk(report: P.Report, vtype: str) -> bool:
    if not report.root:
        return False
    return bool(os.path.isdir(os.path.join(report.root, "CustomVisuals", vtype))
                or glob.glob(os.path.join(glob.escape(report.root), "StaticResources", "RegisteredResources",
                                          glob.escape(vtype) + "*.pbiviz")))


def _standard_visual_types() -> set[str]:
    from .catalog import load_catalog
    return set(load_catalog().get("visuals", {}).keys()) | {
        "actionButton", "textbox", "image", "shape", "basicShape", "group", "kpi",
        "waterfallChart", "funnel", "filledMap", "shapeMap", "decompositionTreeVisual",
        "keyDriversVisual", "qnaVisual", "smartNarrative", "paginatedReportBearer",
        "rScript", "pythonVisual", "scriptVisual"
    }


def custom_visual_delivery(report: P.Report, facts: dict | None = None,
                           workspace: tuple[str, ...] | None = None) -> list[Finding]:
    """Whether every custom visual in the report reaches its viewers: registered, packaged when it
    must be, not switched off in the store, certified (the enterprise floor, which runs whether or not
    `facts` are given and which no fact downgrades), and, when `facts` are given, rendered by this tenant.

    `workspace` is the target of a publish, as (id, display name): an SDK visual approved for one
    workspace (`pbi_sdk_workspace`) is refused anywhere else; `()` leaves the target unchecked. Left
    out (None), the project's own `pbi_workspace` / `ws_id` facts stand in for the target.

    `ad-pbip check` and `ad-pbi publish report` both run it; publish refuses on any error row."""
    from ..pbiviz import gate as SG
    out: list[Finding] = []
    standard = _standard_visual_types()
    public, store, private, bare = _custom_visual_registry(report)
    known = facts if facts is not None else {}
    sdk = SG.gate(known)
    certified = _listed(known.get("pbi_certified_visuals"))
    org_listed = _listed(known.get("pbi_org_visuals"))

    tenant = str(known.get("pbi_custom_visuals") or "").strip().lower()
    if facts is not None and tenant and tenant not in TENANT + ("unknown",):
        out.append(Finding(
            "warning", "custom-visual-tenant-fact-invalid", "AGENTS.md", "pbi_custom_visuals",
            f"pbi_custom_visuals is '{tenant}', which is none of {', '.join(TENANT)}; treated as unrecorded",
            "record what the tenant renders for this report's viewers: allowed, certified-only or org-only",
        ))
        tenant = ""
    if facts is not None and sdk.invalid:
        out.append(Finding(
            "warning", "custom-visual-sdk-fact-invalid", "AGENTS.md", SG.FACT,
            f"{SG.FACT} is '{sdk.written}', which is none of {', '.join(SG.STATES)}; treated as blocked",
            f"write `- {SG.FACT}: blocked`, or `approved` once the operator has workspace approval for SDK visuals",
        ))
    for name in sorted(bare):
        out.append(Finding(
            "warning", "custom-visual-org-root-entry", "definition/report.json", name,
            f"'{name}' is listed in report.json organizationCustomVisuals, which does not register the visual: "
            "Desktop draws an empty placeholder in its place",
            f"register it as a resourcePackages entry of type OrganizationalStoreCustomVisual named "
            f"'{_guid(name)}{ORG_SUFFIX}' (item path \"\"), with the same visualType, and drop the root entry",
        ))
    unchecked: list[str] = []
    sdk_shipped = False

    for v in report.all_visuals():
        vtype = v.type
        if not vtype or vtype in standard:
            continue

        on_disk = _private_package_on_disk(report, vtype)
        channel = (ORG if vtype in store else FILE if vtype in private or on_disk
                   else APPSOURCE if vtype in public else None)

        if channel is None:
            out.append(Finding(
                "error", "custom-visual-guid-unregistered", v.file, v.id,
                f"custom visual type '{vtype}' is in none of report.json publicCustomVisuals, "
                "resourcePackages or organizationCustomVisuals",
                (f"the organizational store registers it as '{vtype}{ORG_SUFFIX}': set visualType to that"
                 if vtype + ORG_SUFFIX in store else
                 "add it in Desktop from AppSource or My organization (never from a name-guessed GUID), or "
                 "replace it: " + ROUTES),
            ))
            continue

        # only a private visual ships its package
        if channel == FILE and not on_disk:
            out.append(Finding(
                "error", "custom-visual-package-missing", v.file, v.id,
                f"report.json says the report carries '{vtype}' as a private visual, but its package is not on disk",
                "commit the package (CustomVisuals/ or StaticResources/RegisteredResources/), or replace it: " + ROUTES,
            ))

        if channel == ORG and store[vtype]:
            out.append(Finding(
                "error", "custom-visual-store-disabled", v.file, v.id,
                f"'{vtype}' is switched off in the organizational store: viewers read "
                "'This custom visual is no longer available. Contact your administrator for details.'",
                "ask the Fabric admin to turn access back on, or " + ROUTES,
            ))

        # The enterprise floor: certified, or (store only) the enterprise's own pick. No fact downgrades it.
        if channel == ORG:
            picked = vtype.lower() in org_listed or _guid(vtype).lower() in org_listed
            if not (_is_certified(vtype, certified) or (picked and tenant == "org-only")):
                out.append(Finding(
                    "error", "custom-visual-org-unapproved", v.file, v.id,
                    f"'{vtype}' comes from the organizational store; its GUID is not in pbi_certified_visuals, and "
                    "it is not an organizational visual the operator approved (in pbi_org_visuals, on a tenant "
                    "recorded as pbi_custom_visuals: org-only): the enterprise blocks visuals that are not certified",
                    "check its certified badge and add the GUID to pbi_certified_visuals; or, when this tenant "
                    "renders the organizational store only and the store carries it, list it in pbi_org_visuals; "
                    "otherwise " + ROUTES,
                ))
            continue        # the tenant settings never reach a store visual
        if channel == FILE and not sdk.approved:
            out.append(Finding(
                "error", "custom-visual-uncertified", v.file, v.id,
                f"'{vtype}' is a private visual from a .pbiviz file, built with the Power BI SDK and not "
                f"Microsoft-certified: {SG.BLOCKED}",
                ROUTES + f"; `{SG.FACT}: approved` is the operator's to write, once workspace approval exists",
            ))
            continue
        if channel == APPSOURCE and _uncertified_edition(vtype):
            out.append(Finding(
                "error", "custom-visual-uncertified", v.file, v.id,
                f"'{vtype}' is an uncertified edition of Deneb: the enterprise blocks visuals that are not certified",
                "use Deneb's certified AppSource edition (`ad-pbip visual deneb`), or " + ROUTES,
            ))
            continue
        if channel == APPSOURCE and not _is_certified(vtype, certified):
            out.append(Finding(
                "error", "custom-visual-certification-unconfirmed", v.file, v.id,
                f"'{vtype}' comes from AppSource, and the enterprise renders it only if it is Microsoft-certified; "
                "pbi_certified_visuals does not list it",
                "check the certified badge on its AppSource listing, then add the GUID to pbi_certified_visuals "
                "in AGENTS.md; if it is not certified, " + ROUTES,
            ))
            continue
        sdk_shipped = sdk_shipped or channel == FILE

        if facts is None:
            continue
        origin = "a .pbiviz file" if channel == FILE else "AppSource"
        if tenant == "org-only":
            out.append(Finding(
                "error", "custom-visual-tenant-blocked", v.file, v.id,
                f"'{vtype}' comes from {origin}, and this tenant renders organizational-store visuals only "
                "(pbi_custom_visuals: org-only): viewers get an error in its place",
                ("ask the Fabric admin to add this certified visual to the organizational store "
                 "(skill `pbi-custom-visual` has the request), or " if channel == APPSOURCE else "") + ROUTES,
            ))
        elif tenant == "certified-only" and channel == FILE:
            out.append(Finding(
                "error", "custom-visual-tenant-blocked", v.file, v.id,
                f"'{vtype}' comes from a .pbiviz file, and this tenant renders certified visuals only "
                "(pbi_custom_visuals: certified-only): a visual loaded from a file is not the certified one",
                "for a certified visual, add its AppSource edition instead; otherwise " + ROUTES,
            ))
        elif tenant == "allowed" and channel == FILE:
            out.append(Finding(
                "warning", "custom-visual-uncertified", v.file, v.id,
                f"'{vtype}' is a non-certified SDK visual loaded from a file: it ships under the operator's approval "
                f"({SG.FACT}: approved), renders while the tenant allows files, and stops the day the tenant "
                "turns certified-only",
                ROUTES,
            ))
        elif tenant not in TENANT:
            unchecked.append(vtype)

    if sdk_shipped:
        targets = (workspace if workspace is not None
                   else tuple(str(t) for t in (known.get("pbi_workspace"), known.get("ws_id")) if t))
        if not sdk.workspace:
            out.append(Finding(
                "warning", "custom-visual-sdk-workspace-unrecorded", "AGENTS.md", SG.WORKSPACE_FACT,
                "the report carries an SDK visual, and AGENTS.md does not name the workspace the approval covers",
                f"record `- {SG.WORKSPACE_FACT}: <workspace name or id>`: publish then refuses any other workspace",
            ))
        elif targets and not sdk.workspace_matches(*targets):
            out.append(Finding(
                "error", "custom-visual-sdk-workspace", "AGENTS.md", SG.WORKSPACE_FACT,
                f"SDK visuals are approved for workspace '{sdk.workspace}' only, and this report goes to "
                f"'{' / '.join(str(t) for t in targets)}'",
                f"publish to '{sdk.workspace}', or take the SDK visual out: " + ROUTES,
            ))

    if unchecked:
        out.append(Finding(
            "error", "custom-visual-tenant-unknown", "AGENTS.md", "pbi_custom_visuals",
            f"{len(unchecked)} visual(s) from a file or AppSource ({', '.join(sorted(set(unchecked)))}) render only "
            "if the tenant allows them, and AGENTS.md does not say whether it does",
            "record `- pbi_custom_visuals: allowed | certified-only | org-only` (skill `pbi-custom-visual`)",
        ))
    return out


def _check_custom_visuals(out: list[Finding], report: P.Report, model: Model, idx: ModelIndex,
                          facts: dict | None = None) -> None:
    from ..pbiviz import core as PV
    out.extend(custom_visual_delivery(report, facts))
    standard = _standard_visual_types()

    for v in report.all_visuals():
        vtype = v.type
        if not vtype or vtype in standard:
            continue

        # Read capabilities
        caps = PV.read_visual_capabilities(vtype, report.root) if report.root else None
        if not caps:
            v_dir = os.path.join("visuals", vtype)
            if os.path.isdir(v_dir) and os.path.exists(os.path.join(v_dir, "capabilities.json")):
                try:
                    with open(os.path.join(v_dir, "capabilities.json"), "r", encoding="utf-8") as f:
                        caps = json.load(f)
                except Exception:
                    pass

        if caps:
            roles = {r.get("name"): r for r in caps.get("dataRoles", [])}
            raw_v = v.raw.get("visual") or {}
            raw_proj = raw_v.get("projections") or {}
            raw_qs = (raw_v.get("query") or {}).get("queryState") or {}
            filled_roles = set(raw_proj.keys()) | set(raw_qs.keys())

            # 5. custom-visual-role-unfilled
            for rname, rinfo in roles.items():
                if rinfo.get("required") and rname not in filled_roles:
                    out.append(Finding(
                        "error", "custom-visual-role-unfilled", v.file, v.id,
                        f"required dataRole '{rname}' in custom visual '{vtype}' is unfilled",
                        f"bind fields to role '{rname}' in visual projections",
                    ))

            # 6. custom-visual-role-kind-mismatch
            for ref in v.fields:
                if ref.context.startswith("projection:"):
                    role_name = ref.context.split(":", 1)[1]
                    rinfo = roles.get(role_name)
                    if rinfo:
                        expected_kind = rinfo.get("kind")
                        if expected_kind == "Grouping" and (ref.kind == "measure" or ref.agg):
                            out.append(Finding(
                                "error", "custom-visual-role-kind-mismatch", v.file, v.id,
                                f"role '{role_name}' expects Grouping column, but projected field '{ref.label()}' is a measure/aggregation",
                                "project an unaggregated column into Grouping roles",
                            ))
                        elif expected_kind == "Measure" and ref.kind == "column" and not ref.agg:
                            out.append(Finding(
                                "error", "custom-visual-role-kind-mismatch", v.file, v.id,
                                f"role '{role_name}' expects Measure/aggregation, but projected field '{ref.label()}' is an unaggregated column",
                                "project a measure or aggregated column into Measure roles",
                            ))


def _has_sourceref_entity(obj: Any) -> bool:
    if isinstance(obj, dict):
        if "SourceRef" in obj and isinstance(obj["SourceRef"], dict) and "Entity" in obj["SourceRef"]:
            return True
        for v in obj.values():
            if _has_sourceref_entity(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_sourceref_entity(item):
                return True
    return False


def _filter_checks(out: list[Finding], flt: dict, idx: ModelIndex, names: dict[str, str], scope: str) -> None:
    name = flt.get("name")
    if name:
        if name in names:
            out.append(Finding("error", "duplicate-filter-id", flt["file"], name, f"filter name also used in {names[name]}", "filter names must be unique across the whole report"))
        names[name] = scope
        if not P.FILTER_NAME.match(name):
            out.append(Finding("warning", "filter-name-format", flt["file"], name, "filter name should be Filter + 24 lowercase hex chars", "keep Desktop-generated names"))

    # Anti-pattern: filter-entity-vs-source
    raw = flt.get("raw") or {}
    where = (raw.get("filter") or {}).get("Where")
    if where and _has_sourceref_entity(where):
        out.append(Finding("error", "filter-entity-vs-source", flt["file"], name or scope,
                           "Filter Where condition uses SourceRef.Entity instead of SourceRef.Source alias",
                           "Filter conditions must reference the From[] alias via SourceRef: {Source: ...}, not Entity"))

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


# ---------- live evaluation (Desktop or XMLA) ----------
def evaluate_live(report: P.Report, model: Model, server: str, dscmd: str, database: str | None = None, run=None,
                  file_flag: bool = True) -> tuple[list[Finding], dict]:
    """Evaluate every measure the report uses against a live instance, and compare live INFO.VIEW.MEASURES() with
    the TMDL parse (a stale Desktop shows measures missing or extra)."""
    from . import dax as D
    out: list[Finding] = []
    idx = ModelIndex(model, report)
    used = sorted({r.prop for _v, r in report.all_refs() if r.kind == "measure" and r.entity and r.prop in idx.tables.get(r.entity, {}).get("measures", set())})
    info: dict = {"server": server, "measures_probed": 0, "measures_failed": 0}
    try:
        live = D.run_dax(D.INFO_MEASURES, server, dscmd, database, run=run, file_flag=file_flag, name="info")
        live_names = {str(r[1]) for r in live.rows} if live.columns else set()
        model_names = {m["name"] for t in model.tables for m in t["measures"]}
        for m in sorted(model_names - live_names):
            out.append(Finding("warning", "live-stale", server, f"[{m}]", "measure exists in TMDL but not in the running model", "Desktop does not hot-reload: close and reopen the .pbip (ad-pbip launch)"))
        for m in sorted(live_names - model_names):
            out.append(Finding("warning", "live-extra", server, f"[{m}]", "measure exists in the running model but not in TMDL", "save from Desktop or delete it there; the files are the source of truth"))
    except D.DaxError as e:
        out.append(Finding("error", "live-connect", server, "", f"INFO.VIEW.MEASURES failed: {e}", "check the server (ad-pbip desktop) and dscmd_exe"))
        return out, info
    for m in used:
        info["measures_probed"] += 1
        try:
            D.run_dax(D.measure_probe(m), server, dscmd, database, run=run, file_flag=file_flag, name="probe")
        except D.DaxError as e:
            info["measures_failed"] += 1
            out.append(Finding("error", "live-dax", server, f"[{m}]", str(e)[-300:], "fix the measure DAX in TMDL, then reopen the PBIP in Desktop"))
    return out, info
