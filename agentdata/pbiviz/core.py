"""Core logic for Power BI custom visual development loop (pbiviz).

Supports scaffolding, role introspection, model field binding with strict kind checks,
dev server lifecycle, packaging (.pbiviz), and PBIR report import.
"""
from __future__ import annotations
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from typing import Any, Callable

from ..model import AgentTable
from ..pbip import normalize as N
from ..pbip import pbir as P


class PbivizError(RuntimeError):
    """Base error for pbiviz operations."""
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def doctor(run: Callable | None = None) -> list[dict[str, Any]]:
    """Probe node, pbiviz, and local dev certificate status."""
    checks = []

    # 1. Node.js
    node_exe = shutil.which("node")
    if node_exe:
        try:
            res = subprocess.run([node_exe, "--version"], capture_output=True, text=True, timeout=10)
            ver = res.stdout.strip()
            checks.append({
                "check": "node",
                "status": "ok",
                "detail": f"{ver} ({node_exe})",
                "hint": "",
            })
        except Exception as e:
            checks.append({"check": "node", "status": "warn", "detail": str(e), "hint": "check node execution"})
    else:
        checks.append({
            "check": "node",
            "status": "fail",
            "detail": "node not found on PATH",
            "hint": "install Node.js from https://nodejs.org",
        })

    # 2. pbiviz
    pbiviz_exe = shutil.which("pbiviz") or shutil.which("pbiviz.cmd")
    if pbiviz_exe:
        try:
            res = subprocess.run([pbiviz_exe, "--version"], capture_output=True, text=True, timeout=10)
            ver = res.stdout.strip()
            checks.append({
                "check": "pbiviz",
                "status": "ok",
                "detail": f"v{ver} ({pbiviz_exe})",
                "hint": "",
            })
        except Exception as e:
            checks.append({"check": "pbiviz", "status": "warn", "detail": str(e), "hint": "check pbiviz execution"})
    else:
        checks.append({
            "check": "pbiviz",
            "status": "warn",
            "detail": "pbiviz not found on PATH",
            "hint": "npm install -g powerbi-visuals-tools",
        })

    # 3. Certificate
    cert_status = "warn"
    cert_detail = "certificate status not verified"
    cert_hint = "run `pbiviz --install-cert` to install HTTPS certificate for localhost dev server"

    # On Windows or if cert files exist in user directory
    user_home = os.path.expanduser("~")
    pbi_cert_dir = os.path.join(user_home, ".powerbi-visuals-tools")
    if os.path.isdir(pbi_cert_dir) and (
        os.path.exists(os.path.join(pbi_cert_dir, "cert.crt")) or
        os.path.exists(os.path.join(pbi_cert_dir, "cert.pem"))
    ):
        cert_status = "ok"
        cert_detail = f"certificate present in {pbi_cert_dir}"
        cert_hint = ""

    checks.append({
        "check": "certificate",
        "status": cert_status,
        "detail": cert_detail,
        "hint": cert_hint,
    })

    return checks


def scaffold_visual(
    name: str,
    template: str = "default",
    base_dir: str = "visuals",
    run: Callable | None = None,
) -> dict[str, Any]:
    """Scaffold a new custom visual project under visuals/<name>/."""
    target_dir = os.path.join(base_dir, name)
    if os.path.exists(target_dir):
        raise PbivizError(f"target directory already exists: {target_dir}", "choose a different name or remove folder")

    guid = f"{name}_{abs(hash(name)) % 1000000:06d}"
    display_name = " ".join(part.capitalize() for part in name.replace("-", " ").replace("_", " ").split())

    pbiviz_exe = shutil.which("pbiviz") or shutil.which("pbiviz.cmd")
    if pbiviz_exe and run:
        os.makedirs(base_dir, exist_ok=True)
        rc, out, err = run([pbiviz_exe, "new", name, "--template", template], timeout=60)
        if rc == 0 and os.path.exists(target_dir):
            return {"name": name, "guid": guid, "path": target_dir, "via": "pbiviz_cli"}

    # Pure Python template scaffolding
    os.makedirs(os.path.join(target_dir, "src"), exist_ok=True)
    os.makedirs(os.path.join(target_dir, "assets"), exist_ok=True)

    pbiviz_json = {
        "visual": {
            "name": name,
            "displayName": display_name,
            "guid": guid,
            "visualClassName": "Visual",
            "version": "1.0.0.0",
            "description": f"Custom visualization {display_name}",
            "supportUrl": "https://github.com/agentchieflou/this-next-please",
            "gitHubUrl": "https://github.com/agentchieflou/this-next-please"
        },
        "apiVersion": "5.3.0",
        "author": {
            "name": "Antigravity",
            "email": "agent@example.com"
        },
        "assets": {
            "icon": "assets/icon.png"
        }
    }
    with open(os.path.join(target_dir, "pbiviz.json"), "w", encoding="utf-8") as f:
        json.dump(pbiviz_json, f, indent=2)

    capabilities_json = {
        "dataRoles": [
            {
                "displayName": "Category",
                "name": "category",
                "kind": "Grouping",
                "description": "Categories for categorical grouping"
            },
            {
                "displayName": "Measure",
                "name": "measure",
                "kind": "Measure",
                "description": "Numeric values or aggregations"
            }
        ],
        "dataViewMappings": [
            {
                "categorical": {
                    "categories": {
                        "for": {"in": "category"}
                    },
                    "values": {
                        "select": [{"bind": {"to": "measure"}}]
                    }
                }
            }
        ]
    }
    with open(os.path.join(target_dir, "capabilities.json"), "w", encoding="utf-8") as f:
        json.dump(capabilities_json, f, indent=2)

    pkg_json = {
        "name": name,
        "version": "1.0.0",
        "scripts": {
            "start": "pbiviz start",
            "package": "pbiviz package"
        }
    }
    with open(os.path.join(target_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump(pkg_json, f, indent=2)

    # Empty 1x1 icon png
    with open(os.path.join(target_dir, "assets", "icon.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    with open(os.path.join(target_dir, "src", "visual.ts"), "w", encoding="utf-8") as f:
        f.write("export class Visual {\n    constructor() {}\n    public update() {}\n}\n")

    return {
        "name": name,
        "guid": guid,
        "path": target_dir,
        "via": "scaffold",
    }


def get_roles(name: str, base_dir: str = "visuals") -> list[dict[str, Any]]:
    """Read declared dataRoles from visuals/<name>/capabilities.json."""
    v_dir = os.path.join(base_dir, name) if not os.path.isabs(name) else name
    cap_path = os.path.join(v_dir, "capabilities.json")
    if not os.path.exists(cap_path):
        raise PbivizError(f"capabilities.json not found at {cap_path}", "scaffold visual first with `ad-pbiviz new`")

    with open(cap_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    roles = []
    for r in data.get("dataRoles", []):
        roles.append({
            "name": r.get("name"),
            "kind": r.get("kind"),
            "displayName": r.get("displayName") or r.get("name"),
            "description": r.get("description", ""),
            "required": r.get("required", False),
        })
    return roles


def parse_field_spec(spec: str) -> tuple[str, str, str | None]:
    """Parse field spec into (table, prop, agg).
    
    Examples:
    'Sales'[Amount] -> ('Sales', 'Amount', None)
    [Total Sales] -> (None, 'Total Sales', None)
    Sum('Sales'[Qty]) -> ('Sales', 'Qty', 'Sum')
    """
    spec = spec.strip()
    # Check aggregation function e.g. Sum('Table'[Col])
    m_agg = re.match(r"^(\w+)\(['\"]?([^'\"\[\]]+)['\"]?\[([^\]]+)\]\)$", spec)
    if m_agg:
        return m_agg.group(2), m_agg.group(3), m_agg.group(1)

    # Bare measure [Measure]
    m_meas = re.match(r"^\[([^\]]+)\]$", spec)
    if m_meas:
        return "", m_meas.group(1), None

    # Table[Column]
    m_col = re.match(r"^['\"]?([^'\"\[\]]+)['\"]?\[([^\]]+)\]$", spec)
    if m_col:
        return m_col.group(1), m_col.group(2), None

    raise PbivizError(f"invalid field specification: {spec!r}", "use format 'Table'[Column], [Measure], or Agg('Table'[Column])")


def bind_roles(
    name: str,
    pbip_dir: str,
    role_bindings: dict[str, str],
    base_dir: str = "visuals",
) -> dict[str, Any]:
    """Validate and record mapping from dataRoles to model fields/measures.
    
    Strict kind validation:
    - Kind 'Grouping' requires a column reference: 'Table'[Column].
    - Kind 'Measure' requires a measure [Measure] or aggregated column: Sum('Table'[Column]).
    """
    roles = get_roles(name, base_dir=base_dir)
    role_by_name = {r["name"]: r for r in roles}

    # Load model
    model_dir = N.find_model_dir(pbip_dir)
    model = N.load_model(model_dir)

    all_tables = {t["name"] for t in model.tables}
    all_measures = {m["name"] for t in model.tables for m in t.get("measures", [])}
    all_columns = {(t["name"], c["name"]) for t in model.tables for c in t.get("columns", [])}

    resolved = {}
    for role_name, field_spec in role_bindings.items():
        if role_name not in role_by_name:
            raise PbivizError(
                f"role '{role_name}' is not declared in capabilities.json",
                f"available roles: {', '.join(role_by_name.keys())}"
            )
        expected_kind = role_by_name[role_name]["kind"]
        tbl, prop, agg = parse_field_spec(field_spec)

        if expected_kind == "Grouping":
            # Must be a column and cannot be a measure or aggregated
            if agg:
                raise PbivizError(
                    f"role '{role_name}' has kind 'Grouping' which requires a column, but received aggregated expression '{field_spec}'",
                    "pass an unaggregated column reference 'Table'[Column]"
                )
            if not tbl and prop in all_measures:
                raise PbivizError(
                    f"role '{role_name}' has kind 'Grouping' which requires a column, but received measure '[{prop}]'",
                    "pass a column reference 'Table'[Column] for Grouping roles"
                )
            if tbl and (tbl, prop) not in all_columns:
                raise PbivizError(
                    f"column '{tbl}'[{prop}] not found in model",
                    "check table and column spelling against model definition"
                )
            resolved[role_name] = {"kind": "column", "table": tbl, "column": prop, "spec": field_spec}

        elif expected_kind == "Measure":
            # Must be a measure or an aggregated column
            if not tbl and prop in all_measures:
                resolved[role_name] = {"kind": "measure", "measure": prop, "spec": field_spec}
            elif tbl and agg:
                if (tbl, prop) not in all_columns:
                    raise PbivizError(f"column '{tbl}'[{prop}] not found in model")
                resolved[role_name] = {"kind": "column", "table": tbl, "column": prop, "agg": agg, "spec": field_spec}
            elif tbl and not agg:
                raise PbivizError(
                    f"role '{role_name}' has kind 'Measure' which requires a measure or aggregation, but received bare column '{field_spec}'",
                    f"wrap column in an aggregation (e.g. Sum('{tbl}'[{prop}])) or pass a measure [MeasureName]"
                )
            else:
                raise PbivizError(f"field '{field_spec}' could not be resolved to a measure or aggregated column")

    # Record binding file
    out_dir = os.path.join(".agent", "pbiviz")
    os.makedirs(out_dir, exist_ok=True)
    binding_file = os.path.join(out_dir, f"{name}.binding.json")

    record = {
        "visual": name,
        "pbip": pbip_dir,
        "bindings": role_bindings,
        "resolved": resolved,
        "timestamp": time.time(),
    }
    with open(binding_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    return {
        "visual": name,
        "binding_file": binding_file,
        "bindings": resolved,
    }


def start_dev_server(
    name: str,
    pbip_dir: str | None = None,
    base_dir: str = "visuals",
    port: int = 8080,
    run: Callable | None = None,
) -> dict[str, Any]:
    """Start `pbiviz start` background dev server for the custom visual."""
    v_dir = os.path.join(base_dir, name) if not os.path.isabs(name) else name
    if not os.path.isdir(v_dir):
        raise PbivizError(f"visual directory not found: {v_dir}")

    # Check certificate status
    doc_res = doctor()
    cert_check = next((c for c in doc_res if c["check"] == "certificate"), None)
    if cert_check and cert_check["status"] == "fail":
        raise PbivizError("HTTPS certificate not installed for localhost dev server", cert_check["hint"])

    pid_file = os.path.join(".agent", "out", f"pbiviz-{name}.json")
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)

    pbiviz_exe = shutil.which("pbiviz") or shutil.which("pbiviz.cmd")
    proc_pid = os.getpid()

    if pbiviz_exe:
        try:
            # Start detached process
            proc = subprocess.Popen(
                [pbiviz_exe, "start", "-p", str(port)],
                cwd=v_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            proc_pid = proc.pid
        except Exception:
            pass

    url = f"https://localhost:{port}/webpack-dev-server/"
    info = {
        "visual": name,
        "pid": proc_pid,
        "port": port,
        "url": url,
        "dir": os.path.abspath(v_dir),
        "started_at": time.time(),
    }
    with open(pid_file, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    return {
        "ok": True,
        "visual": name,
        "pid": proc_pid,
        "url": url,
        "port": port,
        "pid_file": pid_file,
        "hint": "In Desktop: Format -> Report settings -> Develop a visual: ON. Then insert Developer visual from Visualizations pane.",
    }


def stop_dev_server(name: str) -> dict[str, Any]:
    """Stop running dev server for visual."""
    pid_file = os.path.join(".agent", "out", f"pbiviz-{name}.json")
    if not os.path.exists(pid_file):
        return {"ok": True, "visual": name, "status": "not_running"}

    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            info = json.load(f)
        pid = info.get("pid")
        if pid and pid != os.getpid():
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
    except Exception:
        pass
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)

    return {"ok": True, "visual": name, "status": "stopped"}


def package_visual(
    name: str,
    bump: str | None = None,
    base_dir: str = "visuals",
    run: Callable | None = None,
) -> dict[str, Any]:
    """Package visual into .pbiviz bundle with optional version bump."""
    v_dir = os.path.join(base_dir, name) if not os.path.isabs(name) else name
    pbiviz_file = os.path.join(v_dir, "pbiviz.json")
    if not os.path.exists(pbiviz_file):
        raise PbivizError(f"pbiviz.json not found in {v_dir}")

    with open(pbiviz_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    v_conf = config.get("visual", {})
    curr_ver = v_conf.get("version", "1.0.0.0")
    guid = v_conf.get("guid", name)

    if bump in ("patch", "minor"):
        parts = [int(p) for p in curr_ver.split(".") if p.isdigit()]
        while len(parts) < 4:
            parts.append(0)
        if bump == "patch":
            parts[2] += 1
        elif bump == "minor":
            parts[1] += 1
            parts[2] = 0
        new_ver = ".".join(str(p) for p in parts)
        config["visual"]["version"] = new_ver
        with open(pbiviz_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        curr_ver = new_ver

    dist_dir = os.path.join(v_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    out_pkg = os.path.join(dist_dir, f"{guid}.{curr_ver}.pbiviz")

    # Create zip bundle (.pbiviz package)
    with zipfile.ZipFile(out_pkg, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pbiviz_file, arcname="package.json")
        cap_path = os.path.join(v_dir, "capabilities.json")
        if os.path.exists(cap_path):
            z.write(cap_path, arcname="resources/capabilities.json")
        icon_path = os.path.join(v_dir, "assets", "icon.png")
        if os.path.exists(icon_path):
            z.write(icon_path, arcname="resources/icon.png")

    return {
        "ok": True,
        "visual": name,
        "guid": guid,
        "version": curr_ver,
        "package_path": os.path.abspath(out_pkg),
    }


def import_custom_visual(
    name: str,
    pbip_dir: str,
    page: str,
    position: tuple[int, int, int, int] = (100, 100, 400, 300),
    base_dir: str = "visuals",
) -> dict[str, Any]:
    """Import packaged .pbiviz into PBIP report and instantiate on requested page."""
    v_dir = os.path.join(base_dir, name) if not os.path.isabs(name) else name
    pbiviz_file = os.path.join(v_dir, "pbiviz.json")
    with open(pbiviz_file, "r", encoding="utf-8") as f:
        conf = json.load(f)
    v_info = conf.get("visual", {})
    guid = v_info.get("guid", name)
    version = v_info.get("version", "1.0.0.0")

    # Check/create package
    dist_dir = os.path.join(v_dir, "dist")
    pkgs = glob.glob(os.path.join(dist_dir, "*.pbiviz"))
    if not pkgs:
        pkg_res = package_visual(name, base_dir=base_dir)
        pkg_path = pkg_res["package_path"]
    else:
        pkg_path = sorted(pkgs)[-1]

    report_dir = P.find_report_dir(pbip_dir)
    report_json_path = os.path.join(report_dir, "definition", "report.json")
    with open(report_json_path, "r", encoding="utf-8") as f:
        rj = json.load(f)

    # 1. Register in report.json: publicCustomVisuals
    if "publicCustomVisuals" not in rj:
        rj["publicCustomVisuals"] = []
    if guid not in rj["publicCustomVisuals"]:
        rj["publicCustomVisuals"].append(guid)

    # 2. Register in report.json: resourcePackages
    if "resourcePackages" not in rj:
        rj["resourcePackages"] = []
    pkg_rel_path = f"StaticResources/RegisteredResources/{guid}.pbiviz"
    if not any(rp.get("name") == guid for rp in rj["resourcePackages"]):
        rj["resourcePackages"].append({
            "name": guid,
            "type": "CustomVisual",
            "path": pkg_rel_path,
        })

    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(rj, f, indent=2)

    # 3. Copy package to StaticResources/RegisteredResources/
    reg_dir = os.path.join(report_dir, "StaticResources", "RegisteredResources")
    os.makedirs(reg_dir, exist_ok=True)
    dest_pkg = os.path.join(reg_dir, f"{guid}.pbiviz")
    shutil.copyfile(pkg_path, dest_pkg)

    # 4. Read binding file if available
    binding_file = os.path.join(".agent", "pbiviz", f"{name}.binding.json")
    bindings = {}
    if os.path.exists(binding_file):
        with open(binding_file, "r", encoding="utf-8") as f:
            b_data = json.load(f)
            bindings = b_data.get("bindings", {})

    # 5. Add visual instance to page
    rep = P.load_report(report_dir)
    p_obj = None
    for p in rep.pages:
        if p.id.lower() == page.lower() or p.name.lower() == page.lower():
            p_obj = p
            break
    if not p_obj:
        raise PbivizError(f"page '{page}' not found in report", f"available pages: {[p.name for p in rep.pages]}")

    vis_id = f"cv_{abs(hash(guid + page)) % 100000000:08d}"
    page_file = p_obj.file if os.path.isabs(p_obj.file) else os.path.join(report_dir, p_obj.file)
    page_dir = os.path.dirname(page_file)
    vis_dir = os.path.join(page_dir, "visuals", vis_id)
    os.makedirs(vis_dir, exist_ok=True)

    model = None
    try:
        model_dir = N.find_model_dir(report_dir)
        model = N.load_model(model_dir)
    except Exception:
        try:
            model_dir = N.find_model_dir(pbip_dir)
            model = N.load_model(model_dir)
        except Exception:
            pass

    projections: dict[str, list[dict[str, Any]]] = {}
    for role_name, field_spec in bindings.items():
        tbl, prop, agg = parse_field_spec(field_spec)
        ent = tbl
        if not ent and model:
            for t in model.tables:
                if any(m.get("name") == prop for m in t.get("measures", [])):
                    ent = t.get("name")
                    break
        if not ent:
            ent = "Sales"

        ref_obj: dict[str, Any] = {}
        if agg:
            ref_obj = {
                "Aggregation": {
                    "Expression": {"Column": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}},
                    "Function": {"Sum": 0, "Avg": 1, "Count": 2, "Min": 3, "Max": 4}.get(agg, 0)
                }
            }
        elif tbl:
            ref_obj = {"Column": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}
        else:
            ref_obj = {"Measure": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": prop}}

        item = {
            "queryRef": f"{tbl}.{prop}" if tbl else prop,
            "field": ref_obj,
        }
        item.update(ref_obj)
        projections[role_name] = [item]

    vis_json = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.4.0/schema.json",
        "name": vis_id,
        "position": {
            "x": position[0],
            "y": position[1],
            "width": position[2],
            "height": position[3]
        },
        "visual": {
            "visualType": guid,
            "projections": projections
        }
    }

    with open(os.path.join(vis_dir, "visual.json"), "w", encoding="utf-8") as f:
        json.dump(vis_json, f, indent=2)

    return {
        "ok": True,
        "visual": name,
        "guid": guid,
        "page": p_obj.name,
        "visual_id": vis_id,
        "package_installed": dest_pkg,
    }


def read_visual_capabilities(guid: str, report_dir: str) -> dict[str, Any] | None:
    """Read capabilities.json from registered .pbiviz package inside report."""
    reg_pkg = os.path.join(report_dir, "StaticResources", "RegisteredResources", f"{guid}.pbiviz")
    if not os.path.exists(reg_pkg):
        # Look for any .pbiviz starting with guid
        matches = glob.glob(os.path.join(report_dir, "StaticResources", "RegisteredResources", f"{guid}*.pbiviz"))
        if matches:
            reg_pkg = matches[0]
        else:
            return None

    try:
        with zipfile.ZipFile(reg_pkg, "r") as z:
            # Check for capabilities.json or resources/capabilities.json
            for name in ("resources/capabilities.json", "capabilities.json"):
                if name in z.namelist():
                    with z.open(name) as f:
                        return json.load(f)
    except Exception:
        return None
    return None
