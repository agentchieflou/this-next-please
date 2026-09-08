"""Model deployment to Power BI Premium/Fabric via Tabular Editor 2 (TE2)."""
from __future__ import annotations
import glob
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
from typing import Any, Callable

from .. import config as C
from .. import proc
from .client import FabricClient, FabricError
from .. import textio


def compute_model_sha(definition_dir: str) -> str:
    """Compute SHA256 over all .tmdl files in definition_dir sorted by path."""
    tmdl_files = sorted(glob.glob(os.path.join(definition_dir, "**", "*.tmdl"), recursive=True))
    if not tmdl_files and os.path.exists(os.path.join(definition_dir, "model.tmdl")):
        tmdl_files = [os.path.join(definition_dir, "model.tmdl")]

    h = hashlib.sha256()
    for path in tmdl_files:
        rel = textio.norm_path(os.path.relpath(path, definition_dir))
        h.update(rel.encode("utf-8"))
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def check_clean_tree(allow_dirty: bool = False, runner: Callable | None = None) -> None:
    """Refuse to run when git status --porcelain is non-empty unless allow_dirty is True."""
    if allow_dirty:
        return
    r = runner or proc.run
    try:
        rc, out, err, _ = r(["git", "status", "--porcelain"], timeout=15)
        if rc == 0 and out and out.strip():
            raise FabricError(
                "clean_tree_required",
                "git working tree has uncommitted changes. Commit or stash before deploy, or pass --allow-dirty.",
                hint="commit model edits (git commit -m '...') before deploying to service",
            )
    except FileNotFoundError:
        pass


def get_deploy_stamp(workspace: str, model: str) -> dict | None:
    """Load latest deploy stamp for workspace and model if present."""
    stamp_file = os.path.join(".agent", "out", "deploy_stamp.json")
    if os.path.exists(stamp_file):
        try:
            stamps = json.loads(open(stamp_file, encoding="utf-8").read())
            key = f"{workspace}:{model}".lower()
            return stamps.get(key)
        except Exception:
            return None
    return None


def record_deploy_stamp(workspace: str, model: str, model_sha: str, log_file: str, roles: bool = False) -> None:
    """Save deploy stamp to .agent/out/deploy-<ts>.json and deploy_stamp.json."""
    os.makedirs(os.path.join(".agent", "out"), exist_ok=True)
    ts = int(time.time())
    record = {
        "model_sha": model_sha,
        "workspace": workspace,
        "model": model,
        "timestamp": ts,
        "roles": roles,
        "log": textio.norm_path(log_file),
    }

    # Write specific timestamped record
    ts_file = os.path.join(".agent", "out", f"deploy-{ts}.json")
    with open(ts_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    # Update latest deploy_stamp.json
    stamp_file = os.path.join(".agent", "out", "deploy_stamp.json")
    stamps = {}
    if os.path.exists(stamp_file):
        try:
            stamps = json.loads(open(stamp_file, encoding="utf-8").read())
        except Exception:
            stamps = {}
    key = f"{workspace}:{model}".lower()
    stamps[key] = record
    with open(stamp_file, "w", encoding="utf-8") as f:
        json.dump(stamps, f, indent=2)


def deploy_model(
    definition_dir: str,
    workspace: str,
    model: str,
    dry_run: bool = False,
    roles: bool = False,
    allow_dirty: bool = False,
    force: bool = False,
    runner: Callable | None = None,
    te2_exe: str | None = None,
) -> dict[str, Any]:
    """Deploy model folder over XMLA via Tabular Editor 2."""
    r = runner or proc.run

    # 1. Clean tree check
    check_clean_tree(allow_dirty=allow_dirty, runner=r)

    # 2. Locate model.tmdl folder
    tmdl_dir = os.path.abspath(definition_dir)
    if os.path.exists(os.path.join(tmdl_dir, "definition", "model.tmdl")):
        tmdl_dir = os.path.join(tmdl_dir, "definition")
    elif not os.path.exists(os.path.join(tmdl_dir, "model.tmdl")):
        raise FileNotFoundError(f"no model.tmdl found in {definition_dir}")

    # 3. Model SHA and already-deployed check
    model_sha = compute_model_sha(tmdl_dir)
    if not force and not dry_run:
        last_stamp = get_deploy_stamp(workspace, model)
        if last_stamp and last_stamp.get("model_sha") == model_sha:
            return {
                "ok": True,
                "status": "already_deployed",
                "model_sha": model_sha,
                "workspace": workspace,
                "model": model,
                "message": f"model definition matches already deployed stamp (sha: {model_sha[:8]})",
            }

    # 4. Resolve TE2 and XMLA URL
    te2 = te2_exe or C.get(C.load(), "powerbi.tools.te2_exe") or proc.which("TabularEditor.exe") or "TabularEditor.exe"
    ws_quoted = urllib.parse.quote(workspace, safe="")
    xmla_url = f"powerbi://api.powerbi.com/v1.0/myorg/{ws_quoted}"

    # 5. Build command line
    base_flags = ["-S", "-C", "-O", "-E", "-W"]
    if roles:
        base_flags.extend(["-R", "-M"])

    os.makedirs(os.path.join(".agent", "out"), exist_ok=True)
    ts = int(time.time())
    log_path = os.path.abspath(os.path.join(".agent", "out", f"deploy-{ts}.log"))

    if dry_run:
        xmla_out = os.path.abspath(os.path.join(".agent", "out", f"deploy-{ts}.xmla"))
        cmd = [te2, tmdl_dir, "-X", xmla_out, *base_flags]
    else:
        cmd = [te2, tmdl_dir, "-D", xmla_url, model, *base_flags, "-P", "-Y"]

    # 6. Execute and log
    rc, out, err, _ = r(cmd, timeout=300)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Command: {' '.join(cmd)}\n")
        f.write(f"Return code: {rc}\n")
        f.write("--- STDOUT ---\n")
        f.write(out or "")
        f.write("\n--- STDERR ---\n")
        f.write(err or "")

    if rc != 0:
        # Parse error lines
        error_lines = []
        for line in (err or "" + "\n" + out or "").splitlines():
            line = line.strip()
            if any(k in line.lower() for k in ("error", "failed", "exception")):
                error_lines.append(line)
        if not error_lines:
            error_lines = [(err or out or f"exit {rc}").strip()[-200:]]

        raise FabricError(
            "deploy_failed",
            f"TE2 deploy failed (exit {rc})",
            hint="check XMLA permissions, workspace name, or view log",
            detail={"errors": error_lines, "log": textio.norm_path(log_path)},
        )

    if not dry_run:
        record_deploy_stamp(workspace, model, model_sha, log_path, roles=roles)

    return {
        "ok": True,
        "status": "preview" if dry_run else "deployed",
        "action": "dry_run" if dry_run else "deployed",
        "workspace": workspace,
        "model": model,
        "model_sha": model_sha,
        "log": textio.norm_path(log_path),
    }
