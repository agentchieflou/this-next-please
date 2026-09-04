"""CLI entrypoint for ad-pbi: Fabric item-definition transport (reports and semantic models)."""
from __future__ import annotations
import argparse
import base64
import glob
import json
import os
import sys
import tempfile

from . import toon
from .pbi.binding import verify_binding
from .pbi.client import FabricClient, FabricError
from .pbi.parts import check_vanished_parts, extract_parts_to_disk, load_model_parts, load_report_parts
from .version import add_version


def _locate_report_folder(path: str) -> tuple[str, str]:
    """Given a .pbip path or report folder, return (report_folder_path, default_report_name)."""
    p = os.path.abspath(path)
    if os.path.isfile(p) and p.endswith(".pbip"):
        base_dir = os.path.dirname(p)
        name = os.path.splitext(os.path.basename(p))[0]
        cands = glob.glob(os.path.join(base_dir, "*.Report"))
        if cands:
            return cands[0], name
        raise FileNotFoundError(f"no .Report folder found next to {p}")
    if os.path.isdir(p):
        if p.endswith(".Report"):
            name = os.path.basename(p)[:-7]
            return p, name
        cands = glob.glob(os.path.join(p, "*.Report"))
        if cands:
            name = os.path.basename(cands[0])[:-7]
            return cands[0], name
        if os.path.exists(os.path.join(p, "definition.pbir")):
            return p, os.path.basename(p)
    raise FileNotFoundError(f"could not identify a Power BI report folder from {path}")


def cmd_ls(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        items = client.list_items(ws_id, kind=args.kind)
        rows = [
            [
                it.get("id", ""),
                it.get("displayName", ""),
                it.get("kind", args.kind or "item"),
                it.get("description", "") or "",
            ]
            for it in items
        ]
        print(f"workspace: {ws_name} ({ws_id})")
        print(toon.table("items", ["id", "name", "kind", "description"], rows))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_get(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        kind = args.kind.lower()
        if kind not in ("report", "model"):
            print(toon.encode({"ok": False, "error": f"kind must be 'report' or 'model', got '{kind}'"}), file=sys.stderr)
            return 2

        item_id, item_name = client.resolve_item(ws_id, args.target, kind=kind)
        out_dir = args.out or os.path.join(".agent", "out", "def", item_name)

        if kind == "report":
            definition = client.get_report_definition(ws_id, item_id)
        else:
            definition = client.get_model_definition(ws_id, item_id)

        parts = definition.get("parts", [])
        count, total_bytes = extract_parts_to_disk(parts, out_dir)

        print(toon.encode({
            "ok": True,
            "workspace": ws_name,
            "item_id": item_id,
            "name": item_name,
            "kind": kind,
            "out": os.path.abspath(out_dir).replace("\\", "/"),
            "parts_count": count,
            "total_bytes": total_bytes,
        }))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_publish_report(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        report_dir, default_name = _locate_report_folder(args.pbip)
        report_name = args.name or default_name

        # Resolve model
        model_id, model_name = client.resolve_item(ws_id, args.model, kind="model")

        # Step 1: Binding diff against target model's TMDL
        with tempfile.TemporaryDirectory(prefix="pbi_target_model_") as tmp_model_dir:
            model_def = client.get_model_definition(ws_id, model_id)
            model_parts = model_def.get("parts", [])
            extract_parts_to_disk(model_parts, tmp_model_dir)

            is_valid, unresolved = verify_binding(report_dir, tmp_model_dir)
            if not is_valid and not args.allow_unbound:
                rows = [
                    [u.get("where", ""), u.get("entity", ""), u.get("prop", ""), u.get("reason", "")]
                    for u in unresolved
                ]
                print(toon.encode({
                    "ok": False,
                    "code": "binding_diff_failed",
                    "error": f"binding verification failed: {len(unresolved)} unresolved references against target model '{model_name}'",
                    "hint": "update report visual fields, rename model objects, or pass --allow-unbound to override",
                }), file=sys.stderr)
                print(toon.table("unresolved", ["where", "entity", "property", "reason"], rows), file=sys.stderr)
                return 1

        # Step 2: Assemble parts (rewriting definition.pbir in memory to byConnection)
        parts, paths = load_report_parts(report_dir, target_model_id=model_id)

        # Step 3: Check --dry-run (AGENTS.md rule 8)
        if args.dry_run:
            part_rows = []
            for p in parts:
                raw = base64.b64decode(p.get("payload", ""))
                part_rows.append([p["path"], len(raw)])
            print(toon.encode({
                "ok": True,
                "dry_run": True,
                "workspace": ws_name,
                "report_name": report_name,
                "target_model": f"{model_name} ({model_id})",
                "parts_count": len(parts),
                "unresolved_bindings": len(unresolved),
            }))
            print(toon.table("parts", ["path", "bytes"], part_rows))
            return 0

        # Step 4: Check if report already exists in workspace (create vs update)
        existing_id = None
        try:
            eid, _ = client.resolve_item(ws_id, report_name, kind="report")
            existing_id = eid
        except FabricError:
            existing_id = None

        if existing_id:
            # Check for vanished parts from previously saved definition if present
            prev_dir = os.path.join(".agent", "out", "def", report_name)
            vanished = check_vanished_parts(paths, prev_dir)
            for v in vanished:
                print(f"warn: part '{v}' was present in previous definition but is missing from local folder; "
                      f"Fabric updateDefinition replaces the whole definition, so this part will be deleted on the service.",
                      file=sys.stderr)

            op_id = client.update_report_definition(ws_id, existing_id, parts)
            rep_id = existing_id
            action = "updated"
        else:
            rep_id, op_id = client.create_report(ws_id, report_name, parts)
            action = "created"

        url = f"https://app.powerbi.com/groups/{ws_id}/reports/{rep_id}"
        print(toon.encode({
            "ok": True,
            "action": action,
            "workspace": ws_name,
            "report_id": rep_id,
            "name": report_name,
            "operation_id": op_id,
            "url": url,
        }))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_publish_model(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        model_dir = os.path.abspath(args.path)
        model_name = args.name or os.path.basename(model_dir.rstrip("/\\"))
        if model_name.endswith(".SemanticModel"):
            model_name = model_name[:-14]

        parts, paths = load_model_parts(model_dir)

        if args.dry_run:
            part_rows = []
            for p in parts:
                raw = base64.b64decode(p.get("payload", ""))
                part_rows.append([p["path"], len(raw)])
            print(toon.encode({
                "ok": True,
                "dry_run": True,
                "workspace": ws_name,
                "model_name": model_name,
                "parts_count": len(parts),
            }))
            print(toon.table("parts", ["path", "bytes"], part_rows))
            return 0

        existing_id = None
        try:
            eid, _ = client.resolve_item(ws_id, model_name, kind="model")
            existing_id = eid
        except FabricError:
            existing_id = None

        if existing_id:
            op_id = client.update_model_definition(ws_id, existing_id, parts)
            m_id = existing_id
            action = "updated"
        else:
            m_id, op_id = client.create_model(ws_id, model_name, parts)
            action = "created"

        print(toon.encode({
            "ok": True,
            "action": action,
            "workspace": ws_name,
            "model_id": m_id,
            "name": model_name,
            "operation_id": op_id,
        }))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_rm(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        kind = args.kind.lower()
        item_id, item_name = client.resolve_item(ws_id, args.target, kind=kind)

        if args.hard and sys.stdin.isatty() and not args.yes:
            confirm = input(f"Permanently delete {kind} '{item_name}' ({item_id}) from workspace '{ws_name}'? [y/N]: ")
            if confirm.strip().lower() not in ("y", "yes"):
                print("cancelled")
                return 0

        client.delete_item(ws_id, item_id, kind=kind)
        print(toon.encode({
            "ok": True,
            "action": "deleted",
            "workspace": ws_name,
            "item_id": item_id,
            "name": item_name,
            "kind": kind,
            "hard": bool(args.hard),
        }))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_ops(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        op_id = args.op_id
        record = client.load_operation(op_id)
        if not record:
            # Try fetching from API
            res = client.poll_operation(op_id, max_attempts=1, interval=0.1)
            print(toon.encode({"ok": True, "operation_id": op_id, "status": res.get("status", "Unknown"), "detail": res}))
            return 0

        st = record.get("status", "")
        if st in ("Running", "NotStarted"):
            res = client.poll_operation(op_id)
            print(toon.encode({"ok": True, "operation_id": op_id, "status": "Succeeded", "resumed": True, "result": res}))
        else:
            print(toon.encode({"ok": True, "operation_id": op_id, "status": st, "record": record}))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def cmd_export_png(args: argparse.Namespace) -> int:
    client = FabricClient(tenant=args.tenant)
    try:
        ws_id, ws_name = client.resolve_workspace(args.workspace)
        rep_id, rep_name = client.resolve_item(ws_id, args.target, kind="report")
        out_path = args.out or os.path.join(".agent", "out", "screenshots", f"{rep_name}_{args.page}.png")

        client.export_report_png(ws_id, rep_id, args.page, out_path)
        print(toon.encode({
            "ok": True,
            "workspace": ws_name,
            "report_id": rep_id,
            "report_name": rep_name,
            "page": args.page,
            "out": os.path.abspath(out_path).replace("\\", "/"),
        }))
        return 0
    except FabricError as e:
        print(toon.encode(e.to_dict()), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ad-pbi", description="Fabric REST item-definition transport (reports and semantic models)")
    add_version(p)
    sub = p.add_subparsers(dest="command", required=True)

    # ls
    p_ls = sub.add_parser("ls", help="list reports and models in a workspace")
    p_ls.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_ls.add_argument("--kind", "-k", choices=["report", "model"], help="filter by kind")
    p_ls.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_ls.set_defaults(func=cmd_ls)

    # get
    p_get = sub.add_parser("get", help="fetch report or model definition to disk")
    p_get.add_argument("kind", choices=["report", "model"], help="kind of item")
    p_get.add_argument("target", help="name or ID of item")
    p_get.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_get.add_argument("--out", "-o", help="destination directory (default: .agent/out/def/<name>/)")
    p_get.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_get.set_defaults(func=cmd_get)

    # publish
    p_pub = sub.add_parser("publish", help="publish report or model definition")
    sub_pub = p_pub.add_subparsers(dest="publish_command", required=True)

    # publish report
    p_pub_rep = sub_pub.add_parser("report", help="publish report to workspace")
    p_pub_rep.add_argument("pbip", help="path to .pbip file or .Report folder")
    p_pub_rep.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_pub_rep.add_argument("--model", "-m", required=True, help="target semantic model name or ID")
    p_pub_rep.add_argument("--name", "-n", help="report display name")
    p_pub_rep.add_argument("--dry-run", action="store_true", help="dry-run: binding diff and parts list only")
    p_pub_rep.add_argument("--allow-unbound", action="store_true", help="publish even if entity references are unbound")
    p_pub_rep.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_pub_rep.set_defaults(func=cmd_publish_report)

    # publish model
    p_pub_mod = sub_pub.add_parser("model", help="publish TMDL semantic model definition")
    p_pub_mod.add_argument("path", help="path to TMDL definition folder or .SemanticModel folder")
    p_pub_mod.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_pub_mod.add_argument("--name", "-n", help="model display name")
    p_pub_mod.add_argument("--dry-run", action="store_true", help="dry-run: parts list only")
    p_pub_mod.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_pub_mod.set_defaults(func=cmd_publish_model)

    # rm
    p_rm = sub.add_parser("rm", help="delete a report or semantic model")
    p_rm.add_argument("kind", choices=["report", "model"], help="kind of item")
    p_rm.add_argument("target", help="name or ID of item")
    p_rm.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_rm.add_argument("--hard", action="store_true", help="permanently delete")
    p_rm.add_argument("-y", "--yes", action="store_true", help="confirm deletion non-interactively")
    p_rm.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_rm.set_defaults(func=cmd_rm)

    # ops
    p_ops = sub.add_parser("ops", help="check status of or resume a recorded operation")
    p_ops.add_argument("op_id", help="operation ID")
    p_ops.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_ops.set_defaults(func=cmd_ops)

    # export-png
    p_png = sub.add_parser("export-png", help="export report page as PNG (stretch)")
    p_png.add_argument("target", help="report name or ID")
    p_png.add_argument("--workspace", "-w", required=True, help="workspace name or ID")
    p_png.add_argument("--page", required=True, help="page name")
    p_png.add_argument("--out", "-o", help="destination PNG path")
    p_png.add_argument("--tenant", "-t", help="Azure tenant ID")
    p_png.set_defaults(func=cmd_export_png)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
