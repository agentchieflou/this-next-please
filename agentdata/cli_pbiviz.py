"""Command-line interface for `ad-pbiviz` — Power BI custom visual development loop."""
from __future__ import annotations
import argparse
import json
import os
import sys

from . import completion
from . import policy
from . import toon
from . import ui
from .model import AgentTable
from .pbiviz import core as PV


def utf8_stdout() -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


from .policy import error, render


def cmd_doctor(a) -> int:
    checks = PV.doctor()
    t = AgentTable.from_records(checks, name="doctor", source="ad-pbiviz doctor")
    has_fail = any(c["status"] == "fail" for c in checks)
    print(render(t, extra={"ok": not has_fail, "source": "ad-pbiviz doctor"}))
    return 1 if has_fail else 0


def cmd_new(a) -> int:
    try:
        res = PV.scaffold_visual(a.name, template=a.template)
        t = AgentTable.from_records([res], name="new", source="ad-pbiviz new")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz new", "name": a.name, "path": res["path"]}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz new"))
        return 1


def cmd_roles(a) -> int:
    try:
        roles = PV.get_roles(a.name)
        t = AgentTable.from_records(roles, name="data_roles", source="ad-pbiviz roles")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz roles", "visual": a.name, "count": len(roles)}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz roles"))
        return 1


def cmd_bind(a) -> int:
    role_dict = {}
    for item in a.role:
        if "=" not in item:
            print(error(f"invalid --role format '{item}'", "use --role <name>=<spec> (e.g. --role category='Sales'[Product])", "ad-pbiviz bind"))
            return 1
        r_name, r_spec = item.split("=", 1)
        role_dict[r_name.strip()] = r_spec.strip()

    try:
        res = PV.bind_roles(a.name, a.pbip, role_dict)
        rows = [{"role": k, "kind": v.get("kind"), "spec": v.get("spec")} for k, v in res["bindings"].items()]
        t = AgentTable.from_records(rows, name="bindings", source="ad-pbiviz bind")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz bind", "visual": a.name, "file": res["binding_file"]}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz bind"))
        return 1


def cmd_dev(a) -> int:
    try:
        res = PV.start_dev_server(a.name, pbip_dir=a.pbip, port=a.port)
        t = AgentTable.from_records([res], name="dev", source="ad-pbiviz dev")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz dev", "url": res["url"], "pid": res["pid"], "hint": res["hint"]}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz dev"))
        return 1


def cmd_stop(a) -> int:
    res = PV.stop_dev_server(a.name)
    t = AgentTable.from_records([res], name="stop", source="ad-pbiviz stop")
    print(render(t, extra={"ok": True, "source": "ad-pbiviz stop", "visual": a.name, "status": res["status"]}))
    return 0


def cmd_package(a) -> int:
    try:
        res = PV.package_visual(a.name, bump=a.bump)
        t = AgentTable.from_records([res], name="package", source="ad-pbiviz package")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz package", "visual": a.name, "package": res["package_path"]}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz package"))
        return 1


def cmd_import(a) -> int:
    pos = (100, 100, 400, 300)
    if a.position:
        try:
            parts = [int(p.strip()) for p in a.position.split(",")]
            if len(parts) == 4:
                pos = (parts[0], parts[1], parts[2], parts[3])
        except Exception:
            pass

    try:
        res = PV.import_custom_visual(a.name, a.pbip, a.page, position=pos)
        t = AgentTable.from_records([res], name="import", source="ad-pbiviz import")
        print(render(t, extra={"ok": True, "source": "ad-pbiviz import", "visual": a.name, "visual_id": res["visual_id"]}))
        return 0
    except PV.PbivizError as e:
        print(error(str(e), e.hint or "", "ad-pbiviz import"))
        return 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ad-pbiviz",
        description="Power BI custom visual development loop (pbiviz): scaffold, dev, bind, package, import",
    )
    from .version import add_version
    add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    # doctor
    p_doc = sub.add_parser("doctor", help="probe node, pbiviz, and dev certificate status")
    p_doc.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_doc.set_defaults(fn=cmd_doctor)

    # new
    p_new = sub.add_parser("new", help="scaffold custom visual under visuals/<name>/")
    p_new.add_argument("name", help="visual project name")
    p_new.add_argument("--template", default="default", choices=["default", "circlecard"], help="visual template")
    p_new.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_new.set_defaults(fn=cmd_new)

    # roles
    p_roles = sub.add_parser("roles", help="inspect declared dataRoles from capabilities.json")
    p_roles.add_argument("name", help="visual project name")
    p_roles.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_roles.set_defaults(fn=cmd_roles)

    # bind
    p_bind = sub.add_parser("bind", help="validate and record dataRole mapping to model fields")
    p_bind.add_argument("name", help="visual project name")
    p_bind.add_argument("--pbip", required=True, help="path to PBIP root directory")
    p_bind.add_argument("--role", action="append", required=True, help="role binding: --role <name>='Table'[Column] or [Measure]")
    p_bind.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bind.set_defaults(fn=cmd_bind)

    # dev
    p_dev = sub.add_parser("dev", help="start background pbiviz dev server on localhost:8080")
    p_dev.add_argument("name", help="visual project name")
    p_dev.add_argument("--pbip", help="optional PBIP path")
    p_dev.add_argument("--port", type=int, default=8080, help="dev server port (default: 8080)")
    p_dev.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_dev.set_defaults(fn=cmd_dev)

    # stop
    p_stop = sub.add_parser("stop", help="stop running dev server")
    p_stop.add_argument("name", help="visual project name")
    p_stop.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_stop.set_defaults(fn=cmd_stop)

    # package
    p_pkg = sub.add_parser("package", help="package visual into .pbiviz bundle")
    p_pkg.add_argument("name", help="visual project name")
    p_pkg.add_argument("--bump", choices=["patch", "minor"], help="bump version in pbiviz.json before packaging")
    p_pkg.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pkg.set_defaults(fn=cmd_package)

    # import
    p_imp = sub.add_parser("import", help="register .pbiviz into PBIP and instantiate on page")
    p_imp.add_argument("name", help="visual project name")
    p_imp.add_argument("--pbip", required=True, help="path to PBIP root directory")
    p_imp.add_argument("--page", required=True, help="target page id or display name")
    p_imp.add_argument("--position", help="bounding box x,y,width,height (default: 100,100,400,300)")
    p_imp.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_imp.set_defaults(fn=cmd_import)

    return ap


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = build_parser()
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        sys.exit(a.fn(a))
    except (FileNotFoundError, ValueError) as e:
        print(error(str(e)[:300], "check arguments", "ad-pbiviz"))
        sys.exit(2)


if __name__ == "__main__":
    main()
